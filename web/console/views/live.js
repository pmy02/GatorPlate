// Live view (docs/UI_SPEC.md A3.8, A2.6, A6.8): memory-only transcript with the word-to-field highlight, the
// now-asking chip, the range bar with its count-up, compact answers, not-asked / never-asked and privacy chips, the
// end choreography and the second-call pill. The DOM persists per case so the bubbles, the band and the count-up move.
import { h, icon, chip, replace, countUp, reducedMotion } from "./dom.js";
import { compactAnswers } from "./answers.js";
import { reasonChip, notAskedChip, qrImage, talkQr } from "./detail.js";
import { followBottom } from "./follow.js";
import { money } from "../../shared/format.js";
import { lineKey } from "../store.js";
import {
  LIVE_CORE, NEVER_ASKED, ANSWERED_BEFORE, nowAskingChip, askedChip, skippedChip, answeredBeforeAsked, rangeLabel,
  reasonLabel, privacyChip, languageChip, FLAG_CHIPS, answersKept, callEnded, callDuration, filledCount, minSec,
  slotLabel, rulesPill, spokenMonthly,
} from "../text.js";

const CHANNELS = { phone: ["i-phone", "Phone"], web: ["i-globe", "Web"] };
const LANGS = { en: "EN", es: "ES" };
const FRESH_MS = 1500;
const REDACTION = /\[REDACTED\]|#{3,}/g;

export function createLiveView(root, on) {
  let key = null; // mode + case id the skeleton was built for
  let ui = null;
  let st = null; // per-case view memory

  function reset() {
    st = { lines: new Map(), marks: new Map(), pending: new Map(), maxHi: 0, settled: null, appliedDiffAt: 0,
      nowKey: undefined, phase: "none", wasLive: false, timers: [], qrFor: null, lastRangeKey: null, caseId: null };
  }

  function clearTimers() {
    if (st) for (const t of st.timers) clearTimeout(t);
  }

  function later(fn, ms) {
    st.timers.push(setTimeout(fn, reducedMotion() ? 0 : ms));
  }

  function update(model) {
    const k = `${model.mode}:${model.id || ""}`;
    if (k !== key) {
      clearTimers();
      if (ui && ui.follow) ui.follow.stop();
      key = k;
      reset();
      ui = model.mode === "idle" ? buildIdle(model) : buildCase(model);
    }
    if (model.mode === "idle") return updateIdle(model);
    updateCase(model);
  }

  // ------------------------------------------------------------ idle

  function buildIdle(model) {
    const meta = model.meta || {};
    const phone = meta.demo_phone_display;
    const node = h("div", { class: "live-idle" },
      h("div", { class: "live-idle__top" },
        h("h1", { class: "live-idle__title" }, icon("i-live"), "Live view"),
        exitButton()),
      h("div", { class: "live-idle__body" },
        h("div", { class: "live-idle__call" },
          h("p", { class: "live-idle__lede", text: "No live call right now. A new call opens here." }),
          phone ? h("p", { class: "live-idle__phone num" }, h("span", { class: "label", text: "Call" }), h("span", { text: phone })) : null,
          h("p", { class: "live-idle__talk" }, h("span", { class: "label", text: "Or talk in the browser" }),
            h("span", { class: "live-idle__url", text: `${location.origin}/talk` })),
          h("p", { class: "pill pill--rules", text: rulesPill(meta.rules) })),
        talkQr("en")));
    replace(root, node);
    return { node };
  }

  function updateIdle() { /* static */ }

  function exitButton() {
    return h("button", { class: "btn btn--console", type: "button", dataset: { key: "live-exit" },
      on: { click: () => on.exit() } }, icon("i-arrow-left"), "Exit live view · L");
  }

  // ------------------------------------------------------------ a case (live, ended or replay)

  function buildCase(model) {
    const title = h("strong", { class: "live__title" });
    const dot = h("span", { class: "live-dot", "aria-hidden": "true" });
    const elapsed = h("span", { class: "num live__elapsed" });
    const meta = h("span", { class: "live__meta" });
    const consent = h("span", { class: "live__consent" });
    const other = h("span", { class: "live__other" });
    const hint = h("p", { class: "live__hint", hidden: true }, icon("i-info"), "No activity for 1 min — the call may have dropped.");
    const head = h("header", { class: "live__head" }, dot, title, meta, elapsed,
      h("span", { class: "tag" }, icon("i-eye-off"), "Not recorded"), consent, other,
      h("span", { class: "live__spacer" }),
      model.mode === "replay"
        ? h("button", { class: "btn btn--console", type: "button", dataset: { key: "replay-stop" }, on: { click: () => on.stopReplay() } },
          icon("i-close"), "Stop replay · Esc")
        : exitButton());

    const announce = h("input", { type: "checkbox", id: "announce-live" });
    announce.addEventListener("change", () => on.announce(announce.checked));
    const transcript = h("ol", { class: "transcript", role: "list", "aria-label": "Live transcript" });
    const follow = followBottom(transcript);
    const nowBig = h("div", { class: "live__nowbig", hidden: true });
    const notice = h("p", { class: "live__notice", hidden: true });
    const qr = h("div", { class: "live__qr", hidden: true });
    const talk = h("section", { class: "live__talk", "aria-labelledby": "lt-label" },
      h("div", { class: "live__talk-head" },
        h("h2", { class: "label", id: "lt-label", text: model.mode === "replay" ? "Replay" : "Transcript" }),
        model.mode === "replay" ? null : h("label", { class: "toggle small", for: "announce-live" }, announce, "Announce live transcript")),
      transcript, nowBig, notice, qr);

    const rangeLo = h("span", { class: "range__end num" });
    const rangeHi = h("span", { class: "range__end num" });
    const band = h("span", { class: "range__band" });
    const track = h("div", { class: "range", "aria-hidden": "true" }, band);
    const rangePrefix = h("span", { class: "range__prefix", "aria-hidden": "true" });
    const rangeAmount = h("span", { class: "range__amount num", "aria-hidden": "true" });
    const rangeText = h("span", { class: "range__text" });
    const rangeSr = h("span", { class: "sr-only" });
    const rangeLabelEl = h("p", { class: "range__label" }, rangePrefix, rangeAmount, rangeText, rangeSr);
    const reason = h("p", { class: "live__reason", hidden: true });
    const rangeBox = h("div", { class: "range-wrap" }, rangeLo, track, rangeHi);
    const est = h("div", { class: "panel live__est" }, h("h2", { class: "label", text: "Estimate so far" }), rangeBox, rangeLabelEl, reason);

    const nowText = h("p", { class: "live__now" });
    const nowChip = h("div", { class: "live__nowchip" });
    const why = h("div", { class: "panel live__why" }, h("h2", { class: "label", text: "Now asking — why" }), nowText, nowChip);
    const chips = h("div", { class: "cluster live__chips" });

    const answers = h("div", { class: "live__answer-list" });
    const notAsked = h("div", { class: "cluster live__notasked" });
    const skips = h("div", { class: "live__skips" }, notAsked);
    const answersSec = h("section", { class: "live__answers", "aria-labelledby": "la-label", dataset: { scroll: "" } },
      h("h2", { class: "label", id: "la-label", text: "Answers" }), answers, skips);
    answersSec.addEventListener("mouseover", (e) => hot(e.target, true));
    answersSec.addEventListener("mouseout", (e) => hot(e.target, false));
    answersSec.addEventListener("focusin", (e) => hot(e.target, true));
    answersSec.addEventListener("focusout", (e) => hot(e.target, false));

    const side = h("section", { class: "live__side", "aria-label": "Estimate and why", dataset: { scroll: "" } }, est, why, chips);
    const node = h("div", { class: ["live-case", model.mode === "replay" && "is-replay"] }, head, hint,
      h("div", { class: "live__body" }, talk, side, answersSec));
    replace(root, node);
    return { node, title, dot, elapsed, meta, consent, other, hint, transcript, follow, nowBig, notice, qr, rangeLo, rangeHi,
      band, track, rangePrefix, rangeAmount, rangeText, rangeSr, reason, rangeBox, est, nowText, nowChip, why, chips, answers, notAsked,
      announce, talk, answersSec, skips };
  }

  function hot(target, on) {
    const row = target.closest && target.closest("[data-slot]");
    if (!row) return;
    for (const m of ui.transcript.querySelectorAll("mark.heard")) {
      if ((m.dataset.slots || "").split(" ").includes(row.dataset.slot)) m.classList.toggle("is-hot", on);
    }
  }

  function updateCase(model) {
    const entry = model.entry;
    const d = entry && entry.data;
    if (!d) { ui.title.textContent = "Loading the call…"; return; }
    const c = d.case;
    const replay = model.mode === "replay";
    st.caseId = c.id;
    // The list summary moves first (events), the detail follows its fetch: a call is live when the summary says so.
    const liveFlag = model.live === undefined || model.live === null ? c.live : model.live;
    const isLive = !replay ? (liveFlag && !model.ended) : !model.replayLast;
    if (isLive && !st.wasLive && st.phase !== "none") {
      // First seen ended (a stale detail), now live: start the transcript over instead of staying cleared.
      clearTimers();
      st.timers = [];
      st.phase = "none";
      ui.notice.hidden = true;
      ui.qr.hidden = true;
      st.qrFor = null;
    }
    if (isLive) st.wasLive = true;

    // Header
    const [ch, chName] = CHANNELS[c.channel] || CHANNELS.phone;
    ui.dot.hidden = !isLive;
    ui.title.textContent = replay ? (model.replayLast ? "Replay finished" : "Replay") : (isLive ? "Live call" : callEnded(callDuration(c)));
    replace(ui.meta, icon(ch), h("span", { text: chName }), h("span", { text: LANGS[c.lang] || c.lang }),
      c.seeded ? h("span", { class: "tag", text: "Sample" }) : null, replay ? chip("REPLAY", { cls: "chip--yellow" }) : null,
      replay && model.turn ? h("span", { class: "num", text: `Turn ${model.turn}` }) : null);
    ui.elapsed.hidden = !isLive || replay;
    if (isLive && !replay) { ui.elapsed.dataset.elapsed = c.id; ui.elapsed.textContent = minSec(model.elapsed(c.id), true); }
    if (c.consent && c.consent.given && c.consent.at) {
      replace(ui.consent, chip(`Consent ${minSec(Date.parse(c.consent.at) - Date.parse(c.created_at))}`, { cls: "chip--routine", iconId: "i-check" }));
    } else ui.consent.textContent = "";
    replace(ui.other, model.otherLive && model.otherLiveId && isLive
      ? h("button", { class: "pill pill--live", type: "button", dataset: { key: "other-live" }, on: { click: () => on.follow(model.otherLiveId) } },
        h("span", { class: "live-dot", "aria-hidden": "true" }), `Another live call (${model.otherLive})`) : null);
    ui.hint.hidden = !(isLive && !replay && model.idleMs > 60000);

    // Transcript (or Now asking in large type without the setting; the replay has none)
    const transcriptOn = !replay && model.meta && model.meta.live_transcript;
    ui.talk.querySelector(".toggle")?.toggleAttribute("hidden", !transcriptOn || !isLive);
    ui.transcript.hidden = !transcriptOn || st.phase === "cleared";
    ui.transcript.setAttribute("aria-live", model.announce ? "polite" : "off");
    ui.announce.checked = !!model.announce;
    // Lines are shown only while the call is live; after the end they are never painted again.
    if (transcriptOn && isLive && st.phase === "none") syncLines(model.lines || []);
    const freshDiff = entry.diff && !entry.diff.firstLoad && Date.now() - (entry.at || 0) < FRESH_MS;
    if (transcriptOn && isLive && freshDiff && entry.at !== st.appliedDiffAt) queueHeard(c, entry.diff.slots);
    if (freshDiff) st.appliedDiffAt = entry.at;
    if (transcriptOn && isLive && st.pending.size) markHeard(model.lines || []);
    const latest = Object.values(c.slots || {}).filter((s) => s.heard).sort((a, b) => (b.turn || 0) - (a.turn || 0))[0];
    ui.nowBig.hidden = transcriptOn || (!isLive && !replay);
    if (!ui.nowBig.hidden) {
      replace(ui.nowBig, h("p", { class: "label", text: replay ? "Steps through the saved timeline at 2× — no transcript" : "Now asking" }),
        h("p", { class: "live__nowbig-text num", text: replay ? (model.turn ? `Turn ${model.turn}` : "Start") : ((model.now && model.now.text) || "—") }),
        latest ? h("p", { class: "live__nowbig-quote" }, h("span", { class: "muted", text: "Newest answer " }), h("q", { class: "q", text: latest.heard })) : null);
    }

    // Estimate so far
    updateRange(c, isLive || replay);

    // Now asking — why
    let nowChipData = null;
    let nowTextValue = "";
    if (replay) {
      nowChipData = model.now ? askedChip(model.now) : null;
      nowTextValue = model.now ? (model.now.slots || []).map((s) => slotLabel(s, model.meta && model.meta.slot_specs)).join(", ") : "";
    } else if (isLive && model.now) {
      nowChipData = nowAskingChip(model.now.key, model.now.reason);
      nowTextValue = model.now.text || "";
    }
    ui.why.hidden = !isLive && !replay;
    const nk = `${nowTextValue}|${nowChipData ? nowChipData.text : ""}`;
    if (nk !== st.nowKey) {
      st.nowKey = nk;
      ui.nowText.textContent = nowTextValue || (isLive ? "—" : "");
      replace(ui.nowChip, nowChipData ? reasonChip(nowChipData) : null);
    }

    // Other chips, only from data
    const chips = [];
    for (const ev of c.privacy_events || []) chips.push(chip(privacyChip(ev), { cls: "chip--routine", iconId: "i-shield" }));
    for (const f of c.flags || []) if (FLAG_CHIPS[f]) chips.push(chip(FLAG_CHIPS[f], { cls: "chip--routine", iconId: "i-info" }));
    const lang = languageChip(c.language_request);
    if (lang) {
      chips.push(h("button", { class: "chip chip--outcome chip--button", type: "button", dataset: { key: "lang-qr" },
        on: { click: () => on.showTalkQr(c.language_request.asked === "es" ? "es" : "en") } }, icon("i-qr"), h("span", { text: lang })));
    }
    if (c.ended_early) chips.push(chip("Ended early", { cls: "chip--routine" }));
    replace(ui.chips, chips);

    // Answers, not asked, never asked: rebuilt only when the case data changes, so the fill sweep never restarts.
    if (st.answersFor !== d) {
      st.answersFor = d;
      const fresh = freshDiff ? new Set(entry.diff.slots) : new Set();
      replace(ui.answers, compactAnswers(c, model.meta && model.meta.slot_specs, fresh, LIVE_CORE));
      const newest = [...ui.answers.querySelectorAll(".is-new")].pop();
      if (newest) newest.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
    }
    const skipped = (c.skipped || []).map(skippedChip).filter(Boolean);
    const before = answeredBeforeAsked(c);
    const skipCount = skipped.length + before.length;
    replace(ui.notAsked,
      before.map((s) => chip(`${slotLabel(s, model.meta && model.meta.slot_specs)}: ${ANSWERED_BEFORE}`, { cls: "chip--routine chip--reason" })),
      skipped.length ? h("span", { class: "label live__chiplabel", text: "Not asked" }) : null,
      skipped.map((s) => notAskedChip(s)),
      h("span", { class: "label live__chiplabel", text: "Never asked" }),
      chip(NEVER_ASKED.replace(/^Never asked — /, ""), { cls: "chip--never", iconId: "i-lock" }));
    if (skipCount > (st.skipCount || 0) && (isLive || replay)) {
      ui.skips.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
    }
    st.skipCount = skipCount;

    // End choreography
    if (!replay && !isLive) endChoreography(model, d);
    if (replay && model.replayLast) showQr(d);

    // Every render re-pins a transcript that is following: a Presenter toggle re-renders and grows the text.
    ui.follow.pin();
  }

  function updateRange(c, moving) {
    const r = c.estimate_range;
    const nonLikely = c.tier && c.tier !== "likely";
    ui.rangeBox.hidden = !!nonLikely;
    ui.reason.hidden = !nonLikely;
    if (nonLikely) {
      ui.reason.textContent = reasonLabel(c.reason_code);
      ui.rangeAmount.textContent = "";
      ui.rangeText.textContent = "";
      ui.rangeSr.textContent = "";
      return;
    }
    const rk = JSON.stringify([r, !!c.estimate_is_floor]);
    if (rk === st.lastRangeKey) return;
    st.lastRangeKey = rk;
    ui.rangePrefix.textContent = "";
    if (!r) {
      ui.track.classList.add("is-empty");
      ui.band.hidden = true;
      ui.rangeLo.textContent = "";
      ui.rangeHi.textContent = "";
      ui.rangeAmount.textContent = "";
      ui.rangeText.textContent = rangeLabel(null);
      ui.rangeSr.textContent = "";
      st.settled = null;
      return;
    }
    ui.track.classList.remove("is-empty");
    ui.band.hidden = false;
    st.maxHi = Math.max(st.maxHi, r.hi, 1);
    const pct = (v) => `${((v * 100) / st.maxHi).toFixed(2)}%`;
    ui.band.style.setProperty("--lo", pct(r.lo));
    ui.band.style.setProperty("--hi", pct(r.hi));
    const settled = r.settled || r.lo === r.hi;
    ui.track.classList.toggle("is-settled", settled);
    ui.rangeLo.textContent = settled ? "" : money(r.lo);
    ui.rangeHi.textContent = money(r.hi);
    if (settled) {
      // A floor estimate reads "at least about", as in the summary band (docs/UI_SPEC.md A3.5 item 2).
      const floor = !!c.estimate_is_floor;
      ui.rangePrefix.textContent = floor ? "at least about " : "";
      ui.rangeText.textContent = " a month · Settled";
      ui.rangeSr.textContent = `${floor ? "at least about " : ""}${spokenMonthly(r.hi)}, settled`;
      if (st.settled === false && moving) countUp(ui.rangeAmount, r.hi, { from: 0, duration: 450, fmt: money });
      else ui.rangeAmount.textContent = money(r.hi);
    } else {
      ui.rangeAmount.textContent = "";
      ui.rangeText.textContent = `${rangeLabel(r)} · Not settled yet`;
      ui.rangeSr.textContent = "";
    }
    st.settled = settled;
  }

  // ------------------------------------------------------------ transcript

  // Lines arrive sorted (store.js); a line that arrives late (GET /live after the events) is inserted in its place.
  // Following is the reader's choice (views/follow.js), not the box's size when the lines arrive.
  function syncLines(lines) {
    const box = ui.transcript;
    let added = false;
    let prevLi = null;
    for (const line of lines) {
      const k = lineKey(line);
      const have = st.lines.get(k);
      if (have) { prevLi = have.li; continue; }
      const text = h("p", { class: "bubble__text" });
      const li = h("li", { class: ["bubble", `bubble--${line.who === "student" ? "student" : "assistant"}`] },
        h("span", { class: "bubble__who", text: line.who === "student" ? "Student" : "GatorPlate" }), text);
      paintText(text, line.text, []);
      st.lines.set(k, { li, text, line });
      if (prevLi) prevLi.after(li); else box.prepend(li);
      prevLi = li;
      added = true;
    }
    if (!added) return;
    const all = [...box.children];
    all.forEach((li, i) => li.classList.toggle("is-old", i < all.length - 2));
    ui.follow.pin();
  }

  // A field that just filled waits until a student line holds its words: the line may come before or after the
  // case update, depending on the path (events or GET /live).
  function queueHeard(c, slots) {
    for (const name of slots) {
      const s = c.slots && c.slots[name];
      if (s && s.heard) st.pending.set(name, s.heard);
    }
  }

  function markHeard(lines) {
    const students = lines.filter((l) => l.who === "student").reverse();
    for (const [name, heard] of st.pending) {
      for (const line of students) {
        let at = line.text.indexOf(heard);
        if (at < 0) at = line.text.toLowerCase().indexOf(heard.toLowerCase());
        if (at < 0) continue;
        const k = lineKey(line);
        const rec = st.lines.get(k);
        if (!rec) continue;
        const ranges = (st.marks.get(k) || []).filter((r) => r.slot !== name);
        ranges.push({ start: at, end: at + heard.length, slot: name });
        st.marks.set(k, ranges);
        paintText(rec.text, line.text, ranges);
        st.pending.delete(name);
        break;
      }
    }
  }

  // Remove every transcript node and forget the lines (the end of the call; also while the view is hidden).
  function wipeTranscript() {
    ui.transcript.replaceChildren();
    ui.transcript.classList.remove("is-clearing");
    ui.transcript.hidden = true;
    st.lines.clear();
    st.marks.clear();
    st.pending.clear();
    st.phase = "cleared";
  }

  // Text with "number removed" pills for redactions and <mark class="heard"> for words that became a field.
  function paintText(el, text, ranges) {
    const red = [...text.matchAll(REDACTION)].map((m) => [m.index, m.index + m[0].length]);
    const cuts = new Set([0, text.length]);
    for (const [a, b] of red) { cuts.add(a); cuts.add(b); }
    for (const r of ranges) { cuts.add(r.start); cuts.add(r.end); }
    const pts = [...cuts].filter((x) => x >= 0 && x <= text.length).sort((x, y) => x - y);
    const out = [];
    for (let i = 0; i < pts.length - 1; i += 1) {
      const a = pts[i];
      const b = pts[i + 1];
      if (a === b) continue;
      const inRed = red.find(([x, y]) => a >= x && b <= y);
      const slots = ranges.filter((r) => a >= r.start && b <= r.end).map((r) => r.slot);
      let node;
      if (inRed) {
        if (a !== inRed[0]) continue;
        node = h("span", { class: "pill-removed" }, icon("i-shield"), "number removed");
      } else node = document.createTextNode(text.slice(a, b));
      out.push(slots.length ? h("mark", { class: "heard", dataset: { slots: [...new Set(slots)].join(" ") } }, node) : node);
    }
    replace(el, out);
  }

  // ------------------------------------------------------------ end of the call

  function endChoreography(model, d) {
    if (st.phase === "none") {
      const shown = st.lines.size > 0;
      if (shown && st.wasLive) {
        st.phase = "ended";
        later(() => {
          ui.transcript.classList.add("is-clearing");
          later(() => {
            wipeTranscript();
            on.forget(d.case.id);
            showNotice(d);
            showQr(d);
          }, 600);
        }, 1500);
      } else {
        wipeTranscript();
        const id = d.case.id;
        queueMicrotask(() => on.forget(id)); // never dispatch in the middle of a render
        if (st.wasLive) showNotice(d);
        showQr(d);
      }
    } else if (st.phase === "cleared") {
      if (st.wasLive) showNotice(d);
      showQr(d);
    }
  }

  function showNotice(d) {
    ui.notice.hidden = false;
    replace(ui.notice, icon("i-eye-off"), h("span", { text: answersKept(filledCount(d.case)) }));
  }

  function showQr(d) {
    if (!d.card_url) { ui.qr.hidden = true; return; }
    const k = `${d.qr_svg_url}|${d.short_code}`;
    ui.qr.hidden = false;
    if (st.qrFor === k) return;
    st.qrFor = k;
    replace(ui.qr, h("figure", { class: "qr-panel" },
      d.qr_svg_url ? qrImage(d.qr_svg_url, `QR code for the student card of case ${d.case.code}`) : null,
      h("figcaption", {}, h("span", { text: "Student card — scan with your phone camera" }),
        h("span", { class: "code", text: d.case.code }),
        d.short_code ? h("span", { class: "code shortcode", text: String(d.short_code).replace(/^(\d{3})(\d{3})$/, "$1 $2") }) : null)));
  }

  function tick(model) {
    if (!ui || !ui.elapsed || ui.elapsed.hidden || !model || model.mode !== "case") return;
    const id = ui.elapsed.dataset.elapsed;
    if (id) ui.elapsed.textContent = minSec(model.elapsed(id), true);
    ui.hint.hidden = !(model.idleMs > 60000);
  }

  // Called while the Live view is hidden: a call that ended off screen loses its bubbles at once (no choreography);
  // the notice and the QR still show when the view opens again.
  function wipeIfEnded(isEnded) {
    if (!st || !ui || !ui.transcript || !st.caseId || !isEnded(st.caseId)) return;
    if (st.phase === "cleared" || (st.lines.size === 0 && st.phase === "none")) return;
    clearTimers();
    st.timers = [];
    wipeTranscript();
  }

  return { update, tick, wipeIfEnded, reset: () => { clearTimers(); key = null; } };
}
