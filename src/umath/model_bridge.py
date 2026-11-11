"""Optional thin consumer of the canonical Rust stage's model JSON ABI.

This module does not construct Python LML classes. The native stage owns all
model construction and semantic validation; Python returns its portable data.
"""
from __future__ import annotations
import ctypes
from functools import lru_cache
import json
import os
from pathlib import Path
from .native_library import packaged_library_path

class ModelRuntimeUnavailable(RuntimeError):
    """The separately installed canonical stage ABI could not be loaded."""

class ModelParseError(ValueError):
    """The canonical stage rejected the input; ``error`` retains its payload."""
    def __init__(self, error):
        self.error = error
        super().__init__(str(error.get("message", "canonical model parse rejected")))

class ModelResourceError(RuntimeError):
    """A typed native parser budget abort, distinct from syntax rejection."""
    def __init__(self, error):
        self.error = error
        self.category = error["category"]
        self.depth = error.get("depth")
        self.max_depth = error.get("max_depth")
        super().__init__(str(error.get("message", self.category)))

@lru_cache(maxsize=4)
def _load(path):
    target = Path(path)
    if not target.is_absolute():
        raise ModelRuntimeUnavailable("UMATH_MODEL_CDYLIB must be an absolute library path")
    try:
        library = ctypes.CDLL(str(target))
        library.umath_abi_version.argtypes = []
        library.umath_abi_version.restype = ctypes.c_uint32
        library.umath_parse_model_json_v1.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
        library.umath_parse_model_json_v1.restype = ctypes.c_void_p
        library.umath_free_json_v1.argtypes = [ctypes.c_void_p]
        library.umath_free_json_v1.restype = None
        if library.umath_abi_version() != 1:
            raise ModelRuntimeUnavailable("unsupported umath model ABI version")
    except (OSError, AttributeError) as error:
        raise ModelRuntimeUnavailable(f"cannot load canonical umath model ABI: {error}") from error
    return library

def _library_path():
    path = os.environ.get("UMATH_MODEL_CDYLIB") or packaged_library_path()
    if not path:
        raise ModelRuntimeUnavailable("native library missing; install a platform wheel or set UMATH_MODEL_CDYLIB")
    return path

def parse_model_json(source: str, *, decimal: str = ".") -> dict:
    """Return canonical model JSON as a Python dict through ABI v1.

    The platform wheel supplies the canonical Rust stage cdylib. An absolute
    ``UMATH_MODEL_CDYLIB`` path remains an optional override. This is
    JSON model data, not Python classes.
    """
    from . import _validate
    _validate(source, decimal)
    library = _load(_library_path())
    encoded, marker = source.encode("utf-8"), decimal.encode("utf-8")
    pointer = library.umath_parse_model_json_v1(encoded, len(encoded), marker, len(marker))
    if not pointer:
        raise ModelRuntimeUnavailable("canonical umath ABI returned a null result")
    try:
        try:
            result = json.loads(ctypes.string_at(pointer).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ModelRuntimeUnavailable("invalid canonical model ABI JSON encoding") from error
    finally:
        library.umath_free_json_v1(ctypes.c_void_p(pointer))
    if not isinstance(result, dict) or result.get("abi_version") != 1:
        raise ModelRuntimeUnavailable("invalid canonical umath ABI result envelope")
    if result.get("ok") is False and isinstance(result.get("error"), dict):
        if result["error"].get("category") in ("recursion_limit", "call_depth_limit"):
            raise ModelResourceError(result["error"])
        raise ModelParseError(result["error"])
    if result.get("ok") is not True or not isinstance(result.get("model"), dict):
        raise ModelRuntimeUnavailable("invalid canonical umath model payload")
    return result["model"]
