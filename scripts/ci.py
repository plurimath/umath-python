"""Repository-native CI: public pinned native build and installed-wheel suite.

No handoff files or machine-specific paths are required. One canonical stage
cdylib supplies both model ABI v1 and the Parsanol C ABI on each platform.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import platform
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "ci/native-source.json").read_text(encoding="utf-8"))
STAGE = CONFIG["stage"]
EVIDENCE = ROOT / ".ci-evidence"
EVIDENCE.mkdir(exist_ok=True)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, label, cwd=ROOT, timeout=1200, env=None):
    start = time.monotonic()
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout, env=env)
    (EVIDENCE / (label + ".log")).write_text(result.stdout, encoding="utf-8")
    (EVIDENCE / (label + ".json")).write_text(json.dumps({
        "command": command, "exit_code": result.returncode,
        "seconds": round(time.monotonic() - start, 3),
    }, indent=2) + "\n", encoding="utf-8")
    if result.returncode:
        print(result.stdout[-6000:])
        raise RuntimeError(f"{label} exited {result.returncode}; full output in .ci-evidence")


def source_pin(config):
    repository, revision = config["repository"], config["revision"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("expected a public GitHub owner/repository")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("native public task commit must be pinned before CI can build it")
    return repository, revision


def library_name():
    if sys.platform == "win32":
        return STAGE + ".dll"
    return "lib" + STAGE + (".dylib" if sys.platform == "darwin" else ".so")


def build_native():
    repository, revision = source_pin(CONFIG)
    source = ROOT / ".native-source"
    source.mkdir(exist_ok=False)
    run(["git", "init", str(source)], "native-init")
    run(["git", "config", "core.autocrlf", "false"], "native-lf", source)
    run(["git", "remote", "add", "origin", f"https://github.com/{repository}.git"], "native-origin", source)
    run(["git", "fetch", "--depth", "1", "origin", revision], "native-fetch", source)
    run(["git", "checkout", "--detach", "FETCH_HEAD"], "native-checkout", source)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if actual != revision:
        raise RuntimeError("native checkout does not match the pinned task commit")
    environment = os.environ.copy()
    if sys.platform == "darwin":
        deployment = ".".join(platform.mac_ver()[0].split(".")[:2])
        environment["MACOSX_DEPLOYMENT_TARGET"] = deployment
    else:
        deployment = None
    run(["cargo", "build", "--locked", "--release", "--features", "ffi", "--lib"], "native-build", source, env=environment)
    binary = source / "target/release" / library_name()
    output = ROOT / ".native"
    output.mkdir(exist_ok=True)
    shutil.copyfile(binary, output / binary.name)
    tag = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    if deployment:
        tag = "macosx_" + deployment.replace(".", "_") + "_" + platform.machine()
    info = {
        "repository": repository, "revision": revision, "platform": sys.platform,
        "architecture": platform.machine(), "library": binary.name, "sha256": digest(binary),
        "cargo_lock_sha256": digest(source / "Cargo.lock"), "wheel_platform_tag": tag,
        "macos_deployment_target": deployment, "source_revision_verified_for_this_binary": True,
    }
    if sys.platform == "linux":
        symbols = subprocess.check_output(["readelf", "--version-info", str(binary)], text=True)
        versions = set(re.findall(r"GLIBC_(\d+\.\d+)", symbols))
        info["glibc_required"] = max(versions, key=lambda value: tuple(map(int, value.split(".")))) if versions else None
    licenses = output / "licenses"
    licenses.mkdir(exist_ok=True)
    metadata = json.loads(subprocess.check_output(["cargo", "metadata", "--locked", "--format-version", "1", "--features", "ffi"], cwd=source, env=environment, text=True))
    notices = []
    for package in metadata["packages"]:
        directory = Path(package["manifest_path"]).parent
        candidates = [p for p in directory.iterdir() if p.is_file() and p.name.lower().startswith(("license", "copying", "notice"))]
        if package.get("license_file"):
            candidates.append(directory / package["license_file"])
        copied = {}
        for notice in set(candidates):
            if notice.is_file():
                target = licenses / (package["name"] + "-" + package["version"]) / notice.name
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(notice, target)
                copied[notice.name] = digest(notice)
        notices.append({"package": package["name"], "version": package["version"], "license": package.get("license"), "notice_files": copied})
    (licenses / "manifest.json").write_text(json.dumps(notices, indent=2) + "\n", encoding="utf-8")
    (output / "build-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(f"Built one pinned canonical {STAGE} library for platform wheel {tag}")



def install_wheel(runtime_installed):
    if not runtime_installed:
        repository, revision = source_pin(CONFIG["python_runtime"])
        run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
             f"parsanol @ git+https://github.com/{repository}.git@{revision}"], "runtime-install")
    else:
        from parsanol import NativeContext
        if not callable(NativeContext):
            raise RuntimeError("the local shortcut requires the actual explicit-context candidate")
    command = [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", "dist", "."]
    if runtime_installed:
        command.insert(4, "--no-build-isolation")
    run(command, "wheel-build")
    expected = "latexmath" if STAGE == "latexmath" else "plurimath_" + STAGE
    wheels = [p for p in (ROOT / "dist").glob(expected + "-*.whl") if not p.name.endswith("-any.whl")]
    if len(wheels) != 1:
        raise RuntimeError("expected one platform-tagged wheel in dist")
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()
        binaries = [p for p in members if p.endswith((".so", ".dylib", ".dll"))]
        if binaries != [STAGE + "/_native/" + library_name()]:
            raise RuntimeError("the platform wheel must carry exactly one canonical native library")
        metadata = archive.read(next(p for p in members if p.endswith(".dist-info/WHEEL"))).decode()
        if "Root-Is-Purelib: false" not in metadata or "Tag: py3-none-" not in metadata:
            raise RuntimeError("native C ABI payload requires an honest py3-none platform tag")
        if not any(p.endswith("/LICENSE") for p in members):
            raise RuntimeError("upstream license missing from platform wheel")
        native_info = json.loads(archive.read(STAGE + "/_native/build-info.json"))
        if hashlib.sha256(archive.read(binaries[0])).hexdigest() != native_info["sha256"]:
            raise RuntimeError("wheel native payload checksum mismatch")
    run([sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", str(wheel)], "wheel-install")
    run([sys.executable, "-m", "pip", "check"], "dependency-check")
    (EVIDENCE / "wheel.json").write_text(json.dumps({
        "wheel": wheel.name, "sha256": digest(wheel), "native_binary_count": 1,
        "native_payload_sha256": native_info["sha256"], "wheel_metadata": metadata,
    }, indent=2) + "\n", encoding="utf-8")



def test_installed(library):
    # This is the verification harness, not the runtime loader. The default
    # qualification deliberately removes overrides to prove fresh-install use.
    if library:
        native = str(Path(library).resolve())
        os.environ[STAGE.upper() + "_MODEL_CDYLIB"] = native
        os.environ["PARSANOL_CDYLIB"] = native
    else:
        os.environ.pop(STAGE.upper() + "_MODEL_CDYLIB", None)
        os.environ.pop("PARSANOL_CDYLIB", None)
    package = importlib.import_module(STAGE)
    if Path(package.__file__).resolve().is_relative_to(ROOT / "src"):
        raise RuntimeError("CI must exercise an installed wheel, not the source checkout")
    native_module = importlib.import_module(STAGE + ".native_library")
    bundled = native_module.packaged_library_path()
    if not bundled:
        raise RuntimeError("the installed platform wheel has no native payload")
    provenance = json.loads((ROOT / "tests/fixtures-provenance.json").read_text(encoding="utf-8"))
    for boundary in ["raw", "model"]:
        if provenance[boundary]["sha256"] != digest(ROOT / "tests" / (boundary + "-cases.json")):
            raise RuntimeError("a pinned fixture changed without provenance")
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    with (EVIDENCE / "tests.log").open("w", encoding="utf-8") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    from parsanol import _ffi
    if not library and _ffi._lib is not None:
        raise RuntimeError("bundled raw parsing unexpectedly changed the framework default singleton")
    context = package._artifacts()[0].native_context
    report = {
        "python": sys.version, "package": str(Path(package.__file__).resolve()),
        "native_library_sha256": digest(bundled), "native_engine": context.engine_version(),
        "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "native_overrides_unset": not bool(library),
        "framework_default_singleton_untouched": _ffi._lib is None,
        "model_fixtures": len(json.loads((ROOT / "tests/model-cases.json").read_text(encoding="utf-8"))),
        "raw_fixtures": len(json.loads((ROOT / "tests/raw-cases.json").read_text(encoding="utf-8"))),
    }
    (EVIDENCE / "tests.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    if not result.wasSuccessful() or result.skipped or not result.testsRun:
        print((EVIDENCE / "tests.log").read_text(encoding="utf-8")[-6000:])
        raise RuntimeError("installed-wheel suite failed or skipped native checks")



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["build-native", "install-wheel", "test-installed"])
    parser.add_argument("--library", help="explicit existing platform library for local validation")
    parser.add_argument("--runtime-installed", action="store_true", help="reuse the already pinned local Python runtime")
    args = parser.parse_args()
    if args.command == "build-native": build_native()
    elif args.command == "install-wheel": install_wheel(args.runtime_installed)
    else: test_installed(args.library)

if __name__ == "__main__": main()
