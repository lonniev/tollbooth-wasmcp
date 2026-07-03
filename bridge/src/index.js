// tollbooth-fermyon bridge Worker
//
// Why this exists: Nostr relays speak WebSocket only, but the Wasm operator
// (Akamai Functions) can dial outbound HTTP only. This Worker is the protocol
// adapter — it opens an outbound WebSocket to the relays (native in Cloudflare
// Workers), runs one NIP-01 REQ, and returns the raw signed event as JSON.
//
// Contract:
//   GET /event?author=<64-hex-pubkey>&kind=<int, default 30078>&d=<d-tag>
//   200 -> the raw Nostr event object (JSON)
//   404 -> no matching event on any relay
//   400 -> bad/missing parameters
//   502 -> all relays errored
//
// Trust model: stateless, holds no secrets. The payload it returns is NIP-04
// ciphertext it cannot read, and the consumer verifies the Authority's schnorr
// signature in-Wasm before trusting it. A lying or dead bridge can only cause a
// failed cold start — never a leaked or forged config.

const DEFAULT_RELAYS = [
  "wss://relay.primal.net",
  "wss://nos.lol",
  "wss://relay.damus.io",
  "wss://relay.nostr.band",
];

const HEX64 = /^[0-9a-f]{64}$/;
const RELAY_TIMEOUT_MS = 6000;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method !== "GET") {
      return json({ error: "method_not_allowed" }, 405);
    }
    if (url.pathname === "/health") {
      return json({ ok: true, service: "tollbooth-fermyon-bridge" }, 200);
    }
    if (url.pathname !== "/event") {
      return json({ error: "not_found", detail: "use GET /event?author=&kind=&d=" }, 404);
    }

    const author = (url.searchParams.get("author") || "").toLowerCase();
    const kindRaw = url.searchParams.get("kind") || "30078";
    const kind = Number.parseInt(kindRaw, 10);
    const dtag = url.searchParams.get("d") || "";

    if (!HEX64.test(author)) {
      return json({ error: "bad_author", detail: "author must be a 64-char hex pubkey" }, 400);
    }
    if (!Number.isInteger(kind) || kind < 0 || kind > 65535) {
      return json({ error: "bad_kind", detail: "kind must be a non-negative integer" }, 400);
    }
    if (!dtag) {
      return json({ error: "missing_d", detail: "d-tag required for an addressable (3xxxx) event" }, 400);
    }

    const relays = (env && env.RELAYS ? String(env.RELAYS).split(",") : DEFAULT_RELAYS)
      .map((s) => s.trim())
      .filter(Boolean);

    const filter = { kinds: [kind], authors: [author], "#d": [dtag], limit: 1 };

    try {
      const event = await raceRelays(relays, filter);
      if (!event) {
        return json({ error: "not_found", detail: "no matching event on any relay" }, 404);
      }
      return json(event, 200);
    } catch (e) {
      return json({ error: "bridge_error", detail: String(e && e.message ? e.message : e) }, 502);
    }
  },
};

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

// Resolve with the first relay that yields a matching EVENT; null if every
// relay reaches EOSE / errors / times out without one.
async function raceRelays(relays, filter) {
  if (relays.length === 0) return null;
  const attempts = relays.map((r) => fetchFromRelay(r, filter));
  return await new Promise((resolve) => {
    let remaining = attempts.length;
    for (const p of attempts) {
      p.then((v) => {
        if (v) resolve(v);
        else if (--remaining === 0) resolve(null);
      }).catch(() => {
        if (--remaining === 0) resolve(null);
      });
    }
  });
}

async function fetchFromRelay(relayUrl, filter) {
  // Cloudflare's outbound WebSocket uses fetch() with an Upgrade header over
  // an http(s) URL; normalize the ws(s) relay scheme.
  const httpUrl = relayUrl.replace(/^wss:\/\//, "https://").replace(/^ws:\/\//, "http://");
  const resp = await fetch(httpUrl, { headers: { Upgrade: "websocket" } });
  const ws = resp.webSocket;
  if (!ws) throw new Error(`relay did not upgrade: ${relayUrl}`);
  ws.accept();

  const sub = "b" + Math.random().toString(36).slice(2, 12);

  return await new Promise((resolve) => {
    let settled = false;
    const done = (v) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { ws.close(); } catch (_) { /* ignore */ }
      resolve(v);
    };
    const timer = setTimeout(() => done(null), RELAY_TIMEOUT_MS);

    ws.addEventListener("message", (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (!Array.isArray(msg)) return;
      if (msg[0] === "EVENT" && msg[1] === sub && msg[2]) done(msg[2]);
      else if (msg[0] === "EOSE" && msg[1] === sub) done(null);
      else if (msg[0] === "CLOSED" && msg[1] === sub) done(null);
    });
    ws.addEventListener("close", () => done(null));
    ws.addEventListener("error", () => done(null));

    try {
      ws.send(JSON.stringify(["REQ", sub, filter]));
    } catch (_) {
      done(null);
    }
  });
}
