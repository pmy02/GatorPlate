// Landing page view (docs/UI_SPEC.md A7.2): the headline with and without the demo number, the links, and the strings
// in English and Spanish. Run with `make test-web` (or WEB=web).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { LANDING_STRINGS, headlineParts, landingView, resolveLang } from "./landing.js";
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

test("headline lines: hook, then channel; the dash stays on the hook's line; nothing is lost", () => {
  const nb = "\u00a0";
  assert.deepEqual(headlineParts(LANDING_STRINGS.en.headline_phone),
    [`Check the money you may be missing${nb}—`, `by phone or in${nb}your${nb}browser.`]);
  assert.deepEqual(headlineParts(LANDING_STRINGS.en.headline_web), [`Check the money you may be missing${nb}—`, "in your browser."]);
  assert.deepEqual(headlineParts(LANDING_STRINGS.es.headline_phone),
    ["Revisa el dinero que quizá te falta reclamar,", `por teléfono o en${nb}tu${nb}navegador.`]);
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
