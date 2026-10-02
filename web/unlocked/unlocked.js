// Card unlocked part (docs/UI_SPEC.md A4.2 row 2b): renders UnlockedView as sent; computes no amount.
import { fetchJSON } from "/shared/api.js";
import { countValue, fillCount, gone, share, splitAmount, usd, widths } from "/unlocked/unlocked-lib.mjs";

let root, view, opts, N = {}, shown = null, busy = false, planOpen = false, focusTo = null, raf = 0;
const L = (k) => view?.labels[k] || "";
const ms = (k) => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(k)) || 1;

function h(sel, ...kids) {
  const [tag, ...cls] = sel.split(".");
  const el = document.createElement(tag);
  const attrs = kids[0]?.constructor === Object ? kids.shift() : {};
  if (cls.length) el.className = cls.join(" ");
  for (const [k, v] of Object.entries(attrs)) if (v != null && v !== false) el.setAttribute(k, v === true ? "" : v);
  el.append(...kids.flat(9).filter(Boolean));
  return el;
}

function icon(id, cls = "icon icon--card") {
  const t = document.createElement("template");
  t.innerHTML = `<svg class="${cls}" aria-hidden="true" focusable="false"><use href="/shared/icons.svg#${id}"/></svg>`;
  return t.content.firstChild;
}

const say = (t) => { N.live.textContent = ""; requestAnimationFrame(() => { N.live.textContent = t; }); };

function render(v) {
  view = v;
  if (!root) return;
  planOpen = root.querySelector(".unl-plan")?.open ?? planOpen;
  root.hidden = !v;
  if (!v) return root.replaceChildren(), delete root.dataset.mode;
  root.classList.add("card", "unl");
  root.setAttribute("aria-labelledby", "unl-t");
  root.lang = v.lang;
  const full = v.mode === "full";
  if (root.dataset.mode !== v.mode) {
    N = { title: h("h2", { id: "unl-t" }), body: h("div.unl-body"), foot: h("p.unl-foot"),
      total: h("p.unl-total", { tabindex: -1 }), bar: h("div.unl-bar", { "aria-hidden": "true" }),
      claimed: h("p.unl-claimed.num"), key: h("p.unl-key"), live: h("p.sr-only", { role: "status" }) };
    root.replaceChildren(N.title, ...(full ? [N.total, N.bar, N.claimed, N.key] : []), N.live, N.body, N.foot);
    root.dataset.mode = v.mode;
    shown = null;
  }
  N.title.textContent = v.title;
  N.foot.textContent = v.footnote;
  if (!full) {
    return N.body.replaceChildren(h("p", L("ui.list_only_intro")), h("ul.unl-list", { role: "list" },
      v.programs.map((p) => h("li", h("strong", p.name), h("span", p.line)))));
  }
  total(v);
  bar(v);
  N.claimed.textContent = L("ui.claimed");
  N.key.replaceChildren(icon("i-key"), h("span", L("ui.calfresh_part"), h("br"), L("ui.key_line")));
  N.body.replaceChildren(...[v.question && question(v.question),
    v.chips.length > 0 && h("ul.unl-chips", { role: "list" }, v.chips.map((c) => h("li.chip", c))),
    plans(v), v.share_text && shareBox(v.share_text)].filter(Boolean));
  if (focusTo === "q") (N.body.querySelector(".unl-q h3") || N.total).focus();
  else if (focusTo) root.querySelector(`[data-mark="${focusTo}"]`)?.focus();
  focusTo = null;
}

function total(v) {
  const parts = splitAmount(v.total_text, v.found_display);
  const amt = parts && h("span.amount.num", { "aria-hidden": "true" }, parts[1]);
  N.total.replaceChildren(...(parts ? [parts[0], amt, h("span.sr-only", parts[1]), parts[2]] : [v.total_text]));
  const from = shown, to = (shown = v.found_display), t0 = performance.now(), dur = ms("--gp-d-clear");
  if (!amt || from == null || from === to || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  cancelAnimationFrame(raf);
  const step = (now) => {
    amt.textContent = usd(countValue(from, to, (now - t0) / dur));
    if (now - t0 < dur) raf = requestAnimationFrame(step);
  };
  amt.textContent = usd(from);
  raf = requestAnimationFrame(step);
}

function bar(v) {
  const on = new Set(v.programs.filter((p) => p.applied).map((p) => p.id));
  const old = new Map([...N.bar.children].map((s) => [s.dataset.id, s]));
  const segs = widths(v.segments, v.found_display).map(([id, w]) => {
    let s = old.get(id);
    if (!s) (s = h("span.unl-seg", { "data-id": id })).style.setProperty("--w", old.size ? 0 : w);
    s.classList.toggle("is-key", id === "calfresh");
    s.classList.toggle("is-on", on.has(id));
    return [s, w];
  });
  N.bar.replaceChildren(...segs.map(([s]) => s));
  void N.bar.offsetWidth; // a new segment grows from 0
  for (const [s, w] of segs) s.style.setProperty("--w", w);
}

function question(q) {
  const retry = h("p.unl-retry", { hidden: true }, opts.t("retry"));
  const group = h("div.unl-choices", { role: "group", "aria-labelledby": "unl-q" },
    q.choices.map((c) => h("button.btn.btn--block", { "aria-pressed": "false", "data-v": c.value }, c.label)));
  group.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || busy) return;
    const wait = (on) => {
      b.setAttribute("aria-pressed", on);
      group.setAttribute("aria-disabled", on);
      retry.hidden = on;
    };
    wait(true);
    send("answers", { answers: { [q.id]: b.dataset.v } }, "q", () => wait(false));
  });
  return h("div.unl-q", h("p.unl-count", fillCount(L("ui.question_count"), q.index, q.total)),
    h("h3", { id: "unl-q", tabindex: -1 }, q.text), group, retry);
}

async function send(kind, body, focus, failed) {
  busy = true;
  try {
    const next = await fetchJSON(`/api/card/${encodeURIComponent(opts.token)}/${kind}?lang=${view.lang}`,
      { method: "POST", body, lang: view.lang });
    if (next.lang == view.lang) focusTo = focus, render(next), say(next.total_text); // else: lang switched
  } catch (e) {
    if (gone(e)) opts.onGone();
    else failed(), say(opts.t("retry"));
  }
  busy = false;
}

function plans(v) {
  const d = h("details.unl-plan", { open: planOpen },
    h("summary", h("span", L("ui.plan_title")), icon("i-chevron-down", "icon chev")));
  d.addEventListener("toggle", () => { planOpen = d.open; });
  v.programs.forEach((p, i) => {
    if (p.stage !== v.programs[i - 1]?.stage) d.append(h("h3", p.stage_label));
    d.append(program(p));
  });
  return d;
}

function program(p) {
  const muted = p.status === "zero" || p.status === "note";
  const out = !p.apply_url.startsWith("#");
  const name = "unl-n-" + p.id;
  const mark = p.can_mark_applied && h("button.btn.btn--quiet.btn--block", { "aria-pressed": "" + p.applied,
    "aria-describedby": name, "data-mark": p.id }, p.applied && icon("i-check", "icon"), L(p.applied ? "ui.undo" : "ui.mark_applied"));
  mark && mark.addEventListener("click", () => busy || send("progress", { program: p.id, applied: !p.applied }, p.id, () => {}));
  return h("article.unl-p" + (muted ? ".is-muted" : ""),
    h("h4", { id: name }, p.name, " ", h(p.status === "likely" ? "span.chip.chip--likely" : "span.chip", p.status_label)),
    p.value_text && h("p.unl-v.num", p.value_text), h("p", p.line),
    p.notes.length > 0 && h("ul", p.notes.map((n) => h("li", n))),
    p.apply_by_text && h("p.unl-by", icon("i-calendar"), p.apply_by_text),
    !muted && h("div.unl-act", h("a.btn.btn--block", { href: p.apply_url, target: out && "_blank",
      rel: out && "noopener" }, out && icon("i-external", "icon"), p.apply_label,
    out && h("span.sr-only", ` (${L("ui.new_tab")})`)), mark),
    p.prefill.length > 0 && [h("p.unl-at", L("ui.answers_title")), h("ul.unl-pf", { role: "list" },
      p.prefill.map((r) => h("li", h("span", r.screen), h("span", r.question), h("b", r.answer))))],
    h("p.unl-src", p.source_text));
}

function shareBox(text) {
  const label = h("span", L("ui.share_button"));
  const btn = h("button.btn.btn--block", icon("i-send", "icon"), label);
  const box = h("div.unl-share", btn);
  btn.addEventListener("click", async () => {
    const how = await share(text, navigator);
    if (how === "copied") {
      label.textContent = L("ui.copied");
      say(L("ui.copied"));
      setTimeout(() => { label.textContent = L("ui.share_button"); }, ms("--gp-d-toast"));
    } else if (how === "field" && !box.querySelector("input")) {
      const f = h("input.input", { readonly: true, value: text, "aria-label": L("ui.share_button") });
      box.append(f);
      f.focus();
      f.select();
    }
  });
  return box;
}

addEventListener("beforeprint", () => root?.querySelector(".unl-plan")?.setAttribute("open", ""));

window.GPUnlocked = {
  mount(el, v, o) {
    root = el;
    opts = { t: (k) => k, onGone() {}, ...o };
    render(v);
  },
  render,
};
