"""Discover this distribution's single platform-native library without global mutation."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sys
from parsanol import ParsanolError

@lru_cache(maxsize=1)
def packaged_library_path():
    directory = Path(__file__).resolve().parent / "_native"
    manifest = directory / "build-info.json"
    if not manifest.is_file():
        return None
    info = json.loads(manifest.read_text(encoding="utf-8"))
    filename = info["library"]
    if Path(filename).name != filename or info["platform"] != sys.platform:
        raise ParsanolError("bundled native artifact platform or filename mismatch")
    path = directory / filename
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != info["sha256"]:
        raise ParsanolError("bundled native artifact checksum mismatch")
    return str(path)


def raw_library_path():
    return os.environ.get("PARSANOL_CDYLIB") or packaged_library_path()
