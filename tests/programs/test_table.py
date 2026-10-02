"""The programs table loads strictly: rates are decimal strings, whole dollars ints, no float anywhere, every value
row has `valid` and dated sources, every condition names known facts, questions and rows (docs/SPEC.md §5.10)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from gatorplate.programs.facts import FACT_NAMES
from gatorplate.programs.table import (
    BreaksRow,
    CalEitcRow,
    CareRow,
    Cond,
    FaresRow,
    FederalEitcRow,
    FlatRow,
    LimitRow,
    TableError,
    YctcRow,
    load_table,
    valid_on,
)

TABLE = Path(__file__).resolve().parent.parent.parent / "data" / "rules" / "programs_2026.json"


@pytest.fixture
def raw() -> dict:
    return json.loads(TABLE.read_text(encoding="utf-8"))


def write(tmp_path: Path, doc: dict | str) -> Path:
    path = tmp_path / "programs.json"
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return path


def test_the_table_loads(engine) -> None:
    t = engine.table
    assert t.id == "GP-Programs-2026"
    assert t.checked == date(2026, 10, 1)
    assert t.effective == (date(2026, 10, 1), date(2027, 9, 30))
    assert [p.id for p in t.programs] == ["medi_cal", "clipper_start", "lifeline", "care", "tax_credits"]
    assert list(t.questions) == ["break_transit", "tax_dependent", "pge_bill"]
    assert t.facts_defaults.roommates_count_when_unsaid == 2


def test_rows_have_their_types_and_exact_rates(engine) -> None:
    rows = engine.table.rows
    kinds = {"medi_cal.limit_138": LimitRow, "medi_cal.limit_266_child": LimitRow, "clipper.fares": FaresRow,
             "clipper.breaks": BreaksRow, "care.rates": CareRow, "lifeline.state": FlatRow,
             "lifeline.federal": FlatRow, "tax.caleitc_no_child_2025": CalEitcRow,
             "tax.federal_eitc_2026": FederalEitcRow, "tax.yctc_2025": YctcRow}
    assert {k: type(v) for k, v in rows.items()} == kinds
    fares = rows["clipper.fares"]
    assert isinstance(fares, FaresRow)
    assert fares.muni_adult == Decimal("2.85") and isinstance(fares.muni_pass_month, int)
    care = rows["care.rates"]
    assert isinstance(care, CareRow) and care.electric_discount == Decimal("0.35")
    life = rows["lifeline.state"]
    assert isinstance(life, FlatRow) and life.monthly == Decimal("19.00") and life.ceiling is True


def test_every_value_row_has_valid_and_dated_sources(engine) -> None:
    sources = {s.id: s for s in engine.table.sources}
    assert all(s.date.strip() for s in sources.values())
    for name, row in engine.table.rows.items():
        assert row.valid[0] is not None, name
        assert row.sources, name
        assert all(sid in sources for sid in row.sources), name
    for p in engine.table.programs:
        assert p.sources and all(sid in sources for sid in p.sources), p.id
    assert engine.table.calfresh_key.source in sources


def test_valid_on_is_inclusive_and_open_ended(engine) -> None:
    rows = engine.table.rows
    life = rows["lifeline.state"]
    assert valid_on(life, date(2025, 1, 1)) and valid_on(life, date(2026, 12, 31))
    assert not valid_on(life, date(2024, 12, 31)) and not valid_on(life, date(2027, 1, 1))
    fares = rows["clipper.fares"]
    assert fares.valid[1] is None and valid_on(fares, date(2099, 1, 1)) and not valid_on(fares, date(2026, 9, 30))
    t = engine.table
    assert t.effective_on(date(2026, 10, 1)) and t.effective_on(date(2027, 9, 30))
    assert not t.effective_on(date(2026, 9, 30)) and not t.effective_on(date(2027, 10, 1))


def test_a_float_is_rejected(tmp_path: Path) -> None:
    text = TABLE.read_text(encoding="utf-8").replace('"muni_adult": "2.85"', '"muni_adult": 2.85')
    assert '"muni_adult": 2.85' in text
    with pytest.raises(TableError, match="float"):
        load_table(write(tmp_path, text), set(FACT_NAMES))


def test_a_rate_must_be_a_string(tmp_path: Path, raw: dict) -> None:
    raw["rows"]["care.rates"]["electric_discount"] = 1
    with pytest.raises(ValidationError):
        load_table(write(tmp_path, raw), set(FACT_NAMES))


def test_unknown_keys_are_rejected(tmp_path: Path, raw: dict) -> None:
    raw["programs"][0]["surprise"] = True
    with pytest.raises(ValidationError):
        load_table(write(tmp_path, raw), set(FACT_NAMES))


def test_a_row_needs_valid(tmp_path: Path, raw: dict) -> None:
    del raw["rows"]["lifeline.state"]["valid"]
    with pytest.raises(ValidationError):
        load_table(write(tmp_path, raw), set(FACT_NAMES))


def test_unknown_source_is_rejected(tmp_path: Path, raw: dict) -> None:
    raw["programs"][1]["sources"].append("NOT-A-SOURCE")
    with pytest.raises(TableError, match="NOT-A-SOURCE"):
        load_table(write(tmp_path, raw), set(FACT_NAMES))


def test_conditions_name_known_facts_questions_and_choices(tmp_path: Path, raw: dict) -> None:
    raw["programs"][0]["status_rules"][0]["when"] = {"fact": "shoe_size", "op": "gte", "value": 65}
    with pytest.raises(TableError, match="shoe_size"):
        load_table(write(tmp_path, raw), set(FACT_NAMES))
    raw = json.loads(TABLE.read_text(encoding="utf-8"))
    raw["programs"][2]["status_rules"][1]["when"] = {"answer": "tax_dependent", "op": "in", "value": ["perhaps"]}
    with pytest.raises(TableError, match="perhaps"):
        load_table(write(tmp_path, raw), set(FACT_NAMES))


def test_the_last_status_rule_is_the_catch_all(tmp_path: Path, raw: dict) -> None:
    raw["programs"][1]["status_rules"].pop()
    with pytest.raises(TableError, match="catch-all"):
        load_table(write(tmp_path, raw), set(FACT_NAMES))


def test_condition_shapes() -> None:
    assert Cond.model_validate({}) == Cond()
    Cond.model_validate({"fact": "age", "op": "between", "value": [19, 64]})
    Cond.model_validate({"fact": "magi_monthly", "op": "lte_row", "row": "medi_cal.limit_138"})
    for bad in ({"fact": "age", "op": "between", "value": [19]},
                {"fact": "age", "op": "lte_row", "value": 3},
                {"fact": "age", "op": "about", "value": 3},
                {"answer": "tax_dependent", "op": "lt", "value": "no"},
                {"fact": "age", "answer": "tax_dependent", "op": "eq", "value": 1},
                {"op": "eq", "value": 1},
                {"fact": "age", "op": "in", "value": 3}):
        with pytest.raises(ValidationError):
            Cond.model_validate(bad)


def test_lte_row_only_in_status_rules(tmp_path: Path, raw: dict) -> None:
    raw["programs"][0]["note_rules"]["medi_cal.child_too"] = {"fact": "magi_monthly", "op": "lte_row",
                                                               "row": "medi_cal.limit_138"}
    with pytest.raises(TableError, match="lte_row"):
        load_table(write(tmp_path, raw), set(FACT_NAMES))
