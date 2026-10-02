// Console shell (docs/UI_SPEC.md A3.3, A3.12, A2.5, A2.7): top bar with the rules, connection, sample-data,
// presenter and demo controls; banners; dialogs (demo menu, shortcuts, rules drawer, delete, QR); toasts; login.
import { h, icon, replace, rerender } from "./dom.js";
import { talkQr, qrImage } from "./detail.js";
import { rulesPill, longDate, OFFLINE, RULES_INVALID, programsHeader } from "../text.js";

const CONN = { live: "Live", polling: "Polling", replay: "Replay", connecting: "Connecting" };

export function renderTopbar(el, state, on) {
  rerender(el, () => {
    const meta = state.meta;
    const demo = !!(meta && meta.demo_mode);
    replace(el,
      h("div", { class: "topbar__brand" },
        icon("gp-logo", "logo topbar__logo"),
        h("span", { class: "wordmark", translate: "no" }, "refri", h("b", { text: "Gator" })),
        h("span", { class: "topbar__role", text: "Coordinator" }),
        h("span", { class: "topbar__proto", text: "Prototype coordinator view" })),
      h("div", { class: "topbar__tools" },
        meta ? h("button", { class: "pill pill--rules", type: "button", dataset: { key: "rules-pill" },
          "aria-haspopup": "dialog", on: { click: () => on.rules() } }, icon("i-table"), rulesPill(meta.rules)) : null,
        h("span", { class: ["pill", `pill--conn-${state.conn}`], title: "Connection" },
          state.conn === "live" ? h("span", { class: "live-dot", "aria-hidden": "true" }) : null,
          h("span", { class: "sr-only", text: "Connection: " }), CONN[state.conn] || state.conn),
        demo ? h("span", { class: "pill pill--sample", text: "Sample data" }) : null,
        h("button", { class: "btn btn--console btn--bar", type: "button", "aria-pressed": String(state.view === "live"),
          dataset: { key: "tb-live" }, title: "Live view (L)", on: { click: () => on.toggleLive() } }, icon("i-live"), h("span", { class: "btn__text", text: "Live view" })),
        h("button", { class: "btn btn--console btn--bar", type: "button", "aria-pressed": String(state.presenter),
          dataset: { key: "tb-presenter" }, title: "Presenter (P)", on: { click: () => on.presenter() } }, icon("i-monitor"), h("span", { class: "btn__text", text: "Presenter" })),
        demo ? h("button", { class: "btn btn--console btn--bar", type: "button", "aria-haspopup": "dialog",
          dataset: { key: "tb-demo" }, title: "Demo menu (Shift+D)", on: { click: () => on.demoMenu() } }, icon("i-play"), "Demo") : null,
        h("button", { class: "btn btn--console btn--icon btn--bar", type: "button", "aria-haspopup": "dialog",
          "aria-label": "Keyboard shortcuts", title: "Keyboard shortcuts (?)", dataset: { key: "tb-help" },
          on: { click: () => on.shortcuts() } }, icon("i-help")),
        h("button", { class: "btn btn--console btn--icon btn--bar", type: "button", "aria-label": "Log out", title: "Log out",
          dataset: { key: "tb-logout" }, on: { click: () => on.logout() } }, icon("i-log-out"))));
  });
}

export function renderBanners(el, state) {
  const out = [];
  if (state.offline) {
    const last = state.lastUpdate ? new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit",
      timeZone: "America/Los_Angeles" }).format(new Date(state.lastUpdate)) : null;
    out.push(h("div", { class: "banner banner--error", role: "alert" }, icon("i-alert-triangle"), h("span", { text: OFFLINE(last) })));
  }
  if (state.meta && state.meta.rules_valid_today === false) {
    out.push(h("div", { class: "banner banner--error", role: "alert" }, icon("i-alert-triangle"), h("span", { text: RULES_INVALID })));
  }
  const key = out.map((n) => n.textContent).join("|");
  if (el.dataset.k === key) return;
  el.dataset.k = key;
  replace(el, out);
}

// ---------------------------------------------------------------- dialogs (focus trapped by <dialog>; Esc closes)

export function openDialog(dialog, title, body, { wide = false, side = false, onClose } = {}) {
  const opener = document.activeElement;
  replace(dialog, h("div", { class: "dialog__head" },
    h("h2", { id: "dialog-title", text: title }),
    h("button", { class: "btn btn--console btn--icon btn--quiet", type: "button", "aria-label": "Close", title: "Close",
      on: { click: () => dialog.close() } }, icon("i-close"))), body);
  dialog.className = ["dialog", wide && "dialog--wide", side && "dialog--side"].filter(Boolean).join(" ");
  const done = () => {
    dialog.removeEventListener("close", done);
    if (onClose) onClose();
    if (opener && opener.isConnected) opener.focus();
  };
  dialog.addEventListener("close", done);
  if (!dialog.open) dialog.showModal();
  const first = dialog.querySelector("[autofocus]") || dialog.querySelector(".dialog__body button, .dialog__body a, .dialog__body input");
  if (first) first.focus();
}

export function demoMenuBody(state, on) {
  const follow = h("input", { type: "checkbox", id: "dm-follow", checked: state.followLive });
  follow.addEventListener("change", () => on.followLive(follow.checked));
  const sel = state.selectedId;
  const detail = sel && state.details[sel] && state.details[sel].data;
  const result = h("p", { class: "demo__result small", role: "status", text: state.demoResult || "" });
  // One run at a time: a second click while Reset demo is running would reset and seed twice.
  const action = (label, iconId, fn, disabled = false, hint = null) => h("li", {},
    h("button", { class: "btn btn--console btn--block demo__btn", type: "button", disabled,
      on: { click: async (e) => {
        const btn = e.currentTarget;
        if (btn.getAttribute("aria-busy") === "true") return;
        btn.setAttribute("aria-busy", "true");
        try { const r = await fn(); if (r && r.text) result.textContent = r.text; } finally { btn.removeAttribute("aria-busy"); }
      } } },
    icon(iconId), h("span", { text: label }), hint ? h("span", { class: "muted small demo__hint", text: hint }) : null));
  return h("div", { class: "dialog__body demo" },
    h("ul", { class: "demo__list", role: "list" },
      action("Reset demo", "i-reset", on.reset, false, "removes calls, restores samples"),
      action("Seed samples", "i-person-check", on.seed),
      action("Replay case", "i-play", on.replay, !detail || !(detail.case.timeline || []).length, "R"),
      action("Show card QR", "i-qr", on.cardQr, !detail || !detail.card_url)),
    h("div", { class: "field field--check" }, follow, h("label", { for: "dm-follow", text: "Follow live calls" })),
    result);
}

export function shortcutsBody(state, on) {
  const sw = h("input", { type: "checkbox", id: "sc-on", checked: state.shortcutsOn, role: "switch" });
  sw.addEventListener("change", () => on.shortcutsOn(sw.checked));
  const rows = [["L", "Live view"], ["P", "Presenter"], ["R", "Replay the selected case at 2×"],
    ["Shift + T", "Open the talk page in a new tab"], ["Shift + D", "Demo menu"], ["Esc", "Back to the work view or close"],
    ["?", "This list"], ["Up / Down", "Move in the case list"], ["Enter", "Open the case"]];
  return h("div", { class: "dialog__body" },
    h("div", { class: "field field--check" }, sw, h("label", { for: "sc-on", text: "Keyboard shortcuts" })),
    h("p", { class: "small muted", text: "Single-key shortcuts never fire while you type in a field." }),
    h("dl", { class: "keys" }, rows.flatMap(([k, v]) => [h("dt", {}, h("kbd", { text: k })), h("dd", { text: v })])));
}

export function rulesBody(meta) {
  const r = meta && meta.rules;
  const p = meta && meta.programs;
  const list = (sources) => h("ul", { class: "sources", role: "list" }, (sources || []).map((s) => h("li", {},
    h("span", { class: "sources__title", text: s.title }), h("span", { class: "sources__date small muted num", text: s.date }))));
  return h("div", { class: "dialog__body rules" },
    r ? [h("p", { class: "rules__label", text: r.label }),
      h("p", { class: "small muted", text: `In effect ${longDate(r.effective_from)} to ${longDate(r.effective_to)} · ${r.table_id}` }),
      h("h3", { class: "label", text: "Sources" }), list(r.sources)] : null,
    p ? [h("h3", { class: "rules__sub", text: p.label }), h("p", { class: "small muted", text: programsHeader(p.checked) }),
      h("p", { class: "small muted", text: `In effect ${longDate(p.effective_from)} to ${longDate(p.effective_to)} · ${p.table_id}` }),
      list(p.sources)] : null);
}

export function deleteBody(c, on) {
  return h("div", { class: "dialog__body" },
    h("p", {}, "Delete case ", h("span", { class: "code", text: c.code }), "? This removes the case, its answers and its student card. It can't be undone."),
    h("div", { class: "dialog__actions" },
      h("button", { class: "btn btn--console", type: "button", autofocus: true, on: { click: () => on.cancel() } }, "Cancel"),
      h("button", { class: "btn btn--console btn--danger", type: "button", on: { click: () => on.confirm() } }, icon("i-trash"), "Delete case")));
}

export function qrBody(detail) {
  const c = detail.case;
  return h("div", { class: "dialog__body qr-dialog" }, h("figure", { class: "qr-panel" },
    detail.qr_svg_url ? qrImage(detail.qr_svg_url, `QR code for the student card of case ${c.code}`) : null,
    h("figcaption", {}, h("span", { text: "Student card — scan with your phone camera" }), h("span", { class: "code", text: c.code }))));
}

export function talkQrBody(lang) {
  return h("div", { class: "dialog__body qr-dialog" }, talkQr(lang));
}

// ---------------------------------------------------------------- toasts (bottom-left, 4 s, role=status)

export function renderToasts(el, state) {
  const key = state.toasts.map((t) => t.id).join(",");
  if (el.dataset.k === key) return;
  el.dataset.k = key;
  replace(el, state.toasts.map((t) => h("p", { class: ["toast", t.kind === "error" && "toast--error"] },
    icon(t.kind === "error" ? "i-alert-triangle" : "i-check"), h("span", { text: t.text }))));
}

// ---------------------------------------------------------------- login (A3.1)

export function renderLogin(el, state, on) {
  if (el.dataset.built === "1") {
    const err = el.querySelector(".field__error");
    err.hidden = !state.loginError;
    replace(err, state.loginError ? [icon("i-alert-circle"), h("span", { text: state.loginError })] : []);
    if (state.loginError) el.querySelector("input").focus();
    return;
  }
  el.dataset.built = "1";
  const input = h("input", { id: "passcode", name: "passcode", class: "input", type: "password", autocomplete: "current-password", required: true,
    "aria-describedby": "login-err" });
  const err = h("p", { class: "field__error", id: "login-err", role: "alert", hidden: true });
  const btn = h("button", { class: "btn btn--primary btn--block", type: "submit" }, "Log in");
  const form = h("form", { class: "login__card" },
    h("div", { class: "login__brand" }, icon("gp-logo", "logo login__logo"), h("span", { class: "wordmark", translate: "no" }, "refri", h("b", { text: "Gator" }))),
    h("h1", { text: "Coordinator" }),
    h("p", { class: "muted", text: "Prototype coordinator view. Enter the shared passcode." }),
    h("div", { class: "field" }, h("label", { for: "passcode", text: "Passcode" }), input, err), btn);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!input.value) { input.focus(); return; }
    btn.disabled = true;
    await on.login(input.value);
    btn.disabled = false;
    input.value = "";
  });
  replace(el, form);
  input.focus();
}
