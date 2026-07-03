"""Stub of the `websocket` (websocket-client) module for the Wasm operator.

The wheel's Secure Courier does `from websocket import create_connection` and gates
`_enabled` on that import succeeding (`_HAS_WEBSOCKET`). WASI has no websockets, but
this stub lets the import succeed so the Courier enables itself — its relay I/O is
then rerouted to the bridge Worker by `tollbooth_wasmcp.courier_relay` (which replaces
every method that would have called `create_connection`). If something still reaches
`create_connection`, fail loudly rather than silently no-op.
"""


def create_connection(*_args, **_kwargs):
    raise RuntimeError(
        "websocket-client is unavailable under WASI; Courier relay I/O must go "
        "through the bridge (tollbooth_wasmcp.courier_relay). A create_connection "
        "call means a relay method was not rerouted."
    )
