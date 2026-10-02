"""Misreadings found by the verification runs (live model, adversarial dialogues, simulated students), each pinned by
the smallest check that would have caught it: the rule parser alone (the path closed mode, timeouts and the fake model
use), the merge with a model that leaves a fact out, the input guard, and the fast path."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from gatorplate.contracts.common import Lang, SlotSource
from gatorplate.contracts.extraction import (
    ExtractionResult,
    ExtractOutcome,
    Intent,
    PendingQuestion,
    SlotObservation,
)
from gatorplate.contracts.slots import SlotName
from gatorplate.extract import Understander
from gatorplate.extract.keywords import KeywordMatcher
from gatorplate.extract.llm.fake import FakeLLM
from gatorplate.extract.merge import Merger
from gatorplate.extract.parser import Parser
from gatorplate.extract.redact import Redactor
from gatorplate.extract.text import normalize

S = SlotName
AGE = PendingQuestion(key="ask.age_parent", slots=[S.age, S.lives_with_parent], kind="open")
HOUSEHOLD = PendingQuestion(key="ask.household",
                            slots=[S.household_food, S.lives_with_parent, S.roommates, S.spouse, S.children_count],
                            kind="open")
FOOD_FLIP = PendingQuestion(key="flip.household_food", slots=[S.household_food], kind="choice",
                            choices=["shared", "separate"])
INCOME = PendingQuestion(key="ask.income", slots=[S.earned_monthly, S.other_cash_monthly], kind="number")
RENT = PendingQuestion(key="ask.rent", slots=[S.rent_share], kind="number")
CASH = PendingQuestion(key="expedited.intro_cash", slots=[S.cash_on_hand], kind="number")
RBO = PendingQuestion(key="flip.rent_paid_by_others", slots=[S.rent_paid_by_others_to_landlord], kind="yes_no")
HEAT = PendingQuestion(key="flip.heat_cool", slots=[S.heat_cool], kind="yes_no")
UNITS_CLOSED = PendingQuestion(key="ask.units", slots=[S.half_time], kind="yes_no", closed=True)
SPLIT = PendingQuestion(key="flip.earned_split", slots=[S.earned_monthly], kind="yes_no")
CLOSE = PendingQuestion(key="close.anything_else", slots=[], kind="open")
RENT_1100 = {S.rent_share: "1100.00"}


def read(parser: Parser, text: str, pending: PendingQuestion | None, known: dict | None = None,
         lang: str = "en") -> dict[str, tuple[str, str]]:
    parsed = parser.parse(normalize(text), pending, known or {}, lang)
    return {o.slot.value: (o.value, o.state) for o in parsed.observations}


def model(*observations: SlotObservation, answered: str = "yes", lang: str = "en") -> ExtractOutcome:
    return ExtractOutcome(status="ok", result=ExtractionResult(
        observations=list(observations), intents=[], answered_pending=answered, lang=lang,  # type: ignore[arg-type]
        side_question=None, requested_language=None))


def ob(slot: SlotName, value: str, quote: str, period: str | None = None) -> SlotObservation:
    return SlotObservation(slot=slot, value=value, period=period, hours_per_week=None, state="clear",  # type: ignore
                           quote=quote, quote_en=None)


def merge(parser: Parser, text: str, outcome: ExtractOutcome, pending: PendingQuestion,
          known: dict | None = None) -> dict[str, tuple[str, SlotSource]]:
    parsed = parser.parse(text, pending, known or {}, "en")
    merged = Merger().merge(utterance=text, llm=outcome, parsed=parsed, keyword_intents=[], pending=pending,
                            known=known or {}, session_lang="en")
    return {o.slot.value: (o.value, merged.sources[o.slot]) for o in merged.observations}


# ------------------------------------------------------------------------------------------------ who lives with whom
def test_open_question_keeps_the_parsers_answer_the_model_left_out(parser: Parser) -> None:
    """The model returned only the age and the roommates for the open age question; the parser's lives_with_parent and
    the never-asked roommate count stay, so the question is not asked again."""
    text = "I'm 20, and I live with two roommates."
    got = merge(parser, text, model(ob(S.age, "20", "I'm 20"), ob(S.roommates, "true", "two roommates")), AGE)
    assert got["lives_with_parent"] == ("false", SlotSource.parser)
    assert got["roommates_count"] == ("2", SlotSource.parser)
    assert got["age"] == ("20", SlotSource.llm)


def test_the_models_no_still_wins_and_contradictions_drop_the_backstops(parser: Parser) -> None:
    text = "I'm 20, and I live with two roommates."
    assert merge(parser, text, model(answered="no"), AGE) == {}
    got = merge(parser, text, model(ob(S.roommates, "false", "I live with")), AGE)
    assert "roommates_count" not in got
    alone = "I'm 20, and I live by myself."
    assert merge(parser, alone, model(ob(S.age, "20", "I'm 20")), AGE)["household_food"] == ("alone",
                                                                                              SlotSource.parser)
    assert "household_food" not in merge(parser, alone, model(ob(S.roommates, "true", "I live")), AGE)


@pytest.mark.parametrize("text", ["20, two roommates.", "I'm 20 and I have two roommates.",
                                  "I'm twenty, and I share an apartment with two roommates.",
                                  "I'm 25 and I've been staying on a friend's couch, I buy my own food.",
                                  "Tengo 20 años y vivo por mi cuenta.", "I'm 23, I live with my wife."])
def test_who_the_student_lives_with_answers_lives_with_parent(parser: Parser, text: str) -> None:
    got = read(parser, text, AGE)
    assert got["lives_with_parent"] == ("false", "clear") and "age" in got


def test_a_parent_said_with_roommates_is_still_a_parent(parser: Parser) -> None:
    assert read(parser, "I'm 19, I live with my mom and two roommates.", AGE)["lives_with_parent"] == ("true", "clear")
    assert read(parser, "I'm 19 and I share an apartment with my mom.", AGE).get("lives_with_parent") != ("false",
                                                                                                    "clear")


@pytest.mark.parametrize("text,pending", [
    ("I'm 20, and I live by myself.", AGE), ("I'm 20 years old, and I live on my own.", AGE),
    ("Tengo 19 años y vivo solo.", AGE), ("Tengo 21 años y vivo por mi cuenta, solo.", AGE),
    ("I live alone, so I buy and cook my own food separately", HOUSEHOLD),
    ("I live alone, so I don't share food with anyone.", HOUSEHOLD),
    ("Vivo solo, así que compro y cocino mi comida por mi cuenta.", HOUSEHOLD),
    ("I don't have roommates — I live alone, so I buy and cook food just for myself.", FOOD_FLIP),
    ("I live with my wife. She works full-time and isn't in school.", HOUSEHOLD),
    ("I'm 30 and I live with my husband and our two kids.", AGE), ("Vivo con mi esposa y mis dos hijos.", HOUSEHOLD),
])
def test_living_alone_is_household_food_alone(parser: Parser, text: str, pending: PendingQuestion) -> None:
    assert read(parser, text, pending)["household_food"] == ("alone", "clear")


def test_roommates_are_never_alone(parser: Parser) -> None:
    assert read(parser, "Just me and my roommates, we each buy our own food.", HOUSEHOLD)["household_food"][0] \
        == "separate"
    assert read(parser, "I live with my wife and my brother, we share food.", HOUSEHOLD)["household_food"][0] == "shared"
    family = read(parser, "Just me, my mom and my brother.", HOUSEHOLD)
    assert family.get("household_food") != ("alone", "clear") and "roommates" not in family


def test_spouse_household(parser: Parser) -> None:
    got = read(parser, "I live with my wife. She works full-time and isn't in school.", HOUSEHOLD)
    assert got["spouse"] == ("true", "clear") and got["spouse_student"] == ("false", "clear")
    assert "half_time" not in got  # "full-time" is the spouse's job, not the student's units


# ------------------------------------------------------------------------------------------------ numbers that are not money
@pytest.mark.parametrize("text,pending,slot,value", [
    ("I work at the library, about 900 a month, since 2024.", INCOME, "earned_monthly", "900"),
    ("I work Saturdays from nine to five and make 1,200 a month.", INCOME, "earned_monthly", "1200"),
    ("I have to go to work at five, but I make about 900 a month.", INCOME, "earned_monthly", "900"),
    ("I have to go to work at three, I make about 900.", INCOME, "earned_monthly", "900"),
    ("Trabajo de 4 a 8 y gano 800 al mes.", INCOME, "earned_monthly", "800"),
    ("I pay 1100, my room is number 4.", RENT, "rent_share", "1100"),
    ("I have 2 accounts with about 100 total.", CASH, "cash_on_hand", "100"),
])
def test_times_years_labels_and_counts_are_not_amounts(parser: Parser, text: str, pending: PendingQuestion,
                                                      slot: str, value: str) -> None:
    assert read(parser, text, pending)[slot] == (value, "clear")


@pytest.mark.parametrize("text,pending,slot,value", [
    ("Between 800 and 1,000 a month.", INCOME, "earned_monthly", "1000"),  # a range keeps its high end (income)
    ("I make 2000 a month.", INCOME, "earned_monthly", "2000"),  # a round amount is not a year
    ("I get 12 an hour, 10 hours a week.", INCOME, "earned_monthly", "12"),
    ("Rent is 950, I've lived here since 2022.", RENT, "rent_share", "950"),
])
def test_real_amounts_stay(parser: Parser, text: str, pending: PendingQuestion, slot: str, value: str) -> None:
    assert read(parser, text, pending)[slot][0] == value


# ------------------------------------------------------------------------------------------------ whose money
@pytest.mark.parametrize("text", ["I make about 900 a month, nobody gives me cash.",
                                  "About 900 a month, nobody gives me cash.",
                                  "Like 900 a month, no one gives me anything."])
def test_a_denied_gift_never_takes_the_pay(parser: Parser, text: str) -> None:
    got = read(parser, text, INCOME)
    assert got["earned_monthly"] == ("900", "clear") and got["other_cash_monthly"] == ("0", "clear")


def test_pay_from_work_with_nobody_giving_money(parser: Parser) -> None:
    got = read(parser, "About 1,000 a month from work, nobody gives me money.", INCOME)
    assert got == {"earned_monthly": ("1000", "clear"), "other_cash_monthly": ("0", "clear")}


@pytest.mark.parametrize("text", ["No, nadie me paga parte de la renta al dueño.",
                                  "No, nobody pays any part of my rent to my landlord."])
def test_nobody_paying_the_landlord_is_not_family_cash(parser: Parser, text: str) -> None:
    known = {S.rent_share: "900.00", S.other_cash_monthly: "300.00"}
    got = read(parser, text, RBO, known)
    assert got == {"rent_paid_by_others_to_landlord": ("0", "clear")}  # the family cash said earlier stays as it was


def test_nobody_gives_me_money_still_counts_anywhere(parser: Parser) -> None:
    assert read(parser, "No, nobody gives me money, and nobody pays my landlord.", RBO, RENT_1100) == {
        "other_cash_monthly": ("0", "clear"), "rent_paid_by_others_to_landlord": ("0", "clear")}


@pytest.mark.parametrize("text", [
    "I don't have any income, and no one gives me money either.", "No tengo ingresos, nadie me da dinero regularmente.",
    "No tengo ingresos de trabajo, y nadie me da dinero tampoco.",
])
def test_no_income_at_all(parser: Parser, text: str) -> None:
    got = read(parser, text, INCOME)
    assert got == {"earned_monthly": ("0", "clear"), "other_cash_monthly": ("0", "clear")}


@pytest.mark.parametrize("text,pending", [("I don't earn anything from work.", INCOME),
                                          ("No gano nada, no tengo trabajo.", INCOME),
                                          ("I don't work, so I don't have any income from work.", SPLIT)])
def test_no_pay_from_work(parser: Parser, text: str, pending: PendingQuestion) -> None:
    assert read(parser, text, pending)["earned_monthly"] == ("0", "clear")


# ------------------------------------------------------------------------------------------------ rent paid by others
@pytest.mark.parametrize("text", ["No, nobody pays any part of my rent to my landlord. I pay it all myself.",
                                  "No, I pay all eleven hundred myself.", "I pay it all myself.",
                                  "No, yo la pago toda."])
def test_the_student_paying_is_zero_from_others(parser: Parser, text: str) -> None:
    assert read(parser, text, RBO, RENT_1100) == {"rent_paid_by_others_to_landlord": ("0", "clear")}


@pytest.mark.parametrize("text", ["My parents pay all of it.", "Yes, all of it.", "Mis papás pagan todo.", "Todo."])
def test_all_of_it_from_someone_else_still_reads(parser: Parser, text: str) -> None:
    assert read(parser, text, RBO, RENT_1100)["rent_paid_by_others_to_landlord"] == ("1100", "clear")


@pytest.mark.parametrize("text", ["Wait, no, my rent is twelve hundred, not eleven hundred.",
                                  "No, espera, son mil doscientos, no mil cien.", "Espera, son mil doscientos."])
def test_a_corrected_rent_is_never_paid_by_others(parser: Parser, text: str) -> None:
    parsed = parser.parse(normalize(text), RBO, RENT_1100, "en")
    got = {o.slot.value: o.value for o in parsed.observations}
    assert got == {"rent_share": "1200"} and Intent.correction in parsed.intents


def test_the_rent_said_again_answers_nothing(parser: Parser) -> None:
    assert read(parser, "Hello? I said eleven hundred.", RBO, RENT_1100) == {}
    assert read(parser, "Yes, about 300.", RBO, RENT_1100) == {"rent_paid_by_others_to_landlord": ("300", "clear")}
    assert read(parser, "Yes, eleven hundred.", RBO, RENT_1100)["rent_paid_by_others_to_landlord"][0] == "1100"
    assert read(parser, "Yeah, actually my parent pays 1100 dollars a month straight to the landlord for me.", RBO,
                RENT_1100)["rent_paid_by_others_to_landlord"][0] == "1100"


def test_grounding_rejects_a_self_paid_all_of_it(parser: Parser) -> None:
    """A model reading "I pay it all myself" as the whole rent paid by someone else is not grounded."""
    text = "No, nobody pays any part of my rent to my landlord. I pay it all myself."
    got = merge(parser, text, model(ob(S.rent_paid_by_others_to_landlord, "1100", "I pay it all myself", "month")),
                RBO, RENT_1100)
    assert got["rent_paid_by_others_to_landlord"][0] == "0"


# ------------------------------------------------------------------------------------------------ unsure is not no
@pytest.mark.parametrize("text", ["No estoy seguro de cuántas unidades tomo este semestre.",
                                  "No estoy segura, la verdad.", "No sé."])
def test_unsure_is_not_a_no(parser: Parser, text: str) -> None:
    parsed = parser.parse(normalize(text), UNITS_CLOSED, {}, "es")
    assert parsed.observations == [] and parsed.answer is None and Intent.dont_know in parsed.intents


# ------------------------------------------------------------------------------------------------ input guard
@pytest.mark.parametrize("text", [
    "I'm thinking about ending it all.", "What's the point of living, honestly.", "I wish I wasn't alive.",
    "Sometimes I feel like everyone would be better off without me.",
    "I've been thinking about not being here anymore.", "I just want to disappear forever.",
    "Ya no quiero estar aquí, en serio.", "No tiene sentido seguir viviendo.", "Quisiera desaparecer para siempre.",
    "A veces siento que no tiene sentido seguir viviendo.",
])
def test_indirect_crisis_phrases(keywords: KeywordMatcher, text: str) -> None:
    assert Intent.crisis in keywords.match(text)


@pytest.mark.parametrize("text", ["I'm ending my lease in June.", "Can we end the call?", "The point of the job is the pay.",
                                  "My roommate wants to move out.", "No tiene sentido pagar tanto de renta."])
def test_no_crisis_in_ordinary_lines(keywords: KeywordMatcher, text: str) -> None:
    assert Intent.crisis not in keywords.match(text)


@pytest.mark.parametrize("text,kind", [
    ("My social is one twenty three, forty five, sixty seven eighty nine.", "ssn"),
    ("Mi seguro social es uno veintitrés, cuarenta y cinco, sesenta y siete ochenta y nueve.", "ssn"),
    ("It's four fifteen, three three eight, twelve oh three.", "ssn"),
    ("card is forty one eleven, eleven eleven, eleven eleven, eleven eleven", "card_number"),
])
def test_grouped_spoken_numbers_are_redacted(redactor: Redactor, text: str, kind: str) -> None:
    got = redactor.redact(normalize(text))
    assert got.kinds == [kind] and "[REDACTED]" in got.text
    assert not any(w in got.text.lower() for w in ("twenty", "forty", "sixty", "eleven", "fifteen", "sesenta"))


@pytest.mark.parametrize("text", ["about fifteen hundred a month, maybe nineteen fifty", "I'm twenty, twelve units",
                                  "twenty, thirty, forty dollars a day", "nineteen fifty an hour for twenty hours a week",
                                  "I'm twenty two, I take twelve units and make nine fifty",
                                  "Gano mil doscientos cincuenta al mes.", "veinte, treinta y cinco, cuarenta"])
def test_amounts_in_words_are_not_redacted(redactor: Redactor, text: str) -> None:
    got = redactor.redact(normalize(text))
    assert got.kinds == [] and got.text == normalize(text)


async def test_a_grouped_ssn_never_reaches_the_parser_or_the_model(settings_test) -> None:
    fake = FakeLLM()
    u = Understander(settings=settings_test, llm=fake)
    result = await u.understand(text="My social is one twenty three, forty five, sixty seven eighty nine.",
                                masked=False, confidence=0.9, dtmf=None, pending=INCOME, known={}, recent=[],
                                last_prompt=None, lang=Lang.en, deadline=u.clock.monotonic() + 2.6, closed_mode=False)
    assert result.redactions == ["ssn"] and result.observations == []
    assert "sixty" not in result.redacted_text


@pytest.mark.parametrize("text", [
    "No, that's everything, thanks so much for your help!", "No, I think that's everything. Thanks for helping me out!",
    "No, that's helpful, thanks! I'll go ahead and apply today.", "Nope, I got it. Thanks for the help!",
    "No, that's all good. Thanks for the help!", "Thank you so much!",
])
def test_english_closings_are_done(keywords: KeywordMatcher, text: str) -> None:
    assert keywords.is_done_phrase(text, "en")


@pytest.mark.parametrize("text", [
    "No, gracias. Entendido, voy a hacer la solicitud hoy.", "No, nada más. Gracias por la ayuda.",
    "No, gracias. Está claro todo.", "No, ya está. Gracias de nuevo.", "No, está bien. Muchas gracias por la ayuda.",
    "No, gracias. Tengo el número y sé qué hacer. Adiós.", "No, está bien, gracias. Voy a llamar si tengo más preguntas.",
])
def test_spanish_closings_are_done(keywords: KeywordMatcher, text: str) -> None:
    assert keywords.is_done_phrase(text, "es")


@pytest.mark.parametrize("text", [
    "No, but I have one more question.", "Nada más quería preguntar algo.", "Thanks, but what documents do I need?",
    "No, wait, actually my rent is 1200.", "No, pero tengo una pregunta.", "Thank you. Can I ask about the interview?",
    "Yes, one more thing.",
])
def test_a_question_at_the_close_is_not_done(keywords: KeywordMatcher, text: str) -> None:
    assert not keywords.is_done_phrase(text, "en") and not keywords.is_done_phrase(text, "es")


# ------------------------------------------------------------------------------------------------ fast path
async def _turn(u: Understander, text: str, pending: PendingQuestion, lang: Lang = Lang.en) -> Any:
    return await u.understand(text=text, masked=False, confidence=0.9, dtmf=None, pending=pending, known={},
                              recent=[], last_prompt=None, lang=lang, deadline=u.clock.monotonic() + 2.6,
                              closed_mode=False)


async def test_a_closing_phrase_needs_no_model_call(settings_test) -> None:
    fake = FakeLLM()
    u = Understander(settings=settings_test, llm=fake)
    result = await _turn(u, "No, that's all. Thanks for the help!", CLOSE)
    assert fake.calls == 0 and result.llm.status == "skipped" and result.answered_pending == "yes"
    await _turn(u, "Thanks, but what documents do I need?", CLOSE)
    assert fake.calls == 1  # a question at the close still goes to the model


async def test_a_short_full_answer_to_an_open_question_needs_no_model_call(settings_test) -> None:
    fake = FakeLLM()
    u = Understander(settings=settings_test, llm=fake)
    result = await _turn(u, "20, two roommates.", AGE)
    assert fake.calls == 0
    assert {o.slot: o.value for o in result.observations}[S.lives_with_parent] == "false"
    await _turn(u, "Twenty.", AGE)  # only part of the open question: the model listens
    assert fake.calls == 1


# ------------------------------------------------------------------------------------------------ fake table loader
def test_fake_table_loader_skips_blank_lines_and_a_missing_file(tmp_path: Path) -> None:
    row = ('{"id": "x1", "lang": "en", "pending": {"key": "ask.rent", "slots": ["rent_share"], "kind": "number"}, '
           '"utterance": "Nine fifty.", "expect": {"observations": [], "intents": [], "answered_pending": "no", '
           '"lang": "en", "side_question": null, "requested_language": null}}')
    table = tmp_path / "lines.jsonl"
    table.write_text("\n" + row + "\n\n   \n", encoding="utf-8")
    assert list(FakeLLM(table_path=table).table) == ["Nine fifty."]
    assert FakeLLM(table_path=tmp_path / "missing.jsonl").table == {}


def test_money_math_stays_decimal(parser: Parser) -> None:
    ob_ = parser.parse("About 900 a month, nobody gives me cash.", INCOME, {}, "en").observations[0]
    assert Decimal(ob_.value) == Decimal(900)
