"""Shared-PARG raw syntax boundary; typed language models are not provided."""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import json
from parsanol import PargArtifact, BindingsArtifact, ParseFailed, ParsanolError
from .preprocessor import preprocess
from .legacy import legacy_tree
from .errors import ParseError
from .native_library import raw_library_path
from .model_bridge import parse_model_json, ModelParseError, ModelResourceError, ModelRuntimeUnavailable

__version__ = "0.1.0"
DECIMAL_ENTRIES = {".": "dot", ",": "comma", "٫": "arabic"}

@dataclass(frozen=True)
class RawParseResult:
    """Normalized grammar shape and declared bindings, not a typed model.

    Slice offsets are UTF-8 byte offsets in ``text`` after preprocessing.
    ``bindings`` preserves the names and shape of the authoritative artifact.
    """
    source: str
    text: str | None
    decimal: str
    entry: str
    shape: object
    bindings: dict
    label: str | None = None
    labeled: bool = False

    @property
    def tree(self):
        """Legacy raw tree values; native JSON object member order is retained.

        Lists and slice metadata are preserved. Ruby Hash insertion order
        cannot be reconstructed from the native JSON wire."""
        return legacy_tree(self.bindings.get("umath_tree"))

@lru_cache(maxsize=1)
def _artifacts():
    assets = files(__package__).joinpath("artifacts")
    artifact = PargArtifact(assets.joinpath("umath.json").read_text(encoding="utf-8"), library_path=raw_library_path())
    bindings = BindingsArtifact.from_json(assets.joinpath("umath.bindings.python.json").read_text(encoding="utf-8"), expected_target="python")
    return artifact, bindings

def artifact_info() -> dict:
    """Return packaged source pins without requiring a native library."""
    return json.loads(files(__package__).joinpath("artifacts/source-pins.json").read_text(encoding="utf-8"))

def _validate(source, decimal):
    if not isinstance(source, str):
        raise TypeError("input must be a str")
    source.encode("utf-8")
    if "\x00" in source:
        raise ValueError("input must not contain NUL (C ABI string boundary)")
    if decimal not in DECIMAL_ENTRIES:
        raise ValueError("unsupported decimal marker; expected '.', ',' or '٫'")
    return DECIMAL_ENTRIES[decimal]

def parse_grammar(text: str, *, decimal: str = ".") -> RawParseResult:
    """Parse already-normalized grammar input without preprocessing.

    Executes the official Parsanol native runtime and Python bindings. Does
    not unwrap normalized captures or construct typed language models.
    """
    entry = _validate(text, decimal)
    artifact, declared = _artifacts()
    try:
        shape = artifact.parse(text, entry)
    except ParseFailed as error:
        raise ParseError(error, text, text, relocate=False) from error
    bound = declared.apply(artifact.envelope, entry, shape)
    return RawParseResult(text, text, decimal, entry, shape, bound)

def parse_raw(source: str, *, decimal: str = ".") -> RawParseResult:
    """Preprocess caller input, then parse at the normalized syntax boundary."""
    entry = _validate(source, decimal)
    text, label, labeled = preprocess(source)
    if text is None:
        return RawParseResult(source, None, decimal, entry, None, {}, label, labeled)
    try:
        result = parse_grammar(text, decimal=decimal)
    except ParseFailed as error:
        raise ParseError(error, source, text) from error
    return RawParseResult(source, text, decimal, entry, result.shape, result.bindings, label, labeled)

def parse_legacy_raw(source: str, *, decimal: str = ".") -> RawParseResult:
    """Explicit legacy stage policy with source-aware rejection offsets.

    Existing parse_raw/parse_grammar remain native strict. Tree slice offsets
    refer to preprocessed text; ParseError offsets refer to the caller input.
    Requires a native engine exposing the explicit compatibility ABI.
    """
    entry = _validate(source, decimal)
    text, label, labeled = preprocess(source)
    if text is None:
        return RawParseResult(source, None, decimal, entry, None, {}, label, labeled)
    artifact, declared = _artifacts()
    if not callable(getattr(artifact, "parse_with_compatibility", None)):
        raise ParsanolError("legacy parsing requires a Parsanol Python runtime with explicit parsing compatibility")
    try:
        shape = artifact.parse_with_compatibility(text, entry, compatibility="parslet")
    except ParseFailed as error:
        raise ParseError(error, source, text) from error
    bound = declared.apply(artifact.envelope, entry, shape)
    return RawParseResult(source, text, decimal, entry, shape, bound, label, labeled)

__all__ = ["parse_legacy_raw", "parse_model_json", "ModelParseError", "ModelResourceError", "ModelRuntimeUnavailable", "parse_raw", "parse_grammar", "artifact_info", "RawParseResult", "ParseFailed", "ParseError", "ParsanolError", "DECIMAL_ENTRIES"]
