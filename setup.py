"""Build a platform wheel containing one already-built canonical C ABI library."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import sysconfig
from setuptools import setup, Distribution
from setuptools.command.build_py import build_py
from wheel.bdist_wheel import bdist_wheel

ROOT = Path(__file__).resolve().parent
STAGE = json.loads((ROOT / "ci/native-source.json").read_text(encoding="utf-8"))["stage"]

def native_info():
    directory = ROOT / ".native"
    manifest = directory / "build-info.json"
    if not manifest.is_file():
        raise RuntimeError("canonical native dependency missing; run python scripts/ci.py build-native before building a wheel")
    info = json.loads(manifest.read_text(encoding="utf-8"))
    filename = info["library"]
    if Path(filename).name != filename or info["platform"] != sys.platform:
        raise RuntimeError("native payload does not match the build platform")
    tag = info["wheel_platform_tag"]
    expected = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    if tag == "any" or (sys.platform != "darwin" and tag != expected) or (sys.platform == "darwin" and not tag.startswith("macosx_")):
        raise RuntimeError("native payload requires a matching platform tag; universal/manylinux claims are not inferred")
    if sys.platform == "linux" and not tag.startswith("linux_"):
        raise RuntimeError("manylinux compatibility is not asserted by this build")
    if sys.platform == "darwin" and not tag.endswith("_" + __import__("platform").machine()):
        raise RuntimeError("a single-architecture native library cannot be tagged universal")
    binaries = [p for p in directory.rglob("*") if p.suffix in (".so", ".dll", ".dylib")]
    binary = directory / filename
    if binaries != [binary]:
        raise RuntimeError("exactly one canonical native library is required")
    if hashlib.sha256(binary.read_bytes()).hexdigest() != info["sha256"]:
        raise RuntimeError("native payload checksum mismatch")
    return directory, info

class NativeBuild(build_py):
    def run(self):
        directory, info = native_info()
        super().run()
        target = Path(self.build_lib) / STAGE / "_native"
        target.mkdir(parents=True, exist_ok=True)
        for path in directory.rglob("*"):
            if path.is_file():
                output = target / path.relative_to(directory)
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, output)

class NativeDistribution(Distribution):
    def has_ext_modules(self):
        return True

class PlatformWheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False
    def get_tag(self):
        _, info = native_info()
        # ctypes uses the stable C ABI, not a CPython extension ABI.
        # Linux remains linux_*; no manylinux compatibility is asserted.
        return "py3", "none", info["wheel_platform_tag"]

setup(distclass=NativeDistribution, cmdclass={"build_py": NativeBuild, "bdist_wheel": PlatformWheel})
