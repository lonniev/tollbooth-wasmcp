"""Locate the adapter's non-Python build assets from the installed package, so an
operator's Makefile can reference them without vendoring:

    ADAPTER := $(shell python -m tollbooth_wasmcp.paths toplevel)
    WIT     := $(shell python -m tollbooth_wasmcp.paths wit)
    CRYPTO  := $(shell python -m tollbooth_wasmcp.paths crypto)

- toplevel: dir added to componentize `-p` so the wheel finds `pynostr`/`cryptography`
  at their top-level names.
- wit: the standardized DPYC Spin WIT world (`--wit-path`).
- crypto: the prebuilt dpyc:crypto component (`wac plug`).
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def toplevel_dir() -> str:
    return os.path.join(_HERE, "_toplevel")


def wit_dir() -> str:
    return os.path.join(_HERE, "wit")


def crypto_wasm() -> str:
    return os.path.join(_HERE, "crypto.wasm")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    print({"toplevel": toplevel_dir, "wit": wit_dir, "crypto": crypto_wasm}.get(which, lambda: "")())
