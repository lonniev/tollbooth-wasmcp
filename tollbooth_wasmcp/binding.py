"""Argument binding: filter to declared params and coerce JSON scalars to their
annotated types — the job FastMCP does with pydantic at the Horizon edge.

The raw wasmcp transport hands us JSON as-is, so `days="30"` reaches an `int`
param and blows up (e.g. `timedelta(days="30")`). This mirrors pydantic's lenient
scalar coercion using only the standard library.
"""

import inspect
import typing


def base_scalar(ann):
    """Unwrap Annotated[T, ...] and Optional[T]/Union to the base scalar type
    (same traversal as schema.py's _json_type)."""
    origin = typing.get_origin(ann)
    if origin is typing.Annotated:
        return base_scalar(typing.get_args(ann)[0])
    if origin is typing.Union:
        for a in typing.get_args(ann):
            if a is not type(None):
                return base_scalar(a)
    return ann


def bind_args(fn, args):
    """Filter ``args`` to ``fn``'s declared params and coerce JSON scalars to the
    annotated types. Unknown fields are dropped (a client sending an extra field —
    e.g. an npub to a no-arg tool — must not crash the call)."""
    # Resolve PEP 563 string annotations (the tollbooth-dpyc wheel uses
    # `from __future__ import annotations`, so p.annotation is e.g. "int").
    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except Exception:
        hints = {}
    out = {}
    for name, p in inspect.signature(fn).parameters.items():
        if name not in args:
            continue
        v = args[name]
        t = base_scalar(hints.get(name, p.annotation))
        try:
            if t is bool and isinstance(v, str):
                v = v.strip().lower() in ("true", "1", "yes", "on")
            elif t is int and isinstance(v, str) and v.strip():
                v = int(v)
            elif t is float and isinstance(v, (str, int)):
                v = float(v)
        except (ValueError, TypeError):
            pass  # leave as-is; the tool's own validation will speak
        out[name] = v
    return out
