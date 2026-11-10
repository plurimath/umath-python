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


def run(command, label, cwd=ROOT, timeout=1200):
    start = time.monotonic()
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
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
    run(["git", "remote", "add", "origin", f"https://github.com/{repository}.git"], "native-origin", source)
    run(["git", "fetch", "--depth", "1", "origin", revision], "native-fetch", source)
    run(["git", "checkout", "--detach", "FETCH_HEAD"], "native-checkout", source)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if actual != revision:
        raise RuntimeError("native checkout does not match the pinned task commit")
    run(["cargo", "build", "--locked", "--release", "--features", "ffi", "--lib"], "native-build", source)
    binary = source / "target/release" / library_name()
    output = ROOT / ".native"
    output.mkdir(exist_ok=True)
    shutil.copyfile(binary, output / binary.name)
    (output / "build-info.json").write_text(json.dumps({
        "repository": repository, "revision": revision, "platform": sys.platform,
        "library": binary.name, "sha256": digest(binary),
        "cargo_lock_sha256": digest(source / "Cargo.lock"),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Built pinned canonical {STAGE} native dependency for {sys.platform}")


def install_wheel(runtime_installed):
    if not runtime_installed:
        repository, revision = source_pin(CONFIG["python_runtime"])
        run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
             f"parsanol @ git+https://github.com/{repository}.git@{revision}"], "runtime-install")
    elif importlib.metadata.version("parsanol") != "0.1.23":
        raise RuntimeError("the local runtime shortcut requires the pinned Parsanol Python version")
    command = [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", "dist", "."]
    if runtime_installed:
        command.insert(4, "--no-build-isolation")
    run(command, "wheel-build")
    wheels = list((ROOT / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("expected one newly built wheel in dist")
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()
        if any(path.endswith((".so", ".dylib", ".dll")) for path in members):
            raise RuntimeError("a universal Python wheel must not contain native binaries")
        if not any(path.endswith("/LICENSE") for path in members):
            raise RuntimeError("the wheel is missing its upstream license")
        if not all(f"{STAGE}/artifacts/{filename}" in members for filename in ["source-pins.json", "wrappers.json"]):
            raise RuntimeError("the wheel is missing runtime assets")
    run([sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", str(wheel)], "wheel-install")
    run([sys.executable, "-m", "pip", "check"], "dependency-check")
    (EVIDENCE / "wheel.json").write_text(json.dumps({
        "wheel": wheel.name, "sha256": digest(wheel), "native_binary_count": 0,
    }, indent=2) + "\n", encoding="utf-8")


def test_installed(library):
    native = Path(library).resolve() if library else ROOT / ".native" / library_name()
    if not native.is_file():
        raise RuntimeError("the real canonical native library is required; tests cannot be skipped")
    native = native.resolve()
    os.environ[STAGE.upper() + "_MODEL_CDYLIB"] = str(native)
    os.environ["PARSANOL_CDYLIB"] = str(native)
    if not library:
        info = json.loads((ROOT / ".native/build-info.json").read_text(encoding="utf-8"))
        if info["sha256"] != digest(native) or info["revision"] != CONFIG["revision"]:
            raise RuntimeError("native artifact checksum or source revision mismatch")
    package = importlib.import_module(STAGE)
    if Path(package.__file__).resolve().is_relative_to(ROOT / "src"):
        raise RuntimeError("CI must exercise an installed wheel, not the source checkout")
    provenance = json.loads((ROOT / "tests/fixtures-provenance.json").read_text(encoding="utf-8"))
    for boundary in ["raw", "model"]:
        if provenance[boundary]["sha256"] != digest(ROOT / "tests" / (boundary + "-cases.json")):
            raise RuntimeError("a pinned native fixture changed without its provenance")
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    with (EVIDENCE / "tests.log").open("w", encoding="utf-8") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    import parsanol
    report = {
        "python": sys.version, "package": str(Path(package.__file__).resolve()),
        "native_library_sha256": digest(native), "native_engine": parsanol.engine_version(),
        "tests": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "skipped": len(result.skipped),
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
