"""Self-contained JSON Schema generation for MCP tools.

Derives an MCP `inputSchema` from a tool function's signature and docstring —
the conventional way, using only the standard library. No pydantic, no FastMCP.
Parameter descriptions come from the Google-style ``Args:`` section (the same
source FastMCP/pydantic read), so independently-generated schemas agree with them.
"""

from __future__ import annotations

import inspect
import re
import typing
from typing import Any, Callable

_JSON_PRIMITIVES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    type(None): "null",
}


def _json_type(ann: Any) -> str:
    if ann is inspect.Parameter.empty:
        return "string"
    origin = typing.get_origin(ann)
    if origin is typing.Annotated:
        return _json_type(typing.get_args(ann)[0])
    if ann in _JSON_PRIMITIVES:
        return _JSON_PRIMITIVES[ann]
    if origin in (list, tuple, set, frozenset):
        return "array"
    if origin is dict:
        return "object"
    if origin is typing.Union:
        for arg in typing.get_args(ann):
            if arg is not type(None):
                return _json_type(arg)
    return "string"


def _annotated_description(ann: Any) -> str | None:
    """A string (or ``.description``) in ``Annotated[T, ...]`` metadata."""
    if typing.get_origin(ann) is typing.Annotated:
        for meta in typing.get_args(ann)[1:]:
            if isinstance(meta, str):
                return meta
            desc = getattr(meta, "description", None)
            if isinstance(desc, str):
                return desc
    return None


_ARG_RE = re.compile(r"^(\s+)(\w+)\s*(?:\([^)]*\))?:\s*(.*)$")
_SECTIONS = {"Returns:", "Raises:", "Yields:", "Examples:", "Example:", "Note:", "Notes:"}


def _parse_arg_docs(doc: str) -> dict[str, str]:
    """Extract ``name: description`` pairs from a Google-style Args section."""
    out: dict[str, str] = {}
    if not doc:
        return out
    lines = doc.splitlines()
    i = 0
    while i < len(lines) and lines[i].strip() not in ("Args:", "Arguments:", "Parameters:"):
        i += 1
    i += 1
    current: str | None = None
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped in _SECTIONS:
            break
        m = _ARG_RE.match(line)
        if m:
            current = m.group(2)
            out[current] = m.group(3).strip()
        elif stripped and current:
            out[current] += " " + stripped
        i += 1
    return out


def _title(name: str) -> str:
    return name.replace("_", " ").title()


def tool_schema(fn: Callable) -> dict[str, Any]:
    """Build an MCP inputSchema (JSON Schema object) for a tool function."""
    sig = inspect.signature(fn)
    # Resolve PEP 563 string annotations (the tollbooth-dpyc wheel uses
    # `from __future__ import annotations`, so p.annotation is e.g. "int" — a
    # string that would otherwise fall through _json_type to "string").
    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except Exception:
        hints = {}
    arg_docs = _parse_arg_docs(inspect.getdoc(fn) or "")
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, p in sig.parameters.items():
        if name in ("self", "cls") or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        ann = hints.get(name, p.annotation)
        prop: dict[str, Any] = {"type": _json_type(ann), "title": _title(name)}
        desc = _annotated_description(ann) or arg_docs.get(name)
        if desc:
            prop["description"] = desc
        if p.default is inspect.Parameter.empty:
            required.append(name)
        else:
            prop["default"] = p.default
        properties[name] = prop
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    schema["additionalProperties"] = False
    return schema
