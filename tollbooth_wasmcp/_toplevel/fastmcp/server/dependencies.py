"""Stub for fastmcp.server.dependencies.get_context — the wheel's _get_session_id
reads get_context().session_id. Not on the Wasm operator's hot path, but provide a
harmless stub so an incidental call doesn't ModuleNotFound. The wasmcp transport owns
sessions; this returns an empty id."""


class _Ctx:
    session_id = ""


def get_context():
    return _Ctx()
