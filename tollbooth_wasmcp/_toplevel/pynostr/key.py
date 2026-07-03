"""Minimal pure-Python pynostr key shim for the Wasm operator.

npub/nsec <-> hex is pure bech32 (no secp256k1). Key derivation delegates to the
composed dpyc:crypto component. Signing/schnorr issuance is not supported here."""

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]


def _polymod(values):
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            chk ^= _GEN[i] if ((b >> i) & 1) else 0
    return chk


def _hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertbits(data, frm, to, pad=True):
    acc = bits = 0
    ret = []
    maxv = (1 << to) - 1
    for b in data:
        acc = (acc << frm) | b
        bits += frm
        while bits >= to:
            bits -= to
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (to - bits)) & maxv)
    return ret


def _bech32_to_hex(bech):
    bech = bech.lower()
    pos = bech.rfind("1")
    data = [_CHARSET.find(c) for c in bech[pos + 1:]]
    if any(d == -1 for d in data):
        raise ValueError("invalid bech32 char")
    return bytes(_convertbits(data[:-6], 5, 8, pad=False)).hex()


def _hex_to_bech32(hrp, hex_str):
    data = _convertbits(bytes.fromhex(hex_str), 8, 5)
    chk = _polymod(_hrp_expand(hrp) + data + [0, 0, 0, 0, 0, 0]) ^ 1
    checksum = [(chk >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_CHARSET[d] for d in data + checksum)


class PublicKey:
    def __init__(self, raw):
        self._hex = raw.hex() if isinstance(raw, (bytes, bytearray)) else raw

    @classmethod
    def from_npub(cls, npub):
        h = _bech32_to_hex(npub)
        if len(h) != 64:
            raise ValueError("npub does not decode to 32 bytes")
        return cls(h)

    def hex(self):
        return self._hex

    def bytes(self):
        return bytes.fromhex(self._hex)

    def bech32(self):
        return _hex_to_bech32("npub", self._hex)


class PrivateKey:
    def __init__(self, raw=None):
        # PrivateKey() with no arg generates a random ephemeral key (the courier
        # uses these for NIP-17 gift wraps + self-DM agents). WASI random via os.urandom.
        if raw is None:
            import os
            raw = os.urandom(32)
        self._hex = raw.hex() if isinstance(raw, (bytes, bytearray)) else raw

    @classmethod
    def from_nsec(cls, nsec):
        return cls(_bech32_to_hex(nsec))

    def hex(self):
        return self._hex

    @property
    def secret(self):
        return bytes.fromhex(self._hex)

    def bech32(self):
        return _hex_to_bech32("nsec", self._hex)

    @property
    def public_key(self):
        from wit_world.imports import ops
        return PublicKey(bytes(ops.xonly_pubkey(bytes.fromhex(self._hex))))
