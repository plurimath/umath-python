"""Repository-native CI: public pinned native build and installed-wheel suite.

No handoff files or machine-specific paths are required. One canonical stage
cdylib supplies both model ABI v1 and the Parsanol C ABI on each platform.
"""
from __future__ import annotations
import argparse
import ctypes
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


def macos_deployment_target(release):
    """The deployment target, and so the wheel tag, for a macOS release.

    From macOS 11 the wheel tag's minor version is always 0 (pip only
    accepts macosx_<major>_0 there), so build for <major>.0 to keep the
    binary's minimum OS and its tag in agreement.
    """
    parts = [int(part) for part in release.split(".")[:2]] + [0]
    major, minor = parts[0], parts[1]
    return f"{major}.0" if major >= 11 else f"{major}.{minor}"


def collect_notices(metadata, source, revision, licenses):
    """Preserve actual crate and Git-workspace texts, with distinct Cargo identities."""
    notices = []
    for package in metadata["packages"]:
        directory = Path(package["manifest_path"]).resolve().parent
        roots = [("", directory)]
        package_source = package.get("source")
        source_revision = None
        if package_source is None:
            if not directory.is_relative_to(source.resolve()):
                raise RuntimeError("unadmitted local native dependency")
            roots.append(("repository-", source.resolve()))
            source_revision = revision
        elif package_source.startswith("git+"):
            repository = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=directory, text=True).strip())
            source_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
            if not package_source.endswith("#" + source_revision):
                raise RuntimeError("Git notice source differs from its locked commit")
            roots.append(("repository-", repository))
        files = {}
        for prefix, path in roots:
            for candidate in path.iterdir():
                if candidate.is_file() and candidate.name.lower().startswith(("license", "copying", "notice")):
                    files.setdefault(prefix + candidate.name, candidate.read_bytes())
        if package.get("license_file"):
            path = directory / package["license_file"]
            files[path.name] = path.read_bytes()
        spdx_only = not files
        if spdx_only:
            if not package.get("license"):
                raise RuntimeError("native dependency supplies neither license text nor SPDX metadata")
            files["Cargo.toml"] = (directory / "Cargo.toml").read_bytes()
            files["SOURCE-LICENSE.json"] = (json.dumps({"license":package["license"], "source":package_source,
                "source_revision":source_revision, "notice":"Upstream supplies SPDX metadata without standalone text; none synthesized."}, indent=2) + "\n").encode()
        identity = package["id"]
        name = package["name"] + "-" + package["version"] + "-" + hashlib.sha256(identity.encode()).hexdigest()[:12]
        folder = licenses / name
        folder.mkdir()
        copied = {}
        for filename, data in sorted(files.items()):
            (folder / filename).write_bytes(data)
            copied[filename] = hashlib.sha256(data).hexdigest()
        notices.append({"package":package["name"], "version":package["version"], "cargo_id":identity,
                        "source":package_source, "source_revision":source_revision, "directory":name,
                        "license":package.get("license"), "spdx_only":spdx_only, "notice_files":copied})
    (licenses / "manifest.json").write_text(json.dumps(notices, indent=2) + "\n", encoding="utf-8")
    return notices


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
    lock_sha = digest(source / "Cargo.lock")
    if CONFIG.get("cargo_lock_sha256") and lock_sha != CONFIG["cargo_lock_sha256"]:
        raise RuntimeError("native Cargo.lock differs from the admitted source seal")
    environment = os.environ.copy()
    environment["CARGO_BUILD_JOBS"] = "1"
    if sys.platform == "darwin":
        deployment = macos_deployment_target(platform.mac_ver()[0])
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
    rustc = subprocess.check_output(["rustc", "-vV"], text=True)
    host = next(line.split(": ", 1)[1] for line in rustc.splitlines() if line.startswith("host: "))
    metadata_bytes = subprocess.check_output(["cargo", "metadata", "--locked", "--format-version", "1",
                                            "--features", "ffi", "--filter-platform", host], cwd=source, env=environment)
    (EVIDENCE / "native-cargo-metadata.json").write_bytes(metadata_bytes)
    metadata = json.loads(metadata_bytes)
    sdk = [entry for entry in metadata["packages"] if entry["name"] == "parsanol"]
    if CONFIG.get("parsanol_sdk_revision") and (len(sdk) != 1 or not (sdk[0].get("source") or "").endswith("#" + CONFIG["parsanol_sdk_revision"])):
        raise RuntimeError("Cargo resolved a different native SDK source")
    native = ctypes.CDLL(str(binary.resolve()))
    version = getattr(native, STAGE + "_abi_version")
    version.argtypes = []
    version.restype = ctypes.c_uint32
    if version() != 1:
        raise RuntimeError("canonical stage model ABI version differs")
    info.update(abi_version=1, parsanol_sdk_revision=CONFIG.get("parsanol_sdk_revision"))
    collect_notices(metadata, source, revision, licenses)
    info.update(cargo_metadata_sha256=hashlib.sha256(metadata_bytes).hexdigest(), rustc=rustc, target=host,
                source_tree=subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=source, text=True).strip(),
                build_host={"system":platform.system(),"release":platform.release(),"machine":platform.machine()})
    run(["git", "diff", "--exit-code", "HEAD", "--"], "native-source-unchanged", source)
    (output / "build-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(f"Built one pinned canonical {STAGE} library for platform wheel {tag}")



def install_wheel(runtime_installed):
    if not runtime_installed:
        if CONFIG["python_runtime"].get("public_source_available") is False:
            raise RuntimeError("explicit-context runtime source is not public yet; co-install the exact approved local candidate and use --runtime-installed")
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
        notices = json.loads(archive.read(STAGE + "/_native/licenses/manifest.json"))
        for entry in notices:
            if not entry["notice_files"]:
                raise RuntimeError("native notice entry has no attributable files")
            for filename, expected_hash in entry["notice_files"].items():
                path = STAGE + "/_native/licenses/" + entry["directory"] + "/" + filename
                if hashlib.sha256(archive.read(path)).hexdigest() != expected_hash:
                    raise RuntimeError("wheel native notice bytes disagree with the source inventory")
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
    if not library:
        for key in list(os.environ):
            if key in ("PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "RUST_MIN_STACK") or key.startswith("PARSANOL_"):
                os.environ.pop(key, None)
        if sys.platform == "win32":
            system = os.environ.get("SystemRoot", r"C:\Windows")
            os.environ["PATH"] = system + r"\System32;" + system
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
