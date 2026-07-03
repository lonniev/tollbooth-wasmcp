"""AES-256-GCM backed by the composed dpyc:crypto component (the WASI CPython
interpreter has no native cryptography). Matches the AESGCM API the wheel's
VaultCipher uses: AESGCM(key).encrypt/decrypt(nonce, data, associated_data)."""


class AESGCM:
    def __init__(self, key):
        self._key = bytes(key)

    def encrypt(self, nonce, data, associated_data):
        from wit_world.imports import ops
        aad = bytes(associated_data) if associated_data else b""
        return bytes(ops.aes256_gcm_encrypt(self._key, bytes(nonce), aad, bytes(data)))

    def decrypt(self, nonce, data, associated_data):
        from wit_world.imports import ops
        aad = bytes(associated_data) if associated_data else b""
        return bytes(ops.aes256_gcm_decrypt(self._key, bytes(nonce), aad, bytes(data)))
