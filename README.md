# tollbooth-wasmcp

**The Spin/WASI host for [tollbooth-dpyc](https://pypi.org/project/tollbooth-dpyc/) Operators.**

A DPYC Operator is business logic — a set of priced MCP tools over the `tollbooth-dpyc` runtime.
On [Prefect Horizon](https://www.prefect.io/), **FastMCP** is the host that turns that logic into a
running MCP server. `tollbooth-wasmcp` is the **peer host for Fermyon Spin / Akamai Functions**: it
lets the *same* operator code deploy as a WebAssembly component, reusing the `tollbooth-dpyc` wheel
**untouched**. Write the operator once; pick the host.

FastMCP's edge jobs — derive the tool schema from your typed functions, coerce inbound args, run the
transport — are done here by the adapter (`get_type_hints`-based schema + pydantic-lite coercion + a
WASI transport). Same source of truth (your tool functions' hints + docstrings), a second host
projection of it. The operator never writes either.

## Writing an operator

```python
import tollbooth_wasmcp                      # FIRST import — installs the pre-init seams
from tollbooth_wasmcp import SpinOperatorHost
from tollbooth.tool_identity import ToolIdentity, capability_uuid
import weather                               # your domain client

_DOMAIN = { UUID: ToolIdentity(tool_id=UUID, capability="get_current_weather", category="read", intent="…"), … }

host = SpinOperatorHost(service_name="my-operator", slug="myslug", domain_tools=_DOMAIN)
tool = host.tool

@tool
@host.runtime.paid_tool(capability_uuid("get_current_weather"))
async def current(latitude: float, longitude: float, npub: str = "", dpop_token: str = ""):
    return await weather.get_current(latitude, longitude)

Tools = host.tools_export()                  # the wasmcp exports.Tools surface
```

That is the FastMCP `tollbooth-sample` server, line for line, with `SpinOperatorHost(…)` where the
FastMCP operator writes `FastMCP(…)` and `Tools = host.tools_export()` where it writes `mcp.run()`.
See [`examples/weather-operator`](examples/weather-operator) for the complete, runnable version.

## What the host provides

Importing `tollbooth_wasmcp` installs — in order, before the wheel imports — every seam the
componentize-py build needs, none of which the WASI Python interpreter has natively:

- **httpx over `wasi:http`** — every wheel HTTP call (registry, bridge, Neon, upstream APIs).
- **`dpyc:crypto` component** — a Rust WASI component (NIP-04 ECDH, BIP-340 schnorr verify, AES-CBC/GCM)
  standing in for `coincurve`/`cryptography`. Shipped prebuilt as `tollbooth_wasmcp/crypto.wasm`.
- **nsec-only bootstrap** — `ensure_bootstrapped` fetches the operator's encrypted config event through
  an HTTPS→Nostr-relay **bridge** Worker and decrypts it with the crypto component (the operator holds
  only its nsec; the Neon URL is discovered, never configured).
- **schema + coercion** — `tool_schema` (correct JSON types even under the wheel's PEP 563 annotations)
  and `bind_args` (coerce `"90"` → `90` for an `int` param), the FastMCP/pydantic edge jobs.
- **snapshot fixes** — force-bundle the wheel's lazily-imported submodules, pin the wheel version,
  read config from the live WASI environment (`spin up --env`) each call.
- **`PROOF_DEBUG`** (opt-in, off by default) — a rejected proof explains which sub-check failed.

## Building an operator (out-of-repo)

```
pip install tollbooth-wasmcp                 # into your build's deps/ (--target deps)
# then in your Makefile:
componentize-py --wit-path $(python -m tollbooth_wasmcp.paths wit) --world operator \
  componentize app -p . -p deps -p $(python -m tollbooth_wasmcp.paths toplevel) -o operator.wasm
wac plug operator.wasm --plug $(python -m tollbooth_wasmcp.paths crypto) -o plugged.wasm
wasmcp compose server plugged.wasm -o server.wasm
```

Run (the operator is **nsec-only** — supply the nsec + bridge URL at run time, never in the manifest):

```
# start the bridge in bridge/:  npx wrangler dev --port 8799 --local
spin up --env TOLLBOOTH_NOSTR_OPERATOR_NSEC=<nsec> --env BRIDGE_URL=http://localhost:8799
```

Requires `componentize-py`, `wac`, `wasmcp`, and `spin` on PATH. The standardized WIT world imports
`wasi:http`, `dpyc:crypto`, `wasi:cli/environment`, and `wasi:config/store`; do **not** run
`componentize-py bindings` separately (it clobbers the vendored `poll_loop.py`).

## Repo layout

```
tollbooth_wasmcp/       the adapter (PyPI package): SpinOperatorHost, schema, binding, seams
  _toplevel/            pynostr + cryptography shims the wheel imports by top-level name
  wit/                  the standardized DPYC Spin WIT world + deps
  crypto.wasm           prebuilt dpyc:crypto component (from crypto/)
crypto/                 Rust source for the dpyc:crypto component
bridge/                 the HTTPS→Nostr-relay bridge Cloudflare Worker
examples/weather-operator/   a complete reference operator using SpinOperatorHost
tests/                  schema/coercion unit tests (incl. FastMCP parity)
```

Apache-2.0. Part of the [DPYC](https://github.com/lonniev/dpyc-community) ecosystem.
