// The talk, landing and about pages as files (docs/UI_SPEC.md A0, A2.3, A5, A7.2, A7.3, A9): the output guard of
// data/content/guards.json over every page string, names, light only, privacy in the page code, the web disclosure
// from the sentence bank, the about page's contacts and its programs sentence. Run with `make test-web WEB=web/talk`.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

import { STRINGS } from "./strings.js";
import { LANDING_STRINGS } from "../landing.js";
import { programsShown } from "../about/about.js";

const root = new URL("../../", import.meta.url);
const raw = (rel) => readFileSync(new URL(rel, root), "utf8");
const json = (rel) => JSON.parse(raw(rel));
const norm = (s) => String(s).replace(/[‘’]/g, "'").replace(/[“”]/g, "\"").replace(/\s+/g, " ").trim();
const pageText = (rel) => norm(raw(rel).replace(/<script[\s\S]*?<\/script>/g, " ").replace(/<[^>]+>/g, " ")
  .replace(/&amp;/g, "&").replace(/&nbsp;/g, " ")).replace(/ ([,.;:)])/g, "$1");

// A7's own files (docs/UI_SPEC.md A9 covers every page; these are the ones this folder's owner writes).
const OWN = ["web/index.html", "web/landing.js", "web/landing.css", "web/about/index.html", "web/about/about.js",
  "web/about/about.css", ...readdirSync(new URL("web/talk/", root)).filter((f) => !f.endsWith(".test.mjs"))
    .map((f) => `web/talk/${f}`)];
const PAGES = ["web/index.html", "web/talk/index.html", "web/about/index.html"];

// guards.json patterns are Python regular expressions with Unicode word boundaries; JS `\b` and `\w` are ASCII-only,
// so they are rewritten with Unicode letter classes before use.
const W = "[\\p{L}\\p{N}_]";
function pyRegex(pattern) {
  const src = pattern.replace(/\\b/g, `(?:(?<=${W})(?!${W})|(?<!${W})(?=${W}))`).replace(/\\w/g, W);
  return new RegExp(src, "iu");
}
const guards = json("data/content/guards.json").output;
const FORBIDDEN = { en: guards.forbidden.en.map(pyRegex), es: guards.forbidden.es.map(pyRegex) };

function guardHits(text, lang) {
  const t = norm(text);
  const hits = FORBIDDEN[lang].filter((re) => re.test(t)).map(String);
  for (const phrase of guards.forbidden_phrases) if (t.toLowerCase().includes(phrase)) hits.push(phrase);
  return hits;
}

test("the guard reader matches what the output guard blocks (sanity)", () => {
  assert.ok(guardHits("You will get about $306.", "en").length > 0);
  assert.ok(guardHits("We'll send you a text message.", "en").length > 0);
  assert.ok(guardHits("Te enviaremos un recordatorio.", "es").length > 0);
  assert.ok(guardHits("Ya eres elegible.", "es").length > 0);
  assert.ok(guardHits("you'll save $40 a year", "en").length > 0);
  assert.deepEqual(guardHits("Estimate only — the county decides.", "en"), []);
});

test("no page string says what the output guard blocks (rejections, promises, savings), in either language", () => {
  for (const lang of ["en", "es"]) {
    for (const [key, value] of Object.entries(STRINGS[lang])) assert.deepEqual(guardHits(value, lang), [], `talk ${lang} ${key}`);
    for (const [key, value] of Object.entries(LANDING_STRINGS[lang])) {
      assert.deepEqual(guardHits(value, lang), [], `landing ${lang} ${key}`);
    }
  }
  for (const page of PAGES) assert.deepEqual(guardHits(pageText(page), "en"), [], page);
});

test("the UI_SPEC A9 item 6 words appear in none of A7's files (whole words, comments included)", () => {
  const res = [/\bnot eligible\b/i, /\bineligible\b/i, /\bdon'?t qualify\b/i, /\bdenied\b/i, /\bno califica\b/i,
    /\bno eres elegible\b/i];
  for (const file of OWN) for (const re of res) assert.ok(!re.test(raw(file)), `${file}: ${re}`);
});

// The names only the web disclosure may use: the capitalized words inside the privacy line's parentheses.
const NAMES = [...new Set(STRINGS.en.privacy.match(/\(([^)]*)\)/)[1].match(/\b[A-Z][a-z]+\b/g))];

test("browser and company names: only in the web disclosure (the privacy line), nowhere else in A7's files", () => {
  assert.equal(NAMES.length, 4);
  const names = new RegExp(`\\b(?:${NAMES.join("|")})\\b`);
  const privacy = new Set([STRINGS.en.privacy, STRINGS.es.privacy]);
  for (const file of OWN) {
    let text = raw(file);
    for (const p of privacy) text = text.split(p).join(" ");
    assert.ok(!names.test(text), `${file} names a browser or company outside the disclosure`);
  }
});

test("light only: no dark-scheme rules, the color-scheme meta on every page", () => {
  // The media feature's name is assembled so this file does not trip tools/check_contrast.py's own scan.
  const dark = new RegExp(["prefers", "color", "scheme"].join("-"));
  for (const file of OWN) assert.ok(!dark.test(raw(file)), file);
  for (const page of PAGES) {
    const html = raw(page);
    assert.match(html, /<meta name="color-scheme" content="only light">/, page);
    assert.ok(html.indexOf("/shared/tokens.css") < html.indexOf("/shared/base.css"), `${page}: tokens.css first`);
    assert.ok(!/\sstyle=|<style|\son[a-z]+=/i.test(html), `${page}: CSP-safe`);
    assert.ok(!/<script(?![^>]*\bsrc=)[^>]*>/i.test(html), `${page}: no inline script`);
  }
});

test("privacy in the page code: no storage, no logging, no third-party requests, no QR on the talk page", () => {
  for (const file of OWN.filter((f) => f.endsWith(".js"))) {
    const code = raw(file);
    for (const re of [/localStorage/, /sessionStorage/, /indexedDB/, /document\.cookie/, /\bconsole\./, /sendBeacon/,
      /innerHTML/, /https?:\/\//]) {
      assert.ok(!re.test(code), `${file}: ${re}`);
    }
  }
  for (const file of OWN.filter((f) => f.startsWith("web/talk/"))) assert.ok(!/qr/i.test(raw(file)), file);
});

test("the talk page adds nothing for the card's other programs: no program question, name or answer of its own", () => {
  // The card asks its three questions after the call; the call and the talk page do not (docs/SPEC.md §4 row 3.15).
  const programs = /\b(?:tax|dependiente|dependent|Medi-Cal|Clipper|LifeLine|CARE|transit|unlocked|program_answers)\b|PG&E/i;
  for (const file of OWN.filter((f) => f.startsWith("web/talk/"))) assert.ok(!programs.test(raw(file)), file);
});

test("the web disclosure is the sentence bank's text, and the talk page shows the same words before the start", () => {
  for (const lang of ["en", "es"]) {
    const bank = json(`data/content/sentences.${lang}.json`).messages["consent.ask"].web;
    const say = (Array.isArray(bank) ? bank[0] : bank).say;
    const start = json(`web/fixtures/${json("web/fixtures/index.json").routes["POST /v1/calls/{call_id}/start"][lang]}`)[0];
    assert.equal(start.say, say, `${lang}: the fixture opening is the bank's`);
    // The intro's privacy line = the bank's disclosure without its first sentence, plus what is kept.
    const rest = say.slice(say.indexOf(". ") + 2);
    assert.ok(STRINGS[lang].privacy.startsWith(rest), `${lang}: ${rest}`);
  }
});

test("about: the coordinator contact matches data/content/contacts.json", () => {
  const c = json("data/content/contacts.json").coordinator;
  const text = pageText("web/about/index.html");
  const html = raw("web/about/index.html");
  assert.ok(text.includes(c.display), c.display);
  assert.ok(html.includes(`href="tel:${c.phone}"`), c.phone);
  assert.ok(html.includes(`href="mailto:${c.email}"`), c.email);
  assert.ok(text.includes(c.place.en), c.place.en);
  assert.ok(text.includes(c.hours.text.en), c.hours.text.en);
});

test("about: the programs sentence is hedged, computed by code, and hidden when the server switched it off", () => {
  const text = pageText("web/about/index.html");
  const m = text.match(/When the estimate is likely[^]*?Not a promise\./);
  assert.ok(m, "the programs sentence");
  assert.ok(m[0].includes("computed by code, never by the AI"));
  assert.ok(m[0].endsWith("Each agency decides. Not a promise."));
  assert.ok(!/PG&E|\$\d/.test(m[0]), "no utility name and no amount on the about page");
  assert.match(raw("web/about/index.html"), /<p id="programs-note">/);
  assert.equal(programsShown({ programs: { enabled: true, table_id: "GP-Programs-2026", valid_today: true } }), true);
  assert.equal(programsShown({ programs: { enabled: false, table_id: null, valid_today: false } }), false);
  assert.equal(programsShown({ programs: { enabled: true, table_id: "GP-Programs-2026", valid_today: false } }), false);
  assert.equal(programsShown({ ok: true }), true, "an older server: keep the static text");
  assert.equal(programsShown(null), true);
});
