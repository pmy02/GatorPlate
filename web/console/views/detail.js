// Case detail (docs/UI_SPEC.md A3.5-A3.9, A3.11, A3.12): header, summary band, yellow lines and the review lock,
// answers, why these questions, how we got the amount, more money (section 6b), tracking, student card, danger zone.
import { h, icon, chip, replace, rerender } from "./dom.js";
import { answersTable, sourceLegend, isFresh } from "./answers.js";
import { money, time, day } from "../../shared/format.js";
import {
  TIERS, STATUS_LABELS, reasonLabel, estimateParts, firstMonthText, expeditedChip, callDuration, askedChip,
  skippedChip, answeredBeforeAsked, askedCounter, NEVER_ASKED, ANSWERED_BEFORE, effectText, lockReason, LOCK_LIVE,
  checkedAt, reviewedAt, slotLabel, sourceText, countdown, INTERVIEW_MISSED, PROGRAMS_TITLE, programsHeader,
  PROGRAM_STATUS, programPerYear, programName, programsFooter, listOnlyLine, appliedText, canonicalDisplay, capFirst,
  emptyText, isoToPtLocal, ptLocalToIso, minSec,
} from "../text.js";
import { openYellow, elapsedMs, programsShown, cardAnswersShown } from "../store.js";

const CHANNELS = { phone: ["i-phone", "Phone"], web: ["i-globe", "Web"] };
const LANG_NAMES = { en: "English", es: "Spanish" };

export function renderDetail(el, state, on) {
  rerender(el, () => replace(el, build(state, on)), state.selectedId);
}

function build(state, on) {
  const id = state.selectedId;
  const entry = id ? state.details[id] : null;
  if (!state.list.loaded && !entry) return skeleton();
  if (!id) {
    if (state.list.loaded && !Object.keys(state.list.byId).length) return emptyState(state);
    return h("div", { class: "detail__none" }, h("p", { class: "muted", text: "Choose a case from the list." }));
  }
  if (!entry || !entry.data) {
    if (entry && entry.error) return h("div", { class: "detail__none" }, h("p", { text: "This case couldn't be loaded." }),
      h("button", { class: "btn btn--console", type: "button", on: { click: () => on.retry(id) } }, "Try again"));
    return skeleton();
  }
  const d = entry.data;
  const c = d.case;
  const meta = state.meta || {};
  const specs = meta.slot_specs || {};
  const progMeta = meta.programs || null;
  return h("article", { class: "case", "aria-labelledby": "case-title" },
    header(d, state, on),
    summaryBand(d, state, on),
    sectionNav(d, progMeta),
    yellowSection(d, state, on),
    h("section", { class: "section", id: "sec-answers", "aria-labelledby": "h-answers" },
      h("h2", { id: "h-answers", text: "Answers" }),
      answersTable(d, specs, entry, { questionOrder: progMeta ? progMeta.questions : undefined, showCard: cardAnswersShown(meta) }),
      sourceLegend()),
    whySection(d, specs),
    traceSection(d, state, on),
    programsShown(d, meta) ? programsSection(d, entry, state, on, progMeta) : null,
    trackingSection(d, state, on),
    d.card_url ? cardSection(d) : null,
    dangerSection(d, on));
}

function skeleton() {
  return h("div", { class: "case case--skeleton", "aria-busy": "true", "aria-label": "Loading the case" },
    h("span", { class: "skel skel--title" }), h("span", { class: "skel skel--band" }),
    h("span", { class: "skel skel--block" }), h("span", { class: "skel skel--block" }));
}

function emptyState(state) {
  const meta = state.meta || {};
  const phone = meta.demo_phone_display || null;
  // The demo number stands out (48 px in Presenter, docs/UI_SPEC.md A3.12) inside the same sentence.
  const text = emptyText(phone);
  const at = phone ? text.indexOf(phone) : -1;
  return h("div", { class: "empty" },
    h("p", { class: "empty__text" }, at < 0 ? text : [text.slice(0, at),
      h("span", { class: "empty__phone num", text: phone }), text.slice(at + phone.length)]),
    talkQr("en"));
}

export function talkQr(lang) {
  const url = `${location.origin}/talk${lang === "es" ? "?lang=es" : ""}`;
  return h("figure", { class: "qr-panel qr-panel--talk" },
    qrImage(`/api/qr/talk.svg?lang=${lang}`, `QR code for the talk page${lang === "es" ? " in Spanish" : ""}`),
    h("figcaption", {}, h("span", { text: "Talk page" }), h("span", { class: "qr-panel__url", text: url })));
}

// A server-made QR image; in fixture mode (a static server has no QR endpoint) or when it can't load, a plain
// placeholder of the same size.
const FIXTURE_MODE = new URLSearchParams(location.search).get("fixtures") === "1";
export function qrImage(src, alt, { lazy = false } = {}) {
  if (FIXTURE_MODE) return qrPlaceholder(alt);
  const img = h("img", { class: "qr", src, alt, width: "260", height: "260", decoding: "async", loading: lazy ? "lazy" : null });
  img.addEventListener("error", () => img.replaceWith(qrPlaceholder(alt)), { once: true });
  return img;
}

function qrPlaceholder(alt) {
  return h("span", { class: "qr qr--missing", role: "img", "aria-label": alt }, icon("i-qr"),
    h("span", { text: "QR code appears with the live server" }));
}

function header(d, state, on) {
  const c = d.case;
  const [ch, chName] = CHANNELS[c.channel] || CHANNELS.phone;
  const dur = c.live ? minSec(elapsedMs(state, c.id, Date.now())) : callDuration(c);
  return h("header", { class: "case__head" },
    h("div", { class: "case__title" },
      h("h1", { id: "case-title" }, "Case ", h("span", { class: "code", translate: "no", text: c.code })),
      h("p", { class: "case__meta" },
        h("span", {}, icon(ch), chName),
        h("span", { text: LANG_NAMES[c.lang] || c.lang }),
        c.consent && c.consent.at ? h("span", { class: "num", text: `consent ${time(c.consent.at)}` }) : null,
        dur ? h("span", { class: "num", dataset: c.live ? { elapsed: c.id } : {}, text: dur }) : null,
        c.live ? h("span", { class: "tag tag--live" }, h("span", { class: "live-dot", "aria-hidden": "true" }), "Live") : null,
        c.ended_early ? h("span", { class: "tag", text: "Ended early" }) : null,
        c.seeded ? h("span", { class: "tag", text: "Sample" }) : null,
        c.seeded && c.persona ? h("span", { class: "muted", text: c.persona }) : null)),
    h("div", { class: "case__actions" },
      d.card_url ? h("a", { class: "btn btn--console", href: d.card_url, target: "_blank", rel: "noopener",
        dataset: { key: "open-card" } }, icon("i-external"), "Open student card") : null,
      overflowMenu(d, on)));
}

function overflowMenu(d, on) {
  const menu = h("div", { class: "menu", role: "menu", hidden: true, id: "case-menu" },
    h("button", { class: "menu__item menu__item--danger", type: "button", role: "menuitem", dataset: { key: "menu-delete" },
      on: { click: () => { close(); on.askDelete(d.case); } } }, icon("i-trash"), "Delete case"));
  const btn = h("button", { class: "btn btn--console btn--icon", type: "button", "aria-haspopup": "menu",
    "aria-expanded": "false", "aria-controls": "case-menu", "aria-label": "More actions", title: "More actions",
    dataset: { key: "case-more" } }, icon("i-more"));
  function close() { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); }
  btn.addEventListener("click", () => {
    const open = menu.hidden;
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    if (open) menu.querySelector("button").focus();
  });
  menu.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); btn.focus(); } });
  menu.addEventListener("focusout", (e) => { if (!menu.contains(e.relatedTarget) && e.relatedTarget !== btn) close(); });
  return h("div", { class: "menu-wrap" }, btn, menu);
}

function summaryBand(d, state, on) {
  const c = d.case;
  const tier = c.tier ? TIERS[c.tier] : null;
  const est = c.tier === "likely" ? estimateParts(c.estimate_monthly, c.estimate_is_floor) : null;
  const change = state.changes[c.id] && Date.now() - state.changes[c.id].at < 15000 ? state.changes[c.id] : null;
  const exp = expeditedChip(c.expedited_possible);
  const fm = c.tier === "likely" ? firstMonthText(c.first_month) : null;
  const statuses = [c.status, ...(d.allowed_status || []).filter((s) => s !== "reviewed" && s !== c.status)];
  return h("section", { class: "band", "aria-label": "Result" },
    h("div", { class: "band__result" },
      tier ? chip(tier.label, { cls: tier.cls, iconId: tier.icon }) : chip(c.live ? "In progress" : "No result yet"),
      est
        ? h("p", { class: "band__amount", "aria-label": est.spoken },
          est.prefix ? h("span", { class: "band__prefix", text: est.prefix }) : null,
          h("span", { class: "band__num num", text: est.amount }), h("span", { class: "band__per", text: est.suffix }))
        : h("p", { class: "band__reason", text: c.reason_code ? reasonLabel(c.reason_code) : "—" }),
      change && change.from !== null && change.to !== null ? h("p", { class: "band__change num" },
        h("span", { text: money(change.from) }), icon("i-arrow-right"), h("span", { text: money(change.to) }),
        h("span", { class: "sr-only", text: "after the edit" })) : null,
      est ? h("p", { class: "band__caption", text: "estimate — the county decides" }) : null,
      exp ? chip(exp, { cls: "chip--coordinator", iconId: "i-clock" }) : null),
    fm ? h("div", { class: "band__first" }, icon("i-calendar"), h("p", { text: fm })) : null,
    h("div", { class: "band__status field" },
      h("label", { for: "status-select", text: "Status" }),
      h("select", { id: "status-select", class: "input input--console", disabled: c.live || statuses.length < 2,
        dataset: { key: "status-select", server: "1" }, on: { change: (e) => on.setStatus(e.target.value) } },
      statuses.map((s) => h("option", { value: s, selected: s === c.status, text: STATUS_LABELS[s] || s })))));
}

function sectionNav(d, progMeta) {
  const c = d.case;
  const links = [["sec-answers", "Answers"], ["sec-why", "Why these questions"],
    ["sec-trace", howTitle(c)], programsShown(d, { programs: progMeta }) ? ["sec-programs", "More money"] : null,
    ["sec-tracking", "Tracking"], d.card_url ? ["sec-card", "Student card"] : null].filter(Boolean);
  return h("nav", { class: "case__nav", "aria-label": "Sections of this case" },
    links.map(([href, label]) => h("a", { href: `#${href}`, text: label })));
}

const howTitle = (c) => (c.tier === "likely" && c.estimate_monthly !== null && c.estimate_monthly !== undefined
  ? `How we got ${money(c.estimate_monthly)}` : "How we got this result");

// ---------------------------------------------------------------- yellow lines and the lock (A3.6)

function yellowSection(d, state, on) {
  const c = d.case;
  const lines = c.yellow_lines || [];
  const open = openYellow(d);
  const specs = (state.meta && state.meta.slot_specs) || {};
  return h("section", { class: "section section--check", "aria-labelledby": "h-check" },
    h("h2", { id: "h-check" }, "To check ", h("span", { class: "num muted", text: `(${open.length})` })),
    lines.length ? h("ul", { class: "ylines", role: "list" }, lines.map((y) => h("li", {},
      y.resolved ? resolvedLine(y) : yellowCard(y, d, state, specs, on)))) : h("p", { class: "muted", text: "Nothing to check." }),
    lockBar(d, state, on));
}

function resolvedLine(y) {
  return h("div", { class: "yline-done" }, icon("i-check"),
    h("span", { class: "num", text: checkedAt(y.resolved_at) }),
    h("span", { class: "yline-done__reason", text: y.reason }),
    y.resolved_note ? h("span", { class: "muted", text: `· ${y.resolved_note}` }) : null);
}

function yellowCard(y, d, state, specs, on) {
  const busy = Object.keys(state.busy).some((k) => k.endsWith(`/yellow/${encodeURIComponent(y.id)}`));
  const editing = state.editing === y.id && y.slot;
  const eff = effectText(y.effect);
  return h("article", { class: "yellow-line ycard", tabindex: "-1", dataset: { key: `yl-${y.id}`, yid: y.id },
    "aria-labelledby": `yl-r-${y.id}` },
  h("div", { class: "ycard__body" },
    h("h3", { id: `yl-r-${y.id}`, text: y.reason }),
    y.heard ? h("p", { class: "ycard__heard" }, h("span", { class: "muted", text: "Student said " }), h("q", { class: "q", text: y.heard })) : null,
    y.assumed ? h("p", { class: "ycard__assumed", text: `Assumed: ${y.assumed}` }) : null,
    eff ? h("p", { class: "ycard__effect", text: eff }) : null,
    editing ? editForm(y, d, specs, state, on, busy) : null),
  editing ? null : h("div", { class: "ycard__actions" },
    h("button", { class: "btn btn--console btn--primary", type: "button", disabled: busy || d.case.live,
      dataset: { key: `yl-ok-${y.id}` }, on: { click: () => on.confirm(y.id) } }, icon("i-check"), "Looks right"),
    y.slot ? h("button", { class: "btn btn--console", type: "button", disabled: busy || d.case.live,
      dataset: { key: `yl-edit-${y.id}` }, on: { click: () => on.startEdit(y.id) } }, icon("i-pencil"), "Edit") : null));
}

function editForm(y, d, specs, state, on, busy = false) {
  const spec = specs[y.slot] || { type: "money" };
  const slot = d.case.slots ? d.case.slots[y.slot] : null;
  const label = slotLabel(y.slot, specs);
  const inputId = `edit-${y.id}`;
  let input;
  if (spec.type === "bool") {
    input = h("select", { id: inputId, class: "input input--console", dataset: { key: inputId } },
      h("option", { value: "true", selected: slot && slot.value === "true", text: "Yes" }),
      h("option", { value: "false", selected: slot && slot.value === "false", text: "No" }));
  } else if (spec.type === "enum" && spec.choices) {
    input = h("select", { id: inputId, class: "input input--console", dataset: { key: inputId } },
      spec.choices.map((ch) => h("option", { value: ch, selected: slot && slot.value === ch, text: ch.replace(/_/g, " ") })));
  } else {
    input = h("input", { id: inputId, name: "value", class: "input input--console num", type: "text",
      inputmode: spec.type === "int" ? "numeric" : "decimal", autocomplete: "off", spellcheck: "false", dataset: { key: inputId },
      value: slot && slot.value ? canonicalDisplay(slot.value, spec.type).replace(/^\$/, "") : "" });
  }
  const note = h("input", { id: `${inputId}-note`, name: "note", class: "input input--console", type: "text", maxlength: "200",
    autocomplete: "off", dataset: { key: `${inputId}-note` } });
  const error = h("p", { class: "field__error", id: `${inputId}-err`, hidden: true });
  const form = h("form", { class: "ycard__edit", novalidate: true },
    h("div", { class: "field" },
      h("label", { for: inputId, text: spec.type === "money" ? `${label} (${spec.periodic ? "dollars a month" : "dollars"})` : label }),
      input, error),
    h("div", { class: "field" }, h("label", { for: `${inputId}-note`, text: "Note (optional)" }), note),
    h("div", { class: "ycard__actions" },
      h("button", { class: "btn btn--console btn--primary", type: "submit", disabled: busy, dataset: { key: `${inputId}-save` } },
        "Save"),
      h("button", { class: "btn btn--console btn--quiet", type: "button", on: { click: () => on.cancelEdit() } }, "Cancel")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (busy) return; // one save at a time (a second one would only meet a version conflict)
    const ok = on.saveEdit(y.id, spec.type, input.value, note.value.trim());
    if (!ok) {
      error.hidden = false;
      error.replaceChildren(icon("i-alert-circle"), h("span", { text: spec.type === "money" ? "Enter an amount like 1100 or 1,100.50." : "Enter a valid value." }));
      input.setAttribute("aria-invalid", "true");
      input.setAttribute("aria-describedby", error.id);
      input.focus();
    }
  });
  queueMicrotask(() => { if (!document.activeElement || document.activeElement === document.body) input.focus(); });
  return form;
}

function lockBar(d, state, on) {
  const c = d.case;
  const open = openYellow(d);
  const err = state.lockError && state.lockError.id === c.id ? state.lockError.message : null;
  if (c.live) {
    return h("div", { class: "lockbar" }, h("button", { class: "btn btn--console btn--locked", type: "button",
      "aria-disabled": "true", "aria-describedby": "lock-reason", dataset: { key: "lock" } }, icon("i-lock"), "Mark reviewed"),
    h("p", { class: "lockbar__reason", id: "lock-reason", text: LOCK_LIVE }));
  }
  const canReview = (d.allowed_status || []).includes("reviewed");
  if (!canReview) {
    return c.reviewed_at || c.status !== "new"
      ? h("div", { class: "lockbar lockbar--done" }, icon("i-check-circle"),
        h("span", { text: c.reviewed_at ? reviewedAt(c.reviewed_at) : STATUS_LABELS[c.status] }))
      : null;
  }
  const locked = open.length > 0;
  const busy = Object.keys(state.busy).some((k) => k.endsWith("/status"));
  const reason = locked ? lockReason(open.length) : err;
  const entry = state.details[c.id];
  const justUnlocked = !locked && isFresh(entry) && entry.diff.unlocked;
  return h("div", { class: ["lockbar", locked && "is-locked", justUnlocked && "just-unlocked"] },
    h("button", {
      class: ["btn", "btn--console", locked ? "btn--locked" : "btn--primary"], type: "button",
      "aria-disabled": locked || busy ? "true" : null, "aria-describedby": reason ? "lock-reason" : null,
      dataset: { key: "lock" }, on: { click: () => (locked ? on.lockedActivate() : (busy ? null : on.markReviewed())) },
    }, h("span", { class: "lock-icon" }, icon("i-lock", "lock-icon__closed"), icon("i-unlock", "lock-icon__open")), "Mark reviewed"),
    reason ? h("p", { class: ["lockbar__reason", err && !locked && "is-error"], id: "lock-reason", role: err ? "alert" : null,
      text: reason }) : null);
}

// ---------------------------------------------------------------- why these questions (A3.10)

function whySection(d, specs) {
  const c = d.case;
  const asked = c.asked || [];
  const skipped = (c.skipped || []).map(skippedChip).filter(Boolean);
  const before = answeredBeforeAsked(c);
  return h("section", { class: "section", id: "sec-why", "aria-labelledby": "h-why" },
    h("h2", { id: "h-why", text: "Why these questions" }),
    h("p", { class: "small muted num", text: askedCounter(d.summary) }),
    h("h3", { class: "label", text: "Asked" }),
    asked.length ? h("ol", { class: "asked", role: "list" }, asked.map((a) => {
      const ch = askedChip(a);
      return h("li", { class: "asked__item" },
        h("span", { class: "asked__turn num", text: `Turn ${a.turn}` }),
        h("span", { class: "asked__slots", text: (a.slots || []).map((s) => slotLabel(s, specs)).join(", ") }),
        reasonChip(ch),
        a.outcomes && a.outcomes.length ? h("span", { class: "asked__outcomes small muted", text: a.outcomes.join(" · ") }) : null);
    })) : h("p", { class: "muted", text: "No questions asked yet." }),
    before.length ? h("div", { class: "cluster" }, before.map((s) => chip(`${slotLabel(s, specs)}: ${ANSWERED_BEFORE}`, { cls: "chip--routine" }))) : null,
    skipped.length ? [h("h3", { class: "label", text: "Not asked" }),
      h("div", { class: "cluster" }, skipped.map((s) => notAskedChip(s)))] : null,
    h("h3", { class: "label", text: "Never asked" }),
    h("div", { class: "cluster" }, chip(NEVER_ASKED, { cls: "chip--never", iconId: "i-lock" })));
}

export function reasonChip(ch) {
  if (!ch) return null;
  if (ch.style === "outcome") return chip(ch.text, { cls: "chip--outcome chip--reason", badge: "$" });
  return chip(ch.text, { cls: "chip--routine chip--reason" });
}

export function notAskedChip(s) {
  return chip(s.text, { cls: ["chip--not-asked", s.maxQuestions && "has-dot"].filter(Boolean).join(" ") });
}

// ---------------------------------------------------------------- how we got the amount (A3.5 item 6)

function traceSection(d, state, on) {
  const c = d.case;
  const sources = (d.rules && d.rules.sources) || [];
  const steps = c.rule_trace || [];
  const det = h("details", { class: "section section--fold", id: "sec-trace", open: state.sections.trace },
    h("summary", { dataset: { key: "sum-trace" } }, icon("i-chevron-down", "fold-icon"), h("h2", { text: howTitle(c) })),
    h("p", { class: "fold__lede" }, icon("i-table"), "Computed by the rules table — not by AI"),
    steps.length ? h("ol", { class: "trace", role: "list" }, steps.map((s) => h("li", { class: "trace__row" },
      h("p", { class: "trace__result", text: s.result }),
      s.value !== null && s.value !== undefined ? h("span", { class: "trace__value num", text: s.value }) : null,
      s.source ? h("p", { class: "trace__source small muted", title: sourceText(s.source, sources),
        text: `Source: ${sourceText(s.source, sources, { short: true })}` }) : null)))
      : h("p", { class: "muted", text: "No rule steps yet." }),
    d.rules ? h("p", { class: "small muted", text: d.rules.label }) : null);
  det.addEventListener("toggle", () => { if (det.open !== state.sections.trace) on.section("trace", det.open); });
  return det;
}

// ---------------------------------------------------------------- 6b more money (estimates)

function programsSection(d, entry, state, on, progMeta) {
  const p = d.programs;
  const c = d.case;
  const names = progMeta.names || {};
  const fresh = isFresh(entry) ? entry.diff : null;
  let body;
  if (p.mode === "list_only") {
    body = h("p", { class: "programs__list-only", text: listOnlyLine(p, names) || "No other programs to check." });
  } else {
    const rows = (p.lines || []).map((l) => {
      const prog = c.program_progress && c.program_progress[l.id];
      return h("tr", { class: ["prow", fresh && fresh.programs.includes(l.id) && "is-new"], dataset: { line: l.id } },
        h("th", { scope: "row", text: programName(l.id, names) }),
        h("td", {}, statusChip(l.status)),
        h("td", { class: "num prow__value", text: programPerYear(l) }),
        h("td", { class: "prow__how" }, (l.basis || []).map((b) => h("span", { class: "prow__basis", text: b }))),
        h("td", { class: "prow__src" }, (l.source_ids || []).map((sid) => h("span", { class: "prow__source",
          title: sourceText(sid, progMeta.sources), text: sourceText(sid, progMeta.sources, { short: true }) }))),
        h("td", {}, l.applied || (prog && prog.applied)
          ? h("span", { class: "prow__applied" }, icon("i-check"), appliedText(prog && prog.at)) : h("span", { class: "muted", text: "—" })));
    });
    const footer = programsFooter(p, names);
    body = h("div", { class: "table-wrap" }, h("table", { class: "table programs" },
      h("caption", { class: "sr-only", text: PROGRAMS_TITLE }),
      h("thead", {}, h("tr", {}, ["Program", "Status", "Per year", "How", "Source", "Student"].map((t) => h("th", { scope: "col", text: t })))),
      h("tbody", {}, rows),
      footer ? h("tfoot", {}, h("tr", { class: ["prow-foot", fresh && fresh.footer && "is-new"] },
        h("td", { colspan: "6", class: "num", text: footer }))) : null));
  }
  const notes = (p.console_notes || []).map((n) => h("p", { class: ["note-gray", fresh && fresh.notes.includes(n) && "is-new"] },
    icon("i-info"), h("span", { text: (progMeta.console_texts && progMeta.console_texts[n]) || n })));
  const det = h("details", { class: "section section--fold", id: "sec-programs", open: state.sections.programs },
    h("summary", { dataset: { key: "sum-programs" } }, icon("i-chevron-down", "fold-icon"), h("h2", { text: PROGRAMS_TITLE })),
    h("p", { class: "fold__lede" }, icon("i-table"), programsHeader(progMeta.checked || p.checked)),
    body, notes);
  det.addEventListener("toggle", () => { if (det.open !== state.sections.programs) on.section("programs", det.open); });
  return det;
}

function statusChip(status) {
  const text = PROGRAM_STATUS[status] || capFirst(status);
  if (status === "likely") return chip(text, { cls: "chip--likely chip--sm", iconId: "i-check-circle" });
  return chip(text, { cls: "chip--sm chip--neutral" });
}

// ---------------------------------------------------------------- tracking (A3.9)

function trackingSection(d, state, on) {
  const c = d.case;
  const t = c.tracking || {};
  const steps = [
    ["Called", c.created_at ? day(c.created_at) : null, null],
    ["Filed", t.filed_on ? day(t.filed_on) : null, null],
    ["Interview", t.interview_missed ? "missed" : (t.interview_at ? `${day(t.interview_at)}, ${time(t.interview_at)}` : null), null],
    ["Papers", t.doc_request_at ? `asked ${day(t.doc_request_at)}` : null, t.doc_due ? ["due", t.doc_due] : null],
    ["Decision due", t.deadline_30d ? day(t.deadline_30d) : null, t.deadline_30d && !t.approved_at ? ["", t.deadline_30d] : null],
    ["Approved", t.approved_at ? day(t.approved_at) : null, null],
    ["SAR 7 due", t.sar7_due ? `about ${monthDayShort(t.sar7_due)}` : null, null],
    ["Renewal due", t.recert_due ? day(t.recert_due) : null, null],
  ];
  return h("section", { class: "section", id: "sec-tracking", "aria-labelledby": "h-tracking" },
    h("h2", { id: "h-tracking", text: "Tracking" }),
    h("ol", { class: "timeline", role: "list" }, steps.map(([label, value, cd]) => {
      const chipData = cd ? countdown(cd[1]) : null;
      return h("li", { class: ["timeline__step", value && "is-done"] },
        h("span", { class: "timeline__dot", "aria-hidden": "true" }),
        h("span", { class: "timeline__label", text: label }),
        h("span", { class: "timeline__value num", text: value || "—" }),
        chipData ? h("span", { class: ["deadline", `deadline--${chipData.level}`] },
          chipData.level === "urgent" ? icon("i-hourglass") : null, chipData.text) : null);
    })),
    t.interview_missed ? h("p", { class: "tracking__missed" }, icon("i-alert-circle"), INTERVIEW_MISSED) : null,
    trackingForm(d, state, on));
}

const monthDayShort = (dateOnly) => new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
  .format(new Date(`${dateOnly}T12:00:00Z`));

function trackingForm(d, state, on) {
  const c = d.case;
  const t = c.tracking || {};
  const disabled = c.live;
  const saving = Object.keys(state.busy).some((k) => k.endsWith("/tracking"));
  const f = (id, label, type, value) => h("div", { class: "field" }, h("label", { for: id, text: label }),
    h("input", { id, name: id.replace(/^tr-/, ""), class: "input input--console num", type, value: value || "", disabled,
      autocomplete: "off", dataset: { key: id } }));
  const missed = h("input", { id: "tr-missed", name: "missed", type: "checkbox", checked: !!t.interview_missed, disabled,
    dataset: { key: "tr-missed" } });
  const form = h("form", { class: "tracking-form", novalidate: true },
    f("tr-applied", "Filed on", "date", t.applied_at),
    f("tr-interview", "Interview (Pacific time)", "datetime-local", t.interview_at ? isoToPtLocal(t.interview_at) : ""),
    h("label", { class: "field field--check", for: "tr-missed" }, missed, h("span", { text: "Interview missed" })),
    f("tr-docs", "Papers requested on", "date", t.doc_request_at),
    f("tr-approved", "Approved on", "date", t.approved_at),
    h("button", { class: "btn btn--console", type: "submit", disabled: disabled || saving, dataset: { key: "tr-save" } },
      icon("i-calendar"), "Save dates"));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (disabled || saving) return;
    const val = (id) => form.querySelector(`#${id}`).value || null;
    const interview = val("tr-interview");
    on.patchTracking({
      applied_at: val("tr-applied"), interview_at: interview ? ptLocalToIso(interview) : null,
      interview_missed: missed.checked, doc_request_at: val("tr-docs"), approved_at: val("tr-approved"),
    });
  });
  return h("details", { class: "tracking-edit", dataset: { key: "tracking-edit", keepOpen: "1" } }, h("summary", { dataset: { key: "sum-tracking" } },
    icon("i-pencil"), "Update dates"), form);
}

// ---------------------------------------------------------------- student card and danger zone

function cardSection(d) {
  const c = d.case;
  return h("section", { class: "section", id: "sec-card", "aria-labelledby": "h-card" },
    h("h2", { id: "h-card", text: "Student card" }),
    h("div", { class: "card-panel" },
      h("figure", { class: "qr-panel" },
        d.qr_svg_url ? qrImage(d.qr_svg_url, `QR code for the student card of case ${c.code}`, { lazy: true }) : null,
        h("figcaption", {}, h("span", { text: "Student card — scan with your phone camera" }),
          h("span", { class: "code", translate: "no", text: c.code }))),
      h("div", { class: "card-panel__side" },
        h("a", { class: "btn btn--console", href: d.card_url, target: "_blank", rel: "noopener", dataset: { key: "card-open" } },
          icon("i-external"), "Open card"),
        d.short_code ? h("p", {}, h("span", { class: "muted", text: "Short code " }),
          h("span", { class: "code shortcode", text: String(d.short_code).replace(/^(\d{3})(\d{3})$/, "$1 $2") })) : null)));
}

function dangerSection(d, on) {
  return h("section", { class: "section section--danger", "aria-labelledby": "h-danger" },
    h("h2", { id: "h-danger", text: "Danger zone" }),
    h("p", { class: "small muted", text: "Deleting removes the case, its answers and its student card." }),
    h("button", { class: "btn btn--console btn--danger", type: "button", dataset: { key: "delete" },
      on: { click: () => on.askDelete(d.case) } }, icon("i-trash"), "Delete case"));
}
