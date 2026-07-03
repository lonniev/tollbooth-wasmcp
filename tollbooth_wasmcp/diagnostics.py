"""Opt-in proof-rejection diagnostic (env ``PROOF_DEBUG``).

When a proof is rejected, enrich the ``proof_invalid`` error with WHICH sub-check
failed (u-tag binding vs expected runtime tool name, pubkey match, schnorr
signature, event age) — invaluable for debugging a client's proof binding. OFF by
default: leaking which check failed would help an attacker refine an invalid proof.

Wraps ``runtime.require_proof`` (the reference runtime.py binds at import via
``from ...identity_proof import require_proof``, so we patch the runtime module attr).
"""

import json
import os


def install_proof_diagnostic():
    import tollbooth.identity_proof as _idp
    import tollbooth.runtime as _rt_mod

    orig = _rt_mod.require_proof

    async def _require_proof_maybe_diag(npub, dpop_token, tool_name, *, proven_cache=None,
                                        window_seconds=_idp.DEFAULT_WINDOW_SECONDS):
        err = await orig(npub, dpop_token, tool_name, proven_cache=proven_cache,
                         window_seconds=window_seconds)
        if isinstance(err, dict) and err.get("error_code") == "proof_invalid" and os.environ.get("PROOF_DEBUG"):
            err["_diagnostic"] = _explain(_idp, npub, dpop_token, tool_name)
        return err

    _rt_mod.require_proof = _require_proof_maybe_diag


def _explain(_idp, npub, dpop_token, tool_name):
    d = {"expected_tool_name": tool_name}
    try:
        import hashlib
        import time
        ev = json.loads(dpop_token)
        if not isinstance(ev, dict):
            d["dpop_token_form"] = "JSON but not an event object"
            return d
        d["u_tags"] = [t[1] for t in ev.get("tags", []) if len(t) >= 2 and t[0] == "u"]
        d["event_kind"] = ev.get("kind")
        d["age_seconds"] = round(time.time() - (ev.get("created_at") or 0), 1)
        try:
            d["pubkey_matches_operator"] = ev.get("pubkey") == _idp._npub_to_hex(npub)
        except Exception as e:
            d["pubkey_check_error"] = str(e)
        ser = json.dumps([0, ev.get("pubkey"), ev.get("created_at"), ev.get("kind"),
                          ev.get("tags"), ev.get("content")], separators=(",", ":"), ensure_ascii=False)
        rid = hashlib.sha256(ser.encode()).hexdigest()
        d["id_recomputes"] = ev.get("id") == rid
        try:
            from wit_world.imports import ops
            d["sig_verifies"] = ops.schnorr_verify(bytes.fromhex(rid), bytes.fromhex(ev.get("sig", "")),
                                                   bytes.fromhex(ev.get("pubkey", "")))
        except Exception as e:
            d["sig_error"] = str(e)
    except Exception:
        d["dpop_token_form"] = "not JSON (cache-key shape?): " + repr(str(dpop_token)[:40])
    return d
