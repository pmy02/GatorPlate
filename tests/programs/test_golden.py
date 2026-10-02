"""The 14 hand-computed programs cases (data/golden/programs_golden.json) on every key of `expected`, and Maria's
demo sequence (docs/SPEC.md §5.10 "Golden cases" and "Card questions")."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from gatorplate.programs.plan import KEY_LINE

GOLDEN = json.loads((Path(__file__).resolve().parent.parent.parent / "data" / "golden" / "programs_golden.json")
                    .read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in GOLDEN["cases"]}
LINE_KEYS = ("status", "value_yearly", "display_yearly", "counted", "stage", "note_keys", "applied")
TOP_KEYS = ("mode", "calfresh_yearly", "found_yearly", "found_display", "share_display", "claimed_display",
            "open_questions", "question_spreads", "next_question", "console_notes")


def test_the_file_has_14_cases() -> None:
    assert GOLDEN["count"] == len(GOLDEN["cases"]) == 14
    assert list(CASES) == ["PG1", "PG1-b", *(f"PG{i}" for i in range(2, 14))]


@pytest.mark.parametrize("case_id", list(CASES))
def test_golden_case(case_id: str, run_golden) -> None:
    case = CASES[case_id]
    expected = case["expected"]
    computed = run_golden(case)
    if "result" in expected:
        assert expected["result"] is None
        assert computed is None, f"{case_id}: no programs result expected"
        return
    assert computed is not None, case_id
    result = computed.result
    for key in TOP_KEYS:
        if key in expected:
            assert getattr(result, key) == expected[key], f"{case_id} {key}"
    lines = {line.id: line for line in result.lines}
    assert set(lines) == set(expected["lines"]), f"{case_id}: shown lines"
    for hidden in expected["hidden"]:
        assert hidden not in lines, f"{case_id}: {hidden} must be hidden"
    for line_id, want in expected["lines"].items():
        line = lines[line_id]
        for key in LINE_KEYS:
            assert getattr(line, key) == want[key], f"{case_id} {line_id}.{key}"
        want_by = date.fromisoformat(want["apply_by"]) if want["apply_by"] else None
        assert line.apply_by == want_by, f"{case_id} {line_id}.apply_by"
        assert line.range_lo == want.get("range_lo"), f"{case_id} {line_id}.range_lo"
        assert line.range_hi == want.get("range_hi"), f"{case_id} {line_id}.range_hi"
        assert (line.display_yearly is None) == (line.value_yearly is None)
    plan = {stage: [ln.id for ln in result.lines if ln.stage == stage and ln.status in
                    ("likely", "maybe", "check", "coverage")] for stage in ("today", "after_approval", "tax_time")}
    assert plan == expected["plan"], f"{case_id} plan"
    assert [ln.order for ln in result.lines] == list(range(1, len(result.lines) + 1))
    if result.mode == "full":
        assert result.lines[0].id == KEY_LINE
        assert result.found_display == sum(ln.display_yearly or 0 for ln in result.lines if ln.counted)
        assert result.found_yearly == sum(ln.value_yearly or 0 for ln in result.lines if ln.counted)


def test_demo_sequence(run_golden) -> None:
    seq = GOLDEN["demo_sequence"]
    base = CASES["PG2"]
    answers: dict[str, str] = {}
    computed = run_golden(base, answers=answers)
    assert computed is not None
    r = computed.result
    assert (r.found_yearly, r.found_display, r.next_question) == (seq["start"]["found_yearly"],
                                                                   seq["start"]["found_display"],
                                                                   seq["start"]["next_question"])
    shown = [r.found_display]
    for step in seq["steps"]:
        (qid, choice), = step["answer"].items()
        assert r.next_question == qid  # the judge always answers the question on screen
        answers[qid] = choice
        computed = run_golden(base, answers=dict(answers))
        assert computed is not None
        r = computed.result
        assert r.found_yearly == step["found_yearly"]
        assert r.found_display == step["found_display"]
        assert r.next_question == step["next_question"]
        assert r.question_spreads == step["question_spreads"]
        shown.append(r.found_display)
    assert shown == [3670, 3830, 4050, 4220]


def test_maria_question_order_and_spreads(run_golden) -> None:
    r = run_golden(CASES["PG2"]).result
    assert r.open_questions == ["break_transit", "tax_dependent", "pge_bill"]
    assert r.question_spreads == {"break_transit": 440, "tax_dependent": 228, "pge_bill": 170}


def test_the_card_threshold_is_yearly_and_strict(engine, run_golden) -> None:
    rule = engine.table.ask_rule
    assert rule.threshold_usd == 50 and rule.strictly_greater is True and rule.max_questions == 3
    # A spread of exactly the threshold is not asked (strictly greater).
    from gatorplate.programs.ask import plan_questions

    q = engine.table.questions
    asked = plan_questions(q, rule, {}, askable=lambda _q: True,
                           found_yearly=lambda a: 50 if a.get("pge_bill") == "own_roommate" else 0)
    assert "pge_bill" in asked.spreads and asked.spreads["pge_bill"] == 50
    assert "pge_bill" not in asked.open


def test_at_most_max_questions(engine) -> None:
    from gatorplate.programs.ask import plan_questions

    rule = engine.table.ask_rule
    answered = {"break_transit": "none", "tax_dependent": "no", "pge_bill": "in_rent"}
    asked = plan_questions(engine.table.questions, rule, answered, askable=lambda _q: True,
                           found_yearly=lambda a: 0)
    assert asked.open == [] and asked.next is None


def test_expired_rows_on_their_boundaries(run_golden) -> None:
    pg1 = CASES["PG1"]
    last_day = run_golden(pg1, today=date(2026, 12, 31)).result
    first_after = run_golden(pg1, today=date(2027, 1, 1)).result
    by = {ln.id: ln for ln in last_day.lines}
    after = {ln.id: ln for ln in first_after.lines}
    assert by["lifeline"].status == "likely" and by["lifeline"].value_yearly == 228
    assert after["lifeline"].status == "check" and after["lifeline"].value_yearly is None
    assert after["lifeline"].note_keys == []  # the status rule's notes go with the dollars
    assert by["medi_cal"].status == "coverage" and after["medi_cal"].status == "check"
    assert after["medi_cal"].value_yearly is None


def test_apply_by_moves_to_the_next_break(run_golden) -> None:
    pg1 = CASES["PG1"]
    on_day = {ln.id: ln for ln in run_golden(pg1, today=date(2026, 11, 19)).result.lines}
    next_day = {ln.id: ln for ln in run_golden(pg1, today=date(2026, 11, 20)).result.lines}
    assert on_day["clipper_start"].apply_by == date(2026, 11, 19)
    assert next_day["clipper_start"].apply_by == date(2027, 4, 22)


def test_outside_the_table_dates_there_is_no_result(run_golden) -> None:
    pg1 = CASES["PG1"]
    assert run_golden(pg1, today=date(2026, 9, 30)) is None
    assert run_golden(pg1, today=date(2027, 10, 1)) is None
    assert run_golden(pg1, today=date(2027, 9, 30)) is not None
