// Live events for the console (docs/UI_SPEC.md A3.1 and A8.3). ES module, same origin only; only the console loads
// it, so the shared fetch helper stays small for the other pages.
// The stream counts as live once a message or a ping arrives (the server pings at once on connect, then after 15 s of
// quiet). After two stream errors, a stream the browser gave up on, or 25 s without a message or ping (an open stream
// too: a proxy can pass the headers and hold the body), the page polls GET /api/cases?since_seq=N every 1 s. Every
// 30 s a fresh stream is tried next to the polling; its first message or ping switches back to live. A fresh stream
// resumes after the last streamed seq (after a restart a poll noticed, the new server's count), so the deletes and
// resets that polling cannot report are replayed then. No change is delivered twice: a stream event at or below a seq
// that a poll already covered (case.created and case.updated) or that a stream already sent is dropped, and a polled
// row equal to the last summary delivered for that case is skipped. A poll answer with more rows than events since N
// is a whole list (after a reset or a restart); like a visibilitychange it reaches onEvent as {type: "resync"}, and the
// page refetches. onMode receives "connecting", then "live" or "polling" on every change.
// Fixture mode (?fixtures=1) replays /fixtures/maria_live_events.json ({delay_ms, event, detail?} entries; a `detail`
// is the CaseDetail that GET /api/cases/{case_id} answers from then on).
import { FIXTURES, fetchJSON, fixtureFile, setFixtureAnswer } from "../shared/api.js";

const TYPES = ["case.created", "case.updated", "case.deleted", "demo.reset", "resync", "live.turn", "live.ended"];
const POLLED = new Set(["case.created", "case.updated"]);
const SILENCE_MS = 25000;
const POLL_MS = 1000;
const RETRY_MS = 30000;

export function subscribeEvents({ onEvent, onMode = () => {}, sinceSeq = null } = {}) {
  if (FIXTURES) return replayFixtureEvents({ onEvent, onMode });
  const start = typeof sinceSeq === "number" ? sinceSeq : null;
  let lastSeq = start; // every change up to this seq has been delivered (by a stream or a poll)
  let streamSeq = start; // the last seq a stream delivered; a fresh stream resumes after it
  const delivered = new Map(); // case id → "version|updated_at" of the last summary delivered
  let es = null; // the stream: live, or on trial while polling
  let errors = 0;
  let mode = null;
  let polling = false;
  let pollBusy = false;
  let authLost = false;
  let silenceTimer = null;
  let pollTimer = null;
  let retryTimer = null;
  let closed = false;

  const setMode = (next) => {
    if (next === mode) return;
    mode = next;
    onMode(next);
  };
  const stamp = (summary) => `${summary.version}|${summary.updated_at}`;
  const remember = (evt) => {
    if (evt.type === "demo.reset" || evt.type === "resync") delivered.clear();
    else if (evt.type === "case.deleted" && evt.case_id) delivered.delete(evt.case_id);
    else if (evt.summary && evt.summary.id) delivered.set(evt.summary.id, stamp(evt.summary));
  };

  const fromStream = (evt) => {
    const seq = typeof evt.seq === "number" ? evt.seq : null;
    if (evt.type === "resync" && seq !== null) {
      lastSeq = seq; // the server's count (it may have restarted)
      streamSeq = seq;
    } else if (seq !== null) {
      if (streamSeq !== null && seq <= streamSeq) return;
      streamSeq = seq;
      if (POLLED.has(evt.type) && lastSeq !== null && seq <= lastSeq) return;
      lastSeq = lastSeq === null ? seq : Math.max(lastSeq, seq);
    }
    remember(evt);
    onEvent(evt);
  };

  const dropStream = () => {
    const old = es;
    es = null;
    if (old) old.close();
  };
  const armSilence = () => {
    clearTimeout(silenceTimer);
    silenceTimer = polling || closed ? null : setTimeout(fallBack, SILENCE_MS);
  };
  const stopPolling = () => {
    polling = false;
    clearInterval(pollTimer);
    clearInterval(retryTimer);
    pollTimer = null;
    retryTimer = null;
  };
  // A message or a ping: the stream works (a trial stream ends the polling).
  const alive = () => {
    errors = 0;
    if (polling) stopPolling();
    armSilence();
    setMode("live");
  };

  const poll = async () => {
    if (pollBusy || closed) return;
    pollBusy = true;
    const since = lastSeq;
    try {
      const list = await fetchJSON(since === null ? "/api/cases" : `/api/cases?since_seq=${since}`);
      authLost = false;
      const seq = typeof list.seq === "number" ? list.seq : null;
      if (closed || seq === null) return;
      const items = Array.isArray(list.items) ? list.items : [];
      if (since === null || items.length > seq - since) {
        // A count that went back means a restarted server: the old resume point means nothing there any more.
        if (since !== null && seq < since) streamSeq = seq;
        lastSeq = seq;
        delivered.clear();
        onEvent({ type: "resync", seq });
        return;
      }
      for (const item of items) {
        if (closed) return; // the page closed the subscription from its own handler
        if (!item || !item.id || delivered.get(item.id) === stamp(item)) continue;
        delivered.set(item.id, stamp(item));
        onEvent({ type: "case.updated", seq, case_id: item.id, summary: item, at: list.server_time });
      }
      lastSeq = lastSeq === null ? seq : Math.max(lastSeq, seq);
    } catch (err) {
      // A lost session: one resync, so the page's own list fetch shows its login screen.
      if (err && err.status === 401 && !authLost) {
        authLost = true;
        onEvent({ type: "resync", seq: lastSeq });
      }
    } finally {
      pollBusy = false;
    }
  };

  function fallBack() {
    if (closed || polling) return;
    clearTimeout(silenceTimer);
    silenceTimer = null;
    dropStream();
    polling = true;
    setMode("polling");
    pollTimer = setInterval(poll, POLL_MS);
    retryTimer = setInterval(connect, RETRY_MS);
    poll();
  }

  function connect() {
    if (closed) return;
    dropStream();
    const src = new EventSource(streamSeq === null ? "/api/events" : `/api/events?last_event_id=${streamSeq}`,
      { withCredentials: true });
    es = src;
    const onMessage = (m) => {
      if (src !== es) return;
      alive();
      if (!m.data) return;
      let evt = null;
      try { evt = JSON.parse(m.data); } catch { return; }
      if (evt && typeof evt === "object") fromStream(evt);
    };
    src.onmessage = onMessage;
    for (const t of TYPES) src.addEventListener(t, onMessage);
    src.addEventListener("ping", () => { if (src === es) alive(); });
    src.onerror = () => {
      if (src !== es) return;
      errors += 1;
      if (polling) dropStream(); // a failed trial: the retry timer starts the next one
      else if (errors >= 2 || src.readyState === EventSource.CLOSED) fallBack();
    };
  }

  const onVisible = () => {
    if (document.visibilityState === "visible") onEvent({ type: "resync", seq: lastSeq });
  };
  document.addEventListener("visibilitychange", onVisible);
  setMode("connecting");
  connect();
  armSilence();
  return {
    close() {
      closed = true;
      dropStream();
      stopPolling();
      clearTimeout(silenceTimer);
      silenceTimer = null;
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
        if (entry.detail && entry.event.case_id) setFixtureAnswer(`GET /api/cases/${entry.event.case_id}`, entry.detail);
        onEvent(structuredClone(entry.event));
        next();
      }, entry.delay_ms || 0);
    };
    next();
  }).catch(() => onMode("polling"));
  return { close() { stopped = true; clearTimeout(timer); } };
}
