// Landing page (docs/UI_SPEC.md A7.2): the first screen, then five pitch sections to scroll (the gap at SF State, how
// it works, responsible by design, six programs, try it), English and Spanish. The demo phone number comes from
// GET /api/public/info and shows only when it is set; then the call button comes first and is the filled one. The view
// is a pure function (tested with node); the page part runs only in a browser.

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
    "trust.recorded": "Audio isn't recorded",
    "trust.ssn": "Never asks for your Social Security number or immigration status",
    "trust.estimate": "Estimates only — each agency decides",
    "more.label": "More about GatorPlate",
    prototype: "Student-built prototype — not an official SF State, county, or CalFresh service.",
    skip: "Skip to main content",
    "lang.label": "Language",
    // The pitch sections under the first screen (A7.2): the gap, how it works, responsibility, six programs, try it.
    "gap.kicker": "The gap at SF State",
    "gap.title": "About 3,300 SF State undergraduates likely qualify for CalFresh and aren't getting it.",
    "gap.about": "about",
    "gap.students": "students",
    "gap.upto": "up to",
    "gap.year": "a year",
    "gap.money": "Up to $12 million a year in food money — CalFresh alone, at the one-person maximum.",
    "gap.eligible": "≈5,810 likely eligible",
    "gap.receiving": "≈2,520 already receive it",
    "gap.missing": "≈3,290 not yet",
    "gap.method": "Estimate based on UC eligibility research applied to SF State enrollment: 33% of UC undergraduates were eligible for CalFresh (California Policy Lab, Fall 2019 data, published Aug 2024), applied to SF State's 17,607 undergraduates (Fall 2025), minus the 14.3% of SF State undergraduates who already received CalFresh in 2023–24 (California Policy Lab, Aug 2026). \"Up to\" assumes the $306 one-person maximum for 12 months; the average benefit is lower.",
    "gap.sources": "Sources",
    "gap.src1": "Enrollment: 17,607 undergraduates, Fall 2025 (SF State Facts).",
    "gap.src2": "Eligible: 33% of UC undergraduates, Fall 2019 (California Policy Lab, \"Filling the Gap,\" Aug 2024) → ≈5,810 at SF State.",
    "gap.src3": "Already receiving: 14.3% of SF State undergraduates, 2023–24 (California Policy Lab, Aug 2026) → ≈2,520.",
    "gap.src4": "Up to $306/month: CalFresh maximum for one person from Oct 1, 2026 (CDSS ACIN I-40-26).",
    "gap.src5": "Average is lower: participating UC undergraduates averaged $161/month when the maximum was $194 (California Policy Lab, Feb 2025) — about $10M/yr at that ratio.",
    "gap.src6": "Graduate students not counted: 13.6% of SF State grad students already receive CalFresh, above UC's 7% grad eligibility rate.",
    "gap.src7": "Likely conservative: since June 1, 2026, half-time CSU bachelor's students meet the student rule (CDSS ACL 26-25); the 2019 rate predates this.",
    "how.kicker": "How it works",
    "how.title": "The AI listens. A rules table decides. A person confirms.",
    "how.1.h": "The AI listens",
    "how.1.p": "A language model turns what the student says into answers, such as units, rent and income. It never writes a sentence and never sets a number.",
    "how.2.h": "A rules table decides",
    "how.2.p": "A dated rules table computes the estimate, and every sentence comes from a sentence bank written in advance.",
    "how.3.h": "A person confirms",
    "how.3.p": "A campus CalFresh coordinator confirms or edits anything uncertain before a case can be marked reviewed. The county makes every eligibility decision.",
    "care.kicker": "Responsible by design",
    "care.title": "It asks before it starts, keeps little, and decides nothing.",
    "care.consent.h": "Consent before questions",
    "care.consent.p": "Every call and chat opens by saying it's a student-built AI, then asks if it's okay to start.",
    "care.audio.h": "Call audio isn't recorded",
    "care.audio.p": "GatorPlate keeps the student's answers and short quotes of their words, not the conversation.",
    "care.ssn.h": "Never asks for a Social Security number or immigration status",
    "care.ssn.p": "Digits that look like a Social Security or card number are removed before anything else sees the text.",
    "care.est.p": "A coordinator checks every uncertain answer before a case is marked reviewed.",
    "care.yl.tag": "To check",
    "care.yl.text": "Monthly rent — \"around 800, I think\"",
    "prog.kicker": "Six programs",
    "prog.sofar": "The numbers above count CalFresh alone.",
    "prog.title": "CalFresh is the key.",
    "prog.sub": "It can open more help this year: Medi-Cal, Clipper START, PG&E CARE, California LifeLine and tax credits.",
    "prog.tax": "Tax credits",
    "prog.check": "We check six programs. For Maria, four save money, one is health coverage, and one is a maybe at tax time.",
    "prog.who": "Maria, a sample student from our demo",
    "prog.alone": "CalFresh alone",
    "prog.upto": "up to about",
    "prog.transit": "Clipper START — transit",
    "prog.phone": "California LifeLine — phone",
    "prog.phone.amt": "up to $220",
    "prog.energy": "PG&E CARE — energy",
    "prog.total": "Total a year, up to about",
    "prog.coverage": "+ health coverage",
    "prog.maybe": "maybe $200 — not counted",
    "prog.note": "Estimates from dated tables, computed by code, not by the AI. Each agency decides.",
    "try.kicker": "Try it",
    "try.title": "Check the money you may be missing.",
    "try.sub_phone": "A few minutes. Free. Call in English, or talk in your browser in English or Spanish.",
    "try.sub_web": "A few minutes. Free. Talk in your browser in English or Spanish.",
  },
  es: {
    title: "GatorPlate",
    headline_phone: "¡Revisa el dinero que quizá te falta reclamar, por teléfono o en tu navegador!",
    headline_web: "Revisa el dinero que quizá te falta reclamar en tu navegador.",
    sub: "Estudiantes de SF State: CalFresh da hasta $306 al mes a una persona para comida, y puede abrir más ayudas. Unos minutos. Gratis. Solo son estimados: cada agencia decide.",
    talk: "Habla en tu navegador",
    call: "Llama al {number}",
    phone_note: "La línea telefónica es solo en inglés.",
    about: "Cómo funciona y uso responsable de la IA (en inglés)",
    console: "Para la coordinación (en inglés)",
    "trust.label": "Privacidad y límites",
    "trust.recorded": "No se graba el audio",
    "trust.ssn": "Nunca te pide tu número de Seguro Social ni tu estatus migratorio",
    "trust.estimate": "Solo son estimados: cada agencia decide",
    "more.label": "Más sobre GatorPlate",
    prototype: "Prototipo hecho por estudiantes; no es un servicio oficial de SF State, del condado ni de CalFresh.",
    skip: "Ir al contenido",
    "lang.label": "Idioma",
    "gap.kicker": "La brecha en SF State",
    "gap.title": "Unos 3,300 estudiantes de licenciatura de SF State probablemente reúnen los requisitos de CalFresh y no lo reciben.",
    "gap.about": "unos",
    "gap.students": "estudiantes",
    "gap.upto": "hasta",
    "gap.year": "al año",
    "gap.money": "Hasta $12 millones al año en dinero para comida — solo CalFresh, con el máximo para una persona.",
    "gap.eligible": "≈5,810 probablemente elegibles",
    "gap.receiving": "≈2,520 ya lo reciben",
    "gap.missing": "≈3,290 todavía no",
    "gap.method": "Estimado basado en investigación sobre elegibilidad en la UC, aplicado a la matrícula de SF State: el 33% de los estudiantes de licenciatura de la UC eran elegibles para CalFresh (California Policy Lab, datos de otoño de 2019, publicados en agosto de 2024), aplicado a los 17,607 estudiantes de licenciatura de SF State (otoño de 2025), menos el 14.3% de los estudiantes de licenciatura de SF State que ya recibieron CalFresh en 2023–24 (California Policy Lab, agosto de 2026). «Hasta» supone el máximo de $306 para una persona durante 12 meses; el beneficio promedio es menor.",
    "gap.sources": "Fuentes",
    "gap.src1": "Matrícula: 17,607 estudiantes de licenciatura, otoño de 2025 (SF State Facts).",
    "gap.src2": "Elegibles: 33% de los estudiantes de licenciatura de la UC, otoño de 2019 (California Policy Lab, «Filling the Gap», agosto de 2024) → ≈5,810 en SF State.",
    "gap.src3": "Ya lo reciben: 14.3% de los estudiantes de licenciatura de SF State, 2023–24 (California Policy Lab, agosto de 2026) → ≈2,520.",
    "gap.src4": "Hasta $306 al mes: máximo de CalFresh para una persona desde el 1 de octubre de 2026 (CDSS ACIN I-40-26).",
    "gap.src5": "El promedio es menor: los estudiantes de licenciatura de la UC que participaban recibían en promedio $161 al mes cuando el máximo era $194 (California Policy Lab, febrero de 2025), unos $10 millones al año con esa proporción.",
    "gap.src6": "No se cuentan estudiantes de posgrado: el 13.6% de los estudiantes de posgrado de SF State ya recibe CalFresh, más que la tasa de elegibilidad de posgrado de la UC (7%).",
    "gap.src7": "Probablemente conservador: desde el 1 de junio de 2026, los estudiantes de licenciatura de la CSU a medio tiempo cumplen la regla para estudiantes (CDSS ACL 26-25); la tasa de 2019 es anterior.",
    "how.kicker": "Cómo funciona",
    "how.title": "La IA escucha. Una tabla de reglas decide. Una persona confirma.",
    "how.1.h": "La IA escucha",
    "how.1.p": "Un modelo de lenguaje convierte lo que dice el estudiante en respuestas, como unidades, renta e ingresos. Nunca escribe una frase ni fija un número.",
    "how.2.h": "Una tabla de reglas decide",
    "how.2.p": "Una tabla de reglas con fecha calcula el estimado, y cada frase sale de un banco de frases escrito de antemano.",
    "how.3.h": "Una persona confirma",
    "how.3.p": "Una coordinación de CalFresh del campus confirma o corrige todo lo dudoso antes de marcar un caso como revisado. El condado toma cada decisión de elegibilidad.",
    "care.kicker": "Responsable desde el diseño",
    "care.title": "Pide permiso antes de empezar, guarda poco y no decide nada.",
    "care.consent.h": "Permiso antes de preguntar",
    "care.consent.p": "Cada llamada y cada chat empieza diciendo que es una IA hecha por estudiantes y luego pregunta si está bien empezar.",
    "care.audio.h": "El audio de la llamada no se graba",
    "care.audio.p": "GatorPlate guarda las respuestas del estudiante y citas cortas de sus palabras, no la conversación.",
    "care.ssn.h": "Nunca pide el número de Seguro Social ni el estatus migratorio",
    "care.ssn.p": "Los dígitos que parecen un número de Seguro Social o de tarjeta se borran antes de que nada más vea el texto.",
    "care.est.p": "La coordinación revisa cada respuesta dudosa antes de marcar el caso como revisado.",
    "care.yl.tag": "Por revisar",
    "care.yl.text": "Renta mensual — «unos 800, creo»",
    "prog.kicker": "Seis programas",
    "prog.sofar": "Las cifras de arriba cuentan solo CalFresh.",
    "prog.title": "CalFresh es la llave.",
    "prog.sub": "Puede abrir más ayudas este año: Medi-Cal, Clipper START, PG&E CARE, California LifeLine y créditos fiscales.",
    "prog.tax": "Créditos fiscales",
    "prog.check": "Revisamos seis programas. Para Maria, cuatro ahorran dinero, uno es cobertura médica y uno es un «quizá» al declarar impuestos.",
    "prog.who": "Maria, una estudiante de ejemplo de nuestra demo",
    "prog.alone": "Solo CalFresh",
    "prog.upto": "hasta unos",
    "prog.transit": "Clipper START — transporte",
    "prog.phone": "California LifeLine — teléfono",
    "prog.phone.amt": "hasta $220",
    "prog.energy": "PG&E CARE — energía",
    "prog.total": "Total al año, hasta unos",
    "prog.coverage": "+ cobertura médica",
    "prog.maybe": "quizá $200 — no se cuenta",
    "prog.note": "Estimados de tablas con fecha, calculados por código, no por la IA. Cada agencia decide.",
    "try.kicker": "Pruébalo",
    "try.title": "Revisa el dinero que quizá te falta reclamar.",
    "try.sub_phone": "Unos minutos. Gratis. Llama en inglés, o habla en tu navegador en inglés o español.",
    "try.sub_web": "Unos minutos. Gratis. Habla en tu navegador en inglés o español.",
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

// A big pitch title as display lines, one per sentence ("The AI listens." / "A rules table decides." / ...).
export function sentenceLines(text) {
  return String(text).split(/(?<=[.!?])\s+/).filter(Boolean);
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
    trySub: phone ? s["try.sub_phone"] : s["try.sub_web"],   // 05 Try it: mentions the call only when there is one
    // The one filled button on each screen: the call when there is a number, except on the Spanish page, where the
    // English-only phone line stays first but outlined and talking in the browser (in Spanish) is the filled one.
    primary: phone && l !== "es" ? "phone" : "talk",
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
    if (typeof text !== "string") continue;
    if (node.hasAttribute("data-lines")) {   // one display line per sentence
      if (node.textContent === text && node.children.length) continue;
      const lines = sentenceLines(text).map((part) => {
        const span = document.createElement("span");
        span.className = "pitch__line";
        span.textContent = part;
        return span;
      });
      node.replaceChildren(...lines.flatMap((span, i) => (i ? [" ", span] : [span])));
    } else if (node.textContent !== text) node.textContent = text;
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
  if ($("try-sub").textContent !== v.trySub) $("try-sub").textContent = v.trySub;
  for (const pre of ["", "cta-"]) {
    $(`${pre}talk-link`).setAttribute("href", v.talkHref);
    $(`${pre}about-link`).setAttribute("href", v.aboutHref);
    $(`${pre}console-link`).setAttribute("href", v.consoleHref);
    const link = $(`${pre}phone-link`);
    const note = $(`${pre}phone-note`);
    link.hidden = !v.phone;
    note.hidden = !(v.phone && v.phone.note);
    link.classList.toggle("btn--primary", v.primary === "phone");
    $(`${pre}talk-link`).classList.toggle("btn--primary", v.primary === "talk");
    if (v.phone) {
      $(`${pre}phone-text`).textContent = v.phone.text;
      if (v.phone.href) link.setAttribute("href", v.phone.href);
      else link.removeAttribute("href");
      note.textContent = v.phone.note;
    }
  }
}

// Calm reveal of the pitch sections while scrolling: only with motion allowed and IntersectionObserver present;
// otherwise (and before this runs) everything is simply shown.
function reveal() {
  const calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: no-preference)").matches;
  if (!calm || typeof IntersectionObserver !== "function") return;
  const sections = [...document.querySelectorAll(".pitch, .split")];   // the bar grows when it is itself in view
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("is-in");
      io.unobserve(e.target);
    }
  }, { rootMargin: "0px 0px -12% 0px", threshold: 0 });
  for (const el of sections) io.observe(el);
  document.documentElement.classList.add("js-reveal");
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
  reveal();
  try {
    current = { ...current, info: await fetchJSON("/api/public/info", { lang: current.lang }) };
  } catch {
    current = { ...current, info: null };
  }
  paint();
}

if (typeof document !== "undefined" && document.getElementById("headline")) init();
