# Contract requests

The one shared file of the parallel build. An agent that needs a change outside its own files appends an entry here
(one shell append, never an edit of existing text), lists it in its final report and keeps going with a local adapter.
The integrator decides each entry and notes the decision under it; only the integrator edits existing text.

Entry format:

```text
### <agent> · <file> · <short title>
- Change: <the exact change>
- Why: <the reason, with the docs/SPEC.md, docs/BRAIN_API.md or docs/UI_SPEC.md section it follows>
- Local adapter: <what the agent does meanwhile>
- Decision: <left empty; the integrator writes accepted or rejected, with a note>
```

## Entries

### A1 · tests/test_stubs.py · the rules stub check no longer applies
- Change: in `test_stubs_import_and_raise`, remove the three lines that build `Rules(...)` and expect `NotImplementedError` from `rules.valid_on(TODAY)`; if a smoke check is wanted, use `assert Rules(Path("data/rules/ca_fy2027.json")).valid_on(TODAY) is True` instead.
- Why: the rules engine is built (docs/SPEC.md §5), so `valid_on` answers instead of raising and this stub check fails in `make test-core`; the engine's own tests are in `tests/rules/`.
- Local adapter: none; `make test-rules` covers the engine.
- Decision: accepted (INT, integration). `test_stubs_import_and_raise` became `test_modules_import_with_final_signatures` with the smoke check `Rules(...).valid_on(TODAY) is True`; the import and signature checks stay.

### A4 · gatorplate/wiring.py · platform pieces for build_deps
- Change: in `build_deps(settings)` build the platform from `gatorplate.store`: `db = Database(settings.db_file)`; `cases = CaseStore(db, clock=clock)`; `sessions = SessionStore(db)`; `live = LiveStore()`; `events = EventBus(clock=clock, tz=settings.tz)`; for the understander's daily cap `Counters(db, clock=clock)` (methods `incr(key, by=1) -> int`, `get(key) -> int`, `try_take(key, cap) -> bool`, all on the Pacific date; suggested key `llm_turns`). `create_app(deps)` builds its own web tokens, counters, rate limits, demo cases and janitor on `deps.cases.db` and installs the programs-aware summarizer on the event bus, so nothing else is needed for the API.
- Why: docs/SPEC.md §8 (storage, retention) and docs/UI_SPEC.md A8.3; the API and the janitor rely on the store's extra helpers (`get_by_code`, `ids`, `count`, `any_live`, `purge_short_codes`, `SessionStore.idle/for_case`, `EventBus.open/changed_since`), so the deps must be these classes.
- Local adapter: tests build the same objects in `tests/api/fakes.py` (`make_deps`).
- Decision: accepted. `gatorplate/wiring.py` builds `Database(settings.db_file)`, `CaseStore(db, clock=clock)`, `SessionStore(db)`, `LiveStore()`, `EventBus(clock=clock, tz=settings.tz)` and passes `Counters(db, clock=clock)` to the understanding (with the later `incr(key, day)` shape, see the A4 (review) entry). One clock instance reaches every component; `wiring.compose(settings, clock=, ids=)` lets tests pin both.

### A4 · gatorplate/extract (understanding) · language-model health for /healthz
- Change: expose `Understander.llm_health() -> {"status": "no_key" | "ready" | "ok" | "error", "last_ok_at": datetime | None, "usage": {"calls": int, "input_tokens": int, "output_tokens": int}}` (counts since process start, no personal data).
- Why: `/healthz` must report `llm.status` and `llm.usage` (docs/BRAIN_API.md §9 budgets are measured from it; the evaluation tool's cost cap reads `llm.usage`).
- Local adapter: `/healthz` calls `understanding.llm_health()` when it exists, else reads `status`, `last_ok_at` and `usage` (or `metrics`) attributes of `understanding.llm`; with neither it reports `no_key` (provider anthropic without a key) or `ready` and zero usage.
- Decision: accepted; nothing to change: `Understander.llm_health()` exists (A2) and `/healthz` reads it.

### A4 · tests/test_stubs.py · stub test now fails because the rules engine is built
- Change: drop the `rules.valid_on` NotImplementedError assertion from `test_stubs_import_and_raise` (and any other stub-raises assertion for a module that is now built).
- Why: the rules engine answers `valid_on` now, so `make test-core` fails on this line; the import and signature checks in that test still hold (`create_app(deps)` and `build_deps(settings)` keep their signatures).
- Local adapter: none needed (A4's own targets do not run this file).
- Decision: accepted (same change as the A1 entry above).

### A6 · gatorplate/wiring.py · construct the card builder with the rules table and the card TTL
- Change: build the card builder as `CardBuilder(settings.content_dir, programs, guards_path=settings.guards_path, tz=settings.tz, rules_table_path=settings.rules_table_path, card_ttl_days=settings.card_ttl_days)` with the same ProgramsPort that goes into `Deps.programs`. Both new keyword arguments are optional (defaults: the repository's `data/rules/ca_fy2027.json`, 7 days).
- Why: the card shows the IRT line or the SAR 7 line and the "highest amount" line from the rules table's 130 % line and maximum allotment (docs/SPEC.md §5.2 step 12, §6.2), refreshes the filing-date estimate when the student opens the card on a later day (docs/SPEC.md §5.7), and derives half-time from units for its conditions; `GP_RULES_TABLE` should reach it like it reaches the rules engine.
- Local adapter: the defaults point at the repository's own table, so the card works unwired.
- Decision: accepted as written: `CardBuilder(settings.content_dir, programs, guards_path=settings.guards_path, tz=settings.tz, rules_table_path=settings.rules_table_path, card_ttl_days=settings.card_ttl_days)` with the same ProgramsPort instance as `Deps.programs`.

### A6 · gatorplate/contracts/ports.py, gatorplate/api (card routes) · optional `now` for the calendar file
- Change: (optional) `CardBuilderPort.ics(case, *, lang, now: datetime | None = None)`, and the reminders route calls `deps.cards.ics(case, lang=lang, now=deps.clock.now())`. `CardBuilder.ics` already accepts `now`. The route should map `errors.NotFound` from `ics()` (a case with no filing day: no first month and no recorded application date) to 404 `not_found`; `CardView.reminders_url` is null in that case, so the page hides the button.
- Why: `build()` refreshes the filing-date estimate for the day the card is opened (docs/SPEC.md §5.7), so with `now` the three calendar dates (docs/SPEC.md §6.3) follow the same day the card text shows; without it they stay relative to the filing day estimated at the call.
- Local adapter: without `now`, `ics()` uses the recorded application date (`tracking.filed_on`) if any, else the case's `first_month.filed_on`.
- Decision: accepted. `CardBuilderPort.ics(case, *, lang, now: datetime | None = None)` in gatorplate/contracts/ports.py (a Protocol, no snapshot change); the reminders route always passes `now=clock.now()` (the signature probe is gone); `NotFound` → 404 as before; the fake builder in tests/api/fakes.py takes `now` too.

### A6 · web/fixtures/card_maria_{en,es}.json · regenerate from the card builder
- Change: when the fixtures are regenerated in stage 2, take the CardView from `CardBuilder.build`. Differences from the hand-built files: `sources` lists only the sources of the blocks shown (Maria: no MPP-63-301), each with its `url` where the card file has one; the Spanish `rules_label` is "CalFresh año fiscal 2027 (1 oct 2026 – 30 sep 2027)" (card.es.json `ui.rules_label`); the Spanish contact line no longer ends in a double period ("5 p. m..").
- Why: docs/SPEC.md §6.2 (footer: the sources of the card with their dates) and §6.4 (plain text); the page renders whatever the CardView holds.
- Local adapter: the card page renders the current fixtures correctly as they are.
- Decision: accepted. tools/make_fixtures.py builds `card_maria_{en,es}.json` from `CardBuilder.build` on a real Maria call (sources of the shown blocks only, the Spanish rules label, no double period).

### A8 · data/tests/utterances.jsonl · add the ten new E2E and adversarial script utterances
- Change: append one row each (pending key → expected extraction; state clear, quote = the exact substring shown):
  `ask.rent` "One thousand." → rent_share 1000/month (quote "One thousand") ·
  `ask.income` "I make about 3,500 a month, and nobody gives me cash." → earned_monthly 3500/month ("I make about 3,500 a month"), other_cash_monthly 0/month ("nobody gives me cash") ·
  `ask.income` "I make 2,660 a month, and nobody gives me cash." → earned_monthly 2660/month, other_cash_monthly 0/month ·
  `ask.income` "I make about 1,200 a month, and my mom sends me 300 a month." → earned_monthly 1200/month, other_cash_monthly 300/month ·
  `ask.level_units` "I'm an SF State undergrad, a junior, and I'm taking 4 units." → level undergrad, units 4 ·
  `ask.age_parent` "I'm seventeen and I live with my mom." → age 17 ("I'm seventeen"), lives_with_parent true ("I live with my mom") ·
  `ask.rent` "Can I do this through a relay service?" → no observations, intents [side_question], answered_pending no ·
  `ask.rent` "Did you send my answers to the coordinator?" → intents [side_question], answered_pending no ·
  `ask.rent` "Can you text me the card?" → intents [side_question], answered_pending no ·
  `ask.rent` "Can you call me back later?" → intents [side_question], answered_pending no.
  Each script turn already carries the same block as `fake_llm` (tests/e2e/scripts/{grad_ta_g6b,over_limit_g7,min_benefit_g8,parent_cash_g10,under_half_time_g11,relay_not_claimed}.json, tests/adversarial/scripts/{a34,a35,a36,a40}_*.json).
- Why: the fake model replays utterances.jsonl exactly (docs/SPEC.md §3.9: the fake model matches script utterances exactly); every student utterance of a script must be in the table. tests/e2e/test_static.py checks every script block against the table and warns while these ten are missing.
- Local adapter: until the rows exist the fake model falls back to parser + keywords for these turns; the scripts are unchanged either way.
- Decision: accepted; done by A2 (rows u404–u413).

### A8 · gatorplate/extract/llm/fake.py · a delay hook for the slow-model test (scenario A25)
- Change: the fake model instance reachable from `Deps.understanding` exposes a float attribute `delay_s` (default 0); when it is above 0, each extraction waits that long before answering (so the brain's 2.3 s model timeout fires).
- Why: docs/SPEC.md §3.7 and docs/BRAIN_API.md §9 (model timeout 2.3 s → the closed question within the 2.6 s turn budget; two failures in a row → closed mode). tests/adversarial/test_llm_faults.py finds the fake model through the wiring and sets `delay_s = 3.0`; HTTP scripts cannot inject a delay.
- Local adapter: the test skips with the reason "the fake model exposes no delay hook" when the attribute is absent; closed mode itself is covered over HTTP by tests/adversarial/scripts/a26_closed_mode.json (GP_LLM_DAILY_TURN_CAP=0).
- Decision: no action (withdrawn by the next entry: the fake model already has `delay_s` and `fail`).

### A8 · gatorplate/extract/llm/fake.py · withdrawn: the delay hook already exists
- Change: none. The fake model already exposes `delay_s` (and `fail`), which tests/adversarial/test_llm_faults.py uses; the entry above needs no action.
- Why: found after filing.
- Local adapter: none needed.
- Decision: noted; no action.

### A5 · web/fixtures/case_maria.json, web/fixtures/case_maria_reviewed.json, web/fixtures/maria_live_events.json (last entry) · Maria's slot sources
- Change: give Maria's ended-call slots the sources of a live call (`llm` / `parser`, as in the earlier steps of `maria_live_events.json`), not `seed`; Maria's case is not seeded (`seeded: false`).
- Why: docs/UI_SPEC.md A3.5 item 4 shows the source `seed` as a *Sample* tag, so in fixture mode every answer of Maria's ended call reads "Sample" although her case is a real call; the live sequence switches from `llm` to `seed` at its last step.
- Local adapter: none needed; the console shows what the fixture says (and its fill sweep ignores a source-only change). The regenerated fixtures at integration should fix it.
- Decision: accepted. The regenerated fixtures come from a real fake-model call of Maria, so her slots carry the live-call sources (`llm` / `parser`), not `seed`.

### A3 · gatorplate/wiring.py (INT) · how the brain meets the rules and understanding ports (no frozen-file change)
- Change: none to a frozen file. Integration notes for G2, checked by A3 against the current rules and understanding modules (the three golden dialogues and the 23 contract scenarios give the same keys with them as with A3's test doubles):
  (1) `Case.asked`: the brain appends every case question it asks (standard, flip with `reason`/`delta_usd`/`outcomes` copied from the plan's FlipCandidate, confirm, band, closed, reprompt); the follow-up `flip.rent_paid_by_others_amount` is recorded as kind `flip` on the same slot, so the rules count one flip per slot. The rules' `apply` writes the not-asked `SkippedQuestion` entries; the brain only adds an entry for a slot that has none.
  (2) The brain keeps `Case.phase` equal to the conversation phase before every `RulesPort.apply` and re-runs `apply` when it enters the result phase, so the rules see a call that moved past the flip questions.
  (3) `Case.card` (CardRef) is created by the brain at the card line: token from `Ids.card_token()`; on the phone also a 6-digit short code from `Ids.short_code()`, checked free with `CaseStorePort.get_by_short_code`; lifetimes from `GP_CARD_TTL_DAYS` and `GP_SHORT_CODE_TTL_H`. The web reply's `card_url` is `/c/<token>`.
  (4) Cash question: asked after a likely result when `RulesPort.evaluate(facts_from_case(...)).expedited_screen` holds in any remaining utility world (the facts with `utility` set to each unanswered utility value); the outlook comes from `FlipPlan.expedited_outlook` (budget 0) and is written to `Case.expedited_possible`.
  (5) A call starts in closed mode when the understanding has no model client: the brain reads the Understander's `llm_health()["status"] == "no_key"` (or `llm is None`); the port itself has no such method. Over the daily turn cap the client answers `skipped`, which the brain cannot tell apart from the fast path, so those calls ask open questions and the parser answers them.
  (6) A spoken web address on a development host (a loopback or numeric host) is "localhost slash go", so local runs keep the deployed word budgets; `GP_PUBLIC_BASE_URL` on Fly gives "gatorplate dot fly dot dev slash go".
- Why: docs/SPEC.md §3.2 (phases, card line, cash question), §5.6 (question plan), §3.7 (closed mode); docs/BRAIN_API.md §7 (spoken addresses and budgets).
- Local adapter: none needed; tests/dialogue uses in-memory doubles of every port.
- Decision: accepted as integration notes; the wiring gives the brain the real rules, understanding (with `llm_health()`), stores, card builder and one clock. Nothing else needed.

### A2 · gatorplate/wiring.py · build the Understander with the app's clock and daily counter; health from it
- Change: build the understanding as `Understander.from_settings(settings, counters=<counter>, clock=clock)`, where `clock` is the same Clock the brain uses for the turn deadline and `<counter>` is an object with `incr(key: str, day: date) -> int` (the count after adding one) over the platform's `counters` table (key `llm_turns`, day = the Pacific date). `/healthz` `llm` = `deps.understanding.llm_health()` (`{provider, status: no_key | ready | ok | error, last_ok_at, usage: {calls, input_tokens, output_tokens}}`).
- Why: docs/SPEC.md §3.6-§3.7 (one turn budget and model timeout; the daily model turn cap puts new calls in closed mode) and §8.9 (content-free counters only). With the same clock the deadline and "now" share one monotonic scale; with the platform counter the cap survives a restart.
- Local adapter: without these arguments the Understander uses an in-process counter and the system monotonic clock (a deadline that is clearly on another clock's scale falls back to GP_TURN_BUDGET_S), so it already works unwired. Over the cap, or with GP_LLM_DAILY_TURN_CAP=0, `understanding.llm` is None, which the brain already reads as "start new calls in closed mode".
- Decision: accepted as written: `Understander.from_settings(settings, counters=Counters(db, clock=clock), clock=clock)`; `/healthz` llm = `llm_health()`.

### A2 · data/tests/utterances.jsonl · done: the ten rows the A8 entry above asks for
- Change: none needed; rows u404-u413 were added with the scripts' `fake_llm` blocks as their expected extraction (data/tests/utterances.jsonl now holds 413 lines). tests/extract/test_service.py checks that every student line of contracts/examples and tests/e2e/scripts is in the file with the same extraction, so a script added later shows up there.
- Why: docs/SPEC.md §3.9 (the fake model replays the prepared extractions exactly).
- Local adapter: none.
- Decision: noted; no action.

### A6 (review) · gatorplate/api/routes_card.py · the calendar download's file name and its first-month gate
- Change: (1) the reminders route sends `Content-Disposition: attachment; filename="gatorplate-dates.ics"` instead of `gatorplate-reminders.ics`. (2) Optional, with the earlier A6 entry (map `errors.NotFound` from `cards.ics()` to 404): drop the route's own `case.first_month is None` check, so a case whose application day the coordinator recorded (`tracking.filed_on`) also gets its three dates; then widen `has_calendar` in `gatorplate/card/builder.py` (`CardBuilder.build`) to `case.first_month is not None or case.tracking.filed_on is not None`.
- Why: (1) docs/SPEC.md §6.3 and docs/UI_SPEC.md A4.3: no student-facing text calls these dates "reminders"; the file name is what the student sees after the download, and a same-origin `Content-Disposition` name wins over the page's `download="gatorplate-dates.ics"`. (2) Today the route answers 404 for a case without a first-month estimate even when `ics()` could build the file from the recorded filing day.
- Local adapter: the card advertises `reminders_url` only when the case has a first-month estimate (exactly what the route serves), so the page never offers a download that answers 404; `ics()` already prefers the recorded filing day.
- Decision: accepted, both parts. (1) The download is `gatorplate-dates.ics`. (2) The route no longer pre-checks the first month (A4 review) and the card builder offers `reminders_url` whenever the case has a filing day (`first_month` or `tracking.filed_on`). docs/SPEC.md §6.3 and docs/UI_SPEC.md A4.3 aligned; tests in tests/api/test_edges.py and tests/card/test_builder.py.

### A1 (review) · gatorplate/dialogue/policy.py and gatorplate/rules/voi.py · band answers the rules can read back
- Change: decide one representation for a work-income band answer, then INT applies both halves together. Today `_band` stores `above_b` at `b` (the rules then read the band $1,000–$2,000 instead of "over $2,000", which crosses the gross limit), stores `above_x` at `x` instead of the band's top, and stores `below_x` at `x`; the rules re-derive the band from the stored value alone, so after a `flip.earned_split` answer "less than $X" the estimate still uses the old band's top (an under-estimate), and "more than $X" is right only because the rules widen it again. Proposal: (1) dialogue: `above_b` → the gross limit for the household size plus the table's step marked as over the limit (or a value above the limit, so the rules ask at the limit first), `above_x` → the band's top, `below_x` → `x`; (2) rules: once `flip.earned_split` was asked, an assumed work income strictly inside a band is the narrowed band's conservative end (band low edge to the stored value) instead of being widened to the full band. Neither half is safe alone (half 2 with today's `above_x` would over-estimate), so A1 did not change the rules side.
- Why: docs/SPEC.md §5.6 (income band, split rule, "if the band crosses the gross limit, X = the limit first"; stop with the band top + yellow).
- Local adapter: none; the combined behavior today errs low (never above the student's own band), and `Rules.earned_split_point` now gives the docs/SPEC.md §5.6 split (halfway amount, nearest $50) if the dialogue wants it instead of the income midpoint.
- Decision: accepted in principle, deferred to the fix loop (owners A1, A2 and A3 together). Reproduced on the real wiring: "More than two thousand." to `ask.income_band` is stored as $2,000 (assumed), the rules read the $1,000–$2,000 band and the next question is "less than sixteen hundred dollars?"; the call ends `likely_floor` $25. A spoken "more than $b" and "between $a and $b" both arrive as the value b (parser `_spoken_band` and the model's band convention), so the dialogue cannot tell them apart and no single module can fix it: the parser and the extraction prompt need a distinct encoding for "over b" (for example a value above b), the dialogue stores it so the rules ask at the gross limit first, and the rules apply half 2 (narrowed band after the split). Not on the demo path; the unclear yellow line stays on the case meanwhile.

### A1 (review) · gatorplate/contracts/console_text.py · work-rule line wording for a graduate student
- Change: add a graduate variant of the `abawd_possible` text, for example "Less than half-time: the county may apply the 3-month work rule unless the student works {hours} hours a month." (the table's `abawd.yellow_text` wording), and let A1 pick it when the student is a graduate student; the undergraduate text stays "Fewer than {units} units: …".
- Why: docs/SPEC.md §5.2 step 2 — graduate half-time depends on the program, not on 8 units; a graduate below half-time (golden N5-b) gets "Fewer than 8 units", which is not what the student said.
- Local adapter: A1 keeps the frozen template for everyone.
- Decision: accepted. `console_text.abawd_possible(units, hours, *, graduate=False)` adds the "Less than half-time: the county may apply the 3-month work rule unless the student works {hours} hours a month." variant; the rules pick it for `level` grad. Tests in tests/test_contracts_misc.py and tests/rules/test_apply.py.

### A1 (review) · gatorplate/dialogue/policy.py · ask the income split after a band answer
- Change: `_open_for_flip` also accepts `SlotState.assumed` (a band answer), so the `flip.earned_split` question that the rules' plan puts first after "between $1,000 and $2,000" is asked; today the plan's first candidate is dropped and the band's top stays the estimate.
- Why: docs/SPEC.md §5.6 "Income band": within a band the next binary question `flip.earned_split` uses the split point X; the rules plan it for an assumed (band) work income when the spread is over $50 (tests/rules/test_voi.py `test_band_answer_stored_as_assumed_is_measured`).
- Local adapter: none on the rules side; the leftover keeps the conservative band top and the dialogue's own unclear line.
- Decision: accepted; done by A3 (a band answer is open for the plan, so `flip.earned_split` is asked; seen on the real wiring).

### A4 (review) · gatorplate/wiring.py · the daily counter's signature changed (supersedes the `incr` text of the A4 wiring entry)
- Change: in `build_deps`, pass the platform's counter to the understanding module as its daily counter: `Understander.from_settings(settings, counters=Counters(db, clock=clock), clock=clock)`. `Counters.incr` is now `incr(key, day=None, *, by=1) -> int` — the understanding module's `DailyCounter.incr(key, day)` shape (day positional, a `date`). The A4 wiring entry above still says `incr(key, by=1)`; that call shape is gone (a second positional int now raises TypeError instead of being read as a day).
- Why: the understanding module calls `counters.incr(DAILY_KEY, today)`; with the old signature the date landed in `by` and every language-model turn failed with a TypeError (found by tests/api/test_real_platform.py, which runs the platform with every real module). docs/SPEC.md §4.12 item 12.3 (daily model turn cap, Pacific date).
- Local adapter: none needed; `tests/store/test_store.py::test_counters_fit_the_understanding_daily_counter` pins the shape against `MemoryCounter`.
- Decision: accepted; the wiring passes `Counters(db, clock=clock)`.

### A4 (review) · gatorplate/contracts/ports.py · `CardBuilderPort.ics` may take `now` (supports the A6 entry)
- Change: none required. The reminders route now calls `ics(case, lang=…, now=clock.now())` when the injected builder's `ics` accepts `now`, else `ics(case, lang=…)`, and no longer pre-checks `first_month`: the builder decides the filing day (recorded application date, else the estimate) and raises `NotFound` → 404. If INT accepts the A6 entry, the port can gain `now: datetime | None = None` and the route's signature check can go.
- Why: docs/SPEC.md §6.3 and §5.7 (the calendar dates follow the filing-date estimate the card shows today); before, a case with an application date but no first month answered 404 although the builder could build the file.
- Local adapter: `inspect.signature` check in `gatorplate/api/routes_card.py`.
- Decision: accepted together with the A6 entry above (the port takes `now`; the route always passes it).

### A5 (review) · gatorplate/dialogue/orchestrator.py (`_live_lines`) or gatorplate/store/live.py · no `live.turn` event is ever published
- Change: publish one `live.turn` event per transcript line (`events.publish("live.turn", line=line)`, never buffered, as `gatorplate/store/events.py` already allows), and in `Orchestrator.turn` append the turn's lines before `_persist` publishes `case.updated` (today `_persist` runs first), so the student's line reaches the console before the case update that fills its fields. Today `LiveStore.append` only stores the line and nothing in `gatorplate/` calls `publish("live.turn", …)`.
- Why: docs/UI_SPEC.md A3.8 and A8.3 (lines arrive as `live.turn` events; `GET /api/cases/{id}/live` is for a console that opens mid-call or reconnects), docs/SPEC.md §8.6; W1's transcript and its word-to-field highlight depend on it, and UI_SPEC A9 item 8 checks it with a scripted Maria call.
- Local adapter: the console (web/console/store.js `effectsOf`) fetches `GET /api/cases/{id}/live` on every `case.updated` of the watched live call as long as no `live.turn` event has arrived for that call, and the Live view marks a field's words whichever arrives first (line or case update). With the events in place the adapter stops by itself after the first `live.turn`.
- Decision: accepted; done by A3: the brain publishes one `live.turn` per transcript line (only with `GP_LIVE_TRANSCRIPT=1`) before `case.updated`; `LiveStore.append` publishes nothing.

### A9 · gatorplate/api/routes_pages.py (A4) · the card widget is three files; the harness has two assets
- Change: none required today. Keep serving `/unlocked/unlocked.js`, `/unlocked/unlocked-lib.mjs` (an ES module that `unlocked.js` imports; `text/javascript`) and `/unlocked/unlocked.css` in prod. Optionally answer 404 in prod for `/unlocked/harness.js` and `/unlocked/harness.css` as for the harness page itself (they only run with `?fixtures=1`). For the card page budget, the widget's three shipped files are 11,995 bytes together (pinned at 12,000 by `tests/programs/test_widget.py`).
- Why: docs/UI_SPEC.md A4.1 (the card page's 60 KB budget includes the widget) and A4.2 row 2b; the pure helpers live in their own module so `node --test` can check them (`web/unlocked/unlocked-lib.test.mjs`).
- Local adapter: none; the current prod rule blocks only `/unlocked/` and `/unlocked/index.html`, so every widget file is served.
- Decision: accepted, including the optional part: in prod `/unlocked/harness.js` and `/unlocked/harness.css` answer 404 like the harness page; `unlocked.js`, `unlocked-lib.mjs` and `unlocked.css` are served everywhere (test in tests/api/test_edges.py).

### A8 (review) · gatorplate/dialogue (policy) · a partly answered two-part question is re-asked forever
- Change: when an answer fills only part of a question's slots (for example `ask.age_parent` answered with age only), re-ask once with `reprompt.unclear` (or ask only the missing part), then the closed form, then the conservative value with a yellow line (docs/SPEC.md §3.4 and §3.6: one re-ask, then the closed question); never the same open question again and again. Also keep `Case.phase` on the phase still being asked: in the reproduction the case reached phase `expedited` with a settled $306 range while the reply still asked `ask.age_parent`, so a hang-up then left "likely $306" with no `incomplete` yellow line (a silent error on the console).
- Reproduction (fake model, phone or web; the real modules composed as the wiring will do): consent "Yes, go ahead." → "I'm a junior at SF State, twelve units this semester." → "I'm twenty, and I share an apartment with two roommates." (repeat it). Every reply has keys `['ask.age_parent']` (the first two `['ack.short', 'ask.age_parent']`), no `reprompt.unclear`, no closed form; after about 24 such turns `/end` `caller_hangup` leaves tier likely, $306, no yellow line. With a closed form the call would move on.
- Why: found by the scripted evaluation (tools/simulate_student.py, data/eval/personas.json): about half of the English persona calls stall here on the fake model, so V6's scripted report would be dominated by this loop.
- Local adapter: tools/simulate_student.py now hangs up after the same question five times in a row and reports those calls as "not finished" instead of running to the turn cap.
- Decision: accepted; done by A3. Checked on the real wiring: an age-only answer gets one `reprompt.unclear`, then the next question with an `unclear.lives_with_parent` yellow line.

### A8 (review) · gatorplate/extract (parser) · "share an apartment with two roommates" does not answer the living-situation part
- Change: the parser/keyword fallback reads "I share an apartment with (two) roommates", "I live with my wife", "I live by myself" as `lives_with_parent: false` (it already gets the age and `roommates_count`), or the evaluation personas' paraphrases are added to data/tests/utterances.jsonl with their expected extractions.
- Why: with the fake model (and in closed mode, when the model is down) the parser is the only reader; the persona paraphrase above leaves `lives_with_parent` empty, which triggers the loop of the entry above. docs/SPEC.md §10: the scripted evaluation should measure the brain, not one parser gap.
- Local adapter: none; the evaluation report now names the brain's language model and says that with the fake model paraphrases outside the table measure the parser path.
- Decision: accepted. The parser reads "share an apartment / a place / a house with (two) roommates / housemates / friends" and "live with my wife / husband / partner / spouse / boyfriend / girlfriend" as `lives_with_parent` false ("live with my mom" still wins as true). Tests in tests/extract/test_parser.py.

### A8 (review) · correction to the re-ask entry above
- Change: none; the sections that entry means are docs/SPEC.md §3.7 (failure behavior: "Unclear answer → `reprompt.unclear` + the closed form; still unclear → conservative value + yellow") and §4 row 11.6, not §3.4 and §3.6.
- Why: citation fix.
- Local adapter: none.
- Decision: noted.

### A3 (review) · gatorplate/dialogue (A3's own files) · done: the review entries addressed to the dialogue
- Change: none requested; status for INT. (1) A5's `live.turn` entry: the brain now publishes one `live.turn` event per transcript line (only with `GP_LIVE_TRANSCRIPT=1`) and appends the turn's lines before `_persist` publishes `case.updated`; the live store must not publish them a second time. (2) A8's re-ask loop: a two-part question answered in part (`ask.age_parent` with the age only) gets one `reprompt.unclear` re-ask, then the missing goal stays unclear with its yellow line. (3) A1's `_open_for_flip`: a band answer (assumed) is open for the plan, so `flip.earned_split` is asked; the split amount comes from `Rules.earned_split_point` when the rules object has it (read with `getattr`, as `llm_health`). (4) A1's band representation: the dialogue half for the split is done (`below_x` → X, `above_x` → the band's top, which is the stored value), so the rules half 2 of that entry (narrowed band after the split) is now safe to apply; `above_b` still stores `b`, the same as the parser's "more than X", pending INT's decision on that entry.
- Why: docs/SPEC.md §3.7, §5.6, §8.6; docs/UI_SPEC.md A3.8.
- Local adapter: none.
- Decision: noted; each item checked at integration.

### A3 (review) · gatorplate/rules (A1) · a capped call states the highest amount when income or rent was never answered
- Change: at the turn cap or the 8-minute cap (`turn_cap` flag, the conversation moved to the result), a missing `earned_monthly`, `other_cash_monthly` or `rent_share` is read as $0, so the spoken estimate is the maximum (a probe: consent, level, age, then 8 minutes pass at the household answer → "about three hundred six dollars a month" with no income or rent answered). Proposal: at a final result, an unanswered income uses the conservative value (docs/SPEC.md §4.9: "an unknown income use[s] the conservative (lowest likely) value") or the result is `coordinator.unresolved` when income or housing is unknown; the dialogue then says whatever the rules decide.
- Why: docs/SPEC.md §3.6 (cap → result with defaults), §5.6 (unknown income is conservative), §2.4 (never over-promise).
- Local adapter: none in the dialogue (it never overrides the rules' tier or amount).
- Decision: accepted. When the dialogue's `turn_cap` flag is set and work or other-cash income was never answered, the rules give `coordinator.unresolved` with the yellow line "Still open and could change the result: …" instead of reading the income as $0. A missing rent keeps its default (it only lowers the estimate). docs/SPEC.md §3 budgets and row 11.19 aligned; tests in tests/rules/test_apply.py; checked on the real wiring with the 8-minute cap.

### A3 (review) · gatorplate/extract/parser.py (A2) · a bare "No" to a money question asked as a number, and English requested on the Spanish web
- Change: (1) the parser reads a bare "No" / "Nobody" / "Nadie" to `ask.other_cash` and `ask.homeless_cost` (main forms, kind number) as "0", and "No" / "None" to `flip.other_utils` as `none`; today they get `reprompt.unclear` and the closed form (safe, one extra turn). (2) `keywords.language_request.en` could also match "speak English" on a Spanish web call; the dialogue now switches to English when the words name English even without `requested_language`.
- Why: docs/SPEC.md §3.6 (fast path for short closed answers), §3.5 (the web follows a language request).
- Local adapter: (1) none needed; (2) `Routing.asks_english` in gatorplate/dialogue/intents.py.
- Decision: (1) accepted: a bare "No" (also "Nope", "No, nobody", "No, nada") to the single-slot `ask.other_cash` gives 0 a month and to `flip.other_utils` gives none; `ask.homeless_cost` already did; a bare "No" to the two-part `ask.income` stays open. Tests in tests/extract/test_parser.py. (2) rejected for guards.json: the dialogue's `Routing.asks_english` adapter already covers "speak English" on the Spanish web.

### A3 (review) · data/content/sentences.*.json (owner/INT decision) · closed mode never asks whether a student under 22 lives with a parent
- Change: decide a closed (keypad) form for the living-situation part of `ask.age_parent`: in closed mode (no model, or two model failures) the brain asks only the closed age band, so `lives_with_parent` stays unknown and a student under 22 who lives with a parent gets an amount instead of `coordinator.parent_household`. A key cannot be added (docs/SPEC.md, the Brain API stays as it is); options: a second closed question built from `ask.household`'s closed form wording, or the rules treating an unknown `lives_with_parent` under 22 as unresolved at the result.
- Why: docs/SPEC.md §3.2 phase 2 (under 22 with a parent → `coordinator.parent_household`, no exceptions), §3.7 (closed mode).
- Local adapter: none; the open question still asks it whenever a model is available.
- Decision: accepted, rules option: a student under the parent-household age whose `lives_with_parent` was never answered gets `coordinator.unresolved` with the yellow line on "Lives with a parent", never an amount (closed mode asks only the age band). No sentence key is added. docs/SPEC.md §3.7 aligned; tests in tests/rules/test_apply.py.

### A9 (review) · data/content/guards.json (A2) · Spanish equivalents of the refund, credit, discount and coverage promises
- Change: add to `output.forbidden.es` a pattern for "recibirás / vas a recibir / va a recibir / tendrás / vas a tener (un, una, tu) reembolso, crédito, descuento, Medi-Cal or cobertura" (the Spanish side of the English pattern `you(?: will|'ll) (?:get|receive) (?:a |an |your )?(?:refund|tax credit|discount|medi-cal|coverage)`), and to `output.forbidden.en` "you will be / you'll be covered or enrolled" (today only "you are / you're covered or enrolled" is blocked); add matching blocked and allowed vectors to `tests`.
- Why: docs/SPEC.md §5.10 (principle 3, honest amounts: the output guard blocks the card's promise phrases) and §6.6 ("Never: a claim that the student is covered, enrolled or will save"); the `format.output` note of guards.json says the programs patterns block promises of refunds, credits, discounts or coverage, but "Recibirás un reembolso", "Vas a recibir un crédito fiscal", "Tendrás cobertura médica" and "You will be enrolled" pass the output guard today. No current card string uses them.
- Local adapter: tests/programs/test_review.py checks every programs string (as written in programs.{en,es}.json and in the swept card views) against these patterns, so the card content cannot introduce them meanwhile; the runtime guard keeps reading only guards.json.
- Decision: accepted. guards.json `output.forbidden.es` gains the "recibirás / vas a recibir / tendrás / vas a tener (un, una, tu, su) reembolso, crédito, descuento, Medi-Cal or cobertura" pattern and `output.forbidden.en` "you will be / you'll be covered or enrolled"; 6 blocked and 3 allowed vectors added to `tests` (check_content: 188 guard tests).
- Update (owner, 2026-10-02 13:00): the display name is GatorPlate again and the phone opening is back to the original 40-word wording, the same as the contract examples; the entry above no longer applies.
