"""httpx AsyncBaseTransport that routes over wasi:http/outgoing-handler.

This is the load-bearing shim: it lets the unmodified tollbooth wheel (which
constructs httpx.AsyncClient) issue outbound requests inside a Wasm component,
with TLS terminated by the wasi:http host. No `ssl` module is touched.
"""

import asyncio
import httpx

from tollbooth_wasmcp.poll_loop import Stream, Sink, register
from componentize_py_types import Ok
from wit_world.imports import outgoing_handler
from wit_world.imports.wasi_http_types import (
    Method_Get, Method_Post, Method_Put, Method_Delete, Method_Patch,
    Method_Head, Method_Options, Method_Other,
    Scheme_Http, Scheme_Https, Scheme_Other,
    OutgoingRequest, Fields,
)

# Headers the wasi:http host manages itself; setting them on a Fields raises
# HeaderError_Forbidden. host is conveyed via set_authority; content-length via
# the body; the rest are hop-by-hop.
_FORBIDDEN = frozenset({
    "host", "content-length", "connection", "keep-alive",
    "transfer-encoding", "upgrade", "proxy-connection", "te", "trailer",
})

_METHODS = {
    "GET": Method_Get, "POST": Method_Post, "PUT": Method_Put,
    "DELETE": Method_Delete, "PATCH": Method_Patch, "HEAD": Method_Head,
    "OPTIONS": Method_Options,
}


def _method(m: str):
    cls = _METHODS.get(m.upper())
    return cls() if cls else Method_Other(m)


def _scheme(s: str):
    if s == "https":
        return Scheme_Https()
    if s == "http":
        return Scheme_Http()
    return Scheme_Other(s)


async def _exchange(method, scheme, authority, path_with_query, headers, body):
    req = OutgoingRequest(Fields.from_list(headers))
    req.set_method(method)
    req.set_scheme(scheme)
    req.set_authority(authority)
    req.set_path_with_query(path_with_query)

    outgoing_body = req.body()
    future = outgoing_handler.handle(req, None)

    sink = Sink(outgoing_body)
    if body:
        await sink.send(body)
    sink.close()

    # Await the response future (same unwrap logic as poll_loop.send). wasi:http
    # error values are frozen dataclasses — raising them directly fails when Python
    # tries to attach __traceback__ (FrozenInstanceError masks the real cause), so
    # surface a clean httpx.ConnectError with the wasi ErrorCode repr instead.
    while True:
        response = future.get()
        if response is None:
            await register(asyncio.get_event_loop(), future.subscribe())
        else:
            if isinstance(response, Ok):
                if isinstance(response.value, Ok):
                    return response.value.value
                raise httpx.ConnectError(f"wasi:http request error: {response.value!r}")
            raise httpx.ConnectError(f"wasi:http response error: {response!r}")


class WasiHttpTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        authority = url.host
        if url.port is not None:
            authority = f"{authority}:{url.port}"

        headers = [
            (k.decode("ascii"), v) for k, v in request.headers.raw
            if k.decode("ascii").lower() not in _FORBIDDEN
        ]
        path_q = url.raw_path.decode("ascii") or "/"
        body = request.content or b""

        resp = await _exchange(
            _method(request.method), _scheme(url.scheme), authority,
            path_q, headers, body,
        )

        status = resp.status()
        resp_headers = [(k, v) for k, v in resp.headers().entries()]

        chunks = []
        stream = Stream(resp.consume())
        while True:
            chunk = await stream.next()
            if chunk is None:
                break
            chunks.append(chunk)

        return httpx.Response(
            status_code=status,
            headers=resp_headers,
            content=b"".join(chunks),
            request=request,
        )
