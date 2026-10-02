// Answer rows (docs/UI_SPEC.md A3.5 item 4 and A3.8): value, state, the student's words and the source.
// Shared by the case detail (full table) and the Live view (compact rows).
import { h, icon } from "./dom.js";
import { SLOT_GROUPS, NOT_IN_ANSWERS, SOURCES, STATES, slotLabel, canonicalDisplay, fromCardLine } from "../text.js";

const FRESH_MS = 1500;

export function isFresh(entry, nowMs = Date.now()) {
  return !!(entry && entry.diff && !entry.diff.firstLoad && nowMs - (entry.at || 0) < FRESH_MS);
}

function valueCell(name, slot, specs) {
  const type = specs && specs[name] ? specs[name].type : null;
  return h("span", { class: "slot__value num" },
    h("span", { text: slot && slot.display ? slot.display : (slot && slot.value ? canonicalDisplay(slot.value, type) : "—") }),
    slot && slot.confirmed ? h("span", { class: "slot__confirmed", title: "Confirmed" },
      icon("i-check-double"), h("span", { class: "sr-only", text: "Confirmed" })) : null,
    slot && slot.changed_from !== null && slot.changed_from !== undefined
      ? h("span", { class: "slot__changed" }, "changed from ", h("del", { text: canonicalDisplay(slot.changed_from, type) })) : null);
}

function stateCell(slot) {
  const st = STATES[(slot && slot.state) || "missing"] || STATES.missing;
  if (st.icon) return h("span", { class: ["slot__state", st.cls] }, icon(st.icon, "check"), st.label);
  if (slot && slot.state === "missing") return h("span", { class: ["slot__state", st.cls], text: "—" });
  return h("span", { class: ["chip", "chip--sm", st.cls], text: st.label });
}

export function quoteCell(slot) {
  if (!slot || !slot.heard) return h("span", { class: "slot__quote muted", text: "" });
  const long = slot.heard.length > 44 || !!slot.heard_en;
  return h("span", { class: "slot__quote", tabindex: long ? "0" : null, title: slot.heard_en ? null : slot.heard },
    h("q", { class: "q", text: slot.heard }),
    slot.heard_en ? h("span", { class: "slot__gloss", text: `Translation (AI): ${slot.heard_en}` }) : null);
}

function sourceCell(slot) {
  const src = slot && slot.source ? SOURCES[slot.source] : null;
  if (!src) return h("span", { class: "slot__source" });
  if (src.tag) return h("span", { class: "slot__source" }, h("span", { class: "tag", title: src.label, text: src.tag }));
  return h("span", { class: "slot__source", title: src.label }, icon(src.icon), h("span", { class: "sr-only", text: src.label }));
}

// The full table of the case detail: grouped rows, then the read-only "From the card" line.
export function answersTable(detail, specs, entry, { questionOrder, showCard = true } = {}) {
  const c = detail.case;
  const fresh = isFresh(entry) ? new Set(entry.diff.slots) : new Set();
  const known = new Set(SLOT_GROUPS.flatMap(([, names]) => names));
  const extra = Object.keys(c.slots || {}).filter((k) => !known.has(k) && !NOT_IN_ANSWERS.has(k));
  const groups = [...SLOT_GROUPS.map(([g, names]) => [g, names.filter((n) => c.slots && c.slots[n])]),
    ["Other", extra]].filter(([, names]) => names.length);
  const merged = [];
  for (const [g, names] of groups) {
    const same = merged.find((m) => m[0] === g);
    if (same) same[1].push(...names); else merged.push([g, [...names]]);
  }
  const rows = [];
  for (const [group, names] of merged) {
    rows.push(h("tr", { class: "group-row" }, h("th", { scope: "colgroup", colspan: "5", text: group })));
    for (const name of names) {
      const slot = c.slots[name];
      rows.push(h("tr", {
        class: ["slot", fresh.has(name) && "is-new"], dataset: { slot: name },
      },
      h("th", { scope: "row", class: "slot__label", text: slotLabel(name, specs) }),
      h("td", {}, valueCell(name, slot, specs)),
      h("td", {}, stateCell(slot)),
      h("td", { class: "slot__quote-cell" }, quoteCell(slot)),
      h("td", {}, sourceCell(slot))));
    }
  }
  const card = showCard ? fromCardLine(c.program_answers, questionOrder) : null;
  if (card) {
    const freshCard = isFresh(entry) && entry.diff.answers;
    rows.push(h("tr", { class: "group-row" }, h("th", { scope: "colgroup", colspan: "5", text: "From the card" })));
    rows.push(h("tr", { class: ["slot", "slot--card", freshCard && "is-new"] },
      h("td", { colspan: "4", class: "from-card" }, h("span", { text: card.text })),
      h("td", {}, h("span", { class: "slot__source from-card__src", title: "From the student card" },
        icon("i-person"), h("span", { text: "card" })), card.sample ? h("span", { class: "tag", text: "Sample" }) : null)));
  }
  if (!rows.length) return h("p", { class: "muted", text: "No answers yet." });
  return h("div", { class: "table-wrap" }, h("table", { class: "table answers" },
    h("caption", { class: "sr-only", text: "Answers" }),
    h("thead", {}, h("tr", {},
      h("th", { scope: "col", text: "Field" }), h("th", { scope: "col", text: "Value" }),
      h("th", { scope: "col", text: "State" }), h("th", { scope: "col", text: "Student said" }),
      h("th", { scope: "col", text: "Source" }))),
    h("tbody", {}, rows)));
}

export function sourceLegend() {
  return h("p", { class: "legend" },
    h("span", {}, icon("i-quote"), "student's words"),
    h("span", {}, icon("i-keypad"), "phone keypad"),
    h("span", {}, icon("i-person-check"), "set by the coordinator"),
    h("span", {}, icon("i-table"), "rules table default"),
    h("span", {}, h("span", { class: "tag", text: "Sample" }), "sample data"),
    h("span", {}, icon("i-check-double"), "confirmed"));
}

// Live view rows: the usual call answers as pending rows ("—"), then any other answer that arrived.
export function compactAnswers(c, specs, freshSlots, core) {
  const names = [];
  for (const [, group] of SLOT_GROUPS) {
    for (const n of group) if (core.includes(n) || (c.slots && c.slots[n])) names.push(n);
  }
  return h("ul", { class: "compact", role: "list" }, names.map((name) => {
    const slot = c.slots ? c.slots[name] : null;
    const filled = slot && slot.state !== "missing";
    return h("li", {
      class: ["slot", "compact__row", !filled && "is-empty", freshSlots.has(name) && "is-new"],
      dataset: { slot: name }, tabindex: slot && slot.heard ? "0" : null,
    },
    h("span", { class: "slot__label", text: slotLabel(name, specs) }),
    filled ? valueCell(name, slot, specs) : h("span", { class: "slot__value num", text: "—" }),
    filled && slot.heard ? h("q", { class: "q compact__quote", text: slot.heard }) : h("span", { class: "compact__quote" }));
  }));
}
