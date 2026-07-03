# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

tollbooth-wasmcp is the Spin/WASI host adapter for tollbooth-dpyc operators — the
peer of FastMCP on the Prefect Horizon side. `SpinOperatorHost` runs the same
operator source in a WebAssembly component.

## [0.1.5] — 2026-07-03

### Fixed

- Persist ledger debits on the stateless Spin operator. The wheel debits by
  mutating the in-memory ledger and `mark_dirty`, relying on a background-flush
  task and a graceful-shutdown flush — both of which assume a long-lived process.
  Spin tears the instance down after every request, so debits (and rollbacks) were
  discarded and **every paid tool ran for free** (credits persisted only because
  `check_payment` flushes explicitly). `call_tool` now `flush_all()`s the ledger
  synchronously after the tool runs, when a paid tool populated the cache. Verified
  live: balance 1000 → 999, drop survives into a fresh MCP session.

## [0.1.4] — 2026-07-03

### Fixed

- Surface `wasi:http` errors as `httpx.ConnectError` instead of crashing with
  `FrozenInstanceError: cannot assign to field '__traceback__'`. wasi:http error
  values are frozen dataclasses, so raising them directly failed when Python
  attached a traceback — masking the real cause (e.g. an outbound request denied by
  Spin's `allowed_outbound_hosts` read as an opaque dataclass error).

## [0.1.3] — 2026-07-03

### Added — Secure Courier over WASI

- The wheel's Secure Courier (`request`/`receive_npub_proof`, credential channels)
  now works in-Wasm. `dpyc:crypto` gained `schnorr_sign` (BIP-340, raw) so the
  courier can sign DMs, and `chacha20` (RFC 8439) for NIP-44.
- `courier_relay` reroutes the courier's relay primitives through the bridge Worker
  via a synchronous `wasi:http` client (blocking poll — no asyncio nesting), and
  runs `asyncio.to_thread` in-loop (`PollLoop` has no executor).
- `nip44_wasm` / `nip04_wasm`: component-backed NIP-44v2 + NIP-04, byte-identical to
  the wheel (cross-checked bidirectionally). A `websocket` stub flips the wheel's
  `_HAS_WEBSOCKET` gate; `pynostr` shims gained `PrivateKey()` ephemeral keys and
  `Event.sign()`.
- Bridge Worker: `POST /publish` (send EVENT, await OK) and `POST /req` (collect to
  EOSE), with a bounded relay handshake. Outbound WebSocket needs the deployed edge
  runtime — `wrangler dev` does not serve it.

## [0.1.2] — 2026-07-03

### Added

- Minimal `fastmcp.Client` shim so the operator can make MCP-to-MCP calls (Oracle
  delegation, Authority `certify_credits` / `check_balance`, adoption). It speaks MCP
  streamable-HTTP over `httpx` (already routed over `wasi:http`); the full `fastmcp`
  package can't run in the componentize-py interpreter. Operators must allow the
  upstream MCP host in `spin.toml` (`https://*.fastmcp.app`).

## [0.1.1] — 2026-07-03

### Added

- `service_status` now reports `tollbooth_wasmcp_version` alongside the wheel's
  `tollbooth_dpyc_version`, so a client (Pricing Studio) can show the full build
  stack. Version is single-sourced in `_version.py` and read dynamically by
  `pyproject` (hatchling).

## [0.1.0] — 2026-07-03

### Added — initial release

- `SpinOperatorHost`, the Spin/WASI peer of FastMCP: records the same
  `register_standard_tools()` registrations, generates JSON schemas from typed
  signatures, binds/coerces arguments, and exposes the wasmcp `Tools` surface.
- WASI seams so the tollbooth-dpyc wheel runs untouched: `httpx` over `wasi:http`,
  a composed `dpyc:crypto` Rust component (NIP-04 ECDH, BIP-340 verify, AES) standing
  in for coincurve/cryptography, nsec-only bootstrap via an HTTPS→relay bridge Worker,
  and the componentize-py async runtime (poll_loop, transport).
- The wheel ships everything as package data (Python + `pynostr`/`cryptography`
  shims + the WIT world + a prebuilt `crypto.wasm`), so `pip install tollbooth-wasmcp`
  is a complete Spin host. Includes a reference `weather-operator` example.
