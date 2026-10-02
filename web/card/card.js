// Student card (docs/UI_SPEC.md A4): only the A4.7 strings live here.
import { fetchJSON } from "/shared/api.js";
import { changed, pacificDay, pacificTime, segments, sourceDate, splitAmount, tokenFrom } from "/card/card-lib.mjs";

const S = {
  en: {
    title: "GatorPlate card", skip: "Skip to your card", lang: "Language",
    "status.reviewed": "Checked by a coordinator · {time}",
    "tier.likely": "Good chance", "tier.coordinator": "A person will check", "tier.other_help": "Other help",
    "btn.benefitscal": "Open BenefitsCal", "btn.calendar": "Add 3 dates to my calendar",
    "btn.call_clinic": "Call the clinic", "btn.email_clinic": "Email the clinic",
    "btn.county": "Call the county (855) 355-5757", "btn.print": "Print or save PDF", "btn.delete": "Delete my info",
    "delete.title": "Delete your information?",
    "delete.body": "This deletes your answers and this card for good. The coordinator won't see them anymore.",
    "delete.yes": "Delete", "delete.no": "Keep it",
    "delete.failed": "We couldn't delete it. Check your connection and try again.",
    deleted: "Your information was deleted.",
    badlink: "This card link doesn't work. It may have expired or been deleted.", "badlink.talk": "Talk to GatorPlate",
    loading: "Loading your card…", error: "We couldn't load your card. Check your connection and try again.",
    retry: "Try again", code: "Your case code: {code}", "print.header": "GatorPlate card · {code} · printed {date}",
    prototype: "Student-built prototype — not an official SF State, county, or CalFresh service.",
    sources: "Sources", "source.current": "current", "source.saved": "page saved {date}",
    newtab: "(opens a new tab)", "col.screen": "Screen", "col.question": "Question", "col.answer": "Your answer",
  },
  es: {
    title: "Tarjeta de GatorPlate", skip: "Saltar a tu tarjeta", lang: "Idioma",
    "status.reviewed": "Revisado por la coordinación de CalFresh · {time}",
    "tier.likely": "Buenas posibilidades", "tier.coordinator": "Lo revisará una persona", "tier.other_help": "Otra ayuda",
    "btn.benefitscal": "Abrir BenefitsCal", "btn.calendar": "Agregar 3 fechas a mi calendario",
    "btn.call_clinic": "Llamar a la clínica", "btn.email_clinic": "Escribir a la clínica",
    "btn.county": "Llamar al condado (855) 355-5757", "btn.print": "Imprimir o guardar PDF",
    "btn.delete": "Borrar mi información",
    "delete.title": "¿Borrar tu información?",
    "delete.body": "Esto borra tus respuestas y esta tarjeta para siempre. La coordinación ya no podrá verlas.",
    "delete.yes": "Borrar", "delete.no": "No borrar",
    "delete.failed": "No pudimos borrar tu información. Revisa tu conexión e intenta otra vez.",
    deleted: "Tu información fue borrada.",
    badlink: "Este enlace no funciona. Puede que haya vencido o que se haya borrado.",
    "badlink.talk": "Hablar con GatorPlate",
    loading: "Cargando tu tarjeta…", error: "No pudimos cargar tu tarjeta. Revisa tu conexión e intenta otra vez.",
    retry: "Intentar otra vez", code: "Tu código: {code}",
    "print.header": "Tarjeta de GatorPlate · {code} · impresa el {date}",
    prototype: "Prototipo hecho por estudiantes; no es un servicio oficial de SF State, del condado ni de CalFresh.",
    sources: "Fuentes", "source.current": "vigente", "source.saved": "página guardada el {date}",
    newtab: "(se abre en una pestaña nueva)", "col.screen": "Pantalla", "col.question": "Pregunta",
    "col.answer": "Tu respuesta",
  },
};
const ICON = { today_action: "i-calendar", expedited: "i-clock", why: "i-info", answer_sheet: "i-table",
  documents: "i-file", interview: "i-phone", after_approval: "i-check", food_today: "i-utensils", contact: "i-person" };
const TIER = { likely: ["i-check-circle", "likely"], coordinator: ["i-person", "coordinator"],
  other_help: ["i-heart-hand", "other"] };
const KEY = "gp.card.lang";
const COLS = ["screen", "question", "answer"];
const $ = (id) => document.getElementById(id);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const saved = () => { try { return /^(en|es)$/.exec(localStorage.getItem(KEY))?.[0]; } catch { return null; } };
const token = tokenFrom(location.pathname, location.search);
const ql = new URLSearchParams(location.search).get("lang");
const asked = /^(en|es)$/.test(ql) ? ql : saved();
let lang = asked || (/^es/i.test(navigator.language || "") ? "es" : "en");
let view = null, reviewedAt = null, timer = null, mounted = false, mode = "loading";
const api = (path = "") => `/api/card/${token}${path}`;
const gone = (e) => e?.status === 404 || e?.status === 410;
const t = (key, vars = {}) => (S[lang][key] ?? S.en[key] ?? key).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null && v !== false) el.setAttribute(k, v === true ? "" : v);
  el.append(...kids.flat(3).filter((k) => k != null && k !== false));
  return el;
}

function icon(id, cls = "icon icon--card") {
  const box = document.createElement("i");
  box.innerHTML = `<svg class="${cls}" aria-hidden="true" focusable="false"><use href="/shared/icons.svg#${id}"></use></svg>`;
  return box.firstChild;
}

const newTab = () => h("span", { class: "sr-only" }, ` ${t("newtab")}`);
const ext = (href, text, cls) => h("a", { href, target: "_blank", rel: "noopener", class: cls }, text, newTab());
const rich = (text) => segments(text).map((s) => (typeof s === "string" ? s
  : s.external ? ext(s.href, s.text, "u") : h("a", { href: s.href }, s.text)));
const btn = (label, id, cls = "btn", attrs = {}) => h("href" in attrs ? "a" : "button",
  { class: cls, type: "href" in attrs ? null : "button", ...attrs }, icon(id), h("span", null, label),
  attrs.target ? newTab() : null);

function frame() {
  document.documentElement.lang = lang;
  document.title = t("title");
  for (const el of $$("[data-t]")) el.textContent = t(el.dataset.t);
  for (const el of $$("[data-t-label]")) el.setAttribute("aria-label", t(el.dataset.tLabel));
  for (const b of $$("[data-lang]")) b.setAttribute("aria-pressed", String(b.dataset.lang === lang));
}

function state(kind) {
  mode = kind;
  $("card").hidden = kind !== "card";
  $("state").hidden = kind === "card";
  banner();
  if (kind === "card") return;
  if (kind !== "loading") stopPoll();
  $("state-msg").textContent = t(kind);
  $("state-actions").replaceChildren(...(kind === "error" ? [btn(t("retry"), "i-reset", "btn btn--primary retry")]
    : kind === "loading" ? [] : [btn(t("badlink.talk"), "i-arrow-right", "btn", { href: `/talk?lang=${lang}` })]));
}

async function load(want, swap = false) {
  $("main").classList.toggle("swap", swap);
  try {
    view = await fetchJSON(api(want ? `?lang=${want}` : ""), { lang: want || lang });
    lang = view.lang;
    render();
  } catch (e) {
    if (gone(e)) state("badlink");
    else if (!view) state("error");
    else { lang = view.lang; frame(); }
  }
  $("main").classList.remove("swap");
}

function render() {
  frame();
  const open = new Map($$("#blocks details").map((d) => [d.parentElement.id, d.open]));
  const tier = TIER[view.tier];
  const parts = splitAmount(view.headline, view.estimate_monthly);
  $("hero").replaceChildren(
    tier && !/^info\./.test(view.reason_code) ? h("p", { class: `chip chip--${tier[1]}` }, icon(tier[0], "icon"),
      t(`tier.${view.tier}`)) : null,
    h("h1", { id: "hero-title" }, parts ? [parts[0], h("span", { class: "amount" }, parts[1]), parts[2]] : view.headline),
    h("p", { class: "sub" }, view.subhead));
  $("blocks").replaceChildren(...view.blocks.map((b) => block(b, open)));
  foot();
  if (!mounted) reviewedAt = view.status.reviewed ? view.status.reviewed_at : null;
  printHead();
  state("card");
  try {
    if (mounted) window.GPUnlocked.render(view.unlocked);
    else {
      mounted = true;
      window.GPUnlocked.mount($("unlocked"), view.unlocked, { token, lang: view.lang, t, onGone: () => state("badlink") });
    }
  } catch {
    $("unlocked").hidden = true;
  }
  timer ??= setInterval(check, 4000);
}

function block(b, open) {
  const title = h("h2", { id: `${b.id}-t` }, icon(ICON[b.id] || "i-info"), h("span", null, b.title));
  const body = [b.paragraphs.map((p) => h("p", null, rich(p))), b.rows.length ? sheet(b.rows) : null, extras(b.id)];
  const sec = h("section", { id: b.id, class: `card blk card--${b.tone}`, "aria-labelledby": `${b.id}-t` });
  if (!b.collapsed) sec.append(title, ...body.flat().filter(Boolean));
  else sec.append(h("details", { open: open.get(b.id) || false },
    h("summary", null, title, icon("i-chevron-down", "icon chev")), h("div", { class: "inner" }, body)));
  return sec;
}

const sheet = (rows) => h("table", { class: "sheet" },
  h("thead", null, h("tr", null, COLS.map((c) => h("th", { scope: "col" }, t(`col.${c}`))))),
  h("tbody", null, rows.map((r, i) => h("tr", { class: r.screen === rows[i - 1]?.screen ? "rep" : null },
    COLS.map((c) => h("td", null, rich(r[c])))))));

function extras(id) {
  const a = {
    today_action: [btn(t("btn.benefitscal"), "i-external", "btn btn--primary",
      { href: "https://benefitscal.com/", target: "_blank", rel: "noopener" })],
    interview: [view.reminders_url ? btn(t("btn.calendar"), "i-calendar-add", "btn",
      { href: view.reminders_url, download: "gatorplate-dates.ics" }) : null,
    btn(t("btn.county"), "i-phone", "btn", { href: "tel:+18553555757" })],
    contact: [btn(t("btn.call_clinic"), "i-phone", "btn", { href: "tel:+14153381203" }),
      btn(t("btn.email_clinic"), "i-mail", "btn", { href: "mailto:calfresh@sfsu.edu" })],
  }[id];
  return a ? h("div", { class: "actions" }, a) : null;
}

function foot() {
  $("foot").replaceChildren(...view.footer.map((line) => h("p", null, line)),
    h("details", { class: "sources" },
      h("summary", null, h("span", null, t("sources")), icon("i-chevron-down", "icon chev")),
      h("p", null, view.rules_label), h("ul", { role: "list" }, view.sources.map((s) => h("li", null, s.url ? ext(s.url, s.title) : s.title,
        `, ${sourceDate(s.date, lang, t)}`)))),
    h("p", { class: "code-line" }, t("code", { code: "" }), h("span", { class: "code", translate: "no" }, view.code)),
    h("div", { class: "actions" }, btn(t("btn.print"), "i-printer", "btn print-btn"),
      btn(t("btn.delete"), "i-trash", "btn btn--danger del-btn")));
}

function banner() {
  const el = $("banner");
  el.hidden = !(mode === "card" && reviewedAt);
  const text = el.hidden ? "" : t("status.reviewed", { time: pacificTime(reviewedAt, lang) });
  if (text && el.textContent !== text) el.replaceChildren(h("div", { class: "wrap rev" }, icon("i-check-circle"), text));
}

const printHead = () => { $("print-head").textContent = t("print.header", { code: view.code, date: pacificDay(new Date(), lang) }); };

const stopPoll = () => { clearInterval(timer); timer = null; };

async function check() {
  if (document.visibilityState !== "visible" || mode !== "card") return;
  try {
    const st = await fetchJSON(api("/status"));
    reviewedAt = st.reviewed ? st.reviewed_at : null;
    banner();
    if (changed(view, st)) await load(lang);
  } catch (e) {
    if (gone(e)) state("badlink");
  }
}

for (const b of $$("[data-lang]")) {
  b.addEventListener("click", async () => {
    try { localStorage.setItem(KEY, b.dataset.lang); } catch { /* the page works without it */ }
    if (b.dataset.lang === lang && view) return;
    lang = b.dataset.lang;
    frame();
    if (!view) return mode === "loading" || state(mode);
    const y = window.scrollY;
    await load(lang, true);
    window.scrollTo(0, y);
  });
}

const dlg = $("del");
document.addEventListener("click", (e) => {
  const el = e.target.closest("button");
  if (el?.classList.contains("print-btn")) window.print();
  if (el?.classList.contains("retry")) { state("loading"); load(asked ? lang : null); }
  if (el?.classList.contains("del-btn")) {
    $("del-err").hidden = true;
    dlg.showModal();
    $("del-no").focus();
  }
});
$("del-no").addEventListener("click", () => dlg.close());
dlg.addEventListener("close", () => mode === "card" && document.querySelector(".del-btn").focus());
$("del-yes").addEventListener("click", async () => {
  try {
    await fetchJSON(view.delete_url, { method: "DELETE" });
  } catch (e) {
    if (!gone(e)) {
      $("del-err-t").textContent = t("delete.failed");
      return void ($("del-err").hidden = false);
    }
  }
  view = null;
  state("deleted");
  dlg.close();
  $("state-msg").focus();
});

const opened = [];
window.addEventListener("beforeprint", () => {
  if (view) printHead();
  for (const d of $$("details:not([open])")) opened.push(Object.assign(d, { open: true }));
});
window.addEventListener("afterprint", () => { while (opened.length) opened.pop().open = false; });
document.addEventListener("visibilitychange", check);

frame();
if (token) { state("loading"); load(asked ? lang : null); } else state("badlink");
