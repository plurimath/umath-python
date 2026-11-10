# umath Python

Local Python runtime for the authoritative umath PARG artifact. Python 3.10+.

```python
import umath
result = umath.parse_raw("x+1")
print(result.bindings)
```

Install this package and `parsanol==0.1.23`. The Parsanol Python runtime
loads its native C ABI library. Set `PARSANOL_CDYLIB` to an existing compatible
`libparsanol.so`, `.dylib`, or DLL if the dependency does not vendor one.
No native build is performed by this package.

`parse_raw(source, decimal=".")` preprocesses caller text and returns a
`RawParseResult` with source, grammar text, shape, declared bindings and label.
`parse_grammar(text, decimal=".")` consumes already-normalized grammar input.
Decimal markers `.`, `,` and `٫` select the shared artifact entry.
`ParseFailed.wire` contains native failures; offsets refer to UTF-8 bytes in
normalized grammar text. Invalid arguments raise `TypeError`/`ValueError`;
missing native libraries raise `ParsanolError`.

This is the normalized raw syntax boundary. Normalization wrappers remain in
shape/bindings. There is no `parse` alias claiming Ruby's typed model contract,
legacy-tree unwrapping, model construction, serializer, or writer parity.
AsciiMath uses the legacy dialect only; PMA semantic validation is not exposed.
`artifact_info()` records exact upstream source and dependency pins.

The bundled parse artifact and declared Python binding artifact are checksum
verified by Parsanol on load, including binding source pairing on application.
