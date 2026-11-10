"""Character origin tracking ported from the stage Ruby SourceMap."""
import re
from .preprocessor import preprocess

def replace(text, origins, pattern, replacement):
    if isinstance(pattern, str):
        pattern = re.compile(re.escape(pattern))
    parts, mapped, pos = [], [], 0
    for match in pattern.finditer(text):
        start, end = match.span()
        piece = replacement(match) if callable(replacement) else replacement
        parts.extend([text[pos:start], piece])
        mapped.extend(origins[pos:start])
        mapped.extend([origins[start]] * len(piece))
        pos = end
    parts.append(text[pos:])
    mapped.extend(origins[pos:])
    return "".join(parts), mapped


from .preprocessor import _PROTECTED, _protect

def mapped(source):
    chars, origins, position = [], [], 0
    for index, line in enumerate(source.split("\n")):
        if index:
            chars.append("\n"); origins.append(position - 1)
        protected = _protect(line) != line
        start, close = line.find("✎("), line.rfind(")")
        for offset, char in enumerate(line):
            piece = _PROTECTED if protected and char == "#" and start < offset < close else char
            chars.extend(piece); origins.extend([position + offset] * len(piece))
        position += len(line) + 1
    text = "".join(chars)
    cut = text.find("#")
    cut = len(text) if cut < 0 else cut
    text_end = 0 if cut == 0 else None
    text, origins = replace(text[:cut], origins[:cut], _PROTECTED, "#")
    text, origins = replace(text, origins, re.compile(r"[<>'\"&]|[^\u0020-\u007e]"), lambda m: f"&#x{ord(m[0]):x};")
    text, origins = replace(text, origins, "&#x26;", "&")
    text, origins = replace(text, origins, "&#x22;", '"')
    start, close = text.find("&#x2af7;"), text.rfind("&#x2af8;")
    if start >= 0 and close >= start + len("&#x2af7;"):
        end = close + len("&#x2af8;")
        text, origins = text[:start] + text[end:], origins[:start] + origins[end:]
    text, origins = replace(text, origins, "\\\\", "\\")
    text, origins = replace(text, origins, re.compile(r"\\u([\da-fA-F]{1,5})\w{0,5}", re.ASCII), lambda m: f"&#x{m[1]};")
    stripped = text.strip(" \t\r\n\v\f\0")
    if len(stripped) != len(text):
        lead = len(text) - len(text.lstrip(" \t\r\n\v\f\0"))
        if not stripped and text_end is None:
            text_end = origins[lead] if lead < len(origins) else None
        text, origins = stripped, origins[lead:lead + len(stripped)]
    return text, origins, text_end

def caller_position(source, text, char_offset):
    scan, origins, text_end = mapped(source)
    if scan != text or char_offset is None or char_offset < 0:
        return None, None
    char = origins[char_offset] if char_offset < len(origins) else (origins[-1] + 1 if origins else text_end or 0)
    return char, len(source[:char].encode("utf-8"))
