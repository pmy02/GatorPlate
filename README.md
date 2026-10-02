# GatorPlate

GatorPlate is a student-built prototype that helps SF State students check whether they may get CalFresh, California's
food benefit. A student talks to it on the phone or on the web (English and Spanish on the web). It asks only the
questions that can change the answer, gives an estimate that the county decides, and hands the student a card with
the next steps. It is designed for a campus CalFresh coordinator, who would see each conversation's answers in a
console; in this demo the console holds sample data and only our team sees it.

It is not an official SF State, county or CalFresh service. GatorPlate never decides eligibility: every amount is an
estimate, and the county makes the final decision.

In 2023–24, 14.3% of SF State undergraduates received CalFresh at some point in the school year — below the CSU
average (16.4%) and Chico State (33.0%). This is the share of undergraduates receiving CalFresh, not a share of
eligible students. Source: California Policy Lab, *CalFresh Participation Among California's College Students: A
2023–24 School Year Update*, August 2026, Table 2.

## Features

- **A short conversation, by phone or in the browser.** About two minutes for a typical student. The web talk page
  works in English and Spanish, by voice (the browser's own speech recognition) or by typing.
- **Only the questions that can change the answer.** Before each optional question, the rules engine checks whether
  any answer could change the outcome or move the estimate by more than $50 a month; questions that cannot are
  skipped and shown as "not asked" in the console.
- **An estimate, never a decision.** A rules engine computes the likely monthly amount from a dated table of the
  CalFresh rules for October 2026 to September 2027, with a source and date for every step. A student is never told
  they are rejected; when a situation needs a person, the result points to the SF State CalFresh coordinator.
- **A card with the next steps.** What to do today, the documents to bring, the interview, and a calendar file. The
  card opens from a short code (phone) or a link (web) and can be deleted by the student.
- **Money you may be missing.** On the card, after the call, CalFresh comes first and then other aid it can open:
  Medi-Cal coverage, Clipper START discounts during school breaks, PG&E CARE, California LifeLine and tax credits.
  Each amount is an estimate computed by code from one dated programs table (October 2026 to September 2027), shown
  with its source, its date and any assumption (for example "Assumed bill: $140 a month split 3 ways"); a ceiling
  says "up to", and uncertain lines say "maybe" and are not counted. Up to three optional taps on the card can make
  the estimate more precise; they never change the CalFresh estimate. Each agency decides, and nothing on the card is
  a promise.
- **A console for the coordinator.** Each case shows what the student said, what was assumed and why, the rule trace,
  and yellow lines for anything uncertain. A case cannot be marked reviewed until every yellow line is checked.

Product truth: [`docs/SPEC.md`](docs/SPEC.md). Brain API: [`docs/BRAIN_API.md`](docs/BRAIN_API.md) and
[`contracts/`](contracts/). Screens: [`docs/UI_SPEC.md`](docs/UI_SPEC.md).

## How it works

- **The model listens, rules decide, templates speak.** A language model only turns what the student says into
  answers (amounts, yes or no, choices). It never sets an amount, never decides, and never writes a sentence: the
  rules engine computes every number, and every sentence comes from a reviewed sentence bank.
- **A parser checks the model.** A rule parser reads every utterance too. When the model and the parser disagree on
  an amount, or a "teen" and "ty" word could be confused (fifteen or fifty), the student is asked to confirm. When the
  model is slow or unavailable, the conversation continues with the parser and closed questions.
- **A person checks.** Answers the system is unsure about become yellow lines that the coordinator confirms before a
  case can be marked reviewed.

## Responsible AI

- **Disclosure and consent.** Every conversation starts by saying that GatorPlate is a student-built AI assistant,
  not an official SF State service, and how the student's words become text, then asks for consent. Without it,
  nothing from the conversation is kept except that it was declined.
- **Humans decide.** The county decides CalFresh; each agency decides its own program. The coordinator reviews every
  case, and uncertain answers are flagged, not guessed.
- **No rejection.** GatorPlate never says a student is not eligible. Every outcome is an estimate, a referral to the
  coordinator, or other help.
- **Data minimization.** We don't collect Social Security numbers, and we never ask about immigration status.
  Number runs that look like a Social Security or card number are removed before anything else sees the text. A case
  keeps the student's answers, not the conversation, and the student can delete it.
- **Safety.** Statements about self-harm, in English or Spanish, get crisis resources (988 and 911) at once, from the
  model or from keyword lists that work without it.
- **Sources and dates.** Every rule and every program amount comes from a dated table with its sources; the console
  shows "Computed by the rules table — not by AI".
- **Fairness.** English and Spanish are tested with the same cases and reported separately below. Spanish text is
  marked for native review.

Details: [`docs/SPEC.md`](docs/SPEC.md) §9.

## Run it locally

Requirements: Python 3.12. No Node, no build step, no external services are needed for the default setup (the fake
language model is used unless a key is configured).

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
make run          # the app on http://127.0.0.1:8000 (console at /console, talk page at /talk)
make web PORT=8105  # static pages in fixture mode, for example http://127.0.0.1:8105/console/?fixtures=1
make say ARGS="--script maria_g1"  # play the demo phone call against the running app
```

Settings are environment variables named `GP_*` only; `.env.example` lists every name. Make targets start Python with
a clean environment and set the values they need. With `GP_LLM_API_KEY` set in your shell, `make run LLM=anthropic`
uses the real language model.

## Test it

```sh
make test            # the full suite with the fake language model
make lint            # ruff
make validate-data   # rules tables, golden cases, demo cases, content, contract examples
make check-examples  # the Brain API contract examples
make contrast        # design system: contrast, tokens, light theme, fonts, icons, CSP-safe pages
make test-web        # JavaScript unit tests (needs node; skipped without it)
make e2e             # end-to-end scripts: starts one local server per declared setup on port 8000, then stops it
make adversarial     # adversarial conversation scripts (same local mode)
make examples        # replays the contract examples over HTTP (same local mode)
make leakcheck HISTORY=1  # generic public-repository checks, git history included
```

`make eval BASE=http://127.0.0.1:8000` plays the simulated students of `data/eval/personas.json` against a running
app (scripted paraphrases; a live run with a model-played student needs a key and a spending cap).

## Evaluation

All results below come from simulated students and test scripts, not from real students or real speech
recognition. Silent errors are counted as k/n with the Wilson 95 % upper bound, never as "no errors".

| What was measured | n | Result |
|---|---|---|
| CalFresh rules: golden cases (hand-computed) | 78 | all pass; 12 random cases re-derived by hand: 0 mismatches |
| CalFresh rules: random fact sets, engine vs an independent hand model | 4,000 | 0 mismatches |
| Other programs: golden cases (hand-computed) | 14 | all pass; 4 re-derived by hand: 0 mismatches |
| Scripted simulated students (fake model), tier agreement | 59 calls, 35 personas (24 English on web and phone, 11 Spanish on web) | 59/59 (English 48/48, Spanish 11/11) |
| — amount exact on likely cases | 44 | 42/44 (English 36/38, Spanish 6/6); mean absolute error $3.09 |
| — silent errors | 59 | 0/59 (upper bound 6.1 %); English 0/48 (7.4 %), Spanish 0/11 (25.9 %) |
| — questions / student turns per call | 59 | 5.9 / 7.9 |
| Same students, parser only (no model) | 59 | tier 59/59; amounts 42/44 exact; silent 0/59 (upper bound 6.1 %) |
| Live model-played students (web, one earlier build) | 24 calls, 24 personas (13 English, 11 Spanish) | tier 18/24 (English 10/13, Spanish 8/11); amount exact 9/13 |
| — silent errors, adjudicated by what the student actually said | 24 | 3/24 (upper bound 31.0 %); English 1/13, Spanish 2/11 |
| — brain processing per turn (live model, local machine) | 269 turns | p50 1,277 ms, p95 2,198 ms (targets: 800 ms and 1,500 ms — not met yet) |
| — measured language-model cost per call | 24 calls | about $0.05 (GatorPlate's own model calls only) |
| Rewordings of earlier misreadings (adversarial probes; the last fixes were made against them; fake model and parser only) | 146 runs (73 probes × 2 modes) | 143 pass; the 3 left ask one extra question and end with the right result |
| End-to-end scripts / adversarial scripts / contract examples (local, fake model) | 28 / 38 / 8 | all pass; 9 more scripts need a live model and are run only with a key |
| Replies checked against the output guard, word budgets and phone text rules (adversarial run, earlier build) | 4,042 | 0 problems |

The live numbers were measured once, on an earlier build, before the last rounds of fixes; they have not been measured
again since. The two amounts that differ in the scripted run come from one persona (on both channels): its call ends
$68 lower, with a yellow line that asks the coordinator to check.

## How and when we built it

- When: _[to be written by the team]_
- Who: _[to be written by the team]_
- How: _[to be written by the team]_

## License

MIT — see [`LICENSE`](LICENSE).

## Notices

Third-party material (the Atkinson Hyperlegible Next font, SIL Open Font License 1.1) is listed in
[`NOTICE.md`](NOTICE.md). Icons and the logo are original work.
