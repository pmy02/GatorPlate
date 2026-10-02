// Talk page controller (docs/UI_SPEC.md A5; docs/BRAIN_API.md §10). The same brain as the phone line: a web session,
// then /start, /turn and /end with the bearer token. The conversation lives in page memory only (gone after a reload).
// Fixture mode (?fixtures=1) answers from web/fixtures through shared/api.js and shows the REPLAY badge.

import { fetchJSON, FIXTURES } from "/shared/api.js";
import { createT } from "/shared/i18n.js";
import { STRINGS } from "./strings.js";
import {
  LANGS, SLOW_MS, TURN_TIMEOUT_MS, TalkSession, canListen, canSend, cardHref, cleanText, displayText, failureKind,
  initialState, micAction, micLabelKey, reaskReply, reduce, resolveLang, shouldAutoListen, speechPlan,
} from "./core.js";
import { Speaker, listenOnce, localRecognition, probeRecognition, recognitionTags } from "./voice.js";

const ICON = {
  mic: "/shared/icons.svg#i-mic",
  info: "/shared/icons.svg#i-info",
  alert: "/shared/icons.svg#i-alert-triangle",
  check: "/shared/icons.svg#i-check-circle",
  ended: "/shared/icons.svg#i-eye-off",
  volume: "/shared/icons.svg#i-volume",
  volumeOff: "/shared/icons.svg#i-volume-off",
};
const ERROR_NOTICES = new Set(["err.server", "err.busy"]);
const AUTO_LISTEN_DELAY_MS = 250;
const AUTO_LISTEN_START_MS = 1500;
const LONG_LINE = 180;           // a longer reply uses a smaller size so it fits a phone screen

const $ = (id) => document.getElementById(id);
const el = {
  intro: $("intro"), introNotice: $("intro-notice"), introNoticeText: $("intro-notice-text"),
  startVoice: $("start-voice"), startType: $("start-type"),
  convo: $("convo"), line: $("line"), heard: $("heard"), heardFinal: $("heard-final"), heardInterim: $("heard-interim"),
  notice: $("notice"), noticeText: $("notice-text"), noticeIcon: $("notice-icon"), retry: $("retry"),
  finish: $("finish"), finishText: $("finish-text"), finishIcon: $("finish-icon"), cardLink: $("card-link"),
  again: $("again"), micArea: $("mic-area"), mic: $("mic"), micIcon: $("mic-icon"), micLabel: $("mic-label"),
  replies: $("replies"), form: $("type-form"), input: $("type-input"), send: $("send"),
  readAloud: $("read-aloud"), readAloudIcon: $("read-aloud-icon"), readAloudState: $("read-aloud-state"),
  historyList: $("history-list"), toast: $("toast"), announce: $("announce"),
};

let state = initialState({ lang: resolveLang(location.search, (navigator.languages || [])[0] || navigator.language) });
const t = createT(STRINGS, () => state.lang);

let session = null;
let transcript = [];          // [{who: "gp" | "you", text}] in page memory only
let lastQuestion = null;      // the last reply that asked something (said again when a hold ends)
let shownLine = "";
let listener = null;
let probing = false;
const recIndex = { en: 0, es: 0 };
const localOk = new Map();
let holdTimer = null;
let toastTimer = null;
let generation = 0;           // bumps on "Start again": late answers of an old call are ignored

const speaker = new Speaker({ env: window, onNoStart: () => showToast(t("err.no_sound")) });

function dispatch(event) {
  state = reduce(state, event);
  render();
}

// --------------------------------------------------------------------------------------------- rendering

function applyStaticStrings() {
  document.documentElement.lang = state.lang;
  document.title = t("title");
  for (const node of document.querySelectorAll("[data-t]")) setText(node, t(node.dataset.t));
  for (const node of document.querySelectorAll("[data-t-label]")) node.setAttribute("aria-label", t(node.dataset.tLabel));
  for (const button of document.querySelectorAll(".langswitch__btn")) {
    button.setAttribute("aria-pressed", String(button.dataset.lang === state.lang));
  }
}

function setIcon(useNode, href) {
  if (useNode.getAttribute("href") !== href) useNode.setAttribute("href", href);
}

function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

// Phone numbers in a line never break across lines ("(415) 338-1203").
const PHONE = /\(\d{3}\) \d{3}-\d{4}/g;

let lineOnScreen = null;

function showLine(text) {
  if (lineOnScreen === text) return;
  lineOnScreen = text;
  const parts = [];
  let at = 0;
  for (const m of text.matchAll(PHONE)) {
    if (m.index > at) parts.push(text.slice(at, m.index));
    const span = document.createElement("span");
    span.className = "nowrap";
    span.textContent = m[0];
    parts.push(span);
    at = m.index + m[0].length;
  }
  if (at < text.length) parts.push(text.slice(at));
  el.line.replaceChildren(...parts);
  el.line.classList.toggle("is-long", text.length > LONG_LINE);
}

function announce(text) {
  el.announce.textContent = "";
  if (text) setTimeout(() => { el.announce.textContent = text; }, 50);
}

let lastNotice = null;

function render() {
  applyStaticStrings();
  const { phase } = state;
  const inIntro = phase === "intro";
  el.intro.hidden = !inIntro;
  el.convo.hidden = inIntro;

  // Intro notice (too many sessions, server down at the start).
  const introNotice = inIntro && state.notice ? t(state.notice) : "";
  el.introNotice.hidden = !introNotice;
  setText(el.introNoticeText, introNotice);
  el.startVoice.disabled = false;
  el.startType.disabled = false;

  // Current line: the reply's display text; while connecting, a short wait line.
  let line = shownLine;
  if (phase === "connecting") line = state.mode === "voice" && state.voice === "unknown" ? t("intro.mic") : t("connecting");
  showLine(line);

  // Notice line.
  const notice = !inIntro && state.notice ? t(state.notice) : "";
  el.notice.hidden = !notice;
  setText(el.noticeText, notice);
  const isError = ERROR_NOTICES.has(state.notice);
  el.notice.className = `notice ${isError ? "notice--error" : "notice--info"}`;
  setIcon(el.noticeIcon, isError ? ICON.alert : ICON.info);
  el.retry.hidden = !(state.failed && phase === "ready");
  if (state.notice !== lastNotice) {
    lastNotice = state.notice;
    if (state.notice) announce(t(state.notice));
  }

  // Card and end.
  const href = cardHref(state.cardUrl, { fixtures: FIXTURES, lang: state.lang });
  const finished = phase === "done" || phase === "ended";
  el.finish.hidden = !(href || finished);
  el.cardLink.hidden = !href;
  if (href) el.cardLink.setAttribute("href", href);
  el.again.hidden = !finished;
  if (href) {
    el.finishText.textContent = t("done");
    setIcon(el.finishIcon, ICON.check);
    el.finish.dataset.kind = "card";
  } else {
    el.finishText.textContent = t("ended");
    setIcon(el.finishIcon, ICON.ended);
    el.finish.dataset.kind = "ended";
  }

  // Mic.
  const micShown = !inIntro && !finished && state.voice !== "off";
  el.micArea.hidden = !micShown;
  const action = micAction(state);
  const usable = Boolean(action) || (state.voice === "unknown" && phase === "ready");
  el.mic.dataset.phase = phase;
  el.mic.setAttribute("aria-disabled", String(!usable));
  setIcon(el.micIcon, ICON.mic);
  const labelKey = micLabelKey(state);
  const label = labelKey ? t(labelKey) : t("tap_to_talk");
  setText(el.micLabel, labelKey ? label : "");
  if (el.mic.getAttribute("aria-label") !== label) el.mic.setAttribute("aria-label", label);

  // Quick replies (choices) belong to the pending question.
  const reply = state.reply;
  const choices = reply && reply.ask && Array.isArray(reply.choices) && !finished ? reply.choices : [];
  renderChoices(choices);

  // Typing box: always there during the conversation.
  el.form.hidden = inIntro || finished;
  el.send.setAttribute("aria-disabled", String(!canSend(state)));

  // Read aloud.
  el.readAloud.hidden = !speaker.available;
  el.readAloud.setAttribute("aria-pressed", String(state.readAloud));
  el.readAloudState.textContent = t(state.readAloud ? "on" : "off");
  setIcon(el.readAloudIcon, state.readAloud ? ICON.volume : ICON.volumeOff);

  renderHistory();
}

let shownChoices = "";

function renderChoices(choices) {
  const key = JSON.stringify(choices);
  const busy = !canSend(state);
  if (key !== shownChoices) {
    shownChoices = key;
    const hadFocus = el.replies.contains(document.activeElement);
    el.replies.replaceChildren(...choices.map((label) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "btn replies__btn";
      b.textContent = label;
      b.addEventListener("click", () => {
        if (b.getAttribute("aria-disabled") !== "true") sendText(label, { typed: true });
      });
      return b;
    }));
    if (hadFocus) {
      const next = el.replies.querySelector("button") || (el.micArea.hidden ? el.input : el.mic);
      if (next && !next.closest("[hidden]")) next.focus({ preventScroll: true });
    }
  }
  el.replies.hidden = choices.length === 0;
  for (const b of el.replies.querySelectorAll("button")) b.setAttribute("aria-disabled", String(busy));
}

let shownHistory = -1;

function renderHistory() {
  if (shownHistory === transcript.length && el.historyList.childElementCount === transcript.length) {
    for (const node of el.historyList.querySelectorAll("[data-who]")) {
      node.textContent = node.dataset.who === "you" ? t("you") : t("gatorplate");
    }
    return;
  }
  shownHistory = transcript.length;
  el.historyList.replaceChildren(...transcript.map((entry) => {
    const li = document.createElement("li");
    li.className = `bubble bubble--${entry.who}`;
    const who = document.createElement("p");
    who.className = "bubble__who";
    who.dataset.who = entry.who;
    who.textContent = entry.who === "you" ? t("you") : t("gatorplate");
    const text = document.createElement("p");
    text.className = "bubble__text";
    text.textContent = entry.text;
    li.append(who, text);
    return li;
  }));
}

function showHeard(final, interim = "") {
  el.heard.hidden = !(final || interim);
  el.heardFinal.textContent = final;
  el.heardInterim.textContent = interim ? (final ? ` ${interim}` : interim) : "";
}

function showToast(text) {
  clearTimeout(toastTimer);
  el.toast.textContent = text;
  el.toast.hidden = false;
  announce(text);
  toastTimer = setTimeout(() => { el.toast.hidden = true; }, 4000);
}

// --------------------------------------------------------------------------------------------- language

function setLang(lang, { fromReply = false } = {}) {
  if (!LANGS.includes(lang) || lang === state.lang) return;
  if (state.phase === "listening") {
    if (listener) listener.abort();
    showHeard("");
    dispatch({ type: "stop_listening" });
  }
  dispatch({ type: "lang", lang });
  try {
    const url = new URL(location.href);
    url.searchParams.set("lang", lang);
    history.replaceState(history.state, "", url);
  } catch { /* the address stays as it was */ }
  if (fromReply) showToast(t("switched"));
}

// --------------------------------------------------------------------------------------------- API

function request(method, url, { body, token, lang, signal } = {}) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return fetchJSON(url, { method, body, headers, lang, signal });
}

async function begin(mode) {
  const gen = ++generation;
  if (mode === "voice") speaker.unlock();
  // The probe starts inside the tap, so the browser's microphone prompt belongs to it.
  const probe = mode === "voice" && state.voice !== "off"
    ? probeRecognition({ env: window, langs: recognitionTags(state.lang, recIndex[state.lang]) })
    : null;
  transcript = [];
  shownLine = "";
  lastQuestion = null;
  showHeard("");
  dispatch({ type: "start", mode, readAloud: mode === "voice" && speaker.available });
  session = new TalkSession({ request });
  let reply;
  try {
    await session.open(state.lang);
    reply = await session.start();
  } catch (err) {
    if (gen !== generation) return;
    if (session.startSent) session.end("error");
    dispatch({ type: "fail", kind: failureKind(err) });
    el.startVoice.focus();
    return;
  }
  if (probe) {
    const result = await probe;
    if (gen !== generation) return;
    noteProbe(result);
  }
  if (gen !== generation) return;
  handleReply(reply);
}

function noteProbe(result) {
  const lang = state.lang;
  if (result.outcome === "ok" && result.lang) {
    const tags = recognitionTags(lang);
    recIndex[lang] = Math.max(0, tags.indexOf(result.lang));
    if (!localOk.has(result.lang)) {
      localOk.set(result.lang, false);
      localRecognition(window, result.lang).then((ok) => localOk.set(result.lang, ok));
    }
  }
  dispatch({ type: "probe", outcome: result.outcome });
}

function handleReply(reply) {
  const gen = generation;
  clearTimeout(holdTimer);
  if (reply.lang && reply.lang !== state.lang) setLang(reply.lang, { fromReply: true });
  const text = displayText(reply);
  if (text) {
    shownLine = text;
    transcript.push({ who: "gp", text });
  }
  if (reply.ask) lastQuestion = reply;
  const plan = speechPlan(reply);
  const speak = state.readAloud && speaker.available && plan.length > 0;
  dispatch({ type: "reply", reply, speak });
  if (reply.end) session.end(reply.end_reason || "completed");
  if (reply.hold_s > 0 && !reply.end) {
    // Still silent when the hold ends: say the last question again, through the same half-duplex path (the mic stays
    // closed while it is spoken), with its quick replies.
    holdTimer = setTimeout(() => {
      if (gen !== generation || state.phase !== "ready") return;
      const again = reaskReply(lastQuestion);
      if (again && again.lang === state.lang) handleReply(again);
    }, reply.hold_s * 1000);
  }
  if (state.mode === "typing" && !reply.end) focusInput();
  if (state.phase === "done" || state.phase === "ended") focusFinish();
  if (!speak) {
    afterSpeech(reply, gen);
    return;
  }
  speaker.speak(plan, reply.lang || state.lang, {
    onChunk: (_, chunk) => dispatch({ type: "chunk", interruptible: chunk.interruptible }),
  }).then((outcome) => {
    if (gen !== generation || outcome === "cancelled") return;
    dispatch({ type: "spoken" });
    if (state.phase === "done" || state.phase === "ended") focusFinish();
    afterSpeech(reply, gen);
  });
}

// After the voice ends: listen again on its own in voice mode; if that fails, the mic says "Tap to talk".
function afterSpeech(reply, gen) {
  if (!shouldAutoListen(state, reply)) return;
  setTimeout(() => {
    if (gen !== generation || state.phase !== "ready") return;
    startListening({ auto: true });
  }, AUTO_LISTEN_DELAY_MS);
}

function focusInput() {
  if (document.activeElement && document.activeElement.closest && document.activeElement.closest(".replies")) return;
  el.input.focus({ preventScroll: true });
}

function focusFinish() {
  const target = !el.cardLink.hidden ? el.cardLink : (!el.again.hidden ? el.again : null);
  if (target && document.activeElement !== target) target.focus({ preventScroll: false });
}

// --------------------------------------------------------------------------------------------- listening

async function startListening({ auto = false } = {}) {
  // Never cut a voice that may not be cut (the reply's `interruptible`), and never listen while it speaks.
  if (!canListen(state)) return;
  if (state.phase === "speaking") speaker.cancel();
  dispatch({ type: "listen" });
  if (state.phase !== "listening") return;
  const gen = generation;
  const lang = state.lang;
  showHeard("");
  const tags = recognitionTags(lang);
  for (let i = recIndex[lang] || 0; i < tags.length; i += 1) {
    let started = false;
    const current = listenOnce({
      env: window, lang: tags[i], processLocally: localOk.get(tags[i]) === true,
      onStart: () => { started = true; },
      onInterim: ({ final, interim }) => { if (listener === current) showHeard(final, interim); },
    });
    listener = current;
    let watchdog = null;
    if (auto) watchdog = setTimeout(() => { if (!started) current.abort(); }, AUTO_LISTEN_START_MS);
    const result = await current.result;
    clearTimeout(watchdog);
    if (listener === current) listener = null;
    if (gen !== generation || state.phase !== "listening" || lang !== state.lang) return;
    if (result.error === "lang" && i + 1 < tags.length) {
      recIndex[lang] = i + 1;
      continue;
    }
    if (result.text) {
      sendText(result.text, { typed: false, confidence: result.confidence, fromVoice: true });
      return;
    }
    if (result.error === "no_speech") {
      showHeard("");
      dispatch({ type: "no_speech" });
      return;
    }
    if (result.error === "aborted" || (auto && !started)) {
      showHeard("");
      dispatch({ type: "stop_listening" });
      return;
    }
    dispatch({ type: "voice_error", outcome: result.error === "lang" ? "no_voice" : result.error });
    focusInput();
    return;
  }
}

async function onMic() {
  const action = micAction(state);
  if (probing) return;
  if (state.voice === "unknown" && (state.phase === "ready" || (state.phase === "speaking" && state.interruptible))) {
    // Typing mode so far: the first mic tap runs the probe (inside the tap), then listens. A tap during the voice
    // stops it first; a second tap while the probe (or the browser's microphone prompt) is open does nothing.
    const gen = generation;
    if (state.phase === "speaking") {
      speaker.cancel();
      dispatch({ type: "interrupt" });
    }
    probing = true;
    let result;
    try {
      result = await probeRecognition({ env: window, langs: recognitionTags(state.lang, recIndex[state.lang]) });
    } finally {
      probing = false;
    }
    if (gen !== generation) return;
    noteProbe(result);
    if (result.outcome !== "ok") { focusInput(); return; }
    dispatch({ type: "mode", mode: "voice" });
    startListening();
    return;
  }
  if (action === "listen" || action === "interrupt") {
    if (state.mode !== "voice") dispatch({ type: "mode", mode: "voice" });
    startListening();
  } else if (action === "stop" && listener) {
    listener.stop();
  }
}

// --------------------------------------------------------------------------------------------- sending

async function sendText(raw, { typed = true, confidence = null, fromVoice = false, fromInput = false } = {}) {
  const text = cleanText(raw);
  if (!text || !session || !canSend(state)) return;
  if (state.phase === "speaking") speaker.cancel();
  if (state.phase === "listening" && listener && !fromVoice) listener.abort();
  clearTimeout(holdTimer);
  transcript.push({ who: "you", text });
  showHeard(text);
  // Only a sent text box is cleared; a quick-reply tap keeps what the student was typing.
  if (fromInput) el.input.value = "";
  dispatch({ type: "send" });
  const interrupted = state.sentInterrupted;
  await deliver(() => session.turn(text, { typed, confidence, interrupted, lang: state.lang, signal: abortSoon() }));
}

let turnTimer = null;

function abortSoon() {
  const controller = new AbortController();
  clearTimeout(turnTimer);
  turnTimer = setTimeout(() => controller.abort(), TURN_TIMEOUT_MS);
  return controller.signal;
}

async function deliver(call) {
  const gen = generation;
  const slow = setTimeout(() => { if (gen === generation) dispatch({ type: "slow" }); }, SLOW_MS);
  let reply;
  try {
    reply = await call();
  } catch (err) {
    clearTimeout(slow);
    clearTimeout(turnTimer);
    if (gen !== generation) return;
    const kind = failureKind(err);
    if (kind === "gone" && session) session.endSent = true;
    dispatch({ type: "fail", kind });
    if (state.phase === "ended") focusFinish();
    else if (!el.retry.hidden) el.retry.focus();
    return;
  }
  clearTimeout(slow);
  clearTimeout(turnTimer);
  if (gen !== generation) return;
  handleReply(reply);
}

async function retryTurn() {
  if (!session || !session.pending || !state.failed) return;
  dispatch({ type: "send" });
  await deliver(() => session.retry(abortSoon()));
}

// --------------------------------------------------------------------------------------------- read aloud

function toggleReadAloud() {
  const on = !state.readAloud;
  if (on) speaker.unlock();
  dispatch({ type: "read_aloud", on });
  if (!on && state.phase === "speaking") {
    speaker.cancel();
    dispatch({ type: "spoken" });
  }
}

// --------------------------------------------------------------------------------------------- restart and leave

function restart() {
  generation += 1;
  clearTimeout(holdTimer);
  speaker.cancel();
  if (listener) listener.abort();
  if (session) session.end("caller_hangup");
  session = null;
  transcript = [];
  shownLine = "";
  lastQuestion = null;
  showHeard("");
  shownHistory = -1;
  dispatch({ type: "restart" });
  el.startVoice.focus();
}

function leave() {
  speaker.cancel();
  if (listener) listener.abort();
  const b = session && session.beacon("caller_hangup");
  if (!b || FIXTURES) return;
  try {
    fetch(b.url, {
      method: "POST", keepalive: true, credentials: "same-origin",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${b.token}` },
      body: JSON.stringify(b.body),
    }).catch(() => {});
  } catch { /* best effort */ }
}

// --------------------------------------------------------------------------------------------- wiring

function isTypingTarget(node) {
  if (!node || !node.closest) return false;
  return Boolean(node.closest("input, textarea, select, button, a, summary, [contenteditable='true']"));
}

el.startVoice.addEventListener("click", () => begin("voice"));
el.startType.addEventListener("click", () => begin("typing"));
el.mic.addEventListener("click", () => {
  if (el.mic.getAttribute("aria-disabled") === "true") return;
  onMic();
});
el.form.addEventListener("submit", (e) => {
  e.preventDefault();
  sendText(el.input.value, { typed: true, fromInput: true });
});
el.retry.addEventListener("click", retryTurn);
el.again.addEventListener("click", restart);
el.readAloud.addEventListener("click", toggleReadAloud);
for (const button of document.querySelectorAll(".langswitch__btn")) {
  button.addEventListener("click", () => setLang(button.dataset.lang));
}
document.addEventListener("keydown", (e) => {
  if (e.key !== " " || e.repeat || e.altKey || e.ctrlKey || e.metaKey) return;
  if (state.phase === "intro" || isTypingTarget(e.target)) return;
  if (el.mic.getAttribute("aria-disabled") === "true" || el.micArea.hidden) return;
  e.preventDefault();
  onMic();
});
window.addEventListener("pagehide", leave);
// Back from the back/forward cache after pagehide ended the call: show it as ended instead of a call that only looks
// alive (its next turn would be refused).
window.addEventListener("pageshow", (e) => {
  if (!e.persisted || !session || !session.endSent) return;
  generation += 1;
  clearTimeout(holdTimer);
  dispatch({ type: "left" });
});

render();
