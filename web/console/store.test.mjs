// Console state tests (node --test; run through `make test-web WEB=web/console`): the reducer, the effects of live
// events and the controller's API calls with a fetch stub.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  initialState, reduce, segmentCounts, sortedSummaries, visibleSummaries, diffDetail, replayFrames, createController,
  effectsOf, openYellow, elapsedMs, programsShown,
} from "./store.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name) => JSON.parse(readFileSync(path.join(here, "..", "fixtures", name), "utf8"));

class StubError extends Error {
  constructor(status, code, message) { super(message || code); this.status = status; this.code = code; }
}

// A fetch stub: routes "METHOD /path" to a value, a function or an error; records every call in order.
function stub(routes) {
  const calls = [];
  const fetchJSON = async (url, opts = {}) => {
    const method = (opts.method || "GET").toUpperCase();
    const key = `${method} ${url.split("?")[0]}`;
    calls.push({ key, url, body: opts.body });
    if (!(key in routes)) throw new StubError(404, "not_found", `no route ${key}`);
    let v = routes[key];
    if (typeof v === "function") v = v(opts.body, calls);
    if (v instanceof Error) throw v;
    return structuredClone(v);
  };
  return { fetchJSON, calls };
}

const timers = { setTimer: () => 0, clearTimer: () => {} };

function loaded() {
  let s = initialState();
  s = reduce(s, { type: "meta/loaded", meta: fixture("meta.json") });
  s = reduce(s, { type: "list/loaded", list: fixture("cases.json"), now: 1000 });
  return s;
}

test("segments: needs review, live and all, with live rows pinned first", () => {
  let s = loaded();
  assert.deepEqual(segmentCounts(s), { review: 1, live: 0, all: 6 });
  const live = { ...fixture("cases.json").items[0], id: "c_new", code: "AB2-C3D", live: true, created_at: "2026-10-01T00:00:00Z", version: 1 };
  s = reduce(s, { type: "event", event: { type: "case.created", seq: 50, case_id: "c_new", summary: live, at: "2026-10-02T17:00:00Z" }, now: 2000 });
  assert.equal(sortedSummaries(s)[0].id, "c_new");
  assert.deepEqual(segmentCounts(s), { review: 1, live: 1, all: 7 });
  s = reduce(s, { type: "segment", segment: "review" });
  assert.deepEqual(visibleSummaries(s).map((x) => x.code), ["R8W-3ND"]);
});

test("a new live call opens the Live view when following live calls; a second call does not switch", () => {
  let s = loaded();
  const sum = { ...fixture("cases.json").items[0], live: true, version: 1 };
  s = reduce(s, { type: "event", event: { type: "case.created", case_id: sum.id, summary: sum, at: "2026-10-02T16:57:00Z" }, now: 5000 });
  assert.equal(s.followId, "c_maria2demo");
  assert.equal(s.view, "live");
  assert.equal(s.list.byId.c_maria2demo.live, true, "case.created replaces an older stored summary");
  const other = { ...sum, id: "c_other", code: "ZZ2-ZZ3" };
  s = reduce(s, { type: "event", event: { type: "case.created", case_id: "c_other", summary: other }, now: 6000 });
  assert.equal(s.followId, "c_maria2demo");
  assert.equal(elapsedMs(s, "c_maria2demo", 8000), 3000);
});

test("live transcript lines: deduplicated and ordered student first within a turn", () => {
  let s = loaded();
  const line = (turn, who, text) => ({ type: "live.turn", case_id: "c1", line: { case_id: "c1", turn, who, text, lang: "en", at: "2026-10-02T17:00:00Z" } });
  for (const e of [line(1, "assistant", "Great."), line(0, "assistant", "Hi"), line(1, "student", "Yes"), line(1, "student", "Yes")]) {
    s = reduce(s, { type: "event", event: e, now: 1 });
  }
  assert.deepEqual(s.live.lines.c1.map((l) => `${l.turn}:${l.who}`), ["0:assistant", "1:student", "1:assistant"]);
  s = reduce(s, { type: "event", event: { type: "live.ended", case_id: "c1" }, now: 2 });
  assert.equal(s.live.ended.c1, 2);
  s = reduce(s, { type: "live/forget", id: "c1" });
  assert.equal(s.live.lines.c1, undefined);
});

test("a case.updated with changed_programs refetches the open detail and opens section 6b once", async () => {
  const before = fixture("case_maria.json");
  const after = structuredClone(before);
  after.case.version = 13;
  after.summary.version = 13;
  after.summary.found_display = 3830;
  after.case.program_answers = { break_transit: { value: "weekdays_muni", at: "2026-10-02T23:11:20Z", source: "card" } };
  Object.assign(after.programs.lines.find((l) => l.id === "clipper_start"),
    { status: "likely", value_yearly: 168, display_yearly: 160, counted: true, range_lo: null, range_hi: null });
  Object.assign(after.programs, { found_display: 3830, found_yearly: 3840 });
  let served = before;
  const api = stub({ "GET /api/meta": fixture("meta.json"), "GET /api/cases": fixture("cases.json"),
    "GET /api/cases/c_maria2demo": () => served });
  const ctl = createController({ fetchJSON: api.fetchJSON, ...timers });
  await ctl.loadAll();
  await ctl.select("c_maria2demo", "work");
  assert.equal(ctl.getState().sections.programs, false);
  served = after;
  const n = api.calls.length;
  const effects = await ctl.handleEvent({ type: "case.updated", seq: 200, case_id: "c_maria2demo", summary: after.summary,
    changed_slots: [], changed_programs: true, now_asking: null, at: "2026-10-02T23:11:21Z" });
  assert.deepEqual(effects, [["detail", "c_maria2demo"]]);
  assert.deepEqual(api.calls.slice(n).map((c) => c.key), ["GET /api/cases/c_maria2demo"]);
  const s = ctl.getState();
  assert.equal(s.details.c_maria2demo.data.case.version, 13);
  assert.equal(s.list.byId.c_maria2demo.found_display, 3830);
  assert.equal(s.sections.programs, true, "the first changed_programs event opens 6b");
  assert.deepEqual(s.details.c_maria2demo.diff.programs, ["clipper_start"]);
  assert.equal(s.details.c_maria2demo.diff.footer, true);
  assert.equal(s.details.c_maria2demo.diff.answers, true);
  // The user closes 6b; a later card answer does not reopen it.
  ctl.dispatch({ type: "section", key: "programs", open: false });
  await ctl.handleEvent({ type: "case.updated", seq: 201, case_id: "c_maria2demo", summary: { ...after.summary, version: 14 },
    changed_programs: true, at: "2026-10-02T23:11:41Z" });
  assert.equal(ctl.getState().sections.programs, false);
});

test("a polled case.updated with an unchanged version does not refetch; other cases never refetch", () => {
  let s = loaded();
  const d = fixture("case_maria.json");
  s = reduce(s, { type: "select", id: "c_maria2demo" });
  s = reduce(s, { type: "detail/loaded", detail: d, now: 1 });
  const same = { type: "case.updated", case_id: "c_maria2demo", summary: d.summary };
  assert.deepEqual(effectsOf(s, reduce(s, { type: "event", event: same }), same), []);
  const other = { type: "case.updated", case_id: "c_sofia2demo", summary: { ...fixture("case_sofia.json").summary, version: 99 } };
  assert.deepEqual(effectsOf(s, reduce(s, { type: "event", event: other }), other), []);
  const reset = { type: "demo.reset" };
  assert.deepEqual(effectsOf(s, s, reset), [["list"]], "the reset deleted the watched case: no detail fetch");
  const resync = { type: "resync" };
  assert.deepEqual(effectsOf(s, s, resync), [["list"], ["detail", "c_maria2demo"]]);
});

test("Reset demo sends reset, then seed (and Seed samples sends seed alone)", async () => {
  const api = stub({ "GET /api/meta": fixture("meta.json"), "GET /api/cases": fixture("cases.json"),
    "POST /api/demo/reset": fixture("demo_reset.json"), "POST /api/demo/seed": fixture("demo_seed.json") });
  const ctl = createController({ fetchJSON: api.fetchJSON, ...timers });
  await ctl.loadAll();
  const n = api.calls.length;
  const r = await ctl.actions.demoReset();
  assert.equal(r.deleted, 1);
  assert.deepEqual(api.calls.slice(n).map((c) => c.key), ["POST /api/demo/reset", "POST /api/demo/seed", "GET /api/cases"]);
  assert.equal(ctl.getState().demoResult, "Reset · removed 1, samples restored");
  assert.equal(ctl.getState().view, "live");
  assert.equal(ctl.getState().followId, null);
  assert.equal(ctl.getState().selectedId, null, "the Live view is idle after a reset");
  const m = api.calls.length;
  await ctl.actions.demoSeed();
  assert.deepEqual(api.calls.slice(m).map((c) => c.key), ["POST /api/demo/seed", "GET /api/cases"]);
});

test("Reset demo shows the new list by itself: no event and no page reload needed", async () => {
  const before = fixture("cases.json");
  const after = { ...before, seq: before.seq + 2, items: before.items.filter((it) => it.id !== "c_jamal2demo") };
  let resetDone = false;
  const api = stub({ "GET /api/meta": fixture("meta.json"), "GET /api/cases": () => (resetDone ? after : before),
    "POST /api/demo/reset": () => { resetDone = true; return fixture("demo_reset.json"); },
    "POST /api/demo/seed": fixture("demo_seed.json") });
  const ctl = createController({ fetchJSON: api.fetchJSON, ...timers });
  await ctl.loadAll();
  assert.ok(ctl.getState().list.byId.c_jamal2demo);
  await ctl.actions.demoReset();
  const s = ctl.getState();
  assert.equal(s.list.byId.c_jamal2demo, undefined, "the removed case is gone from the list");
  assert.deepEqual(Object.keys(s.list.byId).sort(), after.items.map((it) => it.id).sort());
  assert.equal(s.list.seq, after.seq);
});

test("Reset demo whose seed fails still shows the list after the reset; a failed reset fetches nothing more", async () => {
  const before = fixture("cases.json");
  const after = { ...before, seq: before.seq + 1, items: before.items.filter((it) => it.id !== "c_jamal2demo") };
  let resetDone = false;
  const api = stub({ "GET /api/meta": fixture("meta.json"), "GET /api/cases": () => (resetDone ? after : before),
    "POST /api/demo/reset": () => { resetDone = true; return fixture("demo_reset.json"); },
    "POST /api/demo/seed": new StubError(500, "internal", "Something went wrong.") });
  const ctl = createController({ fetchJSON: api.fetchJSON, ...timers });
  await ctl.loadAll();
  const n = api.calls.length;
  assert.equal(await ctl.actions.demoReset(), null);
  assert.deepEqual(api.calls.slice(n).map((c) => c.key), ["POST /api/demo/reset", "POST /api/demo/seed", "GET /api/cases"]);
  assert.equal(ctl.getState().list.byId.c_jamal2demo, undefined, "the removed case does not linger");

  const refused = stub({ "GET /api/meta": fixture("meta.json"), "GET /api/cases": before,
    "POST /api/demo/reset": new StubError(500, "internal", "Something went wrong.") });
  const ctl2 = createController({ fetchJSON: refused.fetchJSON, ...timers });
  await ctl2.loadAll();
  const m = refused.calls.length;
  assert.equal(await ctl2.actions.demoReset(), null);
  assert.deepEqual(refused.calls.slice(m).map((c) => c.key), ["POST /api/demo/reset"]);
});

test("Sofia: 'Looks right' unlocks 'Mark reviewed'; the review then succeeds", async () => {
  const api = stub({
    "GET /api/meta": fixture("meta.json"), "GET /api/cases": fixture("cases.json"),
    "GET /api/cases/c_sofia2demo": fixture("case_sofia.json"),
    "POST /api/cases/c_sofia2demo/yellow/y1": fixture("case_sofia_confirmed.json"),
    "POST /api/cases/c_sofia2demo/status": fixture("case_sofia_reviewed.json"),
  });
  const ctl = createController({ fetchJSON: api.fetchJSON, ...timers });
  await ctl.loadAll();
  await ctl.select("c_sofia2demo", "work");
  assert.equal(openYellow(ctl.getState().details.c_sofia2demo.data).length, 1);
  const ok = await ctl.actions.confirmYellow("c_sofia2demo", "y1");
  assert.equal(ok.ok, true);
  const confirm = api.calls.find((c) => c.key === "POST /api/cases/c_sofia2demo/yellow/y1");
  assert.deepEqual(confirm.body, { action: "confirm", expected_version: fixture("case_sofia.json").case.version });
  const s = ctl.getState();
  assert.equal(openYellow(s.details.c_sofia2demo.data).length, 0);
  assert.equal(s.details.c_sofia2demo.diff.unlocked, true);
  const rev = await ctl.actions.markReviewed("c_sofia2demo");
  assert.equal(rev.ok, true);
  assert.deepEqual(api.calls.at(-1).body,
    { status: "reviewed", expected_version: fixture("case_sofia_confirmed.json").case.version });
  assert.equal(ctl.getState().details.c_sofia2demo.data.case.status, "reviewed");
  assert.equal(ctl.getState().list.byId.c_sofia2demo.status, "reviewed");
});

test("409 locked shows its reason and refetches; 409 conflict refetches with the toast", async () => {
  let statusAnswer = new StubError(409, "locked", "Check 1 line first.");
  const api = stub({
    "GET /api/meta": fixture("meta.json"), "GET /api/cases": fixture("cases.json"),
    "GET /api/cases/c_sofia2demo": fixture("case_sofia.json"),
    "POST /api/cases/c_sofia2demo/status": () => statusAnswer,
  });
  const ctl = createController({ fetchJSON: api.fetchJSON, ...timers });
  await ctl.loadAll();
  await ctl.select("c_sofia2demo", "work");
  const r = await ctl.actions.markReviewed("c_sofia2demo");
  assert.equal(r.code, "locked");
  assert.deepEqual(ctl.getState().lockError, { id: "c_sofia2demo", message: "Check 1 line first." });
  assert.equal(api.calls.at(-1).key, "GET /api/cases/c_sofia2demo");
  statusAnswer = new StubError(409, "conflict", "stale");
  const r2 = await ctl.actions.setStatus("c_sofia2demo", "follow_up");
  assert.equal(r2.code, "conflict");
  assert.equal(ctl.getState().toasts.at(-1).text, "This case changed — showing the latest.");
  assert.equal(api.calls.at(-1).key, "GET /api/cases/c_sofia2demo");
});

test("401 shows the login; a failed login keeps the message", async () => {
  const api = stub({ "GET /api/meta": new StubError(401, "unauthorized"),
    "POST /api/console/login": new StubError(401, "unauthorized") });
  const ctl = createController({ fetchJSON: api.fetchJSON, ...timers });
  assert.equal(await ctl.loadAll(), false);
  assert.equal(ctl.getState().auth, "login");
  await ctl.actions.login("wrong");
  assert.equal(ctl.getState().loginError, "That passcode doesn't work.");
});

test("network failure keeps the data and raises the offline banner", async () => {
  const api = stub({ "GET /api/meta": fixture("meta.json"), "GET /api/cases": fixture("cases.json"),
    "GET /api/cases/c_maria2demo": new StubError(0, "network") });
  const ctl = createController({ fetchJSON: api.fetchJSON, ...timers });
  await ctl.loadAll();
  await ctl.select("c_maria2demo", "work");
  assert.ok(ctl.getState().offline);
  assert.equal(Object.keys(ctl.getState().list.byId).length, 6);
});

test("diff: filled slots and changed program lines drive the sweeps", () => {
  const d = fixture("case_maria.json");
  const less = structuredClone(d);
  delete less.case.slots.cash_on_hand;
  const diff = diffDetail(less, d);
  assert.deepEqual(diff.slots, ["cash_on_hand"]);
  assert.deepEqual(diff.programs, []);
  assert.equal(diffDetail(null, d).firstLoad, true);
});

test("programs are shown only when the detail and the meta carry them (GP_PROGRAMS=0 hides 6b and the card answers)", () => {
  const meta = fixture("meta.json");
  const jamal = fixture("case_jamal.json");
  assert.equal(programsShown(jamal, meta), true);
  const off = { ...structuredClone(jamal), programs: null };
  off.case.program_answers = {};
  assert.equal(programsShown(off, { ...meta, programs: null }), false);
  assert.equal(programsShown(jamal, { ...meta, programs: null }), false);
});

test("replay frames: 2× pacing within 0.6–3 s, the $151 flip at turn 6, settled at $306", () => {
  const frames = replayFrames(fixture("case_maria.json"));
  assert.equal(frames[0].detail.case.estimate_range, null);
  assert.deepEqual(Object.keys(frames[0].detail.case.slots), []);
  for (const f of frames.slice(1, -1)) assert.ok(f.delay >= 600 && f.delay <= 3000, `delay ${f.delay}`);
  const t6 = frames.find((f) => f.turn === 6);
  assert.deepEqual(t6.detail.case.estimate_range, { lo: 155, hi: 306, settled: false });
  assert.equal(t6.now.reason, "could change the estimate by $151: $155 or $306");
  assert.deepEqual(t6.detail.case.skipped, []);
  const t7 = frames.find((f) => f.turn === 7);
  assert.deepEqual(t7.detail.case.estimate_range, { lo: 306, hi: 306, settled: true });
  assert.equal(t7.detail.case.skipped[0].detail, "Not asked — heating or cooling bill, same estimate either way");
  assert.equal(frames.at(-1).last, true);
  assert.equal(replayFrames(fixture("case_maria.json"), { reduced: true }).length, 1);
});
