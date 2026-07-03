"""NIP-44v2 encrypt/decrypt for WASI — a faithful port of the wheel's
``tollbooth.nip44`` with only the two native calls swapped for the composed
dpyc:crypto component:

  * secp256k1 ECDH (coincurve)      → ops.ecdh_nip04 (same shared-X)
  * ChaCha20 stream cipher (crypto) → ops.chacha20

Padding, HKDF-expand, and HMAC-SHA256 stay pure-Python (byte-identical to the
wheel), so payloads interoperate with the native courier and real Nostr clients.
Installed by ``courier_relay.install`` because the wheel's ``tollbooth.nip44``
fails to import under WASI (coincurve + cryptography are native).
"""

import base64
import hashlib
import hmac
import os
import struct

_VERSION = 2
_MIN_PLAINTEXT_SIZE = 1
_MAX_PLAINTEXT_SIZE = 65535


def _calc_padded_len(unpadded_len):
    if unpadded_len <= 32:
        return 32
    next_power = 1
    while next_power < unpadded_len:
        next_power *= 2
    if next_power <= 256:
        return next_power
    chunk = next_power // 8
    return chunk * ((unpadded_len + chunk - 1) // chunk)


def _pad(plaintext):
    unpadded_len = len(plaintext)
    if unpadded_len < _MIN_PLAINTEXT_SIZE or unpadded_len > _MAX_PLAINTEXT_SIZE:
        raise ValueError(f"Plaintext length {unpadded_len} out of range")
    padded_len = _calc_padded_len(unpadded_len)
    return struct.pack(">H", unpadded_len) + plaintext + b"\x00" * (padded_len - unpadded_len)


def _unpad(padded):
    if len(padded) < 2:
        raise ValueError("Padded data too short")
    (unpadded_len,) = struct.unpack(">H", padded[:2])
    if unpadded_len < _MIN_PLAINTEXT_SIZE or unpadded_len > _MAX_PLAINTEXT_SIZE:
        raise ValueError(f"Invalid unpadded length: {unpadded_len}")
    if 2 + unpadded_len > len(padded):
        raise ValueError("Padded data shorter than declared length")
    tail = padded[2 + unpadded_len:]
    if tail != b"\x00" * len(tail):
        raise ValueError("Non-zero padding bytes detected")
    return padded[2:2 + unpadded_len]


def _hkdf_expand(prk, info, length):
    """HKDF-expand (RFC 5869) with SHA-256 — pure Python, matches cryptography's HKDFExpand."""
    okm = b""
    t = b""
    counter = 1
    while len(okm) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        okm += t
        counter += 1
    return okm[:length]


def _get_conversation_key(private_key_hex, public_key_hex):
    from wit_world.imports import ops  # dpyc:crypto

    shared_x = bytes(ops.ecdh_nip04(bytes.fromhex(private_key_hex), bytes.fromhex(public_key_hex)))
    return hmac.new(b"nip44-v2", shared_x, hashlib.sha256).digest()


def _get_message_keys(conversation_key, nonce):
    expanded = _hkdf_expand(conversation_key, nonce, 76)
    return expanded[:32], expanded[32:44], expanded[44:76]


def _chacha20(key, nonce12, data):
    from wit_world.imports import ops  # dpyc:crypto — RFC 8439, counter 0

    return bytes(ops.chacha20(key, nonce12, data))


def encrypt(plaintext, private_key_hex, public_key_hex):
    padded = _pad(plaintext.encode("utf-8"))
    conversation_key = _get_conversation_key(private_key_hex, public_key_hex)
    nonce = os.urandom(32)
    chacha_key, chacha_nonce, hmac_key = _get_message_keys(conversation_key, nonce)
    ciphertext = _chacha20(chacha_key, chacha_nonce, padded)
    mac = hmac.new(hmac_key, nonce + ciphertext, hashlib.sha256).digest()
    return base64.b64encode(bytes([_VERSION]) + nonce + ciphertext + mac).decode("ascii")


def decrypt(payload_b64, private_key_hex, public_key_hex):
    payload_b64 += "=" * (-len(payload_b64) % 4)
    payload = base64.b64decode(payload_b64)
    if len(payload) < 99:
        raise ValueError("NIP-44 payload too short")
    version = payload[0]
    if version != _VERSION:
        raise ValueError(f"Unsupported NIP-44 version: {version}")
    nonce = payload[1:33]
    ciphertext = payload[33:-32]
    mac = payload[-32:]
    conversation_key = _get_conversation_key(private_key_hex, public_key_hex)
    chacha_key, chacha_nonce, hmac_key = _get_message_keys(conversation_key, nonce)
    expected_mac = hmac.new(hmac_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        raise ValueError("NIP-44 decryption failed: HMAC verification failed")
    padded = _chacha20(chacha_key, chacha_nonce, ciphertext)
    return _unpad(padded).decode("utf-8")
