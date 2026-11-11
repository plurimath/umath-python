# umath Python

Local Python runtime for the authoritative umath PARG artifact. Python 3.10+.

```python
import umath
result = umath.parse_raw("x+1")
print(result.bindings)
```

Platform wheels carry one canonical Rust library for both raw parsing and
model JSON. Native discovery is automatic; environment variables are optional
overrides. These local candidates require the explicit-context Parsanol source
revision pinned in `pyproject.toml`. Delivery of that unreleased upstream source
is still gated; it is not presented as an existing PyPI release.

Source builds require Git, Cargo/Rust 1.95, and the pinned public native source:
run `python scripts/ci.py build-native` before building the Python wheel. No
compiler or global package is installed automatically.

`parse_raw(source, decimal=".")` preprocesses caller text and returns a
`RawParseResult` with source, grammar text, shape, declared bindings and label.
Its `.tree` property inverts the committed normalization wrapper table into
the legacy raw tree. Slice leaves retain `{offset,length,line,column,value}`
wires; offsets are UTF-8 bytes and lengths count Unicode characters in grammar input.
`parse_grammar(text, decimal=".")` consumes already-normalized grammar input.
Decimal markers `.`, `,` and `٫` select the shared artifact entry.
`ParseError` extends `ParseFailed`: `.wire` preserves the native failure;
`.byte_offset`/`.char_offset` locate the failure in caller input and
`.grammar_byte_offset`/`.grammar_char_offset` locate it in `.grammar_input`.
`parse_grammar` reports direct grammar positions. Source relocation follows
the stage SourceMap and fails closed when it cannot reproduce preprocessing. Invalid arguments raise `TypeError`/`ValueError`;
missing native libraries raise `ParsanolError`.

This is the raw syntax boundary. Normalization wrappers remain in
shape/bindings and are inverted by `.tree`. There is no `parse` alias claiming
Ruby's typed model contract, model construction, serializer, or writer parity.
AsciiMath uses the legacy dialect only; PMA semantic validation is not exposed.
`artifact_info()` records exact upstream source and dependency pins.

The bundled parse artifact and declared Python binding artifact are checksum
verified by Parsanol on load, including binding source pairing on application.

The existing native JSON wire sorts object members, so Python cannot recover
the Ruby Hash insertion order from that wire. List order and slice metadata
are retained. This is a known ABI limitation, separate from wrapper inversion.

## Canonical model JSON

`umath.parse_model_json(source, decimal=".")` returns a Python dict containing
the JSON emitted by the canonical Rust stage and upstream LutaML codecs. The platform wheel automatically loads its canonical library, which exports
both model ABI version 1 and the Parsanol raw C ABI. Set `UMATH_MODEL_CDYLIB`
to override the model library, or `PARSANOL_CDYLIB` to override the raw context.
Overrides remain explicit and no process-wide environment/default loader is
changed by autodiscovery.

`ModelParseError.error` preserves the native error payload; native offsets
refer to preprocessed input and use the native farthest-failure reporter.
`ModelRuntimeUnavailable` reports a missing library, wrong ABI version, or
invalid response. Inputs are borrowed for the call and every owned native
JSON result is freed once, including decoding failures.

This is portable model JSON, not generated Python classes. The upstream
serializer's empty/nil omission policy is retained; lossless or idempotent
model serialization is not claimed.

## Verification

CI builds the public Rust task commit pinned in `ci/native-source.json` once
per Linux, macOS, and Windows platform. That library supplies both ABIs. The
installed-wheel suite runs all committed model and raw fixtures on Python
3.10–3.15 on Linux and the latest matrix version on macOS/Windows.

```sh
python scripts/ci.py build-native
python scripts/ci.py install-wheel
python scripts/ci.py test-installed
```

For an existing compatible platform library, use
`python scripts/ci.py test-installed --library /absolute/path/to/library`.
The runner rejects missing native dependencies, source-checkout imports,
changed fixture digests, and skipped native tests. Full command logs and
measured results are saved under `.ci-evidence/`. Fixture origins and the two
known AsciiMath native reporter differences are recorded with the tests.

Native wheels are tagged `py3-none` with their actual platform. Linux builds
use `linux_*` tags and record their native requirements; no manylinux promise
is inferred. macOS builds use an explicit deployment target and one
architecture, not a universal claim. Native source pins, binary hashes, and
license notices are shipped under `_native/`. The installed-wheel runner
clears both library overrides and verifies both APIs still work without
changing Parsanol's default native singleton.

`parse_legacy_raw(source, decimal=".")` exposes the explicit legacy stage policy;
existing `parse_raw`, `parse_grammar` and model JSON APIs retain native strict
behavior. Tree slices refer to preprocessed text; public error offsets refer to
the original caller input, with `grammar_byte_offset` separately available.
UnicodeMath explicitly selects Parslet execution.

The new policy ABI requires the unreleased Parsanol Python/core candidates.
Their exact local wheel/source receipts are required for local testing until
the Python dependency has an approved public source location. This branch does
not claim that the new dependency is released or publicly resolvable.

Native parser budget aborts remain distinct: raw compatibility calls raise
`parsanol.NativeResourceError`; model JSON calls raise `ModelResourceError`
with the native category and depth fields. Codec `model_error` refusals remain
`ModelParseError`; they are not classified from message text.
