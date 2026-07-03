// tollbooth-wasmcp bridge Worker
//
// Why this exists: Nostr relays speak WebSocket only, but the Wasm operator
// (Fermyon Spin / Akamai Functions) can dial outbound HTTP only. This Worker is
// the protocol adapter — it opens outbound WebSockets to relays (native in
// Cloudflare Workers) and speaks NIP-01 on the operator's behalf.
//
// Contract:
//   GET  /event?author=<64-hex>&kind=<int>&d=<d-tag>  -> the first matching event (JSON) | 404
//   POST /req    { filters, relays?, limit?, timeout_ms? } -> { events: [...] }   (batch read)
//   POST /publish{ event, relays? }                        -> { results: [[relay, ok, detail], …] }
//   GET  /health -> { ok: true }
//
// Trust model: stateless, holds no secrets. Payloads are NIP-04/44 ciphertext it
// cannot read, and the operator verifies schnorr signatures in-Wasm before
// trusting anything. A lying or dead bridge can only cause a failed call — never
// a leaked or forged secret.

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
    const relays = resolveRelays(env);

    if (url.pathname === "/health") {
      return json({ ok: true, service: "tollbooth-wasmcp-bridge" }, 200);
    }

    // --- GET /event : first matching addressable event (bootstrap read) --------
    if (url.pathname === "/event") {
      if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405);
      const author = (url.searchParams.get("author") || "").toLowerCase();
      const kind = Number.parseInt(url.searchParams.get("kind") || "30078", 10);
      const dtag = url.searchParams.get("d") || "";
      if (!HEX64.test(author)) return json({ error: "bad_author" }, 400);
      if (!Number.isInteger(kind) || kind < 0 || kind > 65535) return json({ error: "bad_kind" }, 400);
      if (!dtag) return json({ error: "missing_d" }, 400);
      try {
        const event = await raceRelays(relays, { kinds: [kind], authors: [author], "#d": [dtag], limit: 1 });
        return event ? json(event, 200) : json({ error: "not_found" }, 404);
      } catch (e) {
        return json({ error: "bridge_error", detail: errMsg(e) }, 502);
      }
    }

    // --- POST /req : collect a batch of events matching filter(s) ---------------
    if (url.pathname === "/req") {
      if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
      let body;
      try { body = await request.json(); } catch (_) { return json({ error: "bad_json" }, 400); }
      const filters = Array.isArray(body.filters) ? body.filters
        : (body.filter ? [body.filter] : null);
      if (!filters || filters.length === 0) return json({ error: "missing_filters" }, 400);
      const targets = pickRelays(body.relays, relays);
      const limit = clampInt(body.limit, 1, 500, 100);
      const timeout = clampInt(body.timeout_ms, 500, 15000, RELAY_TIMEOUT_MS);
      try {
        const perRelay = await Promise.all(
          targets.map((r) => collectFromRelay(r, filters, limit, timeout).catch(() => [])),
        );
        const byId = new Map();
        for (const evs of perRelay) for (const ev of evs) if (ev && ev.id) byId.set(ev.id, ev);
        return json({ events: [...byId.values()] }, 200);
      } catch (e) {
        return json({ error: "bridge_error", detail: errMsg(e) }, 502);
      }
    }

    // --- POST /publish : broadcast a signed event to relays ---------------------
    if (url.pathname === "/publish") {
      if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
      let body;
      try { body = await request.json(); } catch (_) { return json({ error: "bad_json" }, 400); }
      const event = body.event;
      if (!event || typeof event !== "object" || !HEX64.test(String(event.id || ""))) {
        return json({ error: "bad_event", detail: "event with a 64-hex id required" }, 400);
      }
      const targets = pickRelays(body.relays, relays);
      const timeout = clampInt(body.timeout_ms, 500, 15000, RELAY_TIMEOUT_MS);
      try {
        const results = await Promise.all(
          targets.map((r) => publishToRelay(r, event, timeout).catch((e) => [r, false, errMsg(e)])),
        );
        const accepted = results.some((r) => r[1]);
        return json({ accepted, results }, accepted ? 200 : 502);
      } catch (e) {
        return json({ error: "bridge_error", detail: errMsg(e) }, 502);
      }
    }

    return json({ error: "not_found", detail: "routes: GET /event, POST /req, POST /publish, GET /health" }, 404);
  },
};

// ---------------------------------------------------------------------------

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

function errMsg(e) { return String(e && e.message ? e.message : e); }

function resolveRelays(env) {
  return (env && env.RELAYS ? String(env.RELAYS).split(",") : DEFAULT_RELAYS)
    .map((s) => s.trim()).filter(Boolean);
}

function pickRelays(requested, fallback) {
  const list = Array.isArray(requested)
    ? requested.map((s) => String(s).trim()).filter(Boolean)
    : [];
  return list.length ? list : fallback;
}

function clampInt(v, lo, hi, dflt) {
  const n = Number.parseInt(v, 10);
  if (!Number.isInteger(n)) return dflt;
  return Math.min(hi, Math.max(lo, n));
}

async function openRelay(relayUrl, timeoutMs) {
  // Cloudflare's outbound WebSocket uses fetch() with an Upgrade header over an
  // http(s) URL; normalize the ws(s) relay scheme. Bound the handshake so a slow
  // or non-upgrading relay fails fast instead of hanging the whole request.
  const httpUrl = relayUrl.replace(/^wss:\/\//, "https://").replace(/^ws:\/\//, "http://");
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), Math.min(timeoutMs || RELAY_TIMEOUT_MS, 5000));
  let resp;
  try {
    resp = await fetch(httpUrl, { headers: { Upgrade: "websocket" }, signal: ctl.signal });
  } finally {
    clearTimeout(t);
  }
  const ws = resp.webSocket;
  if (!ws) throw new Error(`relay did not upgrade (status ${resp.status}): ${relayUrl}`);
  ws.accept();
  return ws;
}

// First matching EVENT, else null (bootstrap read).
async function raceRelays(relays, filter) {
  if (relays.length === 0) return null;
  const attempts = relays.map((r) => fetchFromRelay(r, filter));
  return await new Promise((resolve) => {
    let remaining = attempts.length;
    for (const p of attempts) {
      p.then((v) => { if (v) resolve(v); else if (--remaining === 0) resolve(null); })
        .catch(() => { if (--remaining === 0) resolve(null); });
    }
  });
}

async function fetchFromRelay(relayUrl, filter) {
  const ws = await openRelay(relayUrl, RELAY_TIMEOUT_MS);
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
    try { ws.send(JSON.stringify(["REQ", sub, filter])); } catch (_) { done(null); }
  });
}

// All EVENTs matching the filters, until EOSE / limit / timeout.
async function collectFromRelay(relayUrl, filters, limit, timeoutMs) {
  const ws = await openRelay(relayUrl, timeoutMs);
  const sub = "b" + Math.random().toString(36).slice(2, 12);
  const events = [];
  return await new Promise((resolve) => {
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { ws.close(); } catch (_) { /* ignore */ }
      resolve(events);
    };
    const timer = setTimeout(done, timeoutMs);
    ws.addEventListener("message", (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (!Array.isArray(msg)) return;
      if (msg[0] === "EVENT" && msg[1] === sub && msg[2]) {
        events.push(msg[2]);
        if (events.length >= limit) done();
      } else if ((msg[0] === "EOSE" || msg[0] === "CLOSED") && msg[1] === sub) {
        done();
      }
    });
    ws.addEventListener("close", done);
    ws.addEventListener("error", done);
    try { ws.send(JSON.stringify(["REQ", sub, ...filters])); } catch (_) { done(); }
  });
}

// Broadcast one EVENT; resolve [relay, accepted, detail] from the relay's OK.
async function publishToRelay(relayUrl, event, timeoutMs) {
  const ws = await openRelay(relayUrl, timeoutMs);
  return await new Promise((resolve) => {
    let settled = false;
    const done = (accepted, detail) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { ws.close(); } catch (_) { /* ignore */ }
      resolve([relayUrl, accepted, detail]);
    };
    const timer = setTimeout(() => done(false, "timeout"), timeoutMs);
    ws.addEventListener("message", (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (Array.isArray(msg) && msg[0] === "OK" && msg[1] === event.id) {
        done(!!msg[2], String(msg[3] || ""));
      }
    });
    ws.addEventListener("close", () => done(false, "closed"));
    ws.addEventListener("error", () => done(false, "error"));
    try { ws.send(JSON.stringify(["EVENT", event])); } catch (_) { done(false, "send_failed"); }
  });
}
