# umath Python

Local Python runtime for the authoritative umath PARG artifact. Python 3.10+.

```python
import umath
result = umath.parse_raw("x+1")
print(result.bindings)
```

Install `plurimath-umath` and `parsanol==0.1.23`. The Parsanol Python runtime
loads its native C ABI library. Set `PARSANOL_CDYLIB` to an existing compatible
`libparsanol.so`, `.dylib`, or DLL if the dependency does not vendor one.
No native build is performed by this package. The wheel does not contain
libparsanol; the verified local setup uses `PARSANOL_CDYLIB` pointing to the
library shipped by the installed Parsanol Ruby gem. `PARSANOL_CDYLIB` is
the environment variable supported by the Python dependency.

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
the JSON emitted by the canonical Rust stage and upstream LutaML codecs. Set
`UMATH_MODEL_CDYLIB` to the absolute path of the separately installed,
platform-specific `umath` Rust cdylib exporting model ABI version 1. The
Python wheel includes no native binary. This route does not require loading
the separate Parsanol C ABI library used by `parse_raw`.

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
