"""Redaction runs before anything else sees the utterance (docs/SPEC.md §8.7): written runs of 9+ digits, spoken
runs of 7+ digits (English and Spanish), card-like runs of 13-19 digits, and the gateway's masked '#' runs."""

from __future__ import annotations

import json
import re

import pytest

from gatorplate.extract.redact import Redactor
from gatorplate.extract.text import normalize
from tests.extract.support import CARD, DATA, NINE_DIGITS, ROOT, SSN_DASHED, SSN_SPACED

GUARDS = json.loads((DATA / "content" / "guards.json").read_text(encoding="utf-8"))
DIGIT_RUN = re.compile(r"(?:\d[ .-]?){7,}")


@pytest.mark.parametrize("case", GUARDS["tests"]["redact"], ids=lambda c: c["text"][:40])
def test_guard_vectors(redactor: Redactor, case: dict) -> None:
    got = redactor.redact(normalize(case["text"]), masked=case.get("masked", False))
    assert (got.kinds[0] if got.kinds else None) == case["expect"]
    if case["expect"] is not None:
        assert GUARDS["input"]["redact"]["replacement"] in got.text


@pytest.mark.parametrize("text,masked,kind", [
    (f"My card is {CARD}.", False, "card_number"),  # 16 written digits
    ("four one one one, one one one one, one one one one, one one one one", False, "card_number"),  # 16 spoken
    ("cuatro uno uno uno uno uno uno uno uno uno uno uno uno uno uno uno", False, "card_number"),  # 16 spoken es
    (f"It's {NINE_DIGITS}.", False, "ssn"),  # 9 written digits
    ("it's one two three four five six seven", False, "ssn"),  # 7 spoken digits
    ("mi número es nueve ocho siete seis cinco cuatro tres", False, "ssn"),
    ("My debit card is ################.", True, "card_number"),  # masked, names a card
    ("Mi cuenta del banco es #########.", True, "card_number"),
    ("Here you go: #########.", True, "ssn"),  # masked, no card word: the count of '#' means nothing
    ("Here you go: ################.", True, "ssn"),
])
def test_kinds(redactor: Redactor, text: str, masked: bool, kind: str) -> None:
    got = redactor.redact(normalize(text), masked=masked)
    assert got.kinds == [kind]
    assert not DIGIT_RUN.search(got.text)
    assert "#" not in got.text


@pytest.mark.parametrize("text", [
    "I make 900 a month and pay $1,100 in rent", "I'm 20 and I take 12 units", "my zip code is 94132",
    "I get $1,227.50 every two weeks.", "I applied on 10/02/2026", "Like 12 to 15 hours a week at 18 an hour.",
    "I have two jobs, one at the library and one at the gym.", "gano unos novecientos al mes y pago mil cien de renta",
])
def test_no_false_redaction(redactor: Redactor, text: str) -> None:
    got = redactor.redact(normalize(text))
    assert got.kinds == [] and got.text == normalize(text)


def test_both_kinds_card_first(redactor: Redactor) -> None:
    got = redactor.redact(f"my social is {SSN_DASHED} and my card {CARD}")
    assert got.kinds == ["card_number", "ssn"]
    assert not re.search(r"\d", got.text)


def test_utterance_file_redactions(redactor: Redactor, utterances: list[dict]) -> None:
    for row in utterances:
        got = redactor.redact(normalize(row["utterance"]), masked=bool(row.get("masked")))
        assert got.kinds == row["expect"]["redactions"], row["id"]
        if got.kinds:
            assert not DIGIT_RUN.search(got.text), row["id"]


def test_web_typed_example(redactor: Redactor) -> None:
    """The web path's only protection: the typed spoken-digit SSN of contracts/examples/edge_cases.json."""
    examples = json.loads((ROOT / "contracts" / "examples" / "edge_cases.json").read_text(encoding="utf-8"))
    scenario = next(s for s in examples["scenarios"] if s["id"] == "web_typed_digits_redacted")
    body = next(ex["request"]["body"] for ex in scenario["exchanges"] if ex["step"] == "turn")
    assert body["typed"] is True
    got = redactor.redact(normalize(body["text"]), masked=body["masked"])
    assert got.kinds == ["ssn"]
    assert "one two three" not in got.text


async def test_digits_never_reach_the_model(settings_test) -> None:
    """The model's input holds only redacted text (the current utterance and the short-term memory)."""
    from gatorplate.contracts.common import Lang
    from gatorplate.contracts.extraction import ExtractOutcome, PendingQuestion
    from gatorplate.extract import Understander

    seen: list[str] = []

    class Recorder:
        provider, model = "fake", "recorder"

        async def complete(self, system: str, user_json: str, schema: dict, timeout_s: float) -> ExtractOutcome:
            seen.append(user_json)
            return ExtractOutcome(status="error")

    u = Understander(settings=settings_test, llm=Recorder())  # type: ignore[arg-type]
    result = await u.understand(
        text=f"My SSN is {SSN_SPACED} and my rent is 1100.", masked=False, confidence=0.9, dtmf=None,
        pending=PendingQuestion(key="ask.rent", slots=["rent_share"], kind="number"), known={},
        recent=[f"my card is {CARD}", "uno dos tres cuatro cinco seis siete"], last_prompt=None,
        lang=Lang.en, deadline=u.clock.monotonic() + 2.6, closed_mode=False)
    assert result.redactions == ["ssn"]
    assert seen and "987" not in seen[0] and "4111" not in seen[0] and "cinco seis" not in seen[0]
    assert "[REDACTED]" in seen[0] and "1100" in seen[0]
    assert "987" not in result.redacted_text
