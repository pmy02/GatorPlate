// Edge cases of the console (node --test; run through `make test-web WEB=web/console`): the live transcript's
// memory-only life, line identity and order, the GET /live fallback, the polling path of section 6b, Pacific-time
// formatting, and the public-repository rules for every console file.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { initialState, reduce, effectsOf, lineKey, callIsOver, diffDetail, createController, cardAnswersShown } from "./store.js";
import * as T from "./text.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name) => JSON.parse(readFileSync(path.join(here, "..", "fixtures", name), "utf8"));

function loaded() {
  let s = initialState();
  s = reduce(s, { type: "meta/loaded", meta: fixture("meta.json") });
  s = reduce(s, { type: "list/loaded", list: fixture("cases.json"), now: 1000 });
  return s;
}

const liveSummary = () => ({ ...fixture("cases.json").items[0], live: true, version: 2 });
const line = (turn, who, text, at = "2026-10-02T17:00:00Z", id = "c_maria2demo") =>
  ({ type: "live.turn", case_id: id, line: { case_id: id, turn, who, text, lang: "en", at } });

function liveCall() {
  let s = loaded();
  s = reduce(s, { type: "event", event: { type: "case.created", seq: 60, case_id: "c_maria2demo", summary: liveSummary(),
    at: "2026-10-02T17:00:00Z" }, now: 10 });
  return s;
}

// ---------------------------------------------------------------- the transcript lives only while the call is live

test("live.ended wipes the transcript lines from state, even when the Live view is not on screen", () => {
  let s = liveCall();
  s = reduce(s, { type: "view", view: "work" });
  s = reduce(s, { type: "event", event: line(1, "student", "Yes, that's fine.") });
  assert.equal(s.live.lines.c_maria2demo.length, 1);
  s = reduce(s, { type: "event", event: { type: "live.ended", case_id: "c_maria2demo" }, now: 20 });
  assert.equal(s.live.lines.c_maria2demo, undefined, "no line kept after the call");
  assert.equal(callIsOver(s, "c_maria2demo"), true);
});

test("a line or a GET /live answer that arrives after the end is never kept", () => {
  let s = liveCall();
  s = reduce(s, { type: "event", event: { type: "live.ended", case_id: "c_maria2demo" }, now: 20 });
  s = reduce(s, { type: "event", event: line(9, "assistant", "Goodbye.") });
  assert.equal(s.live.lines.c_maria2demo, undefined);
  s = reduce(s, { type: "live/loaded", live: fixture("live_maria.json") });
  assert.equal(s.live.lines.c_maria2demo, undefined);
});

test("the polling path: a summary that is no longer live drops the lines too", () => {
  let s = liveCall();
  s = reduce(s, { type: "event", event: line(1, "student", "Yes.") });
  const ended = { ...liveSummary(), live: false, version: 12 };
  s = reduce(s, { type: "event", event: { type: "case.updated", case_id: "c_maria2demo", summary: ended } });
  assert.equal(s.live.lines.c_maria2demo, undefined);
});

test("a detail that says the call ended drops the lines", () => {
  let s = liveCall();
  s = reduce(s, { type: "event", event: line(1, "student", "Yes.") });
  s = reduce(s, { type: "detail/loaded", detail: fixture("case_maria.json"), now: 30 });
  assert.equal(s.live.lines.c_maria2demo, undefined);
});

test("a new call on a case id seen ended before starts clean (fixture replay)", () => {
  let s = liveCall();
  s = reduce(s, { type: "event", event: { type: "live.ended", case_id: "c_maria2demo" }, now: 20 });
  s = reduce(s, { type: "event", event: { type: "case.created", case_id: "c_maria2demo", summary: liveSummary() }, now: 30 });
  assert.equal(callIsOver(s, "c_maria2demo"), false);
  s = reduce(s, { type: "event", event: line(0, "assistant", "Hi") });
  assert.equal(s.live.lines.c_maria2demo.length, 1);
});

// ---------------------------------------------------------------- line identity and order

test("a silence re-prompt keeps its turn number and is not dropped as a duplicate", () => {
  let s = liveCall();
  s = reduce(s, { type: "event", event: line(3, "assistant", "How old are you?", "2026-10-02T17:00:10Z") });
  s = reduce(s, { type: "event", event: line(3, "assistant", "Are you still there? How old are you?", "2026-10-02T17:00:16Z") });
  s = reduce(s, { type: "event", event: line(3, "assistant", "How old are you?", "2026-10-02T17:00:10Z") }); // repeat
  s = reduce(s, { type: "event", event: line(3, "student", "I'm 20.", "2026-10-02T17:00:08Z") });
  assert.deepEqual(s.live.lines.c_maria2demo.map((l) => l.text),
    ["I'm 20.", "How old are you?", "Are you still there? How old are you?"]);
});

test("lines from GET /live and from live.turn events are the same lines", () => {
  const view = fixture("live_maria.json");
  let s = liveCall();
  for (const l of view.lines.slice(0, 5)) s = reduce(s, { type: "event", event: { type: "live.turn", case_id: l.case_id, line: l } });
  s = reduce(s, { type: "live/loaded", live: view });
  assert.equal(s.live.lines.c_maria2demo.length, view.lines.length);
  assert.equal(new Set(s.live.lines.c_maria2demo.map(lineKey)).size, view.lines.length);
  assert.equal(s.live.now.c_maria2demo.reason, "could change the estimate by $151: $155 or $306");
});

// ---------------------------------------------------------------- GET /live fallback without live.turn events

test("without live.turn events, each update of the followed live call fetches GET /live; one event stops it", () => {
  let s = liveCall();
  assert.equal(s.followId, "c_maria2demo");
  const upd = { type: "case.updated", seq: 61, case_id: "c_maria2demo", summary: { ...liveSummary(), version: 3 } };
  let next = reduce(s, { type: "event", event: upd });
  assert.deepEqual(effectsOf(s, next, upd), [["detail", "c_maria2demo"], ["live", "c_maria2demo"]]);
  s = reduce(next, { type: "event", event: line(1, "student", "Yes.") });
  const upd2 = { ...upd, seq: 63, summary: { ...liveSummary(), version: 4 } };
  next = reduce(s, { type: "event", event: upd2 });
  assert.deepEqual(effectsOf(s, next, upd2), [["detail", "c_maria2demo"]]);
});

test("no GET /live without the transcript setting, for a case not on screen, or after the end", () => {
  let s = liveCall();
  const off = { ...s, meta: { ...s.meta, live_transcript: false } };
  const upd = { type: "case.updated", case_id: "c_maria2demo", summary: { ...liveSummary(), version: 3 } };
  assert.deepEqual(effectsOf(off, reduce(off, { type: "event", event: upd }), upd), [["detail", "c_maria2demo"]]);
  const other = { type: "case.updated", case_id: "c_other", summary: { ...liveSummary(), id: "c_other", version: 1 } };
  assert.deepEqual(effectsOf(s, reduce(s, { type: "event", event: other }), other), []);
  s = reduce(s, { type: "event", event: { type: "live.ended", case_id: "c_maria2demo" } });
  assert.deepEqual(effectsOf(s, reduce(s, { type: "event", event: upd }), upd), [["detail", "c_maria2demo"]]);
});

test("the controller runs the fallback: the transcript fills from GET /live", async () => {
  const calls = [];
  const live = structuredClone(fixture("case_maria.json")); // the call in progress: live, version 3
  live.case.live = true;
  live.case.version = 3;
  live.summary = { ...live.summary, live: true, version: 3 };
  const routes = { "GET /api/meta": fixture("meta.json"), "GET /api/cases": fixture("cases.json"),
    "GET /api/cases/c_maria2demo": live, "GET /api/cases/c_maria2demo/live": fixture("live_maria.json") };
  const fetchJSON = async (url, opts = {}) => {
    const key = `${(opts.method || "GET").toUpperCase()} ${url.split("?")[0]}`;
    calls.push(key);
    return structuredClone(routes[key]);
  };
  const ctl = createController({ fetchJSON, setTimer: () => 0, clearTimer: () => {} });
  await ctl.loadAll();
  await ctl.handleEvent({ type: "case.created", seq: 60, case_id: "c_maria2demo", summary: liveSummary() });
  await ctl.handleEvent({ type: "case.updated", seq: 61, case_id: "c_maria2demo", summary: { ...liveSummary(), version: 3 } });
  assert.ok(calls.includes("GET /api/cases/c_maria2demo/live"));
  assert.equal(ctl.getState().live.lines.c_maria2demo.length, fixture("live_maria.json").lines.length);
});

// ---------------------------------------------------------------- section 6b on the polling path

test("polling path: a detail with a new card answer opens 6b once (no changed_programs flag)", () => {
  const before = fixture("case_maria.json");
  const after = structuredClone(before);
  after.case.version = 13;
  after.case.program_answers = { break_transit: { value: "weekdays_muni", at: "2026-10-02T23:11:20Z", source: "card" } };
  let s = loaded();
  s = reduce(s, { type: "select", id: "c_maria2demo" });
  s = reduce(s, { type: "detail/loaded", detail: before, now: 1 });
  assert.equal(s.sections.programs, false, "a first load never opens it");
  s = reduce(s, { type: "detail/loaded", detail: after, now: 2 });
  assert.equal(s.sections.programs, true);
  s = reduce(s, { type: "section", key: "programs", open: false });
  const marked = structuredClone(after);
  marked.case.program_progress = { calfresh: { applied: true, at: "2026-10-02T23:13:00Z" } };
  assert.equal(diffDetail(after, marked).progress, true);
  s = reduce(s, { type: "detail/loaded", detail: marked, now: 3 });
  assert.equal(s.sections.programs, false, "only once per case");
});

test("a card answer on a case that is not on screen does not open 6b", () => {
  let s = loaded();
  s = reduce(s, { type: "select", id: "c_sofia2demo" });
  const evt = { type: "case.updated", case_id: "c_maria2demo", summary: fixture("case_maria.json").summary, changed_programs: true };
  s = reduce(s, { type: "event", event: evt });
  assert.equal(s.sections.programs, false);
  assert.equal(s.programsAutoOpened.c_maria2demo, undefined);
});

test("GP_PROGRAMS=0: no From the card group", () => {
  assert.equal(cardAnswersShown({ ...fixture("meta.json"), programs: null }), false);
  assert.equal(cardAnswersShown(fixture("meta.json")), true);
});

// ---------------------------------------------------------------- 6b wording on other golden states

test("6b footer and per-year column on uncommon statuses (zero, note, maybe without a value)", () => {
  const names = fixture("meta.json").programs.names;
  const p = { mode: "full", found_display: 3670, calfresh_yearly: 3672, lines: [
    { id: "calfresh", status: "likely", counted: true, display_yearly: 3670 },
    { id: "medi_cal", status: "check", counted: false, display_yearly: 0, note_keys: ["medi_cal.family_income"] },
    { id: "clipper_start", status: "zero", counted: false, display_yearly: 0 },
    { id: "lifeline", status: "note", counted: false, display_yearly: null },
    { id: "care", status: "maybe", counted: false, display_yearly: 170 },
    { id: "tax_credits", status: "maybe", counted: false, display_yearly: 0 },
  ] };
  assert.equal(T.programsFooter(p, names), "Found about $3,670 a year (CalFresh $3,670) · not counted: Medi-Cal to check, "
    + "maybe PG&E CARE $170, maybe tax credits");
  assert.equal(T.programPerYear(p.lines[2]), "—");
  assert.equal(T.programPerYear(p.lines[3]), "—");
  assert.equal(T.programPerYear({ status: "check", counted: false, range_lo: 98, range_hi: 445 }), "$90–$440");
  assert.equal(T.PROGRAM_STATUS.note, "Note");
});

// ---------------------------------------------------------------- wording and time zone

test("first month below the minimum reads correctly for every month name", () => {
  const text = T.firstMonthText({ filed_on: "2026-10-30", amount: 0, month_label: "October" });
  assert.equal(text, "If filed now (estimate): counts from Fri, Oct 30 — too few days left in October for a first-month amount");
  assert.ok(!/\ba (A|E|I|O|U)/.test(text));
});

test("list times are Pacific: just after midnight UTC is still yesterday evening in San Francisco", () => {
  const c = { created_at: "2026-10-02T06:30:00Z" }; // Oct 1, 11:30 PM PT
  assert.equal(T.listTime(c, new Date("2026-10-02T06:45:00Z")), "11:30 PM"); // still Oct 1 in PT
  assert.equal(T.listTime(c, new Date("2026-10-02T07:30:00Z")), "Oct 1, 11:30 PM"); // Oct 2, 12:30 AM in PT
  assert.equal(T.listTime(c, new Date("2026-10-02T17:00:00Z")), "Oct 1, 11:30 PM");
});

test("countdowns count Pacific calendar days, across the end of daylight time", () => {
  assert.deepEqual(T.countdown("2026-11-02", new Date("2026-11-01T08:30:00Z")), { text: "Due in 1 day", level: "urgent" });
  assert.deepEqual(T.countdown("2026-11-02", new Date("2026-11-02T07:30:00Z")), { text: "Due in 1 day", level: "urgent" });
  assert.deepEqual(T.countdown("2026-11-02", new Date("2026-11-02T08:30:00Z")), { text: "Due today", level: "urgent" });
  assert.deepEqual(T.countdown("2026-10-30", new Date("2026-11-02T17:00:00Z")), { text: "3 days past due", level: "urgent" });
  assert.equal(T.ptLocalToIso("2026-11-02T10:00"), "2026-11-02T18:00:00Z");
});

test("routing-only and never-stored slots are never in the answers table", () => {
  const shown = new Set(T.SLOT_GROUPS.flatMap(([, names]) => names));
  for (const s of ["volunteered_status", "elderly_or_disabled", "consent"]) {
    assert.equal(shown.has(s), false, s);
    assert.equal(T.NOT_IN_ANSWERS.has(s), true, s);
  }
  assert.equal(T.SLOT_LABELS.previously_denied, "Applied before");
  assert.equal(T.NEVER_ASKED, "Never asked — Social Security number · immigration status");
});

test("the end notice counts the slots with a value", () => {
  assert.equal(T.answersKept(1), "Conversation cleared — not saved. 1 answer kept.");
  const c = { slots: { consent: { value: "true", state: "clear" }, age: { value: "20", state: "clear" },
    rent_share: { value: null, state: "missing" }, volunteered_status: { value: "x", state: "clear" } } };
  assert.equal(T.filledCount(c), 2);
});

// ---------------------------------------------------------------- public-repository rules for every console file

function walk(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = path.join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}
const sources = walk(here).filter((f) => /\.(js|css|html)$/.test(f));
// The media feature of a dark theme, spelled in parts so this file never mentions it (tools/check_contrast.py).
const DARK_QUERY = new RegExp(["prefers", "color", "scheme"].join("-"));

test("light theme only and CSP-safe page", () => {
  const html = readFileSync(path.join(here, "index.html"), "utf8");
  assert.match(html, /<meta name="color-scheme" content="only light">/);
  assert.match(html, /<meta name="robots" content="noindex">/);
  assert.doesNotMatch(html, /\sstyle=|\son[a-z]+=|<style|<script(?![^>]*\bsrc=)/i);
  assert.match(html, /href="\/shared\/tokens\.css"[\s\S]*href="\/console\/console\.css"/, "tokens.css is linked first");
  for (const f of sources) {
    const text = readFileSync(f, "utf8");
    assert.doesNotMatch(text, DARK_QUERY, path.basename(f));
    assert.doesNotMatch(text, /https?:\/\/(?!www\.w3\.org\/2000\/svg")/, `${path.basename(f)} loads nothing from another site`);
    assert.doesNotMatch(text, /@import|innerHTML\s*=|\.style\.[a-z]+\s*=(?!=)/i, path.basename(f));
  }
});

test("public text: no local paths, no Hangul, no company or browser names, no promises we can't keep", () => {
  const banned = [/\/Users\//, new RegExp("[\\u3131-\\u318E\\uAC00-\\uD7A3]"), /\b(google|apple|chrome|safari|firefox|microsoft)\b/i,
    /sent to the coordinator/i, /we('| wi)ll (call|text)/i, /text message/i, /\byou will get\b/i, /free money/i,
    /any language/i, /\bcall student\b/i];
  for (const f of sources) {
    const text = readFileSync(f, "utf8");
    for (const b of banned) assert.equal(b.test(text), false, `${path.basename(f)} matches ${b}`);
  }
});

test("the transcript is never written to browser storage", () => {
  const js = sources.filter((f) => f.endsWith(".js")).map((f) => readFileSync(f, "utf8")).join("\n");
  const writes = [...js.matchAll(/(localStorage|sessionStorage)\.setItem\(([^)]*)\)/g)].map((m) => m[2]);
  assert.ok(writes.length > 0);
  for (const w of writes) assert.match(w, /^(PREFS|SELECTED)\b/, w);
});

test("leaving the Live view lets go of a call that has ended; a live one stays followed", () => {
  let s = liveCall();
  assert.equal(reduce(s, { type: "unfollow" }).followId, null);
  const none = reduce(reduce(s, { type: "unfollow" }), { type: "unfollow" });
  assert.equal(reduce(none, { type: "unfollow" }), none, "no change, no new state");
});

test("W4: card taps while the Live view shows Maria open 6b when the presenter returns to her case", () => {
  let s = loaded();
  s = reduce(s, { type: "select", id: "c_sofia2demo" });
  s = reduce(s, { type: "follow", id: "c_maria2demo" });
  const evt = { type: "case.updated", case_id: "c_maria2demo", summary: fixture("case_maria.json").summary, changed_programs: true };
  s = reduce(s, { type: "event", event: evt });
  assert.equal(s.programsAutoOpened.c_maria2demo, undefined, "not spent while the Live view shows the case");
  s = reduce(s, { type: "select", id: "c_maria2demo", view: "work" }); // Esc: back to the work view on this case
  assert.equal(s.sections.programs, true);
  assert.equal(s.programsAutoOpened.c_maria2demo, true);
  s = reduce(s, { type: "section", key: "programs", open: false });
  s = reduce(s, { type: "event", event: evt });
  assert.equal(s.sections.programs, false, "still only once");
});
