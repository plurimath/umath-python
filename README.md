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
