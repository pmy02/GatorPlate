// /go: the 6-digit card code read at the end of a phone call (docs/UI_SPEC.md A7.1). POST /api/card/lookup, then
// open the card on this site.
import { FIXTURES, fetchJSON } from "/shared/api.js";
import { cardPath, normalizeCode } from "/go/go-lib.mjs";

const S = {
  en: {
    title: "Enter your card code · GatorPlate", lang: "Language", "go.title": "Enter your card code",
    "go.hint": "6 digits — we said it at the end of your call.", "go.submit": "Open my card",
    "go.notfound": "That code doesn't work. Codes last 24 hours — check the digits or start again.",
    "go.limited": "Too many tries. Wait a minute and try again.",
    "go.error": "We couldn't reach GatorPlate. Check your connection and try again.",
    prototype: "Student-built prototype — not an official SF State, county, or CalFresh service.",
  },
  es: {
    title: "Escribe el código de tu tarjeta · GatorPlate", lang: "Idioma",
    "go.title": "Escribe el código de tu tarjeta", "go.hint": "6 dígitos: te lo dijimos al final de la llamada.",
    "go.submit": "Abrir mi tarjeta",
    "go.notfound": "Ese código no funciona. Los códigos duran 24 horas: revisa los dígitos o empieza otra vez.",
    "go.limited": "Demasiados intentos. Espera un minuto e intenta otra vez.",
    "go.error": "No pudimos conectar con GatorPlate. Revisa tu conexión e intenta otra vez.",
    prototype: "Prototipo hecho por estudiantes; no es un servicio oficial de SF State, del condado ni de CalFresh.",
  },
};
const KEY = "gp.card.lang";
const saved = () => { try { return /^(en|es)$/.exec(localStorage.getItem(KEY))?.[0]; } catch { return null; } };
const q = new URLSearchParams(location.search).get("lang");
let lang = ["en", "es"].includes(q) ? q : saved() || ((navigator.language || "").toLowerCase().startsWith("es") ? "es" : "en");
const t = (key) => S[lang][key] ?? S.en[key];
const form = document.getElementById("go");
const input = document.getElementById("code");
const err = document.getElementById("code-err");
const errText = document.getElementById("code-err-text");
const submit = form.querySelector("button[type=submit]");
let shown = null;

function frame() {
  document.documentElement.lang = lang;
  document.title = t("title");
  for (const el of document.querySelectorAll("[data-t]")) el.textContent = t(el.dataset.t);
  for (const el of document.querySelectorAll("[data-t-label]")) el.setAttribute("aria-label", t(el.dataset.tLabel));
  for (const b of document.querySelectorAll("[data-lang]")) b.setAttribute("aria-pressed", String(b.dataset.lang === lang));
  if (shown) fail(shown);
}

function fail(key) {
  shown = key;
  errText.textContent = t(key);
  err.hidden = false;
  input.setAttribute("aria-invalid", "true");
}

for (const b of document.querySelectorAll("[data-lang]")) {
  b.addEventListener("click", () => {
    lang = b.dataset.lang;
    try { localStorage.setItem(KEY, lang); } catch { /* the page works without it */ }
    frame();
  });
}

input.addEventListener("input", () => {
  shown = null;
  err.hidden = true;
  input.removeAttribute("aria-invalid");
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (submit.getAttribute("aria-disabled") === "true") return;
  const code = normalizeCode(input.value);
  if (!code) { fail("go.notfound"); input.focus(); return; }
  submit.setAttribute("aria-disabled", "true");
  try {
    const res = await fetchJSON("/api/card/lookup", { method: "POST", body: { code } });
    const path = cardPath(res.url, FIXTURES);
    if (!path) throw Object.assign(new Error("bad url"), { status: 404 });
    location.assign(path);
  } catch (x) {
    fail(x && x.status === 429 ? "go.limited" : x && (x.status === 404 || x.status === 422) ? "go.notfound" : "go.error");
    input.focus();
  } finally {
    submit.removeAttribute("aria-disabled");
  }
});

frame();
