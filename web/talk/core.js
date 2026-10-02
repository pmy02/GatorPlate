// Talk page core (docs/UI_SPEC.md A5, docs/BRAIN_API.md §3.2, §4–§6 and §10). Pure ES module: no DOM, no network of
// its own, so `node --test` can run it. talk.js wires it to the page; voice.js wraps the Web Speech API.

export const LANGS = ["en", "es"];

// Recognition languages in the order to try (docs/UI_SPEC.md A5.4).
export const REC_LANGS = { en: ["en-US"], es: ["es-US", "es-MX", "es-ES"] };

// BrainReply.card_url is a same-origin card path (contracts/brain_api.v1.schema.json).
export const CARD_URL = /^\/c\/[A-Za-z0-9_-]{22,64}$/;

export const MAX_TEXT = 1000;      // TurnRequest.text limit
export const SLOW_MS = 3500;       // show "Still thinking…" after this long
export const TURN_TIMEOUT_MS = 15000;

// Page language: ?lang= first, then a browser language that starts with "es", else English (docs/UI_SPEC.md A5.4).
export function resolveLang(search = "", navLang = "") {
  const q = new URLSearchParams(search).get("lang");
  if (LANGS.includes(q)) return q;
  return String(navLang || "").toLowerCase().startsWith("es") ? "es" : "en";
}

export const otherLang = (lang) => (lang === "es" ? "en" : "es");

// Typed or heard text as sent to the brain: whitespace collapsed, at most MAX_TEXT characters.
export function cleanText(text) {
  return String(text ?? "").replace(/\s+/g, " ").trim().slice(0, MAX_TEXT);
}

// The browser's confidence when it has one, else null (some browsers report 0 when they have no value).
export function normalizeConfidence(value) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 && value <= 1 ? value : null;
}

// Sentences for speech synthesis: long single utterances can stall, so speak sentence by sentence. A sentence longer
// than `max` characters is split again at commas or semicolons, then at spaces.
export function chunkSentences(text, max = 180) {
  const clean = String(text ?? "").replace(/\s+/g, " ").trim();
  if (!clean) return [];
  // A sentence ends at . ! ? or … followed by a space ("$18.50" and "8:30" stay whole); a single-letter abbreviation
  // such as the Spanish "a. m." does not end one.
  const sentences = [];
  for (const piece of clean.split(/(?<=[.!?…]["'”’)\]]?) /)) {
    const prev = sentences[sentences.length - 1];
    if (prev !== undefined && /(?:^|[\s(])\p{L}\.$/u.test(prev)) sentences[sentences.length - 1] = `${prev} ${piece}`;
    else sentences.push(piece);
  }
  const out = [];
  for (const raw of sentences) {
    const s = raw.trim();
    if (!s) continue;
    if (s.length <= max) { out.push(s); continue; }
    let part = "";
    for (const piece of s.split(/(?<=[,;:])\s+/)) {
      const next = part ? `${part} ${piece}` : piece;
      if (next.length <= max) { part = next; continue; }
      if (part) out.push(part);
      part = piece;
      while (part.length > max) {
        const cut = part.lastIndexOf(" ", max);
        const at = cut > 0 ? cut : max;
        out.push(part.slice(0, at).trim());
        part = part.slice(at).trim();
      }
    }
    if (part) out.push(part);
  }
  return out;
}

// What to speak for one reply: `say` (interruptible only if the reply says so), then `ask` (always interruptible,
// docs/BRAIN_API.md §6).
export function speechPlan(reply) {
  if (!reply) return [];
  const chunks = [];
  for (const text of chunkSentences(reply.say)) chunks.push({ text, interruptible: Boolean(reply.interruptible) });
  if (!reply.end) for (const text of chunkSentences(reply.ask)) chunks.push({ text, interruptible: true });
  return chunks;
}

// After the voice ends, may the page listen again by itself? Only with the voice on and read aloud, after a question
// or an empty reply ("say nothing and keep listening", docs/BRAIN_API.md §6); never after the end or during a hold.
export function shouldAutoListen(state, reply) {
  if (!state || !reply || reply.end || reply.hold_s > 0) return false;
  const empty = !String(reply.say ?? "").trim() && !reply.ask;
  if (!reply.ask && !empty) return false;
  return state.mode === "voice" && state.voice === "ok" && Boolean(state.readAloud);
}

// When a hold ends and the student is still silent, the page may say the last question again (docs/BRAIN_API.md §6).
// `question` is the last reply that asked something; its quick replies come back with it.
export function reaskReply(question) {
  if (!question || typeof question.ask !== "string" || !question.ask.trim()) return null;
  return {
    say: "", ask: question.ask, end: false, end_reason: null, lang: question.lang, listen: question.listen || "normal",
    expect: question.expect || "open", interruptible: true, hold_s: 0, display: question.ask,
    choices: Array.isArray(question.choices) && question.choices.length ? [...question.choices] : null,
    card_url: null, debug: null,
  };
}

// The text to show for a reply: `display` (web), else say + ask.
export function displayText(reply) {
  if (!reply) return "";
  if (typeof reply.display === "string" && reply.display.trim()) return reply.display;
  return [reply.say, reply.ask].filter((s) => s && String(s).trim()).join(" ");
}

// The "Open my card" link: the reply's card path, or the card page's fixture view in fixture mode.
export function cardHref(cardUrl, { fixtures = false, lang = "en" } = {}) {
  if (typeof cardUrl !== "string" || !CARD_URL.test(cardUrl)) return null;
  if (fixtures) return `/card/?fixtures=1&token=fixture&lang=${lang === "es" ? "es" : "en"}`;
  return cardUrl;
}

// --------------------------------------------------------------------------------------------- voice outcomes

// Probe and recognition errors (docs/UI_SPEC.md A5.3): these switch the page to typing with one plain line.
const VOICE_ERRORS = {
  "not-allowed": "mic_blocked",
  "service-not-allowed": "no_voice",
  "audio-capture": "no_voice",
  network: "network",
};

export function voiceOutcome(code) {
  if (code === "no-speech") return "no_speech";
  if (code === "aborted") return "aborted";
  if (code === "language-not-supported") return "lang";
  return VOICE_ERRORS[code] || "no_voice";
}

export const NOTICE_FOR = {
  mic_blocked: "err.mic_blocked",
  no_voice: "err.no_voice",
  network: "err.network",
  no_speech: "err.no_speech",
};

// API failures: 429 on a new session → busy; a call that is gone (expired token, unknown or ended call) → ended;
// anything else (network, timeout, 5xx) → server, which the student can retry with the same seq.
export function failureKind(err) {
  const status = err && typeof err.status === "number" ? err.status : 0;
  if (status === 429) return "busy";
  if (status === 401 || status === 404 || status === 409) return "gone";
  return "server";
}

// --------------------------------------------------------------------------------------------- the call

// One web call: session, /start, /turn (one utterance each, seq +1), /end. `request(method, path, {body, token, lang,
// signal})` resolves to the JSON answer or throws an error with `status` (shared/api.js fetchJSON does).
export class TalkSession {
  constructor({ request, now = () => Date.now() }) {
    this.request = request;
    this.now = now;
    this.callId = null;
    this.token = null;
    this.lang = "en";
    this.seq = 0;
    this.pending = null;
    this.startSent = false;
    this.started = false;
    this.endSent = false;
    this.startedAt = null;
    this.cardUrl = null;
    this.ended = false;
    this.endReason = null;
    this.last = null;
  }

  async open(lang) {
    this.lang = lang;
    const s = await this.request("POST", "/api/web/sessions", { body: { lang }, lang });
    if (!s || typeof s.call_id !== "string" || typeof s.token !== "string") {
      throw Object.assign(new Error("Bad session answer."), { status: 0 });
    }
    this.callId = s.call_id;
    this.token = s.token;
    return s;
  }

  path(kind) {
    return `/v1/calls/${encodeURIComponent(this.callId)}/${kind}`;
  }

  async start() {
    this.startSent = true;
    this.startedAt = this.now();
    const body = { v: 1, seq: 0, channel: "web", lang: this.lang, test: false };
    const reply = await this.request("POST", this.path("start"), { body, token: this.token, lang: this.lang });
    this.started = true;
    return this.take(reply);
  }

  // A new utterance always takes the next seq (gaps are accepted by the brain); retry() re-sends the same body and
  // seq, so a reply the brain already produced comes back unchanged (docs/BRAIN_API.md §4).
  async turn(text, { typed = false, confidence = null, interrupted = false, lang = this.lang, signal } = {}) {
    this.lang = lang;
    this.seq += 1;
    this.pending = {
      v: 1, seq: this.seq, lang, event: "utterance", text: cleanText(text), masked: false,
      confidence: normalizeConfidence(confidence), interrupted: Boolean(interrupted), typed: Boolean(typed),
    };
    return this.send(this.pending, signal);
  }

  async retry(signal) {
    if (!this.pending) throw Object.assign(new Error("Nothing to retry."), { status: 0 });
    return this.send(this.pending, signal);
  }

  async send(body, signal) {
    const reply = await this.request("POST", this.path("turn"), { body, token: this.token, lang: body.lang, signal });
    if (this.pending === body) this.pending = null;
    return this.take(reply);
  }

  take(reply) {
    if (!reply || typeof reply !== "object") throw Object.assign(new Error("Bad reply."), { status: 0 });
    if (typeof reply.card_url === "string" && CARD_URL.test(reply.card_url)) this.cardUrl = reply.card_url;
    if (reply.end) {
      this.ended = true;
      this.endReason = reply.end_reason || "completed";
    }
    this.last = reply;
    return reply;
  }

  get active() {
    return this.startSent && !this.endSent;
  }

  endBody(reason) {
    const body = { v: 1, reason, turns: this.seq };
    if (this.startedAt !== null) body.duration_ms = Math.max(0, Math.trunc(this.now() - this.startedAt));
    return body;
  }

  // /end once (idempotent here and on the server); failures are ignored, the brain closes idle calls itself.
  async end(reason) {
    if (!this.active) return false;
    this.endSent = true;
    try {
      await this.request("POST", this.path("end"), { body: this.endBody(reason), token: this.token, lang: this.lang });
    } catch { /* best effort */ }
    return true;
  }

  // For pagehide: the request to send with fetch keepalive, or null when the call is not active.
  beacon(reason = "caller_hangup") {
    if (!this.active || !this.callId) return null;
    this.endSent = true;
    return { url: this.path("end"), body: this.endBody(reason), token: this.token };
  }
}

// --------------------------------------------------------------------------------------------- page states

// Phases (docs/UI_SPEC.md A5.2): intro · connecting (session, start, microphone prompt) · speaking · ready (waiting
// for the student: "Tap to talk") · listening · thinking · done (card ready) · ended.
export function initialState({ lang = "en", readAloud = true } = {}) {
  return {
    phase: "intro",
    mode: "voice",          // voice | typing
    voice: "unknown",       // unknown | ok | off
    lang,
    readAloud,
    notice: null,           // a string key, shown in the notice line
    failed: false,          // the last turn failed: offer "Try again"
    reply: null,
    cardUrl: null,
    interruptible: true,    // the chunk being spoken may be cut off
    interrupt: false,       // the student cut the voice off; the next answer carries `interrupted: true`
    sentInterrupted: false, // `interrupted` for the turn that "send" has just started
  };
}

const VOICE_NOTICES = new Set(["err.mic_blocked", "err.no_voice", "err.network"]);

function endPhase(state) {
  return state.reply && state.reply.end_reason === "completed" && state.cardUrl ? "done" : "ended";
}

export function reduce(state, event) {
  const s = { ...state };
  switch (event.type) {
    case "start": {
      // "Start talking" always probes the voice again; "Type instead" keeps what is known about it.
      const typing = event.mode === "typing";
      return { ...initialState({ lang: s.lang, readAloud: event.readAloud ?? s.readAloud }),
        phase: "connecting", mode: typing ? "typing" : "voice", voice: typing ? s.voice : "unknown" };
    }
    case "probe":
      if (event.outcome === "ok") {
        s.voice = "ok";
        if (VOICE_NOTICES.has(s.notice)) s.notice = null;
      } else {
        s.voice = "off";
        s.mode = "typing";
        s.notice = NOTICE_FOR[event.outcome] || "err.no_voice";
      }
      return s;
    case "lang":
      s.lang = event.lang;
      return s;
    case "read_aloud":
      s.readAloud = Boolean(event.on);
      return s;
    case "mode":
      s.mode = event.mode === "typing" ? "typing" : "voice";
      return s;
    case "reply": {
      const reply = event.reply;
      s.reply = reply;
      s.failed = false;
      s.interrupt = false;
      if (typeof reply.card_url === "string" && CARD_URL.test(reply.card_url)) s.cardUrl = reply.card_url;
      if (s.notice && !VOICE_NOTICES.has(s.notice)) s.notice = null;
      const plan = speechPlan(reply);
      if (event.speak && plan.length) {
        s.phase = "speaking";
        s.interruptible = plan[0].interruptible;
      } else {
        s.phase = reply.end ? endPhase(s) : "ready";
      }
      return s;
    }
    case "chunk":
      if (s.phase === "speaking") s.interruptible = Boolean(event.interruptible);
      return s;
    case "spoken":
      if (s.phase !== "speaking") return s;
      s.phase = s.reply && s.reply.end ? endPhase(s) : "ready";
      return s;
    case "interrupt":
      // The student stopped the voice (mic tap) before listening started: the next answer interrupted it.
      if (s.phase !== "speaking" || !s.interruptible) return s;
      s.phase = "ready";
      s.interrupt = true;
      return s;
    case "listen":
      if (!canListen(s)) return s;
      if (s.phase === "speaking") s.interrupt = true;
      s.phase = "listening";
      if (s.notice === "err.no_speech") s.notice = null;
      return s;
    case "no_speech":
      if (s.phase !== "listening") return s;
      s.phase = "ready";
      s.notice = "err.no_speech";
      s.interrupt = false;
      return s;
    case "stop_listening":
      if (s.phase === "listening") s.phase = "ready";
      s.interrupt = false;
      return s;
    case "voice_error":
      s.voice = "off";
      s.mode = "typing";
      s.notice = NOTICE_FOR[event.outcome] || "err.no_voice";
      if (s.phase === "listening") s.phase = "ready";
      s.interrupt = false;
      return s;
    case "send":
      if (!canSend(s)) return s;
      // Typed or tapped while the voice was still speaking, or heard right after a tap that cut it off.
      s.sentInterrupted = s.phase === "speaking" || s.interrupt;
      s.interrupt = false;
      s.phase = "thinking";
      s.failed = false;
      s.notice = null;
      return s;
    case "left":
      // The page was hidden and came back (back/forward cache): the call was already ended with caller_hangup.
      if (["intro", "done", "ended"].includes(s.phase)) return s;
      return { ...s, phase: s.reply && s.reply.end ? endPhase(s) : "ended", notice: null, failed: false,
        interrupt: false };
    case "slow":
      if (s.phase === "thinking") s.notice = "err.slow";
      return s;
    case "fail": {
      const kind = event.kind;
      if (s.phase === "connecting") {
        return { ...s, phase: kind === "gone" ? "ended" : "intro", notice: kind === "busy" ? "err.busy" : "err.server" };
      }
      if (kind === "gone") return { ...s, phase: "ended", notice: "err.server", failed: false };
      return { ...s, phase: "ready", notice: kind === "busy" ? "err.busy" : "err.server", failed: true };
    }
    case "restart":
      return { ...initialState({ lang: s.lang, readAloud: s.readAloud }), voice: s.voice,
        notice: s.voice === "off" ? s.notice : null };
    default:
      return s;
  }
}

export function canListen(state) {
  if (state.voice === "off") return false;
  if (state.phase === "ready") return true;
  return state.phase === "speaking" && state.interruptible;
}

// An answer (typed, tapped or heard) may go out now. While a part the reply marks `interruptible: false` is spoken (the
// opening disclosure, an amount with the county-decides sentence, a code, a phone number, crisis resources), nothing
// cuts it off: the quick replies and Send wait for the question part (docs/BRAIN_API.md §6, §10).
export function canSend(state) {
  if (state.phase === "speaking") return Boolean(state.interruptible);
  return ["ready", "listening"].includes(state.phase);
}

// What a tap on the mic does now: listen · interrupt (stop the voice, then listen) · stop (end listening) · null.
export function micAction(state) {
  if (state.voice === "off") return null;
  if (state.phase === "ready") return "listen";
  if (state.phase === "speaking" && state.interruptible) return "interrupt";
  if (state.phase === "listening") return "stop";
  return null;
}

// The string key under the mic button (docs/UI_SPEC.md A5.2).
export function micLabelKey(state) {
  switch (state.phase) {
    case "connecting": return "connecting";
    case "listening": return "listening";
    case "thinking": return "thinking";
    case "speaking": return state.interruptible ? "speaking.tap" : "speaking";
    case "ready": return "tap_to_talk";
    default: return null;
  }
}
