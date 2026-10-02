// Console wording and formatter tests (node --test; run through `make test-web WEB=web/console`).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import * as T from "./text.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name) => JSON.parse(readFileSync(path.join(here, "..", "fixtures", name), "utf8"));
const meta = fixture("meta.json");
const names = meta.programs.names;

// Maria after the three card taps (golden case PG1): the console footer of section 6b.
function mariaPg1() {
  const p = structuredClone(fixture("case_maria.json").programs);
  const set = (id, patch) => Object.assign(p.lines.find((l) => l.id === id), patch);
  set("clipper_start", { status: "likely", value_yearly: 168, display_yearly: 160, counted: true, range_lo: null, range_hi: null });
  set("lifeline", { status: "likely", counted: true });
  set("care", { status: "likely", counted: true });
  Object.assign(p, { found_yearly: 4238, found_display: 4220, share_display: 4200 });
  return p;
}

test("6b footer, PG1: the exact wording of the brief", () => {
  assert.equal(T.programsFooter(mariaPg1(), names),
    "Found about $4,220 a year (CalFresh $3,670 + 3 programs) · not counted: Medi-Cal coverage, maybe tax credits $200");
});

test("6b footer, PG2: check lines are listed as not counted", () => {
  const p = fixture("case_maria.json").programs;
  assert.equal(T.programsFooter(p, names), "Found about $3,670 a year (CalFresh $3,670) · not counted: Medi-Cal coverage, "
    + "Clipper START to check, California LifeLine to check, PG&E CARE to check, maybe tax credits $200");
});

test("6b per-year column: counted value, a check range floored to $10, otherwise a dash", () => {
  const lines = Object.fromEntries(fixture("case_maria.json").programs.lines.map((l) => [l.id, l]));
  assert.equal(T.programPerYear(lines.calfresh), "$3,670");
  assert.equal(T.programPerYear(lines.clipper_start), "$90–$440");
  assert.equal(T.programPerYear(lines.lifeline), "—");
  assert.equal(T.programPerYear(lines.medi_cal), "—");
  assert.equal(T.programPerYear(lines.tax_credits), "—");
  assert.equal(T.PROGRAM_STATUS.check, "Check");
  assert.equal(T.PROGRAM_STATUS.coverage, "Coverage");
  assert.equal(T.PROGRAM_STATUS.maybe, "Maybe");
  assert.equal(T.PROGRAM_STATUS.zero, "Not counted");
});

test("6b header and the list_only line (Sofia)", () => {
  assert.equal(T.programsHeader("2026-10-01"), "Computed by the programs table — not by AI · checked Oct 1, 2026");
  assert.equal(T.listOnlyLine(fixture("case_sofia.json").programs, names),
    "Programs to check with the student: Medi-Cal (family income) · Clipper START");
  assert.equal(T.listOnlyLine(fixture("case_maria.json").programs, names), null);
  assert.equal(T.programsFooter(fixture("case_sofia.json").programs, names), null);
  assert.equal(T.programsFooter(null, names), null);
});

test("From the card: card answers with the newest answer's Pacific time", () => {
  const answers = {
    pge_bill: { value: "own_roommate", at: "2026-10-02T23:12:00Z", source: "card" },
    break_transit: { value: "weekdays_muni", at: "2026-10-02T23:11:20Z", source: "card" },
    tax_dependent: { value: "no", at: "2026-10-02T23:11:40Z", source: "card" },
  };
  const line = T.fromCardLine(answers, meta.programs.questions);
  assert.equal(line.text, "Rides over breaks: most weekdays (Muni) · Tax dependent: no · PG&E bill: roommate's name — from the card, 4:12 PM");
  assert.equal(line.sample, false);
});

test("From the card: Jamal's seeded answers end with 'sample answers'", () => {
  const line = T.fromCardLine(fixture("case_jamal.json").case.program_answers, meta.programs.questions);
  assert.equal(line.text, "Rides over breaks: 1–2 days a week · Tax dependent: no — sample answers");
  assert.equal(line.sample, true);
  assert.equal(T.fromCardLine({}), null);
  assert.equal(T.fromCardLine(null), null);
});

test("list row: found per year", () => {
  assert.equal(T.foundPerYear(4220), "Found about $4,220/yr");
  assert.equal(T.foundPerYear(3980), "Found about $3,980/yr");
});

test("reason chips (A3.10) and the W1 strings", () => {
  const c = fixture("case_maria.json").case;
  const flip = c.asked.find((a) => a.kind === "flip");
  assert.deepEqual(T.askedChip(flip), { text: "Why this question? Could change the estimate by $151: $155 or $306", style: "outcome" });
  assert.equal(T.askedChip(c.asked.find((a) => a.key === "expedited.intro_cash")).text, "Checks 3-day benefits");
  assert.equal(T.askedChip(c.asked[0]).text, "Needed for any estimate");
  assert.equal(T.askedChip({ kind: "confirm" }).text, "Repeated back to confirm a key number");
  assert.equal(T.askedChip({ kind: "band" }).text, "Asked for a range — the exact amount wasn't known");
  assert.equal(T.askedChip({ kind: "reprompt" }).text, "Asked again in a simpler form");
  assert.equal(T.skippedChip(c.skipped[0]).text, "Not asked — heating or cooling bill, same estimate either way");
  assert.equal(T.skippedChip({ slot: "x", reason: "hard_stop" }), null);
  assert.equal(T.skippedChip({ slot: "x", reason: "max_questions", detail: "Not asked — question limit; see the yellow line" }).maxQuestions, true);
  assert.equal(T.nowAskingChip("flip.rent_paid_by_others", "could change the estimate by $151: $155 or $306").text,
    "Why this question? Could change the estimate by $151: $155 or $306");
  assert.equal(T.nowAskingChip("expedited.intro_cash", null).text, "Checks 3-day benefits");
  assert.equal(T.NEVER_ASKED, "Never asked — Social Security number · immigration status");
  assert.deepEqual(T.answeredBeforeAsked(c), []);
  assert.equal(T.askedCounter({ asked_count: 7, skipped_count: 2 }), "Asked 7 · Not asked 2 (wouldn't change the result)");
});

test("lock, effect and status wording (A3.6, A3.7)", () => {
  assert.equal(T.lockReason(1), "Check 1 line first");
  assert.equal(T.lockReason(2), "Check 2 lines first");
  assert.equal(T.LOCK_LIVE, "Available after the call ends");
  assert.equal(T.effectText({ kind: "amount", delta_usd: 40 }), "Could change the estimate by $40");
  assert.equal(T.effectText({ kind: "tier" }), "Could change the result to Coordinator check");
  assert.equal(T.effectText({ kind: "expedited" }), "Could change 3-day benefits");
  assert.equal(T.STATUS_LABELS.interview_scheduled, "Interview set");
  assert.equal(T.reasonLabel("coordinator.parent_household"), "Under 22, lives with a parent");
  assert.equal(T.CONFLICT_TOAST, "This case changed — showing the latest.");
});

test("amounts, first month, rules pill, durations", () => {
  const c = fixture("case_maria.json").case;
  assert.equal(T.firstMonthText(c.first_month), "If filed now (estimate): counts from Fri, Oct 2 — about $296 for October");
  assert.equal(T.rulesPill(meta.rules), "Rules FY2027 · in effect Oct 1, 2026");
  assert.equal(T.callDuration(c), "1:52");
  assert.equal(T.minSec(72000, true), "01:12");
  assert.deepEqual(T.estimateParts(306, false), { prefix: "", amount: "$306", suffix: "a month", spoken: "306 dollars a month" });
  assert.equal(T.estimateParts(25, true).prefix, "at least about");
  assert.equal(T.expeditedChip("yes"), "3-day benefits possible");
  assert.equal(T.expeditedChip("maybe"), "3-day benefits: maybe");
  assert.equal(T.expeditedChip("no"), null);
  assert.equal(T.rangeLabel({ lo: 155, hi: 306, settled: false }), "Between $155 and $306 a month");
  assert.equal(T.rangeLabel({ lo: 306, hi: 306, settled: true }), "$306 a month");
  assert.equal(T.rangeLabel(null), "Estimate appears after income and rent");
  assert.equal(T.answersKept(13), "Conversation cleared — not saved. 13 answers kept.");
  assert.equal(T.filledCount(c), 13);
});

test("deadline countdown chips (A3.9)", () => {
  const now = new Date("2026-10-02T17:00:00Z");
  assert.deepEqual(T.countdown("2026-10-31", now), { text: "29 days left", level: "neutral" });
  assert.deepEqual(T.countdown("2026-10-07", now), { text: "5 days left", level: "soon" });
  assert.deepEqual(T.countdown("2026-10-04", now), { text: "Due in 2 days", level: "urgent" });
  assert.deepEqual(T.countdown("2026-10-02", now), { text: "Due today", level: "urgent" });
  assert.equal(T.countdown(null), null);
});

test("coordinator edits are encoded without floats", () => {
  assert.equal(T.encodeEdit("money", "$1,100"), "1100.00");
  assert.equal(T.encodeEdit("money", "1100.5"), "1100.50");
  assert.equal(T.encodeEdit("money", " 900 "), "900.00");
  assert.equal(T.encodeEdit("money", "abc"), null);
  assert.equal(T.encodeEdit("money", "-5"), null);
  assert.equal(T.encodeEdit("int", "12"), "12");
  assert.equal(T.encodeEdit("int", "1.5"), null);
  assert.equal(T.encodeEdit("bool", "true"), "true");
  assert.equal(T.encodeEdit("bool", "maybe"), null);
  assert.equal(T.canonicalDisplay("900.00", "money"), "$900");
  assert.equal(T.canonicalDisplay("false", "bool"), "No");
});

test("short source titles keep the first clause and the date", () => {
  assert.equal(T.shortTitle("CDSS All County Information Notice I-40-26: CalFresh cost-of-living adjustments"),
    "CDSS All County Information Notice I-40-26");
  assert.equal(T.shortTitle("Muni fares ($2.85 adult Clipper)"), "Muni fares");
  assert.equal(T.shortTitle("CPUC: California LifeLine vs federal Lifeline ($19 + $9.25)"), "CPUC: California LifeLine vs federal Lifeline");
  assert.equal(T.sourceText("ACL-26-25", meta.rules.sources, { short: true }), "CDSS All County Letter 26-25, 2026-04-13");
  assert.equal(T.sourceText("nope", meta.rules.sources), "nope");
});

test("tracking inputs are Pacific wall time", () => {
  assert.equal(T.ptLocalToIso("2026-10-05T10:00"), "2026-10-05T17:00:00Z");
  assert.equal(T.ptLocalToIso("2026-12-01T10:00"), "2026-12-01T18:00:00Z");
  assert.equal(T.isoToPtLocal("2026-10-01T17:00:00Z"), "2026-10-01T10:00");
  assert.equal(T.ptLocalToIso("nope"), null);
});

// Every file under web/console: no forbidden phrase (UI_SPEC A9 item 6), and every literal icon id exists.
function walk(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = path.join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

test("no forbidden phrase anywhere in the console's files", () => {
  const words = [/\bnot eligible\b/i, /\bineligible\b/i, /\bdon'?t qualify\b/i, /\bdenied\b/i, /\bno califica\b/i, /\bno eres elegible\b/i];
  for (const file of walk(here).filter((f) => /\.(js|css|html)$/.test(f))) {
    const text = readFileSync(file, "utf8");
    for (const w of words) assert.equal(w.test(text), false, `${path.basename(file)} matches ${w}`);
  }
});

test("every icon the console names is in the sprite", () => {
  const sprite = readFileSync(path.join(here, "..", "shared", "icons.svg"), "utf8");
  const ids = new Set([...sprite.matchAll(/<symbol id="([^"]+)"/g)].map((m) => m[1]));
  const used = new Set();
  for (const file of walk(here).filter((f) => /\.(js|html)$/.test(f) && !f.endsWith(".test.mjs"))) {
    const text = readFileSync(file, "utf8");
    for (const m of text.matchAll(/["'#]((?:i|gp)-[a-z-]+[a-z])["']?/g)) if (/^(i-[a-z]|gp-logo)/.test(m[1])) used.add(m[1]);
  }
  assert.ok(used.size > 20);
  for (const id of used) assert.ok(ids.has(id), `icon ${id} is missing from icons.svg`);
});
