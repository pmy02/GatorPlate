# GatorPlate UI Spec

**Version 2026-10-01.** Layout and behavior truth for every GatorPlate screen: the coordinator console, the student
card, the talk page and the small public pages. Related files:

| What | Where |
|---|---|
| Product rules (conversation, rules engine, privacy) | `docs/SPEC.md` |
| Brain API (phone gateway and talk page) | `docs/BRAIN_API.md`, `contracts/brain_api.v1.schema.json`, `contracts/examples/` |
| Design tokens | `data/design/tokens.json` (source) and `web/shared/tokens.css` (same values) |
| Fonts | `web/shared/fonts/` (SIL Open Font License 1.1, `OFL.txt`) |
| Icons and logo | `web/shared/icons.svg` (original, see A6.6) |
| Design-system check (contrast, tokens, light theme, fonts, icons, CSP-safe pages) | `python3 tools/check_contrast.py` |
| Third-party notices | `NOTICE.md` |

Field and endpoint names in this spec are the contract names (A8). If a contract and this spec ever disagree on a
name, the contract wins and this spec is corrected.

---

## A0. Ground rules for every screen

1. **Light only.** Every page has `<meta name="color-scheme" content="only light">`; `tokens.css` sets
   `:root { color-scheme: only light; }` (this also opts out of automatic dark rendering). No
   `prefers-color-scheme` rules, no dark panels or dark sections.
2. **No official marks.** No SF State logo, seal, mascot art, purple/gold palette or campus fonts; no CalFresh,
   BenefitsCal or county logos, and no logo of any program, agency or utility on the card's unlocked part (Medi-Cal,
   Clipper, Muni, BART, PG&E, California LifeLine, FTB, IRS). Names appear as plain text. Every student-facing screen
   carries:
   "Student-built prototype — not an official SF State, county, or CalFresh service." /
   "Prototipo hecho por estudiantes; no es un servicio oficial de SF State, del condado ni de CalFresh."
3. **Never a rejection.** No screen, string, file or API output contains "not eligible", "ineligible",
   "don't qualify", "denied", "no califica", "no eres elegible" (or variants). This includes console labels: the slot
   `previously_denied` is shown as "Applied before". The guard pattern list is `data/content/guards.json`.
4. **The AI never decides.** Amounts, tiers, deadlines and first-month values come from the rules engine; the UI
   only formats them. Every amount sits next to "estimate — the county decides" (card: "This is an estimate. The
   county decides."). The card's other-program amounts come from the programs engine (`docs/SPEC.md` §5.10), are
   worded "about", "up to" or "maybe", and sit above the footnote "Each agency decides. Not a promise."
5. **Plain language** (grade 6–8) on student screens. The coordinator console is English only.
6. **Only working features are visible.** A control whose backend is missing is hidden, never shown as
   "coming soon".
7. **No promises we can't keep.** No texting, no callback, no live transfer, never "sent to the coordinator", no
   reminder messages (only an `.ics` download), never "any language", no error-rate claims, no eligibility
   decisions, never "you will get", "you'll save" or "free money". There is no "call student" action: yellow lines
   have **Looks right** and **Edit** only.
8. **Privacy on screen.** Never show a Social Security number, card number, immigration status, disability-benefit
   detail, name or phone number of a student. None of these are stored; redacted digits appear as a "number removed"
   pill. Cases are identified by a short code such as `K7Q-2FM` and a one-line summary.
9. **The phone line** is described only as "a hosted voice gateway". No vendor, model or server names anywhere. The
   one exception to "no company names" is the web disclosure (A2.3 and the talk page's `privacy` string in A5.6),
   which names the browser's speech service ("Chrome uses Google's speech service; Safari uses Apple's"): a privacy
   fact about where the voice is turned into text. No other screen names a browser, device or company. The card's
   unlocked part (A4.2, row 2b) may name the public programs, agencies and the one regulated utility a student applies
   to: Medi-Cal, DHCS, BenefitsCal, Clipper START, MTC, Muni/SFMTA, BART, Gator Pass/OneCard, PG&E (CARE, FERA), CPUC,
   California LifeLine, federal Lifeline (FCC, USAC), FTB, IRS and SF State VITA. Never a phone company or any other
   company.
10. **CSP `'self'`.** No inline `<style>`, no `style=""` attributes, no inline scripts or `on…=""` handlers, no
    third-party fonts, scripts or images. Dynamic values (for example the range band position) are set from JS with
    `element.style.setProperty('--lo', …)`, which CSP allows. `tools/check_contrast.py` checks every HTML and CSS file
    under `web/` for these.
11. **Tokens only.** Colors, font families, type sizes, radii, shadows and durations come from `var(--gp-*)`; only
    small geometric offsets in motion (a few px, as in A6.8) may be literal. `tools/check_contrast.py` fails on a color
    literal (hex, color function or color name) in any other CSS, JS or SVG file under `web/`, and on a `font-family`
    that is not one of the font tokens.
12. **No emoji** in the UI. Icons come from `/shared/icons.svg`.
13. **Glyphs.** The self-hosted font files are Latin subsets without `→ ↔ ✓ ≤ ≥`. UI chrome uses icons
    (`i-arrow-right`, `i-check`) or words instead; server-made strings that contain these characters (for example a
    rule-trace row) fall back to the system font for those characters, which is acceptable.
14. **Pacific Time.** Every date and time shown is America/Los_Angeles. A first-month value is always labeled as an
    estimate: the filing date counts as the same day on a weekday before 5 PM PT, otherwise the next weekday.

---

## A1. What the demo must show (wow moments)

| # | Moment | What makes it happen (data) | Guard if it doesn't happen |
|---|---|---|---|
| W1 | **"It only asks what can change the answer."** During Maria's call the Live view shows the chip *Why this question? Could change the estimate by $151: $155 or $306*; the range bar *Between $155 and $306 a month* collapses to *$306 a month · Settled* with a count-up; the chip *Not asked — heating or cooling bill, same estimate either way* (and the same chip for other utility bills). | Maria's facts (A2.1) make "rent paid by someone else to the landlord" the only unknown that can move the estimate by more than $50, and the utility questions worthless. The engine drives the chips and the bar: `asked[]` (kind `flip`, `reason`), the live event's `asked_reason`, `estimate_range`, `timeline[]`, `skipped[]` (reason `no_effect`, chip text from `detail`). The transcript column needs the demo setting `GP_LIVE_TRANSCRIPT=1` (`ConsoleMeta.live_transcript`). | If the judge says the rent fact before it is asked, the chip reads *Answered before we asked — no question needed* (same point). If extraction is slow, the closed yes/no question still comes. |
| W2 | **"My answers, on my phone, in my language."** The judge scans the QR at the end of the call; the card shows *their* numbers, the BenefitsCal answer sheet and the first-month estimate, and switches to Spanish without a reload. | `GP_CARD_DELIVERY=screen` at the table, so the call ends with "scan the QR code on the screen" and the Live view shows the case's QR (`qr_svg_url`) after the end choreography. QR 260 px, black on white, quiet zone of at least 4 modules, screen brightness 100%. The card page is small (A4.1). Both languages are pre-written (no live translation): `GET /api/card/{token}?lang=es`. | The judge declines to scan: open the same card on the team phone and hand it over. |
| W3 | **"The AI can't press the button."** Sofia's sample case has one open yellow line: *Under 22 and living with a parent — the parent's household is counted together. Confirm, then help with a household application.* "Mark reviewed" stays locked; the coordinator clicks **Looks right**, the lock opens, **Mark reviewed**. Then Maria's case: **Mark reviewed**, and the judge's phone shows *Checked by a coordinator · 5:03 PM*. | The server answers `409 locked` to a review while any yellow line is open; the UI lock mirrors it. The card polls `GET /api/card/{token}/status` every 4 s and on `visibilitychange`. *Reset demo* re-seeds the samples before every judge group (A2.5), so Sofia's line is open again each time. | The judge's phone is asleep: "It shows the moment you open it." |
| W4 | **"CalFresh is the key."** Right under the hero, the judge's card shows *Money you may be missing this year — About $3,670 a year* and *Question 1 of 3*. Three taps (*Most weekdays (Muni)* · *No* · *Yes, in a roommate's name*) raise it to $3,830, $4,050 and $4,220 with a count-up, while the console's section 6b *More money (estimates)* fills in live. Then *Share* opens the phone's share sheet (or shows *Copied*). About 20 seconds. | The programs engine and its dated table (`docs/SPEC.md` §5.10, `data/rules/programs_2026.json`) through `CardView.unlocked` (A8.2). Each tap is `POST /api/card/{token}/answers` and returns the re-planned `UnlockedView`; the event `case.updated` with `changed_programs` refreshes the console detail (A8.3). Maria's spreads ($440, $228, $170) fix the question order; golden cases PG2 → PG1. | If the bar fails, show the fixture card (`card_maria_en.json` with `unlocked_maria_steps.json`). With `GP_PROGRAMS=0` the part is absent and W1–W3 run unchanged. |

Details that make it feel finished: words in the transcript light up when they become a field; fields fill with a
soft sweep; the range bar narrows; the transcript wipes itself at the end; the lock opens; the card's yearly total
counts up after each tap.

---

## A2. Demo flows the UI must support

### A2.1 Demo personas (fixtures, seed data and golden cases use exactly these facts)

| Persona | Facts | Expected result |
|---|---|---|
| **Maria** — phone, English (golden dialogue `maria_g1`, golden case G1) | SF State undergrad, junior, 12 units · 20 · lives with two roommates; they buy and cook food separately · campus library job, about $900 a month; nobody gives her cash · rent share $1,100 a month · no separate heating bill · nobody pays her rent to the landlord · **cash on hand about $1,000** | Likely · about $306 a month · 3-day benefits: no · one flip question asked (rent paid by someone else: "could change the estimate by $151: $155 or $306") · heating/cooling and other utility bills not asked (no effect) · 0 yellow lines |
| **Sofia** — web, Spanish (G3), seeded | SF State undergrad, 12 units · 19 · lives with her parents | Coordinator check (`coordinator.parent_household`) · no amount shown · one open yellow line (W3 text) |
| **Jamal** — phone, English (G4), seeded | SF State senior, 12 units · 24 · sleeping on a friend's couch since August, buys his own food · no job, no cash from anyone · pays nothing to stay · about $40 on hand | Likely · about $306 a month · 3-day benefits: yes · tracking: filed 3 days before the seed day and interview (10:00) missed the day before the seed day, each raised to Oct 1, 2026 when earlier (seeded on Fri Oct 2, the test clock: filed Thu Oct 1, interview missed Oct 1, decision due Oct 31, 29 days left) |
| List fillers, seeded | grad student with a TA job (G6-b) · student in a dorm with 14 meals a week (G9) · a case at the $25 minimum (G8) | about $55 a month, status Reviewed · Other help · about $25 a month |

Seeded cases carry `seeded: true`, show a *Sample* tag, and use persona labels such as "Sofia (demo persona)". Their
dates are computed relative to the seed time and never fall before 2026-10-01, the first day of the FY2027 rules
table.

**The card's unlocked part for the personas** (W4; `docs/SPEC.md` §5.10; golden cases in
`data/golden/programs_golden.json`; yearly display values, floored to $10):

| Persona | Card answers | Unlocked part |
|---|---|---|
| **Maria** (PG2, then PG1) | none at first; the judge taps *Most weekdays (Muni)* · *No* · *Yes, in a roommate's name* | full: $3,670 → $3,830 → $4,050 → **About $4,220 a year** = CalFresh $3,670 + Clipper START $160 + California LifeLine up to $220 + PG&E CARE $170 (assumed $140 bill split 3 ways); chips *+ health coverage (Medi-Cal)* and *maybe +$200* (tax credits, not counted); share text "about $4,200" |
| **Jamal** (PG4), seeded | seeded: not claimed as a dependent · rides 1–2 days a week | full: **About $3,980 a year** = CalFresh $3,670 + California LifeLine up to $220 + Clipper START $90; Medi-Cal chip; no PG&E question (no regular place to stay); console list *Found about $3,980/yr* |
| **Sofia** (PG5), seeded | none | list_only: *More help to check with the coordinator* — Medi-Cal (family income may count) and Clipper START; no amounts, no questions, no share |

### A2.2 Maria's call, turn by turn

Follows the golden dialogue `maria_g1` in `docs/SPEC.md` §3.9 (contract example `contracts/examples/maria_phone.json`;
the reply wording there is illustrative, the sentence bank owns it). About 2 minutes, 9 student turns.

| Turn | Student (as Maria) | Next reply (sentence keys) | Console (Live view) |
|---|---|---|---|
| start | — | opening `consent.ask` (A2.3) | *Live call* row slides into the list; the Live view opens (Presenter on) |
| 1 | "Yes, that's fine." | `ack.short` + `ask.level_units` | Consent chip with the time |
| 2 | "I'm an SF State undergrad, a junior, and I'm taking 12 units." | `ack.short` + `ask.age_parent` | Student level and Units fill; the heard words light up |
| 3 | "I'm 20, and I live with two roommates." | `ack.short` + `ask.household_food_roommates` | Age, Lives with a parent (no), Lives with roommates fill |
| 4 | "Separately." | `ack.short` + `ask.income` | Buys and cooks food: separately |
| 5 | "I work at the campus library, about 900 a month. Nobody gives me cash." | `readback.earned` + `ask.rent` | Work income $900/mo; Cash from family $0 |
| 6 | "Eleven hundred." | `readback.rent` + `flip.intro` + `flip.rent_paid_by_others` | Rent share $1,100; the range bar appears at $155–$306; W1 chip *Why this question? Could change the estimate by $151: $155 or $306* |
| 7 | "No." | `result.likely` + `expedited.intro_cash` | Rent paid by someone else: no; the bar collapses to *$306 a month* (count-up) · *Settled*; *Not asked* chips for heating/cooling and other utilities |
| 8 | "About a thousand." | `first_month.apply_today` + `card.phone_screen` + `close.anything_else` | Money on hand $1,000; 3-day benefits: no; card QR ready |
| 9 | "No, thanks." | `close.goodbye` (end) | *Call ended* → bubbles fade → *Conversation cleared — not saved. {n} answers kept.* → 260 px QR panel |

`{n}` is the number of slots with a value; the UI counts it.

**After turn 9: the card (W4).** The judge scans the QR; the card opens with the hero (*about $306 a month*) and,
directly under it, the unlocked part. Answers are accepted only after the call has ended (A8.3).

| Step | Judge on the card | Card (unlocked part) | Console (case detail, section 6b) |
|---|---|---|---|
| 1 | opens the card | *About $3,670 a year · You've started $0 of $3,670*; chips *+ health coverage (Medi-Cal)*, *Riding over breaks? about $90–$440*, *maybe +$200*; *Question 1 of 3*: rides over breaks | CalFresh likely $3,670 · Clipper START *Check* · California LifeLine *Check* · PG&E CARE *Check* · Medi-Cal *Coverage* · tax credits *Maybe* |
| 2 | taps *Most weekdays (Muni)* | counts up to $3,830; *Question 2 of 3*: tax dependent | the Clipper START row sweeps in: *Likely* $160, "10 rides/week × 17 break weeks; …"; *From the card* shows the answer |
| 3 | taps *No* | $4,050; *Question 3 of 3*: the PG&E bill | California LifeLine *Likely*, up to $220 |
| 4 | taps *Yes, in a roommate's name* | $4,220; the question area is gone; *Share* | PG&E CARE *Likely* $170 (assumed $140 a month split 3 ways); footer *Found about $4,220 a year (CalFresh $3,670 + 3 programs)*; the list row shows *Found about $4,220/yr*; the gray note *Card: the home has its own PG&E bill. Call: no utility bills. …* appears (expected: Maria's call left the natural default "no utility bills", and $306 is already the maximum, so nothing changes — PG1) |
| 5 (optional) | *Share*, or *I applied* on CalFresh in *Your plan* | share sheet or *Copied* · *You've started $3,670 of $4,220* | the *I applied* mark with its time |

### A2.3 The opening (what the student hears and sees first)

- **Phone** (the `/start` reply; never interruptible): say *"Hi, this is GatorPlate, a student-built AI assistant,
  not an official SF State service. An AI turns what you say into text to check CalFresh for you; the call audio
  isn't recorded."* ask *"Okay to start? Say yes, or press one."* Together that is exactly 40 words, the opening
  budget; phone text never contains digits. This is the bank's canonical phone `consent.ask`. Yes or key 1 continues;
  no or key 2 gives the coordinator contact and ends; an unclear answer gets one re-ask, then counts as no. The console
  transcript shows it as the first GatorPlate bubble.
- **Web** (talk page, first reply, shown and spoken): *"Hi, I'm GatorPlate, a student-built AI assistant, not an
  official SF State service. Your browser turns your voice into text (Chrome uses Google's speech service; Safari
  uses Apple's). GatorPlate only gets the text and never stores audio."* + *"Is that okay?"* — Spanish in the
  sentence bank (see `contracts/examples/sofia_web_es.json`). Quick replies come from `choices`. Naming the browsers
  and their makers here is the only company naming allowed in product text, apart from the public programs and the
  regulated utility on the card's unlocked part (A0.9).
- The sentence bank (`data/content/sentences.{en,es}.json`) owns the final wording; screens never hard-code it.

### A2.4 Fallbacks

| Situation | Move | What the screens must offer |
|---|---|---|
| No ring or no audio within 10 s | Switch to the web line: `Shift+T` opens the talk page on the laptop (earbuds); the judge speaks or types; the console fills the same way. | `Shift+T`; talk page typing mode and quick replies |
| A number is misheard | The repeated number catches it; the judge corrects it. | The row shows *changed from $900* (`changed_from`): point at it, it is a feature |
| The judge hangs up early | Nothing is lost; continue with Sofia. | *Ended early* chip, answers kept, range bar kept, yellow line *Call ended before the result* |
| App unreachable | `R` replays an already-loaded case at 2× from the console's memory; open the card on the team phone; if still down, the backup video. | Replay works without the server; *REPLAY* badge |
| Hall too loud for the phone | The judge steps away from the speakers, or uses the web line with typing. | Talk typing mode |

### A2.5 Reset, seed and pre-flight

- **Reset between judge groups (30 s):** `Shift+D` → *Reset demo*, which sends `POST /api/demo/reset` (removes every
  case that is not seeded, so the last judge's call and card are gone) and then `POST /api/demo/seed` (re-seeding
  replaces the samples, so Sofia's yellow line is open and her case is *New* again for W3) → Live view idle → collect
  the persona cards. The menu shows *Reset · removed N, samples restored* from the two responses.
- **Seed samples:** `Shift+D` → *Seed samples* (`POST /api/demo/seed` alone): Sofia, Jamal and the three fillers, with
  dates relative to the seed time (never before 2026-10-01). Run after a deploy or a purge. Jamal's seed carries two
  card answers (source `seed`), so his row shows *Found about $3,980/yr*; Sofia's carries none.
- **Card answers belong to the case:** *Reset demo* removes the judge's card answers and *I applied* marks together
  with the judge's case, so every group starts Maria's card at *Question 1 of 3*.
- **Live view idle:** the demo number in large type (`demo_phone_display`; hidden when empty), the talk page
  address with its QR (`GET /api/qr/talk.svg?lang=en`), and the rules pill *Rules FY2027 · in effect Oct 1, 2026*.
- **Pre-flight (60 s, before each group):** a warm-up call appears in the list → *Reset demo* (reset, then seed) →
  samples present and Sofia shows *1 to check* → Live view idle → Presenter on.

### A2.6 Replay (`R`)

Replays the selected case at 2× speed without the server: it steps through `timeline[]` (the gaps between `at`
values halved, each step 0.6–3 s), fills the slots whose `turn` has been reached, moves the range bar to that
entry's `lo`/`hi`, and shows the `asked[]` and `skipped[]` chips at their turns. No transcript. A *REPLAY* badge stays
visible the whole time; `Esc` stops it. Replay never writes to the server.

### A2.7 Presenter mode and shortcuts

- **Presenter (`P`):** root font 112.5% (`html.presenter`); no text below 15 px — the 13 px panel labels
  (`--gp-fs-label`, 14.6 px at 112.5%) switch to `--gp-fs-small` (15.75 px) in Presenter; key numbers at least 32 px;
  hides filters and second-level meta; when a call starts, opens the Live view automatically (only if no other live
  call is being followed).
- **Shortcuts:** `L` Live view · `P` Presenter · `R` replay the selected case at 2× · `Shift+T` open the talk page
  in a new tab · `Shift+D` demo menu · `Esc` back to the work view or close the open menu · `?` shortcut list. In the
  case list: `↑`/`↓` move, `Enter` opens.
- Shortcuts never fire while focus is in a text field, select or editable area, or with Ctrl, Cmd or Alt held. The
  `?` popover has a *Keyboard shortcuts* switch that turns the single-key shortcuts off (WCAG 2.1.4).

### A2.8 Judge improvisation: what each screen does

The brain's wording comes from the sentence bank; this table lists what the screens must show.

| Judge does | Brain (expected) | Console | Card |
|---|---|---|---|
| Gives hourly pay ("$20 an hour, about 15 hours a week") | Repeats rate and hours back | Work income shows the monthly amount with its formula (`display`); the estimate comes from the rules table (golden case G12: $266) | Answer sheet shows the student's numbers |
| Corrects a number ("actually 1,000") | Applies the correction and repeats it | New value with *changed from $900* (`changed_from`) | Updated |
| Says they share food with roommates | One closed question; if still shared, routes to a coordinator | Tier *Coordinator check*, reason *Shares food with others* | Coordinator hero |
| "My parents pay my rent to the landlord" | One more question (heating or cooling bill), then about $155 (G1-b) | The flip chip shows the answer moved the estimate; the bar settles at $155 | $155 |
| Speaks Spanish on the phone | One Spanish line pointing to the web page, then English | Chip *Spanish requested — web page offered* (`language_request`) | — |
| Hangs up early | — | *Ended early*, answers kept, yellow line, bar kept | No card link was given |
| Says an SSN or card number | Guidance, then the question again | Transcript shows a *number removed* pill; chip *SSN blocked — not saved* (`privacy_events`) | — |
| "So am I eligible?" | The county decides, plus the estimate | Normal | Normal |
| "Are you a robot? Is this recorded?" | Says it is an AI; the call audio isn't recorded | Visible in the live transcript only | — |
| "Can I talk to a person?" | Coordinator number and hours; no transfer; then asks whether to keep going (no ends the call politely) | Chip *Asked for a person* (flag `human_requested`) | *Talk to a person* section |
| Mentions an immigration status | Respectful other-help or coordinator line; never asks for documents | Tier with a generic reason (*Status-related — other help offered* or *Status question — needs a person*); the status itself is never shown or stored; *Never asked: immigration status* stays | Other-help or coordinator hero |
| Very high income ("$4,000 a month") | Other-help line; the county decides | Tier *Other help*; trace row with the FY2027 gross limit ($2,660 for 1 person) | Other-help hero |
| Lives in a dorm with a meal plan | Asks meals per week (more than 10 means other help) | Trace row with the meal count | Per result |
| Grad student | Exemption question | Per answers | Per result |
| Silence or "um" | Asks again, then the closed form | Transcript only | — |
| Tries to make it say "eligible" or "not eligible" | Stays on task: the county decides | Normal | Normal |
| Crisis words | 988 and 911 at once | Chip *Safety message given* (flag `crisis_resources_given`) | — |

Never test crisis words on purpose. If they come up, stop the demo and be human.

---

## A3. Coordinator console

### A3.1 Users, route, access

- Users: the SF State CalFresh coordinator (pilot); judges watching from 0.8–1.5 m (demo).
- Route `/console`, **password required**: one shared passcode from the server setting `GP_CONSOLE_PASSCODE`;
  `POST /api/console/login` sets a session cookie; any `401` shows the login screen and returns to the same case
  after login. Never public, even in the demo (real students may use the public talk page).
- The top bar always shows the label *Prototype coordinator view*.
- Data: `GET /api/meta` (ConsoleMeta), `GET /api/cases` (list), `GET /api/cases/{id}` (CaseDetail), Server-Sent
  Events from `GET /api/events` (A8.3). Fallback: after two SSE errors, or 25 s without a message or ping, poll
  `GET /api/cases?since_seq=N` every 1 s and retry SSE every 30 s; refetch on `visibilitychange`. A pill in the top
  bar shows *Live* (SSE) or *Polling*. List rows update from the event's `summary`; for the case on screen (and the
  followed live call) a `case.updated` event, or a changed `version` in the polled list, triggers
  `GET /api/cases/{id}`, because `estimate_range`, `timeline`, `asked`, `skipped`, `yellow_lines`, `qr_svg_url` and
  `programs` live only in CaseDetail. A card answer or *I applied* mark bumps the case `version` and sends
  `case.updated` with `changed_programs: true`. Animations are triggered by the diff between the old and the new
  CaseDetail (`changed_slots` names the filled slots), so both paths look the same.

### A3.2 Layouts

| Width | Layout |
|---|---|
| 1600 px and wider | Work view: list 360 + detail. Live view: transcript 44% · answers 32% · estimate, why and QR 24%. Root font 112.5%. |
| 1280–1599 (1366×768 laptop) | Work view: top bar 56, list 320, detail fluid (max 1040). Live view: transcript 56% · right panel 44%. |
| 1024–1279 | List 280; detail sections stack; Live view = transcript above answers. |
| below 1024 | Single column (not used in the demo). |

Work view, 1366×768:
```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ [logo] GatorPlate  Coordinator · Prototype coordinator view                                                        │
│ [Rules FY2027 · in effect Oct 1, 2026]  [Live]  [Sample data]  [Presenter]  [Demo]                                 │
├────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ AI listens  >  Rules decide  >  A person confirms                                                                  │
├───────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────┤
│ Cases               6 │ Case K7Q-2FM · Phone · English · consent 5:01 PM · 1:52     [Open student card] [...]      │
│ [Needs review]        │ ┌ LIKELY  $306 a month ──────────┐  ┌ If filed now (estimate) ─────────────────────────┐   │
│ [Live]  [All]         │ │ estimate — the county decides  │  │ counts from Mon, Oct 5 — about $266 for October  │   │
│ (o) LIVE  5:01  1:12  │ └────────────────────────────────┘  └──────────────────────────────────────────────────┘   │
│ 5:12  EN  Phone       │ To check (0)                                                   [ Mark reviewed ]           │
│   Likely $306/mo      │ Answers · Why these questions · How we got $306 · More money · Tracking · Student card     │
│ 4:58  ES  Web         │                                                                                            │
│   Sample · 1 to check │                                                                                            │
└───────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────┘
```
Live view, 1366×768 (Presenter):
```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ (o) Live call · Phone · EN · 01:12 · Not recorded · Consent 0:09                             [Exit live view · L]  │
├─────────────────────────────────────────────────────┬──────────────────────────────────────────────────────────────┤
│ GATORPLATE                                          │ ESTIMATE SO FAR                                              │
│ Does anyone, like a parent, pay part of your        │ $155 [==============================] $306                   │
│ rent straight to your landlord?                     │ Between $155 and $306 a month · Not settled yet              │
│                                                     │ NOW ASKING — WHY                                             │
│                                       STUDENT       │ ($) Why this question? Could change the estimate             │
│ "I work at the campus library, about                │     by $151: $155 or $306                                    │
│  [900 a month]. Nobody gives me cash."              │ ANSWERS                                                      │
│                                                     │ Student level    Undergrad   "an SF State undergrad"         │
│                                                     │ Work income      $900/mo     "about 900 a month"             │
│                                                     │ Rent share       $1,100/mo   "Eleven hundred"                │
│                                                     │ Rent paid by someone else   —                                │
│                                                     │ NOT ASKED Heating or cooling bill — same estimate either way │
│                                                     │ NEVER ASKED  Social Security number · immigration status     │
└─────────────────────────────────────────────────────┴──────────────────────────────────────────────────────────────┘
```

### A3.3 Top bar and how-it-works strip

- Logo (`gp-logo`, brand color) + wordmark *GatorPlate* + *Coordinator* · *Prototype coordinator view* label · rules
  pill *Rules FY2027 · in effect Oct 1, 2026* (opens a drawer with the table label, the effective dates and every
  source with its date, from `ConsoleMeta.rules`) · connection pill *Live* / *Polling* · neutral *Sample data* badge
  when `demo_mode` · Presenter toggle (`P`) · demo menu (`Shift+D`, only when `demo_mode`): *Seed samples · Reset
  demo · Replay case · Show card QR · Follow live calls on/off* · *Log out* (`POST /api/console/logout`, then the login
  screen).
- Below the top bar, in the work view and the Live view, one quiet line: *AI listens* (`i-quote`), *Rules decide*
  (`i-table`), *A person confirms* (`i-person-check`), with `i-chevron-right` between the steps.

### A3.4 Case list

- Segments with counts: **Needs review** (status `new` and either an open yellow line or tier `coordinator`) ·
  **Live** · **All**.
- Row, 72 px. Line 1: time (PT) · channel icon (`i-phone` / `i-globe`) · language tag EN/ES · case code. Line 2:
  tier chip + estimate (`$306/mo`, tabular) or "—" · summary (`Undergrad · 1 person · work $900 · rent $1,100`, one
  line, ellipsis). Right side: yellow badge *1 to check* or a check icon, status text, next deadline chip if any.
- Under the summary line, only for a case whose `found_display` is not `null` (a likely case with a programs result):
  small tabular text in `--gp-text-2` (`fs-small`), *Found about $4,220/yr* (Jamal's seeded row: *Found about
  $3,980/yr*). The row grows to fit this third line. The word *about* is used instead of an approximately-equal sign,
  which the self-hosted font does not have (A0.13). The text updates from the event's `summary` when the student
  taps on the card.
- Live rows are pinned on top: 3 px left bar in `--gp-live`, pulsing live dot, elapsed time. Seeded rows show
  *Sample*.
- Sort: live first, then newest. Keyboard: `↑`/`↓` move, `Enter` opens; the open row has `aria-current="true"`.
- Cases are identified by `code` and `summary` only: no names are collected.

### A3.5 Case detail (order on the page)

1. **Header:** *Case K7Q-2FM* (`.code`) · channel · language · consent time (`consent.at`) · duration (from
   `created_at` to the last `timeline[].at`; while live, the elapsed time) · *Open student card* (only when `card_url`
   exists) · overflow menu (*Delete case*).
2. **Summary band:** tier chip · estimate in 56 px tabular figures with "a month" (`estimate_is_floor` → "at least
   about") · caption *estimate — the county decides* · 3-day chip when `expedited_possible` is `yes` (*3-day
   benefits possible*) or `maybe` (*3-day benefits: maybe*) · first-month box *If filed now (estimate): counts from
   Mon, Oct 5 — about $266 for October* (`first_month.filed_on`, `first_month.amount`, `first_month.month_label`) ·
   status select (`allowed_status`). Coordinator and other-help cases show the reason label (A3.11) instead of an
   amount.
3. **To check** (yellow lines) and the **lock bar** (A3.6).
4. **Answers**, grouped *Student · Household · Money · Housing · 3-day check · Other · From the card*. Columns:
   field label · value (`display`, semibold, tabular) · state · *student said* quote (`heard`, italic, one line, full
   text on hover and focus; a Spanish quote shows the original plus *Translation (AI): …* from `heard_en`) · source
   icon. A changed value shows *changed from $900* (`changed_from`); a confirmed value (`confirmed`) shows
   `i-check-double`.
   - States: `clear` → `i-check` *Clear* · `assumed` → gray *Assumed* · `unclear` → yellow *Unclear* ·
     `missing` → "—".
   - Source icons, with a legend: `i-quote` from the student's words (`llm`, `parser`) · `i-keypad` phone keypad
     (`keypad`) · `i-person-check` set by the coordinator (`coordinator`) · `i-table` default assumption from the
     rules table (`default`) · *Sample* tag (`seed`).
   - Slot labels (proposed for the contract's slot specs; console only):

     | Group | Slot → label |
     |---|---|
     | Student | `level` Student level · `units` Units this term · `half_time` Half-time or more · `grad_exemption` Grad student exemption · `ta_ra` TA or RA job · `age` Age |
     | Household | `lives_with_parent` Lives with a parent · `roommates` Lives with roommates · `roommates_count` Number of roommates · `household_food` Buys and cooks food · `dorm_on_campus` Lives in a campus dorm · `meals_per_week` Meal plan, meals a week · `dorm_meals_over_10` Meal plan over 10 meals a week · `spouse` Spouse or partner · `spouse_student` Spouse is a student · `children_count` Children · `youngest_child_age` Youngest child's age · `boarder` Pays for room and meals |
     | Money | `earned_monthly` Work income · `work_study_monthly` Work-study · `gig_monthly` Self-employment · `unearned_monthly` Other income · `other_cash_monthly` Cash from family or friends · `dependent_care_monthly` Child or dependent care |
     | Housing | `homeless` No regular place to stay · `homeless_shelter_cost_monthly` Pays to stay · `rent_share` Rent share · `rent_paid_by_others_to_landlord` Rent paid by someone else · `heat_cool` Heating or cooling bill · `other_utils` Other utility bills |
     | 3-day check | `cash_on_hand` Money on hand now |
     | Other | `already_receiving` Already gets CalFresh · `applied_waiting_interview` Applied, waiting for the interview · `previously_denied` Applied before · `income_changing_soon` Income changing soon |

     `consent` appears in the header. `volunteered_status` and `elderly_or_disabled` are routing only and are never
     shown.
   - **From the card** (only when `program_answers` is not empty): one read-only line of the card answers with the
     source icon `i-person` + *card* and the time of the newest answer, for example *Rides over breaks: most
     weekdays (Muni) · Tax dependent: no · PG&E bill: roommate's name — from the card, 4:12 PM*. Jamal's seeded
     answers carry the *Sample* tag. No coordinator edit. Labels (console only):

     | Answer → label | Choices → label |
     |---|---|
     | `break_transit` Rides over breaks | `none` no, or away · `two_days` 1–2 days a week · `weekdays_muni` most weekdays (Muni) · `weekdays_bart` most weekdays (with BART) |
     | `tax_dependent` Tax dependent | `no` no · `yes` yes · `not_sure` not sure |
     | `pge_bill` PG&E bill | `own_mine` student's name · `own_roommate` roommate's name · `in_rent` in the rent · `not_sure` not sure |
5. **Why these questions:** *Asked* (each `asked[]` entry with its reason chip, A3.10; flip questions also list
   their `outcomes`) · *Not asked* (`skipped[]`) · *Never asked* (fixed: Social Security number · immigration
   status). Counter *Asked N · Not asked M (wouldn't change the result)* from the summary's `asked_count` and
   `skipped_count`. The card's tax-dependent question is shown under *From the card*, never under *Asked*, and
   *Never asked* stays exactly Social Security number and immigration status.
6. **How we got $306:** collapsed by default; header *Computed by the rules table — not by AI*. One row per
   `rule_trace[]` step (`result`, `value`) with a source chip (`source`, resolved against `rules.sources` for the
   title and date). Maria's example (engine wording may differ; amounts from CDSS ACIN I-40-26, 2026-09-10):
   - Student rule: SF State undergrad, at least half-time, bachelor's program → exemption met (CDSS ACL 26-25)
   - Household: lives with roommates, buys food separately → 1 person
   - Gross income $900 ≤ $2,660 (200% limit, 1 person, FY2027)
   - Earned-income deduction 20%: −$180 · standard deduction −$217 → $503
   - Shelter: $1,100 − half of $503 ($251.50) = $848.50 → capped at $769
   - Net income: $503 − $769 → $0
   - Estimate: $306 − 30% × $0 = **$306**

   **6b. More money (estimates):** right after *How we got $306*, collapsed by default like it; present when
   `CaseDetail.programs` is not `null`. Header *Computed by the programs table — not by AI · checked Oct 1, 2026*
   (`programs.checked`). In full mode, one row per `programs.lines[]` entry in plan order:
   - Columns: **Program** (console label below) · **Status** chip · **Per year** (`display_yearly`, tabular; "—" when
     not counted; a `check` line with a range shows *$90–$440*) · **How** (the `basis[]` lines as sent, for example
     *10 rides/week × 17 break weeks; weekly cap (86 − 43) × 12/52 = $9.92 → $168*) · **Source** (title and date of
     each `source_ids[]` entry from `ConsoleMeta.programs.sources`) · **Student** (`i-check` + *Applied 4:12 PM* when
     `applied`, with the time from the case's `program_progress`; otherwise "—").
   - Footer row: *Found about $4,220 a year (CalFresh $3,670 + 3 programs) · not counted: Medi-Cal coverage, maybe tax
     credits $200* (from `found_display`, `calfresh_yearly` floored to $10 and the uncounted lines).
   - Program labels (`ConsoleMeta.programs.names`, the `program.<id>` strings of `programs.en.json`): `calfresh` CalFresh ·
     `medi_cal` Medi-Cal · `clipper_start` Clipper START · `lifeline` California LifeLine · `care` PG&E CARE ·
     `tax_credits` Tax credits (CalEITC, EITC).
   - Status chips (A6.5 pill, always with the word): `likely` *Likely* (likely colors, `i-check-circle`) · `maybe`
     *Maybe* · `check` *Check* · `coverage` *Coverage* · `zero` *Not counted* · `note` *Note* (all but *Likely*
     neutral: sunken with `--gp-text-2`). Never yellow.
   - **Gray notes** from `programs.console_notes` (never yellow, never blocking, no action), with the text from
     `ConsoleMeta.programs.console_texts`: `care.utility_conflict` → *Card: the home has its own PG&E bill. Call: no
     utility bills. Check the utility questions (no change when the estimate is already the maximum).* Maria's demo
     case shows it after the third tap (A2.2 step 4); that is expected.
   - **list_only** cases (for example Sofia): one line instead of the table, *Programs to check with the student:
     Medi-Cal (family income) · Clipper START* (names of the lines that are not hidden; Medi-Cal with the note
     `medi_cal.family_income` adds *(family income)*).
   - **Live:** a `case.updated` event with `changed_programs` refetches the detail (A3.1). The first such event while
     the case is on screen opens the section once (the user can close it again); changed rows and the footer use the
     field-fill sweep (A6.8), so the console fills while the judge taps.
7. **Tracking** (A3.9).
8. **Student card:** QR (`qr_svg_url`) at 260 px in a white panel (A6.5), *Open card*, the case code, and the short
   code when one exists (`short_code`, shown in groups: *481 206*).
9. **Danger zone:** *Delete case* (confirm dialog; `DELETE /api/cases/{id}`; toast *Case deleted*).

### A3.6 Yellow lines and the review lock

- A **yellow line** is something a person must check: an answer the system assumed or could not settle that can
  change the tier, the amount or 3-day benefits; a policy check (for example under 22 and living with a parent); a
  call that ended before the result; or a student's side question. An assumption with no effect is **not** a yellow
  line; it appears as a gray *Not asked* or *Assumed* chip (otherwise the lock creates busywork and people start
  clicking through).
- Card anatomy: reason (`reason`, h3) · what the student said (`heard`, quote) · what we assumed (`assumed`) ·
  effect (`effect`: `amount` → *Could change the estimate by $40* from `delta_usd`; `tier` → *Could change the
  result to Coordinator check*; `expedited` → *Could change 3-day benefits*) · actions **Looks right** and **Edit**,
  right-aligned (stacked below 1280 px).
- **Looks right** sends `POST /api/cases/{id}/yellow/{yid}` `{"action": "confirm", "expected_version": n}`.
  **Edit** opens the value inline; *Save* sends `{"action": "edit", "value": "…", "note": "…", "expected_version": n}`;
  the server re-runs the rules and the UI shows the change (*$306*, `i-arrow-right`, *$155*); the field then carries
  the coordinator source icon.
- No *confirm all* and no *call student*: each line is its own decision. A resolved line collapses to one row with
  `i-check` and the time (*Checked · 5:03 PM*).
- **Lock bar:** while any line is open, the button reads *Mark reviewed* with `i-lock`, has `aria-disabled="true"`
  (not the `disabled` attribute, so it stays focusable) and a visible reason *Check 1 line first* linked by
  `aria-describedby`; activating it moves focus to the first open line. With no open lines it is the primary *Mark
  reviewed*; on unlock the icon crossfades from `i-lock` to `i-unlock` (200 ms). It sends
  `POST /api/cases/{id}/status` `{"status": "reviewed", "expected_version": n}`.
- Server answers: `409 locked` while any yellow line is open (the lock cannot be bypassed); `409 conflict` for a live
  case or a stale `expected_version`: refetch and show the toast *This case changed — showing the latest.* While the
  call is live the lock bar reads *Available after the call ends*.
- After review: status *Reviewed · 5:03 PM*; the student card's status endpoint flips (W3).

### A3.7 Status model

Statuses (`status`; changes are server-enforced through `allowed_status`): `new` *New* · `reviewed` *Reviewed* ·
`applied` *Applied* · `interview_scheduled` *Interview set* · `approved` *Approved* · `follow_up` *Follow up*.
Badges that are not statuses: *Live* (`live`) · *Ended early* (`ended_early`, a field of the case and of the list row,
not an entry of `flags[]`) · *Sample* (`seeded`). The review time is `reviewed_at`.

### A3.8 Live view

- **Header:** live dot · *Live call* · channel · language · elapsed time · *Not recorded* tag · consent chip
  (*Consent*, `i-check` and the time).
- **Transcript** (demo setting `GP_LIVE_TRANSCRIPT=1`, which the console reads as `ConsoleMeta.live_transcript`;
  lines arrive as `live.turn` events, and a console that opens mid-call first loads `GET /api/cases/{id}/live`;
  process memory only, never stored): GatorPlate bubbles on the left (`--gp-sunken`, label *GatorPlate*), student
  bubbles on the right (`--gp-primary-tint`, label *Student*).
  18 px (20 px in Presenter). Sticks to the bottom unless the user scrolled up; older bubbles fade to 60%. Redacted
  digits arrive as the replacement text `[REDACTED]` (`data/content/guards.json`, `input.redact.replacement`) and show
  as a *number removed* pill; a run of `#` from the phone gateway's masking shows the same way. Without the setting,
  this column shows *Now asking* in large type and the newest answer's quote (`heard`).
- **Word-to-field highlight:** when a field fills, its `heard` text is marked in the newest student bubble that
  contains it (`<mark class="heard">`, exact substring); hovering or focusing a field highlights its words. This is
  the visible proof of what the AI understood.
- **Now asking — why:** the question (`now_asking_text` from the latest event) and its reason chip (`asked_reason`):
  outcome-changing reasons use the primary chip with a `$` badge; routine ones are gray.
- **Estimate so far:** range bar (A6.5) from $0 to the largest `hi` seen in this case (it never shrinks during the
  call); band `[lo, hi]` from `estimate_range`. Label *Between $155 and $306 a month · Not settled yet*; when
  `settled`: *$306 a month* (450 ms count-up) · *Settled*. No `estimate_range` yet: empty track and *Estimate appears
  after income and rent*. Coordinator and other-help cases show the reason label instead of the bar.
- **Answers:** compact rows; pending rows show "—"; fill animation (A6.8).
- **Not asked / Never asked** chips at the bottom.
- **Other chips, only from data:** *SSN blocked — not saved* / *Card number blocked — not saved* (one per
  `privacy_events[]` entry; kind and time only) · *Asked for a person* (`human_requested`) · *Safety message given*
  (`crisis_resources_given`) · *Spanish requested — web page offered* (`language_request`; the chip opens a QR of the
  Spanish talk page, `GET /api/qr/talk.svg?lang=es`, so the student can switch to the web) · *Simple questions mode*
  (`closed_mode`).
- **End choreography:** on `live.ended` (or `live` turning false): *Call ended · 1:52*; after 1.5 s the bubbles fade,
  blur and rise (600 ms) and are **removed from the DOM**; the panel reads *Conversation cleared — not saved. {n}
  answers kept.*; then the 260 px QR panel appears when the case has a card. `Esc` returns to the work view on this
  case.
- **Second live call** (someone scans the poster mid-demo): the Live view keeps following the call it opened; a pill
  *Another live call (1)* appears. No automatic switch.
- **No events for 60 s** on a live case: hint *No activity for 1 min — the call may have dropped.* The server closes
  idle calls after 10 minutes.

### A3.9 Tracking (deadlines from the engine, shown as countdowns)

- Timeline steps, joined by a line (horizontal at 1280 px and wider, vertical below): Called · Filed · Interview ·
  Papers · Decision due · Approved · SAR 7 due · Renewal due.
- Coordinator inputs: filed date, interview date or *missed*, papers-requested date, approved date, sent with
  `PATCH /api/cases/{id}/tracking`.
- Computed by the engine (`tracking`): decision due (`deadline_30d`), papers due (`doc_due`), SAR 7 due
  (`sar7_due`), renewal (`recert_due`). The UI only displays them. The SAR 7 day (about the 5th, late after about the
  11th) is not verified yet, so its chip always reads as approximate: *SAR 7 due about Apr 5*, never an exact date
  (`docs/SPEC.md` §5.7). The text for a missed interview comes from the engine or content, with the county number
  (855) 355-5757.
- Countdown chips: neutral above 7 days (*29 days left*) · amber (coordinator colors) at 7 days or less (*5 days
  left*) · amber, bold, with `i-hourglass` at 2 days or less (*Due in 2 days*). Red is only for system errors, never
  for deadlines or results.
- Sample Jamal: filed 3 days before the seed day and interview missed the day before the seed day, each raised to
  Oct 1, 2026 when earlier (`data/demo_cases/jamal_g4.json` `tracking`). Seeded on Oct 1 or Oct 2 both dates are
  Oct 1; on Fri Oct 2 (the test clock) his decision-due chip reads *29 days left* (due Oct 31); from a seed on Oct 4
  on, the dates are exactly 3 days and 1 day back. His chips come from the engine.

### A3.10 Reason-chip copy (data → chip)

| Data | Chip text | Style |
|---|---|---|
| `asked[]` kind `flip` | *Why this question?* + `reason` (e.g. *Could change the estimate by $151: $155 or $306*) | outcome-changing |
| `asked[]` kind `standard` | *Needed for any estimate* | routine |
| `asked[]` key `expedited.intro_cash` | *Checks 3-day benefits* | routine |
| `asked[]` kind `confirm` | *Repeated back to confirm a key number* | routine |
| `asked[]` kind `band` | *Asked for a range — the exact amount wasn't known* | routine |
| `asked[]` kind `closed` or `reprompt` | *Asked again in a simpler form* | routine |
| a flip-candidate slot with a student value that no `asked[]` entry lists in its `slots` | *Answered before we asked — no question needed* | routine |
| `skipped[]` reason `no_effect` | `detail` as sent, e.g. *Not asked — heating or cooling bill, same estimate either way* | not asked |
| `skipped[]` reason `below_threshold` | `detail` as sent, e.g. *Not asked — assumed $0; changes the estimate by $50 or less* | not asked |
| `skipped[]` reason `max_questions` | `detail` as sent: *Not asked — question limit; see the yellow line* | not asked, with a yellow dot |
| `skipped[]` reason `hard_stop` or `not_applicable` | not shown | — |
| fixed | *Never asked — Social Security number · immigration status* | never asked |

Flip candidates are the slots in the rules table's question-picker priority list (`household_food`,
`rent_paid_by_others_to_landlord`, `other_cash_monthly`, `earned_monthly`, `heat_cool`, `other_utils`).
The server writes `reason` and `detail` (their wording is fixed by the rules table and
`gatorplate.contracts.console_text`); the console shows `detail` unchanged and only capitalizes the first letter of
`reason` after *Why this question?*.

### A3.11 Reason codes and tier chips

| Code | Console label |
|---|---|
| `likely` | Likely |
| `coordinator.parent_household` | Under 22, lives with a parent |
| `coordinator.shared_household` | Shares food with others |
| `coordinator.grad_no_exemption` | Grad student — no exemption found |
| `coordinator.not_degree` | Not in a degree program |
| `coordinator.age_outside_student_rule` | Age outside the student rule |
| `coordinator.gig_income` | Self-employment income |
| `coordinator.boarder` | Pays for room and meals |
| `coordinator.spouse_student` | Spouse is also a student |
| `coordinator.status_complex` | Status question — needs a person |
| `coordinator.elderly_disabled` | Age or disability rules — needs a person |
| `coordinator.unresolved` | An answer that changes the result is open |
| `other_help.status` | Status-related — other help offered |
| `other_help.over_gross_limit` | Income above the gross limit |
| `other_help.dorm_meal_plan` | Dorm meal plan over 10 meals a week |
| `other_help.not_sfsu` | Not an SF State student |
| `other_help.zero_benefit` | Estimate is $0 — other help offered |
| `info.already_receiving` | Already gets CalFresh |
| `info.interview_waiting` | Waiting for the county interview |

Tier chips: `likely` *Likely* (`i-check-circle`, likely colors) · `coordinator` *Coordinator check* (`i-person`,
coordinator colors) · `other_help` *Other help* (`i-heart-hand`, other colors).

### A3.12 Empty, loading and error states

| State | What shows |
|---|---|
| Empty (no cases) | *No calls yet. When a student calls {demo number} or opens the talk page, the case appears here live.* + the talk page address and its QR (`GET /api/qr/talk.svg?lang=en`). Without a demo number the first sentence starts *When a student opens the talk page*. Presenter: the number at 48 px. |
| Loading | Three skeleton rows and skeleton sections (sunken blocks, no shimmer); no spinner visible longer than 300 ms. |
| Server unreachable | Top banner (error colors, `i-alert-triangle`): *Can't reach the server — retrying. Cases are saved on the server. Last update 5:01:12 PM.* Data stays on screen; backoff 1 s to 5 s. |
| Rules table not valid today | Error banner: *Rules table not valid for today — estimates paused.* when `ConsoleMeta.rules_valid_today` is `false` (the server decides in Pacific Time; the console does no date math). |
| Ended early | Header chip *Ended early*; range bar kept; yellow line *Call ended before the result* (from the server). |
| Deleted | The row disappears; toast *Case deleted*. |
| Session expired (`401`) | Login screen, then back to the same case. |
| Conflict (`409 conflict`) | Toast *This case changed — showing the latest.* and refetch. |

### A3.13 Console accessibility

Full keyboard path: skip link, top bar, list, detail, yellow actions, lock. Visible focus ring everywhere (tokens).
Chips never rely on color alone (icon + text). The live transcript region is `aria-live="polite"` behind a toggle
*Announce live transcript* (off by default). The estimate count-up announces only the final value. Amounts have a
spoken form ("306 dollars a month"). Dialogs trap focus, close on `Esc` and return focus. Tooltips also open on
focus. Single-key shortcuts can be turned off (A2.7).

---

## A4. Student card (phone web, opened by QR or `/go` code)

### A4.1 Access and performance

- Page `/c/{token}`: static HTML + `card.js`, which loads `GET /api/card/{token}?lang=en|es` (CardView). The first
  load omits `lang` and gets the conversation's language. Responses are `Cache-Control: no-store`; the page has
  `<meta name="robots" content="noindex">`. The token is at least 128 bits and URL-safe. No login.
- Budget: HTML + CSS + JS at most 60 KB uncompressed, fonts excluded, including the unlocked widget
  (`/unlocked/unlocked.js` + `/unlocked/unlocked.css`, at most 12 KB together); one data request on load (each card
  answer or *I applied* tap is one more); no third-party requests.
- A `<noscript>` block says the card needs JavaScript and gives the clinic contact (A4.7).
- Status: the first render uses the CardView's own `status` (same shape as below). Then
  `GET /api/card/{token}/status` returns `{status, reviewed, reviewed_at, tier, estimate_monthly}`; poll it every 4 s
  while the page is visible and on `visibilitychange`. `reviewed` true: the banner appears within 5 s. If `tier` or
  `estimate_monthly` differ from the shown card (a coordinator edited an answer), refetch the CardView. `404` or `410`:
  show the *deleted or expired* state (`badlink`) and stop polling. The card never shows the `status` value itself
  (for example it never says "approved"); only `reviewed` matters to the student.

### A4.2 Order of information

| # | Part | Default |
|---|---|---|
| 0 | Top bar: logo + wordmark · language switch *English \| Español* | always |
| 1 | Status banner, only when `reviewed`: *Checked by a coordinator · 5:03 PM* (likely colors, `i-check-circle`) | when present |
| 2 | Hero: `headline` as the one `h1`, `subhead`, tier chip. The page formats `estimate_monthly` (for example `$306`), finds it in `headline` and wraps it in a 44 px heavy tabular span; no amount for coordinator and other-help cards | always |
| 2b | Unlocked part (`unlocked`): a mount directly under the hero; the card page loads `/unlocked/unlocked.css` and `/unlocked/unlocked.js` and calls `GPUnlocked.mount(el, view, {token, lang, t, onGone})` (`t` = the page's string lookup, used only for `retry` and `badlink`; `onGone` = the page's `badlink` state), then `GPUnlocked.render(view)` on every new CardView. Full or list_only mode from `CardView.unlocked` (below; rules in `docs/SPEC.md` §6.2 and §6.6) | when `unlocked` is not `null` |
| 3… | `blocks[]` in the order the server sends them (below) | — |
| last | Footer: `footer[]` lines (privacy, prototype line, "you apply yourself on BenefitsCal"), `rules_label`, `sources[]` with dates, case code, *Delete my info*, *Print or save PDF* | always |

Blocks (`CardBlock.id`). **Which blocks a card shows, their one fixed order, their `tone` and their starting state
(`collapsed`) are defined in a single table: `docs/SPEC.md` §6.2.** The card builder applies that table and
`data/content/card.*.json` holds the wording; the page renders exactly the blocks it receives, in that order, and
never filters or reorders them. The order is the same for every tier: `today_action` · `expedited` · `why` ·
`answer_sheet` · `documents` · `interview` · `after_approval` · `food_today` · `contact` (absent blocks are skipped).

What the page adds per block (titles come from the CardView):

| Block | English title | Extra controls |
|---|---|---|
| `today_action` | *Do this today* | primary *Open BenefitsCal* (`i-external`, new tab, `https://benefitscal.com/`); the first-month line, labeled as an estimate |
| `expedited` | *Help within 3 days* | — |
| `why` | by tier or route (sent by the server) | — |
| `answer_sheet` | *Your answers for BenefitsCal* | the table becomes stacked rows below 480 px (A4.6) |
| `documents` | *What to have ready* | — |
| `interview` | *Your phone interview* | *Add 3 dates to my calendar* (`reminders_url`; hidden when it is `null`), *Call the county (855) 355-5757* |
| `after_approval` | *After approval* | — |
| `food_today` | *Food today* | — |
| `contact` | *Talk to a person* | *Call the clinic* (`tel:`), *Email the clinic* (`mailto:`) |

`tone` maps to the card section styles in A6.5: `default`, `accent`, `warning`, `muted` (no other value).

- Coordinator and other-help cards show no amount: the hero states the situation (SPEC §6.2) next to the tier chip.
  Info-route cards use the hero that matches the route (SPEC §6.2).
- Collapsible blocks use native `<details>`/`<summary>`; `beforeprint` opens all of them.
- Phone numbers and the clinic email inside block text become `tel:` and `mailto:` links.
- Every amount reads "$306 a month" (no "/mo" on the card) next to the estimate wording.

**Row 2b, the unlocked part** (`web/unlocked/`; the widget renders exactly what `UnlockedView` sends and never computes,
filters or reorders an amount). It is one card section (A6.5, `default` tone) labeled by its `h2`.

Full mode, top to bottom:

1. `h2` = `title` (*Money you may be missing this year*).
2. The total = `total_text` (*About $4,220 a year*). The widget formats `found_display`, finds it in `total_text` and
   wraps it in a 44 px heavy tabular span, as in the hero. Directly under it: the bar (A6.5 *Unlocked bar*,
   `aria-hidden="true"`), then the claimed line (`labels["ui.claimed"]`: *You've started $0 of $4,220*), so the text is
   always next to the bar.
3. The key line: `i-key` (`--gp-brand-ink`) + `labels["ui.calfresh_part"]` (*CalFresh: about $3,670 a year ($306 a
   month)*) and `labels["ui.key_line"]` (*CalFresh is the key. It opens the others.*), 16 px, `--gp-text-2`.
4. A visually hidden polite live region (`role="status"`) that receives the new `total_text` after each answer or
   mark (not on the first render).
5. The question, when `question` is not `null`: *Question 1 of 3* (`labels["ui.question_count"]` with `index` and
   `total`, 16 px, `--gp-text-2`); the question `text` as an `h3` (18 px / 600, `tabindex="-1"`); the `choices` as
   full-width secondary buttons, at least 48 px high, stacked one per row, each with `aria-pressed="false"`. A tap
   sets `aria-pressed="true"` on that button, sets `aria-disabled="true"` on the group, sends
   `POST /api/card/{token}/answers` and renders the reply. On a network error, 409 (call still live), 422, 429 or 5xx
   the choices come back with the card's *Try again* (`retry`) line under them; 404 or 410 calls `onGone()` (the
   card's `badlink` state). *Not sure* is an ordinary choice. With no question left, the question area is removed.
6. Chips (`chips[]`): a wrapping row of pills (sunken, `--gp-text-2`, 16 px text), for example *+ health coverage
   (Medi-Cal)*, *Riding over breaks? about $90–$440*, *maybe +$200*.
7. *Your plan*: a native `<details>` (collapsed; `beforeprint` opens it) with `labels["ui.plan_title"]` as its
   `<summary>`. One `h3` per stage (`stage_label`), and per program in the order sent:
   - `name` (18 px / 700) + a status pill (`status_label`) · `value_text` · `line` · `notes[]` as a list ·
     `apply_by_text` with `i-calendar`;
   - the apply link as a secondary button with `i-external` (`apply_label`, `apply_url`, new tab, `rel="noopener"`,
     with a visually hidden `labels["ui.new_tab"]`); CalFresh's `apply_url` is `#today_action`, an in-page link (same
     tab, no `i-external`, label *See today's steps*) to the `today_action` block (the card page gives each block
     section `id` = its `CardBlock.id`);
   - *I applied* / *Undo* (`labels["ui.mark_applied"]` / `labels["ui.undo"]`, quiet button, `aria-pressed` =
     `applied`), only when `can_mark_applied`; it sends `POST /api/card/{token}/progress` and renders the reply;
   - `labels["ui.answers_title"]` (*Your answers for this form*) and the `prefill[]` rows (screen · question ·
     answer) in the answer sheet's table style, stacked rows below 480 px;
   - `source_text` (16 px, `--gp-text-2`).

   Programs with status `zero` or `note` are shown muted (`--gp-text-2`), without a link or a button.
8. *Share* (`labels["ui.share_button"]`, secondary button with `i-send`), only when `share_text` is not `null`: it
   calls `navigator.share({text: share_text})` when the browser has it; otherwise it copies `share_text` to the
   clipboard, the label becomes *Copied* (`labels["ui.copied"]`) for 4 s (`--gp-d-toast`) and the live region says it.
   If neither works, a read-only text field shows `share_text`, selected. Nothing else is shared: no card link, token
   or case code.
9. The footnote (`footnote`, 16 px, `--gp-text-2`).

List_only mode: the same section with `h2` = `title` (*More help to check with the coordinator*),
`labels["ui.list_only_intro"]`, then each program's `name` (700) with its `line`, and the footnote. No bar, total,
chips, question, plan or share.

Focus and order: title, choices, *Your plan*, its links and buttons, *Share*. After an answer, focus moves to the new
question's `h3`, or to the total (`tabindex="-1"`) when no question is left. After *I applied* / *Undo*, focus stays on
that button with its new label. Re-rendering on a language switch keeps *Your plan* open or closed as it was.

### A4.3 Type, layout, buttons

- Mobile first, 360–430 px, single column, 16 px side gutters, text width at most 34 em.
- Body 18 px / 1.5; hero amount 44 px / 800 tabular; hero sentence 28 px / 700; section titles 22 px / 700; small
  text 16 px; legal footer 14 px minimum.
- Buttons at least 48 px high, full width on phones, icon + label. Primary *Open BenefitsCal*. Secondary: *Add 3
  dates to my calendar* (the CardView's `reminders_url`, which is `GET /api/card/{token}/reminders.ics?lang=…`:
  three all-day calendar events relative to the filing day — `tracking.filed_on` when the coordinator recorded it, else `first_month.filed_on` — downloaded by the student as `gatorplate-dates.ics`; the button shows only when the case has a filing day; GatorPlate sends
  nothing, and no student-facing string calls them "reminders", a word the output guard blocks), *Call the clinic*, *Email the clinic*, *Call the county (855) 355-5757* inside the
  interview section, *Print or save PDF*, *Delete my info*.
- *Delete my info* opens a confirm screen, then `DELETE /api/card/{token}`, then *Your information was deleted.*
- No sticky bottom bars, no pop-ups, no carousels.

### A4.4 Language switch

Two buttons with `aria-pressed`, each labeled in its own language (`lang="en"` *English*, `lang="es"` *Español*).
Switching fetches the CardView in the other language and re-renders without a page reload, sets `<html lang>`, keeps
the scroll position and focus, and remembers the choice in `localStorage` (inside try/catch; the page works without
it). Crossfade 120 ms. BenefitsCal screen names stay in English in both languages (they are what the student sees),
with a Spanish explanation next to them. The unlocked part re-renders from the refetched CardView
(`GPUnlocked.render(view)`); the card answers and *I applied* marks stay, because they live on the case.

### A4.5 Print

`@media print`: black text on white (the `tokens.css` print override), buttons and toggles hidden, all sections
expanded, link URLs printed after the link text, case code and date at the top, page break before *Your phone
interview*, 12 pt body. The unlocked part prints as text: the total and the *You've started …* line (the bar graphic
and the question are hidden), with *Your plan* open.

### A4.6 Accessibility (WCAG 2.2 AA)

Text contrast at least 4.5:1 and UI contrast at least 3:1 (only the pairs in `tokens.json`) · targets at least 48 px ·
one `h1` (the hero sentence) and an `h2` per section · tables with `th scope` (the answer sheet becomes stacked rows
below 480 px) · reflow at 320 px without horizontal scroll · readable at 200% text size · no information by color
alone · `lang` on each language button · reduced motion respected · screen-reader order equals visual order. In the
unlocked part: the bar graphic is `aria-hidden` and its values are in the text next to it; a polite live region reads
the new total; choice buttons carry `aria-pressed`; focus moves as in A4.2 row 2b.

### A4.7 Card UI strings (the page owns these; content comes from the CardView)

Spanish needs review by a fluent speaker before public use. The unlocked part (A4.2 row 2b) owns no strings: every
word of it lives in `data/content/programs.{en,es}.json` and arrives through `UnlockedView` in the requested language,
including the control labels in `UnlockedView.labels` (`ui.claimed`, `ui.calfresh_part`, `ui.key_line`,
`ui.question_count`, `ui.plan_title`, `ui.answers_title`, `ui.new_tab`, `ui.mark_applied`, `ui.undo`,
`ui.share_button`, `ui.copied`, `ui.list_only_intro`). Its only borrowed strings are this table's `retry` and `badlink`.

| Key | English | Español |
|---|---|---|
| `lang.en` / `lang.es` | English | Español |
| `status.reviewed` | Checked by a coordinator · {time} | Revisado por la coordinación de CalFresh · {time} |
| `tier.likely` | Good chance | Buenas posibilidades |
| `tier.coordinator` | A person will check | Lo revisará una persona |
| `tier.other_help` | Other help | Otra ayuda |
| `btn.benefitscal` | Open BenefitsCal | Abrir BenefitsCal |
| `btn.calendar` | Add 3 dates to my calendar | Agregar 3 fechas a mi calendario |
| `btn.call_clinic` | Call the clinic | Llamar a la clínica |
| `btn.email_clinic` | Email the clinic | Escribir a la clínica |
| `btn.print` | Print or save PDF | Imprimir o guardar PDF |
| `btn.delete` | Delete my info | Borrar mi información |
| `delete.title` | Delete your information? | ¿Borrar tu información? |
| `delete.body` | This deletes your answers and this card for good. The coordinator won't see them anymore. | Esto borra tus respuestas y esta tarjeta para siempre. La coordinación ya no podrá verlas. |
| `delete.yes` / `delete.no` | Delete · Keep it | Borrar · No borrar |
| `deleted` | Your information was deleted. | Tu información fue borrada. |
| `badlink` | This card link doesn't work. It may have expired or been deleted. | Este enlace no funciona. Puede que haya vencido o que se haya borrado. |
| `badlink.talk` | Talk to GatorPlate | Hablar con GatorPlate |
| `loading` | Loading your card… | Cargando tu tarjeta… |
| `error` | We couldn't load your card. Check your connection and try again. | No pudimos cargar tu tarjeta. Revisa tu conexión e intenta otra vez. |
| `retry` | Try again | Intentar otra vez |
| `code` | Your case code: {code} | Tu código: {code} |
| `print.header` | GatorPlate card · {code} · printed {date} | Tarjeta de GatorPlate · {code} · impresa el {date} |
| `noscript` | This card needs JavaScript. To talk to a person: SF State CalFresh Help Clinic, (415) 338-1203, calfresh@sfsu.edu. | Esta tarjeta necesita JavaScript. Para hablar con una persona: CalFresh Help Clinic de SF State, (415) 338-1203, calfresh@sfsu.edu. |
| `prototype` | Student-built prototype — not an official SF State, county, or CalFresh service. | Prototipo hecho por estudiantes; no es un servicio oficial de SF State, del condado ni de CalFresh. |

Times and dates are Pacific Time (`Intl.DateTimeFormat` with `timeZone: "America/Los_Angeles"`, locales `en-US` and
`es-US`): *5:03 PM*, *Mon, Oct 5* / *5:03 p. m.*, *lun., 5 de oct.* The date inside the unlocked part's
`apply_by_text` is the exception: the server formats it (month and day, no weekday: *November 19* / *19 de
noviembre*) and the widget shows the text as sent.

---

## A5. Talk page (web voice, `/talk?lang=en|es`)

### A5.1 Purpose

The same brain as the phone line, in the browser: English and Spanish by voice, plus typing for anyone. It is the
demo fallback and the Spanish channel. It uses `POST /api/web/sessions` and then `/v1/calls/{call_id}/start`,
`/turn` and `/end` with the bearer token (`docs/BRAIN_API.md`, Web channel).

### A5.2 Screen and states

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│ [logo] GatorPlate            [English | Español]                Not recorded       │
│                                                                                    │
│   Does anyone, like a parent, pay part of your rent     <- current reply, 26 px    │
│   straight to your landlord?                                                       │
│                                                                                    │
│   You: "no, I pay it..."                                <- interim gray, final ink │
│                                                                                    │
│                  (  mic  )   Listening...               <- 96 px mic button        │
│           [ Yes ]   [ No ]                              <- quick replies (choices) │
│   ┌───────────────────────────────────────┐  [send]   <- type instead, always      │
│   └───────────────────────────────────────┘                                        │
│   Show conversation (v)                                                            │
│                                                                                    │
│   Student-built prototype — not an official SF State,                              │
│   county, or CalFresh service.                                                     │
└────────────────────────────────────────────────────────────────────────────────────┘
```

| State | Mic button and label | Notes |
|---|---|---|
| Intro | *Start talking* (primary) + *Type instead* | Copy in A5.6. The microphone is requested only after the Start tap. |
| Permission prompt | — | The browser's prompt. |
| Listening | pulsing ring · *Listening…* | Interim words gray, final words ink. Push to talk, one utterance per tap. |
| Thinking | three dots · *Thinking…* | Calm; no spinner. The brain itself switches to a closed question if it is slow. |
| Speaking | sound bars · *GatorPlate is speaking — tap to interrupt* | The mic is closed while GatorPlate speaks (no echo). When `interruptible` is false (opening, amounts, codes, phone numbers, crisis resources) there is no tap-to-interrupt and the label is just *GatorPlate is speaking*. Tap or `Space` stops the voice and listens. |
| Done | *Your card is ready* + *Open my card* (`card_url`) | After `end: true` the page sends `/end` with the same reason. The page shows the button and the card link; it has no QR of its own (the contract has no QR endpoint the talk page may call, and no client QR library is used). At the demo table the judge scans the card QR in the console's Live view, which works the same for a web call. A declined consent shows *Conversation ended* + *Start again*. |
| Typing mode | text field focused | Same API turns (`typed: true`); quick replies stay. |

- The current reply shows `display`; it is spoken with the browser voice in the reply's `lang`, sentence by sentence.
- Quick replies (`choices`) are buttons; a tap sends the label as an utterance with `typed: true`.
- `card_url`, once set, stays visible as *Open my card*.
- The transcript stays in page memory only (*Show conversation*); it is gone after a reload.
- `aria-live="polite"` on the current reply; the mic button's state is in its label; works keyboard-only (`Space`
  talks when focus is not in the text field; `Enter` sends typed text).

### A5.3 Errors

| Case | English | Español |
|---|---|---|
| Mic blocked | Your microphone is blocked. Allow it in the browser (the site settings icon next to the address), or type — it works the same. | Tu micrófono está bloqueado. Permítelo en el navegador (el ícono de configuración del sitio junto a la dirección) o escribe: funciona igual. |
| No speech recognition in this browser (detected at run time) | Voice doesn't work in this browser. Type your answers — it works the same — or open this page in another browser. | La voz no funciona en este navegador. Escribe tus respuestas (funciona igual) o abre esta página en otro navegador. |
| No speech heard | I didn't catch that. Tap the mic to try again, or type. | No te escuché. Toca el micrófono para intentar otra vez, o escribe. |
| Network | Voice needs the internet right now. You can type instead. | La voz necesita internet. Puedes escribir. |
| Server slow | Still thinking… one moment. | Sigo pensando… un momento. |
| Server down | Something went wrong. Your answers so far are saved — try again. | Algo salió mal. Tus respuestas están guardadas; intenta otra vez. |
| Too many sessions (`429`) | Too many people are starting right now. Try again in a few minutes. | Hay muchas personas empezando ahora. Intenta otra vez en unos minutos. |
| No sound on a phone | Can't hear? Turn up the volume. | ¿No oyes? Sube el volumen. |

Speech recognition is detected at runtime on the Start tap: no start event within 1.5 s, or the errors
`not-allowed`, `service-not-allowed`, `audio-capture` or `network`, switch to typing mode with the message above.

### A5.4 Language

- The switch sets the recognition language (`en-US`; `es-US`, then `es-MX`, then `es-ES`), the voice (the first voice
  whose `lang` starts with the same code), every UI string, and the `lang` sent with each turn.
- If a reply comes back in the other language, the page follows it and shows a toast *Switched to English* /
  *Cambiamos a español*.
- A *Read aloud: On/Off* switch (*Leer en voz alta: sí/no*) stops the voice for screen-reader users; captions stay.

### A5.5 Implementation notes that affect the experience

- The session token comes from `POST /api/web/sessions` (rate-limited); the page never holds the gateway secret.
- If the student leaves before the end, the page sends `/end` with `caller_hangup` on `pagehide`
  (`fetch(…, {keepalive: true})`, best effort).
- Load voices on `voiceschanged`; speak sentence by sentence (long single utterances can stall).
- Start recognition only after the voice ends; if automatic listening fails (some mobile browsers need a tap), show
  *Tap to talk* / *Toca para hablar*.
- Some phone browsers unlock audio only on the first tap; if speech reports no start within 2 s, show *Can't hear?
  Turn up the volume.*
- On-device recognition is used only when the browser reports it available for the language; never install a
  language pack during a demo.

### A5.6 Talk page strings

| Key | English | Español |
|---|---|---|
| `title` | Talk to GatorPlate | Habla con GatorPlate |
| `intro.time` | A few minutes. We'll ask about school, home and money — never your Social Security number or immigration status. | Unos minutos. Te preguntaremos sobre tus estudios, tu casa y tu dinero; nunca tu número de Seguro Social ni tu estatus migratorio. |
| `intro.mic` | Your browser will ask to use your microphone. You can also type. | Tu navegador te pedirá usar el micrófono. También puedes escribir. |
| `privacy` | Your browser turns your voice into text (Chrome uses Google's speech service; Safari uses Apple's). GatorPlate only gets the text and never stores audio. We keep your answers and short quotes, not the conversation. | Tu navegador convierte tu voz en texto (Chrome usa el servicio de voz de Google; Safari usa el de Apple). GatorPlate solo recibe el texto y nunca guarda audio. Guardamos tus respuestas y citas cortas, no la conversación. |
| `start` / `type` / `send` | Start talking · Type instead · Send | Empezar a hablar · Escribir · Enviar |
| `listening` / `thinking` | Listening… · Thinking… | Escuchando… · Pensando… |
| `speaking` / `speaking.tap` | GatorPlate is speaking · GatorPlate is speaking — tap to interrupt | GatorPlate está hablando · GatorPlate está hablando; toca para interrumpir |
| `tap_to_talk` | Tap to talk | Toca para hablar |
| `done` / `open_card` | Your card is ready · Open my card | Tu tarjeta está lista · Abrir mi tarjeta |
| `ended` / `again` | Conversation ended · Start again | Conversación terminada · Empezar otra vez |
| `show_conv` | Show conversation | Mostrar conversación |
| `not_recorded` | Not recorded | No se graba |
| `prototype` | (the A0 prototype line) | (la línea de prototipo de A0) |

---

## A6. Design system

### A6.1 Tokens

- Source: `data/design/tokens.json`; CSS: `web/shared/tokens.css` (identical values, custom properties `--gp-<key>`).
  Link `tokens.css` first on every page, then the page CSS. No other file defines colors or fonts.
- Groups: `color` (surfaces, text, action, brand, tiers, yellow line, system errors) · `font` · `type` · `space`
  (4 px grid) · `radius` · `shadow` · `motion` · `effect` (colors derived with `color-mix`: the live-dot ring and the
  dialog scrim) · `size` · `print`.
- Color roles (2026-10-02 *paper, ink and persimmon*): warm paper surfaces (bg #FAF9F6, sunken #F2F0EA, sunken-2
  #E9E6DE for a hovered sunken control); ink-blue primary (#2142A8, the ballpoint that fills a paper form) for actions
  and live state; persimmon brand for the logo and large accents only, with `brand-wash` (#FFF3EC) as the only brand
  fill (the landing panel, the *Why SF State* fact, the console role pill); green, amber and teal for the three result tiers; yellow for lines a person must check; red only for
  system errors (never for a student's result, never for a deadline).
- `python3 tools/check_contrast.py` must pass. It checks: every allowed text/background pair; token coverage; CSS
  equal to JSON; light theme only (`color-scheme: only light`, no `prefers-color-scheme` anywhere under `web/`, the
  color-scheme `<meta>` on every HTML page); no color literals or font families outside the tokens; every active
  `@font-face` file exists and is WOFF2 and every font file is used and listed in `tokens.json` `meta.fonts.files`;
  the icon sprite parses and every `icons.svg#id` reference exists; and CSP-safe HTML and CSS (no inline styles,
  scripts or handlers, no `@import`, nothing loaded from another site).

### A6.2 Contrast (WCAG 2.2 formula, computed 2026-10-02, truncated to 2 decimals; the full list of 74 pairs is in `tokens.json`)

| Pair | Ratio | Needs |
|---|---|---|
| text on surface · text on page · text on sunken-2 | 17.75 · 16.86 · 14.23 | 4.5 |
| text-2 on surface · text-3 on surface · text-3 on page · text-3 on sunken | 9.14 · 6.11 · 5.80 · 5.36 | 4.5 |
| white on primary · primary on surface · primary on primary-tint | 8.71 · 8.71 · 7.70 | 4.5 |
| likely · coordinator · other · yellow · error ink on their backgrounds | 6.17 · 6.03 · 6.10 · 7.86 · 6.26 | 4.5 |
| brand-ink on surface · brand on surface (large text and logo only) | 5.85 · 3.78 | 4.5 · 3 |
| inside brand-wash: text · text-2 · brand-ink · primary · brand (large) | 16.30 · 8.39 · 5.37 · 8.00 · 3.47 | 4.5 · 3 |
| err-ink on sunken · on sunken-2 (Delete pill) | 6.46 · 5.90 | 4.5 |
| line colors on surface (likely · coordinator · other · yellow · error) | 4.05 · 3.45 · 4.07 · 3.68 · 4.71 | 3 |
| border-strong on surface · on page · on sunken | 3.45 · 3.27 · 3.02 | 3 |
| inside tinted panels: primary on yl-bg · border-strong on yl-bg · focus on yl-bg · focus on primary-tint · coord-line on coord-bg | 8.01 · 3.17 · 8.01 · 7.70 · 3.06 | 4.5 · 3 · 3 · 3 · 3 |

### A6.3 Typeface

- **One family: Atkinson Hyperlegible Next**, an upright and an italic variable WOFF2 (weights 200–800, Latin subset
  including Spanish accents), self-hosted from `web/shared/fonts/` under the SIL Open Font License 1.1 (no font
  service, no `@import`). It is used for all text, on every screen; it is part of the accessibility story. There is
  **no monospace font**: no `--gp-font-mono`, no second family.
- **Files:** both faces are in the repository, from the same official release (version 2.001):
  `AtkinsonHyperlegibleNext-Variable.woff2` (upright) and `AtkinsonHyperlegibleNext-Italic-Variable.woff2` (italic).
  `web/shared/tokens.css` registers them with three active `@font-face` rules: the italic file under its own family
  name *Atkinson Hyperlegible Next Italic* (listed first by `--gp-font-italic`, used for student quotes and `em`); the
  upright file under *Atkinson Hyperlegible Next* (`font-style: normal`, used by `--gp-font` for all other text); and
  the italic file under that upright family name too (`font-style: italic`), so italic text in that family gets the
  real italic instead of a slanted upright. `system-ui, sans-serif` after the family name in `--gp-font` is only the
  usual CSS fallback (while the font loads with `font-display: swap`, or if a file fails to load).
- Never register the italic file as `font-style: normal`: browsers would then render upright text in italics.
- Optionally preload the upright face on the card and talk pages
  (`<link rel="preload" as="font" type="font/woff2" crossorigin href="/shared/fonts/AtkinsonHyperlegibleNext-Variable.woff2">`).
- A future font update must keep `web/shared/tokens.css`, `tokens.json` `meta.fonts.files`, `NOTICE.md` and
  `web/shared/fonts/OFL.txt` in agreement (both faces from one release, one version); `tools/check_contrast.py`
  checks this.
- **Numbers and codes:** amounts, times, countdowns **and case codes** use the text font's tabular figures (`.num`
  and `.code` apply `font-variant-numeric: var(--gp-num)`; the font has the `tnum` feature). Case codes (`.code`) stay
  in `--gp-font` (upright) with `letter-spacing: var(--gp-tracking-code)` (0.06em). The font has no unslashed zero
  (features: ccmp, frac, locl, pnum, tnum only), so large amounts are set at 600, never 800, to keep the slash clean. The code generator avoids the
  look-alike characters `0`, `O`, `1` and `I` (codes keep matching `^[A-Z0-9]{3}-[A-Z0-9]{3}$`).

### A6.4 Type usage

Hierarchy comes from size and space, not weight (2026-10-02): headings 500 with negative tracking, card and section
titles 600, body 400, nothing at 800.

| Token | Size / weight | Use |
|---|---|---|
| `fs-hero-title` | clamp 36–56 / 500, `lh-display` 1.06, `tracking-display` −0.025em | landing headline |
| `fs-title` | clamp 32–44 / 500, −0.025em | page titles (talk intro, about), Live view replay turn |
| `fs-display` | 56 / 600, −0.035em, tabular | console estimate (summary band, Live view) |
| `fs-hero` | clamp 48–56 / 600, −0.035em, tabular | card amount, on its own line inside the hero sentence |
| `fs-h1` | 28 / 500, `tracking-tight` −0.015em | card hero sentence without an amount, console case title, /go title |
| `fs-talk` | 28 / 500, line height 1.3 | talk page current line |
| `fs-card-h2` | 22 / 600 (card sections) · 22 / 500 (hero sentence around the amount) | card section titles |
| `fs-lead` | 20 / 400, text-2 | landing, about and talk intro lead |
| `fs-h2` | 20 / 600 | console section titles |
| `fs-transcript` | 20 / 400 | live transcript in Presenter mode |
| `fs-body-l` | 18 / 400 | card and talk body; live transcript |
| `fs-h3` | 17 / 600 | yellow line reasons |
| `fs-body` | 16 / 400 | console body |
| `fs-small` | 14 / 400–500 | console meta and chips; card legal footer only |
| `fs-label` | 13 / 600, upper case, +0.06em | panel labels (*ESTIMATE SO FAR*) only |

Never below 13 px anywhere; card text at least 16 px except the legal footer (14 px); Presenter mode at least 15 px.
Line height 1.5 for text, 1.2 for headings, 1.0–1.06 for display numbers and the landing headline.

### A6.5 Components

| Component | Spec |
|---|---|
| Button | Pill (`--gp-r-pill`). Min height 48 px (`--gp-tap`; big 56 `--gp-tap-l`; console 40 `--gp-tap-console`), 20 px horizontal padding (console 16, big 32), weight 500, icon + label; pressed scales to 0.98. Primary: `--gp-primary` with `--gp-on-primary` text, hover `--gp-primary-hover`. Secondary: a `--gp-sunken` fill and no line, hover `--gp-sunken-2`. Quiet: text only in `--gp-primary`, hover primary-tint. Locked: no fill, 1 px dashed `--gp-border-strong`, `--gp-text-2`, `i-lock`, visible reason, `aria-disabled`. Danger (*Delete*): secondary style with `--gp-err-ink` text, never a red fill. |
| Tier chip | Pill, 28 px, icon + text: *Likely* (`i-check-circle`, likely colors) · *Coordinator check* (`i-person`, coordinator colors) · *Other help* (`i-heart-hand`, other colors). |
| Reason chip | Pill, 28 px. Outcome-changing: `--gp-primary-tint` with `--gp-primary` text and a `$` badge (`--gp-primary` circle, `--gp-on-primary` text). Routine: sunken with `--gp-text-2`. Not asked: surface with a 1 px dashed `--gp-border-strong` border and `--gp-text-2`. Never asked: sunken, `--gp-text-2`, `i-lock`. |
| Count badge | *1 to check*: `--gp-yl-bg`, `--gp-yl-ink`, `i-alert-circle`. None open: `i-check` in `--gp-likely-ink`. |
| Yellow line card | `--gp-yl-bg`, 4 px left edge `--gp-yl-line`, radius `--gp-r-lg`, padding 16; actions right-aligned (stacked below 1280 px). |
| Answer row | Min 44 px; label (`--gp-text-2`) · value (`--gp-text`, 600, tabular) · state icon · quote (`--gp-text-2`, italic, one line, full text on hover and focus) · source icon. |
| Transcript bubble | Max 85% wide; radius 14 with the speaker's corner 4; GatorPlate = sunken, student = primary-tint; padding 12/16; 13 px upper-case label. |
| Range bar | Track 12 px, sunken, pill; band `--gp-primary`; end labels 14 px tabular; settled = 4 px tick + count-up. |
| Unlocked bar (card) | Track 10 px, sunken, pill, full width. One segment per `segments[]` entry in the order sent, width = its value ÷ `found_display` (set from JS with `style.setProperty('--w', …)`), 2 px gaps. A segment not yet marked *I applied* is the neutral `--gp-border` (at 0 % the bar reads as an empty track, never as a warning); marked *I applied* it turns solid: the CalFresh segment `--gp-brand` (a large accent), the others `--gp-likely-line`; so the colored part always equals `claimed_display`. `aria-hidden="true"`: the total and the claimed line next to it carry the values. Printed as text only (A4.5). |
| Live dot | 10 px `--gp-live`, pulse ring every 1.6 s (`--gp-live-ring`). |
| Toast | Console bottom-left, phones top; surface + `--gp-sh-3`; 4 s; `role="status"`. |
| Card section | Surface, radius `--gp-r-lg` (20), `--gp-sh-1` (a hairline ring, no visible drop), padding 24 (phones 20), 12 px gap. Tones are fills, not edges: default = surface; accent = `--gp-primary-tint`; warning = `--gp-coord-bg`; muted = sunken. *Do this today* shows its first sentence, then its button, then the details (CSS order only). |
| Banner | Full width. System error: `--gp-err-bg`, `--gp-err-ink`, `i-alert-triangle`. Card review banner: `--gp-likely-bg`, `--gp-likely-ink`, `i-check-circle`. |
| Dialog | Surface, radius `--gp-r-xl`, `--gp-sh-3`, backdrop `--gp-scrim`; focus trapped; `Esc` closes. |
| Segmented control | Language switch and list segments: a sunken pill track (4 px inset) holding pill buttons with `aria-pressed`; selected = a surface pill with `--gp-sh-1` and `--gp-text`, the others `--gp-text-2`. |
| Input | 48 px (console 40), 1 px `--gp-border-strong`, radius `--gp-r-md` (12), 16 px padding, label above (500), error text `--gp-err-ink` with an icon. The talk composer is one pill holding the field and the send button; its ring turns 2 px `--gp-focus` on focus (one ring, not two). The /go code field is 80 px, centered, 28 px, +0.2em tracking. |
| QR panel | White panel, QR at 260 px with at least 24 px white margin (quiet zone at least 4 modules), caption *Student card — scan with your phone camera*, case code below. |

### A6.6 Icons (`web/shared/icons.svg`)

Original line icons drawn for GatorPlate: 24 px grid, stroke 2, round caps and joins, `currentColor`. No icon set was
copied. Size 20 px in the console (`--gp-icon`), 24 px on the card and talk page (`--gp-icon-card`).

```html
<svg class="icon" aria-hidden="true" focusable="false"><use href="/shared/icons.svg#i-phone"></use></svg>
```

Decorative icons sit next to visible text and are `aria-hidden`. An icon-only button gets an `aria-label` on the
button (and a tooltip).

| Id | Meaning / where |
|---|---|
| `i-phone` · `i-globe` | phone channel · web channel |
| `i-mic` · `i-mic-off` · `i-keyboard` · `i-send` | talk: listen · mic blocked · type instead · send |
| `i-keypad` | an answer from the phone keypad |
| `i-language` | language switch (optional, next to the labels) |
| `i-volume` · `i-volume-off` | read aloud on / off |
| `i-live` | Live view |
| `i-check` · `i-check-double` · `i-check-circle` | clear · confirmed · Likely tier and review banner |
| `i-alert-circle` · `i-alert-triangle` · `i-info` · `i-help` | yellow count · system error · information · shortcut list |
| `i-hourglass` · `i-clock` | deadline in 2 days or less · times, 3-day benefits |
| `i-lock` · `i-unlock` | review lock closed / open; never asked |
| `i-shield` · `i-eye-off` | privacy · not recorded, conversation cleared |
| `i-quote` · `i-table` · `i-person` · `i-person-check` | from the student's words · rules table · Coordinator check tier · set by the coordinator |
| `i-heart-hand` · `i-utensils` · `i-pin` · `i-mail` · `i-file` | Other help tier · food today · location · email · documents |
| `i-calendar` · `i-calendar-add` · `i-printer` · `i-qr` · `i-external` | tracking dates · add calendar dates (`.ics`) · print · card QR · opens another site |
| `i-key` | CalFresh, the key: the key line of the card's unlocked part (A4.2 row 2b). Drawn with the upgrade, original, on the same 24 px grid and stroke 2 |
| `i-trash` · `i-pencil` · `i-reset` · `i-play` · `i-monitor` · `i-more` · `i-log-out` | delete · edit · reset demo · replay · Presenter · overflow menu · log out |
| `i-arrow-right` · `i-arrow-left` · `i-chevron-down` · `i-chevron-right` · `i-close` | a value change ($306 to $155) and next · back · disclosure · steps · dismiss |

### A6.7 Logo and wordmark

`gp-logo` (in the sprite, on its own 32 px grid): a plate with a voice wave, drawn in `currentColor`. Color it with a
class (`.logo { color: var(--gp-brand); }`), never an inline style (CSP). Wordmark: *GatorPlate* in the UI font at
700, −0.01em, `--gp-text`. The logo is never combined with SF State, CalFresh or county marks.

### A6.8 Motion

| Moment | Spec |
|---|---|
| Field fills | Row background sweeps from primary-tint to transparent over 1200 ms (`--gp-ease`); the value fades up 4 px in 200 ms; the check icon draws in 280 ms. |
| Heard words | The `<mark class="heard">` tint fades in over 200 ms and stays while the call is live. |
| Estimate count-up | 450 ms ease-out, tabular figures; screen readers get only the final value. |
| Range band | `left` and `width` over 500 ms, `--gp-ease`. |
| Reason chip | Opacity and scale from 0.96 to 1 over 160 ms. |
| New case row | Slides down over 240 ms. |
| Lock opens | `i-lock` to `i-unlock` crossfade, 200 ms; button color 200 ms. No confetti. |
| Transcript cleared | Bubbles fade, blur 2 px and rise 6 px over 600 ms, then leave the DOM; then the notice. |
| Card | No motion except the language swap (120 ms crossfade) and the unlocked total (next row). |
| Unlocked total (card) | On a new `found_display` the total counts up from the old value over 600 ms (`--gp-d-clear`), ease-out, tabular figures; the segment widths move over the same 600 ms (`--gp-ease`); a segment marked *I applied* turns solid over 200 ms (`--gp-d2`). The first render shows the value without a count-up. Screen readers get only the final value (live region). Under reduced motion: no count-up and no transitions. |
| Programs rows (console 6b) | New or changed rows and the footer use the field-fill sweep (1200 ms, as *Field fills*). |
| Reduced motion | Everything instant (`tokens.css` rule for CSS; JS-driven motion such as the count-ups and replay pacing checks `matchMedia('(prefers-reduced-motion: reduce)')` and jumps to the end); new fields keep a static *new* dot for 3 s instead. |

```css
@keyframes gp-fill { from { background: var(--gp-primary-tint); } to { background: transparent; } }
.slot.is-new { animation: gp-fill var(--gp-d-fill) var(--gp-ease); }
.slot__value { transition: opacity var(--gp-d2) var(--gp-ease), transform var(--gp-d2) var(--gp-ease); }
.slot.is-pending .slot__value { opacity: 0; transform: translateY(4px); }
.check path { stroke-dasharray: 24; stroke-dashoffset: 24; animation: gp-draw var(--gp-d-draw) var(--gp-ease) forwards; }
@keyframes gp-draw { to { stroke-dashoffset: 0; } }
mark.heard { background: linear-gradient(transparent 58%, var(--gp-primary-tint) 58%); color: inherit; border-radius: 2px; }
.range { position: relative; height: var(--gp-range-h); border-radius: var(--gp-r-pill); background: var(--gp-sunken); }
.range__band { position: absolute; inset-block: 0; left: var(--lo); width: calc(var(--hi) - var(--lo)); min-width: 6px;
  border-radius: inherit; background: var(--gp-primary);
  transition: left var(--gp-d4) var(--gp-ease), width var(--gp-d4) var(--gp-ease); }
.live-dot { width: var(--gp-live-dot); height: var(--gp-live-dot); border-radius: 50%; background: var(--gp-live);
  animation: gp-pulse var(--gp-d-pulse) infinite; }
@keyframes gp-pulse { 0% { box-shadow: 0 0 0 0 var(--gp-live-ring); } 70% { box-shadow: 0 0 0 10px var(--gp-live-ring-0); }
  100% { box-shadow: 0 0 0 0 var(--gp-live-ring-0); } }
.transcript.is-clearing .bubble { opacity: 0; filter: blur(2px); transform: translateY(-6px);
  transition: opacity var(--gp-d-clear) var(--gp-ease), filter var(--gp-d-clear) var(--gp-ease), transform var(--gp-d-clear) var(--gp-ease); }
```
`--lo` and `--hi` are percentages set from JS with `style.setProperty` (allowed by the CSP).

### A6.9 Don'ts

Dark panels or sections · gradients on text · glassmorphism · stock illustrations · purple/gold · emoji · gray text
below 4.5:1 · spinners longer than 300 ms · sound effects · auto-playing video · red for anything a student did ·
color literals outside `tokens.css` · inline styles.

---

## A7. Other public pages

### A7.1 `/go` (card code entry)

For phone calls with `GP_CARD_DELIVERY=code`: the student hears a short address and a 6-digit code (valid 24 hours,
5 tries per minute per IP address). One field (`inputmode="numeric"`, `autocomplete="one-time-code"`, 6 digits,
spaces ignored) sends `POST /api/card/lookup` `{"code": "481206"}`, then the page opens the returned card URL.

| Key | English | Español |
|---|---|---|
| `go.title` | Enter your card code | Escribe el código de tu tarjeta |
| `go.hint` | 6 digits — we said it at the end of your call. | 6 dígitos: te lo dijimos al final de la llamada. |
| `go.submit` | Open my card | Abrir mi tarjeta |
| `go.notfound` (`404`) | That code doesn't work. Codes last 24 hours — check the digits or start again. | Ese código no funciona. Los códigos duran 24 horas: revisa los dígitos o empieza otra vez. |
| `go.limited` (`429`) | Too many tries. Wait a minute and try again. | Demasiados intentos. Espera un minuto e intenta otra vez. |

### A7.2 `/` (landing)

One screen, English and Spanish: headline *Check the money you may be missing — by phone or in your browser.* (without a
demo number: *Check the money you may be missing — in your browser.*) · *SF State students: CalFresh pays one person up
to $306 a month for groceries, and it can open more help. A few minutes. Free. Estimates only — each agency decides.* ·
the demo phone number (`demo_phone_display` from `GET /api/public/info`, only when set) · *Talk in your browser*
(`/talk`, EN/ES) · *How it works and responsible AI* (`/about`) · *For coordinators* (`/console`) · trust row *Not
recorded · Never asks for your Social Security number or immigration status · Estimates only — each agency decides* ·
the prototype line. The headline shows in two parts, the hook up to the dash (Spanish: the comma) and then the channel,
each balanced on its own lines, with no-break spaces before the dash and inside the channel's last three words; on
phones (under 48em) it uses `fs-title`.

### A7.3 `/about` (how it works; facts to use exactly)

Sections: what GatorPlate is · how it works (*The model listens, rules decide, a person confirms*) · what is kept
(answers and short quotes; no audio, no Social Security numbers, no immigration status, no phone numbers) · rules and
sources · why SF State · limits (an estimate only; English on the phone, English and Spanish on the web) · team
(*Built by an SF State student team*; say *SF State students* only if it is true for every team member) · the
prototype line · the phone line as *a hosted voice gateway* (use the README's sentence about it verbatim once it
exists). Facts, with source and date on the page:

| Fact (wording) | Source |
|---|---|
| In 2023–24, 14.3% of SF State undergraduates received CalFresh at some point in the school year — below the CSU average (16.4%) and Chico State (33.0%). This is the share of undergraduates receiving CalFresh, not a share of eligible students. | California Policy Lab, *CalFresh Participation Among California's College Students: A 2023–24 School Year Update*, August 2026, Table 2 |
| For applications since March 1, 2026, grants, scholarships, fellowships and loans for college don't count as income for CalFresh (AB 42). Cash that family or friends give still counts. | CDSS ACL 26-16 (2026-03-19) |
| Since June 1, 2026, students attending a community college, CSU or UC at least half-time in an associate or bachelor's degree program meet an exemption from CalFresh's student rule. | CDSS ACL 26-25 (2026-04-13) |
| New FY2027 amounts took effect on October 1, 2026 — for example, up to $306 a month for one person. | CDSS ACIN I-40-26 (2026-09-10) |
| We don't collect Social Security numbers. | GatorPlate's design (no statute is cited) |
| The pilot uses no student records, so it needs no student-records integration; a real pilot follows SF State's data and accessibility review. | GatorPlate's design |

Not on screens: *"Only about a quarter of eligible students participate"* (a UC and community-college figure only) and
the missed-interview statistic used in the pitch (its wording contains a word the forbidden-phrase check blocks).

---

## A8. Data the UI reads (contract names)

Case, console and card models live in the `gatorplate.contracts` package (`case`, `console_api`, `card_api`); the
Brain API is `contracts/brain_api.v1.schema.json`. The UI reads these fields and nothing else.

### A8.1 Case (detail), summary (list) and console models

| Model | Fields the UI uses |
|---|---|
| `Case` | `id`, `version`, `code`, `summary`, `created_at`, `lang`, `channel`, `live`, `status`, `seeded`, `persona`, `ended_reason`, `ended_early`, `reviewed_at`, `tier`, `reason_code`, `estimate_monthly`, `estimate_is_floor`, `expedited_possible`, `estimate_range {lo, hi, settled}`, `timeline[] {turn, at, slots[], lo, hi}`, `first_month {apply_date, filed_on, amount, days_counted, month_label, estimate}`, `slots`, `yellow_lines[]`, `flags[]`, `asked[]`, `skipped[]`, `rule_trace[]`, `tracking`, `consent {given, at}`, `privacy_events[] {kind, at}`, `language_request {asked, offered}`, `program_answers {question: {value, at, source}}` (source `card` or `seed`), `program_progress {program: {applied, at}}` |
| `Slot` | `value`, `display`, `state`, `heard`, `heard_en`, `turn`, `source`, `confirmed`, `changed_from` |
| `YellowLine` | `id`, `slot`, `kind`, `code`, `reason`, `heard`, `assumed`, `effect {kind: amount \| tier \| expedited, delta_usd}`, `resolved` (`confirm` \| `edit`), `resolved_at`, `resolved_note` |
| `AskedQuestion` · `SkippedQuestion` | `turn`, `key`, `slots`, `kind`, `reason`, `outcomes` · `slot`, `reason`, `detail` |
| `RuleStep` | `step`, `result`, `source`, `value` |
| `Tracking` | `applied_at`, `filed_on`, `deadline_30d`, `interview_at`, `interview_missed`, `doc_request_at`, `doc_due`, `approved_at`, `sar7_due`, `recert_due` |
| `CaseSummary` (list rows) | `id`, `code`, `summary`, `version`, `created_at`, `updated_at`, `lang`, `channel`, `live`, `seeded`, `status`, `ended_early`, `tier`, `reason_code`, `estimate_monthly`, `estimate_is_floor`, `expedited_possible`, `yellow_open`, `yellow_total`, `asked_count`, `skipped_count`, `next_deadline`, `found_display` (`null` unless a likely case has a programs result) |
| `CaseListResponse` | `items[]` (CaseSummary), `seq`, `server_time` |
| `CaseDetail` | `case`, `summary`, `card_url`, `qr_svg_url`, `short_code`, `can_review`, `allowed_status`, `rules` (`label`, `effective_from`, `effective_to`, `sources[] {id, title, date}`), `programs` (`ProgramsResult` or `null`, below) |
| `ProgramsResult` (`CaseDetail.programs`; built through the programs port, never stored) | `table_id`, `checked`, `mode` (`full` \| `list_only`), `calfresh_yearly`, `found_yearly`, `found_display`, `share_display`, `claimed_display`, `lines[]`, `open_questions[]`, `next_question`, `question_spreads`, `console_notes[]` |
| `ProgramLine` (`lines[]`, language-free) | `id`, `status` (`likely` \| `maybe` \| `check` \| `coverage` \| `zero` \| `note`), `value_yearly`, `display_yearly`, `counted`, `range_lo`, `range_hi`, `stage` (`today` \| `after_approval` \| `tax_time`), `order`, `apply_by`, `vars`, `note_keys[]`, `basis[]` (English trace lines with numbers), `source_ids[]`, `applied` |
| `ConsoleMeta` | `rules`, `rules_valid_today`, `slot_specs` (the A3.5 labels, including `roommates_count`), `demo_mode`, `live_transcript`, `card_delivery` (`screen` \| `code`), `demo_phone_display`, `app_version`, `programs` (`null` when `GP_PROGRAMS=0`: `table_id`, `label`, `checked`, `effective_from`, `effective_to`, `programs[]` (ids in priority order), `names` (English program names), `console_texts` (gray-note texts), `questions[]`, `sources[] {id, title, date}` of the programs table, for section 6b's program, gray-note and source columns) |
| `LiveView` (`GET /api/cases/{id}/live`) | `case_id`, `lines[]` (live transcript lines, below), `now_asking_text`, `asked_reason` |
| `CaseEvent` (SSE) | `seq`, `type`, `case_id`, `summary` (CaseSummary), `changed_slots[]`, `changed_programs` (true after a card answer or *I applied* mark), `now_asking_text`, `asked_reason`, `line` (only for `live.turn`), `at` |
| `PublicInfo` (landing and talk page) | `demo_phone_display`, `rules_label`, `effective_from` |

Two different things are called `summary`: `Case.summary` (and the list row's `summary`) is the one-line text built
by code, such as `Undergrad · 1 person · work $900 · rent $1,100`; `CaseDetail.summary` and `CaseEvent.summary` are the
case's `CaseSummary` object (counts such as `asked_count`).

Never present in any of these: a name, a phone number or anything derived from it, audio, a full transcript, a Social
Security or card number, a volunteered immigration status, disability-benefit details, or a handoff field.

### A8.2 Card

| Model | Fields the UI uses |
|---|---|
| `CardView` | `lang`, `code` (shown on the card and in the print header), `tier`, `reason_code`, `headline`, `subhead`, `estimate_monthly`, `estimate_is_floor`, `expedited`, `first_month`, `blocks[] {id, title, paragraphs[], bullets[], rows[] {screen, question, answer}, tone, collapsed}`, `footer[]`, `sources[] {id, title, date}`, `rules_label`, `status` (the card status below, for the first render), `generated_at`, `expires_at`, `reminders_url`, `delete_url`, `unlocked` (`UnlockedView` or `null`, `docs/SPEC.md` §6.2) |
| card status (`CardStatus`) | `{status, reviewed, reviewed_at, tier, estimate_monthly}` |
| `UnlockedView` | `mode` (`full` \| `list_only`), `title`, `total_text`, `found_display`, `claimed_display`, `calfresh_display`, `segments[]` (`[program id, display value]` pairs in plan order), `question` (`UnlockedQuestion` or `null`), `chips[]`, `programs[]` (`UnlockedProgram`), `share_text` (or `null`), `footnote`, `labels` (the control labels of A4.7, already in `lang`), `lang` |
| `UnlockedQuestion` · `UnlockedChoice` | `id`, `text`, `choices[]`, `index`, `total` · `value`, `label` |
| `UnlockedProgram` | `id`, `name`, `status`, `status_label`, `value_text`, `counted`, `line`, `notes[]`, `stage`, `stage_label`, `apply_by_text`, `apply_url`, `apply_label`, `applied`, `can_mark_applied`, `prefill[] {screen, question, answer}`, `source_text` |
| `ProgramAnswersRequest` · `ProgramProgressRequest` | `{answers: {question id: choice}}` (1–3 entries) · `{program, applied}` |

### A8.3 Endpoints and live events

| Method · path | Used by | Notes |
|---|---|---|
| `POST /api/console/login` · `POST /api/console/logout` | console | passcode → session cookie (5 tries per minute per IP) · clears it |
| `GET /api/meta` · `GET /api/cases?status=&since_seq=&limit=` · `GET /api/cases/{id}` | console | ConsoleMeta · CaseListResponse · CaseDetail |
| `GET /api/events` | console | SSE of CaseEvent: `case.created`, `case.updated`, `case.deleted`, `demo.reset`, `resync`, `live.turn`, `live.ended`; `Last-Event-ID` replays `case.*` and `demo.reset` only, never `live.*`. A `case.updated` from the card (answer or mark) carries `changed_programs: true` |
| `GET /api/cases/{id}/live` | console | LiveView from process memory; `404` when the setting is off, when the case is not live, and after the call |
| `POST /api/cases/{id}/yellow/{yid}` | console | `{action: confirm \| edit, value?, note?, expected_version}` → CaseDetail; edit re-runs the rules; `409 conflict` for a stale version |
| `POST /api/cases/{id}/status` | console | `{status, expected_version}` → CaseDetail; `409 locked` while any yellow line is open; `409 conflict` for a live case, a stale version or a transition that is not allowed |
| `PATCH /api/cases/{id}/tracking` · `DELETE /api/cases/{id}` · `GET /api/cases/{id}/qr.svg` | console | tracking dates → CaseDetail (deadlines computed) · delete · card QR (`qr_svg_url`) |
| `GET /api/qr/talk.svg?lang=en\|es` | console | QR of the talk page (empty state, Live view idle, language-request chip) |
| `POST /api/demo/seed` · `POST /api/demo/reset` | console demo menu | `{seeded, replaced}`: samples with dates relative to the seed time (never before 2026-10-01), replacing the old samples · `{deleted, kept}`: removes every case that is not seeded. The menu's *Reset demo* always sends reset, then seed (A2.5) |
| `GET /api/card/{token}?lang=en\|es` · `GET /api/card/{token}/status` · `GET /api/card/{token}/reminders.ics?lang=` · `DELETE /api/card/{token}` | card | public by token (`404`, or `410` once expired); status carries no personal data |
| `POST /api/card/{token}/answers?lang=` | card (unlocked part) | `ProgramAnswersRequest` → `UnlockedView`, re-planned; stores `program_answers` (source `card`; a newer answer to the same question replaces the older one); emits `case.updated` with `changed_programs: true`. `404`, `410`, `422` (unknown question or choice, or a question that is not open for this case), `409 conflict` while the call is live (answers only after the call ended), `429` (30 a minute per card) |
| `POST /api/card/{token}/progress?lang=` | card (unlocked part) | `ProgramProgressRequest` → `UnlockedView`; stores `program_progress`; emits `case.updated` with `changed_programs: true`. `404`, `410`, `422` (unknown program, a program that is not shown, or one that cannot be marked), `429` |
| `POST /api/card/lookup` | `/go` | `{code}` (6 digits) → `{url}`; `404` unknown or expired, `429` after 5 tries per minute |
| `GET /api/public/info` | landing, talk page | PublicInfo (no login) |
| `POST /api/web/sessions`, then `/v1/calls/{call_id}/start`, `/turn`, `/end` | talk page | bearer token; the same brain as the phone line |

Live transcript lines (`LiveTurn`, demo setting `GP_LIVE_TRANSCRIPT=1`): per line the console needs `case_id`, `turn`,
`who` (`student` or `assistant`), `text` (already redacted by the brain), `lang` and `at`. `GET /api/cases/{id}/live`
returns the lines so far, for a console that opens mid-call or reconnects. On `live.ended` the console removes them
from the DOM.

---

## A9. Acceptance checks (no Playwright, axe-core or npm)

Run against fixtures first, then against the real API. "Browser pane" means the build session's built-in browser: it
takes the screenshots and runs the page-console snippets.

| # | Check | How |
|---|---|---|
| 1 | Design-system check | `python3 tools/check_contrast.py` exits 0 (contrast, token sync, light theme, color literals, fonts, icons, CSP-safe HTML and CSS; see A6.1). |
| 2 | Viewports, no horizontal scroll | Browser pane screenshots: console at 1366×768 and 1920×1080 (also 1280×800); card and talk at 390×844, 360×800 and 320×640. In the page console `document.documentElement.scrollWidth <= innerWidth` is `true`. |
| 3 | Light only | `tools/check_contrast.py` passes (no `prefers-color-scheme` under `web/`, the color-scheme `<meta>` on every page); in the Browser pane the computed `body` background has a relative luminance of at least 0.85. |
| 4 | Keyboard | Tab from the top of each page. Console: skip link, top bar, list, detail, yellow actions, lock. Card: language switch, sections, buttons in visual order. Talk: Start, mic, text field, quick replies. `Enter`/`Space` activate; `Esc` closes dialogs and returns focus; the focus ring is always visible; `↑`/`↓` move in the list; the shortcuts switch turns single keys off. |
| 5 | Interface guidelines review | Run the build session's `web-design-guidelines` review on each page's HTML, CSS and JS; fix every finding or write down why not. |
| 6 | Forbidden phrases | `grep -rniwE --exclude=guards.json -e "not eligible" -e "ineligible" -e "don'?t qualify" -e "denied" -e "no califica" -e "no eres elegible" web/ data/content/` prints nothing and exits 1 (whole words, so identifiers such as `previously_denied` don't match; code comments count too; `guards.json` holds the patterns themselves). Use one `-e` per phrase: inside `-E`, an escaped pipe is a literal character and would make the check pass on anything. |
| 7 | Lock (W3) | With an open yellow line, `POST /api/cases/{id}/status` returns `409 locked` and the button shows its reason; after *Looks right* it is enabled; *Mark reviewed*, and the card banner appears within 5 s. After *Reset demo*, Sofia's line is open and the lock closed again. |
| 8 | Live (W1) | A scripted Maria call (fake LLM, `GP_LIVE_TRANSCRIPT=1`, `GP_CARD_DELIVERY=screen`, turns from `contracts/examples/maria_phone.json`): fields fill in order; the range goes from `[155, 306]` to `[306, 306]`; the $151 chip appears; the chips *Not asked — heating or cooling bill, same estimate either way* and the one for other utility bills appear; at the end the transcript nodes leave the DOM and `GET /api/cases/{id}/live` returns `404`. |
| 9 | Card (W2) | Set `window.__noReload = true` in the page console, switch to Español: `<html lang="es">` and `window.__noReload` is still `true` (no reload); the `.ics` has 3 `VEVENT`s dated from `first_month.filed_on`; dispatching `beforeprint` opens every `<details>`; the print stylesheet hides buttons and toggles. |
| 10 | Talk | Denied microphone: typing mode with the message. No speech recognition: typing mode. Spanish uses `es-US`. |
| 11 | Reduced motion | `tokens.css` has the reduced-motion rule; with the system setting on, the fill and the count-up are instant. |
| 12 | Text size 200% | In the page console run `document.documentElement.style.fontSize = "200%"` (the layout is rem-based): the card stays readable, nothing is clipped or overlapping, no horizontal scroll at 390 px. |
| 13 | Clean console, no third parties | No errors in the Browser pane console; every network request is same-origin. |
| 14 | Icons exist | `tools/check_contrast.py` passes (every literal `icons.svg#id` reference exists in the sprite); for ids built at run time, no broken `<use>` shows in the Browser pane. |
| 15 | Card weight | HTML + CSS + JS of `/c/{token}` at most 60 KB uncompressed, fonts excluded (network list sizes); `/unlocked/unlocked.js` + `/unlocked/unlocked.css` at most 12 KB together. |
| 16 | Unlocked part (W4) | Fixtures first (`card_maria_en.json` with `unlocked_maria_steps.json`), then the real API with Maria's case after the call. At 390×844, 360×800 and 320×640: the bar, the total, the claimed line and the question show with no horizontal scroll (`document.documentElement.scrollWidth <= innerWidth`); every choice, *I applied* and *Share* button is at least 48 px high. Three taps show $3,670 → $3,830 → $4,050 → $4,220 and *Question 1 of 3*, *2 of 3*, *3 of 3*, then no question. Keyboard: Tab reaches the choices, *Your plan*, its links and buttons and *Share* in visual order; `Enter`/`Space` answer; focus lands on the next question, then on the total. The live region (`role="status"`) holds the new total after each answer. Share fallback: with `navigator.share` removed in the page console, *Share* copies and shows *Copied*; the copied text contains *about $4,200* and no `/c/`, token or case code. Dispatching `beforeprint` opens *Your plan*; the print stylesheet hides the bar graphic and the question. Under reduced motion the total changes without a count-up. Español: the part re-renders without a reload and the answers stay. The console's section 6b shows the new rows within 2 s of each tap. Sofia's card shows only *More help to check with the coordinator* with no amount; with `GP_PROGRAMS=0` no card shows the part. |

---

## A10. Sources (checked 2026-10-01)

- CDSS All County Information Notice I-40-26 (2026-09-10): FY2027 amounts in effect 2026-10-01 to 2027-09-30 —
  maximum $306 for 1 person, standard deduction $217 (1–3 people), shelter cap $769, gross income limit (200%) $2,660
  for 1 person.
- CDSS All County Letter 26-16 (2026-03-19): AB 42 — grants, awards, scholarships, fellowships and loans for attending
  higher education are not counted as income for CalFresh, effective 2026-03-01 for new applicants; cash from friends
  or relatives still counts.
- CDSS All County Letter 26-25 (2026-04-13): from 2026-06-01, students attending a CCC, CSU or UC half-time or more
  in an associate or bachelor's degree program qualify for the LPIE exemption from the student rule.
- California Policy Lab, *CalFresh Participation Among California's College Students: A 2023–24 School Year Update*,
  August 2026 — Table 2, CSU undergraduates: San Francisco 14.3%, all CSU 16.4%, Chico 33.0% (share of the student
  body enrolled in CalFresh; not a share of eligible students).
- SF State Basic Needs, CalFresh Help Clinic page: book an appointment with a CalFresh coordinator by emailing
  calfresh@sfsu.edu; (415) 338-1203; Student Services Building, Room 301; Monday–Thursday 8:30 am–5 pm, Friday
  8:30 am–4 pm.
- CDSS, CalFresh Noncitizen Eligibility FAQ: refers people to their BenefitsCal.com account (the source for the
  BenefitsCal web address).
- WCAG 2.2 (W3C Recommendation): success criteria 1.4.3, 1.4.4, 1.4.10, 1.4.11, 2.1.4, 2.5.8.
- The card's unlocked part (W4): every program value, rule and date comes from `data/rules/programs_2026.json` (rules
  checked 2026-10-01), whose sources are listed with their dates in `docs/SPEC.md` §13 (for example SFMTA fares, the
  SF State Gator Pass and academic calendar pages, CPUC California LifeLine and CARE pages, PG&E form 01-9077, DHCS
  ACWDL 26-01, FTB 3514 (2025) and IRS Rev. Proc. 2025-32).
- Atkinson Hyperlegible Next: the name tables of both font files, upright and italic (version 2.001, copyright line,
  license URL openfontlicense.org; `tnum` feature present), and the SIL Open Font License 1.1 text in
  `web/shared/fonts/OFL.txt`.
