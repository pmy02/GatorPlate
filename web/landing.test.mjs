// Landing page view (docs/UI_SPEC.md A7.2): the headline with and without the demo number, the links, and the strings
// in English and Spanish. Run with `make test-web` (or WEB=web).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { LANDING_STRINGS, headlineParts, landingView, resolveLang, sentenceLines } from "./landing.js";
import { STRINGS } from "./talk/strings.js";

// The names only the web disclosure may use (the capitalized words inside the talk page's privacy parentheses).
const NAMES = [...new Set(STRINGS.en.privacy.match(/\(([^)]*)\)/)[1].match(/\b[A-Z][a-z]+\b/g))];

const spec = readFileSync(new URL("../docs/UI_SPEC.md", import.meta.url), "utf8");
const a72 = spec.slice(spec.indexOf("### A7.2"), spec.indexOf("### A7.3")).replace(/\s+/g, " ");
const info = (demo) => ({ demo_phone_display: demo, rules_label: "CalFresh FY2027", effective_from: "2026-10-01" });

test("without a demo number: the browser-only headline and no phone button", () => {
  for (const missing of [null, "", "   ", undefined]) {
    const v = landingView(info(missing), "en");
    assert.equal(v.headline, "Check the money you may be missing — in your browser.");
    assert.equal(v.phone, null);
  }
  assert.equal(landingView(null, "en").phone, null);
});

test("with a demo number: the phone headline and a call link", () => {
  const v = landingView(info("(415) 338-1203"), "en");
  assert.equal(v.headline, "Check the money you may be missing — by phone or in your browser.");
  assert.equal(v.phone.text, "Call (415) 338-1203");
  assert.equal(v.phone.href, "tel:+14153381203");
  const es = landingView(info("(415) 338-1203"), "es");
  assert.equal(es.phone.text, "Llama al (415) 338-1203");
  assert.equal(es.phone.note, "La línea telefónica es solo en inglés.");
  assert.equal(landingView(info("DEMO LINE"), "en").phone.href, null);
});

test("the call button comes first and is the filled one when the demo number is set; otherwise talk is", () => {
  assert.equal(landingView(info("(415) 338-1203"), "en").primary, "phone");
  assert.equal(landingView(info("(415) 338-1203"), "en").phone.href, "tel:+14153381203");
  assert.equal(landingView(info(""), "en").primary, "talk");
  assert.equal(landingView(null, "es").primary, "talk");
  // Spanish page: the English-only call stays first but outlined; talking in the browser (in Spanish) is filled.
  assert.equal(landingView(info("(415) 338-1203"), "es").primary, "talk");
  // 05 Try it mentions calling only when there is a number to call.
  for (const lang of ["en", "es"]) {
    for (const missing of [null, "", "   "]) assert.doesNotMatch(landingView(info(missing), lang).trySub, /\b(?:Call|Llama)\b/);
    assert.match(landingView(info("(415) 338-1203"), lang).trySub, /\b(?:Call|Llama)\b/);
  }
  assert.equal(landingView(null, "en").trySub, LANDING_STRINGS.en["try.sub_web"]);
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  for (const pre of ["", "cta-"]) {
    const phone = html.indexOf(`id="${pre}phone-link"`);
    const talk = html.indexOf(`id="${pre}talk-link"`);
    assert.ok(phone > 0 && talk > phone, `${pre}: call before talk`);
    assert.ok(html.includes('id="try-sub"'), "try-sub");
    for (const id of ["phone-text", "phone-note", "about-link", "console-link"]) assert.ok(html.includes(`id="${pre}${id}"`), pre + id);
  }
});

test("pitch sections: every data-t key exists in both languages, big titles split by sentence", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const keys = [...html.matchAll(/data-t(?:-label)?="([^"]+)"/g)].map((m) => m[1]);
  for (const k of keys) for (const lang of ["en", "es"]) assert.equal(typeof LANDING_STRINGS[lang][k], "string", `${lang} ${k}`);
  const ids = [...html.matchAll(/<section id="([^"]+)" class="pitch/g)].map((m) => m[1]);
  assert.deepEqual(ids, ["gap", "how", "why", "care", "programs", "try"]);
  const nos = [...html.matchAll(/<span class="pitch__no num">(\d+)<\/span>/g)].map((m) => m[1]);
  assert.deepEqual(nos, ["01", "02", "03", "04", "05", "06"]);
  assert.deepEqual(sentenceLines(LANDING_STRINGS.en["how.title"]),
    ["The AI listens.", "A dated rules table decides.", "A person confirms."]);
  assert.deepEqual(sentenceLines(LANDING_STRINGS.en["why.title"]),
    ["Not a chatbot add-on.", "Without the AI, the call is a phone tree."]);
  assert.deepEqual(sentenceLines("CalFresh is the key."), ["CalFresh is the key."]);
});

test("02 pipeline: seven numbered steps, the two AI steps (language model, planner) on the accent; 04: eight risks", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const how = html.slice(html.indexOf('<section id="how"'), html.indexOf('<section id="why"'));
  const steps = [...how.matchAll(/<li class="flow__step( flow__step--ai)?">\s*<span class="flow__no num" aria-hidden="true">(\d)<\/span>/g)];
  assert.deepEqual(steps.map((m) => m[2]), ["1", "2", "3", "4", "5", "6", "7"]);
  assert.deepEqual(steps.filter((m) => m[1]).map((m) => m[2]), ["2", "5"]);
  for (let i = 1; i <= 7; i++) assert.ok(how.includes(`data-t="how.${i}.h"`) && how.includes(`data-t="how.${i}.p"`), `step ${i}`);
  const care = html.slice(html.indexOf('<section id="care"'), html.indexOf('<section id="programs"'));
  assert.equal([...care.matchAll(/<tr class="risk" role="row">/g)].length, 8);
  for (let i = 1; i <= 8; i++) for (const k of ["h", "w", "key", "do", "next"]) assert.ok(care.includes(`data-t="care.r${i}.${k}"`), `risk ${i} ${k}`);
  assert.ok(care.includes('<th scope="col"') && care.includes('<th scope="row"'), "a real table with headers");
  // The test count is the base tree's collected count (3,055 on 2026-10-02), said as "3,000+".
  assert.match(LANDING_STRINGS.en["edge.6.p"], /^3,000\+ automated tests/);
  assert.match(LANDING_STRINGS.es["edge.6.p"], /^Más de 3,000 pruebas/);
  // Simulated runs are labeled as such, and no error-rate figure is shown.
  for (const s of [LANDING_STRINGS.en, LANDING_STRINGS.es]) {
    assert.match(s["edge.note"], /simulated|simulados/);
    assert.doesNotMatch(s["care.r5.do"], /error|6\.1/);
    assert.match(s["care.r5.do"], /simulated|simulados/);
  }
});

test("pitch numbers match the owner-approved estimate (2026-10-02 13:35) in both languages", () => {
  const en = LANDING_STRINGS.en, es = LANDING_STRINGS.es;
  assert.match(en["gap.title"], /^About 3,450 SF State students likely qualify/);
  assert.match(es["gap.title"], /3,450/);
  assert.match(en["gap.money"], /^Up to \$12\.7 million a year/);
  assert.match(es["gap.money"], /^Hasta \$12\.7 millones al año/);
  for (const s of [en, es]) {
    assert.match(s["gap.eligible"], /6,030/);
    assert.match(s["gap.receiving"], /2,580/);
    assert.match(s["gap.missing"], /3,450/);   // 6,030 - 2,580 = 3,450 (3,451.6 unrounded), so the split adds up
    assert.match(s["gap.src4"], /\$306/);
    assert.match(s["gap.src5"], /\$161.*\$194/);
    assert.match(s["gap.src6"], /13\.6%/);    // the graduate caveat stays on screen
    assert.match(s["gap.method"], /17,607/);
    assert.match(s["gap.method"], /3,114/);
    assert.match(s["gap.method"], /14\.3%/);
  }
  assert.equal(6030 - 2580, 3450);
  // undergrads 17,607 x (33% - 14.3%) = 3,292.5; grads 3,114 x 7% x (1 - 27%) = 159.1; gap 3,451.6 -> ~3,450; x $306 x 12 = $12.67M (up to).
  const gap = 17607 * (0.33 - 0.143) + 3114 * 0.07 * (1 - 0.27);
  assert.equal(Math.round(gap / 50) * 50, 3450);
  assert.equal(Math.round(gap * 306 * 12 / 1e5) / 10, 12.7);
  assert.equal(3672 + 168 + 228 + 170, 4238);   // Maria's four programs (the screen rounds each: $4,220)
});

test("pitch wording does not overclaim (no 'nothing is recorded', 'anonymous', 'first', 'every benefit', 'compliant', error rates)", () => {
  const bad = { en: [/nothing is recorded/i, /anonym/i, /\bfirst\b/i, /every benefit/i, /error rate/i, /\d+% (?:fewer|less|more accurate)/i,
    /complian/i, /silent error/i, /\bsecure\b/i],
    es: [/nada se graba/i, /an[oó]nim/i, /\bprimer[oa]?\b/i, /todos los beneficios/i, /tasa de error/i, /cumple con/i, /errores silenciosos/i] };
  for (const lang of ["en", "es"]) {
    for (const [key, value] of Object.entries(LANDING_STRINGS[lang])) {
      for (const re of bad[lang]) assert.ok(!re.test(value), `${lang} ${key}: ${re}`);
    }
  }
});

test("headline lines: hook, then channel; the dash stays on the hook's line; nothing is lost", () => {
  const nb = "\u00a0";
  assert.deepEqual(headlineParts(LANDING_STRINGS.en.headline_phone),
    [`Check the money you may be missing${nb}—`, `by phone or in${nb}your${nb}browser.`]);
  assert.deepEqual(headlineParts(LANDING_STRINGS.en.headline_web), [`Check the money you may be missing${nb}—`, "in your browser."]);
  assert.deepEqual(headlineParts(LANDING_STRINGS.es.headline_phone),
    ["¡Revisa el dinero que quizá te falta reclamar,", `por teléfono o en${nb}tu${nb}navegador!`]);
  assert.deepEqual(headlineParts("One line only."), ["One line only."]);
  for (const lang of ["en", "es"]) {
    for (const k of ["headline_phone", "headline_web"]) {
      const text = LANDING_STRINGS[lang][k];
      assert.equal(headlineParts(text).join(" ").replaceAll(nb, " "), text);
    }
  }
});

test("the A7.2 English wording is used word for word", () => {
  const s = LANDING_STRINGS.en;
  for (const key of ["headline_phone", "headline_web", "sub", "talk", "about", "console", "trust.recorded",
    "trust.ssn", "trust.estimate"]) {
    assert.ok(a72.includes(s[key].replace(/\.$/, "")), key);
  }
  assert.ok(spec.includes(`"${LANDING_STRINGS.en.prototype}"`));
  assert.ok(spec.includes(`"${LANDING_STRINGS.es.prototype}"`));
});

test("links: talk page in the page language, about and console; fixture mode keeps fixtures", () => {
  const v = landingView(null, "es");
  assert.equal(v.talkHref, "/talk?lang=es");
  assert.equal(v.aboutHref, "/about");
  assert.equal(v.consoleHref, "/console");
  const f = landingView(null, "en", { fixtures: true });
  assert.equal(f.talkHref, "/talk/?fixtures=1&lang=en");
  assert.equal(f.aboutHref, "/about/?fixtures=1");
  assert.equal(f.consoleHref, "/console/?fixtures=1");
  assert.equal(landingView(null, "fr").lang, "en");
});

test("language: ?lang= first, then a Spanish browser", () => {
  assert.equal(resolveLang("?lang=es", "en"), "es");
  assert.equal(resolveLang("", "es-US"), "es");
  assert.equal(resolveLang("?lang=xx", "en-US"), "en");
});

test("same keys in both languages; no rejection words, no company names", () => {
  assert.deepEqual(Object.keys(LANDING_STRINGS.en).sort(), Object.keys(LANDING_STRINGS.es).sort());
  const bad = [/\bnot eligible\b/i, /\bineligible\b/i, /\bdon'?t qualify\b/i, /\bdenied\b/i, /\bno califica\b/i,
    /\bno eres elegible\b/i, new RegExp(`\\b(?:${NAMES.join("|")})\\b`)];
  for (const lang of ["en", "es"]) {
    for (const [key, value] of Object.entries(LANDING_STRINGS[lang])) {
      for (const re of bad) assert.ok(!re.test(value), `${lang} ${key}`);
    }
  }
});
