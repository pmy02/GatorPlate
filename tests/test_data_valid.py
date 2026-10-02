"""The prepared data files validate against the contracts (tools/validate_data.py, one test per check), plus a few
model-level facts the build relies on."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from gatorplate.contracts.rules_io import Facts, RulesTable
from tools import validate_data as vd

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("label,check", vd.CHECKS, ids=[label for label, _ in vd.CHECKS])
def test_check(label: str, check) -> None:
    problems = check()
    assert problems == [], "\n".join(problems)


def test_rules_table_meta(rules_table: RulesTable) -> None:
    meta = rules_table.meta()
    assert meta.table_id == "CA-CalFresh-FFY2027"
    assert (meta.effective_from, meta.effective_to) == (date(2026, 10, 1), date(2027, 9, 30))
    assert rules_table.parent_household_console_text.startswith("Under 22 and living with a parent")
    assert rules_table.voi.flip_reason_text == "could change the estimate by ${spread}: ${lo} or ${hi}"


def test_golden_counts(golden: dict) -> None:
    assert len(golden) == 78
    g1 = golden["G1"]
    assert g1["facts"]["cash_on_hand"] == "1000" and g1["expected"]["first_month"] == 296
    Facts.model_validate(g1["facts"])


def test_programs_golden_and_table(programs_golden: dict, programs_table: dict) -> None:
    assert len(programs_golden) == 14
    assert programs_table["id"] == "GP-Programs-2026"
    assert programs_table["effective"] == ["2026-10-01", "2027-09-30"]
    assert programs_table["ask_rule"]["threshold_usd"] == 50
    data = json.loads((ROOT / "data" / "golden" / "programs_golden.json").read_text(encoding="utf-8"))
    steps = data["demo_sequence"]["steps"]
    assert [s["found_display"] for s in steps] == [3830, 4050, 4220]


def test_no_float_anywhere_in_programs_files() -> None:
    for rel in ("data/rules/programs_2026.json", "data/golden/programs_golden.json",
                "data/content/programs.en.json", "data/content/programs.es.json"):
        vd.load_json(ROOT / rel, allow_float=False)


def test_float_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text('{"rate": 0.5}', encoding="utf-8")
    with pytest.raises(vd.FloatFound):
        vd.load_json(path, allow_float=False)


def test_jamal_seeded_answers() -> None:
    demo = json.loads((ROOT / "data" / "demo_cases" / "jamal_g4.json").read_text(encoding="utf-8"))
    case = vd.demo_case(demo)
    assert {q: a.value for q, a in case.program_answers.items()} == {"tax_dependent": "no", "break_transit": "two_days"}
    for answer in case.program_answers.values():
        assert answer.source == "seed" and answer.at <= vd.TEST_NOW
    maria = vd.demo_case(json.loads((ROOT / "data" / "demo_cases" / "maria_g1.json").read_text(encoding="utf-8")))
    assert maria.program_answers == {} and maria.slots["roommates_count"].value == "2"


def test_icon_sprite_has_the_key_icon() -> None:
    import xml.etree.ElementTree as ET

    root = ET.parse(ROOT / "web" / "shared" / "icons.svg").getroot()
    ids = {s.get("id"): s for s in root.iter("{http://www.w3.org/2000/svg}symbol")}
    assert "i-key" in ids and ids["i-key"].get("viewBox") == "0 0 24 24"
    assert "gp-logo" in ids
    favicon = (ROOT / "web" / "shared" / "favicon.svg").read_text(encoding="utf-8")
    assert "currentColor" in favicon and "#" not in favicon
