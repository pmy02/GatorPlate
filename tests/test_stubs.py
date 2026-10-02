"""Module stubs carry their final signatures; the programs engine built with enabled=False answers None / False."""

from __future__ import annotations

import importlib
import inspect
from datetime import UTC, date, datetime

import pytest

from gatorplate.contracts.case import Case
from gatorplate.contracts.common import Channel, Lang
from gatorplate.contracts.errors import InvalidRequest
from gatorplate.programs import Programs

CASE = Case(id="c_aaaaaaaaaa", code="K7Q-2FM", created_at=datetime(2026, 10, 2, 17, tzinfo=UTC),
            updated_at=datetime(2026, 10, 2, 17, tzinfo=UTC), lang=Lang.en, channel=Channel.phone)
TODAY = date(2026, 10, 2)


def test_programs_signature() -> None:
    sig = inspect.signature(Programs)
    params = sig.parameters
    assert list(params) == ["enabled", "table_path", "content_dir", "guards_path", "public_base_url"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())
    assert params["enabled"].default is True and params["public_base_url"].default == ""
    assert callable(Programs.from_settings)


def test_programs_disabled_answers_none() -> None:
    p = Programs(enabled=False)
    assert p.evaluate(CASE, today=TODAY) is None
    assert p.view(CASE, lang=Lang.en, today=TODAY) is None
    assert p.meta() is None
    assert p.can_mark(CASE, "calfresh", today=TODAY) is False
    with pytest.raises(InvalidRequest):
        p.validate_answers(CASE, {"tax_dependent": "no"}, today=TODAY)


def test_programs_from_settings(settings_test) -> None:
    p = Programs.from_settings(settings_test)
    assert p.enabled is True and p.table_path == settings_test.programs_table_path
    assert p.public_base_url == "http://127.0.0.1:8000"
    off = Programs.from_settings(settings_test.model_copy(update={"programs": False}))
    assert off.view(CASE, lang=Lang.es, today=TODAY) is None


def test_stubs_import_and_raise() -> None:
    from gatorplate.rules import Rules

    rules = Rules(__import__("pathlib").Path("data/rules/ca_fy2027.json"))
    with pytest.raises(NotImplementedError):
        rules.valid_on(TODAY)
    for name in ("gatorplate.extract", "gatorplate.dialogue", "gatorplate.store", "gatorplate.api.app",
                 "gatorplate.card", "gatorplate.wiring"):
        importlib.import_module(name)
    from gatorplate.api.app import create_app
    from gatorplate.wiring import build_deps

    assert list(inspect.signature(create_app).parameters) == ["deps"]
    assert list(inspect.signature(build_deps).parameters) == ["settings"]


def test_main_import_has_no_side_effects() -> None:
    main = importlib.import_module("gatorplate.main")
    assert "app" not in vars(main)


def test_deps_fields() -> None:
    from dataclasses import fields

    from gatorplate.deps import Deps

    assert [f.name for f in fields(Deps)] == ["settings", "clock", "ids", "rules", "understanding", "brain", "cases",
                                               "sessions", "live", "events", "cards", "programs"]


def test_event_bus_publish_has_changed_programs() -> None:
    from gatorplate.contracts.ports import EventBusPort

    params = inspect.signature(EventBusPort.publish).parameters
    assert params["changed_programs"].default is False
