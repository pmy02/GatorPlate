// GatorPlate coordinator console (docs/UI_SPEC.md A3). Boot: load meta and the case list, subscribe to live events
// (SSE with the polling fallback of web/shared/api.js), render on every state change, keyboard shortcuts (A2.7).
import { fetchJSON, subscribeEvents, FIXTURES } from "../shared/api.js";
import { createController, replayFrames, diffDetail, liveCaseId, elapsedMs, openYellow, callIsOver } from "./store.js";
import { encodeEdit, resetResult, minSec } from "./text.js";
import { reducedMotion } from "./views/dom.js";
import { renderList } from "./views/list.js";
import { renderDetail } from "./views/detail.js";
import { createLiveView } from "./views/live.js";
import {
  renderTopbar, renderBanners, renderToasts, renderLogin, openDialog, demoMenuBody, shortcutsBody, rulesBody, deleteBody,
  qrBody, talkQrBody,
} from "./views/shell.js";

const $ = (id) => document.getElementById(id);
const els = {
  topbar: $("topbar"), steps: $("steps"), banners: $("banners"), main: $("main"), work: $("work"), list: $("list"), detail: $("detail"),
  live: $("live"), login: $("login"), toasts: $("toasts"), dialog: $("dialog"),
};

// ---------------------------------------------------------------- per-viewer conveniences (never required)

const PREFS = "gp.console.prefs";
const SELECTED = "gp.console.selected";
function readPrefs() {
  let prefs = {};
  try { prefs = JSON.parse(localStorage.getItem(PREFS) || "{}") || {}; } catch { prefs = {}; }
  try { prefs.selectedId = sessionStorage.getItem(SELECTED) || null; } catch { /* storage blocked */ }
  return prefs;
}
let savedKey = "";
function savePrefs(s) {
  const key = JSON.stringify([s.presenter, s.shortcutsOn, s.followLive, s.segment, s.selectedId]);
  if (key === savedKey) return;
  savedKey = key;
  try {
    localStorage.setItem(PREFS, JSON.stringify({ presenter: s.presenter, shortcutsOn: s.shortcutsOn,
      followLive: s.followLive, segment: s.segment }));
    if (s.selectedId) sessionStorage.setItem(SELECTED, s.selectedId); else sessionStorage.removeItem(SELECTED);
  } catch { /* storage blocked */ }
}

const ctl = createController({ fetchJSON, save: savePrefs, prefs: readPrefs() });
const { dispatch, actions } = ctl;
const S = () => ctl.getState();

// ---------------------------------------------------------------- handlers

// Move focus to an element by its data-key, now or after the next render (the element may not exist yet).
let pendingFocus = null;
function focusKey(key) {
  const el = document.querySelector(`[data-key="${CSS.escape(key)}"]`);
  if (el && !el.closest("[hidden]")) { el.focus(); pendingFocus = null; } else pendingFocus = key;
}

function closeDialog() { if (els.dialog.open) els.dialog.close(); }

const detailOn = {
  retry: (id) => ctl.refetchDetail(id),
  askDelete: (c) => openDialog(els.dialog, "Delete case", deleteBody(c, {
    cancel: closeDialog,
    confirm: async () => {
      closeDialog();
      if (await actions.deleteCase(c.id)) focusKey("seg-all");
    },
  })),
  setStatus: (status) => actions.setStatus(S().selectedId, status),
  async confirm(yid) {
    const id = S().selectedId;
    const r = await actions.confirmYellow(id, yid);
    if (r.ok) {
      const next = openYellow(r.detail)[0];
      focusKey(next ? `yl-ok-${next.id}` : "lock");
    }
  },
  startEdit: (yid) => { dispatch({ type: "edit", yid }); focusKey(`edit-${yid}`); },
  cancelEdit: () => { const y = S().editing; dispatch({ type: "edit", yid: null }); if (y) focusKey(`yl-edit-${y}`); },
  saveEdit(yid, type, value, note) {
    const encoded = encodeEdit(type, value);
    if (encoded === null) return false;
    const id = S().selectedId;
    actions.editYellow(id, yid, encoded, note || null).then((r) => { if (r.ok) focusKey("lock"); });
    return true;
  },
  async markReviewed() {
    const r = await actions.markReviewed(S().selectedId);
    if (r.ok) focusKey("status-select");
    else if (r.code === "locked") focusFirstOpenLine();
  },
  lockedActivate: () => focusFirstOpenLine(),
  section: (key, open) => dispatch({ type: "section", key, open }),
  async patchTracking(patch) {
    const r = await actions.patchTracking(S().selectedId, patch);
    if (r.ok) ctl.toast("Dates saved");
  },
};

function focusFirstOpenLine() {
  const card = els.detail.querySelector(".ycard[data-yid]");
  if (card) { card.focus(); card.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" }); }
}

const listOn = {
  retry: () => ctl.loadAll().then((ok) => { if (ok) startEvents(); }),
  segment: (segment) => dispatch({ type: "segment", segment }),
  open: (id) => ctl.select(id, "work"),
};

const shellOn = {
  rules: () => openDialog(els.dialog, "Rules in effect", rulesBody(S().meta), { side: true }),
  toggleLive,
  presenter: () => dispatch({ type: "presenter", on: !S().presenter }),
  demoMenu,
  shortcuts,
  // Logging out also stops the event stream; logging in starts it again (no stream with an expired cookie).
  logout: () => { stopEvents(); return actions.logout(); },
  login: (passcode) => actions.login(passcode).then((ok) => { if (ok) startEvents(); }),
};

const liveOn = {
  exit: () => backToWork(),
  stopReplay: () => { actions.stopReplay(); backToWork(); },
  follow: (id) => ctl.follow(id),
  announce: (on) => dispatch({ type: "announceLive", on }),
  showTalkQr: (lang) => openDialog(els.dialog, lang === "es" ? "Talk page in Spanish" : "Talk page", talkQrBody(lang)),
  forget: (id) => dispatch({ type: "live/forget", id }),
};

function toggleLive() {
  if (S().view === "live") backToWork();
  else dispatch({ type: "view", view: "live" });
}

// Esc in the Live view returns to the work view on this case (A3.8).
function backToWork() {
  const s = S();
  const id = s.replay ? s.replay.id : liveCaseId(s);
  if (s.replay) actions.stopReplay();
  // A followed call that has ended is let go here, so L later shows the selected case or the next live call.
  if (s.followId && callIsOver(S(), s.followId)) dispatch({ type: "unfollow" });
  if (id && id !== S().selectedId) ctl.select(id, "work");
  else dispatch({ type: "view", view: "work" });
}

function demoMenu() {
  if (!S().meta || !S().meta.demo_mode) return;
  openDialog(els.dialog, "Demo", demoMenuBody(S(), {
    reset: async () => {
      const r = await actions.demoReset();
      return r ? { text: resetResult(r.deleted ?? 0) } : null;
    },
    seed: async () => { const r = await actions.demoSeed(); return r ? { text: S().demoResult } : null; },
    replay: () => { closeDialog(); startReplay(); },
    cardQr: () => {
      const s = S();
      const d = s.selectedId && s.details[s.selectedId] && s.details[s.selectedId].data;
      if (d && d.card_url) openDialog(els.dialog, "Student card", qrBody(d));
    },
    followLive: (on) => dispatch({ type: "followLive", on }),
  }));
}

function shortcuts() {
  openDialog(els.dialog, "Keyboard shortcuts", shortcutsBody(S(), { shortcutsOn: (on) => dispatch({ type: "shortcuts", on }) }));
}

function startReplay() {
  const s = S();
  const id = s.selectedId;
  const d = id && s.details[id] && s.details[id].data;
  if (!d || !(d.case.timeline || []).length) { ctl.toast("Choose a case with answers to replay it."); return; }
  replayShown.clear();
  actions.startReplay(id, replayFrames(d, { reduced: reducedMotion() }));
}

// ---------------------------------------------------------------- keyboard shortcuts (A2.7)

function typing(target) {
  if (!target || !(target instanceof Element)) return false;
  return !!target.closest("input, select, textarea, [contenteditable=''], [contenteditable='true']");
}

document.addEventListener("keydown", (e) => {
  const s = S();
  if (s.auth !== "ok") return;
  if (e.key === "Escape") {
    if (els.dialog.open || e.defaultPrevented) return;
    if (s.replay) { e.preventDefault(); actions.stopReplay(); backToWork(); return; }
    if (s.view === "live") { e.preventDefault(); backToWork(); }
    return;
  }
  if (!s.shortcutsOn || e.ctrlKey || e.metaKey || e.altKey || typing(e.target) || els.dialog.open) return;
  const k = e.key;
  if (k === "?" || (e.shiftKey && e.code === "Slash")) { e.preventDefault(); shortcuts(); return; }
  if (e.shiftKey && (k === "T" || k === "t")) { e.preventDefault(); window.open("/talk", "_blank", "noopener"); return; }
  if (e.shiftKey && (k === "D" || k === "d")) { e.preventDefault(); demoMenu(); return; }
  if (e.shiftKey) return;
  if (k === "l" || k === "L") { e.preventDefault(); toggleLive(); }
  else if (k === "p" || k === "P") { e.preventDefault(); shellOn.presenter(); }
  else if (k === "r" || k === "R") { e.preventDefault(); startReplay(); }
});

// ---------------------------------------------------------------- render

const liveView = createLiveView(els.live, liveOn);
const replayShown = new Map();
let prev = null;
let newRows = new Map();

function liveModel(s) {
  const base = { meta: s.meta, elapsed: (cid) => elapsedMs(s, cid, Date.now()), announce: s.announceLive };
  if (s.replay) {
    const i = s.replay.index;
    const f = s.replay.frames[i];
    if (!replayShown.has(i)) replayShown.set(i, Date.now());
    const before = i > 0 ? s.replay.frames[i - 1].detail : null;
    const diff = { ...diffDetail(before, f.detail), firstLoad: i === 0 };
    return { ...base, mode: "replay", id: s.replay.id, entry: { data: f.detail, diff, at: replayShown.get(i) },
      now: f.now, turn: f.turn, replayLast: f.last, lines: [] };
  }
  const id = liveCaseId(s);
  const sum = id ? s.list.byId[id] : null;
  if (!id || (!sum && !s.details[id])) return { ...base, mode: "idle" };
  const others = Object.values(s.list.byId).filter((x) => x.live && x.id !== id);
  return { ...base, mode: "case", id, entry: s.details[id], lines: s.live.lines[id] || [], now: s.live.now[id] || null,
    live: sum ? !!sum.live : null, ended: callIsOver(s, id), otherLive: others.length,
    otherLiveId: others.length ? others[0].id : null,
    idleMs: s.live.lastEventAt[id] ? Date.now() - s.live.lastEventAt[id] : 0 };
}

function detailInputsChanged(s, p) {
  if (!p) return true;
  return s.selectedId !== p.selectedId || s.details[s.selectedId] !== p.details[p.selectedId] || s.sections !== p.sections
    || s.editing !== p.editing || s.lockError !== p.lockError || s.changes !== p.changes || s.busy !== p.busy
    || s.meta !== p.meta || s.view !== p.view || s.list.loaded !== p.list.loaded
    || (!s.selectedId && s.list.byId !== p.list.byId);
}

function render(s) {
  document.documentElement.classList.toggle("presenter", s.presenter);
  const loginMode = s.auth === "login";
  els.login.hidden = !loginMode;
  els.topbar.hidden = loginMode;
  els.steps.hidden = loginMode;
  els.main.hidden = loginMode;
  els.banners.hidden = loginMode;
  if (loginMode) { renderLogin(els.login, s, shellOn); prev = s; return; }
  if (!prev || prev.meta !== s.meta || prev.conn !== s.conn || prev.presenter !== s.presenter || prev.view !== s.view
    || prev.auth !== s.auth) renderTopbar(els.topbar, s, shellOn);
  renderBanners(els.banners, s);
  const liveMode = s.view === "live";
  els.work.hidden = liveMode;
  els.live.hidden = !liveMode;
  if (!liveMode) {
    if (prev && prev.list.loaded && prev.list.byId !== s.list.byId) {
      for (const id of Object.keys(s.list.byId)) if (!prev.list.byId[id]) newRows.set(id, Date.now());
    }
    if (!prev || prev.list !== s.list || prev.selectedId !== s.selectedId || prev.segment !== s.segment
      || prev.view !== s.view || prev.auth !== s.auth) {
      renderList(els.list, s, listOn);
      for (const [id, at] of newRows) {
        if (Date.now() - at > 1000) { newRows.delete(id); continue; }
        const row = els.list.querySelector(`[data-key="row-${CSS.escape(id)}"]`);
        if (row) row.classList.add("is-arriving");
      }
    }
    if (detailInputsChanged(s, prev)) renderDetail(els.detail, s, detailOn);
    liveView.wipeIfEnded((id) => callIsOver(s, id));
  } else {
    liveView.update(liveModel(s));
  }
  renderToasts(els.toasts, s);
  if (reducedMotion()) staticNewDots();
  if (pendingFocus) {
    const el = document.querySelector(`[data-key="${CSS.escape(pendingFocus)}"]`);
    if (el) { el.focus(); pendingFocus = null; }
  }
  prev = s;
}

ctl.subscribe((s) => render(s));

// Reduced motion: no sweep; a field that just filled keeps a static "new" dot for 3 s (docs/UI_SPEC.md A6.8).
function staticNewDots() {
  const fresh = [...document.querySelectorAll(".is-new:not([data-new-timer])")];
  for (const el of fresh) el.dataset.newTimer = "1";
  if (fresh.length) setTimeout(() => { for (const el of fresh) el.classList.remove("is-new"); }, 3000);
}

// One-second tick: elapsed clocks of live calls, the 60-second no-activity hint.
setInterval(() => {
  const s = S();
  for (const span of document.querySelectorAll("[data-elapsed]")) {
    const ms = elapsedMs(s, span.dataset.elapsed, Date.now());
    span.textContent = span.closest(".live__head") ? minSec(ms, true) : minSec(ms);
  }
  if (s.view === "live" && !s.replay) liveView.tick(liveModel(s));
}, 1000);

// ---------------------------------------------------------------- events and recovery

let sub = null;
function stopEvents() {
  if (sub) sub.close();
  sub = null;
}
function startEvents() {
  if (sub) return;
  if (FIXTURES && new URLSearchParams(location.search).get("events") === "0") return;
  sub = subscribeEvents({
    onEvent: (evt) => { ctl.handleEvent(evt); },
    onMode: (mode) => dispatch({ type: "conn", mode }),
    sinceSeq: S().list.seq,
  });
}

// Server unreachable: keep the data on screen and retry with a backoff of 1 s to 5 s (A3.12).
let retryDelay = 1000;
let retrying = false;
async function recover() {
  if (retrying) return;
  retrying = true;
  while (S().offline && S().auth !== "login") {
    await new Promise((r) => setTimeout(r, retryDelay));
    retryDelay = Math.min(5000, retryDelay + 1000);
    const ok = S().meta ? await ctl.loadList().then(() => true, (err) => { ctl.handleFailure(err); return false; })
      : await ctl.loadAll();
    if (ok) { dispatch({ type: "online" }); startEvents(); }
  }
  retryDelay = 1000;
  retrying = false;
}
ctl.subscribe((s, p) => { if (s.offline && !p.offline) recover(); });

async function boot() {
  render(S());
  const ok = await ctl.loadAll();
  if (ok) startEvents();
}

boot();
