"""tollbooth-wasmcp — the Spin/WASI host adapter for tollbooth-dpyc Operators.

Peer to FastMCP on the Horizon side. Importing this package (which an operator does
as its FIRST import, before the wheel) installs — in order — every pre-init seam the
componentize-py build needs, so the operator itself carries only business logic:

  1. route httpx over wasi:http BEFORE the wheel imports;
  2. import the wheel and point ``ensure_bootstrapped`` at the bridge/crypto path;
  3. force-bundle the wheel's lazily-imported submodules into the frozen snapshot;
  4. pin the wheel version (importlib.metadata can't scan the frozen fs);
  5. install the opt-in PROOF_DEBUG diagnostic;
  6. force-import the ``pynostr``/``cryptography`` shims + the crypto binding.

Seams install only inside the componentize-py build (detected by ``wit_world``);
native imports — unit tests, ``SpinOperatorHost`` construction — skip them.
"""


def _install_seams():
    # 1) httpx -> wasi:http, BEFORE importing the wheel.
    import httpx

    from tollbooth_wasmcp.transport import WasiHttpTransport

    _orig_async_client = httpx.AsyncClient

    class _WasiAsyncClient(_orig_async_client):
        def __init__(self, *a, **k):
            k.setdefault("transport", WasiHttpTransport())
            super().__init__(*a, **k)

    httpx.AsyncClient = _WasiAsyncClient

    # 2) Import the wheel + wire the crypto/bootstrap seam.
    import tollbooth.bootstrap

    from tollbooth_wasmcp.bootstrap import wasm_ensure_bootstrapped

    tollbooth.bootstrap.ensure_bootstrapped = wasm_ensure_bootstrapped

    # 3) + 4) Bundle lazy wheel submodules; pin the wheel version.
    from tollbooth_wasmcp.bundling import force_bundle_wheel, install_version_shim

    force_bundle_wheel()
    install_version_shim()

    # 5) Opt-in proof-rejection diagnostic (off unless PROOF_DEBUG is set).
    from tollbooth_wasmcp.diagnostics import install_proof_diagnostic

    install_proof_diagnostic()

    # 6) Force-import the top-level shims + crypto binding so they enter the snapshot.
    import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
    import pynostr.event  # noqa: F401
    import pynostr.key  # noqa: F401
    from wit_world.imports import ops  # noqa: F401


try:
    import wit_world  # noqa: F401 — present only in the componentize-py build
    _IN_WASM = True
except Exception:
    _IN_WASM = False

if _IN_WASM:
    _install_seams()

from tollbooth_wasmcp._version import __version__  # noqa: E402
from tollbooth_wasmcp.host import SpinOperatorHost  # noqa: E402

__all__ = ["SpinOperatorHost", "__version__"]
