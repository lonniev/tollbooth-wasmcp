"""Minimal pure-Python pynostr shim for the Wasm operator.

npub/nsec <-> hex is pure bech32 (no secp256k1). Key derivation and signing
delegate to the composed dpyc:crypto component. Event signing/schnorr issuance
(proof creation) is NOT supported here — proof issuance stays on FastMCP.
"""
