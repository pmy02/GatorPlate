import assert from "node:assert/strict";
import { test } from "node:test";

import { cardPath, normalizeCode } from "./go-lib.mjs";

test("codes: six digits, spaces and dashes ignored", () => {
  assert.equal(normalizeCode("481206"), "481206");
  assert.equal(normalizeCode(" 481 206 "), "481206");
  assert.equal(normalizeCode("481-206"), "481206");
  assert.equal(normalizeCode("4 8 1 2 0 6"), "481206"); // the field allows 16 characters for this
  assert.equal(normalizeCode("48120"), null);
  assert.equal(normalizeCode("4812067"), null);
  assert.equal(normalizeCode("abc123"), null);
  assert.equal(normalizeCode(null), null);
});

test("only a card path on this site is opened", () => {
  assert.equal(cardPath("/c/fixtureMariaCard000001"), "/c/fixtureMariaCard000001");
  assert.equal(cardPath("/c/fixtureMariaCard000001", true), "/card/?fixtures=1&token=fixtureMariaCard000001");
  assert.equal(cardPath("https://example.invalid/c/abcdefgh12"), null);
  assert.equal(cardPath("//example.invalid/c/abcdefgh12"), null);
  assert.equal(cardPath("/console"), null);
  assert.equal(cardPath(undefined), null);
});
