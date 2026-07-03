"""Minimal pynostr Event shim: id recomputation + BIP-340 sign/verify via the
composed dpyc:crypto component. Covers the wheel's inline kind-27235 proof
verification (identity_proof.verify_proof) and the Secure Courier's DM signing
(gift wraps, seals, NIP-04 DMs) — all through the dpyc:crypto ops interface."""

import hashlib
import json


class Event:
    def __init__(self, pubkey="", kind=0, content="", created_at=0, tags=None,
                 id=None, sig=None):
        self.pubkey = pubkey
        self.kind = kind
        self.content = content
        self.created_at = created_at
        self.tags = tags or []
        self.id = id
        self.sig = sig

    @classmethod
    def from_dict(cls, d):
        return cls(
            pubkey=d.get("pubkey", ""), kind=d.get("kind", 0),
            content=d.get("content", ""), created_at=d.get("created_at", 0),
            tags=d.get("tags", []), id=d.get("id"), sig=d.get("sig"),
        )

    def compute_id(self):
        ser = json.dumps(
            [0, self.pubkey, self.created_at, self.kind, self.tags, self.content],
            separators=(",", ":"), ensure_ascii=False,
        )
        return hashlib.sha256(ser.encode("utf-8")).hexdigest()

    def to_dict(self):
        return {
            "id": self.id, "pubkey": self.pubkey, "created_at": self.created_at,
            "kind": self.kind, "tags": self.tags, "content": self.content, "sig": self.sig,
        }

    def to_message(self):
        return json.dumps(["EVENT", self.to_dict()])

    def sign(self, privkey_hex):
        """Set pubkey from the key, compute the id, and BIP-340-sign it (raw)
        via the crypto component — the counterpart to verify()."""
        from wit_world.imports import ops  # dpyc:crypto

        self.pubkey = bytes(ops.xonly_pubkey(bytes.fromhex(privkey_hex))).hex()
        self.id = self.compute_id()
        self.sig = bytes(ops.schnorr_sign(bytes.fromhex(self.id), bytes.fromhex(privkey_hex))).hex()
        return self.sig

    def verify(self):
        if not (self.id and self.sig and self.pubkey):
            return False
        if self.id != self.compute_id():
            return False
        from wit_world.imports import ops  # dpyc:crypto
        try:
            return ops.schnorr_verify(
                bytes.fromhex(self.id), bytes.fromhex(self.sig), bytes.fromhex(self.pubkey)
            )
        except Exception:
            return False
