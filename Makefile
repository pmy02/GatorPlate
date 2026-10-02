# GatorPlate make targets. Every Python process starts with a clean environment (CLEAN): only PATH, HOME,
# TMPDIR, the standard proxy variables and PYTHONUTF8 pass through, then each target sets the GP_* values it needs.
# Live targets pass GP_LLM_API_KEY through by reference, so its value is never echoed.

PY      ?= .venv/bin/python
BASE    ?=
PORT    ?= 8105
WEB     ?= web
ONLY    ?=
CLEAN    = env -i PATH="$$PATH" HOME="$$HOME" TMPDIR="$$TMPDIR" PYTHONUTF8=1 PYTHONPATH="$(CURDIR)" \
           HTTPS_PROXY="$$HTTPS_PROXY" HTTP_PROXY="$$HTTP_PROXY" NO_PROXY="$$NO_PROXY"
KEY      = $(if $(filter anthropic,$(LLM)),GP_LLM_API_KEY="$$GP_LLM_API_KEY",)
SECRETS  = $(if $(SIGN),GP_GATEWAY_SECRET="$$GP_GATEWAY_SECRET" GP_CONSOLE_PASSCODE="$$GP_CONSOLE_PASSCODE",)
TESTENV  = $(CLEAN) GP_ENV=test GP_LLM_PROVIDER=fake GP_DEBUG_KEYS=1 GP_DEMO_MODE=1 GP_LIVE_TRANSCRIPT=0 GP_CARD_DELIVERY=code
DEVENV   = $(CLEAN) GP_ENV=dev GP_LLM_PROVIDER=$(or $(LLM),fake) $(KEY) GP_DEBUG_KEYS=1 GP_DEMO_MODE=1 GP_LIVE_TRANSCRIPT=1 \
           GP_CARD_DELIVERY=$(or $(CARD),screen) GP_DB_PATH=$(or $(DB),var/dev.db) \
           GP_PUBLIC_BASE_URL=http://127.0.0.1:$(or $(APP_PORT),8000)
TOOLENV  = $(CLEAN) GP_ENV=dev
# E2E runner: remote mode with BASE (no server started), else local mode (one server per declared environment)
RUNNER   = $(TOOLENV) $(SECRETS) $(KEY) $(PY) tools/e2e_run.py \
           $(if $(BASE),--base $(BASE),--serve --port $(or $(APP_PORT),8000) $(if $(filter anthropic,$(LLM)),--llm anthropic,)) \
           $(if $(CONC),--concurrency $(CONC),)

# Every target is phony: without this line `make web` does nothing, because the folder web/ exists.
.PHONY: lint test test-core test-rules test-extract test-dialogue test-api test-card test-programs test-e2e-static test-web \
        validate-data check-examples contrast check run web fixtures e2e adversarial examples eval bench test-live \
        leakcheck ownership say py

lint:            ; $(CLEAN) $(PY) -m ruff check gatorplate tests tools
test:            ; $(TESTENV) $(PY) -m pytest -q -m "not live"
test-core:       ; $(TESTENV) $(PY) -m pytest -q tests/test_*.py
test-rules:      ; $(TESTENV) $(PY) -m pytest -q tests/rules
test-extract:    ; $(TESTENV) $(PY) -m pytest -q tests/extract -m "not live"
test-dialogue:   ; $(TESTENV) $(PY) -m pytest -q tests/dialogue
test-api:        ; $(TESTENV) $(PY) -m pytest -q tests/api tests/store
test-card:       ; $(TESTENV) $(PY) -m pytest -q tests/card
test-programs:   ; $(TESTENV) $(PY) -m pytest -q tests/programs
test-e2e-static: ; $(TESTENV) $(PY) -m pytest -q tests/e2e/test_static.py
test-web:        ; @if command -v node >/dev/null 2>&1; then node --test "$(WEB)/**/*.test.mjs"; else echo "node not installed: skipped"; fi
validate-data:   ; $(TOOLENV) $(PY) tools/validate_data.py && $(TOOLENV) $(PY) data/content/check_content.py && $(TOOLENV) $(PY) contracts/check_examples.py
check-examples:  ; $(TOOLENV) $(PY) contracts/check_examples.py
contrast:        ; $(TOOLENV) $(PY) tools/check_contrast.py
check:           lint test validate-data contrast leakcheck
run:             ; $(DEVENV) $(PY) -m uvicorn gatorplate.main:app --host 127.0.0.1 --port $(or $(APP_PORT),8000) --workers 1 --no-access-log
web:             ; $(CLEAN) $(PY) -m http.server $(PORT) --bind 127.0.0.1 -d web
fixtures:        ; $(DEVENV) $(PY) tools/make_fixtures.py
e2e:             ; $(RUNNER) --scripts tests/e2e/scripts $(if $(LIVE),--live,) $(if $(ONLY),--only $(ONLY),)
adversarial:     ; $(RUNNER) --scripts tests/adversarial/scripts
examples:        ; $(RUNNER) --examples contracts/examples
eval:            ; $(TOOLENV) $(if $(LIVE),GP_LLM_PROVIDER=anthropic GP_LLM_API_KEY="$$GP_LLM_API_KEY",) $(PY) tools/simulate_student.py --base $(or $(BASE),http://127.0.0.1:8000) --personas data/eval/personas.json $(if $(LIVE),--live --max-usd $(or $(MAX_USD),3),) $(if $(ONLY),--only $(ONLY),) $(ARGS)
bench:           ; $(TOOLENV) GP_LLM_PROVIDER=anthropic GP_LLM_API_KEY="$$GP_LLM_API_KEY" $(PY) tools/bench_llm.py --n 30
test-live:       ; $(TESTENV) GP_LLM_PROVIDER=anthropic GP_LLM_API_KEY="$$GP_LLM_API_KEY" $(PY) -m pytest -q -m live tests/extract
leakcheck:       ; $(TOOLENV) $(PY) tools/leakcheck.py --root . $(if $(HISTORY),--git-history,)
ownership:       ; $(TOOLENV) $(PY) tools/check_ownership.py $(if $(BASELINE),--baseline,) $(if $(AGENT),--agent $(AGENT),) $(if $(FILES),--files $(FILES),)
say:             ; $(TOOLENV) $(PY) tools/say_call.py --base $(or $(BASE),http://127.0.0.1:$(or $(APP_PORT),8000)) $(ARGS)
py:              ; $(TOOLENV) $(PY) $(SCRIPT)
