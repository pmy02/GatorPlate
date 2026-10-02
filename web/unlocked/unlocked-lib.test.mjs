import assert from "node:assert/strict";
import { test } from "node:test";

import { countValue, fillCount, gone, share, splitAmount, usd, widths } from "./unlocked-lib.mjs";

test("count-up steps run from the old total to the new one, ease-out, whole dollars", () => {
  assert.equal(countValue(3670, 3830, 0), 3670);
  assert.equal(countValue(3670, 3830, 1), 3830);
  assert.equal(countValue(3670, 3830, 7), 3830);
  assert.equal(countValue(3670, 3830, -1), 3670);
  const steps = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1].map((t) => countValue(3670, 3830, t));
  for (let i = 1; i < steps.length; i += 1) assert.ok(steps[i] >= steps[i - 1], `monotone at ${i}`);
  assert.ok(steps[2] - steps[0] > steps[6] - steps[4], "fast first, slow at the end");
  for (const v of steps) assert.equal(v, Math.trunc(v));
  assert.equal(countValue(4220, 4050, 1), 4050);
  assert.ok(countValue(4220, 4050, 0.5) < 4220);
});

test("segment widths are each counted line's share of the headline, in the order sent", () => {
  const segs = [["calfresh", 3670], ["clipper_start", 160], ["lifeline", 220], ["care", 170]];
  const w = widths(segs, 4220);
  assert.deepEqual(w.map(([id]) => id), ["calfresh", "clipper_start", "lifeline", "care"]);
  assert.ok(Math.abs(w.reduce((s, [, x]) => s + x, 0) - 1) < 1e-9);
  assert.ok(Math.abs(w[0][1] - 3670 / 4220) < 1e-12);
  assert.deepEqual(widths([["calfresh", 0]], 0), [["calfresh", 0]]);
  assert.deepEqual(widths(null, 10), []);
});

test("the total amount is found in the total text in both languages", () => {
  assert.equal(usd(4220), "$4,220");
  assert.deepEqual(splitAmount("About $4,220 a year", 4220), ["About ", "$4,220", " a year"]);
  assert.deepEqual(splitAmount("Unos $10,410 al año", 10410), ["Unos ", "$10,410", " al año"]);
  assert.equal(splitAmount("About $4,220 a year", 4050), null);
  assert.equal(splitAmount(null, 4220), null);
  assert.equal(splitAmount("About $0 a year", null), null);
});

test("question count and gone", () => {
  assert.equal(fillCount("Question {i} of {n}", 2, 3), "Question 2 of 3");
  assert.equal(fillCount("Pregunta {i} de {n}", 1, 3), "Pregunta 1 de 3");
  assert.equal(gone({ status: 404 }), true);
  assert.equal(gone({ status: 410 }), true);
  for (const status of [0, 409, 422, 429, 500, 503]) assert.equal(gone({ status }), false);
  assert.equal(gone(null), false);
});

test("share uses the share sheet when there is one", async () => {
  const seen = [];
  const how = await share("I found about $4,200", { share: async (data) => { seen.push(data); } });
  assert.equal(how, "shared");
  assert.deepEqual(seen, [{ text: "I found about $4,200" }]);
});

test("share: closing the sheet is not an error and copies nothing", async () => {
  let copied = false;
  const nav = {
    share: async () => { throw Object.assign(new Error("closed"), { name: "AbortError" }); },
    clipboard: { writeText: async () => { copied = true; } },
  };
  assert.equal(await share("x", nav), "cancelled");
  assert.equal(copied, false);
});

test("share falls back to the clipboard, then to a selectable field", async () => {
  let copied = null;
  const clip = { clipboard: { writeText: async (t) => { copied = t; } } };
  assert.equal(await share("text one", clip), "copied");
  assert.equal(copied, "text one");
  const refused = { share: async () => { throw Object.assign(new Error("no"), { name: "NotAllowedError" }); }, ...clip };
  assert.equal(await share("text two", refused), "copied");
  assert.equal(copied, "text two");
  const noClip = { clipboard: { writeText: async () => { throw new Error("blocked"); } } };
  assert.equal(await share("text three", noClip), "field");
  assert.equal(await share("text four", {}), "field");
});
