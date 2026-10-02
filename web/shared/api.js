// GatorPlate shared API helper (docs/UI_SPEC.md A8.3). ES module, same origin only.
// fetchJSON: JSON in and out; a non-200 answer throws ApiError from the {"error": {code, message, retryable}} body.
// subscribeEvents: server-sent events with a polling fallback; header pill text comes from onMode("live"|"polling").
// Fixture mode (?fixtures=1): fetchJSON answers from web/fixtures/ through /fixtures/index.json and
// subscribeEvents replays /fixtures/maria_live_events.json ({delay_ms, event, detail?} entries; a `detail` is the
// CaseDetail that GET /api/cases/{case_id} answers from then on). A fixture file {"__status": 409, "error": {...}}
// answers as that error.

export class ApiError extends Error {
  constructor(status, code, message, retryable = false) {
    super(message || code);
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

const query = new URLSearchParams(location.search);
export const FIXTURES = query.get("fixtures") === "1";

let indexPromise = null;
const fileCache = new Map();
const counters = new Map();
const overrides = new Map();

function loadIndex() {
  if (!indexPromise) {
    indexPromise = fetch("/fixtures/index.json", { cache: "no-store" }).then((r) => r.json())
      .then((d) => d.routes || d);
  }
  return indexPromise;
}

// Key "METHOD /path/{name}?query": {name} matches one segment; a query part must equal the request's query.
function score(key, method, path, search) {
  const [km, rest] = key.split(" ");
  if (!rest || km !== method) return -1;
  const [kp, kq] = rest.split("?");
  if (kq !== undefined && kq !== search) return -1;
  const a = kp.split("/");
  const b = path.split("/");
  if (a.length !== b.length) return -1;
  let literal = 0;
  for (let i = 0; i < a.length; i += 1) {
    if (/^\{[^}]+\}$/.test(a[i])) continue;
    if (a[i] !== b[i]) return -1;
    literal += 1;
  }
  return literal * 2 + (kq !== undefined ? 1000 : 0);
}

function langOf(search, explicit) {
  const q = new URLSearchParams(search).get("lang");
  return explicit || q || document.documentElement.lang || query.get("lang") || "en";
}

async function fixtureFile(name) {
  if (!fileCache.has(name)) {
    const r = await fetch(`/fixtures/${name}`, { cache: "no-store" });
    if (!r.ok) throw new ApiError(404, "not_found", `Fixture ${name} is missing.`);
    fileCache.set(name, await r.json());
  }
  return fileCache.get(name);
}

async function fromFixtures(method, url, lang) {
  const u = new URL(url, location.origin);
  const search = u.search.replace(/^\?/, "");
  const override = overrides.get(`${method} ${u.pathname}`);
  if (override) return structuredClone(override);
  const index = await loadIndex();
  let best = null;
  let bestScore = -1;
  for (const key of Object.keys(index)) {
    const s = score(key, method, u.pathname, search);
    if (s > bestScore) { best = key; bestScore = s; }
  }
  if (best === null) throw new ApiError(404, "not_found", `No fixture for ${method} ${u.pathname}.`);
  let name = index[best];
  if (name && typeof name === "object") name = name[langOf(search, lang)] || name.en;
  const data = await fixtureFile(name);
  let out = data;
  if (Array.isArray(data)) {
    const n = counters.get(name) || 0;
    counters.set(name, n + 1);
    out = data[Math.min(n, data.length - 1)];
  }
  if (out && out.__status) {
    const e = out.error || {};
    throw new ApiError(out.__status, e.code, e.message, e.retryable);
  }
  return structuredClone(out);
}

export async function fetchJSON(url, { method = "GET", body, headers = {}, signal, lang } = {}) {
  if (FIXTURES) return fromFixtures(method.toUpperCase(), url, lang);
  const init = { method, headers: { Accept: "application/json", ...headers }, credentials: "same-origin",
    cache: "no-store", signal };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, init);
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    throw new ApiError(0, "network", "Network error.", true);
  }
  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = null; }
  }
  if (!res.ok) {
    const e = data && data.error;
    throw new ApiError(res.status, e ? e.code : "internal", e ? e.message : `HTTP ${res.status}`,
      e ? e.retryable : res.status >= 500);
  }
  return data === null ? {} : data;
}

// Live events. Fallback to polling GET /api/cases?since_seq=N every 1 s after two stream errors, or 25 s without
// any event while the stream is not open (or after visible pings stopped); the stream is retried every 30 s and
// the list is refetched on visibilitychange (onEvent receives {type: "resync"}).
const TYPES = ["case.created", "case.updated", "case.deleted", "demo.reset", "resync", "live.turn", "live.ended"];

export function subscribeEvents({ onEvent, onMode = () => {}, sinceSeq = null } = {}) {
  if (FIXTURES) return replayFixtureEvents({ onEvent, onMode });
  let lastSeq = sinceSeq;
  let es = null;
  let errors = 0;
  let lastSeen = Date.now();
  let sawPing = false;
  let pollTimer = null;
  let retryTimer = null;
  let closed = false;

  const deliver = (evt) => {
    if (typeof evt.seq === "number") lastSeq = Math.max(lastSeq || 0, evt.seq);
    onEvent(evt);
  };
  const onMessage = (m) => {
    lastSeen = Date.now();
    errors = 0;
    if (!m.data) return;
    try { deliver(JSON.parse(m.data)); } catch { /* not an event body */ }
  };
  const startPolling = () => {
    if (closed || pollTimer) return;
    if (es) { es.close(); es = null; }
    onMode("polling");
    pollTimer = setInterval(async () => {
      try {
        const q = lastSeq === null ? "" : `?since_seq=${lastSeq}`;
        const list = await fetchJSON(`/api/cases${q}`);
        for (const item of list.items || []) {
          deliver({ type: "case.updated", seq: list.seq, case_id: item.id, summary: item, at: list.server_time });
        }
        if (typeof list.seq === "number") lastSeq = list.seq;
      } catch { /* keep polling */ }
    }, 1000);
    retryTimer = setTimeout(() => { stopPolling(); connect(); }, 30000);
  };
  const stopPolling = () => {
    clearInterval(pollTimer);
    clearTimeout(retryTimer);
    pollTimer = null;
    retryTimer = null;
  };
  const connect = () => {
    if (closed) return;
    es = new EventSource("/api/events", { withCredentials: true });
    lastSeen = Date.now();
    es.onopen = () => { lastSeen = Date.now(); errors = 0; onMode("live"); };
    es.onmessage = onMessage;
    for (const t of TYPES) es.addEventListener(t, onMessage);
    es.addEventListener("ping", () => { lastSeen = Date.now(); sawPing = true; });
    es.onerror = () => {
      errors += 1;
      if (errors >= 2) startPolling();
    };
  };
  const watchdog = setInterval(() => {
    if (!es || pollTimer || Date.now() - lastSeen < 25000) return;
    if (sawPing || es.readyState !== EventSource.OPEN) startPolling();
  }, 5000);
  const onVisible = () => {
    if (document.visibilityState === "visible") onEvent({ type: "resync", seq: lastSeq });
  };
  document.addEventListener("visibilitychange", onVisible);
  connect();
  return {
    close() {
      closed = true;
      if (es) es.close();
      stopPolling();
      clearInterval(watchdog);
      document.removeEventListener("visibilitychange", onVisible);
    },
  };
}

function replayFixtureEvents({ onEvent, onMode }) {
  let stopped = false;
  let timer = null;
  onMode("replay");
  fixtureFile("maria_live_events.json").then((entries) => {
    let i = 0;
    const next = () => {
      if (stopped || i >= entries.length) return;
      const entry = entries[i];
      i += 1;
      timer = setTimeout(() => {
        if (stopped) return;
        if (entry.detail && entry.event.case_id) overrides.set(`GET /api/cases/${entry.event.case_id}`, entry.detail);
        onEvent(structuredClone(entry.event));
        next();
      }, entry.delay_ms || 0);
    };
    next();
  }).catch(() => onMode("polling"));
  return { close() { stopped = true; clearTimeout(timer); } };
}

// Fixture mode is always visible: a small "REPLAY" badge (styled by .replay-badge in base.css).
if (FIXTURES) {
  const addBadge = () => {
    if (document.querySelector(".replay-badge")) return;
    const b = document.createElement("span");
    b.className = "replay-badge chip chip--yellow";
    b.textContent = "REPLAY";
    document.body.append(b);
  };
  if (document.body) addBadge(); else document.addEventListener("DOMContentLoaded", addBadge);
}
