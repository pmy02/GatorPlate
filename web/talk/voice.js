// Web voice for the talk page (docs/UI_SPEC.md A5.2–A5.5): the browser's own Web Speech API only. GatorPlate never
// receives audio; recognition gives the page text, synthesis speaks the reply. Every function takes `env` (the
// window) so tests can pass stubs.

import { REC_LANGS, voiceOutcome } from "./core.js";

export const PROBE_TIMEOUT_MS = 1500;   // no start event within 1.5 s → typing
export const PROMPT_TIMEOUT_MS = 30000; // while the browser's microphone prompt is open
export const SPEECH_START_MS = 2000;    // no speech start within 2 s → "Can't hear? Turn up the volume."
const BLOCKED_GRACE_MS = 300;           // the microphone permission is refused and no error event came

export function recognitionCtor(env = globalThis) {
  return (env && (env.SpeechRecognition || env.webkitSpeechRecognition)) || null;
}

// The recognition tags to try for a page language, starting at a remembered index.
export function recognitionTags(lang, from = 0) {
  const tags = REC_LANGS[lang] || REC_LANGS.en;
  return tags.slice(Math.min(from, tags.length - 1));
}

// Runtime probe, run from the Start tap (so the microphone prompt belongs to that gesture): start a recognition and
// wait for its start event. Resolves {outcome, lang}: outcome ok · mic_blocked · no_voice · network.
export function probeRecognition({ env = globalThis, langs = ["en-US"], timeoutMs = PROBE_TIMEOUT_MS,
  promptMs = PROMPT_TIMEOUT_MS } = {}) {
  const Ctor = recognitionCtor(env);
  if (!Ctor) return Promise.resolve({ outcome: "no_voice", lang: null });
  return new Promise((resolve) => {
    let index = 0;
    let rec = null;
    let timer = null;
    let settled = false;
    let status = null;

    const detach = () => {
      if (!rec) return;
      rec.onstart = null;
      rec.onaudiostart = null;
      rec.onerror = null;
      rec.onend = null;
    };
    const finish = (outcome) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (status) status.onchange = null;
      detach();
      try { if (rec) rec.abort(); } catch { /* already stopped */ }
      resolve({ outcome, lang: outcome === "ok" ? langs[index] : null });
    };
    const arm = (ms, outcome = "no_voice") => {
      clearTimeout(timer);
      timer = setTimeout(() => finish(outcome), ms);
    };
    const attempt = () => {
      try {
        rec = new Ctor();
      } catch {
        finish("no_voice");
        return;
      }
      rec.lang = langs[index];
      rec.continuous = false;
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      rec.onstart = () => finish("ok");
      rec.onaudiostart = () => finish("ok");
      rec.onerror = (e) => {
        const outcome = voiceOutcome(e && e.error);
        if (outcome === "lang" && index + 1 < langs.length) {
          detach();
          index += 1;
          attempt();
          return;
        }
        finish(["mic_blocked", "network"].includes(outcome) ? outcome : "no_voice");
      };
      rec.onend = () => finish("no_voice");
      try {
        rec.start();
      } catch {
        finish("no_voice");
      }
    };

    arm(timeoutMs);
    attempt();

    // While the browser's microphone prompt is open, wait for the student's choice instead of timing out.
    const permissions = env.navigator && env.navigator.permissions;
    if (!settled && permissions && typeof permissions.query === "function") {
      Promise.resolve()
        .then(() => permissions.query({ name: "microphone" }))
        .then((st) => {
          if (settled || !st) return;
          status = st;
          // States: granted, prompt, or refused. Refused: the recognition's own error normally comes first;
          // without one, say "blocked" soon.
          const refused = () => st.state !== "granted" && st.state !== "prompt";
          if (refused()) arm(Math.min(timeoutMs, BLOCKED_GRACE_MS), "mic_blocked");
          if (st.state === "prompt") arm(promptMs);
          st.onchange = () => {
            if (settled) return;
            if (refused()) arm(Math.min(timeoutMs, BLOCKED_GRACE_MS), "mic_blocked");
            else if (st.state === "granted") arm(timeoutMs);
          };
        })
        .catch(() => { /* this browser cannot query the microphone permission */ });
    }
  });
}

// On-device recognition only when the browser reports it available for the language; never install a language pack.
export async function localRecognition(env, tag, timeoutMs = 400) {
  const Ctor = recognitionCtor(env);
  if (!Ctor || typeof Ctor.available !== "function") return false;
  let timer = null;
  try {
    const answer = await Promise.race([
      Ctor.available({ langs: [tag], processLocally: true }),
      new Promise((res) => { timer = setTimeout(() => res(null), timeoutMs); }),
    ]);
    return answer === "available";
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

// One push-to-talk utterance. `result` resolves {text, confidence} or {error}: error is an outcome of
// core.voiceOutcome (no_speech, aborted, lang, mic_blocked, no_voice, network).
export function listenOnce({ env = globalThis, lang = "en-US", processLocally = false, onInterim, onStart } = {}) {
  const Ctor = recognitionCtor(env);
  let rec = null;
  const result = new Promise((resolve) => {
    let done = false;
    let finalText = "";
    let interimText = "";
    let confidence = null;
    let error = null;
    const finish = (r) => {
      if (done) return;
      done = true;
      resolve(r);
    };
    if (!Ctor) { finish({ error: "no_voice" }); return; }
    try {
      rec = new Ctor();
    } catch {
      finish({ error: "no_voice" });
      return;
    }
    rec.lang = lang;
    rec.continuous = false;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    if (processLocally) {
      try { rec.processLocally = true; } catch { /* not supported */ }
    }
    rec.onstart = () => { if (onStart) onStart(); };
    rec.onresult = (e) => {
      let fin = "";
      let interim = "";
      const results = (e && e.results) || [];
      for (let k = 0; k < results.length; k += 1) {
        const r = results[k];
        const alt = r && r[0];
        if (!alt) continue;
        if (r.isFinal) {
          fin += alt.transcript;
          if (typeof alt.confidence === "number") confidence = alt.confidence;
        } else {
          interim += alt.transcript;
        }
      }
      finalText = fin;
      interimText = interim;
      if (onInterim) onInterim({ final: fin, interim });
    };
    rec.onerror = (e) => { error = voiceOutcome(e && e.error); };
    rec.onend = () => {
      const text = (finalText || (error ? "" : interimText)).trim();
      if (text) finish({ text, confidence });
      else finish({ error: error || "no_speech" });
    };
    try {
      rec.start();
    } catch {
      finish({ error: "no_voice" });
    }
  });
  return {
    result,
    stop() { try { if (rec) rec.stop(); } catch { /* already stopped */ } },
    abort() { try { if (rec) rec.abort(); } catch { /* already stopped */ } },
  };
}

// The voice for a language: a regional match in the recognition order first, then the first voice whose language
// starts with the same code (docs/UI_SPEC.md A5.4).
export function pickVoice(voices, lang) {
  const list = Array.from(voices || []);
  const norm = (v) => String((v && v.lang) || "").replace(/_/g, "-").toLowerCase();
  for (const tag of REC_LANGS[lang] || []) {
    const hit = list.find((v) => norm(v) === tag.toLowerCase());
    if (hit) return hit;
  }
  const code = lang === "es" ? "es" : "en";
  return list.find((v) => norm(v).startsWith(code)) || null;
}

// Speech synthesis, sentence by sentence (docs/UI_SPEC.md A5.5).
export class Speaker {
  constructor({ env = globalThis, onNoStart = () => {}, startMs = SPEECH_START_MS } = {}) {
    this.synth = (env && env.speechSynthesis) || null;
    this.Utterance = (env && env.SpeechSynthesisUtterance) || null;
    this.onNoStart = onNoStart;
    this.startMs = startMs;
    this.voices = [];
    this.run = 0;
    this.current = null;
    if (this.synth) {
      this.loadVoices();
      const reload = () => this.loadVoices();
      if (typeof this.synth.addEventListener === "function") this.synth.addEventListener("voiceschanged", reload);
      else this.synth.onvoiceschanged = reload;
    }
  }

  get available() {
    return Boolean(this.synth && this.Utterance);
  }

  loadVoices() {
    try { this.voices = this.synth.getVoices() || []; } catch { this.voices = []; }
  }

  // Some phone browsers play speech only after a first speak() inside a tap: call this from the tap handler.
  unlock() {
    if (!this.available) return;
    try {
      const u = new this.Utterance(" ");
      u.volume = 0;
      this.synth.speak(u);
    } catch { /* nothing to unlock */ }
  }

  // Speak chunks [{text, interruptible}] in `lang`. Resolves "done", "cancelled" (cancel() or a newer speak) or
  // "silent" (speech did not start within 2 s; onNoStart has been called and the rest is skipped).
  async speak(chunks, lang, { onChunk } = {}) {
    if (!this.available || !chunks || !chunks.length) return "done";
    const run = ++this.run;
    const previous = this.current;
    this.current = null;
    this.stopSynth();
    if (previous) previous.finish("cancelled");
    if (!this.voices.length) this.loadVoices();
    const voice = pickVoice(this.voices, lang);
    const tag = voice && voice.lang ? String(voice.lang).replace(/_/g, "-") : (REC_LANGS[lang] || REC_LANGS.en)[0];
    for (let i = 0; i < chunks.length; i += 1) {
      if (run !== this.run) return "cancelled";
      if (onChunk) onChunk(i, chunks[i]);
      const outcome = await this.speakOne(chunks[i].text, tag, voice, run);
      if (run !== this.run || outcome === "cancelled") return "cancelled";
      if (outcome === "silent") {
        this.stopSynth();
        this.onNoStart();
        return "silent";
      }
    }
    return "done";
  }

  speakOne(text, tag, voice, run) {
    return new Promise((resolve) => {
      let startTimer = null;
      let endTimer = null;
      const finish = (outcome) => {
        clearTimeout(startTimer);
        clearTimeout(endTimer);
        if (this.current && this.current.run === run) this.current = null;
        resolve(outcome);
      };
      let u;
      try {
        u = new this.Utterance(text);
      } catch {
        finish("done");
        return;
      }
      u.lang = tag;
      if (voice) u.voice = voice;
      u.rate = 1;
      u.pitch = 1;
      u.onstart = () => {
        clearTimeout(startTimer);
        // A guard against browsers that never report the end of an utterance.
        endTimer = setTimeout(() => finish("done"), text.length * 90 + 4000);
      };
      u.onend = () => finish("done");
      u.onerror = (e) => finish(e && ["interrupted", "canceled"].includes(e.error) ? "cancelled" : "done");
      this.current = { run, finish };
      startTimer = setTimeout(() => finish("silent"), this.startMs);
      try {
        this.synth.speak(u);
      } catch {
        finish("done");
      }
    });
  }

  stopSynth() {
    try { if (this.synth) this.synth.cancel(); } catch { /* nothing to stop */ }
  }

  cancel() {
    this.run += 1;
    const current = this.current;
    this.current = null;
    this.stopSynth();
    if (current) current.finish("cancelled");
  }
}
