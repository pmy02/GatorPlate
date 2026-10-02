// Talk page edge cases (docs/UI_SPEC.md A5; docs/BRAIN_API.md §4, §6, §10): the `interrupted` flag, the reply's
// `interruptible`, holds, empty replies, a page restored from the back/forward cache, and retries that keep their seq.
// Run with `make test-web WEB=web/talk`.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  TalkSession, canListen, canSend, initialState, micAction, reaskReply, reduce, shouldAutoListen, speechPlan,
} from "./core.js";

const read = (rel) => JSON.parse(readFileSync(new URL(rel, import.meta.url), "utf8"));
const schema = read("../../contracts/brain_api.v1.schema.json");

const reply = (over = {}) => ({
  say: "Got it.", ask: "How old are you?", end: false, end_reason: null, lang: "en", listen: "normal",
  expect: "open", interruptible: true, hold_s: 0, display: "Got it. How old are you?", choices: null,
  card_url: null, debug: null, ...over,
});

const run = (events, start = initialState()) => events.reduce(reduce, start);
const voiceReady = () => run([{ type: "start", mode: "voice", readAloud: true }, { type: "probe", outcome: "ok" }]);
const speaking = (over = {}) => reduce(voiceReady(), { type: "reply", reply: reply(over), speak: true });

// ------------------------------------------------------------------------------------------- `interrupted`

test("interrupted: true only for the answer that cut the voice off", () => {
  // Tap during the voice, then speak: interrupted.
  let s = run([{ type: "listen" }, { type: "send" }], speaking());
  assert.equal(s.phase, "thinking");
  assert.equal(s.sentInterrupted, true);
  // Typed (or a quick reply) while the voice speaks: interrupted.
  s = reduce(speaking(), { type: "send" });
  assert.equal(s.sentInterrupted, true);
  // An answer after the voice ended on its own: not interrupted.
  s = run([{ type: "spoken" }, { type: "listen" }, { type: "send" }], speaking());
  assert.equal(s.sentInterrupted, false);
  // The next turn starts clean.
  s = run([{ type: "reply", reply: reply(), speak: false }, { type: "listen" }, { type: "send" }], s);
  assert.equal(s.sentInterrupted, false);
});

test("interrupted does not leak: a cut-off voice followed by silence, an aborted listen or a new call", () => {
  // Interrupt, hear nothing, tap again later and answer: that answer did not interrupt anything.
  let s = run([{ type: "listen" }, { type: "no_speech" }, { type: "listen" }, { type: "send" }], speaking());
  assert.equal(s.sentInterrupted, false);
  s = run([{ type: "listen" }, { type: "stop_listening" }, { type: "listen" }, { type: "send" }], speaking());
  assert.equal(s.sentInterrupted, false);
  s = run([{ type: "listen" }, { type: "voice_error", outcome: "network" }, { type: "send" }], speaking());
  assert.equal(s.sentInterrupted, false);
  // "Start again" and a new start never carry it over.
  const cut = reduce(speaking(), { type: "listen" });
  assert.equal(cut.interrupt, true);
  assert.equal(reduce(cut, { type: "restart" }).interrupt, false);
  assert.equal(reduce(cut, { type: "start", mode: "typing" }).interrupt, false);
  assert.equal(reduce(cut, { type: "reply", reply: reply(), speak: false }).interrupt, false);
});

test("a mic tap that stops the voice before listening (first-time probe) marks the next answer", () => {
  let s = reduce(speaking(), { type: "interrupt" });
  assert.equal(s.phase, "ready");
  assert.equal(s.interrupt, true);
  s = run([{ type: "listen" }, { type: "send" }], s);
  assert.equal(s.sentInterrupted, true);
});

test("interruptible:false — no listening, no interrupt; the question part can be cut off", () => {
  const opening = reply({ interruptible: false, say: "Hi, I'm GatorPlate. GatorPlate only gets the text.",
    ask: "Is that okay?", choices: ["Yes", "No"] });
  let s = reduce(voiceReady(), { type: "reply", reply: opening, speak: true });
  assert.equal(s.interruptible, false);
  assert.equal(canListen(s), false);
  assert.equal(micAction(s), null);
  assert.deepEqual(reduce(s, { type: "listen" }), s);
  assert.deepEqual(reduce(s, { type: "interrupt" }), s);
  // A quick reply or Send can't cut it off either: they wait for the question part.
  assert.equal(canSend(s), false);
  assert.deepEqual(reduce(s, { type: "send" }), s);
  const plan = speechPlan(opening);
  assert.deepEqual(plan.map((c) => c.interruptible), [false, false, true]);
  s = reduce(s, { type: "chunk", interruptible: plan[2].interruptible });
  assert.equal(micAction(s), "interrupt");
  assert.equal(canSend(s), true);
  // Read aloud switched off (or the voice done): the answer goes out at once.
  assert.equal(canSend(reduce(reduce(voiceReady(), { type: "reply", reply: opening, speak: false }), { type: "spoken" })),
    true);
  // An end reply is never interruptible and never spoken with its (null) question.
  const bye = reply({ end: true, end_reason: "completed", ask: null, interruptible: false, say: "Good luck!" });
  assert.ok(speechPlan(bye).every((c) => !c.interruptible));
});

// ------------------------------------------------------------------------------------------- listening again

test("auto-listen: after a question or an empty reply, in voice mode with read aloud on only", () => {
  const ok = { mode: "voice", voice: "ok", readAloud: true };
  assert.equal(shouldAutoListen(ok, reply()), true);
  assert.equal(shouldAutoListen(ok, reply({ say: "", ask: null, display: "" })), true, "empty reply: keep listening");
  assert.equal(shouldAutoListen(ok, reply({ say: "Take your time.", ask: null, hold_s: 30 })), false, "hold");
  assert.equal(shouldAutoListen(ok, reply({ say: "Noted.", ask: null })), false, "a statement without a question");
  assert.equal(shouldAutoListen(ok, reply({ end: true, end_reason: "completed", ask: null, interruptible: false })),
    false);
  assert.equal(shouldAutoListen({ ...ok, mode: "typing" }, reply()), false);
  assert.equal(shouldAutoListen({ ...ok, voice: "off" }, reply()), false);
  assert.equal(shouldAutoListen({ ...ok, voice: "unknown" }, reply()), false);
  assert.equal(shouldAutoListen({ ...ok, readAloud: false }, reply()), false);
  assert.equal(shouldAutoListen(null, reply()), false);
});

test("an empty reply keeps the conversation open and changes nothing on screen", () => {
  const s = reduce(voiceReady(), { type: "reply", reply: reply({ say: "", ask: null, display: "" }), speak: true });
  assert.equal(s.phase, "ready");
  assert.equal(canSend(s), true);
  assert.deepEqual(speechPlan(reply({ say: "", ask: null })), []);
});

// A tiny reader for the BrainReply rules the re-ask must keep (docs/BRAIN_API.md §6).
function brainReplyProblems(r) {
  const def = schema.$defs.BrainReply;
  const problems = [];
  for (const key of def.required) if (!(key in r)) problems.push(`missing ${key}`);
  for (const key of Object.keys(r)) if (!(key in def.properties)) problems.push(`extra ${key}`);
  if (r.end) problems.push("end");
  if (r.end_reason !== null) problems.push("end_reason");
  if (r.hold_s !== 0) problems.push("hold_s");
  if (r.choices !== null && !(Array.isArray(r.choices) && r.choices.length >= 1 && r.choices.length <= 6)) {
    problems.push("choices");
  }
  if (r.choices && !r.ask) problems.push("choices without ask");
  return problems;
}

test("hold: when the hold ends the last question comes back with its quick replies, interruptible", () => {
  const question = reply({ say: "Got it — about $900 a month from work.", ask: "How much is your share of the rent?",
    expect: "number", listen: "long", interruptible: false, choices: ["I don't pay rent"] });
  const again = reaskReply(question);
  assert.deepEqual(brainReplyProblems(again), []);
  assert.equal(again.say, "");
  assert.equal(again.ask, question.ask);
  assert.equal(again.display, question.ask);
  assert.deepEqual(again.choices, ["I don't pay rent"]);
  assert.notEqual(again.choices, question.choices, "a copy, not the same array");
  assert.equal(again.interruptible, true);
  assert.equal(again.expect, "number");
  assert.equal(again.listen, "long");
  assert.equal(again.lang, "en");
  assert.deepEqual(speechPlan(again).map((c) => c.interruptible), [true]);
  // Spoken through the normal path: the mic is closed while it speaks, then the page may listen again.
  let s = run([{ type: "reply", reply: reply({ say: "Take your time.", ask: null, hold_s: 30, display: "Take your time." }),
    speak: true }, { type: "spoken" }], voiceReady());
  assert.equal(s.phase, "ready");
  s = reduce(s, { type: "reply", reply: again, speak: true });
  assert.equal(s.phase, "speaking");
  assert.equal(shouldAutoListen(s, again), true);
  assert.equal(reaskReply(null), null);
  assert.equal(reaskReply(reply({ ask: null })), null);
  assert.equal(reaskReply(reply({ choices: [] })).choices, null);
});

// ------------------------------------------------------------------------------------------- leaving the page

test("back from the back/forward cache after pagehide: the call shows as ended (or done after its last reply)", () => {
  const card = "/c/fixtureMariaCard000001";
  let s = reduce(voiceReady(), { type: "reply", reply: reply({ card_url: card }), speak: false });
  const left = reduce(s, { type: "left" });
  assert.equal(left.phase, "ended");
  assert.equal(left.notice, null);
  assert.equal(left.cardUrl, card, "the card button stays");
  s = reduce(s, { type: "send" });
  assert.equal(reduce(s, { type: "left" }).phase, "ended", "a turn in flight");
  const last = reply({ end: true, end_reason: "completed", ask: null, interruptible: false, card_url: card });
  s = reduce(s, { type: "reply", reply: last, speak: true });
  assert.equal(reduce(s, { type: "left" }).phase, "done");
  for (const phase of ["intro", "done", "ended"]) {
    const x = { ...initialState(), phase };
    assert.deepEqual(reduce(x, { type: "left" }), x);
  }
});

// ------------------------------------------------------------------------------------------- call sequencing

function api(script) {
  const calls = [];
  let i = 0;
  const request = async (method, path, opts = {}) => {
    calls.push({ method, path, body: opts.body === undefined ? undefined : structuredClone(opts.body) });
    if (path === "/api/web/sessions") {
      return { call_id: "0a00000000000000000000000000f001", token: "fixture-web-token-maria-000001",
        expires_at: "2026-10-02T17:30:00Z" };
    }
    if (path.endsWith("/end")) return {};
    const r = script[Math.min(i, script.length - 1)];
    i += 1;
    if (r instanceof Error) throw r;
    return r;
  };
  return { request, calls };
}

test("idempotency: a retry re-sends the identical body (same seq, same interrupted flag); a new answer moves on", async () => {
  const down = Object.assign(new Error("down"), { status: 503 });
  const { request, calls } = api([reply(), down, down, reply(), down, reply()]);
  const s = new TalkSession({ request, now: () => 0 });
  await s.open("en");
  await s.start();
  await assert.rejects(s.turn("about 900 a month", { interrupted: true, confidence: 0.6 }));
  await assert.rejects(s.retry());
  await s.retry();
  const turns = calls.filter((c) => c.path.endsWith("/turn"));
  assert.equal(turns.length, 3);
  for (const t of turns) assert.deepEqual(t.body, turns[0].body);
  assert.equal(turns[0].body.seq, 1);
  assert.equal(turns[0].body.interrupted, true);
  assert.equal(turns[0].body.confidence, 0.6);
  // A failed turn the student answers with something new: the next seq (the brain accepts gaps).
  await assert.rejects(s.turn("eleven hundred"));
  await s.turn("eleven hundred, sorry");
  const after = calls.filter((c) => c.path.endsWith("/turn")).slice(3).map((c) => c.body.seq);
  assert.deepEqual(after, [2, 3]);
  await assert.rejects(s.retry(), "nothing left to retry after a reply");
});

test("end: once, with the reply's reason; never before /start; the page leaving after the end sends nothing", async () => {
  const { request, calls } = api([reply(), reply({ end: true, end_reason: "declined", ask: null, interruptible: false })]);
  const s = new TalkSession({ request, now: () => 0 });
  assert.equal(await s.end("caller_hangup"), false, "no call yet");
  await s.open("en");
  assert.equal(s.beacon(), null, "a session without /start has no call to end");
  await s.start();
  const last = await s.turn("no");
  assert.equal(last.end, true);
  assert.equal(s.ended, true);
  assert.equal(s.endReason, "declined");
  assert.equal(await s.end(s.endReason), true);
  assert.equal(s.beacon(), null);
  const ends = calls.filter((c) => c.path.endsWith("/end"));
  assert.equal(ends.length, 1);
  assert.equal(ends[0].body.reason, "declined");
  assert.ok(["completed", "declined", "no_input"].includes(ends[0].body.reason));
});

test("a turn body has exactly the contract's utterance fields, in the page's current language", async () => {
  const { request, calls } = api([reply(), reply({ lang: "es" })]);
  const s = new TalkSession({ request, now: () => 0 });
  await s.open("en");
  await s.start();
  await s.turn("  ¿Puedo   hablar en español?  ", { lang: "es", typed: true, confidence: 0 });
  const body = calls.find((c) => c.path.endsWith("/turn")).body;
  assert.deepEqual(Object.keys(body).sort(),
    ["confidence", "event", "interrupted", "lang", "masked", "seq", "text", "typed", "v"]);
  assert.equal(body.text, "¿Puedo hablar en español?");
  assert.equal(body.lang, "es");
  assert.equal(body.masked, false, "the brain redacts digits itself on the web");
  assert.equal(body.confidence, null);
  const props = schema.$defs.TurnRequest.properties;
  for (const key of Object.keys(body)) assert.ok(key in props, key);
  assert.equal(s.lang, "es", "later turns and /end use the new language");
});
