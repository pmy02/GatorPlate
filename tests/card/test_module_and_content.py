"""Module boundaries of gatorplate/card, the card content files and the condition evaluator."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from gatorplate.card.conditions import CardContext, truthy, when_true, zeroish
from gatorplate.contracts.card_api import BLOCK_ORDER

ROOT = Path(__file__).resolve().parents[2]
CARD_DIR = ROOT / "gatorplate" / "card"


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", sorted(CARD_DIR.glob("*.py")), ids=lambda p: p.name)
def test_card_imports_only_contracts_and_stdlib(path: Path) -> None:
    for name in imports_of(path):
        top = name.split(".")[0]
        if top == "gatorplate":
            assert name.startswith(("gatorplate.contracts", "gatorplate.card")), f"{path.name} imports {name}"
        else:
            assert top in sys.stdlib_module_names or top == "__future__", f"{path.name} imports {name}"


def test_card_never_reads_the_environment_or_floats() -> None:
    for path in CARD_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "os.environ" not in text and "getenv" not in text, path.name
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                assert not isinstance(node.value, float), f"{path.name}: float literal {node.value}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("round", "float"), f"{path.name}: {node.func.id}()"


@pytest.mark.parametrize("lang", ["en", "es"])
def test_content_follows_the_block_table(card_content, lang) -> None:
    content = card_content[lang]
    assert [b["id"] for b in content["blocks"]] == BLOCK_ORDER
    style = {b["id"]: (b["tone"], b["collapsed"]) for b in content["blocks"]}
    assert style == {"today_action": ("accent", False), "expedited": ("accent", False), "why": ("default", False),
                     "answer_sheet": ("default", False), "documents": ("default", True),
                     "interview": ("default", True), "after_approval": ("default", True),
                     "food_today": ("muted", False), "contact": ("default", False)}
    titles = {b["id"]: b["title"] for b in content["blocks"]}
    assert "approv" not in titles["after_approval"].lower().replace("approval", "")
    sources = {s["id"]: s for s in content["sources"]}
    assert sources["ACL-15-42"]["date"] == "2015-04-15"
    assert set(content["ui"]) == set(card_content["en"]["ui"])


def test_rules_label_matches_the_rules_table(card_content) -> None:
    table = json.loads((ROOT / "data" / "rules" / "ca_fy2027.json").read_text(encoding="utf-8"))
    assert card_content["en"]["ui"]["rules_label"] == table["label"]
    assert "2027" in card_content["es"]["ui"]["rules_label"]


def test_conditions() -> None:
    ctx = CardContext(tier="likely", reason="likely", expedited="no",
                      slots={"level": "undergrad", "half_time": "true", "rent_share": "1100.00",
                             "earned_monthly": "0.00", "household_food": "separate"},
                      answered=frozenset({"rent_share"}), flags=frozenset({"abawd_possible"}),
                      facts=frozenset({"case_code"}), irt_applies=True, at_max=True)
    assert when_true({}, ctx)
    assert when_true({"reason": ["likely"], "level": ["undergrad"], "slot": {"half_time": ["true"]}}, ctx)
    assert when_true({"positive": "rent_share", "zero": "earned_monthly", "answered": "rent_share"}, ctx)
    assert not when_true({"zero": "other_cash_monthly"}, ctx)  # missing is neither zero nor positive
    assert when_true({"has": ["case_code", "rent_share"]}, ctx) and not when_true({"has": "first_month"}, ctx)
    assert when_true({"homeless": False, "irt_applies": True, "at_max": True, "flag": ["abawd_possible"]}, ctx)
    assert not when_true({"irt_applies": False}, ctx)
    assert when_true({"not": [{"positive": "earned_monthly"}, {"homeless": True}]}, ctx)
    assert not when_true({"not": [{"positive": "rent_share"}]}, ctx)
    # an OR written with not: not(not A and not B)
    assert when_true({"not": [{"not": [{"expedited": ["yes"]}, {"tier": ["likely"]}]}]}, ctx)
    assert when_true({"lang": "es"}, ctx)
    no_irt = CardContext()
    assert not when_true({"irt_applies": True}, no_irt) and not when_true({"irt_applies": False}, no_irt)
    with pytest.raises(ValueError):
        when_true({"unknown_key": 1}, ctx)


def test_truthy_and_zeroish() -> None:
    assert truthy("900.00") and truthy("true") and truthy("two_plus") and truthy("1")
    assert not truthy("0.00") and not truthy("false") and not truthy("none") and not truthy(None)
    assert zeroish("0.00") and zeroish("false") and zeroish("none") and not zeroish(None) and not zeroish("5")
