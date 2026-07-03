# tollbooth-fermyon bridge

A stateless Cloudflare Worker that adapts HTTPS → Nostr WebSocket, so the Wasm
operator (which can only dial outbound HTTP) can read its Authority-published
bootstrap config off the relays (which speak WebSocket only).

## Why it exists

Nostr relays are WebSocket-only. Akamai Functions components get outbound HTTP
only (no `wasi:sockets`; `wasi:http` has no Upgrade even in WASI 0.3.0). Cloudflare
Workers natively support outbound WebSocket clients, so the Worker runs the one
NIP-01 query the operator needs at cold start and returns the raw event.

## Contract

```
GET /event?author=<64-hex-pubkey>&kind=<int, default 30078>&d=<d-tag>
```

- `200` → the raw Nostr event object as JSON (unmodified)
- `404` → no matching event on any relay
- `400` → bad/missing parameters
- `502` → all relays errored
- `GET /health` → `{ "ok": true }`

## Trust model

Stateless; holds no secrets. The returned payload is NIP-04 ciphertext the bridge
cannot read, and the consumer verifies the Authority's schnorr signature in-Wasm
before trusting it. A lying or dead bridge can only cause a failed operator cold
start — never a leaked or forged config. No auth (public ciphertext); rate-limit
at the edge.

## Scope

PoC plumbing for tollbooth-fermyon, deliberately **not** a DPYC Advocate. If the
PoC graduates, promote to a standalone single-purpose Advocate service.

## Dev

```
npm install
npm run dev      # wrangler dev on http://localhost:8787
npm run deploy   # wrangler deploy (interactive login)
```
