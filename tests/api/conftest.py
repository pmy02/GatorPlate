"""API test fixtures: the real app and stores on a temporary database, the fixed clock, fixed ids and the fakes of
tests/api/fakes.py. `make_client(**settings)` builds a client with other settings (prod, programs off, live
transcript on, ...)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gatorplate.api.app import create_app
from gatorplate.contracts.case import CardRef, Case, Slot
from gatorplate.contracts.common import Channel, Lang, SlotSource, SlotState, Tier
from gatorplate.contracts.slots import SlotName
from tests.api.fakes import make_deps, make_settings

PASSCODE = "dev"


class Harness:
    def __init__(self, client: TestClient, app: Any, deps: Any, clock: Any) -> None:
        self.client, self.app, self.deps, self.clock = client, app, deps, clock

    @property
    def ctx(self) -> Any:
        return self.app.state.ctx

    def login(self) -> TestClient:
        r = self.client.post("/api/console/login", json={"passcode": PASSCODE})
        assert r.status_code == 200, r.text
        return self.client

    def add_case(self, *, code: str = "K7Q-2FM", tier: Tier | None = Tier.likely, live: bool = False,
                 lang: Lang = Lang.en, token: str = "cardtoken0000000000000001", short_code: str | None = None,
                 card_days: int = 7, slots: dict[str, str] | None = None, apply_rules: bool = True) -> Case:
        now = self.clock.now()
        case = Case(id=self.deps.ids.case_id(), code=code, created_at=now - timedelta(minutes=3), updated_at=now,
                    lang=lang, channel=Channel.phone, live=live)
        for name, raw in (slots or {"age": "20", "lives_with_parent": "false", "earned_monthly": "900.00",
                                    "rent_share": "1100.00", "rent_paid_by_others_to_landlord": "0.00"}).items():
            case.slots[SlotName(name)] = Slot(value=raw, state=SlotState.clear, source=SlotSource.seed, turn=1)
        if apply_rules:
            case = self.deps.rules.apply(case, now=now)
        if tier is None:
            case.tier = case.reason_code = case.estimate_monthly = None
        case.card = CardRef(token=token, short_code=short_code,
                            short_code_expires_at=now + timedelta(hours=24) if short_code else None,
                            created_at=now, expires_at=now + timedelta(days=card_days))
        return self.deps.cases.create(case)


@pytest.fixture
def make_client(clean_gp_env, tmp_db, fixed_clock, fixed_ids) -> Callable[..., Harness]:
    clients: list[TestClient] = []

    def build(*, programs_port: Any = None, rules: Any = None, brain: Any = None, understanding: Any = None,
              **overrides: Any) -> Harness:
        settings = make_settings(tmp_db, **overrides)
        deps = make_deps(settings, clock=fixed_clock, ids=fixed_ids, programs=programs_port, rules=rules,
                         brain=brain, understanding=understanding)
        app = create_app(deps)
        client = TestClient(app, base_url="https://testserver")
        clients.append(client)
        return Harness(client, app, deps, fixed_clock)

    yield build
    for client in clients:
        client.close()


@pytest.fixture
def h(make_client) -> Harness:
    return make_client()
