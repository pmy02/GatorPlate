// Talk page strings: word for word as docs/UI_SPEC.md A5.3 and A5.6 (and the A0 prototype line), the same keys in
// English and Spanish, no rejection words, and browser or company names only in the privacy line (A0.9).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { LANG_NAMES, STRINGS } from "./strings.js";

const spec = readFileSync(new URL("../../docs/UI_SPEC.md", import.meta.url), "utf8");

function section(title) {
  const start = spec.indexOf(title);
  assert.ok(start >= 0, title);
  const end = spec.indexOf("\n### ", start + title.length);
  return spec.slice(start, end < 0 ? undefined : end);
}

function rows(text) {
  return text.split("\n").filter((l) => l.startsWith("| ") && !l.startsWith("| ---") && !/^\|\s*-/.test(l))
    .map((l) => l.slice(1, -1).split(" | ").map((c) => c.trim()));
}

test("A5.6 strings are word for word, in both languages", () => {
  const table = rows(section("### A5.6 Talk page strings")).slice(1);
  let checked = 0;
  for (const [keyCell, en, es] of table) {
    const keys = keyCell.split(" / ").map((k) => k.replace(/`/g, "").trim());
    if (keys[0] === "prototype") continue;
    const ens = keys.length > 1 ? en.split(" · ") : [en];
    const ess = keys.length > 1 ? es.split(" · ") : [es];
    keys.forEach((key, i) => {
      assert.equal(STRINGS.en[key], ens[i], `en ${key}`);
      assert.equal(STRINGS.es[key], ess[i], `es ${key}`);
      checked += 1;
    });
  }
  assert.ok(checked >= 18, `checked ${checked}`);
});

test("A5.3 error messages are word for word", () => {
  const table = rows(section("### A5.3 Errors")).slice(1);
  const keyOf = {
    "Mic blocked": "err.mic_blocked",
    "No speech recognition in this browser (detected at run time)": "err.no_voice",
    "No speech heard": "err.no_speech",
    Network: "err.network",
    "Server slow": "err.slow",
    "Server down": "err.server",
    "Too many sessions (`429`)": "err.busy",
    "No sound on a phone": "err.no_sound",
  };
  assert.equal(table.length, Object.keys(keyOf).length);
  for (const [name, en, es] of table) {
    const key = keyOf[name];
    assert.ok(key, name);
    assert.equal(STRINGS.en[key], en, `en ${key}`);
    assert.equal(STRINGS.es[key], es, `es ${key}`);
  }
});

test("A5.4 and A5.5 short strings, and the A0 prototype line", () => {
  assert.equal(STRINGS.en.switched, "Switched to English");
  assert.equal(STRINGS.es.switched, "Cambiamos a español");
  assert.equal(`${STRINGS.en.read_aloud}: ${STRINGS.en.on}/${STRINGS.en.off}`, "Read aloud: On/Off");
  assert.equal(`${STRINGS.es.read_aloud}: ${STRINGS.es.on}/${STRINGS.es.off}`, "Leer en voz alta: sí/no");
  assert.equal(STRINGS.en.tap_to_talk, "Tap to talk");
  assert.equal(STRINGS.es.tap_to_talk, "Toca para hablar");
  const a0 = section("## A0. Ground rules for every screen");
  assert.ok(a0.includes(`"${STRINGS.en.prototype}"`));
  assert.ok(a0.includes(`"${STRINGS.es.prototype}"`));
  assert.deepEqual(LANG_NAMES, { en: "English", es: "Español" });
});

test("English and Spanish have the same keys, none empty", () => {
  assert.deepEqual(Object.keys(STRINGS.en).sort(), Object.keys(STRINGS.es).sort());
  for (const lang of ["en", "es"]) {
    for (const [key, value] of Object.entries(STRINGS[lang])) assert.ok(value && value.trim(), `${lang} ${key}`);
  }
});

// The names the web disclosure may use: the capitalized words inside the privacy line's parentheses.
function disclosureNames() {
  const inside = STRINGS.en.privacy.match(/\(([^)]*)\)/)[1];
  return [...new Set(inside.match(/\b[A-Z][a-z]+\b/g))];
}

test("never a rejection; browser and company names only in the privacy line", () => {
  const forbidden = [/\bnot eligible\b/i, /\bineligible\b/i, /\bdon'?t qualify\b/i, /\bdenied\b/i,
    /\bno califica\b/i, /\bno eres elegible\b/i];
  assert.equal(disclosureNames().length, 4);
  const names = new RegExp(`\\b(?:${disclosureNames().join("|")})\\b`);
  for (const lang of ["en", "es"]) {
    for (const [key, value] of Object.entries(STRINGS[lang])) {
      for (const re of forbidden) assert.ok(!re.test(value), `${lang} ${key}`);
      if (key !== "privacy") assert.ok(!names.test(value), `${lang} ${key} names a company`);
    }
  }
});
