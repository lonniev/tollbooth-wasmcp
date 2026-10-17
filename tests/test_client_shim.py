"""The Wasm `fastmcp.Client` shim carries the bearer the wheel asks for.

A member with tollbooth-dpyc holder bearer on refuses a request with no
`Authorization` header, and the wheel's service clients ask for
`auth="anonymous"`. The shim must send it, as fastmcp does.
"""

import asyncio
import importlib.util
import json
import pathlib

import httpx

_REAL_ASYNC_CLIENT = httpx.AsyncClient
_SHIM = pathlib.Path(__file__).parent.parent / "tollbooth_wasmcp" / "_toplevel" / "fastmcp" / "__init__.py"


def _load_shim():
    spec = importlib.util.spec_from_file_location("fastmcp_shim", _SHIM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seen_headers(auth, monkeypatch):
    shim = _load_shim()
    seen = []

    def answer(request):
        seen.append(request.headers)
        body = json.loads(request.content)
        if body.get("method") == "tools/call":
            result = {"content": [{"type": "text", "text": "{}"}]}
        else:
            result = {}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id"), "result": result})

    monkeypatch.setattr(
        shim.httpx, "AsyncClient",
        lambda **kw: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(answer), **kw),
    )

    async def run():
        async with shim.Client("https://op.example/mcp", auth=auth) as client:
            await client.call_tool("x_service_status", {})

    asyncio.run(run())
    return seen


def test_a_string_auth_is_sent_as_a_bearer_on_every_request(monkeypatch):
    seen = _seen_headers("anonymous", monkeypatch)
    assert seen and all(h.get("authorization") == "Bearer anonymous" for h in seen)


def test_oauth_and_no_auth_send_no_authorization(monkeypatch):
    for auth in ("oauth", None):
        assert all("authorization" not in h for h in _seen_headers(auth, monkeypatch))
