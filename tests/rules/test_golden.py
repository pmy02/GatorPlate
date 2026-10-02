"""Every CalFresh golden case (data/golden/golden_cases.json) on every key of its `expected` object.

Each case runs on its own `today` when it gives one (N33: 2027-10-01, outside the table's dates) and otherwise on the
test clock's day. Never change an expected value to match the engine.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from gatorplate.contracts.rules_io import REASON_CODES, Facts
from gatorplate.contracts.slots import MoneyBasis
from gatorplate.rules import Rules

from .conftest import ROOT, TODAY

GOLDEN = json.loads((ROOT / "data" / "golden" / "golden_cases.json").read_text(encoding="utf-8"))
CASES = GOLDEN["cases"]
EXPECTED_KEYS = {"tier", "reason_code", "amount", "min_benefit_applied", "gross_monthly", "net_monthly", "expedited",
                 "expedited_screen", "irt_applies", "yellow_count", "yellow_codes", "first_month"}


def _evaluate(rules: Rules, case: dict):
    facts = Facts.model_validate(case["facts"])
    today = date.fromisoformat(case["today"]) if "today" in case else TODAY
    return rules.evaluate(facts, today=today)


def test_count_and_keys() -> None:
    assert GOLDEN["count"] == len(CASES) == 78
    for case in CASES:
        assert set(case["expected"]) <= EXPECTED_KEYS, case["id"]
        assert case["expected"]["reason_code"] in REASON_CODES


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden_case(rules: Rules, case: dict) -> None:
    ev = _evaluate(rules, case)
    got = {
        "tier": ev.tier.value,
        "reason_code": ev.reason_code,
        "amount": ev.monthly,
        "min_benefit_applied": ev.min_benefit_applied,
        "gross_monthly": ev.gross_monthly,
        "net_monthly": ev.net_monthly,
        "expedited": ev.expedited,
        "expedited_screen": ev.expedited_screen,
        "irt_applies": ev.irt_applies,
        "yellow_count": len(ev.policy_flags),
        "yellow_codes": ev.policy_flags,
        "first_month": ev.first_month.amount if ev.first_month else None,
    }
    for key, want in case["expected"].items():
        if key == "gross_monthly":
            assert got[key] == Decimal(want), f"{case['id']} {key}"
            assert str(got[key]) == want, f"{case['id']} {key} keeps cents"
        else:
            assert got[key] == want, f"{case['id']} {key}: expected {want}, got {got[key]}"
    assert ev.table_id == "CA-CalFresh-FFY2027"
    assert ev.trace, "every evaluation has a trace"


NORMALIZE = [(c["id"], n) for c in CASES for n in c.get("normalize", [])]


@pytest.mark.parametrize("cid,check", NORMALIZE, ids=[f"{cid}-{i}" for i, (cid, _) in enumerate(NORMALIZE)])
def test_normalize(rules: Rules, cid: str, check: dict) -> None:
    basis = MoneyBasis.model_validate(check["basis"])
    assert rules.normalize_money(basis) == Decimal(check["monthly"])
    assert str(rules.normalize_money(basis)) == check["monthly"]


def test_normalize_covers_the_named_cases() -> None:
    assert {cid for cid, _ in NORMALIZE} == {"G12", "G13", "N4", "N12", "N17-b", "N17-c", "N17-d", "N26"}


ROUTING = [c for c in CASES if c["source"] == "routing_coverage"]


@pytest.mark.parametrize("case", ROUTING, ids=[c["id"] for c in ROUTING])
def test_routing_case_routes_at_its_step(rules: Rules, case: dict) -> None:
    ev = _evaluate(rules, case)
    assert ev.trace[-1].step == case["route_step"]
    assert ev.monthly is None and ev.hard_stop
    step_names = [s.step for s in rules.table.decision_order]
    assert case["route_step"] in step_names


def test_routing_cases_cover_r18() -> None:
    codes = {c["id"]: c["expected"]["reason_code"] for c in ROUTING}
    assert codes == {
        "N27": "coordinator.parent_household", "N27-b": "coordinator.age_outside_student_rule",
        "N28": "other_help.not_sfsu", "N29": "coordinator.boarder", "N30": "coordinator.spouse_student",
        "N31": "coordinator.elderly_disabled", "N32": "coordinator.gig_income", "N33": "coordinator.unresolved",
    }


def test_n33_inside_the_table_dates_gives_306(rules: Rules) -> None:
    case = next(c for c in CASES if c["id"] == "N33")
    facts = Facts.model_validate(case["facts"])
    ev = rules.evaluate(facts, today=TODAY)
    assert (ev.reason_code, ev.monthly) == ("likely", 306)


@pytest.mark.parametrize("cid", ["N20", "N21", "N26", "G13"])
def test_traps_are_avoided(rules: Rules, cid: str) -> None:
    case = next(c for c in CASES if c["id"] == cid)
    ev = _evaluate(rules, case)
    trap = case["trap"]
    if "wrong_amount" in trap:
        assert ev.monthly != trap["wrong_amount"]
    if "wrong_first_month" in trap:
        assert ev.first_month is not None and ev.first_month.amount != trap["wrong_first_month"]


def test_g1_demo_values(rules: Rules) -> None:
    g1 = next(c for c in CASES if c["id"] == "G1")
    assert g1["facts"]["cash_on_hand"] == "1000" and g1["facts"]["apply_date"] == "2026-10-02"
    ev = _evaluate(rules, g1)
    assert (ev.monthly, ev.expedited, ev.first_month.amount) == (306, False, 296)
    assert ev.first_month.filed_on == date(2026, 10, 2) and ev.first_month.month_label == "October"


def test_g12_and_g13(rules: Rules) -> None:
    by_id = {c["id"]: c for c in CASES}
    assert _evaluate(rules, by_id["G12"]).monthly == 266
    assert _evaluate(rules, by_id["G13"]).monthly == 31


def test_maria_trace_reads_like_the_console_example(rules: Rules) -> None:
    ev = _evaluate(rules, next(c for c in CASES if c["id"] == "G1"))
    text = {s.step: s.result for s in ev.trace}
    assert text["gross_income_test"] == "Gross $900 ≤ $2,660 (gross income limit, 1 person)"
    assert text["adjusted_income"] == "Earned-income deduction 20%: −$180 · standard deduction −$217 → $503"
    assert text["shelter"] == "Shelter: $1,100 − 50% of $503 ($251.50) = $848.50 → capped at $769"
    assert text["net_income"] == "Net income: $503 − $769 → $0"
    assert text["benefit"] == "Estimate: $306 − 30% × $0 ($0) = $306"
    sources = {s.id for s in rules.table.sources}
    assert all(s.source in sources for s in ev.trace)
