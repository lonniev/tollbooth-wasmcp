"""Tests for the self-contained MCP schema generator.

Proves it derives high-quality metadata from signatures + docstrings, and that it
agrees with FastMCP/pydantic on the wheel's standard tools (both read the same
docstrings) — no FastMCP or pydantic involved here.
"""

import json
import os
import sys
from typing import Annotated, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tollbooth_wasmcp.schema import tool_schema


def test_types_required_defaults_descriptions():
    async def f(a: int, b: float, c: str = "x", flag: bool = False):
        """Summary.

        Args:
            a: the a value.
            b: the b value.
        """

    s = tool_schema(f)
    assert s["type"] == "object"
    assert s["additionalProperties"] is False
    assert s["required"] == ["a", "b"]
    assert s["properties"]["a"] == {"type": "integer", "title": "A", "description": "the a value."}
    assert s["properties"]["b"]["type"] == "number"
    assert s["properties"]["c"] == {"type": "string", "title": "C", "default": "x"}
    assert s["properties"]["flag"]["type"] == "boolean"


def test_annotated_description_and_optional():

    async def f(x: Annotated[str, "an x value"] = "", y: int | None = None):
        """Doc."""

    s = tool_schema(f)
    assert s["properties"]["x"]["description"] == "an x value"
    assert s["properties"]["y"]["type"] == "integer"
    assert "required" not in s  # both have defaults


def test_both_spellings_of_an_optional_unwrap_to_the_inner_type():
    """`Optional[int]` and `int | None` must produce the SAME schema.

    They are different objects to `typing.get_origin` — `typing.Union` vs
    `types.UnionType` — and checking only the first let every PEP 604 annotation
    fall through to the "string" default. Silent and wrong in a schema an agent
    trusts: a tool wanting `5` would be sent `"5"`. Caught only because a lint
    auto-fix modernised the fixture above, taking the old spelling's coverage
    with it — so both are pinned here.
    """
    async def modern(a: int | None = None, b: str | None = None, c: float | None = None):
        """Doc."""

    async def classic(
        a: Optional[int] = None,    # noqa: UP045 — the legacy spelling IS the subject
        b: Optional[str] = None,    # noqa: UP045
        c: Optional[float] = None,  # noqa: UP045
    ):
        """Doc."""

    assert tool_schema(modern)["properties"] == tool_schema(classic)["properties"]
    assert tool_schema(modern)["properties"]["a"]["type"] == "integer"
    assert tool_schema(modern)["properties"]["c"]["type"] == "number"


def test_multiline_arg_description():
    async def f(a: str):
        """Doc.

        Args:
            a: first line
                continued second line.
        """

    assert tool_schema(f)["properties"]["a"]["description"] == "first line continued second line."


def test_parity_with_fastmcp_on_wheel_standard_tools():
    """The generator's descriptions match FastMCP's for the wheel's standard
    tools, because both parse the same docstrings."""
    from tollbooth.runtime import OperatorRuntime, register_standard_tools
    from tollbooth.tool_identity import STANDARD_IDENTITIES

    class _Shim:
        def __init__(self):
            self.registry = {}

        def tool(self, name=None, **_kw):
            def deco(fn):
                self.registry[name or fn.__name__] = fn
                return fn
            return deco

    rt = OperatorRuntime(tool_registry=dict(STANDARD_IDENTITIES), service_name="t")
    mcp = _Shim()
    register_standard_tools(mcp, "weather", rt, service_name="t", service_version="0")

    fixture_path = os.path.join(os.path.dirname(__file__), "sample_tools_catalog.json")
    with open(fixture_path) as fh:
        live = {t["name"]: t["inputSchema"] for t in json.load(fh)}

    # Content parity, modulo whitespace: FastMCP preserves the docstring's hard
    # line-wraps inside a description; this generator reflows them to single
    # spaces. The words are identical.
    def norm(d):
        return {k: (" ".join(v.split()) if v else v) for k, v in d.items()}

    for name in ("weather_check_balance", "weather_purchase_credits", "weather_check_price"):
        gen = tool_schema(mcp.registry[name])
        gen_desc = {k: v.get("description") for k, v in gen["properties"].items()}
        live_desc = {k: v.get("description") for k, v in live[name].get("properties", {}).items()}
        assert norm(gen_desc) == norm(live_desc), f"{name}: {gen_desc} != {live_desc}"


def test_wheel_future_annotations_resolve_to_json_types():
    """The tollbooth-dpyc wheel uses `from __future__ import annotations`, so a
    param annotated `int` reaches us as the string "int". tool_schema must resolve
    it (via get_type_hints) to the correct JSON type — not fall through to the
    "string" default. Otherwise a client sends a string and the wheel's
    `timedelta(days=...)` raises TypeError."""
    from tollbooth.runtime import OperatorRuntime, register_standard_tools
    from tollbooth.tool_identity import STANDARD_IDENTITIES

    class _Shim:
        def __init__(self):
            self.registry = {}

        def tool(self, name=None, **_kw):
            def deco(fn):
                self.registry[name or fn.__name__] = fn
                return fn
            return deco

    rt = OperatorRuntime(tool_registry=dict(STANDARD_IDENTITIES), service_name="t")
    mcp = _Shim()
    register_standard_tools(mcp, "weather", rt, service_name="t", service_version="0")

    days = tool_schema(mcp.registry["weather_account_statement"])["properties"]["days"]
    assert days["type"] == "integer", f"days mis-typed as {days['type']!r} (PEP 563 not resolved)"
