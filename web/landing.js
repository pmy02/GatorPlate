// Landing page (docs/UI_SPEC.md A7.2): one screen, English and Spanish. The demo phone number comes from
// GET /api/public/info and shows only when it is set. The view is a pure function (tested with node); the page part
// runs only in a browser.

import { fill } from "./shared/i18n.js";
import { telHref } from "./shared/format.js";

export const LANDING_STRINGS = {
  en: {
    title: "GatorPlate",
    headline_phone: "Check the money you may be missing — by phone or in your browser.",
    headline_web: "Check the money you may be missing — in your browser.",
    sub: "SF State students: CalFresh pays one person up to $306 a month for groceries, and it can open more help. A few minutes. Free. Estimates only — each agency decides.",
    talk: "Talk in your browser",
    call: "Call {number}",
    phone_note: "",
    about: "How it works and responsible AI",
    console: "For coordinators",
    "trust.label": "Privacy and limits",
    "trust.recorded": "Not recorded",
    "trust.ssn": "Never asks for your Social Security number or immigration status",
    "trust.estimate": "Estimates only — each agency decides",
    "more.label": "More about GatorPlate",
    prototype: "Student-built prototype — not an official SF State, county, or CalFresh service.",
    skip: "Skip to main content",
    "lang.label": "Language",
  },
  es: {
    title: "GatorPlate",
    headline_phone: "Revisa el dinero que quizá te falta reclamar, por teléfono o en tu navegador.",
    headline_web: "Revisa el dinero que quizá te falta reclamar en tu navegador.",
    sub: "Estudiantes de SF State: CalFresh da hasta $306 al mes a una persona para comida, y puede abrir más ayudas. Unos minutos. Gratis. Solo son estimados: cada agencia decide.",
    talk: "Habla en tu navegador",
    call: "Llama al {number}",
    phone_note: "La línea telefónica es solo en inglés.",
    about: "Cómo funciona y uso responsable de la IA (en inglés)",
    console: "Para la coordinación (en inglés)",
    "trust.label": "Privacidad y límites",
    "trust.recorded": "No se graba",
    "trust.ssn": "Nunca te pide tu número de Seguro Social ni tu estatus migratorio",
    "trust.estimate": "Solo son estimados: cada agencia decide",
    "more.label": "Más sobre GatorPlate",
    prototype: "Prototipo hecho por estudiantes; no es un servicio oficial de SF State, del condado ni de CalFresh.",
    skip: "Ir al contenido",
    "lang.label": "Idioma",
  },
};

export function resolveLang(search = "", navLang = "") {
  const q = new URLSearchParams(search).get("lang");
  if (q === "en" || q === "es") return q;
  return String(navLang || "").toLowerCase().startsWith("es") ? "es" : "en";
}

// The headline as display lines: the hook (up to "—" or the first comma), then the channel part, so a break never
// splits "you may be / missing". No-break spaces keep the dash on the hook's line (no line starts with "—") and the
// channel's last three words together ("by phone or / in your browser", never "… or in / your browser"). Only spaces
// change; the words are the strings above.
export function headlineParts(text) {
  const t = String(text).replace(/ —/g, "\u00a0—");
  const m = t.match(/^(.*?(?:\u00a0—|,))\s+(\S.*)$/);
  if (!m) return [t];
  const words = m[2].split(" ");
  const tail = words.length > 3 ? words.splice(-3).join("\u00a0") : null;
  return [m[1], tail ? [...words, tail].join(" ") : m[2]];
}

// Everything the page shows, from PublicInfo (or null when it could not be loaded) and the language.
export function landingView(info, lang, { fixtures = false } = {}) {
  const l = lang === "es" ? "es" : "en";
  const s = LANDING_STRINGS[l];
  const raw = info && typeof info.demo_phone_display === "string" ? info.demo_phone_display.trim() : "";
  const digits = raw.replace(/\D/g, "");
  const phone = raw
    ? { text: fill(s.call, { number: raw }), href: digits.length >= 10 ? telHref(raw) : null, note: s.phone_note }
    : null;
  return {
    lang: l,
    headline: phone ? s.headline_phone : s.headline_web,
    phone,
    talkHref: fixtures ? `/talk/?fixtures=1&lang=${l}` : `/talk?lang=${l}`,
    aboutHref: fixtures ? "/about/?fixtures=1" : "/about",
    consoleHref: fixtures ? "/console/?fixtures=1" : "/console",
    strings: s,
  };
}

// ------------------------------------------------------------------------------------------------ the page

let current = { info: null, lang: "en", fixtures: false };

function paint() {
  const v = landingView(current.info, current.lang, { fixtures: current.fixtures });
  const s = v.strings;
  const $ = (id) => document.getElementById(id);
  document.documentElement.lang = v.lang;
  document.title = s.title;
  for (const node of document.querySelectorAll("[data-t]")) {
    const text = s[node.dataset.t];
    if (typeof text === "string" && node.textContent !== text) node.textContent = text;
  }
  for (const node of document.querySelectorAll("[data-t-label]")) node.setAttribute("aria-label", s[node.dataset.tLabel]);
  for (const b of document.querySelectorAll(".langswitch__btn")) {
    b.setAttribute("aria-pressed", String(b.dataset.lang === v.lang));
  }
  const lines = headlineParts(v.headline).map((part) => {
    const span = document.createElement("span");
    span.className = "hero__line";
    span.textContent = part;
    return span;
  });
  $("headline").replaceChildren(...lines.flatMap((span, i) => (i ? [" ", span] : [span])));
  $("talk-link").setAttribute("href", v.talkHref);
  $("about-link").setAttribute("href", v.aboutHref);
  $("console-link").setAttribute("href", v.consoleHref);
  const link = $("phone-link");
  const note = $("phone-note");
  link.hidden = !v.phone;
  note.hidden = !(v.phone && v.phone.note);
  if (v.phone) {
    $("phone-text").textContent = v.phone.text;
    if (v.phone.href) link.setAttribute("href", v.phone.href);
    else link.removeAttribute("href");
    note.textContent = v.phone.note;
  }
}

// Re-render with other public info (also handy from the page console to check the number's layout).
export function show(info) {
  current = { ...current, info };
  if (typeof document !== "undefined") paint();
}

async function init() {
  const { fetchJSON, FIXTURES } = await import("./shared/api.js");
  const browserLang = (navigator.languages || [])[0] || navigator.language;
  current = { info: null, lang: resolveLang(location.search, browserLang), fixtures: FIXTURES };
  for (const b of document.querySelectorAll(".langswitch__btn")) {
    b.addEventListener("click", () => {
      current = { ...current, lang: b.dataset.lang };
      try {
        const url = new URL(location.href);
        url.searchParams.set("lang", current.lang);
        history.replaceState(history.state, "", url);
      } catch { /* the address stays as it was */ }
      paint();
    });
  }
  paint();
  try {
    current = { ...current, info: await fetchJSON("/api/public/info", { lang: current.lang }) };
  } catch {
    current = { ...current, info: null };
  }
  paint();
}

if (typeof document !== "undefined" && document.getElementById("headline")) init();
