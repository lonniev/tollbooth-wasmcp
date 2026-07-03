"""Wasm-friendly operator bootstrap: replaces the wheel's sync-websocket relay
read with an async HTTPS fetch via the bridge Worker + ops-based NIP-04 decrypt.
Monkeypatched over tollbooth.bootstrap.ensure_bootstrapped."""

import base64
import json
import os

import httpx

_REGISTRY = "https://raw.githubusercontent.com/lonniev/dpyc-community/main/members/read-only-lookup-cache.json"


def _b64(s: str) -> bytes:
    return base64.b64decode(s + "=" * (-len(s) % 4))


async def wasm_ensure_bootstrapped(relays=None):
    from tollbooth.bootstrap import BootstrapResult
    from wit_world.imports import ops
    from pynostr.key import PrivateKey, PublicKey

    nsec = os.environ.get("TOLLBOOTH_NOSTR_OPERATOR_NSEC", "")
    if not nsec:
        return BootstrapResult(success=False, error="TOLLBOOTH_NOSTR_OPERATOR_NSEC not set")

    op = PrivateKey.from_nsec(nsec)
    op_priv = op.secret
    op_pub_hex = op.public_key.hex()
    bridge = os.environ.get("BRIDGE_URL", "http://localhost:8799").rstrip("/")

    async with httpx.AsyncClient() as client:
        members = (await client.get(_REGISTRY)).json().get("members", [])
        auth_npub = None
        for m in members:
            try:
                if PublicKey.from_npub(m["npub"]).hex() == op_pub_hex:
                    auth_npub = m.get("upstream_authority_npub")
                    break
            except Exception:
                pass
        if not auth_npub:
            return BootstrapResult(success=False, error="operator not in registry (no upstream authority)")
        auth_hex = PublicKey.from_npub(auth_npub).hex()
        dtag = "dpyc-bootstrap-config:" + op_pub_hex
        ev = (await client.get(f"{bridge}/event",
                               params={"author": auth_hex, "kind": 30078, "d": dtag})).json()

    if not isinstance(ev, dict) or "content" not in ev:
        return BootstrapResult(success=False, error=f"bridge returned no config event: {ev}")

    ct_b64, iv_b64 = ev["content"].split("?iv=", 1)
    key = bytes(ops.ecdh_nip04(op_priv, bytes.fromhex(auth_hex)))
    pt = bytes(ops.aes256_cbc_decrypt(key, _b64(iv_b64), _b64(ct_b64))).decode("utf-8")
    cfg = json.loads(pt)
    config = cfg.get("config", cfg)
    return BootstrapResult(
        success=True,
        neon_database_url=config.get("neon_database_url"),
        encryption_nsec_hex=op.hex(),
        npub="",
        authority_npub=auth_npub,
        config=config,
    )
