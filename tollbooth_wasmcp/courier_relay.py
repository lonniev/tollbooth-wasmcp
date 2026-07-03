"""Bridge-backed relay I/O for the Secure Courier on WASI.

The wheel's ``NostrCredentialExchange`` does relay I/O with ``websocket-client`` in
background threads (``nostr_credentials.py``) — neither exists in the componentize-py
Wasm interpreter. This reroutes its four relay primitives through the HTTPS→relay
**bridge Worker** (which holds the WSS connections, as it already does for bootstrap),
exactly the ``ensure_bootstrapped`` seam pattern one level lower. Event construction and
NIP-04/17 encryption stay in the wheel; only the relay *transport* moves.

Two WASI realities shape this:
  * ``PollLoop`` has no ``run_in_executor`` (raises), so ``asyncio.to_thread`` — which
    the courier uses to run its sync relay methods — is replaced with an in-loop shim.
  * The relay methods are therefore invoked synchronously, so each drives its bridge
    call to completion on a nested ``PollLoop`` (``_run_sync``), restoring the running
    loop afterward. httpx already rides ``wasi:http``.
"""

import json
import os
from urllib.parse import urlsplit


def _bridge_url():
    url = os.environ.get("BRIDGE_URL")
    if not url:
        raise RuntimeError("BRIDGE_URL not set — courier relay bridge unavailable")
    return url.rstrip("/")


def _bridge_post(path, body_obj):
    """Synchronous JSON POST over wasi:http, blocking on wasi:io/poll.

    The courier's relay methods are synchronous (invoked via the in-loop to_thread),
    so we can't await httpx here — and a nested asyncio loop trips its task-reentrancy
    guard. Instead this drives wasi:http directly with blocking poll (mirroring
    transport.py's async _exchange), returning the parsed JSON. Blocking the single
    Wasm thread for a short bridge round-trip is fine — nothing else can run anyway."""
    from componentize_py_types import Err, Ok
    from wit_world.imports import outgoing_handler, poll
    from wit_world.imports.streams import StreamError_Closed
    from wit_world.imports.wasi_http_types import (
        Fields, IncomingBody, Method_Post, OutgoingBody, OutgoingRequest,
        Scheme_Http, Scheme_Https,
    )

    body_bytes = json.dumps(body_obj).encode("utf-8")
    u = urlsplit(_bridge_url() + path)
    scheme = Scheme_Https() if u.scheme == "https" else Scheme_Http()
    path_q = (u.path or "/") + (f"?{u.query}" if u.query else "")

    req = OutgoingRequest(Fields.from_list([("content-type", b"application/json")]))
    req.set_method(Method_Post())
    req.set_scheme(scheme)
    req.set_authority(u.netloc)
    req.set_path_with_query(path_q)

    def _block(pollable):
        # Poll one pollable to readiness and release it (a Pollable is a child
        # resource; leaking them trips the component model's "resource has children").
        poll.poll([pollable])
        pollable.__exit__(None, None, None)

    out_body = req.body()
    future = outgoing_handler.handle(req, None)

    # Write the request body with blocking backpressure, then finish the body.
    out = out_body.write()
    offset = 0
    while offset < len(body_bytes):
        count = out.check_write()
        if count == 0:
            _block(out.subscribe())
            continue
        n = min(count, len(body_bytes) - offset)
        out.write(body_bytes[offset:offset + n])
        offset += n
    out.flush()
    while out.check_write() == 0:
        _block(out.subscribe())
    out.__exit__(None, None, None)          # drop the write stream before finishing
    OutgoingBody.finish(out_body, None)

    # Block for the response.
    while True:
        response = future.get()
        if response is None:
            _block(future.subscribe())
            continue
        if isinstance(response, Ok) and isinstance(response.value, Ok):
            resp = response.value.value
            break
        raise RuntimeError(f"bridge request failed: {response}")

    # Read the response body to EOF, then release stream-before-body (as Stream.next).
    incoming = resp.consume()
    stream = incoming.stream()
    chunks = []
    while True:
        try:
            buf = stream.read(16384)
            if len(buf) == 0:
                _block(stream.subscribe())
            else:
                chunks.append(bytes(buf))
        except Err as e:
            if isinstance(e.value, StreamError_Closed):
                stream.__exit__(None, None, None)
                IncomingBody.finish(incoming)
                break
            raise
    return json.loads(b"".join(chunks))


def _publish(event, relays=None):
    body = {"event": event}
    if relays:
        body["relays"] = relays
    return _bridge_post("/publish", body)


def _query(filters, relays=None, limit=None):
    body = {"filters": filters}
    if relays:
        body["relays"] = relays
    if limit:
        body["limit"] = limit
    return _bridge_post("/req", body)


# --- the four relay primitives, bound onto NostrCredentialExchange -------------
# Signatures + return shapes mirror the wheel's create_connection versions exactly.

def _publish_to_relays(self, message):
    """message is ``json.dumps(["EVENT", event])`` → publish to all relays."""
    event = json.loads(message)[1]
    try:
        res = _publish(event, list(self._relays))
    except Exception as e:  # noqa: BLE001 — surface as per-relay failure, never raise
        return [(r, False, str(e)) for r in self._relays]
    return [(row[0], bool(row[1]), str(row[2])) for row in res.get("results", [])]


def _publish_to_one_relay(self, message, relay_url):
    event = json.loads(message)[1]
    try:
        res = _publish(event, [relay_url])
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    for row in res.get("results", []):
        if row[0] == relay_url:
            return bool(row[1]), str(row[2])
    return bool(res.get("accepted")), "published"


def _subscribe_one_relay(self, relay_url, sub_id, filters):
    """Query one relay and append matching events to the shared buffer that
    ``_find_dm_candidates`` / ``_pop_event`` read."""
    if isinstance(filters, dict):
        filters = [filters]
    try:
        res = _query(filters, [relay_url])
    except Exception:  # noqa: BLE001 — a dead relay must not break the drain
        return
    events = res.get("events", [])
    with self._lock:
        self._received_events.extend(events)


def _query_one_relay_has_event(self, relay_url, sub_id, filt):
    try:
        res = _query([filt], [relay_url], limit=1)
    except Exception:  # noqa: BLE001
        return False
    return len(res.get("events", [])) > 0


def install():
    """Monkeypatch the wheel's relay primitives onto the exchange, wire the WASI
    NIP-44 implementation, and make ``asyncio.to_thread`` run in-loop (PollLoop
    has no executor)."""
    import asyncio
    import sys

    from tollbooth import nostr_credentials as nc

    from tollbooth_wasmcp import nip04_wasm, nip44_wasm

    nc.NostrCredentialExchange._publish_to_relays = _publish_to_relays
    nc.NostrCredentialExchange._publish_to_one_relay = _publish_to_one_relay
    nc.NostrCredentialExchange._subscribe_one_relay = _subscribe_one_relay
    nc.NostrCredentialExchange._query_one_relay_has_event = _query_one_relay_has_event

    # The wheel's tollbooth.nip44 / tollbooth.nip04 fail to import under WASI
    # (coincurve + cryptography are native), so _HAS_NIP44/_HAS_NIP04 are False —
    # outbound DMs are refused and vault encryption of the courier's __pending__
    # channel record raises. Supply the component-backed ports and flip the flags.
    # Register them as the module names too, for the wheel's lazy re-imports
    # (send_dm's nip04 encrypt, the audit publisher, bootstrap_relay).
    nc._nip44_encrypt = nip44_wasm.encrypt
    nc._nip44_decrypt = nip44_wasm.decrypt
    nc._HAS_NIP44 = True
    nc._nip04_decrypt = nip04_wasm.decrypt
    nc._HAS_NIP04 = True
    sys.modules.setdefault("tollbooth.nip44", nip44_wasm)
    sys.modules.setdefault("tollbooth.nip04", nip04_wasm)

    async def _to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    asyncio.to_thread = _to_thread
