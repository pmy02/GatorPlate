// Talk page core: helpers, the page state machine and the call sequencing (docs/UI_SPEC.md A5; docs/BRAIN_API.md §4,
// §10). Run with `make test-web WEB=web/talk`.
import test from "node:test";
import assert from "node:assert/strict";

import { STRINGS } from "./strings.js";
import {
  CARD_URL, MAX_TEXT, TalkSession, canListen, canSend, cardHref, chunkSentences, cleanText, displayText, failureKind,
  initialState, micAction, micLabelKey, normalizeConfidence, reduce, resolveLang, speechPlan, spokenName, voiceOutcome,
} from "./core.js";

const reply = (over = {}) => ({
  say: "Got it.", ask: "How old are you?", end: false, end_reason: null, lang: "en", listen: "normal",
  expect: "open", interruptible: true, hold_s: 0, display: "Got it. How old are you?", choices: null,
  card_url: null, debug: null, ...over,
});

test("page language: ?lang= first, then a Spanish browser, else English", () => {
  assert.equal(resolveLang("?lang=es", "en-US"), "es");
  assert.equal(resolveLang("?lang=en", "es-MX"), "en");
  assert.equal(resolveLang("?lang=fr", "es-419"), "es");
  assert.equal(resolveLang("", "ES"), "es");
  assert.equal(resolveLang("", "de-DE"), "en");
  assert.equal(resolveLang("", undefined), "en");
});

test("text sent to the brain is trimmed and at most 1000 characters", () => {
  assert.equal(cleanText("  about   900\n a month "), "about 900 a month");
  assert.equal(cleanText("x".repeat(1500)).length, MAX_TEXT);
  assert.equal(cleanText(null), "");
});

test("confidence is the browser's value when it has one, else null", () => {
  assert.equal(normalizeConfidence(0.93), 0.93);
  assert.equal(normalizeConfidence(1), 1);
  assert.equal(normalizeConfidence(0), null);
  assert.equal(normalizeConfidence(undefined), null);
  assert.equal(normalizeConfidence(Number.NaN), null);
  assert.equal(normalizeConfidence(1.2), null);
});

test("speech is chunked sentence by sentence, amounts and Spanish hours stay whole", () => {
  // The web opening: a disclosure sentence, then the page's privacy line without its last sentence.
  const opening = "Hi, I'm refriGator, a student-built AI assistant, not an official SF State service. "
    + STRINGS.en.privacy.split(" We keep")[0];
  const chunks = chunkSentences(opening);
  assert.equal(chunks.length, 3);
  assert.ok(chunks[1].endsWith(")."), chunks[1]);
  assert.deepEqual(chunkSentences("You may get about $18.50 a month. The county decides."),
    ["You may get about $18.50 a month.", "The county decides."]);
  // "a. m." is never cut (a sentence that ends in one stays joined to the next: one longer utterance, no odd pause).
  const hours = "Atiende de lun a jue 8:30 a. m.–5 p. m., vie 8:30 a. m.–4 p. m. Escribe para pedir cita. Gracias.";
  const spoken = chunkSentences(hours);
  assert.ok(spoken[0].includes("8:30 a. m.–5 p. m., vie 8:30 a. m.–4 p. m."), spoken[0]);
  assert.equal(spoken[spoken.length - 1], "Gracias.");
  for (const c of spoken) assert.ok(!/\b[ap]\.$/.test(c), c);
  const long = `${"word ".repeat(80)}end.`;
  for (const c of chunkSentences(long, 60)) assert.ok(c.length <= 60, c);
  assert.equal(chunkSentences(long, 60).join(" "), long);
  assert.deepEqual(chunkSentences(""), []);
  assert.deepEqual(chunkSentences("¿Te parece bien?"), ["¿Te parece bien?"]);
});

test("speech plan: say follows the reply's interruptible flag, ask can always be cut off", () => {
  const plan = speechPlan(reply({ say: "Got it — about $900 a month from work.", interruptible: false,
    ask: "How much is your share of the rent each month?" }));
  assert.deepEqual(plan.map((c) => c.interruptible), [false, true]);
  const end = speechPlan(reply({ end: true, end_reason: "completed", ask: null, say: "Thanks. Good luck!",
    interruptible: false }));
  assert.deepEqual(end.map((c) => c.text), ["Thanks.", "Good luck!"]);
  assert.deepEqual(speechPlan(reply({ say: "", ask: null })), []);
});

test("speech plan: the voice says the display name as two words; the text keeps it", () => {
  const r = reply({ say: "Hi, I'm refriGator, a student-built AI assistant.", ask: "Thanks for using refriGator?" });
  const plan = speechPlan(r);
  assert.ok(plan.every((c) => !c.text.includes("refriGator")));
  assert.ok(plan.some((c) => c.text.includes("Refri Gator")));
  assert.equal(r.say, "Hi, I'm refriGator, a student-built AI assistant.");
  assert.equal(spokenName("a refrigerator"), "a refrigerator");
});

test("display text: the reply's display, else say and ask", () => {
  assert.equal(displayText(reply()), "Got it. How old are you?");
  assert.equal(displayText(reply({ display: null })), "Got it. How old are you?");
  assert.equal(displayText(reply({ display: null, say: "", ask: null })), "");
});

test("the card appears only as a same-origin card path", () => {
  assert.ok(CARD_URL.test("/c/fixtureMariaCard000001"));
  assert.equal(cardHref("/c/fixtureMariaCard000001"), "/c/fixtureMariaCard000001");
  assert.equal(cardHref("/c/fixtureMariaCard000001", { fixtures: true, lang: "es" }),
    "/card/?fixtures=1&token=fixture&lang=es");
  for (const bad of ["https://example.org/c/fixtureMariaCard000001", "javascript:alert(1)", "/c/short", "/c/../x",
    "//evil/c/fixtureMariaCard000001", null, undefined]) {
    assert.equal(cardHref(bad), null, String(bad));
  }
});

test("recognition errors map to the documented outcomes", () => {
  assert.equal(voiceOutcome("not-allowed"), "mic_blocked");
  assert.equal(voiceOutcome("service-not-allowed"), "no_voice");
  assert.equal(voiceOutcome("audio-capture"), "no_voice");
  assert.equal(voiceOutcome("network"), "network");
  assert.equal(voiceOutcome("no-speech"), "no_speech");
  assert.equal(voiceOutcome("aborted"), "aborted");
  assert.equal(voiceOutcome("language-not-supported"), "lang");
  assert.equal(voiceOutcome("something-new"), "no_voice");
});

test("API failures: 429 busy, a call that is gone, else retryable", () => {
  assert.equal(failureKind({ status: 429 }), "busy");
  for (const status of [401, 404, 409]) assert.equal(failureKind({ status }), "gone");
  for (const status of [0, 500, 502, 503, 422]) assert.equal(failureKind({ status }), "server");
  assert.equal(failureKind(new Error("x")), "server");
});

// ------------------------------------------------------------------------------------------- state machine

const run = (events, start = initialState()) => events.reduce(reduce, start);

test("voice start: connecting, probe ok, the opening is spoken without tap-to-interrupt", () => {
  let s = run([{ type: "start", mode: "voice", readAloud: true }]);
  assert.equal(s.phase, "connecting");
  assert.equal(s.voice, "unknown");
  assert.equal(micLabelKey(s), "connecting");
  assert.equal(micAction(s), null);
  s = run([{ type: "probe", outcome: "ok" },
    { type: "reply", reply: reply({ interruptible: false, expect: "yes_no", choices: ["Yes", "No"] }), speak: true }], s);
  assert.equal(s.phase, "speaking");
  assert.equal(s.interruptible, false);
  assert.equal(micLabelKey(s), "speaking");
  assert.equal(micAction(s), null);
  assert.equal(canListen(s), false);
  s = reduce(s, { type: "chunk", interruptible: true });
  assert.equal(micLabelKey(s), "speaking.tap");
  assert.equal(micAction(s), "interrupt");
  s = reduce(s, { type: "spoken" });
  assert.equal(s.phase, "ready");
  assert.equal(micLabelKey(s), "tap_to_talk");
  assert.equal(micAction(s), "listen");
});

test("probe outcomes switch to typing with one plain line", () => {
  for (const [outcome, notice] of [["mic_blocked", "err.mic_blocked"], ["no_voice", "err.no_voice"],
    ["network", "err.network"]]) {
    const s = run([{ type: "start", mode: "voice" }, { type: "probe", outcome }]);
    assert.equal(s.mode, "typing", outcome);
    assert.equal(s.voice, "off");
    assert.equal(s.notice, notice);
    assert.equal(micAction({ ...s, phase: "ready" }), null);
  }
});

test("listening: a heard answer is sent, silence asks to try again", () => {
  let s = run([{ type: "start", mode: "voice" }, { type: "probe", outcome: "ok" },
    { type: "reply", reply: reply(), speak: false }]);
  assert.equal(s.phase, "ready");
  s = reduce(s, { type: "listen" });
  assert.equal(s.phase, "listening");
  assert.equal(micLabelKey(s), "listening");
  assert.equal(micAction(s), "stop");
  const quiet = reduce(s, { type: "no_speech" });
  assert.equal(quiet.phase, "ready");
  assert.equal(quiet.notice, "err.no_speech");
  assert.equal(reduce(quiet, { type: "listen" }).notice, null);
  s = reduce(s, { type: "send" });
  assert.equal(s.phase, "thinking");
  assert.equal(micLabelKey(s), "thinking");
  assert.equal(canSend(s), false);
  s = reduce(s, { type: "slow" });
  assert.equal(s.notice, "err.slow");
  s = reduce(s, { type: "reply", reply: reply({ say: "Thanks." }), speak: false });
  assert.equal(s.phase, "ready");
  assert.equal(s.notice, null);
});

test("a recognition error later in the call keeps the conversation in typing mode", () => {
  let s = run([{ type: "start", mode: "voice" }, { type: "probe", outcome: "ok" },
    { type: "reply", reply: reply(), speak: false }, { type: "listen" }]);
  s = reduce(s, { type: "voice_error", outcome: "mic_blocked" });
  assert.equal(s.phase, "ready");
  assert.equal(s.mode, "typing");
  assert.equal(s.notice, "err.mic_blocked");
  assert.equal(canSend(s), true);
  // The voice notice stays while replies arrive, until the student sends something.
  s = reduce(s, { type: "reply", reply: reply(), speak: false });
  assert.equal(s.notice, "err.mic_blocked");
  s = reduce(s, { type: "send" });
  assert.equal(s.notice, null);
});

test("failures: retry after a server error, ended when the call is gone, busy at the start", () => {
  const ready = run([{ type: "start", mode: "typing" }, { type: "reply", reply: reply(), speak: false }]);
  const failed = run([{ type: "send" }, { type: "fail", kind: "server" }], ready);
  assert.equal(failed.phase, "ready");
  assert.equal(failed.failed, true);
  assert.equal(failed.notice, "err.server");
  const gone = run([{ type: "send" }, { type: "fail", kind: "gone" }], ready);
  assert.equal(gone.phase, "ended");
  const busy = run([{ type: "start", mode: "typing" }, { type: "fail", kind: "busy" }]);
  assert.equal(busy.phase, "intro");
  assert.equal(busy.notice, "err.busy");
  const down = run([{ type: "start", mode: "voice" }, { type: "fail", kind: "server" }]);
  assert.equal(down.phase, "intro");
  assert.equal(down.notice, "err.server");
});

test("the end: card ready (completed with a card), else conversation ended", () => {
  const card = "/c/fixtureMariaCard000001";
  let s = run([{ type: "start", mode: "typing" },
    { type: "reply", reply: reply({ card_url: card, ask: "Anything else I can help with?" }), speak: false }]);
  assert.equal(s.cardUrl, card);
  assert.equal(s.phase, "ready");
  s = reduce(s, { type: "send" });
  s = reduce(s, { type: "reply", speak: true, reply: reply({ end: true, end_reason: "completed", ask: null,
    interruptible: false, say: "Thanks for using refriGator. Good luck!", card_url: card }) });
  assert.equal(s.phase, "speaking");
  s = reduce(s, { type: "spoken" });
  assert.equal(s.phase, "done");
  assert.equal(micLabelKey(s), null);
  const declined = run([{ type: "start", mode: "typing" }, { type: "reply", speak: false,
    reply: reply({ end: true, end_reason: "declined", ask: null, interruptible: false }) }]);
  assert.equal(declined.phase, "ended");
  const restarted = reduce(declined, { type: "restart" });
  assert.equal(restarted.phase, "intro");
  assert.equal(restarted.cardUrl, null);
});

test("typing start keeps read-aloud off and the voice unknown until the mic is used", () => {
  const s = run([{ type: "start", mode: "typing", readAloud: false }]);
  assert.equal(s.mode, "typing");
  assert.equal(s.readAloud, false);
  assert.equal(s.voice, "unknown");
  const v = reduce(s, { type: "read_aloud", on: true });
  assert.equal(v.readAloud, true);
});

// ------------------------------------------------------------------------------------------- call sequencing

function fakeApi(replies) {
  const calls = [];
  let i = 0;
  const request = async (method, path, opts = {}) => {
    calls.push({ method, path, ...opts });
    if (path === "/api/web/sessions") {
      return { call_id: "0a00000000000000000000000000f001", token: "fixture-web-token-maria-000001",
        expires_at: "2026-10-02T17:30:00Z" };
    }
    if (path.endsWith("/end")) return {};
    const r = replies[Math.min(i, replies.length - 1)];
    i += 1;
    if (r instanceof Error) throw r;
    return r;
  };
  return { request, calls };
}

test("session: start is seq 0, every new utterance takes the next seq, a retry re-sends the same body", async () => {
  let clock = 1000;
  const boom = Object.assign(new Error("down"), { status: 503 });
  const { request, calls } = fakeApi([reply(), reply(), boom, reply(), reply()]);
  const s = new TalkSession({ request, now: () => clock });
  await s.open("es");
  assert.deepEqual(calls[0].body, { lang: "es" });
  await s.start();
  assert.equal(calls[1].path, "/v1/calls/0a00000000000000000000000000f001/start");
  assert.deepEqual(calls[1].body, { v: 1, seq: 0, channel: "web", lang: "es", test: false });
  assert.equal(calls[1].token, "fixture-web-token-maria-000001");
  await s.turn("Sí", { typed: true, lang: "es" });
  assert.deepEqual(calls[2].body, { v: 1, seq: 1, lang: "es", event: "utterance", text: "Sí", masked: false,
    confidence: null, interrupted: false, typed: true });
  await assert.rejects(s.turn("tengo 19 años", { confidence: 0.82, interrupted: true, lang: "es" }));
  assert.equal(calls[3].body.seq, 2);
  assert.ok(s.pending);
  await s.retry();
  assert.equal(calls[4].body, calls[3].body);
  assert.equal(s.pending, null);
  await s.turn("vivo con mis papás", { lang: "es" });
  assert.equal(calls[5].body.seq, 3);
  clock = 64000;
  assert.equal(await s.end("completed"), true);
  const end = calls[6];
  assert.equal(end.path, "/v1/calls/0a00000000000000000000000000f001/end");
  assert.deepEqual(end.body, { v: 1, reason: "completed", turns: 3, duration_ms: 63000 });
  assert.equal(await s.end("completed"), false);
  assert.equal(s.beacon(), null);
  assert.equal(calls.length, 7);
});

test("session: the card path sticks once set; pagehide sends caller_hangup once", async () => {
  const card = "/c/fixtureMariaCard000001";
  const { request } = fakeApi([reply(), reply({ card_url: card }), reply({ card_url: null })]);
  const s = new TalkSession({ request, now: () => 0 });
  assert.equal(s.beacon(), null);
  await s.open("en");
  await s.start();
  await s.turn("yes");
  assert.equal(s.cardUrl, card);
  await s.turn("no");
  assert.equal(s.cardUrl, card);
  const b = s.beacon();
  assert.equal(b.url, "/v1/calls/0a00000000000000000000000000f001/end");
  assert.equal(b.body.reason, "caller_hangup");
  assert.equal(b.body.turns, 2);
  assert.equal(b.token, "fixture-web-token-maria-000001");
  assert.equal(s.beacon(), null);
});

test("session: a malformed session answer is an error", async () => {
  const s = new TalkSession({ request: async () => ({ call_id: 7 }) });
  await assert.rejects(s.open("en"));
});
