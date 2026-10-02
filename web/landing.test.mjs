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
const json = (path) => JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));
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
  // The button can wrap its words, never the number: the view hands the number over on its own.
  assert.equal(landingView(info("(415) 338-1203"), "es").phone.number, "(415) 338-1203");
  assert.ok(es.phone.text.includes(es.phone.number));
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
  assert.deepEqual(ids, ["gap", "how", "care", "programs", "spanish", "try"]);
  const nos = [...html.matchAll(/<span class="pitch__no num">(\d+)<\/span>/g)].map((m) => m[1]);
  assert.deepEqual(nos, ["01", "02", "03", "04", "05", "06"]);
  assert.deepEqual(sentenceLines(LANDING_STRINGS.en["how.title"]),
    ["The AI understands and plans.", "Rules do the math.", "A person confirms."]);
  assert.deepEqual(sentenceLines("CalFresh is the key."), ["CalFresh is the key."]);
  // D7: the old 03 ("why the AI is essential") is gone, words and keys alike.
  assert.ok(!html.includes('id="why"'));
  for (const lang of ["en", "es"]) {
    for (const [key, value] of Object.entries(LANDING_STRINGS[lang])) {
      assert.ok(!/^(?:why|edge)\./.test(key), `${lang} ${key}`);
      assert.doesNotMatch(value, /chatbot|phone tree|men[uú] telef[oó]nico/i, `${lang} ${key}`);
    }
  }
});

test("hero: the big number is up to $12.7M a year, with a caption that matches 01 and links to it", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const hero = html.slice(html.indexOf('<section class="hero'), html.indexOf('<section id="gap"'));
  const big = hero.slice(hero.indexOf('<div class="numeral">'), hero.indexOf('<div class="hero__copy">'));
  assert.match(big, /<span class="numeral__cur">\$<\/span>12\.7M<\/span>/);
  assert.doesNotMatch(big, /306|a month|al mes/);
  assert.match(big, /href="#gap"/);
  const en = LANDING_STRINGS.en, es = LANDING_STRINGS.es;
  // The total is the school's, not one student's: the label over the figure says so.
  assert.equal(en["hero.upto"], "SF State students together: up to");
  assert.match(es["hero.upto"], /^Entre todos los estudiantes de SF State: hasta$/);
  assert.equal(en["hero.year"], en["gap.year"]);
  assert.equal(es["hero.year"], es["gap.year"]);
  assert.match(en["hero.fig"], /^Up to \$12\.7 million a year$/);
  assert.match(es["hero.fig"], /^Hasta \$12\.7 millones al año$/);
  for (const s of [en, es]) {
    assert.match(s["hero.cap"], /CalFresh/);
    assert.match(s["hero.cap"], /3,450/);        // the same students as 01's title
    assert.match(s["gap.money"], /\$12\.7/);     // and the same dollars as 01's lead
  }
  // The first screen names the AI and links to 02, where the pipeline is.
  assert.match(hero, /<p class="hero__ai">[\s\S]*data-t="hero\.ai"[\s\S]*href="#how" data-t="hero\.ai\.link"/);
  assert.equal(en["hero.ai"], "The AI understands and plans; rules do the math; a person confirms.");
  assert.equal(es["hero.ai.tag"], "IA");
});

test("02 pipeline: seven numbered steps, the two AI steps (language model, AI · Planner) on the accent", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const how = html.slice(html.indexOf('<section id="how"'), html.indexOf('<section id="care"'));
  const steps = [...how.matchAll(/<li class="flow__step( flow__step--ai)?">\s*<div class="flow__top"><span class="flow__no num" aria-hidden="true">(\d)<\/span> <p class="flow__chip" data-t="how\.chip\.(\w+)"/g)];
  assert.deepEqual(steps.map((m) => m[2]), ["1", "2", "3", "4", "5", "6", "7"]);
  assert.deepEqual(steps.filter((m) => m[1]).map((m) => m[2]), ["2", "5"]);
  assert.deepEqual(steps.map((m) => m[3]), ["student", "lm", "code", "code", "planner", "person", "student"]);
  for (let i = 1; i <= 7; i++) for (const k of ["h", "p", "ai"]) assert.ok(how.includes(`data-t="how.${i}.${k}"`), `step ${i} ${k}`);
  assert.equal(LANDING_STRINGS.en["how.chip.planner"], "AI · Planner");
  assert.equal(LANDING_STRINGS.es["how.chip.planner"], "IA · Planificador");
  assert.equal(LANDING_STRINGS.en["how.chip.lm"], "AI · Language model");
  assert.ok(how.includes('data-t="how.loop"'), "the loop (steps 1-5) is stated in words");
  // The planner, as data/rules/ca_fy2027.json "voi" runs it: a value-of-information search over the optional
  // questions only, at most max_questions, re-planned after each answer; core questions keep their fixed order.
  const voi = json("../data/rules/ca_fy2027.json").voi;
  assert.equal(voi.flip_threshold_usd, 50);
  assert.equal(voi.max_questions, 2);
  assert.equal(voi.replan_after_each_answer, true);
  const en = LANDING_STRINGS.en, es = LANDING_STRINGS.es;
  for (const s of [en, es]) assert.match(s["how.5.ai"], /\$50/);
  assert.match(en["how.5.p"], /^Before each optional question, .*value-of-information search\. Core questions follow a fixed order\.$/);
  assert.match(en["how.5.ai"], /at most two, starting with the most decisive/);
  assert.match(es["how.5.ai"], /como máximo dos/);
  assert.match(en["how.loop"], /After every answer, the planner re-plans/);
  // Noise is set aside by code before the model (gatorplate/extract/noise.py: "makes no model call"), so the AI step
  // does not claim it; disagreements are marked unsure (gatorplate/extract/merge.py), not always asked again.
  for (const s of [en, es]) assert.doesNotMatch(s["how.2.ai"], /noise|ruido/i);
  assert.match(en["how.1.p"], /Code sets noise .* aside before the AI sees them/);
  assert.match(en["how.1.ai"], /^Speech recognition \(AI\)/);
  assert.match(en["how.3.p"], /marked unsure for a person to check/);
  for (const i of [4, 7]) assert.match(en[`how.${i}.ai`], /^None, by design: /);
});

// Two real turns of Maria's demo call (tests/e2e/scripts/maria_g1.json), traced: her words, the two facts the AI fills
// with her quotes, the planner's one question ($151: $155 or $306) in the sentence bank's words, the two it skips.
test("02 traced example: Maria's turns, facts, quotes and the planner's question match the demo script", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const how = html.slice(html.indexOf('<section id="how"'), html.indexOf('<section id="care"'));
  const trace = how.slice(how.indexOf('<figure class="trace"'), how.indexOf("</figure>"));
  assert.ok(trace.length > 0 && how.indexOf('<figure class="trace"') < how.indexOf('<div class="perf"'));
  assert.equal([...trace.matchAll(/<li class="trace__step( trace__step--ai)?">/g)].length, 5);
  assert.equal([...trace.matchAll(/trace__step--ai/g)].length, 2);
  const maria = json("../tests/e2e/scripts/maria_g1.json");
  const work = maria.turns.find((t) => t.user && t.user.startsWith("I work at the campus library"));
  assert.ok(trace.includes(`<p class="trace__say" lang="en">“${work.user}”</p>`));
  for (const o of work.fake_llm.observations) assert.ok(trace.includes(`<q class="trace__quote" lang="en">${o.quote}</q>`), o.quote);
  assert.deepEqual(work.case.slots, { earned_monthly: "900.00", other_cash_monthly: "0.00" });
  const rent = maria.turns.find((t) => t.user === "Eleven hundred.");
  assert.equal(rent.case.asked_last.reason, "could change the estimate by $151: $155 or $306");
  assert.deepEqual(maria.final.skipped.map((x) => x.slot), ["heat_cool", "other_utils"]);
  assert.equal(maria.final.estimate_monthly, 306);
  const en = LANDING_STRINGS.en, es = LANDING_STRINGS.es;
  assert.match(en["ex.2.a"], /\$900 a month/);
  assert.match(en["ex.2.b"], /\$0$/);
  for (const s of [en, es]) {
    assert.match(s["ex.4.p"], /Eleven hundred.*\$155 .*\$306 .*\$151/);
    assert.match(s["ex.5.p"], /\$306/);
  }
  for (const [lang, s] of [["en", en], ["es", es]]) {
    const bank = json(`../data/content/sentences.${lang}.json`);
    const find = (o) => (o && typeof o === "object" ? (o["flip.rent_paid_by_others"] || Object.values(o).map(find).find(Boolean)) : null);
    assert.equal(s["ex.4.q"].slice(1, -1), find(bank).all[0], lang);
  }
});

// Every number in the performance panel, as measured on 2026-10-02 (private/redesign/d7/METRICS.md):
// pytest 3,054 + node 176 (this tree; 171 before D7) = 3,230 -> "3,200+"; e2e 28/28 and adversarial 38/38
// (var/reports/e2e-*-local-20261002T2050*Z.md);
// golden 78/78 (tests/rules/test_golden.py) and 14/14 (tests/programs/test_golden.py); real-model noisy runs 24/24 with
// 1 wrong value stored and 0 in a result, 3 of 113 model timeouts (robust runs d5v + d5rb); Maria: 7 questions, 12 answers,
// 37 answer fields (tests/e2e/scripts/maria_g1.json, contracts/slots.py), 2 skipped, 1 asked at $151; 5.9 questions over
// 59 simulated calls (tools/simulate_student.py, scripted, fake model, re-run 2026-10-02 21:59Z: 59/59 tiers, English
// 48/48, Spanish 11/11); model step median 1.53 s (n = 32), rest of the turn about 5 ms (n = 72).
test("02 performance panel: the measured numbers, each with how it was measured, labeled simulated / text-level", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const how = html.slice(html.indexOf('<section id="how"'), html.indexOf('<section id="care"'));
  const nums = [...how.matchAll(/<p class="perf__num num">([^<]*)(?:<span class="perf__unit">([^<]*)<\/span>)?<\/p>/g)]
    .map((m) => m[1] + (m[2] || ""));
  assert.deepEqual(nums, ["24/24", "0", "100%", "3,200+", "78/78", "7", "≈1.5 s"]);
  for (const k of ["robust", "wrong", "ground", "tests", "rules", "q", "speed"]) {
    for (const part of ["l", "how"]) assert.ok(how.includes(`data-t="perf.${k}.${part}"`), `${k}.${part}`);
  }
  for (const [lang, s] of Object.entries(LANDING_STRINGS)) {
    assert.match(s["perf.date"], lang === "en" ? /Oct 2, 2026.*simulated students, text-level/ : /2 de octubre de 2026.*simulados, solo texto/);
    assert.match(s["perf.robust.how"], /^24 /);
    assert.match(s["perf.robust.how"], /15 .*3 .*Maria/);
    assert.match(s["perf.robust.how"], /3 .*113/);
    assert.match(s["perf.wrong.how"], /\$9/);
    assert.match(s["perf.tests.how"], /^3,054 .*176 /);
    assert.match(s["perf.tests.how"], /28\/28 .*38\/38 /);
    assert.equal(3054 + 176 >= 3200, true);
    assert.match(s["perf.rules.how"], /14\/14/);
    assert.match(s["perf.q.l"], /Maria.*37/);
    assert.match(s["perf.q.how"], /12 .*2 .*1 .*\$151.*59 .*5\.9/);
    assert.match(s["perf.speed.how"], /n = 32 .*5 ms .*\(n = 72\)/);
    // The unreproduced "4,000 random fact sets, 0 mismatches" is not on the page.
    for (const [key, value] of Object.entries(s)) assert.doesNotMatch(value, /4,000|al azar|random/i, `${lang} ${key}`);
  }
});

test("03 responsible: a laws & standards table (10 rows) and a risks table (10 rows), real tables with headers", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const care = html.slice(html.indexOf('<section id="care"'), html.indexOf('<section id="programs"'));
  const law = care.slice(care.indexOf('<table class="tbl tbl--law"'), care.indexOf("</table>") + 8);
  const risk = care.slice(care.indexOf('<table class="tbl tbl--risk"'));
  assert.equal([...law.matchAll(/<tr class="tbl__row" role="row">/g)].length, 10);
  assert.equal([...risk.matchAll(/<tr class="tbl__row" role="row">/g)].length, 10);
  assert.equal([...law.matchAll(/<th scope="col"/g)].length, 4);
  assert.equal([...risk.matchAll(/<th scope="col"/g)].length, 4);
  for (let i = 1; i <= 10; i++) {
    for (const k of ["h", "cite", "req", "do", "status"]) assert.ok(law.includes(`data-t="law.${i}.${k}"`), `law ${i} ${k}`);
    for (const k of ["h", "how", "ev", "open"]) assert.ok(risk.includes(`data-t="risk.${i}.${k}"`), `risk ${i} ${k}`);
  }
  // Each citation links to the law's text (official code sites or Cornell LII), read on 2026-10-02.
  const cites = [...law.matchAll(/<a class="tbl__cite" href="([^"]+)" rel="noopener" data-t="law\.(\d+)\.cite">/g)];
  assert.equal(cites.length, 10);
  for (const m of cites) assert.match(m[1], /^https:\/\/(?:leginfo\.legislature\.ca\.gov|www\.law\.cornell\.edu)\//);
  assert.match(LANDING_STRINGS.en["law.checked"], /^Sources read Oct 2, 2026\./);
  // Under 64em each table row is a details card (name + badge in the summary); the same keys, the same order.
  const lawCards = care.slice(care.indexOf('<ul class="tcards" role="list" aria-labelledby="law-title">'), care.indexOf('<div class="tblock"', care.indexOf("law-title")));
  const riskCards = care.slice(care.indexOf('<ul class="tcards" role="list" aria-labelledby="risk-title">'));
  assert.equal([...lawCards.matchAll(/<details class="tcard">/g)].length, 10);
  assert.equal([...riskCards.matchAll(/<details class="tcard">/g)].length, 10);
  for (let i = 1; i <= 10; i++) {
    for (const k of ["h", "req", "do", "status"]) assert.ok(lawCards.includes(`data-t="law.${i}.${k}"`), `card law ${i} ${k}`);
    for (const k of ["h", "how", "ev", "open"]) assert.ok(riskCards.includes(`data-t="risk.${i}.${k}"`), `card risk ${i} ${k}`);
  }
  assert.deepEqual([...lawCards.matchAll(/class="badge badge--(\w+)"/g)].map((m) => m[1]),
    [...law.matchAll(/class="badge badge--(\w+)"/g)].map((m) => m[1]));
  // Status is one of three worded badges, never a claim of meeting a law.
  const badges = [...law.matchAll(/class="badge badge--(\w+)" data-t="law\.badge\.(\w+)"/g)];
  assert.equal(badges.length, 10);
  for (const m of badges) assert.equal(m[1], m[2]);
  assert.deepEqual([...new Set(badges.map((m) => m[1]))].sort(), ["design", "pilot", "scope"]);
  const en = LANDING_STRINGS.en;
  for (const [i, name] of [[1, "Invasion of Privacy"], [3, "CCPA"], [5, "FERPA"], [6, "TCPA"], [8, "Accessibility"], [9, "HIPAA"]]) {
    assert.match(en[`law.${i}.h`], new RegExp(name));
  }
  assert.match(en["law.1.cite"], /§631, §632/);
  assert.match(en["law.7.cite"], /89005\.5/);
  assert.match(en["law.8.do"], /117 color pairs/);    // tools/check_contrast.py on 2026-10-02
  assert.match(en["law.8.cite"], /Apr\. 26, 2027/);    // DOJ interim final rule, 91 FR 20902 (2026-04-20)
  assert.match(en["risk.4.ev"], /78\/78.*14\/14/);
  assert.match(en["risk.5.ev"], /48\/48.*11\/11.*1 real-model Spanish run/);
  // One format for evidence; a declined call keeps no answers (tests/dialogue/test_flows.py), not "nothing".
  for (let i = 1; i <= 10; i++) assert.match(en[`risk.${i}.ev`], /^(?:Tests|Scripts|Runs): /, `risk ${i}`);
  assert.match(en["risk.1.ev"], /a declined call keeps no answers — only that it was declined/);
  assert.match(en["law.8.status"], /TTY/);
  for (const s of [LANDING_STRINGS.en, LANDING_STRINGS.es]) {
    assert.match(s["care.note"], /simulated|simulados/);
    assert.match(s["care.sub"], /legal advice|asesoría legal/);
    for (const [key, value] of Object.entries(s)) {
      assert.doesNotMatch(value, /18\/24|3\/24|4,042/, key);   // earlier-build numbers stay off the page
      assert.doesNotMatch(value, /native speaker reviewed|hispanohablante nativa revis/i, key);
      assert.doesNotMatch(value, /stores nothing|no guarda nada|guiones adversarios|a\d\d_\w+/i, key);
    }
  }
});

test("05 English and Spanish: the Census and SF State figures, sourced, and the channel truth", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const bi = html.slice(html.indexOf('<section id="spanish"'), html.indexOf('<section id="try"'));
  const figs = [...bi.matchAll(/<p class="bi__num num">([^<]+)<\/p>/g)].map((m) => m[1]);
  assert.deepEqual(figs, ["5.7%", "63.7%", "38.7%"]);
  // ACS 2024 1-year DP02 (retrieved 2026-10-02): US 18,432,221 / 321,745,943 = 5.7%; of 28,918,748 with limited
  // English, 63.7% speak Spanish; California 4,234,066 = 11.3%. SF State Fall 2025: 8,015 of 20,721 Latinx = 38.7%.
  assert.equal((18432221 / 321745943 * 100).toFixed(1), "5.7");
  assert.equal((18432221 / 28918748 * 100).toFixed(1), "63.7");
  assert.equal((8015 / 20721 * 100).toFixed(1), "38.7");
  assert.equal(17607 + 3114, 20721);   // the same enrollment as 01
  assert.equal(LANDING_STRINGS.en["bi.kicker"], "English and Spanish");
  assert.equal(LANDING_STRINGS.es["bi.kicker"], "Inglés y español");
  for (const s of [LANDING_STRINGS.en, LANDING_STRINGS.es]) {
    assert.match(s["bi.1"], /18\.4/);
    assert.match(s["bi.ca"], /4\.2 .*11\.3%/);
    assert.match(s["bi.src1"], /2024.*DP02.*18,432,221.*321,745,943.*28,918,748.*4,234,066/);
    assert.match(s["bi.src2"], /8,015 .*20,721/);
    assert.match(s["bi.close"], /(?:phone line is in English|línea telefónica es en inglés)/);
    assert.match(s["bi.parity"], /48\/48.*11\/11/);
    assert.match(s["bi.snap"], /7 CFR 272\.4\(b\)/);
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

test("pitch wording does not overclaim (no 'nothing is recorded', 'anonymous', 'first', 'every benefit', 'compliant', 'legal' as a claim, 'more than double', error rates)", () => {
  const bad = { en: [/nothing is recorded/i, /anonym/i, /\bfirst\b/i, /every benefit/i, /error rate/i, /\d+% (?:fewer|less|more accurate)/i,
    /complian/i, /silent error/i, /\bsecure\b/i, /more than double/i, /\b(?:is|are|fully|100%) legal\b/i, /\bguarantee/i],
    es: [/nada se graba/i, /an[oó]nim/i, /\bprimer[oa]?\b/i, /todos los beneficios/i, /tasa de error/i, /cumple con/i, /cumplimiento/i, /errores silenciosos/i, /m[aá]s del doble/i, /garantiz/i] };
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
  assert.equal(v.aboutHref, "#how");   // 02 and 03 on this page
  assert.equal(v.consoleHref, "/console");
  const f = landingView(null, "en", { fixtures: true });
  assert.equal(f.talkHref, "/talk/?fixtures=1&lang=en");
  assert.equal(f.aboutHref, "#how");
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
