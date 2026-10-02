// Talk page voice: the runtime probe, push-to-talk recognition, voice choice and sentence-by-sentence speech
// (docs/UI_SPEC.md A5.2–A5.5), with stub speech objects. Run with `make test-web WEB=web/talk`.
import test from "node:test";
import assert from "node:assert/strict";

import { Speaker, listenOnce, localRecognition, pickVoice, probeRecognition, recognitionTags } from "./voice.js";

const later = (fn, ms = 1) => setTimeout(fn, ms);

// A stub recognition class: each new instance runs the next behavior on start().
function recognition(...behaviors) {
  const instances = [];
  class StubRecognition {
    constructor() {
      this.behavior = behaviors[Math.min(instances.length, behaviors.length - 1)];
      this.aborted = false;
      instances.push(this);
    }
    start() { this.behavior(this); }
    stop() { later(() => { if (this.onend) this.onend(); }); }
    abort() {
      this.aborted = true;
      later(() => {
        if (this.onerror) this.onerror({ error: "aborted" });
        if (this.onend) this.onend();
      });
    }
  }
  return { Ctor: StubRecognition, instances };
}

const starts = (rec) => later(() => rec.onstart && rec.onstart(), 5);
const fails = (error) => (rec) => later(() => {
  if (rec.onerror) rec.onerror({ error });
  if (rec.onend) rec.onend();
});
const silent = () => {};

function result(transcript, { isFinal = true, confidence = 0.9 } = {}) {
  const r = [{ transcript, confidence }];
  r.isFinal = isFinal;
  return r;
}

test("recognition tags: English en-US; Spanish es-US, then es-MX, then es-ES", () => {
  assert.deepEqual(recognitionTags("en"), ["en-US"]);
  assert.deepEqual(recognitionTags("es"), ["es-US", "es-MX", "es-ES"]);
  assert.deepEqual(recognitionTags("es", 1), ["es-MX", "es-ES"]);
  assert.deepEqual(recognitionTags("es", 9), ["es-ES"]);
});

test("probe: no speech recognition in this browser → typing", async () => {
  assert.deepEqual(await probeRecognition({ env: {} }), { outcome: "no_voice", lang: null });
});

test("probe: a start event means voice works; the probe recognition is stopped", async () => {
  const { Ctor, instances } = recognition(starts);
  const out = await probeRecognition({ env: { webkitSpeechRecognition: Ctor }, langs: ["en-US"], timeoutMs: 200 });
  assert.deepEqual(out, { outcome: "ok", lang: "en-US" });
  assert.equal(instances[0].lang, "en-US");
  assert.equal(instances[0].continuous, false);
  assert.equal(instances[0].aborted, true);
});

test("probe: blocked microphone, unavailable service, no microphone, no network", async () => {
  for (const [error, outcome] of [["not-allowed", "mic_blocked"], ["service-not-allowed", "no_voice"],
    ["audio-capture", "no_voice"], ["network", "network"]]) {
    const { Ctor } = recognition(fails(error));
    const out = await probeRecognition({ env: { SpeechRecognition: Ctor }, timeoutMs: 200 });
    assert.equal(out.outcome, outcome, error);
  }
});

test("probe: no start event within the time limit → typing", async () => {
  const { Ctor, instances } = recognition(silent);
  const t0 = Date.now();
  const out = await probeRecognition({ env: { SpeechRecognition: Ctor }, timeoutMs: 30 });
  assert.equal(out.outcome, "no_voice");
  assert.ok(Date.now() - t0 >= 25);
  assert.equal(instances[0].aborted, true);
});

test("probe: a constructor or start() that throws → typing", async () => {
  const throwing = { SpeechRecognition: class { constructor() { throw new Error("no"); } } };
  assert.equal((await probeRecognition({ env: throwing, timeoutMs: 50 })).outcome, "no_voice");
  const { Ctor } = recognition(() => { throw new Error("start failed"); });
  assert.equal((await probeRecognition({ env: { SpeechRecognition: Ctor }, timeoutMs: 50 })).outcome, "no_voice");
});

test("probe: Spanish falls back from es-US to es-MX when a language is not supported", async () => {
  const { Ctor, instances } = recognition(fails("language-not-supported"), starts);
  const out = await probeRecognition({ env: { SpeechRecognition: Ctor }, langs: recognitionTags("es"),
    timeoutMs: 200 });
  assert.deepEqual(out, { outcome: "ok", lang: "es-MX" });
  assert.deepEqual(instances.map((r) => r.lang), ["es-US", "es-MX"]);
});

test("probe: while the microphone prompt is open the page waits for the answer", async () => {
  const { Ctor } = recognition((rec) => later(() => rec.onstart(), 120));
  const permissions = { query: async () => ({ state: "prompt" }) };
  const out = await probeRecognition({ env: { SpeechRecognition: Ctor, navigator: { permissions } },
    timeoutMs: 40, promptMs: 1000 });
  assert.equal(out.outcome, "ok");
});

test("probe: a refused permission is a blocked microphone, unless recognition starts anyway", async () => {
  // Any state other than granted or prompt is the refused state.
  const permissions = { query: async () => ({ state: "refused" }) };
  let { Ctor } = recognition(silent);
  let out = await probeRecognition({ env: { SpeechRecognition: Ctor, navigator: { permissions } }, timeoutMs: 1500 });
  assert.equal(out.outcome, "mic_blocked");
  ({ Ctor } = recognition(starts));
  out = await probeRecognition({ env: { SpeechRecognition: Ctor, navigator: { permissions } }, timeoutMs: 1500 });
  assert.equal(out.outcome, "ok");
});

test("listen: interim words, then the final text with the browser's confidence", async () => {
  const { Ctor, instances } = recognition((rec) => {
    later(() => rec.onstart(), 1);
    later(() => rec.onresult({ results: [result("I make about", { isFinal: false })] }), 3);
    later(() => rec.onresult({ results: [result("I make about 900 a month", { confidence: 0.93 })] }), 6);
    later(() => rec.onend(), 9);
  });
  const seen = [];
  let started = false;
  const l = listenOnce({ env: { SpeechRecognition: Ctor }, lang: "en-US", onInterim: (x) => seen.push(x),
    onStart: () => { started = true; } });
  assert.deepEqual(await l.result, { text: "I make about 900 a month", confidence: 0.93 });
  assert.equal(started, true);
  assert.deepEqual(seen[0], { final: "", interim: "I make about" });
  assert.equal(instances[0].interimResults, true);
  assert.equal(instances[0].continuous, false);
  assert.equal(instances[0].maxAlternatives, 1);
  assert.equal(instances[0].processLocally, undefined);
});

test("listen: nothing heard, a blocked microphone, an unsupported language", async () => {
  let { Ctor } = recognition((rec) => { later(() => rec.onstart()); later(() => rec.onend(), 3); });
  assert.deepEqual(await listenOnce({ env: { SpeechRecognition: Ctor } }).result, { error: "no_speech" });
  ({ Ctor } = recognition(fails("no-speech")));
  assert.deepEqual(await listenOnce({ env: { SpeechRecognition: Ctor } }).result, { error: "no_speech" });
  ({ Ctor } = recognition(fails("not-allowed")));
  assert.deepEqual(await listenOnce({ env: { SpeechRecognition: Ctor } }).result, { error: "mic_blocked" });
  ({ Ctor } = recognition(fails("language-not-supported")));
  assert.deepEqual(await listenOnce({ env: { SpeechRecognition: Ctor } }).result, { error: "lang" });
  assert.deepEqual(await listenOnce({ env: {} }).result, { error: "no_voice" });
});

test("listen: tapping again stops and keeps the words heard so far; abort discards them", async () => {
  let { Ctor } = recognition((rec) => {
    later(() => rec.onstart());
    later(() => rec.onresult({ results: [result("eleven hundred", { isFinal: false })] }), 2);
  });
  let l = listenOnce({ env: { SpeechRecognition: Ctor } });
  await new Promise((r) => setTimeout(r, 10));
  l.stop();
  assert.deepEqual(await l.result, { text: "eleven hundred", confidence: null });
  ({ Ctor } = recognition((rec) => {
    later(() => rec.onstart());
    later(() => rec.onresult({ results: [result("eleven", { isFinal: false })] }), 2);
  }));
  l = listenOnce({ env: { SpeechRecognition: Ctor } });
  await new Promise((r) => setTimeout(r, 10));
  l.abort();
  assert.deepEqual(await l.result, { error: "aborted" });
});

test("listen: on-device recognition is requested only when asked", async () => {
  const { Ctor, instances } = recognition((rec) => { later(() => rec.onstart()); later(() => rec.onend(), 2); });
  await listenOnce({ env: { SpeechRecognition: Ctor }, processLocally: true }).result;
  assert.equal(instances[0].processLocally, true);
});

test("on-device check: only 'available' counts, nothing is ever installed", async () => {
  const make = (answer) => {
    const C = class {};
    C.available = async () => answer;
    C.install = () => { throw new Error("must not install"); };
    return { SpeechRecognition: C };
  };
  assert.equal(await localRecognition(make("available"), "en-US"), true);
  assert.equal(await localRecognition(make("downloadable"), "en-US"), false);
  assert.equal(await localRecognition(make("unavailable"), "es-US"), false);
  assert.equal(await localRecognition({ SpeechRecognition: class {} }, "en-US"), false);
  const slow = { SpeechRecognition: Object.assign(class {}, { available: () => new Promise(() => {}) }) };
  assert.equal(await localRecognition(slow, "en-US", 20), false);
});

test("voice choice: the regional voice first, then the first voice of the same language", () => {
  const voices = [{ name: "a", lang: "en-GB" }, { name: "b", lang: "es-ES" }, { name: "c", lang: "es_MX" },
    { name: "d", lang: "en-US" }];
  assert.equal(pickVoice(voices, "en").name, "d");
  assert.equal(pickVoice(voices, "es").name, "c");
  assert.equal(pickVoice([{ name: "x", lang: "es-AR" }], "es").name, "x");
  assert.equal(pickVoice([{ name: "y", lang: "en-AU" }], "en").name, "y");
  assert.equal(pickVoice([{ name: "z", lang: "fr-FR" }], "es"), null);
  assert.equal(pickVoice(null, "en"), null);
});

function synthesis({ startDelay = 1, voices = [] } = {}) {
  const spoken = [];
  const synth = {
    cancels: 0,
    getVoices() { return voices; },
    addEventListener() {},
    speak(u) {
      spoken.push(u);
      if (startDelay === null) return;
      later(() => {
        if (u.onstart) u.onstart();
        later(() => { if (u.onend) u.onend(); }, 2);
      }, startDelay);
    },
    cancel() { this.cancels += 1; },
  };
  class Utterance { constructor(text) { this.text = text; } }
  return { env: { speechSynthesis: synth, SpeechSynthesisUtterance: Utterance }, spoken, synth };
}

test("speaker: sentence by sentence, in the reply's language and voice", async () => {
  const { env, spoken } = synthesis({ voices: [{ lang: "es-ES" }, { lang: "es-MX" }, { lang: "en-US" }] });
  const speaker = new Speaker({ env });
  assert.equal(speaker.available, true);
  const flags = [];
  const out = await speaker.speak([{ text: "Gracias.", interruptible: true }, { text: "¿Cuántos años tienes?",
    interruptible: true }], "es", { onChunk: (i, c) => flags.push([i, c.interruptible]) });
  assert.equal(out, "done");
  assert.deepEqual(spoken.map((u) => u.text), ["Gracias.", "¿Cuántos años tienes?"]);
  assert.equal(spoken[0].lang, "es-MX");
  assert.equal(spoken[0].voice.lang, "es-MX");
  assert.deepEqual(flags, [[0, true], [1, true]]);
});

test("speaker: no start within the limit → 'Can't hear?' once, the rest is skipped", async () => {
  const { env, spoken } = synthesis({ startDelay: null });
  let hints = 0;
  const speaker = new Speaker({ env, onNoStart: () => { hints += 1; }, startMs: 20 });
  const out = await speaker.speak([{ text: "One.", interruptible: false }, { text: "Two.", interruptible: true }], "en");
  assert.equal(out, "silent");
  assert.equal(hints, 1);
  assert.equal(spoken.length, 1);
  assert.equal(spoken[0].lang, "en-US");
});

test("speaker: cancel stops at once; a newer reply replaces the old one", async () => {
  const { env } = synthesis({ startDelay: null });
  const speaker = new Speaker({ env, startMs: 5000 });
  const first = speaker.speak([{ text: "A long sentence.", interruptible: true }], "en");
  speaker.cancel();
  assert.equal(await first, "cancelled");
  const second = speaker.speak([{ text: "Old.", interruptible: true }], "en");
  const third = speaker.speak([{ text: "New.", interruptible: true }], "en");
  assert.equal(await second, "cancelled");
  speaker.cancel();
  assert.equal(await third, "cancelled");
});

test("speaker: unlock speaks a silent utterance inside the tap; no synthesis → nothing to do", async () => {
  const { env, spoken } = synthesis();
  new Speaker({ env }).unlock();
  assert.equal(spoken.length, 1);
  assert.equal(spoken[0].volume, 0);
  const none = new Speaker({ env: {} });
  assert.equal(none.available, false);
  none.unlock();
  assert.equal(await none.speak([{ text: "Hi.", interruptible: true }], "en"), "done");
});
