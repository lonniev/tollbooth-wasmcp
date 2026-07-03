"""NIP-04 encrypt/decrypt for WASI — a port of the wheel's ``tollbooth.nip04``
with the native calls swapped for the composed dpyc:crypto component:

  * secp256k1 ECDH (coincurve)          → ops.ecdh_nip04 (the AES-256 key)
  * AES-256-CBC + PKCS7 (cryptography)  → ops.aes256_cbc_encrypt/decrypt (PKCS7 built in)

Format is ``<base64_ciphertext>?iv=<base64_iv>``, byte-identical to the wheel (the
component's CBC path is validated against wheel vectors in the crypto crate's tests).
Installed by ``courier_relay.install`` because the wheel's ``tollbooth.nip04`` fails to
import under WASI. Used for the Secure Courier's vault encryption + legacy NIP-04 DMs.
"""

import base64
import os


def encrypt(plaintext, private_key_hex, public_key_hex):
    from wit_world.imports import ops  # dpyc:crypto

    shared = bytes(ops.ecdh_nip04(bytes.fromhex(private_key_hex), bytes.fromhex(public_key_hex)))
    iv = os.urandom(16)
    ciphertext = bytes(ops.aes256_cbc_encrypt(shared, iv, plaintext.encode("utf-8")))
    return f"{base64.b64encode(ciphertext).decode()}?iv={base64.b64encode(iv).decode()}"


def decrypt(ciphertext_with_iv, private_key_hex, public_key_hex):
    from wit_world.imports import ops  # dpyc:crypto

    if "?iv=" not in ciphertext_with_iv:
        raise ValueError("Invalid NIP-04 format: expected <base64>?iv=<base64>")
    ct_part, iv_part = ciphertext_with_iv.split("?iv=", 1)
    ct = base64.b64decode(ct_part + "=" * (-len(ct_part) % 4))
    iv = base64.b64decode(iv_part + "=" * (-len(iv_part) % 4))
    shared = bytes(ops.ecdh_nip04(bytes.fromhex(private_key_hex), bytes.fromhex(public_key_hex)))
    plaintext = bytes(ops.aes256_cbc_decrypt(shared, iv, ct))
    return plaintext.decode("utf-8")
