"""The integration wiring: build_deps builds every real module on one clock, the app boots on it, and GP_PROGRAMS=0
hides every programs surface (docs/SPEC.md §5.10)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gatorplate.api.app import create_app
from gatorplate.card import CardBuilder
from gatorplate.clock import SystemClock
from gatorplate.dialogue import Brain
from gatorplate.extract import Understander
from gatorplate.ids import SystemIds
from gatorplate.programs import Programs
from gatorplate.rules import Rules
from gatorplate.store import CaseStore, EventBus, LiveStore, SessionStore
from gatorplate.wiring import build_deps, compose


def test_build_deps_uses_the_real_modules(settings_test) -> None:
    deps = build_deps(settings_test)
    assert isinstance(deps.clock, SystemClock) and isinstance(deps.ids, SystemIds)
    assert isinstance(deps.rules, Rules) and isinstance(deps.understanding, Understander)
    assert isinstance(deps.brain, Brain) and isinstance(deps.cards, CardBuilder)
    assert isinstance(deps.cases, CaseStore) and isinstance(deps.sessions, SessionStore)
    assert isinstance(deps.live, LiveStore) and isinstance(deps.events, EventBus)
    assert isinstance(deps.programs, Programs) and deps.programs.enabled is True
    # One programs engine and one clock everywhere.
    assert deps.cards.programs is deps.programs
    assert deps.brain.clock is deps.clock and deps.understanding.clock is deps.clock
    assert deps.understanding.llm_health()["provider"] == "fake"


def test_compose_pins_clock_and_ids(settings_test, fixed_clock, fixed_ids) -> None:
    deps = compose(settings_test, clock=fixed_clock, ids=fixed_ids)
    assert deps.clock is fixed_clock and deps.ids is fixed_ids and deps.brain.ids is fixed_ids
    assert deps.rules.valid_on(fixed_clock.today())


def test_app_boots_and_health_reports_the_wiring(settings_test) -> None:
    deps = build_deps(settings_test)
    with TestClient(create_app(deps)) as client:
        assert client.get("/v1/health").json() == {"ok": True}
        health = client.get("/healthz").json()
    assert health["rules_valid_today"] is True
    assert health["llm"]["provider"] == "fake"
    assert health["programs"]["enabled"] is True and health["programs"]["valid_today"] is True


def test_programs_off_hides_every_surface(settings_test) -> None:
    deps = build_deps(settings_test.model_copy(update={"programs": False}))
    assert deps.programs.enabled is False and deps.programs.meta() is None
    assert deps.cards.programs is deps.programs
