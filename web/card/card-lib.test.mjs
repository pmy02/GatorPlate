import assert from "node:assert/strict";
import { test } from "node:test";

import { changed, money, pacificTime, segments, sourceDate, splitAmount, tokenFrom } from "./card-lib.mjs";

test("token from the /c/ path or the fixture query", () => {
  assert.equal(tokenFrom("/c/fixtureMariaCard000001", ""), "fixtureMariaCard000001");
  assert.equal(tokenFrom("/c/Ab_cd-EF12345678/", ""), "Ab_cd-EF12345678");
  assert.equal(tokenFrom("/card/", "?fixtures=1&token=fixture"), "fixture");
  assert.equal(tokenFrom("/card/", "?fixtures=1"), null);
  assert.equal(tokenFrom("/c/../../etc", ""), null);
  assert.equal(tokenFrom("/card/", "?token=%3Cscript%3E"), null);
});

test("the hero amount is found in the headline", () => {
  assert.equal(money(1100), "$1,100");
  assert.deepEqual(splitAmount("You may get about $306 a month for groceries.", 306),
    ["You may get about ", "$306", " a month for groceries."]);
  assert.deepEqual(splitAmount("Podrías recibir unos $1,023 al mes.", 1023), ["Podrías recibir unos ", "$1,023", " al mes."]);
  assert.equal(splitAmount("One detail needs a person to check.", null), null);
  assert.equal(splitAmount("No amount here.", 306), null);
});

test("phone numbers, the email and web addresses become links", () => {
  const s = segments("Email calfresh@sfsu.edu to book a time, or call (415) 338-1203. Hours: Mon–Thu.");
  assert.deepEqual(s, ["Email ", { text: "calfresh@sfsu.edu", href: "mailto:calfresh@sfsu.edu" }, " to book a time, or call ",
    { text: "(415) 338-1203", href: "tel:+14153381203" }, ". Hours: Mon–Thu."]);
  const u = segments("Hours change. See https://asi.sfsu.edu/gator-groceries.");
  assert.deepEqual(u[1], { text: "asi.sfsu.edu/gator-groceries", href: "https://asi.sfsu.edu/gator-groceries", external: true });
  assert.equal(u[2], ".");
  const c = segments("In crisis? Call 988 anytime. In an emergency, call 911.");
  assert.deepEqual(c.filter((x) => typeof x !== "string").map((x) => x.href), ["tel:988", "tel:911"]);
  assert.deepEqual(segments("No links, $1,729 a month, CF 386."), ["No links, $1,729 a month, CF 386."]);
});

test("988 and 911 inside an amount or a longer number stay text", () => {
  for (const text of ["Work pays about $1,911 a month.", "About $988.", "Rent $2,988.50 a month.", "Code 9111 or 1988."]) {
    assert.deepEqual(segments(text), [text], text);
  }
  const c = segments("988 anytime; 911 now (988/911).");
  assert.deepEqual(c.filter((x) => typeof x !== "string").map((x) => x.text), ["988", "911", "988", "911"]);
  assert.equal(c.filter((x) => typeof x === "string").join(""), " anytime;  now (/).");
  const es = segments("¿En crisis? Llama al 988 a cualquier hora. En una emergencia, llama al 911.");
  assert.deepEqual(es.map((x) => (typeof x === "string" ? x : x.text)).join(""),
    "¿En crisis? Llama al 988 a cualquier hora. En una emergencia, llama al 911.");
});

test("refetch only when the tier or the estimate changed", () => {
  const view = { tier: "likely", estimate_monthly: 306 };
  assert.equal(changed(view, { tier: "likely", estimate_monthly: 306, reviewed: true }), false);
  assert.equal(changed(view, { tier: "likely", estimate_monthly: 155 }), true);
  assert.equal(changed({ tier: "coordinator", estimate_monthly: null }, { tier: "coordinator", estimate_monthly: null }), false);
});

test("times and source dates in Pacific Time", () => {
  assert.equal(pacificTime("2026-10-03T00:03:00Z", "en"), "5:03 PM");
  assert.match(pacificTime("2026-10-03T00:03:00Z", "es"), /^5:03\sp/);
  const t = (k, v = {}) => ({ "source.current": "current", "source.saved": `page saved ${v.date}` })[k];
  assert.equal(sourceDate("2015-04-15", "en", t), "Apr 15, 2015");
  assert.equal(sourceDate("current", "en", t), "current");
  assert.equal(sourceDate("page as saved 2026-10-01", "en", t), "page saved Oct 1, 2026");
});
