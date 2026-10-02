"""Noise and background speech (extract/noise.py) and the parser's off-script cases: corrections inside one answer
for every slot, and no amount or age taken from background speech (a TV on a speakerphone)."""

from __future__ import annotations

import pytest

from gatorplate.contracts.extraction import PendingQuestion
from gatorplate.contracts.slots import SlotName
from gatorplate.extract.noise import background, kind
from gatorplate.extract.parser import Parser
from gatorplate.extract.prompt import SYSTEM_PROMPT

S = SlotName
INCOME = PendingQuestion(key="ask.income", slots=[S.earned_monthly, S.other_cash_monthly], kind="number")
OTHER = PendingQuestion(key="ask.other_cash", slots=[S.other_cash_monthly], kind="number")
RENT = PendingQuestion(key="ask.rent", slots=[S.rent_share], kind="number")
AGE = PendingQuestion(key="ask.age_parent", slots=[S.age, S.lives_with_parent], kind="open")
LEVEL = PendingQuestion(key="ask.level_units", slots=[S.level, S.units], kind="open")
RBO = PendingQuestion(key="flip.rent_paid_by_others", slots=[S.rent_paid_by_others_to_landlord], kind="yes_no")


def read(parser: Parser, text: str, pending: PendingQuestion, lang: str = "en") -> dict[SlotName, str]:
    return {SlotName(o.slot): o.value for o in parser.parse(text, pending, {}, lang).observations}


# ------------------------------------------------------------------------------------------ classifier

@pytest.mark.parametrize("text", [
    "", "   ", "...", "?", "[inaudible]", "[background noise]", "[music]", "(noise)", "<unk>", "[ruido]", "uh", "Um.",
    "mm", "mmm", "eh", "the", "uh, um", "under-", "el-", "I'm tw-", "oh",
])
def test_content_free_transcripts_are_noise(text: str) -> None:
    assert kind(text) == "noise"


@pytest.mark.parametrize("text", ["hello?", "Hello? Hello?", "hello? can you hear me?", "are you still there",
                                  "¿bueno? ¿me escuchas?", "¿hola?", "I can't hear you"])
def test_line_checks(text: str) -> None:
    assert kind(text) == "check"


@pytest.mark.parametrize("text", ["what?", "sorry what", "Sorry?", "huh?", "say that again?", "come again?",
                                  "sorry can you repeat that", "wait what", "¿qué?", "¿perdón?", "¿cómo?"])
def test_repeat_requests(text: str) -> None:
    assert kind(text) == "repeat"


@pytest.mark.parametrize("text", [
    "yes", "no", "okay", "mhm", "uh-huh", "uh-uh", "Uh huh.", "uh uh", "mm hmm", "Mm-hmm.", "nine", "Um, twelve", "twelve hund-", "I don't know", "hmm, no",
    "Sí", "bueno", "Bueno.", "como", "stop", "wait", "Separately.", "nah", "Grad— no sorry, undergrad", "900",
])
def test_answers_are_never_noise(text: str) -> None:
    assert kind(text) is None


@pytest.mark.parametrize("text", [
    "police say the twenty four year old suspect was arrested near the park",
    "tonight's jackpot is now four hundred million dollars",
    "gas prices jumped to five dollars a gallon this week",
    "and the Giants won it four to two in the ninth",
    "el precio de la gasolina subió a cinco dólares",
    "please hold for the next available operator",
])
def test_background_speech(text: str) -> None:
    assert background(text)


@pytest.mark.parametrize("text", [
    "About 900 a month from work.", "It's about nine hundred a month.", "600 at the library and 300 at the cafe.",
    "Eleven fifty, split three ways, so like three eighty three.", "Twenty, and I live with two roommates",
    "We each buy our own food separately", "No, utilities are included in the rent here", "Tengo diecinueve años",
    "Nobody gives me any money for anything at all", "Yeah the rent is eleven hundred for the room",
    "Quiero hablar con una persona, por favor.", "Espera, no son mil cien, son mil doscientos.",
    "Voy a un colegio comunitario, no a SF State.", "Grad student— no sorry, undergrad. Twelve units.",
    "senior at State, full load, twelve units", "Licenciatura, eh, quince unidades... no, perdón, doce.",
    "Can you connect to a human right now please", "Wait it's not eleven hundred it's twelve hundred",
])
def test_answers_are_not_background(text: str) -> None:
    assert not background(text)


# ------------------------------------------------------------------------------------------ parser

@pytest.mark.parametrize("text,pending", [
    ("police say the twenty four year old suspect was arrested near the park", AGE),
    ("tonight's jackpot is now four hundred million dollars", INCOME),
    ("gas prices jumped to five dollars a gallon this week", OTHER),
    ("and the Giants won it four to two in the ninth", INCOME),
    ("el precio de la gasolina subió a cinco dólares", INCOME),
])
def test_no_value_from_background_speech(parser: Parser, text: str, pending: PendingQuestion) -> None:
    assert read(parser, text, pending) == {}


def test_no_band_from_background_speech_to_a_closed_money_question(parser: Parser) -> None:
    closed_rent = PendingQuestion(key="ask.rent", slots=[S.rent_share], kind="choice", closed=True)
    assert read(parser, "and coming up after the break the Warriors take on the Lakers at seven thirty",
                closed_rent) == {}
    assert read(parser, "Seven thirty.", closed_rent) == {S.rent_share: "730"}


@pytest.mark.parametrize("text,pending,want", [
    ("Grad student— no sorry, undergrad. Twelve units.", LEVEL, {S.level: "undergrad", S.units: "12"}),
    ("undergrad, no, grad student, nine units", LEVEL, {S.level: "grad", S.units: "9"}),
    ("Undergrad, twelve— no, fifteen units", LEVEL, {S.units: "15"}),
    ("Licenciatura, eh, quince unidades… no, doce.", LEVEL, {S.units: "12"}),
    ("I'm 23 — sorry, 24, my birthday was last week", AGE, {S.age: "24"}),
    ("Yes— sorry, no, I pay all of it", RBO, {S.rent_paid_by_others_to_landlord: "0"}),
    ("Twelve hundred— wait, actually eleven hundred", RENT, {S.rent_share: "1100"}),
    ("I make like 900, no wait, 950 a month", INCOME, {S.earned_monthly: "950"}),
    ("Espera, no son mil cien, son mil doscientos.", RENT, {S.rent_share: "1200"}),
])
def test_a_correction_inside_one_answer_keeps_the_last_value(parser: Parser, text: str, pending: PendingQuestion,
                                                             want: dict[SlotName, str]) -> None:
    got = read(parser, text, pending, "es" if ("unidades" in text or "Espera" in text) else "en")
    for slot, value in want.items():
        assert got.get(slot) == value, (slot, got)


@pytest.mark.parametrize("text,pending,want", [
    ("I'm 20, no roommates, I live with my mom", AGE, {S.age: "20", S.lives_with_parent: "true"}),
    ("No, I'm 20 and I live with roommates", AGE, {S.age: "20"}),
    ("About 900 a month from work.", INCOME, {S.earned_monthly: "900"}),
])
def test_a_plain_no_is_no_correction(parser: Parser, text: str, pending: PendingQuestion,
                                     want: dict[SlotName, str]) -> None:
    got = read(parser, text, pending)
    for slot, value in want.items():
        assert got.get(slot) == value, (slot, got)


def test_the_prompt_says_noise_and_background_are_nothing() -> None:
    assert "background speech" in SYSTEM_PROMPT and "never dont_know" in SYSTEM_PROMPT


def test_by_myself_to_together_or_separately_is_separately() -> None:
    from gatorplate.contracts.extraction import ExtractionResult, ExtractOutcome
    from gatorplate.extract.merge import Merger

    pending = PendingQuestion(key="flip.household_food", slots=[S.household_food], kind="choice",
                              choices=["Together", "Separately"])
    text = "I buy and cook my own food, by myself."
    parsed = Parser().parse(text, pending, {}, "en")
    model = ExtractionResult.model_validate({
        "observations": [{"slot": "household_food", "value": "alone", "period": None, "hours_per_week": None,
                          "state": "clear", "quote": "by myself", "quote_en": None}],
        "intents": [], "answered_pending": "yes", "lang": "en", "side_question": None, "requested_language": None})
    merged = Merger().merge(utterance=text, llm=ExtractOutcome(status="ok", result=model), parsed=parsed,
                            keyword_intents=[], pending=pending, known={}, session_lang="en")
    food = [o for o in merged.observations if o.slot == S.household_food]
    assert [(o.value, o.state) for o in food] == [("separate", "clear")]
