"""The rules table: loading, checks, household-size rows, dated sources and the wording rulings it carries."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from gatorplate.contracts import console_text
from gatorplate.contracts.rules_io import RulesTable
from gatorplate.rules import Rules
from gatorplate.rules.table import (
    RulesTableError,
    by_size,
    check_table,
    load_table,
    min_benefit_max_size,
    zero_benefit_min_size,
)

from .conftest import TABLE


def test_loads_and_meta(rules: Rules) -> None:
    meta = rules.meta()
    assert meta.table_id == "CA-CalFresh-FFY2027"
    assert (meta.effective_from, meta.effective_to) == (date(2026, 10, 1), date(2027, 9, 30))
    assert check_table(rules.table) == []


@pytest.mark.parametrize("day,valid", [(date(2026, 9, 30), False), (date(2026, 10, 1), True),
                                       (date(2027, 9, 30), True), (date(2027, 10, 1), False)])
def test_valid_on(rules: Rules, day: date, valid: bool) -> None:
    assert rules.valid_on(day) is valid


def test_rows_one_to_eight_are_stored(rules: Rules) -> None:
    t = rules.table
    assert [by_size(t.max_allotment, n) for n in range(1, 9)] == [306, 562, 808, 1023, 1217, 1463, 1616, 1841]
    assert [by_size(t.gross_limit_200, n) for n in range(1, 9)] == [2660, 3608, 4554, 5500, 6448, 7394, 8340, 9288]
    assert [by_size(t.irt_130, n) for n in range(1, 9)] == [1729, 2345, 2960, 3575, 4191, 4806, 5421, 6037]
    assert [by_size(t.standard_deduction, n) for n in range(1, 8)] == [217, 217, 217, 229, 268, 308, 308]


def test_increments_apply_per_member_over_eight(rules: Rules) -> None:
    t = rules.table
    assert by_size(t.max_allotment, 9) == 1841 + 225
    assert by_size(t.max_allotment, 10) == 1841 + 2 * 225
    assert by_size(t.gross_limit_200, 9) == 9288 + 948
    assert by_size(t.irt_130, 11) == 6037 + 3 * 616
    assert by_size(t.max_allotment, 18) == 3887 and by_size(t.irt_130, 20) == 12197
    assert by_size(t.max_allotment, 17) == 1841 + 9 * 225
    with pytest.raises(ValueError):
        by_size(t.max_allotment, 0)


def test_household_sizes_from_key_names() -> None:
    assert min_benefit_max_size() == 2 and zero_benefit_min_size() == 3


def test_acl_15_42_date(rules: Rules) -> None:
    acl = next(s for s in rules.table.sources if s.id == "ACL-15-42")
    assert acl.date == "2015-04-15"


def test_lua_wording(rules: Rules) -> None:
    """At least two separate utility bills other than heating or cooling; electricity counts; not a closed list."""
    text = rules.table.utility_rules.lua_utilities
    assert text.startswith("At least two separate utility bills other than heating or cooling (for example "
                           "electricity, water, sewer, garbage or phone); not a closed list")
    assert "Electricity counts." in text and "internet doesn't count" in text


def test_sar7_days_are_approximate(rules: Rules) -> None:
    t = rules.table
    assert t.value_sources["deadlines.sar7_due_day"] == "UNVERIFIED"
    assert t.value_sources["deadlines.sar7_late_day"] == "UNVERIFIED"
    assert "approximate" in t.deadlines.note
    unverified = next(s for s in t.sources if s.id == "UNVERIFIED")
    assert unverified.grade == "unverified" and "approximate" in unverified.title


def test_parent_household_text_is_fixed(rules: Rules) -> None:
    assert rules.table.parent_household_console_text == console_text.PARENT_HOUSEHOLD_TEXT
    assert rules.table.voi.flip_reason_text == console_text.FLIP_REASON_TEMPLATE
    not_asked = rules.table.voi.not_asked.left_by_cap_spread_over_threshold
    assert not_asked.yellow_text == console_text.ASSUMED_UP_TO_TEMPLATE
    assert not_asked.yellow_text_when_default_is_highest == console_text.ASSUMED_AS_LOW_AS_TEMPLATE


def test_constants_match_the_decisions(rules: Rules) -> None:
    t = rules.table
    assert str(t.homeless_shelter_deduction) == "205.66"
    assert t.utility_allowance.model_dump() == {"heat_cool": 686, "two_other": 176, "phone_only": 21, "none": 0}
    assert t.excess_shelter_cap_non_elderly_disabled == 769 and t.min_benefit_1_2_persons == 25
    assert t.half_time.undergrad_units_at_least == t.sfsu_half_time_units_undergrad == 8
    assert str(t.abawd.earnings_exempt_monthly) == "941.78" and t.abawd.work_requirement_hours_month == 80
    assert (t.expedited.income_lt, t.expedited.liquid_le) == (150, 100)
    assert (t.voi.flip_threshold_usd, t.voi.max_questions) == (50, 2)
    assert t.parent_household_age_under == 22 and t.parent_household_exceptions == []
    assert t.homeless_deduction_mode == "direct_if_cost"
    assert t.rounding.float_allowed is False and t.rounding.builtin_round_allowed is False


def test_every_source_has_a_date(rules: Rules) -> None:
    ids = {s.id for s in rules.table.sources}
    assert all(s.date for s in rules.table.sources)
    assert set(rules.table.value_sources.values()) <= ids


def _write(tmp_path: Path, raw: dict) -> Path:
    path = tmp_path / "table.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_a_float_is_refused(tmp_path: Path) -> None:
    text = TABLE.read_text(encoding="utf-8").replace('"homeless_shelter_deduction": "205.66"',
                                                     '"homeless_shelter_deduction": 205.66')
    path = tmp_path / "table.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RulesTableError):
        load_table(path)


@pytest.mark.parametrize("change", [
    lambda raw: raw["routes"].__setitem__("boarder", "coordinator.renter"),
    lambda raw: raw["value_sources"].__setitem__("rates.benefit_reduction", "NO-SUCH-SOURCE"),
    lambda raw: raw["decision_order"].reverse(),
    lambda raw: raw["voi"]["priority"].append("cash_on_hand"),
    lambda raw: raw.__setitem__("effective", ["2027-09-30", "2026-10-01"]),
    lambda raw: raw["max_allotment"].pop("5"),
])
def test_checks_catch_problems(tmp_path: Path, table_raw: dict, change) -> None:
    raw = json.loads(json.dumps(table_raw))
    change(raw)
    with pytest.raises(RulesTableError):
        load_table(_write(tmp_path, raw))


def test_unknown_key_is_refused(tmp_path: Path, table_raw: dict) -> None:
    raw = json.loads(json.dumps(table_raw))
    raw["surprise"] = 1
    with pytest.raises(ValueError):
        load_table(_write(tmp_path, raw))
    assert RulesTable.model_validate(table_raw)
