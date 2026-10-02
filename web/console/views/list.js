// Case list (docs/UI_SPEC.md A3.4): segments with counts, live rows pinned on top, keyboard ↑/↓ and Enter.
import { h, icon, chip, replace, rerender } from "./dom.js";
import { TIERS, STATUS_LABELS, perMonth, foundPerYear, yellowBadge, listTime, countdown, minSec } from "../text.js";
import { visibleSummaries, segmentCounts, elapsedMs } from "../store.js";

const SEGMENTS = [["review", "Needs review"], ["live", "Live"], ["all", "All"]];
const LANGS = { en: "EN", es: "ES" };

export function renderList(el, state, on) {
  rerender(el, () => {
    const counts = segmentCounts(state);
    const items = visibleSummaries(state);
    const head = h("div", { class: "list__head" },
      h("h2", { class: "list__title", id: "cases-title" }, "Cases ", h("span", { class: "list__count num", text: String(counts.all) })),
      h("div", { class: "segments", role: "group", "aria-label": "Show" },
        SEGMENTS.map(([key, label]) => h("button", {
          class: "segment", type: "button", "aria-pressed": String(state.segment === key), dataset: { key: `seg-${key}` },
          on: { click: () => on.segment(key) },
        }, label, h("span", { class: "segment__n num", text: String(counts[key]) })))));
    let body;
    if (!state.list.loaded && state.list.error && !state.offline) {
      body = h("div", { class: "list__empty" }, h("p", { class: "muted", text: "The cases couldn't be loaded." }),
        h("button", { class: "btn btn--console", type: "button", dataset: { key: "list-retry" }, on: { click: () => on.retry() } },
          "Try again"));
    } else if (!state.list.loaded) {
      body = h("ul", { class: "rows", role: "list", "aria-busy": "true", "aria-label": "Loading cases" },
        [0, 1, 2].map(() => h("li", { class: "row row--skeleton" }, h("span", { class: "skel skel--w60" }), h("span", { class: "skel skel--w90" }))));
    } else if (!items.length) {
      body = h("p", { class: "list__empty muted", text: state.segment === "all" ? "No cases yet." : "Nothing here right now." });
    } else {
      body = h("ul", { class: "rows", role: "list", "aria-labelledby": "cases-title", on: { keydown: (e) => onKeys(e, el) } },
        items.map((s, i) => h("li", {}, row(s, state, on, rovingStop(items, state, i)))));
    }
    replace(el, head, body);
  });
}

// One tab stop for the whole list (the open row, else the first); ↑/↓ move between rows.
function rovingStop(items, state, i) {
  const open = items.findIndex((s) => s.id === state.selectedId);
  return i === (open >= 0 ? open : 0);
}

function row(s, state, on, stop) {
  const tier = s.tier ? TIERS[s.tier] : null;
  const open = state.selectedId === s.id;
  const est = s.estimate_monthly !== null && s.estimate_monthly !== undefined
    ? (s.estimate_is_floor ? `at least ${perMonth(s.estimate_monthly)}` : perMonth(s.estimate_monthly)) : "—";
  const deadline = s.next_deadline ? countdown(s.next_deadline) : null;
  return h("button", {
    type: "button", class: ["row", s.live && "row--live", open && "is-open"], dataset: { key: `row-${s.id}`, id: s.id },
    tabindex: stop ? "0" : "-1",
    "aria-current": open ? "true" : null, on: { click: () => on.open(s.id) },
  },
  h("span", { class: "row__line1" },
    s.live ? h("span", { class: "live-dot", "aria-hidden": "true" }) : null,
    s.live ? h("span", { class: "row__live", text: "LIVE" }) : null,
    h("span", { class: "num", text: listTime(s) }),
    s.live ? h("span", { class: "num row__elapsed", dataset: { elapsed: s.id }, text: minSec(elapsedMs(state, s.id, Date.now())) }) : null,
    icon(s.channel === "web" ? "i-globe" : "i-phone"),
    h("span", { class: "sr-only", text: s.channel === "web" ? "Web" : "Phone" }),
    h("span", { class: "lang-tag", text: LANGS[s.lang] || s.lang }),
    h("span", { class: "code", translate: "no", text: s.code })),
  h("span", { class: "row__line2" },
    tier ? chip(tier.label, { cls: `chip--sm ${tier.cls}`, iconId: tier.icon }) : null,
    h("span", { class: "row__est num", text: est })),
  h("span", { class: "row__flags" },
    s.yellow_open > 0
      ? h("span", { class: "badge-yl" }, icon("i-alert-circle"), yellowBadge(s.yellow_open))
      : h("span", { class: "row__ok", title: "Nothing to check" }, icon("i-check"), h("span", { class: "sr-only", text: "Nothing to check" }))),
  h("span", { class: "row__summary", text: s.summary || "" }),
  s.found_display !== null && s.found_display !== undefined
    ? h("span", { class: "row__found num", text: foundPerYear(s.found_display) }) : null,
  h("span", { class: "row__meta" },
    h("span", { text: STATUS_LABELS[s.status] || s.status }),
    s.seeded ? h("span", { class: "tag", text: "Sample" }) : null,
    s.ended_early ? h("span", { class: "tag", text: "Ended early" }) : null,
    deadline ? h("span", { class: ["deadline", `deadline--${deadline.level}`] },
      deadline.level === "urgent" ? icon("i-hourglass") : null, deadline.text) : null));
}

function onKeys(e, root) {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const rows = [...root.querySelectorAll("button.row")];
  const i = rows.indexOf(document.activeElement);
  if (i < 0) return;
  e.preventDefault();
  const next = rows[Math.max(0, Math.min(rows.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
  next.focus();
}

// Called every second: live rows' elapsed time, without a re-render.
export function tickList(el, state) {
  for (const span of el.querySelectorAll("[data-elapsed]")) {
    span.textContent = minSec(elapsedMs(state, span.dataset.elapsed, Date.now()));
  }
}

