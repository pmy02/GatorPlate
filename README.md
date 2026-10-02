# GatorPlate

GatorPlate is a student-built prototype that helps SF State students check whether they may get CalFresh, California's
food benefit. A student talks to it on the phone or on the web (English and Spanish on the web). It asks only the
questions that can change the answer, gives an estimate that the county decides, and hands the student a card with
the next steps. The SF State CalFresh coordinator sees each conversation's answers in a console and checks them.

It is not an official SF State, county or CalFresh service. GatorPlate never decides eligibility: every amount is an
estimate, and the county makes the final decision.

## How it works

- **The model listens, rules decide, templates speak.** A language model only turns what the student says into
  answers. A rules engine computes the result from a dated rules table, and every sentence comes from a reviewed
  sentence bank.
- **Only ask what can change the answer.** Questions that would not change the estimate are skipped and shown as
  "not asked" in the console.
- **A person checks.** Answers the system is unsure about become yellow lines that the coordinator confirms before a
  case can be marked reviewed.
- **Money you may be missing.** The student card also lists other programs CalFresh opens (Medi-Cal coverage,
  Clipper START, PG&E CARE, California LifeLine, tax credits), each computed by code from a dated programs table.
  Each agency decides; nothing is a promise.

Product truth: [`docs/SPEC.md`](docs/SPEC.md). Brain API: [`docs/BRAIN_API.md`](docs/BRAIN_API.md) and
[`contracts/`](contracts/). Screens: [`docs/UI_SPEC.md`](docs/UI_SPEC.md).

## Run it locally

Requirements: Python 3.12. No Node, no build step, no external services are needed for the default setup (the fake
language model is used unless a key is configured).

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
make run          # the app on http://127.0.0.1:8000 (console at /console, talk page at /talk)
make web PORT=8105  # static pages in fixture mode, for example http://127.0.0.1:8105/console/?fixtures=1
```

Settings are environment variables named `GP_*` only; `.env.example` lists every name. Make targets start Python with
a clean environment and set the values they need.

## Test it

```sh
make test            # the full suite with the fake language model
make lint            # ruff
make validate-data   # rules tables, golden cases, demo cases, content, contract examples
make check-examples  # the Brain API contract examples
make contrast        # design system: contrast, tokens, light theme, fonts, icons, CSP-safe pages
make leakcheck       # generic public-repository checks
```

## Privacy

- GatorPlate never receives audio or the caller's phone number. The web page uses the browser's own speech
  recognition; GatorPlate only gets text.
- Digits that look like a Social Security or card number are removed before anything else sees the text. We don't
  collect Social Security numbers, and we never ask about immigration status.
- A case keeps the student's answers, not the conversation. Students can delete their information from the card.

## License

MIT — see [`LICENSE`](LICENSE).

## Notices

Third-party material (the Atkinson Hyperlegible Next font, SIL Open Font License 1.1) is listed in
[`NOTICE.md`](NOTICE.md). Icons and the logo are original work.
