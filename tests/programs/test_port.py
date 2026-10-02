"""The ProgramsPort methods on Cases (docs/SPEC.md §5.10 modes, §6.6 endpoints): None where there is no programs part,
answer validation, "I applied" marks, meta, and a case that never changes."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import date
from pathlib import Path

import pytest

from gatorplate.contracts.common import Lang
from gatorplate.contracts.errors import InvalidRequest
from gatorplate.programs import Programs

ROOT = Path(__file__).resolve().parent.parent.parent
TODAY = date(2026, 10, 2)


# ---------------------------------------------------------------------------------------------- no programs part

def test_disabled_answers_none_everywhere(make_case) -> None:
    off = Programs(enabled=False)
    case = make_case("maria_g1")
    assert off.evaluate(case, today=TODAY) is None
    assert off.view(case, lang=Lang.en, today=TODAY) is None
    assert off.meta() is None
    assert off.can_mark(case, "calfresh", today=TODAY) is False
    with pytest.raises(InvalidRequest):
        off.validate_answers(case, {"tax_dependent": "no"}, today=TODAY)


def test_from_settings(settings_test, make_case) -> None:
    on = Programs.from_settings(settings_test)
    assert on.enabled and on.table_path == settings_test.programs_table_path
    view = on.view(make_case("maria_g1", answers={}), lang=Lang.en, today=TODAY)
    assert view is not None and view.share_text is not None
    assert view.share_text.endswith("http://127.0.0.1:8000")
    off = Programs.from_settings(settings_test.model_copy(update={"programs": False}))
    assert off.evaluate(make_case("maria_g1"), today=TODAY) is None and off.meta() is None


@pytest.mark.parametrize("route", ["other_help.status", "other_help.dorm_meal_plan", "other_help.not_sfsu",
                                   "other_help.over_gross_limit", "other_help.zero_benefit", None, "something.else"])
def test_mode_none_routes(engine, make_case, route: str | None) -> None:
    case = make_case("maria_g1", reason_code=route or "", estimate=306)
    if route is None:
        case = case.model_copy(update={"reason_code": None})
    assert engine.evaluate(case, today=TODAY) is None
    assert engine.view(case, lang=Lang.es, today=TODAY) is None
    with pytest.raises(InvalidRequest):
        engine.validate_answers(case, {"tax_dependent": "no"}, today=TODAY)
    assert engine.can_mark(case, "calfresh", today=TODAY) is False


@pytest.mark.parametrize("route", ["coordinator.parent_household", "coordinator.unresolved", "coordinator.gig_income",
                                   "info.already_receiving", "info.interview_waiting"])
def test_list_only_routes(engine, make_case, route: str) -> None:
    case = make_case("maria_g1", reason_code=route, estimate=306)
    result = engine.evaluate(case, today=TODAY)
    assert result is not None and result.mode == "list_only"
    assert result.found_display is None and result.share_display is None and result.claimed_display == 0
    assert result.open_questions == [] and result.next_question is None and result.question_spreads == {}
    assert all(line.status == "check" and line.value_yearly is None and not line.counted for line in result.lines)
    assert all(line.id != "calfresh" for line in result.lines)
    with pytest.raises(InvalidRequest):
        engine.validate_answers(case, {"tax_dependent": "no"}, today=TODAY)
    assert engine.can_mark(case, "medi_cal", today=TODAY) is False


def test_outside_the_table_dates(engine, make_case) -> None:
    case = make_case("maria_g1")
    assert engine.evaluate(case, today=date(2027, 10, 1)) is None
    assert engine.view(case, lang=Lang.en, today=date(2026, 9, 30)) is None


def test_a_likely_case_without_an_estimate_shows_nothing(engine, make_case) -> None:
    case = make_case("maria_g1").model_copy(update={"estimate_monthly": None})
    assert engine.evaluate(case, today=TODAY) is None


# ---------------------------------------------------------------------------------------------- answers

def test_validate_answers(engine, make_case) -> None:
    maria = make_case("maria_g1", answers={})
    assert engine.validate_answers(maria, {"break_transit": "weekdays_muni"}, today=TODAY) == {
        "break_transit": "weekdays_muni"}
    assert engine.validate_answers(maria, {"tax_dependent": "not_sure", "pge_bill": "in_rent"}, today=TODAY) == {
        "tax_dependent": "not_sure", "pge_bill": "in_rent"}
    for bad in ({"shoe_size": "no"}, {"tax_dependent": "maybe"}, {"tax_dependent": "No"}, {}):
        with pytest.raises(InvalidRequest):
            engine.validate_answers(maria, bad, today=TODAY)


def test_a_question_that_is_not_open_is_rejected(engine, make_case) -> None:
    jamal = make_case("jamal_g4")  # homeless: the PG&E bill question never applies
    with pytest.raises(InvalidRequest):
        engine.validate_answers(jamal, {"pge_bill": "own_mine"}, today=TODAY)
    dorm = make_case("maria_g1", answers={}, slots={"age": "18", "lives_with_parent": "false",
                                                    "dorm_on_campus": "true", "earned_monthly": "0.00"})
    with pytest.raises(InvalidRequest):
        engine.validate_answers(dorm, {"break_transit": "none"}, today=TODAY)  # 18: Clipper START starts at 19


def test_a_re_answer_replaces_the_old_one(engine, make_case) -> None:
    jamal = make_case("jamal_g4")  # seeded: tax_dependent no, break_transit two_days; nothing left open
    assert engine.evaluate(jamal, today=TODAY).open_questions == []
    assert engine.validate_answers(jamal, {"break_transit": "weekdays_bart"}, today=TODAY) == {
        "break_transit": "weekdays_bart"}
    replaced = make_case("jamal_g4", answers={"tax_dependent": "no", "break_transit": "weekdays_bart"})
    lines = {ln.id: ln for ln in engine.evaluate(replaced, today=TODAY).lines}
    assert lines["clipper_start"].value_yearly == 440


def test_stored_answers_the_table_does_not_know_read_as_unanswered(engine, make_case) -> None:
    odd = make_case("maria_g1", answers={"break_transit": "by_boat", "favourite_color": "blue"})
    result = engine.evaluate(odd, today=TODAY)
    assert result is not None and result.next_question == "break_transit" and result.found_display == 3670


# ---------------------------------------------------------------------------------------------- marks

def test_can_mark(engine, make_case) -> None:
    maria = make_case("maria_g1", answers={"break_transit": "none", "tax_dependent": "yes", "pge_bill": "in_rent"})
    result = engine.evaluate(maria, today=TODAY)
    statuses = {ln.id: ln.status for ln in result.lines}
    assert statuses["clipper_start"] == "zero" and statuses["lifeline"] == "note" and statuses["care"] == "note"
    assert "tax_credits" not in statuses
    assert engine.can_mark(maria, "calfresh", today=TODAY) is True
    assert engine.can_mark(maria, "medi_cal", today=TODAY) is True  # check: a box on the same application
    for program in ("clipper_start", "lifeline", "care", "tax_credits", "nope"):
        assert engine.can_mark(maria, program, today=TODAY) is False, program


def test_claimed_follows_the_marks(engine, make_case) -> None:
    taps = {"break_transit": "weekdays_muni", "tax_dependent": "no", "pge_bill": "own_roommate"}
    marked = make_case("maria_g1", answers=taps, progress={"calfresh": True, "clipper_start": True, "care": False})
    result = engine.evaluate(marked, today=TODAY)
    assert result.claimed_display == 3830
    view = engine.view(marked, lang=Lang.en, today=TODAY)
    assert view.labels["ui.claimed"] == "You've started $3,830 of $4,220"
    assert [p.applied for p in view.programs][:3] == [True, False, True]


# ---------------------------------------------------------------------------------------------- meta, sources

def test_meta_matches_the_console_fixture(engine) -> None:
    meta = engine.meta()
    fixture = json.loads((ROOT / "web" / "fixtures" / "meta.json").read_text(encoding="utf-8"))["programs"]
    assert meta is not None and meta.model_dump(mode="json") == fixture


def test_every_shown_line_names_dated_sources(engine, make_case) -> None:
    dated = {s.id for s in engine.table.sources if s.date.strip()}
    for name, answers in (("maria_g1", {}), ("jamal_g4", None), ("sofia_g3", None)):
        result = engine.evaluate(make_case(name, answers=answers), today=TODAY)
        for line in result.lines:
            assert line.source_ids and set(line.source_ids) <= dated, (name, line.id)
            assert line.basis, (name, line.id)


# ---------------------------------------------------------------------------------------------- the case never changes

def test_evaluating_and_answering_never_change_the_case(engine, make_case) -> None:
    case = make_case("maria_g1", answers={"break_transit": "two_days"}, progress={"calfresh": True})
    before = case.model_dump()
    engine.evaluate(case, today=TODAY)
    engine.view(case, lang=Lang.es, today=TODAY)
    engine.validate_answers(case, {"tax_dependent": "no"}, today=TODAY)
    engine.can_mark(case, "calfresh", today=TODAY)
    engine.meta()
    assert case.model_dump() == before
    assert case.estimate_monthly == 306 and case.rule_trace == [] and case.slots == make_case("maria_g1").slots


# ---------------------------------------------------------------------------------------------- guard at run time

def test_a_guard_hit_drops_the_part_without_content_in_logs(tmp_path: Path, make_case, caplog) -> None:
    content = tmp_path / "content"
    content.mkdir()
    for name in ("programs.en.json", "programs.es.json", "guards.json"):
        shutil.copy(ROOT / "data" / "content" / name, content / name)
    doc = json.loads((content / "programs.en.json").read_text(encoding="utf-8"))
    doc["strings"]["ui.key_line"] = "CalFresh is the key: free money for everyone."
    (content / "programs.en.json").write_text(json.dumps(doc), encoding="utf-8")
    engine = Programs(content_dir=content, public_base_url="https://gatorplate.fly.dev")
    case = make_case("maria_g1", answers={})
    with caplog.at_level(logging.WARNING, logger="gatorplate.programs"):
        assert engine.view(case, lang=Lang.en, today=TODAY) is None
    assert engine.view(case, lang=Lang.es, today=TODAY) is not None  # the Spanish text is clean
    assert any("guard_hit" in r.getMessage() for r in caplog.records)
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "free money" not in logged and "K7Q-2FM" not in logged
