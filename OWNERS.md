# Owners

Who may write which files during the parallel build. Every path has exactly one owner group; `tools/check_ownership.py`
reads the block below (and nothing else in this file).

Glob rules: paths are relative to the repository root; `*` matches within one path segment (never `/`), `**` matches
any depth, `{a,b}` lists alternatives. A root-level `*` therefore matches only the files directly in the root.

| Owner | Writes |
|---|---|
| S0, then INT | root files; `docs/**`; `contracts/**`; `gatorplate/{__init__,config,clock,ids,deps,wiring,main}.py`; `gatorplate/contracts/**`; `data/content/{contacts.json,check_content.py}`; `data/design/**`; `web/shared/**`; `web/fixtures/**`; `tests/{conftest.py,test_*.py,snapshots/**}`; `tools/{leakcheck,check_ownership,validate_data,make_fixtures,check_contrast}.py` |
| A1 rules | `gatorplate/rules/**`, `tests/rules/**`, `data/rules/ca_*.json`, `data/golden/golden_*.json` |
| A2 understand | `gatorplate/extract/**`, `tests/extract/**`, `data/tests/**`, `data/content/guards.json`, `tools/bench_llm.py` |
| A3 dialogue | `gatorplate/dialogue/**`, `tests/dialogue/**`, `data/content/sentences.*.json` |
| A4 platform | `gatorplate/store/**`, `gatorplate/api/**`, `tests/store/**`, `tests/api/**`, `data/demo_cases/**` |
| A5 console | `web/console/**` |
| A6 card | `gatorplate/card/**`, `web/card/**`, `web/go/**`, `tests/card/**`, `data/content/card.*.json` |
| A7 talk and landing | `web/talk/**`, `web/index.html`, `web/landing.*`, `web/about/**` |
| A8 QA | `tests/e2e/**`, `tests/adversarial/**`, `tools/{say_call,e2e_run,simulate_student}.py`, `data/eval/**` |
| A9 programs | `gatorplate/programs/**`, `tests/programs/**`, `web/unlocked/**`, `data/rules/programs_*.json`, `data/golden/programs_*.json`, `data/content/programs.*.json` |

- **Frozen** after the foundation gate (changed only by the integrator, for an accepted `CONTRACT_REQUESTS.md` entry):
  `docs/**`, `contracts/**`, `gatorplate/contracts/**`, `gatorplate/{config,clock,ids,deps}.py`,
  `data/content/{contacts.json,check_content.py}`, `data/design/**`, `web/shared/**`.
- **Shared:** `CONTRACT_REQUESTS.md` takes appends from every agent; any other change to it is the integrator's.
- **Any file:** the integrator (INT) and the freeze agent (FREEZE) are single writers and may edit any file.
- **Never checked:** paths that are never committed (`.git/`, `.build/`, `.claude/`, `.venv/`, `var/`, caches and the
  other `.gitignore` patterns).
- Prepared files keep the owner listed above; `data/golden/golden_cases.json` and `data/golden/programs_golden.json`
  are add-only for their owners.

```owners
# kind     agents            glob
owner      S0,INT            *
owner      S0,INT            docs/**
owner      S0,INT            contracts/**
owner      S0,INT            gatorplate/{__init__,config,clock,ids,deps,wiring,main}.py
owner      S0,INT            gatorplate/contracts/**
owner      S0,INT            data/content/{contacts.json,check_content.py}
owner      S0,INT            data/design/**
owner      S0,INT            web/shared/**
owner      S0,INT            web/fixtures/**
owner      S0,INT            tests/{conftest.py,test_*.py,snapshots/**}
owner      S0,INT            tools/{leakcheck,check_ownership,validate_data,make_fixtures,check_contrast}.py
owner      A1                gatorplate/rules/**
owner      A1                tests/rules/**
owner      A1                data/rules/ca_*.json
owner      A1                data/golden/golden_*.json
owner      A2                gatorplate/extract/**
owner      A2                tests/extract/**
owner      A2                data/tests/**
owner      A2                data/content/guards.json
owner      A2                tools/bench_llm.py
owner      A3                gatorplate/dialogue/**
owner      A3                tests/dialogue/**
owner      A3                data/content/sentences.*.json
owner      A4                gatorplate/store/**
owner      A4                gatorplate/api/**
owner      A4                tests/store/**
owner      A4                tests/api/**
owner      A4                data/demo_cases/**
owner      A5                web/console/**
owner      A6                gatorplate/card/**
owner      A6                web/card/**
owner      A6                web/go/**
owner      A6                tests/card/**
owner      A6                data/content/card.*.json
owner      A7                web/talk/**
owner      A7                web/index.html
owner      A7                web/landing.*
owner      A7                web/about/**
owner      A8                tests/e2e/**
owner      A8                tests/adversarial/**
owner      A8                tools/{say_call,e2e_run,simulate_student}.py
owner      A8                data/eval/**
owner      A9                gatorplate/programs/**
owner      A9                tests/programs/**
owner      A9                web/unlocked/**
owner      A9                data/rules/programs_*.json
owner      A9                data/golden/programs_*.json
owner      A9                data/content/programs.*.json
frozen     -                 docs/**
frozen     -                 contracts/**
frozen     -                 gatorplate/contracts/**
frozen     -                 gatorplate/{config,clock,ids,deps}.py
frozen     -                 data/content/{contacts.json,check_content.py}
frozen     -                 data/design/**
frozen     -                 web/shared/**
shared     *                 CONTRACT_REQUESTS.md
anyfile    INT,FREEZE        **
skip       -                 .git/**
skip       -                 .build/**
skip       -                 .claude/**
skip       -                 .venv/**
skip       -                 var/**
skip       -                 **/__pycache__/**
skip       -                 **/.pytest_cache/**
skip       -                 **/.ruff_cache/**
skip       -                 **/node_modules/**
skip       -                 **/*.pyc
skip       -                 **/*.db
skip       -                 **/*.sqlite*
skip       -                 **/.env
skip       -                 **/.DS_Store
skip       -                 **/CLAUDE.md
skip       -                 **/CLAUDE.local.md
skip       -                 **/AGENTS.md
```
