// About page (docs/UI_SPEC.md A7.3): every fact word for word with its source, the phone line only as "a hosted voice
// gateway", the team line, and none of the figures that must stay off screens. Run with `make test-web`.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { STRINGS } from "../talk/strings.js";

// The names only the web disclosure may use (the capitalized words inside the talk page's privacy parentheses).
const NAMES = [...new Set(STRINGS.en.privacy.match(/\(([^)]*)\)/)[1].match(/\b[A-Z][a-z]+\b/g))];

const flat = (s) => s.replace(/\s+/g, " ").trim();
const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
const text = flat(html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&")).replace(/ ([,.;:)])/g, "$1");
const spec = readFileSync(new URL("../../docs/UI_SPEC.md", import.meta.url), "utf8");
const a73 = spec.slice(spec.indexOf("### A7.3"), spec.indexOf("## A8."));

const factRows = a73.split("\n").filter((l) => l.startsWith("| ") && !l.startsWith("| Fact") && !l.startsWith("|---"))
  .map((l) => l.slice(1, -1).split(" | ").map((c) => c.trim()));

test("every A7.3 fact is on the page word for word", () => {
  assert.equal(factRows.length, 6);
  for (const [fact] of factRows) assert.ok(text.includes(fact), fact);
});

test("every fact shows its source and date", () => {
  for (const [, source] of factRows) {
    const shown = flat(source.replace(/\*/g, "").replace(/ \(no statute is cited\)/, ""));
    assert.ok(text.includes(`Source: ${shown}`), shown);
  }
});

test("sections, the hosted voice gateway, the team line and the prototype line", () => {
  for (const heading of ["What GatorPlate is", "The model listens, rules decide, a person confirms", "What is kept",
    "Rules and sources", "Why SF State", "Limits", "Team"]) {
    assert.ok(new RegExp(`<h2[^>]*>${heading}</h2>`).test(html), heading);
  }
  assert.ok(text.includes("a hosted voice gateway"));
  assert.ok(text.includes("Built by an SF State student team."));
  assert.ok(!/SF State students built/i.test(text));
  assert.ok(text.includes("Student-built prototype — not an official SF State, county, or CalFresh service."));
  assert.ok(text.includes("English on the phone; English and Spanish on the web."));
  assert.match(html, /<meta name="color-scheme" content="only light">/);
});

test("not on screens: the UC and community-college figure, the interview statistic, rejection words, names", () => {
  for (const re of [/quarter of eligible/i, /missed (?:their|the) interview/i, /\bnot eligible\b/i, /\bineligible\b/i,
    /\bdon'?t qualify\b/i, /\bdenied\b/i, new RegExp(`\\b(?:${NAMES.join("|")})\\b`), /PG&E/]) {
    assert.ok(!re.test(text), String(re));
  }
});
