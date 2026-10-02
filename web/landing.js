// Landing page (docs/UI_SPEC.md A7.2): the first screen, then six pitch sections to scroll (the gap at SF State, how
// it works with measured performance, responsible by design (laws and risks), six programs, English and Spanish, try
// it), English and Spanish. The demo phone number comes from
// GET /api/public/info and shows only when it is set; then the call button comes first and is the filled one. The view
// is a pure function (tested with node); the page part runs only in a browser.

import { fill } from "./shared/i18n.js";
import { telHref } from "./shared/format.js";

export const LANDING_STRINGS = {
  en: {
    title: "GatorPlate",
    headline_phone: "Check the money you may be missing — by phone or in your browser.",
    headline_web: "Check the money you may be missing — in your browser.",
    sub: "SF State students: CalFresh pays one person up to $306 a month for groceries, and it can open more help. A few minutes. Free. Estimates only — each agency decides.",
    talk: "Talk in your browser",
    call: "Call {number}",
    phone_note: "",
    about: "How it works and responsible AI",
    console: "For coordinators",
    "trust.label": "Privacy and limits",
    "trust.recorded": "Audio isn't recorded",
    "trust.ssn": "Never asks for your Social Security number or immigration status",
    "trust.estimate": "Estimates only — each agency decides",
    "more.label": "More about GatorPlate",
    prototype: "Student-built prototype — not an official SF State, county, or CalFresh service.",
    skip: "Skip to main content",
    "lang.label": "Language",
    // The pitch sections under the first screen (A7.2): the gap, how it works (the seven-step pipeline and the
    // performance panel, every number measured on 2026-10-02 — see web/landing.test.mjs), responsibility (laws and
    // standards, risks), six programs, English and Spanish (U.S. Census ACS 2024 1-year, DP02), try it.
    "gap.kicker": "The gap at SF State",
    "gap.title": "About 3,450 SF State students likely qualify for CalFresh and aren't getting it.",
    "gap.about": "about",
    "gap.students": "students",
    "gap.upto": "up to",
    "gap.year": "a year",
    "gap.money": "Up to $12.7 million a year in food money — CalFresh alone, at the one-person maximum.",
    "gap.eligible": "≈6,030 likely eligible",
    "gap.receiving": "≈2,580 already receive it",
    "gap.missing": "≈3,450 not yet",
    "gap.method": "Estimate based on UC eligibility research applied to SF State enrollment: 33% of UC undergraduates and 7% of UC graduate students were eligible for CalFresh (California Policy Lab, Fall 2019 data, published Aug 2024), applied to SF State's 17,607 undergraduates and 3,114 graduate students (Fall 2025), minus the 14.3% of SF State undergraduates who already received CalFresh in 2023–24 (California Policy Lab, Aug 2026) and graduate students at the UC rate. \"Up to\" assumes the $306 one-person maximum for 12 months; the average benefit is lower.",
    "gap.sources": "Sources",
    "gap.src1": "Enrollment: 17,607 undergraduates and 3,114 graduate students, Fall 2025 (SF State Facts).",
    "gap.src2": "Eligible: 33% of UC undergraduates and 7% of UC graduate students, Fall 2019 (California Policy Lab, \"Filling the Gap,\" Aug 2024) → ≈6,030 at SF State.",
    "gap.src3": "Already receiving: 14.3% of SF State undergraduates, 2023–24 (California Policy Lab, Aug 2026); graduate students at the UC rate of 27% of those eligible → ≈2,580.",
    "gap.src4": "Up to $306/month: CalFresh maximum for one person from Oct 1, 2026 (CDSS ACIN I-40-26).",
    "gap.src5": "Average is lower: participating UC undergraduates averaged $161/month when the maximum was $194 (California Policy Lab, Feb 2025) — about $10.5M/yr at that ratio.",
    "gap.src6": "Graduate students are estimated with UC rates (7% eligible, 27% of them receiving). SF State's own data show 13.6% of graduate students already receive CalFresh — higher than this method assumes — so the ~160 graduate students in this estimate are the least certain part.",
    "gap.src7": "Likely conservative: since June 1, 2026, half-time CSU bachelor's students meet the student rule (CDSS ACL 26-25); the 2019 rate predates this.",
    "hero.upto": "SF State students together: up to",
    "hero.year": "a year",
    "hero.fig": "Up to $12.7 million a year",
    "hero.cap": "in CalFresh that about 3,450 SF State students may be missing, at the one-person maximum.",
    "hero.link": "How we estimate it",
    "hero.ai.tag": "AI",
    "hero.ai": "The AI understands and plans; rules do the math; a person confirms.",
    "hero.ai.link": "How it works",
    "how.kicker": "How it works",
    "how.title": "The AI understands and plans. Rules do the math. A person confirms.",
    "how.lede": "A short conversation instead of a screening form. Two AI steps sit at the center: a language model that understands free speech, and a planner that decides what to ask next.",
    "how.legend": "Highlighted: the two AI steps",
    "how.list": "The pipeline, step by step",
    "how.chip.student": "Student",
    "how.chip.lm": "AI · Language model",
    "how.chip.planner": "AI · Planner",
    "how.chip.code": "Code",
    "how.chip.person": "Person",
    "how.ai.tag": "AI's part",
    "how.1.h": "You talk",
    "how.1.p": "By phone (English) or in your browser (English or Spanish). GatorPlate gets text, never audio. Code sets noise and line checks (“hello?”) aside before the AI sees them.",
    "how.1.ai": "Speech recognition (AI) turns your voice into text; GatorPlate gets text only.",
    "how.2.h": "Understands",
    "how.2.p": "Turns free speech — any wording, corrections, several answers at once — into the exact facts the rules need.",
    "how.2.ai": "Fills each fact with the student's own quote and flags what it isn't sure of.",
    "how.3.h": "Checked against your words",
    "how.3.p": "A rule parser reads every sentence too. If it disagrees with the AI on an amount, the answer is marked unsure for a person to check, and a key amount can be confirmed on the call.",
    "how.3.ai": "Its output is checked: a number the student never said is dropped.",
    "how.4.h": "Rules do the math",
    "how.4.p": "A dated CalFresh table (Oct 2026 – Sep 2027) computes every dollar, with a source for each step.",
    "how.4.ai": "None, by design: the AI never does the math.",
    "how.5.h": "Picks the next question",
    "how.5.p": "Before each optional question, it re-runs the rules for every candidate answer — a value-of-information search. Core questions follow a fixed order.",
    "how.5.ai": "Asks only if an answer could change the result or move the estimate by more than $50 a month — at most two, starting with the most decisive.",
    "how.6.h": "A person confirms",
    "how.6.p": "Uncertain answers become yellow lines; a case can't be marked reviewed until each is checked. The county decides.",
    "how.6.ai": "Its “unsure” flags are what the person checks.",
    "how.7.h": "Your card",
    "how.7.p": "The estimate, answers for the application, documents, interview prep — and other help CalFresh may open.",
    "how.7.ai": "None, by design: code builds the card from the rules result.",
    "how.loop": "Steps 1–5 repeat every turn. After every answer, the planner re-plans — until it moves on to the result.",
    "ex.title": "Two turns, traced",
    "ex.sub": "From Maria's demo call: a simulated student, text-level.",
    "ex.1.h": "She says",
    "ex.2.h": "AI · Language model fills",
    "ex.2.a": "Work income: $900 a month",
    "ex.2.b": "Cash from family: $0",
    "ex.3.h": "Code checks",
    "ex.3.p": "Each quote is in her words, and $900 was said: both kept. A number she never said would be dropped.",
    "ex.4.h": "AI · Planner asks",
    "ex.4.p": "Next, her rent: “Eleven hundred.” One open answer could make her estimate $155 or $306 — $151 apart — so it asks:",
    "ex.4.q": "“Does anyone, like a parent, pay part of your rent straight to your landlord?”",
    "ex.4.skip": "Heating or cooling and other utility bills couldn't change her result: not asked.",
    "ex.5.h": "Rules result",
    "ex.5.p": "“No.” → likely $306 a month. An estimate; the county decides.",
    "care.yl.tag": "To check",
    "care.yl.text": "Monthly rent — “around 800, I think”",
    "perf.title": "Performance",
    "perf.date": "Measured Oct 2, 2026 · simulated students, text-level",
    "perf.robust.l": "off-script and noisy calls with the real language model reached the right amount",
    "perf.robust.how": "24 runs: 15 variations of 3 simulated students (one in Spanish) plus the Maria demo script — noise on every turn, a TV in the room, cut-off words, corrections, several answers at once. 3 of 113 model calls timed out; the rule parser carried on and the amount was still right.",
    "perf.wrong.l": "wrong values reached a result",
    "perf.wrong.how": "Same 24 runs. One noisy word (“nine”) was saved as $9 but marked unsure, and the confirm question fixed it. No call was ended by noise.",
    "perf.ground.l": "of saved quotes are the student's own words",
    "perf.ground.how": "Enforced in code and tested: a quote not found in what was said turns the answer “unsure”; a number the student never said is dropped.",
    "perf.tests.l": "automated tests pass",
    "perf.tests.how": "3,054 Python and 176 JavaScript tests, with a stand-in for the language model. Plus 28/28 end-to-end and 38/38 adversarial scripts (prompt injection, a spoken Social Security number, a crisis in Spanish).",
    "perf.rules.l": "hand-computed CalFresh cases match the rules engine exactly",
    "perf.rules.how": "Every result field compared. The other programs: 14/14 hand-computed cases.",
    "perf.q.l": "questions in Maria's demo call, out of 37 answer fields",
    "perf.q.how": "They filled 12 answers. The planner skipped 2 that couldn't change her result and asked 1 that could move it by $151 a month. Average across 59 simulated calls: 5.9.",
    "perf.speed.l": "median for the AI to understand an answer (language-model step)",
    "perf.speed.how": "Local runs of the current code, n = 32 model calls. Rules, planner, sentences and checks add a median of about 5 ms per answer (n = 72). Phone and network time not included.",
    "care.kicker": "Responsible by design",
    "care.title": "The rules we designed around, and the risks we handle.",
    "care.sub": "A free student prototype that no lawyer has reviewed yet. These tables show how we read each rule, what GatorPlate does today, and what a real SF State pilot would still need. Not legal advice.",
    "law.title": "Laws & standards",
    "law.checked": "Sources read Oct 2, 2026. Each citation links to the law's text. Our reading, not legal advice.",
    "law.caption": "Laws and standards: what each requires, what GatorPlate does today, and its status",
    "law.col.law": "Law or standard",
    "law.col.req": "What it requires",
    "law.col.do": "What GatorPlate does today",
    "law.col.status": "Status",
    "law.badge.design": "Designed for it",
    "law.badge.scope": "Outside scope, as we read it",
    "law.badge.pilot": "Pilot: review needed",
    "law.1.h": "California Invasion of Privacy Act",
    "law.1.cite": "Penal Code §631, §632",
    "law.1.req": "Listening in on or recording a confidential call needs the consent of all parties.",
    "law.1.do": "Before any question, the call says it is a student-built AI, not an official SF State service, that an AI turns speech into text, and that the call audio isn't recorded. Then it asks: say yes or press one. A no, or two unclear answers, ends the call; only the fact that it was declined is kept.",
    "law.1.status": "Built for all-party consent. Pilot: legal review of the consent wording.",
    "law.2.h": "California bot disclosure",
    "law.2.cite": "Bus. & Prof. Code §17940–17941 (SB 1001)",
    "law.2.req": "An online bot may not hide that it is a bot to push a sale or sway a vote.",
    "law.2.do": "Says “AI” in its opening sentence, on the phone and on the web. “Are you a robot?”, “Is this recorded?” and “Is this official?” get a true answer at any point.",
    "law.2.status": "Nothing is sold and there is no vote. We disclose anyway.",
    "law.3.h": "CCPA / CPRA",
    "law.3.cite": "Civil Code §1798.100 ff.",
    "law.3.req": "Duties fall on for-profit businesses above a revenue or data-volume threshold.",
    "law.3.do": "No revenue, no ads, no data sales. Keeps answers with short quotes, not the conversation; never receives the caller's phone number; never asks for a name. Delete by voice (“delete my data”) or on the card.",
    "law.3.status": "Not a for-profit business. We follow its collect-less-and-delete ideas anyway.",
    "law.4.h": "CalFresh confidentiality",
    "law.4.cite": "Welf. & Inst. Code §10850; 7 CFR 272.1(c)",
    "law.4.req": "Agencies running CalFresh must keep applicant and recipient records confidential and use them only for the program.",
    "law.4.do": "Receives no county or state records and sends nothing to the county. Keeps no list of recipients. Students apply on BenefitsCal themselves.",
    "law.4.status": "An agency rule; we hold no agency records. Sharing data with the county would need its own review.",
    "law.5.h": "FERPA",
    "law.5.cite": "20 U.S.C. §1232g; 34 CFR Part 99",
    "law.5.req": "Protects education records kept by a school or someone acting for it.",
    "law.5.do": "The pilot uses no student records, so it needs no student-records integration.",
    "law.5.status": "SF State's data and accessibility review comes before a pilot.",
    "law.6.h": "TCPA",
    "law.6.cite": "47 U.S.C. §227(b); FCC ruling, Feb. 8, 2024",
    "law.6.req": "Calls made with an artificial or prerecorded voice — AI voices included — need prior consent.",
    "law.6.do": "Only answers calls a student places. No outbound calls, texts or return calls: none are built, and the reply guard blocks promising them.",
    "law.6.status": "Inbound calls only.",
    "law.7.h": "CSU name use",
    "law.7.cite": "Education Code §89005.5",
    "law.7.req": "No one may use the CSU or a campus name to suggest affiliation or endorsement without the Trustees' permission.",
    "law.7.do": "Every call and web chat opens with “a student-built AI assistant, not an official SF State service.” This site says it is not an official SF State, county or CalFresh service. No SF State logos, seals or colors.",
    "law.7.status": "A factual description only. Any adoption starts with SF State's own review.",
    "law.8.h": "Accessibility",
    "law.8.cite": "ADA Title II web rule (DOJ 2024; WCAG 2.1 AA; larger public entities by Apr. 26, 2027) · WCAG 2.2 AA",
    "law.8.req": "A campus must offer web content and apps that people with disabilities can use.",
    "law.8.do": "The phone path needs no screen, app or login, and speaks the card code. Typing always works on the web. The card targets WCAG 2.2 AA: 117 color pairs checked (4.5:1 text, 3:1 interface), keyboard use, screen-reader labels, 200% zoom, reflow at 320 px.",
    "law.8.status": "WCAG 2.2 AA targeted, not audited. Pilot: SF State accessibility review. Calls from TTY users aren't specially handled yet.",
    "law.9.h": "HIPAA",
    "law.9.cite": "45 CFR Parts 160, 164",
    "law.9.req": "Covers health plans, health-care clearinghouses and providers that bill electronically.",
    "law.9.do": "None of these. Medi-Cal appears only as a box on the same application. No health or disability details are stored.",
    "law.9.status": "Not a covered entity.",
    "law.10.h": "Truthful claims",
    "law.10.cite": "FTC Act §5; Bus. & Prof. Code §17500",
    "law.10.req": "Claims must not mislead; “up to” must not read as what everyone gets.",
    "law.10.do": "Every amount says it is an estimate and the agency decides. Ceilings say “up to.” The $12.7M is an upper bound for CalFresh alone, with its method and sources on this page. A reply guard blocks promises of savings or payouts.",
    "law.10.status": "Wording rules are tested in code.",
    "risk.title": "Risks & how we handle them",
    "risk.caption": "Risks: how GatorPlate handles each, the evidence, and what is still open",
    "risk.col.risk": "Risk",
    "risk.col.how": "How we handle it",
    "risk.col.ev": "Evidence",
    "risk.col.open": "Still open",
    "risk.1.h": "Privacy",
    "risk.1.how": "Consent before questions. No audio stored, no full transcript, no caller number received. A case keeps answers with short quotes (80 characters at most). The language model sees only the current question and the last two sentences, with ID-like digits removed. Students can delete their case by voice or on the card.",
    "risk.1.ev": "Tests: a declined call keeps no answers — only that it was declined; “delete my data” removes the case.",
    "risk.1.open": "The consent wording has not been reviewed by a lawyer yet.",
    "risk.2.h": "Security",
    "risk.2.how": "The AI can't set a number. Phone requests are signed; the coordinator console needs a passcode; card links are unguessable and expire (7 days; spoken code 24 hours); requests are rate-limited; logs hold no conversation content; pages load nothing from third parties.",
    "risk.2.ev": "Tests: routes, logs, request signatures. Scripts: prompt injection.",
    "risk.2.open": "SF State's data review comes before a pilot.",
    "risk.3.h": "Accessibility",
    "risk.3.how": "Any phone, no app or login. The card code is spoken. Typing on the web. WCAG 2.2 AA targets on the card.",
    "risk.3.ev": "Tests: 117 color pairs pass the contrast check (Oct 2, 2026). Scripts: a question about TTY services is noted, never promised.",
    "risk.3.open": "No WCAG audit yet. Calls from TTY users aren't specially handled yet.",
    "risk.4.h": "Data accuracy",
    "risk.4.how": "One dated rules table (Oct 1, 2026 – Sep 30, 2027), each value with its source. No estimate outside those dates.",
    "risk.4.ev": "Tests: 78/78 hand-computed CalFresh cases and 14/14 other-program cases (Oct 2, 2026).",
    "risk.4.open": "A new table is needed from Oct 1, 2027.",
    "risk.5.h": "Bias & language",
    "risk.5.how": "One rules engine for English and Spanish; results reported per language. Spanish works on the web and on the card; the phone line is English.",
    "risk.5.ev": "Runs: simulated calls with a stand-in model, English 48/48 and Spanish 11/11 (Oct 2, 2026); 1 real-model Spanish run, right amount.",
    "risk.5.open": "Real accents and real speech recognition not tested yet. The phone line is English only.",
    "risk.6.h": "Over-reliance",
    "risk.6.how": "Every result is an estimate; GatorPlate never gives a “no” on eligibility. Uncertain answers become yellow lines, and the server won't mark a case reviewed until a person checks each one. It never applies or signs for anyone.",
    "risk.6.ev": "Tests: the review stays locked until every yellow line is checked. Scripts: asking for a “no”; asking it to apply.",
    "risk.6.open": "Not yet tried with real students or coordinators.",
    "risk.7.h": "Crisis",
    "risk.7.how": "A mention of self-harm, in English or Spanish, gets 988 and 911 at once, before anything else. The AI and word lists both listen, so it works even if the language model is down. Nothing from that sentence is quoted.",
    "risk.7.ev": "Tests: crisis words in both languages. Scripts: a crisis in English; a crisis in Spanish.",
    "risk.7.open": "With the model down, only the word lists listen; indirect wording can be missed.",
    "risk.8.h": "Immigration safety",
    "risk.8.how": "Never asks for a Social Security number or immigration status. A volunteered status isn't stored or kept as context; the student is pointed to the coordinator or legal aid. SSN- or card-like digits are removed before the AI sees the text.",
    "risk.8.ev": "Tests: digit redaction. Scripts: a spoken Social Security number; an immigration question.",
    "risk.8.open": "Tested with text scripts, not real speech.",
    "risk.9.h": "AI errors & invented numbers",
    "risk.9.how": "The model only fills answers. Each quote must appear in what the student said and each number must have been said — otherwise the answer is marked unsure or dropped. Amounts come from the rules table. Risky numbers (“fifteen or fifty?”) are read back. If the model is slow or down, a rule parser and closed questions carry on.",
    "risk.9.ev": "Tests: merge, model faults. Scripts: “fifteen hundred” read back. Runs: 24/24 real-model noisy runs (above).",
    "risk.9.open": "In those runs, 3 of 113 model calls timed out; the rule parser carried on.",
    "risk.10.h": "Noise & off-script speech",
    "risk.10.how": "Noise, a TV in the room or “hello?” is never saved or counted as an answer and makes no model call; the question is asked again. Side questions are noted for the coordinator. Long silence gets a closed question.",
    "risk.10.ev": "Tests: noise turns. Scripts: three silences; a side question; mixed English and Spanish.",
    "risk.10.open": "Real phone lines and speech recognition not tested yet.",
    "care.note": "Tested with simulated students and scripts, not real students or real speech recognition. Not an official SF State, county or CalFresh service. Not legal advice.",
    "bi.kicker": "English and Spanish",
    "bi.title": "Why Spanish, too.",
    "bi.1": "of people in the U.S. age 5 and up — 18.4 million — speak Spanish at home and English less than “very well.”",
    "bi.2": "of people in the U.S. who speak English less than “very well” speak Spanish at home.",
    "bi.3": "of SF State students are Latinx (Fall 2025). SF State is a Hispanic-Serving Institution.",
    "bi.ca": "In California, 4.2 million people (11.3%) speak Spanish at home and English less than “very well.”",
    "bi.close": "So you can talk or type in Spanish in your browser, and your card comes in Spanish. The phone line is in English.",
    "bi.parity": "Same rules engine in both languages: 48/48 English and 11/11 Spanish simulated calls got the expected result (stand-in model, text-level).",
    "bi.snap": "Federal SNAP rules require materials — and, in larger offices, bilingual staff or interpreters — in a language spoken by enough local households (7 CFR 272.4(b)).",
    "bi.sources": "Sources",
    "bi.src1": "U.S. Census Bureau, American Community Survey 2024 (1-year), table DP02: 18,432,221 of 321,745,943 people age 5+ (5.7%); 63.7% of the 28,918,748 who speak English less than “very well”; California 4,234,066 (11.3%).",
    "bi.src2": "SF State Facts, Fall 2025 enrollment: 8,015 of 20,721 students. SF State News, Oct. 11, 2022 (Hispanic-Serving Institution).",
    "bi.src3": "7 CFR 272.4(b)(2)–(3). All retrieved Oct. 2, 2026.",
    "prog.kicker": "Six programs",
    "prog.sofar": "The numbers above count CalFresh alone.",
    "prog.title": "CalFresh is the key.",
    "prog.sub": "It can open more help this year: Medi-Cal, Clipper START, PG&E CARE, California LifeLine and tax credits.",
    "prog.tax": "Tax credits",
    "prog.check": "We check six programs. For Maria, four save money, one is health coverage, and one is a maybe at tax time.",
    "prog.who": "Maria, a sample student from our demo",
    "prog.alone": "CalFresh alone",
    "prog.upto": "up to about",
    "prog.transit": "Clipper START — transit",
    "prog.phone": "California LifeLine — phone",
    "prog.phone.amt": "up to $220",
    "prog.energy": "PG&E CARE — energy",
    "prog.total": "Total a year, up to about",
    "prog.coverage": "+ health coverage",
    "prog.maybe": "maybe $200 — not counted",
    "prog.note": "Estimates from dated tables, computed by code, not by the AI. Each agency decides.",
    "try.kicker": "Try it",
    "try.title": "Check the money you may be missing.",
    "try.sub_phone": "A few minutes. Free. Call in English, or talk in your browser in English or Spanish.",
    "try.sub_web": "A few minutes. Free. Talk in your browser in English or Spanish.",
  },
  es: {
    title: "GatorPlate",
    headline_phone: "¡Revisa el dinero que quizá te falta reclamar, por teléfono o en tu navegador!",
    headline_web: "Revisa el dinero que quizá te falta reclamar en tu navegador.",
    sub: "Estudiantes de SF State: CalFresh da hasta $306 al mes a una persona para comida, y puede abrir más ayudas. Unos minutos. Gratis. Solo son estimados: cada agencia decide.",
    talk: "Habla en tu navegador",
    call: "Llama al {number}",
    phone_note: "La línea telefónica es solo en inglés.",
    about: "Cómo funciona y uso responsable de la IA",
    console: "Para la coordinación (en inglés)",
    "trust.label": "Privacidad y límites",
    "trust.recorded": "No se graba el audio",
    "trust.ssn": "Nunca te pide tu número de Seguro Social ni tu estatus migratorio",
    "trust.estimate": "Solo son estimados: cada agencia decide",
    "more.label": "Más sobre GatorPlate",
    prototype: "Prototipo hecho por estudiantes; no es un servicio oficial de SF State, del condado ni de CalFresh.",
    skip: "Ir al contenido",
    "lang.label": "Idioma",
    "gap.kicker": "La brecha en SF State",
    "gap.title": "Unos 3,450 estudiantes de SF State probablemente reúnen los requisitos de CalFresh y no lo reciben.",
    "gap.about": "unos",
    "gap.students": "estudiantes",
    "gap.upto": "hasta",
    "gap.year": "al año",
    "gap.money": "Hasta $12.7 millones al año en dinero para comida — solo CalFresh, con el máximo para una persona.",
    "gap.eligible": "≈6,030 probablemente elegibles",
    "gap.receiving": "≈2,580 ya lo reciben",
    "gap.missing": "≈3,450 todavía no",
    "gap.method": "Estimado basado en investigación sobre elegibilidad en la UC, aplicado a la matrícula de SF State: el 33% de los estudiantes de licenciatura y el 7% de los de posgrado de la UC eran elegibles para CalFresh (California Policy Lab, datos de otoño de 2019, publicado en agosto de 2024), aplicado a los 17,607 estudiantes de licenciatura y 3,114 de posgrado de SF State (otoño de 2025), menos el 14.3% de los estudiantes de licenciatura de SF State que ya recibieron CalFresh en 2023–24 (California Policy Lab, agosto de 2026) y los de posgrado con la tasa de la UC. «Hasta» supone el máximo de $306 para una persona durante 12 meses; el beneficio promedio es menor.",
    "gap.sources": "Fuentes",
    "gap.src1": "Matrícula: 17,607 estudiantes de licenciatura y 3,114 de posgrado, otoño de 2025 (SF State Facts).",
    "gap.src2": "Elegibles: 33% de los estudiantes de licenciatura y 7% de los de posgrado de la UC, otoño de 2019 (California Policy Lab, «Filling the Gap», agosto de 2024) → ≈6,030 en SF State.",
    "gap.src3": "Ya lo reciben: 14.3% de los estudiantes de licenciatura de SF State, 2023–24 (California Policy Lab, agosto de 2026); los de posgrado con la tasa de la UC, 27% de los elegibles → ≈2,580.",
    "gap.src4": "Hasta $306 al mes: máximo de CalFresh para una persona desde el 1 de octubre de 2026 (CDSS ACIN I-40-26).",
    "gap.src5": "El promedio es menor: los estudiantes de licenciatura de la UC que participaban recibían en promedio $161 al mes cuando el máximo era $194 (California Policy Lab, febrero de 2025), unos $10.5 millones al año con esa proporción.",
    "gap.src6": "Los estudiantes de posgrado se estiman con las tasas de la UC (7% elegibles, 27% de ellos lo reciben). Los datos de SF State muestran que el 13.6% de sus estudiantes de posgrado ya recibe CalFresh — más de lo que supone este método —, así que los ~160 estudiantes de posgrado de este estimado son la parte menos segura.",
    "gap.src7": "Probablemente conservador: desde el 1 de junio de 2026, los estudiantes de licenciatura de la CSU a medio tiempo cumplen la regla para estudiantes (CDSS ACL 26-25); la tasa de 2019 es anterior.",
    "hero.upto": "Entre todos los estudiantes de SF State: hasta",
    "hero.year": "al año",
    "hero.fig": "Hasta $12.7 millones al año",
    "hero.cap": "en CalFresh que unos 3,450 estudiantes de SF State quizá no reciben, con el máximo para una persona.",
    "hero.link": "Cómo lo calculamos",
    "hero.ai.tag": "IA",
    "hero.ai": "La IA entiende y planifica; las reglas hacen las cuentas; una persona confirma.",
    "hero.ai.link": "Cómo funciona",
    "how.kicker": "Cómo funciona",
    "how.title": "La IA entiende y planifica. Las reglas hacen las cuentas. Una persona confirma.",
    "how.lede": "Una conversación corta en lugar de un formulario. En el centro hay dos pasos de IA: un modelo de lenguaje que entiende el habla libre y un planificador que decide qué preguntar después.",
    "how.legend": "Resaltado: los dos pasos de IA",
    "how.list": "El proceso, paso a paso",
    "how.chip.student": "Estudiante",
    "how.chip.lm": "IA · Modelo de lenguaje",
    "how.chip.planner": "IA · Planificador",
    "how.chip.code": "Código",
    "how.chip.person": "Persona",
    "how.ai.tag": "Papel de la IA",
    "how.1.h": "Hablas",
    "how.1.p": "Por teléfono (inglés) o en tu navegador (inglés o español). GatorPlate recibe texto, nunca audio. El código aparta el ruido y los «¿bueno?» antes de que la IA los vea.",
    "how.1.ai": "El reconocimiento de voz (IA) convierte tu voz en texto; GatorPlate solo recibe texto.",
    "how.2.h": "Entiende",
    "how.2.p": "Convierte el habla libre —cualquier forma de decirlo, correcciones, varias respuestas a la vez— en los datos exactos que necesitan las reglas.",
    "how.2.ai": "Llena cada dato con la cita del estudiante y marca lo que no tiene claro.",
    "how.3.h": "Comprobado con tus palabras",
    "how.3.p": "Un analizador de reglas también lee cada frase. Si no coincide con la IA en una cantidad, la respuesta queda como dudosa para que una persona la revise, y una cantidad clave se puede confirmar en la llamada.",
    "how.3.ai": "Su salida se revisa: un número que el estudiante no dijo se descarta.",
    "how.4.h": "Las reglas calculan",
    "how.4.p": "Una tabla de CalFresh con fecha (oct. 2026 – sep. 2027) calcula cada dólar, con la fuente de cada paso.",
    "how.4.ai": "Ninguno, a propósito: la IA nunca hace las cuentas.",
    "how.5.h": "Elige la siguiente pregunta",
    "how.5.p": "Antes de cada pregunta opcional, vuelve a calcular las reglas con cada respuesta posible: una búsqueda del valor de la información. Las preguntas básicas siguen un orden fijo.",
    "how.5.ai": "Solo pregunta si una respuesta podría cambiar el resultado o mover el estimado más de $50 al mes; como máximo dos, empezando por la más decisiva.",
    "how.6.h": "Una persona confirma",
    "how.6.p": "Las respuestas dudosas quedan en amarillo; un caso no se marca como revisado hasta revisar cada una. El condado decide.",
    "how.6.ai": "Sus marcas de «duda» son lo que la persona revisa.",
    "how.7.h": "Tu tarjeta",
    "how.7.p": "El estimado, respuestas para la solicitud, documentos, preparación para la entrevista y otras ayudas que CalFresh puede abrir.",
    "how.7.ai": "Ninguno, a propósito: el código arma la tarjeta con el resultado de las reglas.",
    "how.loop": "Los pasos 1–5 se repiten en cada turno. Después de cada respuesta, el planificador vuelve a planear, hasta pasar al resultado.",
    "ex.title": "Dos turnos, paso a paso",
    "ex.sub": "De la llamada de demo de Maria: una estudiante simulada, solo texto.",
    "ex.1.h": "Ella dice",
    "ex.2.h": "IA · El modelo llena",
    "ex.2.a": "Ingreso por trabajo: $900 al mes",
    "ex.2.b": "Dinero de la familia: $0",
    "ex.3.h": "El código revisa",
    "ex.3.p": "Cada cita está en sus palabras y dijo $900: se guardan las dos. Un número que no dijo se descartaría.",
    "ex.4.h": "IA · El planificador pregunta",
    "ex.4.p": "Luego, su renta: «Eleven hundred». Una respuesta abierta podría dejar su estimado en $155 o $306 —$151 de diferencia—, así que pregunta:",
    "ex.4.q": "«¿Alguien, como tu mamá o tu papá, le paga parte de tu renta directamente al dueño?»",
    "ex.4.skip": "La calefacción o el aire y otras facturas no podían cambiar su resultado: no se preguntan.",
    "ex.5.h": "Resultado de las reglas",
    "ex.5.p": "«No» → probablemente $306 al mes. Es un estimado; el condado decide.",
    "care.yl.tag": "Por revisar",
    "care.yl.text": "Renta mensual — «unos 800, creo»",
    "perf.title": "Rendimiento",
    "perf.date": "Medido el 2 de octubre de 2026 · estudiantes simulados, solo texto",
    "perf.robust.l": "llamadas fuera de guion y con ruido, con el modelo de lenguaje real, llegaron al monto correcto",
    "perf.robust.how": "24 ejecuciones: 15 variantes de 3 estudiantes simulados (una en español) y el guion de demo de Maria —ruido en cada turno, una tele de fondo, palabras cortadas, correcciones, varias respuestas a la vez—. 3 de 113 llamadas al modelo se pasaron de tiempo; el analizador de reglas siguió y el monto salió correcto.",
    "perf.wrong.l": "valores equivocados llegaron a un resultado",
    "perf.wrong.how": "Las mismas 24 ejecuciones. Una palabra con ruido («nine») se guardó como $9 pero marcada como dudosa, y la pregunta de confirmación la corrigió. El ruido no terminó ninguna llamada.",
    "perf.ground.l": "de las citas guardadas son palabras del propio estudiante",
    "perf.ground.how": "Lo impone el código y está probado: una cita que no está en lo dicho deja la respuesta como «dudosa»; un número que el estudiante no dijo se descarta.",
    "perf.tests.l": "pruebas automáticas pasan",
    "perf.tests.how": "3,054 pruebas en Python y 176 en JavaScript, con un sustituto del modelo de lenguaje. Además, 28/28 guiones de principio a fin y 38/38 guiones adversariales (inyección de instrucciones, un número de Seguro Social dicho en voz alta, una crisis en español).",
    "perf.rules.l": "casos de CalFresh calculados a mano coinciden exactamente con el motor de reglas",
    "perf.rules.how": "Se compara cada campo del resultado. Los otros programas: 14/14 casos calculados a mano.",
    "perf.q.l": "preguntas en la llamada de demo de Maria, de 37 campos de respuesta",
    "perf.q.how": "Llenaron 12 respuestas. El planificador omitió 2 que no podían cambiar su resultado y preguntó 1 que podía moverlo $151 al mes. Promedio en 59 llamadas simuladas: 5.9.",
    "perf.speed.l": "mediana para que la IA entienda una respuesta (paso del modelo de lenguaje)",
    "perf.speed.how": "Ejecuciones locales del código actual, n = 32 llamadas al modelo. Reglas, planificador, frases y controles suman una mediana de unos 5 ms por respuesta (n = 72). No incluye el tiempo del teléfono ni de la red.",
    "care.kicker": "Responsable desde el diseño",
    "care.title": "Las normas que tuvimos en cuenta y los riesgos que manejamos.",
    "care.sub": "Un prototipo estudiantil gratuito que todavía no ha revisado un abogado. Estas tablas muestran cómo leemos cada norma, qué hace GatorPlate hoy y qué faltaría para un piloto real en SF State. No es asesoría legal.",
    "law.title": "Leyes y normas",
    "law.checked": "Fuentes consultadas el 2 de octubre de 2026. Cada cita enlaza al texto de la ley. Es nuestra lectura, no asesoría legal.",
    "law.caption": "Leyes y normas: qué exige cada una, qué hace GatorPlate hoy y su estado",
    "law.col.law": "Ley o norma",
    "law.col.req": "Qué exige",
    "law.col.do": "Qué hace GatorPlate hoy",
    "law.col.status": "Estado",
    "law.badge.design": "Diseñado para ello",
    "law.badge.scope": "Fuera de alcance, según creemos",
    "law.badge.pilot": "Piloto: requiere revisión",
    "law.1.h": "Ley de Invasión de la Privacidad de California",
    "law.1.cite": "Código Penal §631, §632",
    "law.1.req": "Escuchar o grabar una llamada confidencial requiere el consentimiento de todas las partes.",
    "law.1.do": "Antes de cualquier pregunta, la llamada dice que es una IA hecha por estudiantes, que no es un servicio oficial de SF State, que una IA convierte la voz en texto y que el audio no se graba. Luego pregunta: di sí o marca uno. Un no, o dos respuestas poco claras, terminan la llamada, y solo se guarda que no se aceptó.",
    "law.1.status": "Pensado para el consentimiento de todas las partes. Piloto: revisión legal del texto de consentimiento.",
    "law.2.h": "Divulgación de bots en California",
    "law.2.cite": "Código de Negocios y Profesiones §17940–17941 (SB 1001)",
    "law.2.req": "Un bot en línea no puede ocultar que es un bot para impulsar una venta o influir en un voto.",
    "law.2.do": "Dice «IA» en su frase inicial, por teléfono y en la web. «¿Eres un robot?», «¿Esto se graba?» y «¿Es oficial?» reciben una respuesta veraz en cualquier momento.",
    "law.2.status": "No se vende nada ni hay voto. Igual lo decimos.",
    "law.3.h": "CCPA / CPRA",
    "law.3.cite": "Código Civil §1798.100 y ss.",
    "law.3.req": "Las obligaciones recaen en empresas con fines de lucro que superan un umbral de ingresos o de volumen de datos.",
    "law.3.do": "Sin ingresos, sin anuncios, sin venta de datos. Guarda respuestas con citas breves, no la conversación; nunca recibe el número de quien llama; nunca pide el nombre. Se borra por voz («borra mis datos») o en la tarjeta.",
    "law.3.status": "No es una empresa con fines de lucro. Igual seguimos su idea de recoger poco y borrar.",
    "law.4.h": "Confidencialidad de CalFresh",
    "law.4.cite": "Código de Bienestar e Instituciones §10850; 7 CFR 272.1(c)",
    "law.4.req": "Las agencias que administran CalFresh deben mantener confidenciales los datos de solicitantes y beneficiarios y usarlos solo para el programa.",
    "law.4.do": "No recibe registros del condado ni del estado y no envía nada al condado. No guarda listas de beneficiarios. El estudiante presenta su solicitud en BenefitsCal por su cuenta.",
    "law.4.status": "Es una norma para agencias; no tenemos registros de ninguna agencia. Compartir datos con el condado requeriría su propia revisión.",
    "law.5.h": "FERPA",
    "law.5.cite": "20 U.S.C. §1232g; 34 CFR Parte 99",
    "law.5.req": "Protege los expedientes educativos que guarda una escuela o alguien en su nombre.",
    "law.5.do": "El piloto no usa expedientes de estudiantes, así que no necesita integrarse con ellos.",
    "law.5.status": "La revisión de datos y accesibilidad de SF State va antes de un piloto.",
    "law.6.h": "TCPA",
    "law.6.cite": "47 U.S.C. §227(b); resolución de la FCC del 8 de febrero de 2024",
    "law.6.req": "Las llamadas con voz artificial o grabada —incluidas las voces de IA— requieren consentimiento previo.",
    "law.6.do": "Solo contesta llamadas que hace el estudiante. No hace llamadas, no envía mensajes de texto ni devuelve llamadas: nada de eso está construido, y el filtro de respuestas impide prometerlo.",
    "law.6.status": "Solo llamadas entrantes.",
    "law.7.h": "Uso del nombre de la CSU",
    "law.7.cite": "Código de Educación §89005.5",
    "law.7.req": "Nadie puede usar el nombre de la CSU o de un campus para sugerir afiliación o respaldo sin permiso de los Trustees.",
    "law.7.do": "Cada llamada y chat web empieza con «un asistente de IA hecho por estudiantes, no un servicio oficial de SF State». Este sitio dice que no es un servicio oficial de SF State, del condado ni de CalFresh. Sin logotipos, sellos ni colores de SF State.",
    "law.7.status": "Solo una descripción de hechos. Cualquier adopción empieza con la revisión de SF State.",
    "law.8.h": "Accesibilidad",
    "law.8.cite": "Regla web del Título II de la ADA (DOJ 2024; WCAG 2.1 AA; entidades públicas grandes antes del 26 de abril de 2027) · WCAG 2.2 AA",
    "law.8.req": "Un campus debe ofrecer contenido web y apps que puedan usar las personas con discapacidad.",
    "law.8.do": "Por teléfono no hace falta pantalla, app ni cuenta, y el código de la tarjeta se dice en voz alta. En la web siempre se puede escribir. La tarjeta apunta a WCAG 2.2 AA: 117 pares de colores revisados (4.5:1 texto, 3:1 interfaz), uso con teclado, etiquetas para lectores de pantalla, zoom al 200 %, reflujo a 320 px.",
    "law.8.status": "Apunta a WCAG 2.2 AA, sin auditoría. Piloto: revisión de accesibilidad de SF State. Las llamadas de usuarios de TTY aún no tienen un trato especial.",
    "law.9.h": "HIPAA",
    "law.9.cite": "45 CFR Partes 160, 164",
    "law.9.req": "Cubre planes de salud, centros de intercambio de información de salud y proveedores que facturan por vía electrónica.",
    "law.9.do": "No es ninguno de ellos. Medi-Cal aparece solo como una casilla en la misma solicitud. No se guardan datos de salud ni de discapacidad.",
    "law.9.status": "No es una entidad cubierta.",
    "law.10.h": "Afirmaciones veraces",
    "law.10.cite": "Ley de la FTC §5; Código de Negocios y Profesiones §17500",
    "law.10.req": "La publicidad no debe engañar; «hasta» no debe leerse como lo que recibe todo el mundo.",
    "law.10.do": "Cada monto dice que es un estimado y que la agencia decide. Los topes dicen «hasta». Los $12.7 millones son un tope solo de CalFresh, con el método y las fuentes en esta página. Un filtro de respuestas bloquea promesas de ahorros o de pagos.",
    "law.10.status": "Las reglas de redacción se prueban en el código.",
    "risk.title": "Riesgos y cómo los manejamos",
    "risk.caption": "Riesgos: cómo los maneja GatorPlate, la evidencia y lo que sigue pendiente",
    "risk.col.risk": "Riesgo",
    "risk.col.how": "Cómo lo manejamos",
    "risk.col.ev": "Evidencia",
    "risk.col.open": "Pendiente",
    "risk.1.h": "Privacidad",
    "risk.1.how": "El consentimiento va antes de todo. No se guarda audio ni la transcripción completa, y no se recibe el número de quien llama. Un caso guarda respuestas con citas breves (80 caracteres como máximo). El modelo de lenguaje solo ve la pregunta actual y las dos últimas frases, sin dígitos que parezcan identificaciones. El estudiante puede borrar su caso por voz o en la tarjeta.",
    "risk.1.ev": "Pruebas: una llamada sin consentimiento no guarda respuestas, solo que no se aceptó; «borra mis datos» elimina el caso.",
    "risk.1.open": "Un abogado todavía no ha revisado el texto de consentimiento.",
    "risk.2.h": "Seguridad",
    "risk.2.how": "La IA no puede fijar ninguna cifra. Las solicitudes telefónicas van firmadas; la consola pide una clave; los enlaces de la tarjeta no se pueden adivinar y caducan (7 días; el código hablado, 24 horas); hay límite de solicitudes; los registros no guardan el contenido de la conversación; las páginas no cargan nada de terceros.",
    "risk.2.ev": "Pruebas: rutas, registros, firmas de solicitudes. Guiones: inyección de instrucciones.",
    "risk.2.open": "La revisión de datos de SF State va antes de un piloto.",
    "risk.3.h": "Accesibilidad",
    "risk.3.how": "Cualquier teléfono, sin app ni cuenta. El código de la tarjeta se dice en voz alta. En la web se puede escribir. La tarjeta apunta a WCAG 2.2 AA.",
    "risk.3.ev": "Pruebas: 117 pares de colores pasan el control de contraste (2 de octubre de 2026). Guiones: una pregunta sobre servicios TTY se anota, nunca se promete.",
    "risk.3.open": "Sin auditoría WCAG todavía. Las llamadas de usuarios de TTY aún no tienen un trato especial.",
    "risk.4.h": "Exactitud de los datos",
    "risk.4.how": "Una sola tabla de reglas con fechas (1 de octubre de 2026 – 30 de septiembre de 2027), cada valor con su fuente. Ningún estimado fuera de esas fechas.",
    "risk.4.ev": "Pruebas: 78/78 casos de CalFresh y 14/14 de otros programas calculados a mano (2 de octubre de 2026).",
    "risk.4.open": "Hará falta una tabla nueva desde el 1 de octubre de 2027.",
    "risk.5.h": "Sesgo e idioma",
    "risk.5.how": "Un solo motor de reglas para inglés y español; resultados por idioma. El español funciona en la web y en la tarjeta; la línea telefónica es en inglés.",
    "risk.5.ev": "Ejecuciones: llamadas simuladas con un sustituto del modelo, inglés 48/48 y español 11/11 (2 de octubre de 2026); 1 ejecución en español con el modelo real, monto correcto.",
    "risk.5.open": "Aún no se prueban acentos reales ni reconocimiento de voz real. La línea telefónica es solo en inglés.",
    "risk.6.h": "Dependencia excesiva",
    "risk.6.how": "Todo resultado es un estimado; GatorPlate nunca da un «no» sobre la elegibilidad. Las respuestas dudosas quedan en amarillo, y el servidor no marca un caso como revisado hasta que una persona revise cada una. Nunca presenta solicitudes ni firma por nadie.",
    "risk.6.ev": "Pruebas: la revisión queda bloqueada hasta revisar cada línea amarilla. Guiones: pedir un «no»; pedir que presente la solicitud.",
    "risk.6.open": "Aún no se prueba con estudiantes ni coordinadores reales.",
    "risk.7.h": "Crisis",
    "risk.7.how": "Si alguien menciona hacerse daño, en inglés o en español, recibe el 988 y el 911 de inmediato, antes que nada. La IA y unas listas de palabras escuchan a la vez, así que funciona aunque el modelo de lenguaje no responda. No se cita nada de esa frase.",
    "risk.7.ev": "Pruebas: palabras de crisis en los dos idiomas. Guiones: una crisis en inglés; una crisis en español.",
    "risk.7.open": "Si el modelo falla, solo escuchan las listas de palabras; una forma indirecta de decirlo puede pasar desapercibida.",
    "risk.8.h": "Seguridad migratoria",
    "risk.8.how": "Nunca pide número de Seguro Social ni estatus migratorio. Si alguien lo menciona, no se guarda ni se usa como contexto; se le indica la coordinación o una oficina de ayuda legal. Los dígitos que parecen de Seguro Social o de tarjeta se quitan antes de que la IA vea el texto.",
    "risk.8.ev": "Pruebas: borrado de dígitos. Guiones: un número de Seguro Social dicho en voz alta; una pregunta migratoria.",
    "risk.8.open": "Probado con guiones de texto, no con voz real.",
    "risk.9.h": "Errores de la IA y cifras inventadas",
    "risk.9.how": "El modelo solo llena respuestas. Cada cita debe aparecer en lo que dijo el estudiante y cada número debe haberse dicho; si no, la respuesta queda como dudosa o se descarta. Los montos salen de la tabla de reglas. Los números dudosos («¿quince o cincuenta?») se repiten para confirmar. Si el modelo tarda o falla, siguen un analizador de reglas y preguntas cerradas.",
    "risk.9.ev": "Pruebas: combinación, fallas del modelo. Guiones: «fifteen hundred» se repite para confirmar. Ejecuciones: 24/24 con ruido y el modelo real (arriba).",
    "risk.9.open": "En esas ejecuciones, 3 de 113 llamadas al modelo se pasaron de tiempo; siguió el analizador de reglas.",
    "risk.10.h": "Ruido y respuestas fuera de guion",
    "risk.10.how": "El ruido, una tele de fondo o un «¿bueno?» nunca se guardan ni cuentan como respuesta y no llaman al modelo; se repite la pregunta. Las preguntas aparte quedan anotadas para la coordinación. Un silencio largo recibe una pregunta cerrada.",
    "risk.10.ev": "Pruebas: turnos con ruido. Guiones: tres silencios; una pregunta aparte; inglés y español mezclados.",
    "risk.10.open": "Aún no se prueban líneas telefónicas ni reconocimiento de voz reales.",
    "care.note": "Probado con estudiantes simulados y guiones, no con estudiantes reales ni con reconocimiento de voz real. No es un servicio oficial de SF State, del condado ni de CalFresh. No es asesoría legal.",
    "bi.kicker": "Inglés y español",
    "bi.title": "Por qué también en español.",
    "bi.1": "de las personas de 5 años o más en EE. UU. —18.4 millones— hablan español en casa e inglés menos que «muy bien».",
    "bi.2": "de las personas en EE. UU. que hablan inglés menos que «muy bien» hablan español en casa.",
    "bi.3": "de los estudiantes de SF State son latinx (otoño de 2025). SF State es una Institución al Servicio de Hispanos.",
    "bi.ca": "En California son 4.2 millones de personas (11.3%) que hablan español en casa e inglés menos que «muy bien».",
    "bi.close": "Por eso puedes hablar o escribir en español en tu navegador, y tu tarjeta sale en español. La línea telefónica es en inglés.",
    "bi.parity": "El mismo motor de reglas en los dos idiomas: 48/48 llamadas simuladas en inglés y 11/11 en español dieron el resultado esperado (sustituto del modelo, solo texto).",
    "bi.snap": "Las reglas federales de SNAP exigen materiales —y, en oficinas grandes, personal bilingüe o intérpretes— en el idioma de suficientes hogares de la zona (7 CFR 272.4(b)).",
    "bi.sources": "Fuentes",
    "bi.src1": "Oficina del Censo de EE. UU., Encuesta sobre la Comunidad Estadounidense 2024 (1 año), tabla DP02: 18,432,221 de 321,745,943 personas de 5 años o más (5.7%); 63.7% de las 28,918,748 que hablan inglés menos que «muy bien»; California 4,234,066 (11.3%).",
    "bi.src2": "SF State Facts, matrícula de otoño de 2025: 8,015 de 20,721 estudiantes. SF State News, 11 de octubre de 2022 (Institución al Servicio de Hispanos).",
    "bi.src3": "7 CFR 272.4(b)(2)–(3). Todo consultado el 2 de octubre de 2026.",
    "prog.kicker": "Seis programas",
    "prog.sofar": "Las cifras de arriba cuentan solo CalFresh.",
    "prog.title": "CalFresh es la llave.",
    "prog.sub": "Puede abrir más ayudas este año: Medi-Cal, Clipper START, PG&E CARE, California LifeLine y créditos fiscales.",
    "prog.tax": "Créditos fiscales",
    "prog.check": "Revisamos seis programas. Para Maria, cuatro ahorran dinero, uno es cobertura médica y uno es un «quizá» al declarar impuestos.",
    "prog.who": "Maria, una estudiante de ejemplo de nuestra demo",
    "prog.alone": "Solo CalFresh",
    "prog.upto": "hasta unos",
    "prog.transit": "Clipper START — transporte",
    "prog.phone": "California LifeLine — teléfono",
    "prog.phone.amt": "hasta $220",
    "prog.energy": "PG&E CARE — energía",
    "prog.total": "Total al año, hasta unos",
    "prog.coverage": "+ cobertura médica",
    "prog.maybe": "quizá $200 — no se cuenta",
    "prog.note": "Estimados de tablas con fecha, calculados por código, no por la IA. Cada agencia decide.",
    "try.kicker": "Pruébalo",
    "try.title": "Revisa el dinero que quizá te falta reclamar.",
    "try.sub_phone": "Unos minutos. Gratis. Llama en inglés, o habla en tu navegador en inglés o español.",
    "try.sub_web": "Unos minutos. Gratis. Habla en tu navegador en inglés o español.",
  },
};

export function resolveLang(search = "", navLang = "") {
  const q = new URLSearchParams(search).get("lang");
  if (q === "en" || q === "es") return q;
  return String(navLang || "").toLowerCase().startsWith("es") ? "es" : "en";
}

// The headline as display lines: the hook (up to "—" or the first comma), then the channel part, so a break never
// splits "you may be / missing". No-break spaces keep the dash on the hook's line (no line starts with "—") and the
// channel's last three words together ("by phone or / in your browser", never "… or in / your browser"). Only spaces
// change; the words are the strings above.
export function headlineParts(text) {
  const t = String(text).replace(/ —/g, "\u00a0—");
  const m = t.match(/^(.*?(?:\u00a0—|,))\s+(\S.*)$/);
  if (!m) return [t];
  const words = m[2].split(" ");
  const tail = words.length > 3 ? words.splice(-3).join("\u00a0") : null;
  return [m[1], tail ? [...words, tail].join(" ") : m[2]];
}

// A big pitch title as display lines, one per sentence ("The AI listens." / "A rules table decides." / ...).
export function sentenceLines(text) {
  return String(text).split(/(?<=[.!?])\s+/).filter(Boolean);
}

// Everything the page shows, from PublicInfo (or null when it could not be loaded) and the language.
export function landingView(info, lang, { fixtures = false } = {}) {
  const l = lang === "es" ? "es" : "en";
  const s = LANDING_STRINGS[l];
  const raw = info && typeof info.demo_phone_display === "string" ? info.demo_phone_display.trim() : "";
  const digits = raw.replace(/\D/g, "");
  const phone = raw
    ? { text: fill(s.call, { number: raw }), number: raw, href: digits.length >= 10 ? telHref(raw) : null,
      note: s.phone_note }
    : null;
  return {
    lang: l,
    headline: phone ? s.headline_phone : s.headline_web,
    phone,
    trySub: phone ? s["try.sub_phone"] : s["try.sub_web"],   // 06 Try it: mentions the call only when there is one
    // The one filled button on each screen: the call when there is a number, except on the Spanish page, where the
    // English-only phone line stays first but outlined and talking in the browser (in Spanish) is the filled one.
    primary: phone && l !== "es" ? "phone" : "talk",
    talkHref: fixtures ? `/talk/?fixtures=1&lang=${l}` : `/talk?lang=${l}`,
    aboutHref: "#how",   // 02 How it works and 03 Responsible by design, on this page
    consoleHref: fixtures ? "/console/?fixtures=1" : "/console",
    strings: s,
  };
}

// ------------------------------------------------------------------------------------------------ the page

let current = { info: null, lang: "en", fixtures: false };

function paint() {
  const v = landingView(current.info, current.lang, { fixtures: current.fixtures });
  const s = v.strings;
  const $ = (id) => document.getElementById(id);
  document.documentElement.lang = v.lang;
  document.title = s.title;
  for (const node of document.querySelectorAll("[data-t]")) {
    const text = s[node.dataset.t];
    if (typeof text !== "string") continue;
    if (node.hasAttribute("data-lines")) {   // one display line per sentence
      if (node.textContent === text && node.children.length) continue;
      const lines = sentenceLines(text).map((part) => {
        const span = document.createElement("span");
        span.className = "pitch__line";
        span.textContent = part;
        return span;
      });
      node.replaceChildren(...lines.flatMap((span, i) => (i ? [" ", span] : [span])));
    } else if (node.textContent !== text) node.textContent = text;
  }
  for (const node of document.querySelectorAll("[data-t-label]")) node.setAttribute("aria-label", s[node.dataset.tLabel]);
  for (const b of document.querySelectorAll(".langswitch__btn")) {
    b.setAttribute("aria-pressed", String(b.dataset.lang === v.lang));
  }
  const lines = headlineParts(v.headline).map((part) => {
    const span = document.createElement("span");
    span.className = "hero__line";
    span.textContent = part;
    return span;
  });
  $("headline").replaceChildren(...lines.flatMap((span, i) => (i ? [" ", span] : [span])));
  if ($("try-sub").textContent !== v.trySub) $("try-sub").textContent = v.trySub;
  for (const pre of ["", "cta-"]) {
    $(`${pre}talk-link`).setAttribute("href", v.talkHref);
    $(`${pre}about-link`).setAttribute("href", v.aboutHref);
    $(`${pre}console-link`).setAttribute("href", v.consoleHref);
    const link = $(`${pre}phone-link`);
    const note = $(`${pre}phone-note`);
    link.hidden = !v.phone;
    note.hidden = !(v.phone && v.phone.note);
    link.classList.toggle("btn--primary", v.primary === "phone");
    $(`${pre}talk-link`).classList.toggle("btn--primary", v.primary === "talk");
    if (v.phone) {
      // "Call (415) 338-1203": the words may wrap, the number never does.
      const at = v.phone.text.indexOf(v.phone.number);
      const num = document.createElement("span");
      num.className = "nowrap";
      num.textContent = v.phone.number;
      if (at < 0) $(`${pre}phone-text`).textContent = v.phone.text;
      else {
        const end = at + v.phone.number.length;
        $(`${pre}phone-text`).replaceChildren(v.phone.text.slice(0, at), num, v.phone.text.slice(end));
      }
      if (v.phone.href) link.setAttribute("href", v.phone.href);
      else link.removeAttribute("href");
      note.textContent = v.phone.note;
    }
  }
}

// Calm reveal of the pitch sections while scrolling: only with motion allowed and IntersectionObserver present;
// otherwise (and before this runs) everything is simply shown.
function reveal() {
  const calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: no-preference)").matches;
  if (!calm || typeof IntersectionObserver !== "function") return;
  const sections = [...document.querySelectorAll(".pitch, .split")];   // the bar grows when it is itself in view
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("is-in");
      io.unobserve(e.target);
    }
  }, { rootMargin: "0px 0px -12% 0px", threshold: 0 });
  for (const el of sections) io.observe(el);
  document.documentElement.classList.add("js-reveal");
}

// Re-render with other public info (also handy from the page console to check the number's layout).
export function show(info) {
  current = { ...current, info };
  if (typeof document !== "undefined") paint();
}

async function init() {
  const { fetchJSON, FIXTURES } = await import("./shared/api.js");
  const browserLang = (navigator.languages || [])[0] || navigator.language;
  current = { info: null, lang: resolveLang(location.search, browserLang), fixtures: FIXTURES };
  for (const b of document.querySelectorAll(".langswitch__btn")) {
    b.addEventListener("click", () => {
      current = { ...current, lang: b.dataset.lang };
      try {
        const url = new URL(location.href);
        url.searchParams.set("lang", current.lang);
        history.replaceState(history.state, "", url);
      } catch { /* the address stays as it was */ }
      paint();
    });
  }
  paint();
  reveal();
  try {
    current = { ...current, info: await fetchJSON("/api/public/info", { lang: current.lang }) };
  } catch {
    current = { ...current, info: null };
  }
  paint();
}

if (typeof document !== "undefined" && document.getElementById("headline")) init();
