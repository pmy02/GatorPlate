// Live-event tests for web/console/events.js (node --test; run through `make test-web WEB=web/console`): the silence
// watchdog falls back to polling even on an open stream, a fresh stream is tried next to the polling and a ping
// brings it back to live, and no change reaches the page twice. A fake EventSource, a fetch stub and node's mock
// timers stand in for the browser.
import { test } from "node:test";
import assert from "node:assert/strict";

class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static all = [];

  constructor(url, opts) {
    this.url = url;
    this.opts = opts;
    this.readyState = FakeEventSource.CONNECTING;
    this.listeners = {};
    FakeEventSource.all.push(this);
  }

  static last() { return FakeEventSource.all[FakeEventSource.all.length - 1]; }

  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }

  close() { this.readyState = FakeEventSource.CLOSED; }

  // The headers came through (a proxy may still hold the body).
  open() {
    this.readyState = FakeEventSource.OPEN;
    if (this.onopen) this.onopen({});
  }

  emit(type, data) {
    const m = { data: JSON.stringify(data) };
    for (const fn of this.listeners[type] || []) fn(m);
  }

  fail({ closed = false } = {}) {
    this.readyState = closed ? FakeEventSource.CLOSED : FakeEventSource.CONNECTING;
    if (this.onerror) this.onerror({});
  }
}

const docListeners = {};
globalThis.location = { search: "", origin: "https://console.test" };
globalThis.document = {
  visibilityState: "visible",
  documentElement: { lang: "en" },
  body: null,
  addEventListener(type, fn) { (docListeners[type] ||= new Set()).add(fn); },
  removeEventListener(type, fn) { if (docListeners[type]) docListeners[type].delete(fn); },
};
globalThis.EventSource = FakeEventSource;

// GET /api/cases answers by URL: a list of answers, served in order (the last one repeats); a number is an error status;
// a function is called and its promise awaited (an answer that is still on its way).
let answers = {};
const fetches = [];
const served = new Map();
globalThis.fetch = async (url) => {
  fetches.push(url);
  const list = answers[url];
  if (!list) return { ok: false, status: 404, text: async () => "" };
  const n = served.get(url) || 0;
  served.set(url, n + 1);
  const next = list[Math.min(n, list.length - 1)];
  const answer = typeof next === "function" ? await next() : next;
  if (typeof answer === "number") {
    return { ok: false, status: answer, text: async () => JSON.stringify({ error: { code: "unauthorized", message: "x" } }) };
  }
  return { ok: true, status: 200, text: async () => JSON.stringify(answer) };
};

const { subscribeEvents } = await import("./events.js");

const AT = "2026-10-02T17:00:00Z";
const sum = (id, version, updatedAt = `2026-10-02T17:00:0${version % 10}Z`) => ({ id, version, updated_at: updatedAt,
  live: false });
const event = (seq, type, summary) => ({ seq, type, case_id: summary.id, summary, at: AT });
const list = (seq, items) => ({ items, seq, server_time: AT });

// Settle the async poll callbacks (fetch, then text, then the page's onEvent).
async function flush() {
  for (let i = 0; i < 6; i += 1) await new Promise((r) => setImmediate(r));
}

// Move the clock in one-second steps, so every poll's answer settles before the next poll is due.
async function advance(t, ms) {
  for (let left = ms; left > 0; left -= 1000) {
    t.mock.timers.tick(Math.min(1000, left));
    await flush();
  }
}

const timed = new WeakSet();
function start(t, sinceSeq, routes) {
  if (!timed.has(t)) {
    t.mock.timers.enable({ apis: ["setTimeout", "setInterval", "Date"], now: 0 });
    timed.add(t);
  }
  answers = routes;
  fetches.length = 0;
  served.clear();
  const seen = { events: [], modes: [] };
  const sub = subscribeEvents({ onEvent: (e) => seen.events.push(e), onMode: (m) => seen.modes.push(m), sinceSeq });
  t.after(() => sub.close());
  return { sub, seen, stream: FakeEventSource.last() };
}

const brief = (events) => events.map((e) => (e.summary ? [e.type, e.summary.id, e.summary.version] : [e.type, e.case_id ?? e.seq]));

test("an open stream that stays silent falls back to polling at 25 s; a ping on a fresh stream brings back live", async (t) => {
  const { sub, seen, stream } = start(t, 5, {
    "/api/cases?since_seq=5": [list(7, [sum("c_a", 2)])],
    "/api/cases?since_seq=7": [list(7, [])],
  });
  assert.equal(stream.url, "/api/events?last_event_id=5", "the stream resumes after the list the page loaded");
  assert.deepEqual(seen.modes, ["connecting"]);
  stream.open(); // headers through, body held: no message and no ping ever arrive
  t.mock.timers.tick(24999);
  await flush();
  assert.deepEqual(seen.modes, ["connecting"], "an open stream is not live until a message or ping arrives");
  assert.equal(fetches.length, 0);

  t.mock.timers.tick(1);
  await flush();
  assert.deepEqual(seen.modes, ["connecting", "polling"], "25 s of silence: polling, although the stream is open");
  assert.equal(stream.readyState, FakeEventSource.CLOSED);
  assert.deepEqual(fetches, ["/api/cases?since_seq=5"], "the first poll goes out at once");
  assert.deepEqual(brief(seen.events), [["case.updated", "c_a", 2]]);
  t.mock.timers.tick(1000);
  await flush();
  assert.deepEqual(fetches, ["/api/cases?since_seq=5", "/api/cases?since_seq=7"], "then one poll per second");

  // 30 s after the fallback a fresh stream is tried next to the polling.
  await advance(t, 29000);
  const trial = FakeEventSource.last();
  assert.notEqual(trial, stream);
  assert.equal(trial.url, "/api/events?last_event_id=5", "it resumes after the last streamed seq");
  assert.equal(seen.modes.at(-1), "polling", "a trial that has said nothing yet is not live");
  trial.open();
  await advance(t, 2000);
  assert.equal(seen.modes.at(-1), "polling");
  const polls = fetches.length;
  trial.emit("ping", {});
  assert.deepEqual(seen.modes, ["connecting", "polling", "live"]);
  await advance(t, 5000);
  assert.equal(fetches.length, polls, "live again: polling stopped");

  // The replay after seq 5: the update a poll already delivered is dropped, the delete (polling cannot report one)
  // is delivered, and an event sent twice arrives once.
  trial.emit("case.updated", event(6, "case.updated", sum("c_a", 2)));
  trial.emit("case.deleted", { seq: 7, type: "case.deleted", case_id: "c_b", at: AT });
  trial.emit("case.created", event(8, "case.created", sum("c_c", 1)));
  trial.emit("case.created", event(8, "case.created", sum("c_c", 1)));
  assert.deepEqual(brief(seen.events), [["case.updated", "c_a", 2], ["case.deleted", "c_b"], ["case.created", "c_c", 1]]);

  // A stream that pings every 15 s stays live.
  for (let i = 0; i < 4; i += 1) {
    t.mock.timers.tick(15000);
    trial.emit("ping", {});
  }
  await flush();
  assert.equal(seen.modes.at(-1), "live");
  assert.equal(fetches.length, polls);

  // Closed: no stream, no polling, no retry.
  const streams = FakeEventSource.all.length;
  sub.close();
  await advance(t, 120000);
  assert.equal(trial.readyState, FakeEventSource.CLOSED);
  assert.equal(FakeEventSource.all.length, streams);
  assert.equal(fetches.length, polls);
});

test("a live stream that goes quiet falls back too; two errors or a stream the browser gave up on fall back at once", async (t) => {
  const quiet = start(t, 3, { "/api/cases?since_seq=4": [list(4, [])] });
  quiet.stream.open();
  quiet.stream.emit("ping", {});
  quiet.stream.emit("case.updated", event(4, "case.updated", sum("c_a", 1)));
  assert.deepEqual(quiet.seen.modes, ["connecting", "live"]);
  t.mock.timers.tick(24999);
  assert.equal(quiet.seen.modes.at(-1), "live");
  t.mock.timers.tick(1);
  await flush();
  assert.equal(quiet.seen.modes.at(-1), "polling", "25 s after the last message");
  assert.deepEqual(fetches, ["/api/cases?since_seq=4"]);
  quiet.sub.close();

  const flaky = start(t, 3, { "/api/cases?since_seq=3": [list(3, [])] });
  flaky.stream.fail();
  assert.deepEqual(flaky.seen.modes, ["connecting"], "one error: the browser reconnects by itself");
  flaky.stream.fail();
  await flush();
  assert.deepEqual(flaky.seen.modes, ["connecting", "polling"]);
  flaky.sub.close();

  const refused = start(t, 3, { "/api/cases?since_seq=3": [list(3, [])] });
  refused.stream.fail({ closed: true });
  await flush();
  assert.deepEqual(refused.seen.modes, ["connecting", "polling"], "a stream the browser closed falls back at once");
  // A trial that fails is dropped; polling goes on and the next trial comes 30 s later.
  await advance(t, 30000);
  const trial = FakeEventSource.last();
  trial.fail({ closed: true });
  assert.equal(trial.readyState, FakeEventSource.CLOSED);
  const polls = fetches.length;
  await advance(t, 3000);
  assert.equal(fetches.length, polls + 3);
  assert.equal(refused.seen.modes.at(-1), "polling");
  await advance(t, 27000);
  assert.notEqual(FakeEventSource.last(), trial, "the next trial");
});

test("polling skips a row it already delivered and turns a whole-list answer into one resync", async (t) => {
  const { seen, stream } = start(t, 10, {
    "/api/cases?since_seq=10": [list(11, [sum("c_a", 3)])],
    "/api/cases?since_seq=11": [list(12, [sum("c_a", 3)])], // the same row again (a change it already reported)
    "/api/cases?since_seq=12": [list(13, [sum("c_a", 4), sum("c_b", 1), sum("c_c", 1)])], // 3 rows for 1 event
    "/api/cases?since_seq=13": [list(14, [sum("c_b", 2)])],
  });
  stream.fail({ closed: true });
  await flush();
  await advance(t, 3000);
  assert.deepEqual(fetches, ["/api/cases?since_seq=10", "/api/cases?since_seq=11", "/api/cases?since_seq=12",
    "/api/cases?since_seq=13"]);
  assert.deepEqual(brief(seen.events), [["case.updated", "c_a", 3], ["resync", 13], ["case.updated", "c_b", 2]]);
  assert.ok(seen.events.every((e) => e.type !== "case.updated" || e.seq === 11 || e.seq === 14));
});

test("a lost session while polling sends one resync, so the page shows its login", async (t) => {
  const { seen, stream } = start(t, 2, { "/api/cases?since_seq=2": [401, 401, 401, list(2, [])] });
  stream.fail({ closed: true });
  await flush();
  await advance(t, 2000);
  assert.deepEqual(brief(seen.events), [["resync", 2]]);
  assert.equal(fetches.length, 3, "polling goes on (the page logs in again)");
});

test("a resync from the server resets the count (a restart), so later events are not taken for old ones", async (t) => {
  const { seen, stream } = start(t, 40, {});
  stream.open();
  stream.emit("ping", {});
  stream.emit("case.updated", event(50, "case.updated", sum("c_a", 5)));
  stream.emit("resync", { seq: 2, type: "resync", at: AT });
  stream.emit("case.created", event(3, "case.created", sum("c_new", 1)));
  assert.deepEqual(brief(seen.events), [["case.updated", "c_a", 5], ["resync", 2], ["case.created", "c_new", 1]]);
});

test("visibilitychange asks the page to refetch", async (t) => {
  const { seen } = start(t, 9, {});
  for (const fn of docListeners.visibilitychange || []) fn();
  assert.deepEqual(brief(seen.events), [["resync", 9]]);
});

// ---------------------------------------------------------------- reconnect loops, races and resume points

// A promise the test resolves itself: a poll answer that is still on its way.
function held() {
  let release;
  const gate = new Promise((r) => { release = r; });
  return { gate, release };
}

test("no reconnect storm: over three live → silent → polling → live cycles, one stream at a time, one poll a second, one trial every 30 s", async (t) => {
  const base = FakeEventSource.all.length;
  const { seen, stream } = start(t, 1, { "/api/cases?since_seq=1": [list(1, [])] });
  const mine = () => FakeEventSource.all.slice(base);
  const open = () => mine().filter((s) => s.readyState !== FakeEventSource.CLOSED).length;
  // One-second steps; after every step at most one stream may be open.
  const run = async (ms) => {
    for (let left = ms; left > 0; left -= 1000) {
      t.mock.timers.tick(1000);
      await flush();
      assert.ok(open() <= 1, "never two streams at once");
    }
  };
  stream.open();
  stream.emit("ping", {});
  let live = stream;
  for (let cycle = 0; cycle < 3; cycle += 1) {
    const polls = fetches.length;
    const streams = mine().length;
    await run(24000);
    assert.equal(seen.modes.at(-1), "live");
    assert.equal(fetches.length, polls, "live: no polling");
    assert.equal(mine().length, streams, "live: no trial streams");
    await run(1000);
    assert.equal(seen.modes.at(-1), "polling", "25 s after the last ping");
    assert.equal(live.readyState, FakeEventSource.CLOSED, "the silent stream is closed");
    await run(29000);
    assert.equal(fetches.length - polls, 30, "the first poll at once, then exactly one a second");
    assert.equal(mine().length, streams, "no new stream before 30 s");
    await run(1000);
    assert.equal(mine().length, streams + 1, "one trial at 30 s");
    live = FakeEventSource.last();
    live.open();
    live.emit("ping", {});
    assert.equal(seen.modes.at(-1), "live"); // the next cycle starts at this ping
  }
  assert.deepEqual(seen.modes, ["connecting", "live", "polling", "live", "polling", "live", "polling", "live"]);
});

test("a single error after a good reconnect does not add up with an earlier one (the server pings at once)", async (t) => {
  const { seen, stream } = start(t, 1, { "/api/cases?since_seq=1": [list(1, [])] });
  stream.open();
  stream.emit("ping", {});
  stream.fail(); // the browser reconnects by itself ...
  stream.open();
  stream.emit("ping", {}); // ... and the fresh connection pings at once
  stream.fail();
  await flush();
  assert.deepEqual(seen.modes, ["connecting", "live"], "one error since the last ping: still live");
  assert.equal(fetches.length, 0);
  stream.fail();
  await flush();
  assert.deepEqual(seen.modes, ["connecting", "live", "polling"], "two in a row: polling");
});

test("a poll answer that lands after the stream came back neither repeats a change nor restarts polling", async (t) => {
  const slow = held();
  const { seen, stream } = start(t, 3, {
    "/api/cases?since_seq=3": [() => slow.gate.then(() => list(4, [sum("c_a", 2)]))],
    "/api/cases?since_seq=4": [list(4, [])],
  });
  stream.fail({ closed: true });
  await advance(t, 30000);
  assert.equal(fetches.length, 1, "no second poll while the first is still waiting");
  const trial = FakeEventSource.last();
  assert.notEqual(trial, stream);
  trial.open();
  trial.emit("ping", {});
  trial.emit("case.updated", event(4, "case.updated", sum("c_a", 2)));
  slow.release();
  await flush();
  assert.deepEqual(brief(seen.events), [["case.updated", "c_a", 2]], "the same change once");
  await advance(t, 5000);
  assert.equal(fetches.length, 1, "live: the late answer did not start polling again");
  assert.equal(seen.modes.at(-1), "live");
  trial.emit("case.updated", event(5, "case.updated", sum("c_a", 3)));
  assert.deepEqual(brief(seen.events), [["case.updated", "c_a", 2], ["case.updated", "c_a", 3]]);
});

test("a reset made while polling reaches the page when the stream comes back; polled changes are not repeated", async (t) => {
  const { seen, stream } = start(t, 5, {
    "/api/cases?since_seq=5": [list(6, [sum("c_a", 1)])],
    "/api/cases?since_seq=6": [list(6, [])],
  });
  stream.fail({ closed: true });
  await advance(t, 30000);
  const trial = FakeEventSource.last();
  assert.equal(trial.url, "/api/events?last_event_id=5");
  trial.open();
  trial.emit("ping", {});
  trial.emit("case.created", event(6, "case.created", sum("c_a", 1))); // a poll delivered it
  trial.emit("demo.reset", { seq: 7, type: "demo.reset", at: AT }); // polling cannot report it
  trial.emit("case.created", event(8, "case.created", sum("c_b", 1)));
  assert.deepEqual(brief(seen.events), [["case.updated", "c_a", 1], ["demo.reset", 7], ["case.created", "c_b", 1]]);
  // The browser's own reconnect of this stream replays from its Last-Event-ID: nothing reaches the page twice.
  trial.fail();
  trial.open();
  trial.emit("ping", {});
  trial.emit("demo.reset", { seq: 7, type: "demo.reset", at: AT });
  trial.emit("case.created", event(8, "case.created", sum("c_b", 1)));
  assert.equal(seen.events.length, 3);
});

test("without a loaded list the stream has no resume point and the first poll asks for the whole list", async (t) => {
  const { seen, stream } = start(t, null, {
    "/api/cases": [list(3, [sum("c_a", 1), sum("c_b", 1)])],
    "/api/cases?since_seq=3": [list(4, [sum("c_a", 2)])],
  });
  assert.equal(stream.url, "/api/events");
  stream.fail({ closed: true });
  await flush();
  assert.deepEqual(brief(seen.events), [["resync", 3]], "the page refetches its list instead of row by row");
  await advance(t, 1000);
  assert.deepEqual(brief(seen.events), [["resync", 3], ["case.updated", "c_a", 2]]);
});

test("after close() nothing reaches the page: not a poll answer still on its way, not the rest of a poll answer", async (t) => {
  const slow = held();
  const first = start(t, 3, { "/api/cases?since_seq=3": [() => slow.gate.then(() => list(4, [sum("c_a", 2)]))] });
  first.stream.fail({ closed: true });
  await flush();
  first.sub.close();
  slow.release();
  await advance(t, 60000);
  assert.deepEqual(first.seen.events, []);
  assert.equal(fetches.length, 1);

  // The page may close the subscription from its own event handler (a logout): the rest of that answer is dropped.
  answers = { "/api/cases?since_seq=3": [list(5, [sum("c_a", 2), sum("c_b", 2)])] };
  const got = [];
  const sub = subscribeEvents({ onEvent: (e) => { got.push(e); sub.close(); }, sinceSeq: 3 });
  t.after(() => sub.close());
  FakeEventSource.last().fail({ closed: true });
  await flush();
  assert.deepEqual(brief(got), [["case.updated", "c_a", 2]]);
});

test("a restart seen by a poll moves the stream's resume point to the new server's count", async (t) => {
  const { seen, stream } = start(t, 40, {
    "/api/cases?since_seq=40": [list(2, [sum("c_a", 1)])], // the count went back: a restarted server
    "/api/cases?since_seq=2": [list(9, [sum("c_b", 1)])],
    "/api/cases?since_seq=9": [list(9, [])],
  });
  stream.fail({ closed: true });
  await flush();
  assert.deepEqual(brief(seen.events), [["resync", 2]]);
  await advance(t, 30000);
  const trial = FakeEventSource.last();
  assert.equal(trial.url, "/api/events?last_event_id=2", "not 40, a number the new server may already have reused");
  trial.open();
  trial.emit("ping", {});
  trial.emit("case.deleted", { seq: 5, type: "case.deleted", case_id: "c_a", at: AT }); // made while polling
  trial.emit("case.created", event(8, "case.created", sum("c_b", 1))); // a poll delivered it
  assert.deepEqual(brief(seen.events), [["resync", 2], ["case.updated", "c_b", 1], ["case.deleted", "c_a"]]);
});
