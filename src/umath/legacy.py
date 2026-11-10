"""Inverse of stage capture normalization and Parsanol CanFlatten algebra.

Slice wire objects stay distinct from keyed subtrees and keep UTF-8 offsets.
"""
from functools import lru_cache
from importlib.resources import files
import json
_SLICE_KEYS = {"offset", "length", "line", "column", "value"}
def is_slice(v):
    return isinstance(v, dict) and set(v) == _SLICE_KEYS

def _hash(v):
    return isinstance(v, dict) and not is_slice(v)

def _text(v):
    return isinstance(v, str) or is_slice(v)

def _join(values):
    values = [v for v in values if v is not None]
    value = "".join(v["value"] if is_slice(v) else str(v) for v in values)
    first = next((v for v in values if is_slice(v)), None)
    if first is None:
        return value
    return dict(first, value=value, length=len(value))

def merge(left, right):
    if is_slice(left) and is_slice(right):
        return _join([left, right])
    if type(left) is type(right) and not is_slice(left) and not is_slice(right):
        return {**left, **right} if _hash(left) else left + right
    if _text(left) and _text(right):
        return right if is_slice(right) else left
    if _text(right):
        return left
    if _text(left):
        return right
    if _hash(right) and isinstance(left, list):
        return left + [right]
    if _hash(left) and isinstance(right, list):
        return [left] + right
    raise ValueError("cannot merge normalized sequence parts")

def fold(parts):
    parts = [p for p in parts if p is not None]
    if not parts:
        return ""
    out = parts[0]
    for part in parts[1:]:
        out = merge(out, part)
    return out

def repetition(parts):
    if any(_hash(p) for p in parts):
        return [p for p in parts if _hash(p)]
    if any(isinstance(p, list) for p in parts):
        return [item for p in parts if isinstance(p, list) for item in p]
    return [] if not parts else _join(parts)

def _part(kind, value):
    if kind == "text":
        return "" if value is None or value == [] else value
    if kind == "empty":
        return ""
    if kind == "empty_list":
        return []
    if kind == "list":
        return "" if value == [] else value
    if kind == "nil":
        return None
    if kind == "text_list":
        return [] if value == [] or value == "" else value
    if kind == "items":
        return value
    raise ValueError(f"unknown wrapper kind {kind!r}")

@lru_cache(maxsize=1)
def wrappers():
    return json.loads(files(__package__).joinpath("artifacts/wrappers.json").read_text(encoding="utf-8"))["wrappers"]

def unwrap(tree):
    table = wrappers()
    done, todo = [], [(tree, False)]
    while todo:
        node, ready = todo.pop()
        if not (_hash(node) or isinstance(node, list)):
            done.append(node)
        elif not ready:
            todo.append((node, True))
            children = list(node.values()) if _hash(node) else node
            todo.extend((child, False) for child in reversed(children))
        else:
            count = len(node)
            values = done[-count:] if count else []
            if count:
                del done[-count:]
            if isinstance(node, list):
                done.append(repetition(values))
                continue
            rebuilt = dict(zip(node, values))
            if not any(k in table for k in rebuilt):
                done.append(rebuilt)
                continue
            parts, run, only_nil = [], {}, True
            for key, value in rebuilt.items():
                kind = table.get(key)
                if kind:
                    if run:
                        parts.append(run)
                        run = {}
                    only_nil = only_nil and kind == "nil"
                    parts.append(_part(kind, value))
                else:
                    only_nil = False
                    run[key] = value
            if run:
                parts.append(run)
            done.append(None if only_nil else fold(parts))
    return done[0]

def renest(tree):
    done, todo = [], [(tree, False)]
    while todo:
        node, ready = todo.pop()
        if not (_hash(node) or isinstance(node, list)):
            done.append(node)
        elif not ready:
            todo.append((node, True))
            children = list(node.values()) if _hash(node) else node
            todo.extend((child, False) for child in reversed(children))
        else:
            count = len(node)
            values = done[-count:] if count else []
            if count:
                del done[-count:]
            if isinstance(node, list):
                done.append(values)
            elif "amath_chain" not in node:
                done.append(dict(zip(node, values)))
            else:
                items = values[0]
                rest = items[-1].get("amath_end", "") if items and _hash(items[-1]) else ""
                nested = rest
                for item in reversed(items):
                    for key, part in item.items():
                        level = {"amath_step": "expr", "amath_lr": "left_right"}.get(key)
                        if level:
                            nested = {level: fold([part, nested])}
                done.append(next(iter(nested.values())))
    return done[0]

def legacy_tree(shape):
    if __package__ == "amath":
        if _hash(shape) and list(shape) == ["root"]:
            shape = shape["root"]
        return renest(unwrap(shape))
    result = unwrap(shape)
    if __package__ == "latexmath":
        # Ruby restores the grammar-only row_break spelling after unwrapping.
        done, todo = [], [(result, False)]
        while todo:
            node, ready = todo.pop()
            if not (_hash(node) or isinstance(node, list)):
                done.append(node)
            elif not ready:
                todo.append((node, True))
                children = list(node.values()) if _hash(node) else node
                todo.extend((c, False) for c in reversed(children))
            else:
                n = len(node)
                vals = done[-n:] if n else []
                if n: del done[-n:]
                done.append(dict(zip(("\\\\" if k == "row_break" else k for k in node), vals)) if _hash(node) else vals)
        return done[0]
    return result
