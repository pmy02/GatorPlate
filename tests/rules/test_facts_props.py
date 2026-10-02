"""facts_from_case, the work-rule inputs, roommates_count, property tests, reachability and the literal check."""

from __future__ import annotations

import ast
import re
from decimal import Decimal
from pathlib import Path

import pytest

from gatorplate.contracts.common import Phase, SlotState
from gatorplate.contracts.rules_io import REASON_CODES, Facts, IncomeItem
from gatorplate.contracts.slots import MoneyBasis, Slot, SlotName
from gatorplate.rules import Rules

from .conftest import MARIA, NOW, ROOT, TODAY, demo_case, make_case

N = SlotName
RULES_DIR = ROOT / "gatorplate" / "rules"


# ---------------------------------------------------------------------------------------------- facts


def test_maria_facts(rules: Rules) -> None:
    facts = rules.facts_from_case(demo_case("maria_g1"), today=TODAY)
    assert (facts.age, facts.level, facts.half_time, facts.units, facts.household_size) == (20, "undergrad", True,
                                                                                           12, 1)
    assert facts.household_food == "separate" and not facts.under22_with_parent
    assert [(i.amount, i.kind) for i in facts.incomes] == [(Decimal("900.00"), "earned")]
    assert (facts.rent_share, facts.rent_paid_by_others_to_landlord, facts.utility) == (Decimal("1100.00"),
                                                                                      Decimal("0.00"), "none")
    assert facts.cash_on_hand == Decimal("1000.00") and facts.apply_date is None


def test_jamal_and_sofia_facts(rules: Rules) -> None:
    jamal = rules.facts_from_case(demo_case("jamal_g4"), today=TODAY)
    assert jamal.homeless and jamal.homeless_shelter_cost == 0 and jamal.incomes == []
    assert jamal.cash_on_hand == Decimal("40.00")
    sofia = rules.facts_from_case(demo_case("sofia_g3"), today=TODAY)
    assert sofia.under22_with_parent and sofia.age == 19


def test_roommates_count_changes_nothing(rules: Rules) -> None:
    """The CalFresh rules never read roommates_count: a case with it evaluates exactly like one without it."""
    with_count = demo_case("maria_g1")
    without = with_count.model_copy(deep=True)
    del without.slots[N.roommates_count]
    assert rules.facts_from_case(with_count, today=TODAY) == rules.facts_from_case(without, today=TODAY)
    a, b = rules.apply(with_count, now=NOW), rules.apply(without, now=NOW)
    for field in ("tier", "reason_code", "estimate_monthly", "estimate_range", "expedited_possible", "first_month",
                  "skipped", "yellow_lines", "rule_trace"):
        assert getattr(a, field) == getattr(b, field), field
    four = with_count.model_copy(deep=True)
    four.slots[N.roommates_count] = Slot(value="4", state=SlotState.clear)
    assert rules.apply(four, now=NOW).estimate_monthly == 306
    assert "roommates_count" not in Facts.model_fields


def test_works_80h_from_twenty_hours_a_week(rules: Rules) -> None:
    case = make_case({**MARIA, "units": "4"})
    case.slots[N.earned_monthly] = Slot(value="1732.00", state=SlotState.clear,
                                        basis=MoneyBasis(amount=Decimal("20"), period="hour",
                                                         hours_per_week=Decimal("20")))
    assert rules.facts_from_case(case, today=TODAY).works_80h_month  # 20 × 4.33 = 86.6 ≥ 80
    few = case.model_copy(deep=True)
    few.slots[N.earned_monthly].basis = MoneyBasis(amount=Decimal("20"), period="hour", hours_per_week=Decimal("18"))
    assert not rules.facts_from_case(few, today=TODAY).works_80h_month  # 18 × 4.33 = 77.94
    assert not rules.facts_from_case(make_case(MARIA), today=TODAY).works_80h_month


def test_receives_unemployment_from_the_students_words(rules: Rules) -> None:
    case = make_case({**MARIA, "unearned_monthly": "400.00"})
    assert not rules.facts_from_case(case, today=TODAY).receives_unemployment
    case.slots[N.unearned_monthly].heard = "I get about 400 in unemployment"
    assert rules.facts_from_case(case, today=TODAY).receives_unemployment
    es = make_case({**MARIA, "unearned_monthly": "400.00"}, lang="es")
    es.slots[N.unearned_monthly].heard = "Recibo 400 de desempleo"
    assert rules.facts_from_case(es, today=TODAY).receives_unemployment


def test_g11_work_rule_exemptions(rules: Rules, golden: dict) -> None:
    facts = Facts.model_validate(golden["G11"]["facts"])
    assert rules.evaluate(facts, today=TODAY).policy_flags == ["abawd_possible"]
    worked = facts.model_copy(update={"works_80h_month": True})
    assert rules.evaluate(worked, today=TODAY).policy_flags == []
    unemployed = facts.model_copy(update={"receives_unemployment": True})
    assert rules.evaluate(unemployed, today=TODAY).policy_flags == []
    child = facts.model_copy(update={"child_under14_in_hh": True})
    assert rules.evaluate(child, today=TODAY).policy_flags == []
    older = facts.model_copy(update={"age": 65})
    assert "abawd_possible" not in rules.evaluate(older, today=TODAY).policy_flags
    earning = facts.model_copy(update={"incomes": [IncomeItem(amount=Decimal("941.78"), freq="monthly",
                                                              kind="earned")]})
    assert rules.evaluate(earning, today=TODAY).policy_flags == []


def test_half_time_from_units(rules: Rules) -> None:
    for units, half in (("7", False), ("8", True), ("12", True)):
        assert rules.facts_from_case(make_case({**MARIA, "units": units}), today=TODAY).half_time is half
    no_units = {k: v for k, v in MARIA.items() if k != "units"}
    assert rules.facts_from_case(make_case(no_units), today=TODAY).half_time
    stated = make_case({**no_units, "half_time": "false"})
    assert not rules.facts_from_case(stated, today=TODAY).half_time
    grad = make_case({**no_units, "level": "grad", "grad_exemption": "under_half_time"})
    assert not rules.facts_from_case(grad, today=TODAY).half_time


def test_missing_facts_never_route(rules: Rules) -> None:
    """Before the student answers, nothing routes and there is no result."""
    for slots in ({"consent": "true"}, {"consent": "true", "lives_with_parent": "true"},
                  {"consent": "true", "level": "undergrad", "units": "12"}):
        done = rules.apply(make_case(slots, phase=Phase.student), now=NOW)
        assert done.tier is None and done.reason_code is None and done.yellow_lines == []


def test_n27_with_a_parent_routes_by_household(rules: Rules) -> None:
    seventeen = {"consent": "true", "level": "undergrad", "units": "12", "age": "17", "lives_with_parent": "true"}
    assert rules.apply(make_case(seventeen), now=NOW).reason_code == "coordinator.parent_household"
    alone = {**seventeen, "lives_with_parent": "false"}
    assert rules.apply(make_case(alone), now=NOW).reason_code == "coordinator.age_outside_student_rule"


# ---------------------------------------------------------------------------------------------- properties


def _facts(golden: dict, earned: Decimal, size: int = 1, rent: str = "1100", utility: str = "none") -> Facts:
    base = Facts.model_validate(golden["G1"]["facts"])
    return base.model_copy(update={
        "incomes": [IncomeItem(amount=earned, freq="monthly", kind="earned")], "household_size": size,
        "rent_share": Decimal(rent), "utility": utility, "cash_on_hand": None, "apply_date": None})


@pytest.mark.parametrize("size", [1, 2, 3, 5, 9])
@pytest.mark.parametrize("rent,utility", [("0", "none"), ("700", "phone_only"), ("1100", "two_other"),
                                          ("1500", "heat_cool")])
def test_benefit_never_increases_with_income(rules: Rules, golden: dict, size: int, rent: str, utility: str) -> None:
    last = None
    for step in range(0, 260):
        earned = Decimal(step * 25) + Decimal("0.37")
        ev = rules.evaluate(_facts(golden, earned, size, rent, utility), today=TODAY)
        if ev.reason_code != "likely":
            continue
        assert ev.monthly >= 0
        if ev.min_benefit_applied:
            assert size <= 2 and ev.monthly == rules.table.min_benefit_1_2_persons
        if last is not None:
            assert ev.monthly <= last
        last = ev.monthly


def test_minimum_only_for_one_or_two(rules: Rules, golden: dict) -> None:
    assert rules.evaluate(_facts(golden, Decimal("2600"), 1), today=TODAY).min_benefit_applied
    assert rules.evaluate(_facts(golden, Decimal("3500"), 2, rent="800"), today=TODAY).min_benefit_applied
    three = rules.evaluate(_facts(golden, Decimal("4500"), 3, rent="1000"), today=TODAY)
    assert three.reason_code == "other_help.zero_benefit" and not three.min_benefit_applied


def test_benefit_reduction_reference_formula(rules: Rules, golden: dict) -> None:
    """The engine's Decimal ceiling equals the table's integer reference (3 × net + 9) // 10 over a grid of nets."""
    from gatorplate.rules.money import dollar_ceil

    rate = rules.table.rates.benefit_reduction
    for net in range(0, 3000):
        assert dollar_ceil(rate * net) == (3 * net + 9) // 10


@pytest.mark.parametrize("lang", ["en", "es"])
def test_every_reason_code_has_a_result_sentence(lang: str) -> None:
    """docs/SPEC.md §5.9: every reason code has a sentence in both languages (the bank is read, never changed)."""
    import json

    messages = json.loads((ROOT / "data" / "content" / f"sentences.{lang}.json").read_text(encoding="utf-8"))
    keys = set(messages["messages"])
    missing = [code for code in REASON_CODES if f"result.{code}" not in keys]
    assert missing == []


def test_every_engine_reason_code_is_reachable(rules: Rules, golden: dict) -> None:
    reached = {c["expected"]["reason_code"] for c in golden.values()}
    engine_codes = {c for c in REASON_CODES if not c.startswith("info.")}
    assert engine_codes <= reached
    for slot, code in (("already_receiving", "info.already_receiving"),
                       ("applied_waiting_interview", "info.interview_waiting")):
        assert rules.apply(make_case({"consent": "true", slot: "true"}), now=NOW).reason_code == code


# ---------------------------------------------------------------------------------------------- literals

NUMERIC = re.compile(r"^\s*[+-]?(\d[\d_]*)?(\.\d+)?([eE][+-]?\d+)?\s*$")


def _numeric_literals(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool) or v is None or v is Ellipsis:
                continue
            if isinstance(v, int | float | complex) and v not in (0, 1):
                found.append(f"{path.name}:{node.lineno}: {v!r}")
            if isinstance(v, str) and any(ch.isdigit() for ch in v) and NUMERIC.match(v) and v.strip() not in ("0",
                                                                                                                 "1"):
                found.append(f"{path.name}:{node.lineno}: {v!r}")
    return found


def test_no_numeric_literal_except_0_and_1() -> None:
    files = sorted(RULES_DIR.glob("*.py"))
    assert files
    problems = [p for f in files for p in _numeric_literals(f)]
    assert problems == [], "\n".join(problems)


def test_the_literal_check_catches_literals(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text('A = 2\nB = "0.30"\nC = 1\nD = "x2"\nE = 0.5\nF = "1_000"\n', encoding="utf-8")
    assert [p.split(": ")[1] for p in _numeric_literals(sample)] == ["2", "'0.30'", "0.5", "'1_000'"]


def test_no_float_or_round_in_the_rules_code() -> None:
    for path in sorted(RULES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("round", "float"), f"{path.name}:{node.lineno}"
