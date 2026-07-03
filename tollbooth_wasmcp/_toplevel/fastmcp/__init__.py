"""Minimal `fastmcp.Client` shim for the Wasm operator.

The tollbooth-dpyc wheel makes server-to-server MCP calls via `fastmcp.Client`
(Oracle delegation, Authority certify_credits / check_balance, cross-Authority
adoption). The full `fastmcp` package can't run in the componentize-py Wasm
interpreter, but the calls are just MCP streamable-HTTP — which rides `httpx`
(already routed over `wasi:http`). This shim speaks that protocol: initialize
(+ session id) → notifications/initialized → tools/call, parsing JSON or SSE.

Only what the wheel uses is implemented: `Client(url, auth=…)` as an async
context manager with `call_tool(name, arguments)` returning a result whose
`.content` is a list of text blocks (and `.data` the structured content, if any) —
the exact surface `OracleClient._parse_result` / `AuthorityCertifier._parse_result`
duck-type. `auth` is accepted and ignored (targets that need OAuth are out of
scope; the Oracle is free/unauthenticated and the Authority gates on the proof arg).
"""

import json

import httpx


class _TextBlock:
    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


class _Result:
    __slots__ = ("content", "data")

    def __init__(self, content, data=None):
        self.content = content
        self.data = data


class Client:
    def __init__(self, url, auth=None, **_kw):
        self._url = str(url)
        self._session_id = None
        self._http = None

    async def __aenter__(self):
        self._http = httpx.AsyncClient(timeout=30.0)
        await self._initialize()
        return self

    async def __aexit__(self, *_a):
        if self._http is not None:
            await self._http.aclose()

    async def _post(self, payload):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        r = await self._http.post(self._url, json=payload, headers=headers)
        sid = r.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        return r

    @staticmethod
    def _parse_body(r):
        """A streamable-HTTP response is either application/json or an SSE stream
        of `data: {…}` lines. Return the first JSON-RPC message object."""
        text = r.text
        if "data:" in text and ("event:" in text or text.lstrip().startswith("data:")):
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    frag = line[5:].strip()
                    if frag and frag != "[DONE]":
                        return json.loads(frag)
        return json.loads(text)

    async def _initialize(self):
        r = await self._post({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "tollbooth-wasmcp", "version": "0.1"},
            },
        })
        self._parse_body(r)  # session id captured from the header in _post
        # Best-effort; some servers 202 this, some ignore it.
        try:
            await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception:
            pass

    async def call_tool(self, name, arguments=None):
        r = await self._post({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        msg = self._parse_body(r)
        if isinstance(msg, dict) and msg.get("error"):
            raise RuntimeError(f"MCP error: {msg['error']}")
        result = (msg or {}).get("result", {}) if isinstance(msg, dict) else {}
        blocks = [
            _TextBlock(b.get("text", ""))
            for b in result.get("content", []) or []
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        structured = result.get("structuredContent")
        data = structured if isinstance(structured, dict) else None
        return _Result(blocks, data)
