// Console state: a pure reducer, selectors, the detail diff that drives the animations, the replay frames, and a
// controller that runs the API calls through an injected fetchJSON (docs/UI_SPEC.md A3.1, A2.5, A2.6, A8.3).
// No DOM and no global state here, so node unit tests can drive it with a fetch stub.
import { lockReason, CONFLICT_TOAST, resetResult, seedResult } from "./text.js";

export function initialState(prefs = {}) {
  return {
    auth: "unknown", // unknown | login | ok
    loginError: null,
    meta: null,
    list: { byId: {}, seq: null, serverTime: null, loaded: false, error: null },
    segment: prefs.segment || "all",
    selectedId: prefs.selectedId || null,
    details: {}, // id → {data, diff, at, loading, error, gone}
    view: "work", // work | live
    followId: null,
    live: { lines: {}, now: {}, anchors: {}, lastEventAt: {}, ended: {}, seenCreated: {}, gotTurn: {} },
    conn: "connecting", // connecting | live | polling | replay
    offline: null, // {since}
    lastUpdate: null,
    presenter: !!prefs.presenter,
    shortcutsOn: prefs.shortcutsOn !== false,
    followLive: prefs.followLive !== false,
    announceLive: false,
    sections: { trace: false, programs: false },
    programsAutoOpened: {},
    programsPending: {},
    editing: null, // yellow line id being edited
    lockError: null, // {id, message}
    changes: {}, // id → {from, to, at}: the estimate change after an edit
    toasts: [],
    replay: null, // {id, frames, index}
    demoResult: null,
    busy: {},
  };
}

// ---------------------------------------------------------------- selectors

export const isNeedsReview = (s) => s.status === "new" && (s.yellow_open > 0 || s.tier === "coordinator");

export function sortedSummaries(state) {
  return Object.values(state.list.byId).sort((a, b) => {
    if (a.live !== b.live) return a.live ? -1 : 1;
    return Date.parse(b.created_at) - Date.parse(a.created_at);
  });
}

export function segmentCounts(state) {
  const all = Object.values(state.list.byId);
  return { review: all.filter(isNeedsReview).length, live: all.filter((s) => s.live).length, all: all.length };
}

export function visibleSummaries(state) {
  const items = sortedSummaries(state);
  if (state.segment === "review") return items.filter(isNeedsReview);
  if (state.segment === "live") return items.filter((s) => s.live);
  return items;
}

export const detailOf = (state, id) => (id && state.details[id] ? state.details[id].data : null);

export function openYellow(detail) {
  return ((detail && detail.case && detail.case.yellow_lines) || []).filter((y) => !y.resolved);
}

// Section 6b needs both the case's programs result and the programs meta; both are null with GP_PROGRAMS=0, and then
// neither 6b nor the "From the card" answers are shown (docs/UI_SPEC.md A3.5).
export const programsShown = (detail, meta) => !!(detail && detail.programs && meta && meta.programs);
export const cardAnswersShown = (meta) => !!(meta && meta.programs);

// The case the Live view shows: the followed call, else the selected case.
export const liveCaseId = (state) => state.followId || state.selectedId;

export function otherLiveCount(state) {
  return Object.values(state.list.byId).filter((s) => s.live && s.id !== state.followId).length;
}

// Milliseconds since a live call started, from the newest event's server time plus the local time since then.
export function elapsedMs(state, id, nowMs) {
  const s = state.list.byId[id];
  const d = detailOf(state, id);
  const created = Date.parse((s && s.created_at) || (d && d.case.created_at));
  if (!Number.isFinite(created)) return 0;
  const a = state.live.anchors[id];
  if (a) return Math.max(0, a.at - created + (nowMs - a.client));
  if (state.list.serverTime && state.list.loadedAt) {
    return Math.max(0, Date.parse(state.list.serverTime) - created + (nowMs - state.list.loadedAt));
  }
  return Math.max(0, nowMs - created);
}

// ---------------------------------------------------------------- diff (drives the fill sweep and the 6b sweep)

// A field "fills" when its value, display, state or confirmation changes (a source change alone is not a fill).
const slotKey = (s) => (s ? [s.value, s.display, s.state, s.confirmed].join("|") : "");
const programLineKey = (l) => JSON.stringify([l.status, l.display_yearly, l.counted, l.applied, l.range_lo, l.range_hi,
  l.basis, l.note_keys]);

export function diffDetail(prev, next) {
  const out = { slots: [], programs: [], footer: false, notes: [], estimate: null, range: false, asked: 0, skipped: 0,
    answers: false, progress: false, liveEnded: false, unlocked: false, firstLoad: !prev };
  if (!next) return out;
  const pc = prev ? prev.case : null;
  const nc = next.case;
  for (const [name, slot] of Object.entries(nc.slots || {})) {
    if (!pc || slotKey(pc.slots && pc.slots[name]) !== slotKey(slot)) out.slots.push(name);
  }
  if (!prev) return out;
  if (pc.estimate_monthly !== nc.estimate_monthly) out.estimate = { from: pc.estimate_monthly, to: nc.estimate_monthly };
  const pr = pc.estimate_range;
  const nr = nc.estimate_range;
  out.range = JSON.stringify(pr) !== JSON.stringify(nr);
  out.asked = Math.max(0, (nc.asked || []).length - (pc.asked || []).length);
  out.skipped = Math.max(0, (nc.skipped || []).length - (pc.skipped || []).length);
  out.answers = JSON.stringify(pc.program_answers || {}) !== JSON.stringify(nc.program_answers || {});
  out.progress = JSON.stringify(pc.program_progress || {}) !== JSON.stringify(nc.program_progress || {});
  out.liveEnded = pc.live && !nc.live;
  out.unlocked = openYellow(prev).length > 0 && openYellow(next).length === 0;
  const pp = prev.programs;
  const np = next.programs;
  if (np) {
    const before = new Map(((pp && pp.lines) || []).map((l) => [l.id, programLineKey(l)]));
    for (const l of np.lines || []) if (before.get(l.id) !== programLineKey(l)) out.programs.push(l.id);
    out.footer = !pp || pp.found_display !== np.found_display || pp.claimed_display !== np.claimed_display
      || out.programs.length > 0;
    const oldNotes = new Set((pp && pp.console_notes) || []);
    out.notes = (np.console_notes || []).filter((n) => !oldNotes.has(n));
  }
  return out;
}

// ---------------------------------------------------------------- replay frames (A2.6: 2×, steps 0.6–3 s)

export function replayFrames(detail, { reduced = false } = {}) {
  const c = detail.case;
  const points = [...(c.timeline || [])].sort((a, b) => a.turn - b.turn);
  const final = { delay: 0, turn: null, detail: { ...detail, case: { ...c, live: false } }, now: null, last: true };
  if (reduced || !points.length) return [final];
  const frames = [];
  const at = (x) => Date.parse(x);
  let prevAt = at(c.created_at);
  let range = null;
  frames.push({ delay: 0, turn: 0, now: null, last: false,
    detail: { ...detail, case: { ...c, live: true, slots: {}, estimate_range: null, asked: [], skipped: [],
      estimate_monthly: null, tier: null, reason_code: null, yellow_lines: [], first_month: null } } });
  points.forEach((p, i) => {
    const gap = Number.isFinite(at(p.at)) && Number.isFinite(prevAt) ? (at(p.at) - prevAt) / 2 : 600;
    prevAt = at(p.at);
    if (p.lo !== null && p.lo !== undefined) range = { lo: p.lo, hi: p.hi, settled: p.lo === p.hi };
    const slots = {};
    for (const [k, s] of Object.entries(c.slots || {})) if (s.turn !== null && s.turn !== undefined && s.turn <= p.turn) slots[k] = s;
    const last = i === points.length - 1;
    const settled = range && range.settled;
    frames.push({
      delay: Math.min(3000, Math.max(600, gap)), turn: p.turn, last: false,
      now: (c.asked || []).find((a) => a.turn === p.turn) || null,
      detail: { ...detail, case: { ...c, live: true, slots: last ? c.slots : slots, estimate_range: range,
        asked: (c.asked || []).filter((a) => a.turn <= p.turn), skipped: settled || last ? c.skipped : [],
        estimate_monthly: settled ? c.estimate_monthly : null, tier: settled ? c.tier : null,
        reason_code: settled ? c.reason_code : null, yellow_lines: [], first_month: null } },
    });
  });
  final.delay = 900;
  frames.push(final);
  return frames;
}

// ---------------------------------------------------------------- reducer

// Transcript order: by turn; within a turn the student speaks first and GatorPlate answers, then by time (a silence
// re-prompt keeps the turn number of the question it repeats, so one turn can hold two GatorPlate lines).
const lineOrder = (a, b) => a.turn - b.turn || (a.who === "student" ? 0 : 1) - (b.who === "student" ? 0 : 1)
  || (Date.parse(a.at) || 0) - (Date.parse(b.at) || 0);
// One transcript line's identity: the same line from a live.turn event and from GET /api/cases/{id}/live.
export const lineKey = (l) => `${l.turn}|${l.who}|${l.at || ""}|${l.text}`;
const hasLine = (lines, l) => lines.some((m) => lineKey(m) === lineKey(l));

// The live transcript lives in memory for the current call only: when the call ends (live.ended, or a summary that
// is no longer live on the polling path) the console drops its lines too (docs/SPEC.md §8.6).
function dropLines(s, id) {
  if (!id || !s.live.lines[id]) return s;
  return { ...s, live: { ...s.live, lines: drop(s.live.lines, id) } };
}
export const callIsOver = (s, id) => (s.live.ended[id] !== undefined && s.live.ended[id] !== null)
  || !!(s.list.byId[id] && s.list.byId[id].live === false);
const put = (obj, key, val) => ({ ...obj, [key]: val });
const drop = (obj, key) => { const o = { ...obj }; delete o[key]; return o; };

function upsertSummary(list, s, { force = false } = {}) {
  if (!s || !s.id) return list;
  const old = list.byId[s.id];
  if (old && old.version > s.version && !force) return list;
  return { ...list, byId: put(list.byId, s.id, s) };
}

function onScreen(state, id) {
  return (state.view === "work" && state.selectedId === id) || (state.view === "live" && liveCaseId(state) === id);
}

// Section 6b opens by itself once per case, on the first card answer or "I applied" mark while the case is on screen
// (docs/UI_SPEC.md A3.5 item 6b); the user can close it again. 6b lives in the case detail: while the Live view shows
// the case (right after the call, when the judge starts tapping), the opening waits for the work view.
function openProgramsOnce(s, id) {
  if (s.programsAutoOpened[id]) return s;
  if (s.view === "work" && s.selectedId === id) {
    return { ...s, sections: { ...s.sections, programs: true }, programsAutoOpened: put(s.programsAutoOpened, id, true),
      programsPending: drop(s.programsPending, id) };
  }
  if (onScreen(s, id)) return { ...s, programsPending: put(s.programsPending, id, true) };
  return s;
}
const settlePrograms = (s) => (s.view === "work" && s.selectedId && s.programsPending[s.selectedId]
  ? openProgramsOnce(s, s.selectedId) : s);

function applyEvent(state, evt, nowMs) {
  let s = state;
  const id = evt.case_id || (evt.summary && evt.summary.id) || null;
  if (id && evt.at) s = { ...s, live: { ...s.live, anchors: put(s.live.anchors, id, { at: Date.parse(evt.at), client: nowMs }) } };
  if (id) s = { ...s, live: { ...s.live, lastEventAt: put(s.live.lastEventAt, id, nowMs) } };
  switch (evt.type) {
    case "case.created":
    case "case.updated": {
      s = { ...s, list: upsertSummary(s.list, evt.summary, { force: evt.type === "case.created" }) };
      if (Object.prototype.hasOwnProperty.call(evt, "now_asking") && id) {
        s = { ...s, live: { ...s.live, now: put(s.live.now, id, { key: evt.now_asking, text: evt.now_asking_text,
          reason: evt.asked_reason }) } };
      }
      if (evt.type === "case.created" && id) {
        s = { ...s, live: { ...s.live, seenCreated: put(s.live.seenCreated, id, true), ended: drop(s.live.ended, id) } };
        const following = s.followId && s.list.byId[s.followId] && s.list.byId[s.followId].live;
        const isLive = evt.summary ? evt.summary.live : true;
        if (isLive && !following && (s.presenter || s.followLive)) {
          s = { ...s, followId: id, view: "live", replay: null };
        }
      }
      if (evt.changed_programs && id) s = openProgramsOnce(s, id);
      if (evt.summary && evt.summary.live === false) s = dropLines(s, id);
      return s;
    }
    case "case.deleted": {
      if (!id) return s;
      return { ...s, list: { ...s.list, byId: drop(s.list.byId, id) }, details: drop(s.details, id),
        selectedId: s.selectedId === id ? null : s.selectedId, followId: s.followId === id ? null : s.followId };
    }
    case "live.turn": {
      const line = evt.line;
      if (!line || !line.case_id) return s;
      const cid = line.case_id;
      s = { ...s, live: { ...s.live, gotTurn: put(s.live.gotTurn, cid, true) } };
      if (callIsOver(s, cid)) return s; // a late line after the call ended is never kept
      const lines = s.live.lines[cid] || [];
      if (hasLine(lines, line)) return s;
      const next = [...lines, line].sort(lineOrder);
      return { ...s, live: { ...s.live, lines: put(s.live.lines, cid, next) } };
    }
    case "live.ended": {
      if (!id) return s;
      const sum = s.list.byId[id];
      const list = sum ? { ...s.list, byId: put(s.list.byId, id, { ...sum, live: false }) } : s.list;
      // The transcript is wiped here, whatever the console shows; the Live view clears its own bubbles on screen.
      return dropLines({ ...s, list, live: { ...s.live, ended: put(s.live.ended, id, nowMs), now: drop(s.live.now, id) } }, id);
    }
    default:
      return s;
  }
}

export function reduce(state, action) {
  const now = action.now ?? 0;
  switch (action.type) {
    case "auth/login": return { ...state, auth: "login", loginError: action.error || null };
    case "auth/ok": return { ...state, auth: "ok", loginError: null };
    case "meta/loaded": return { ...state, meta: action.meta };
    case "list/loaded": {
      const byId = {};
      for (const it of action.list.items || []) byId[it.id] = it;
      return { ...state, list: { byId, seq: action.list.seq, serverTime: action.list.server_time, loadedAt: now,
        loaded: true, error: null }, lastUpdate: now, offline: null };
    }
    case "list/error": return { ...state, list: { ...state.list, error: action.error || "error" } };
    case "offline": return { ...state, offline: state.offline || { since: now } };
    case "online": return { ...state, offline: null, lastUpdate: now };
    case "conn": return { ...state, conn: action.mode };
    case "segment": return { ...state, segment: action.segment };
    case "select": {
      if (action.id === state.selectedId) return settlePrograms({ ...state, view: action.view || state.view });
      return settlePrograms({ ...state, selectedId: action.id, editing: null, lockError: null, view: action.view || state.view,
        sections: { trace: false, programs: false } });
    }
    case "view": return settlePrograms({ ...state, view: action.view, replay: action.view === "work" ? null : state.replay });
    case "follow": return { ...state, followId: action.id, view: "live", replay: null };
    case "unfollow": return state.followId ? { ...state, followId: null } : state;
    case "detail/loading":
      return { ...state, details: put(state.details, action.id, { ...(state.details[action.id] || {}), loading: true }) };
    case "detail/loaded": {
      const d = action.detail;
      const id = d.case.id;
      const old = state.details[id];
      const prev = old && old.data;
      const diff = diffDetail(prev && prev.case.id === id ? prev : null, d);
      let s = { ...state, details: put(state.details, id, { data: d, diff, at: now, loading: false, error: null }),
        list: upsertSummary(state.list, d.summary), lastUpdate: now, offline: null };
      if (diff.estimate && action.fromEdit) s = { ...s, changes: put(s.changes, id, { ...diff.estimate, at: now }) };
      // The polling path has no changed_programs flag: a new card answer or mark in the detail opens 6b the same way.
      if (diff.answers || diff.progress) s = openProgramsOnce(s, id);
      if (d.case.live === false) s = dropLines(s, id);
      if (state.lockError && state.lockError.id === id && openYellow(d).length === 0 && action.fromAction) {
        s = { ...s, lockError: null };
      }
      return s;
    }
    case "detail/error":
      return { ...state, details: put(state.details, action.id, { ...(state.details[action.id] || {}), loading: false,
        error: action.error || "error" }) };
    case "detail/gone": {
      const s = { ...state, details: drop(state.details, action.id), list: { ...state.list, byId: drop(state.list.byId, action.id) } };
      return { ...s, selectedId: s.selectedId === action.id ? null : s.selectedId, followId: s.followId === action.id ? null : s.followId };
    }
    case "live/loaded": {
      const v = action.live;
      if (!v || !v.case_id || callIsOver(state, v.case_id)) return state; // an answer that arrives after the end
      const merged = [...(state.live.lines[v.case_id] || [])];
      for (const l of v.lines || []) if (!hasLine(merged, l)) merged.push(l);
      merged.sort(lineOrder);
      const nowAsk = v.now_asking_text || v.now_asking ? { key: v.now_asking || null, text: v.now_asking_text, reason: v.asked_reason } : state.live.now[v.case_id];
      return { ...state, live: { ...state.live, lines: put(state.live.lines, v.case_id, merged),
        now: nowAsk ? put(state.live.now, v.case_id, nowAsk) : state.live.now } };
    }
    case "live/forget": return dropLines(state, action.id);
    case "event": return applyEvent(state, action.event, now);
    case "presenter": return { ...state, presenter: action.on };
    case "shortcuts": return { ...state, shortcutsOn: action.on };
    case "followLive": return { ...state, followLive: action.on };
    case "announceLive": return { ...state, announceLive: action.on };
    case "section": return { ...state, sections: { ...state.sections, [action.key]: action.open } };
    case "edit": return { ...state, editing: action.yid };
    case "lock/error": return { ...state, lockError: { id: action.id, message: action.message } };
    case "busy": return { ...state, busy: action.on ? put(state.busy, action.key, true) : drop(state.busy, action.key) };
    case "toast": return { ...state, toasts: [...state.toasts, { id: action.id, text: action.text, kind: action.kind || "info" }] };
    case "toast/dismiss": return { ...state, toasts: state.toasts.filter((t) => t.id !== action.id) };
    case "demo/result": return { ...state, demoResult: action.text };
    case "replay/start": return { ...state, replay: { id: action.id, frames: action.frames, index: 0 }, view: "live" };
    case "replay/step":
      return state.replay ? { ...state, replay: { ...state.replay, index: Math.min(action.index, state.replay.frames.length - 1) } } : state;
    case "replay/stop": return { ...state, replay: null };
    default: return state;
  }
}

// ---------------------------------------------------------------- effects of an event

// Which fetches an event needs: ["list"], ["detail", id], ["live", id].
export function effectsOf(prev, next, evt) {
  const out = [];
  const id = evt.case_id || (evt.summary && evt.summary.id) || null;
  const watched = new Set([next.selectedId, next.followId].filter(Boolean));
  // A reset deleted every case: only the list is fetched again (a watched case is gone, so no detail fetch).
  if (evt.type === "demo.reset") return [["list"]];
  if (evt.type === "resync") {
    out.push(["list"]);
    for (const w of watched) out.push(["detail", w]);
    return out;
  }
  if ((evt.type === "case.created" || evt.type === "case.updated") && id && watched.has(id)) {
    const have = detailOf(next, id);
    const newer = !evt.summary || !have || have.case.version !== evt.summary.version;
    if (evt.changed_programs || newer || evt.type === "case.created") out.push(["detail", id]);
  }
  // Without live.turn events for this call (a server that only keeps the lines for GET /live), each update of the
  // watched live call fetches the lines so far; the reducer drops the lines it already has.
  if (evt.type === "case.updated" && id && watched.has(id) && evt.summary && evt.summary.live
    && next.meta && next.meta.live_transcript && !next.live.gotTurn[id] && !callIsOver(next, id)) out.push(["live", id]);
  if (evt.type === "live.ended" && id && watched.has(id)) out.push(["detail", id]);
  if (next.followId && next.followId !== prev.followId && !next.live.seenCreated[next.followId]) out.push(["live", next.followId]);
  return out;
}

// ---------------------------------------------------------------- controller

export function createController({ fetchJSON, now = () => Date.now(), save = () => {}, prefs = {},
  setTimer = (fn, ms) => setTimeout(fn, ms), clearTimer = (t) => clearTimeout(t) } = {}) {
  let state = initialState(prefs);
  const subs = new Set();
  let toastSeq = 0;
  let replayTimer = null;

  const getState = () => state;
  const subscribe = (fn) => { subs.add(fn); return () => subs.delete(fn); };
  function dispatch(action) {
    const prev = state;
    state = reduce(state, { now: now(), ...action });
    if (state !== prev) {
      save(state);
      for (const fn of subs) fn(state, prev, action);
    }
    return state;
  }

  function toast(text, kind = "info", ms = 4000) {
    toastSeq += 1;
    const id = toastSeq;
    dispatch({ type: "toast", id, text, kind });
    setTimer(() => dispatch({ type: "toast/dismiss", id }), ms);
  }

  // A failed call: 401 → login; network or 5xx → offline banner; returns true when it was handled here.
  function handleFailure(err) {
    if (err && err.status === 401) { dispatch({ type: "auth/login" }); return true; }
    if (err && (err.status === 0 || err.status >= 500 || err.code === "network")) { dispatch({ type: "offline" }); return true; }
    return false;
  }

  async function call(url, opts) {
    const out = await fetchJSON(url, opts);
    if (state.offline) dispatch({ type: "online" });
    return out;
  }

  async function loadMeta() {
    const meta = await call("/api/meta");
    dispatch({ type: "meta/loaded", meta });
    dispatch({ type: "auth/ok" });
    return meta;
  }

  async function loadList() {
    const list = await call("/api/cases?limit=200");
    dispatch({ type: "list/loaded", list });
    return list;
  }

  async function loadAll() {
    try {
      await loadMeta();
      await loadList();
      const ids = [state.selectedId, state.followId].filter(Boolean);
      await Promise.all(ids.map((id) => refetchDetail(id)));
      return true;
    } catch (err) {
      if (!handleFailure(err)) dispatch({ type: "list/error", error: err && err.message });
      return false;
    }
  }

  async function refetchDetail(id) {
    if (!id) return null;
    dispatch({ type: "detail/loading", id });
    try {
      const detail = await call(`/api/cases/${encodeURIComponent(id)}`);
      dispatch({ type: "detail/loaded", detail });
      return detail;
    } catch (err) {
      if (err && err.status === 404) { dispatch({ type: "detail/gone", id }); return null; }
      if (!handleFailure(err)) dispatch({ type: "detail/error", id, error: err && err.message });
      return null;
    }
  }

  async function loadLive(id) {
    try {
      const live = await call(`/api/cases/${encodeURIComponent(id)}/live`);
      dispatch({ type: "live/loaded", live });
    } catch (err) {
      if (!(err && err.status === 404)) handleFailure(err);
    }
  }

  async function run(effect) {
    const [kind, id] = effect;
    if (kind === "list") {
      try { await loadList(); } catch (err) { handleFailure(err); }
    } else if (kind === "detail") await refetchDetail(id);
    else if (kind === "live") await loadLive(id);
  }

  async function handleEvent(evt) {
    const prev = state;
    dispatch({ type: "event", event: evt });
    const effects = effectsOf(prev, state, evt);
    await Promise.all(effects.map(run));
    return effects;
  }

  async function select(id, view) {
    dispatch({ type: "select", id, view });
    const tasks = [refetchDetail(id)];
    const sum = state.list.byId[id];
    if (sum && sum.live && !state.live.seenCreated[id]) tasks.push(loadLive(id));
    await Promise.all(tasks);
  }

  async function follow(id) {
    dispatch({ type: "follow", id });
    const tasks = [];
    if (!detailOf(state, id)) tasks.push(refetchDetail(id));
    const sum = state.list.byId[id];
    if (sum && sum.live && !state.live.seenCreated[id]) tasks.push(loadLive(id));
    await Promise.all(tasks);
  }

  // A mutation that answers with a CaseDetail; a 409 conflict refetches and shows the toast (A3.6).
  async function mutate(id, url, opts, { fromEdit = false } = {}) {
    const key = `${opts.method || "GET"} ${url}`;
    dispatch({ type: "busy", key, on: true });
    try {
      const detail = await call(url, opts);
      if (detail && detail.case) dispatch({ type: "detail/loaded", detail, fromEdit, fromAction: true });
      return { ok: true, detail };
    } catch (err) {
      if (err && err.status === 409 && err.code === "locked") {
        dispatch({ type: "lock/error", id, message: err.message || lockReason(Math.max(1, openYellow(detailOf(state, id)).length)) });
        await refetchDetail(id);
        return { ok: false, code: "locked" };
      }
      if (err && err.status === 409) {
        toast(CONFLICT_TOAST);
        await refetchDetail(id);
        return { ok: false, code: err.code || "conflict" };
      }
      if (err && err.status === 404) { dispatch({ type: "detail/gone", id }); return { ok: false, code: "not_found" }; }
      if (!handleFailure(err)) toast(err && err.message ? err.message : "Something went wrong.", "error");
      return { ok: false, code: err && err.code };
    } finally {
      dispatch({ type: "busy", key, on: false });
    }
  }

  const version = (id) => { const d = detailOf(state, id); return d ? d.case.version : 0; };

  const actions = {
    confirmYellow: (id, yid, note) => mutate(id, `/api/cases/${encodeURIComponent(id)}/yellow/${encodeURIComponent(yid)}`,
      { method: "POST", body: { action: "confirm", ...(note ? { note } : {}), expected_version: version(id) } }),
    editYellow: async (id, yid, value, note) => {
      const r = await mutate(id, `/api/cases/${encodeURIComponent(id)}/yellow/${encodeURIComponent(yid)}`,
        { method: "POST", body: { action: "edit", value, ...(note ? { note } : {}), expected_version: version(id) } },
        { fromEdit: true });
      if (r.ok) dispatch({ type: "edit", yid: null });
      return r;
    },
    markReviewed: (id) => mutate(id, `/api/cases/${encodeURIComponent(id)}/status`,
      { method: "POST", body: { status: "reviewed", expected_version: version(id) } }),
    setStatus: (id, status) => mutate(id, `/api/cases/${encodeURIComponent(id)}/status`,
      { method: "POST", body: { status, expected_version: version(id) } }),
    patchTracking: (id, patch) => mutate(id, `/api/cases/${encodeURIComponent(id)}/tracking`,
      { method: "PATCH", body: { ...patch, expected_version: version(id) } }),
    async deleteCase(id) {
      try {
        await call(`/api/cases/${encodeURIComponent(id)}`, { method: "DELETE" });
        dispatch({ type: "detail/gone", id });
        toast("Case deleted");
        return true;
      } catch (err) {
        if (err && err.status === 404) { dispatch({ type: "detail/gone", id }); toast("Case deleted"); return true; }
        if (!handleFailure(err)) toast(err && err.message ? err.message : "Something went wrong.", "error");
        return false;
      }
    },
    // Seed samples = POST /api/demo/seed alone; Reset demo = reset, then seed (A2.5).
    async demoSeed() {
      try {
        const r = await call("/api/demo/seed", { method: "POST", body: {} });
        const text = seedResult(r.seeded ?? 0);
        dispatch({ type: "demo/result", text });
        toast(text);
        await loadList();
        return r;
      } catch (err) {
        if (!handleFailure(err)) toast(err && err.message ? err.message : "Something went wrong.", "error");
        return null;
      }
    },
    async demoReset() {
      let reset = null;
      try {
        // nothing is watched while the cases are deleted, so no fetch asks for a case the reset just removed
        dispatch({ type: "select", id: null });
        dispatch({ type: "follow", id: null });
        reset = await call("/api/demo/reset", { method: "POST", body: {} });
        await call("/api/demo/seed", { method: "POST", body: {} });
        const text = resetResult(reset.deleted ?? 0);
        dispatch({ type: "demo/result", text });
        // Afterwards the Live view is idle, ready for the next judge group (docs/UI_SPEC.md A2.5).
        dispatch({ type: "replay/stop" });
        dispatch({ type: "select", id: null });
        dispatch({ type: "follow", id: null });
        dispatch({ type: "view", view: "live" });
        toast(text);
        await loadList();
        return reset;
      } catch (err) {
        if (!handleFailure(err)) toast(err && err.message ? err.message : "Something went wrong.", "error");
        // The reset went through and a later step failed: the list must not keep showing the removed cases.
        if (reset) await loadList().catch(() => {});
        return null;
      }
    },
    async login(passcode) {
      try {
        await fetchJSON("/api/console/login", { method: "POST", body: { passcode } });
        return await loadAll();
      } catch (err) {
        let msg = "Something went wrong. Try again.";
        if (err && err.status === 401) msg = "That passcode doesn't work.";
        else if (err && err.status === 429) msg = "Too many tries. Wait a minute and try again.";
        else if (err && (err.status === 0 || err.code === "network")) msg = "Can't reach the server. Try again.";
        dispatch({ type: "auth/login", error: msg });
        return false;
      }
    },
    async logout() {
      try { await fetchJSON("/api/console/logout", { method: "POST", body: {} }); } catch { /* the login screen follows anyway */ }
      dispatch({ type: "auth/login" });
    },
    startReplay(id, frames) {
      if (replayTimer) clearTimer(replayTimer);
      dispatch({ type: "replay/start", id, frames });
      const step = (i) => {
        if (!state.replay || i >= frames.length) return;
        replayTimer = setTimer(() => {
          if (!state.replay) return;
          dispatch({ type: "replay/step", index: i });
          step(i + 1);
        }, frames[i].delay);
      };
      step(1);
    },
    stopReplay() {
      if (replayTimer) clearTimer(replayTimer);
      replayTimer = null;
      dispatch({ type: "replay/stop" });
    },
  };

  return { getState, subscribe, dispatch, toast, loadAll, loadList, refetchDetail, loadLive, handleEvent, select,
    follow, actions, handleFailure };
}
