"""Native rejection with explicit caller and normalized grammar positions."""
from parsanol import ParseFailed
from .source_map import caller_position

class ParseError(ParseFailed):
    """Failure from the shared native grammar.

    Native ``wire`` is preserved unchanged. Public offsets refer to caller
    input after source relocation; grammar offsets remain separately visible.
    """
    def __init__(self, failure, source, text, *, relocate=True):
        super().__init__(failure.wire)
        self.input = source
        self.grammar_input = text
        self.grammar_byte_offset = self.wire.get("offset")
        self.grammar_char_offset = (len(text.encode("utf-8")[:self.grammar_byte_offset].decode("utf-8", errors="replace")) if self.grammar_byte_offset is not None else None)
        self.char_offset, self.byte_offset = (caller_position(source, text, self.grammar_char_offset) if relocate else (self.grammar_char_offset, self.grammar_byte_offset))
        where = (f"at character {self.char_offset} (byte {self.byte_offset})" if self.char_offset is not None else "at an unmapped position")
        self.args = (f"input rejected {where}; grammar byte {self.grammar_byte_offset}: {failure}",)
