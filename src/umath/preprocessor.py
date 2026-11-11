"""UnicodeMath stage preprocessing ported from its pinned Ruby contract."""
import re
_PROTECTED = '"replacement"'
def _protect(line):
    start, close = line.find("✎("), line.rfind(")")
    if start < 0 or close < start + 2:
        return line
    hash_at = line.find("#", start + 2)
    if hash_at < 0 or hash_at >= close:
        return line
    return line[:start] + line[start:close + 1].replace("#", _PROTECTED) + line[close + 1:]
def preprocess(source):
    text = "\n".join(_protect(line) for line in source.split("\n"))
    parts = text.split("#")
    while parts and parts[-1] == "":
        parts.pop()
    if not parts:
        return None, None, False
    formula = parts[0].replace(_PROTECTED, "#")
    labeled = len(parts) > 1
    label = parts[-1] if labeled else None
    text = "".join(f"&#x{ord(c):x};" if c in "<>'\"&" or not 0x20 <= ord(c) <= 0x7e else c for c in formula)
    text = text.replace("&#x26;", "&").replace("&#x22;", '"')
    start, close = text.find("&#x2af7;"), text.rfind("&#x2af8;")
    if start >= 0 and close >= start + len("&#x2af7;"):
        text = text[:start] + text[close + len("&#x2af8;"):]
    text = text.replace("\\\\", "\\")
    text = re.sub(r"\\u([\da-fA-F]{1,5})\w{0,5}", lambda m: f"&#x{m[1]};", text, flags=re.ASCII)
    return text.strip(" \t\r\n\v\f\0"), label, labeled
