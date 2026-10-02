"""Misreadings found by the second verification round (adversarial dialogues and simulated students), each pinned by
the smallest check that would have caught it: the rule parser alone (the path closed mode, model timeouts and the
fake model use), the input guard, and one understanding turn without the model."""

from __future__ import annotations

from typing import Any

import pytest

from gatorplate.contracts.common import Lang
from gatorplate.contracts.extraction import Intent, PendingQuestion
from gatorplate.contracts.slots import SlotName
from gatorplate.extract import Understander
from gatorplate.extract.keywords import KeywordMatcher
from gatorplate.extract.llm.fake import FakeLLM
from gatorplate.extract.parser import Parser
from gatorplate.extract.text import normalize

S = SlotName
INCOME = PendingQuestion(key="ask.income", slots=[S.earned_monthly, S.other_cash_monthly], kind="number")
INCOME_CLOSED = PendingQuestion(key="ask.income", slots=[S.earned_monthly], kind="yes_no", closed=True)
RENT = PendingQuestion(key="ask.rent", slots=[S.rent_share], kind="number")
RENT_CLOSED = PendingQuestion(key="ask.rent", slots=[S.rent_share], kind="choice", closed=True)
CASH = PendingQuestion(key="expedited.intro_cash", slots=[S.cash_on_hand], kind="number")
RBO = PendingQuestion(key="flip.rent_paid_by_others", slots=[S.rent_paid_by_others_to_landlord], kind="yes_no")
HEAT = PendingQuestion(key="flip.heat_cool", slots=[S.heat_cool], kind="yes_no")
UNITS_CLOSED = PendingQuestion(key="ask.units", slots=[S.half_time], kind="yes_no", closed=True)
AGE = PendingQuestion(key="ask.age_parent", slots=[S.age, S.lives_with_parent], kind="open")
HOUSEHOLD = PendingQuestion(key="ask.household",
                            slots=[S.household_food, S.lives_with_parent, S.roommates, S.spouse, S.children_count],
                            kind="open")
MARIA = {S.earned_monthly: "900.00", S.other_cash_monthly: "0.00", S.rent_share: "1100.00"}
FAMILY_CASH = {S.earned_monthly: "1200.00", S.other_cash_monthly: "300.00", S.rent_share: "900.00"}


def read(parser: Parser, text: str, pending: PendingQuestion | None, known: dict | None = None,
         lang: str = "en") -> dict[str, tuple[str, str]]:
    parsed = parser.parse(normalize(text), pending, known or {}, lang)
    return {o.slot.value: (o.value, o.state) for o in parsed.observations}


async def turn(u: Understander, text: str, pending: PendingQuestion, known: dict | None = None,
               lang: Lang = Lang.en, closed_mode: bool = False) -> Any:
    return await u.understand(text=text, masked=False, confidence=0.9, dtmf=None, pending=pending,
                              known=known or {}, recent=[], last_prompt=None, lang=lang,
                              deadline=u.clock.monotonic() + 2.6, closed_mode=closed_mode)


# ------------------------------------------------------------------------------------------------ crisis without a model
CRISIS = [
    "Life isn't worth living anymore.", "I have nothing to live for.", "I don't want to wake up tomorrow.",
    "Everyone would be better off if I was gone.", "I feel like I can't go on.", "I don't want to exist anymore.",
    "I'd rather be dead.", "I don't see a reason to keep going.", "I wish I could just go to sleep and never wake up.",
    "I'm done with life.", "I feel like dying.", "I'm good, thanks. I don't really see the point of anything anymore.",
    "Me quiero matar.", "No vale la pena vivir.", "No quiero despertar mañana.", "Estaría mejor muerta.",
    "Quiero dejar de existir.", "Pienso en morirme.", "No tengo razones para vivir.", "Ya no puedo más con la vida.",
]
NOT_CRISIS = [
    "This rent is killing me, it's eleven hundred.", "I'm dying to know how much I get.", "Me muero de hambre, la verdad.",
    "I don't want to wake up early for the interview.", "I can't go on campus on Fridays.", "Estoy muerta de cansancio.",
    "No quiero despertar temprano mañana.", "No tiene sentido pagar tanto de renta, son mil cien.",
    "I don't see a reason to keep going with this call.", "I'm done with the semester in May.",
]


@pytest.mark.parametrize("text", CRISIS)
def test_crisis_phrasings_are_caught_by_the_keyword_lists(keywords: KeywordMatcher, text: str) -> None:
    assert Intent.crisis in keywords.match(text)


@pytest.mark.parametrize("text", NOT_CRISIS)
def test_ordinary_lines_are_not_a_crisis(keywords: KeywordMatcher, text: str) -> None:
    assert Intent.crisis not in keywords.match(text)


async def test_a_crisis_line_reaches_the_dialogue_in_closed_mode(settings_test) -> None:
    u = Understander(settings=settings_test, llm=FakeLLM())
    result = await turn(u, "Me quiero matar.", INCOME, MARIA, lang=Lang.es, closed_mode=True)
    assert Intent.crisis in result.keyword_intents and result.llm.status == "skipped"


# ------------------------------------------------------------------------------------------------ one amount, not a sum
@pytest.mark.parametrize("text,value", [
    ("I've worked at the library since 2023 and make about 900 a month.", "900"),
    ("Trabajo desde 2023 y gano 900 al mes.", "900"),
    ("I make 900 a month, 450 from each of my 2 jobs.", "900"),
    ("In 2025 I made 700, now I make 900 a month.", "900"),
    ("I used to make 1200 but now it's 900 a month.", "900"),
])
def test_a_year_or_an_old_or_partial_amount_is_never_added_to_the_pay(parser: Parser, text: str, value: str) -> None:
    assert read(parser, text, INCOME)["earned_monthly"] == (value, "clear")


def test_another_season_or_a_guess_is_never_a_clear_sum(parser: Parser) -> None:
    assert read(parser, "About nine fifty a month, maybe nineteen fifty in the summer.", INCOME)["earned_monthly"] \
        == ("950", "unclear")
    assert read(parser, "Like 800, maybe 900 a month.", INCOME)["earned_monthly"] == ("900", "unclear")


@pytest.mark.parametrize("text", ["I make 600 at the library and 300 at the cafe.",
                                  "I make 600 at the library, 300 at the cafe.",
                                  "I make 600 a month at the library, and now also 300 at the cafe."])
def test_two_jobs_are_still_added(parser: Parser, text: str) -> None:
    assert read(parser, text, INCOME)["earned_monthly"] == ("900", "clear")


@pytest.mark.parametrize("text,value", [("Eleven fifty, split three ways, so like three eighty three.", "383"),
                                        ("The whole place is 2200, I pay half, so 1100.", "1100")])
def test_a_rent_said_with_its_split_keeps_the_share_unclear(parser: Parser, text: str, value: str) -> None:
    assert read(parser, text, RENT) == {"rent_share": (value, "unclear")}


# ------------------------------------------------------------------------------------------------ whose amount
@pytest.mark.parametrize("text,lang", [("I make 900 a month, my mom gives me 200.", "en"),
                                       ("I make 900 a month. My mom gives me 200.", "en"),
                                       ("Gano 900 al mes, mi mamá me da 200.", "es")])
def test_pay_and_a_gift_in_one_sentence_stay_apart(parser: Parser, text: str, lang: str) -> None:
    got = read(parser, text, INCOME, lang=lang)
    assert got["earned_monthly"] == ("900", "clear") and got["other_cash_monthly"] == ("200", "clear")


def test_pay_and_money_sent_by_parents(parser: Parser) -> None:
    got = read(parser, "I earn 900, my parents send me 300.", INCOME)
    assert got["earned_monthly"][0] == "900" and got["other_cash_monthly"] == ("300", "clear")


@pytest.mark.parametrize("text,slot,lang", [
    ("Vendo comida los fines de semana, gano como trescientos al mes.", "gig_monthly", "es"),
    ("It's work-study, I make 400 a month.", "work_study_monthly", "en"),
])
def test_the_kind_of_work_said_in_the_same_sentence_types_the_pay(parser: Parser, text: str, slot: str,
                                                                  lang: str) -> None:
    got = read(parser, text, INCOME, lang=lang)
    assert slot in got and "earned_monthly" not in got


def test_the_students_own_part_of_the_rent_is_never_paid_by_others(parser: Parser) -> None:
    text = "My parents pay 300 of my rent, I pay 800."
    assert read(parser, text, RBO, MARIA) == {"rent_paid_by_others_to_landlord": ("300", "clear")}
    assert read(parser, text, RENT) == {"rent_share": ("800", "clear")}


@pytest.mark.parametrize("text,pending,slot,value", [
    ("Give me a second, it's eleven hundred.", RENT, "rent_share", "1100"),
    ("They give me a room for eleven hundred.", RENT, "rent_share", "1100"),
    ("Give me a second, it's about 900 a month.", INCOME, "earned_monthly", "900"),
])
def test_give_me_a_second_or_a_room_is_not_money_given(parser: Parser, text: str, pending: PendingQuestion,
                                                       slot: str, value: str) -> None:
    assert read(parser, text, pending, MARIA) == {slot: (value, "clear")}


@pytest.mark.parametrize("text", ["Hold on, I make 900 a month, let me check my rent.",
                                  "I make 900 a month, let me check my rent.", "I make 900 a month, so rent is hard."])
def test_pay_said_at_the_rent_question_is_pay(parser: Parser, text: str) -> None:
    for pending in (RENT, RENT_CLOSED):
        assert read(parser, text, pending, MARIA) == {"earned_monthly": ("900", "clear")}


@pytest.mark.parametrize("text,pending", [("I have 1000 saved.", RENT), ("I have 1000 saved.", RENT_CLOSED),
                                          ("I have about a thousand in the bank.", INCOME)])
def test_savings_are_cash_on_hand_never_rent_or_pay(parser: Parser, text: str, pending: PendingQuestion) -> None:
    assert read(parser, text, pending, MARIA) == {"cash_on_hand": ("1000", "clear")}


def test_a_band_answer_to_the_closed_rent_question_still_reads(parser: Parser) -> None:
    assert read(parser, "Eleven hundred.", RENT_CLOSED)["rent_share"] == ("1100", "clear")
    assert read(parser, "Under a thousand.", RENT_CLOSED)["rent_share"] == ("0", "unclear")


# ------------------------------------------------------------------------------------------------ cash on hand
@pytest.mark.parametrize("text", [
    "About forty dollars until I get paid.", "About forty dollars until I get paid on the 15th.",
    "Forty dollars, I get paid Friday.", "About 40 dollars, my paycheck comes next week.",
    "About forty dollars, I get paid on Friday the 10th.", "Unos cuarenta dólares hasta que me paguen.",
])
def test_when_the_student_gets_paid_is_not_pay(parser: Parser, text: str) -> None:
    assert read(parser, text, CASH, MARIA) == {"cash_on_hand": ("40", "clear")}


def test_pay_said_with_the_cash_still_reads_as_pay(parser: Parser) -> None:
    got = read(parser, "I have 40, I get paid 450 every two weeks.", CASH, MARIA)
    assert got["cash_on_hand"] == ("40", "clear") and got["earned_monthly"][0] == "450"
    got = read(parser, "I get paid on Friday, about 450 every two weeks.", INCOME)
    assert got["earned_monthly"][0] == "450"


# ------------------------------------------------------------------------------------------------ family cash said earlier
@pytest.mark.parametrize("text,pending", [
    ("No, nobody helps me with the rent.", RBO), ("No, nobody gives my landlord anything for me.", RBO),
    ("No, nadie me ayuda con la renta.", RBO), ("No, nadie me da nada para la renta.", RBO),
    ("Nadie me ayuda, la pago yo.", RBO),
    ("No, nobody sends me a heating bill, it's included.", HEAT), ("No, nadie me manda recibo de calefacción.", HEAT),
])
def test_an_answer_to_another_question_never_zeroes_family_cash(parser: Parser, text: str,
                                                                pending: PendingQuestion) -> None:
    got = read(parser, text, pending, FAMILY_CASH)
    assert "other_cash_monthly" not in got and pending.slots[0].value in got


async def test_family_cash_survives_the_landlord_question_in_closed_mode(settings_test) -> None:
    u = Understander(settings=settings_test, llm=FakeLLM())
    result = await turn(u, "No, nobody helps me with the rent.", RBO, FAMILY_CASH, closed_mode=True)
    assert {o.slot: o.value for o in result.observations} == {S.rent_paid_by_others_to_landlord: "0"}


@pytest.mark.parametrize("text", ["I'm unemployed right now and nobody helps me.", "Estoy desempleado y nadie me da nada."])
def test_no_job_and_nobody_helping_at_the_income_question(parser: Parser, text: str) -> None:
    for pending in (INCOME, INCOME_CLOSED):
        got = read(parser, text, pending)
        assert got == {"earned_monthly": ("0", "clear"), "other_cash_monthly": ("0", "clear")}


# ------------------------------------------------------------------------------------------------ nobody pays the landlord
@pytest.mark.parametrize("text", ["Nobody.", "No one.", "Nobody does.", "Nadie.", "No one, I pay the entire rent on my own.",
                                  "No one, I pay the full rent myself."])
def test_nobody_is_a_no_to_the_landlord_question(parser: Parser, text: str) -> None:
    parsed = parser.parse(normalize(text), RBO, MARIA, "en")
    assert {o.slot: (o.value, o.state) for o in parsed.observations} == {
        S.rent_paid_by_others_to_landlord: ("0", "clear")}
    assert parsed.confident


def test_nobody_but_my_mom_names_someone(parser: Parser) -> None:
    assert "rent_paid_by_others_to_landlord" not in read(parser, "Nobody but my mom.", RBO, MARIA)


async def test_a_bare_nobody_needs_no_model_call(settings_test) -> None:
    fake = FakeLLM()
    u = Understander(settings=settings_test, llm=fake)
    result = await turn(u, "Nobody.", RBO, MARIA)
    assert fake.calls == 0 and result.answered_pending == "yes"


# ------------------------------------------------------------------------------------------------ spouse
@pytest.mark.parametrize("text", ["My wife and I. She works full-time, she's not in school.", "Just me and my wife.",
                                  "Me and my husband.", "It's just my wife and me.", "Mi esposa y yo."])
def test_a_spouse_only_household(parser: Parser, text: str) -> None:
    got = read(parser, text, HOUSEHOLD)
    assert got["spouse"] == ("true", "clear") and got["household_food"] == ("alone", "clear")


def test_a_spouse_not_in_school(parser: Parser) -> None:
    got = read(parser, "My wife and I. She works full-time, she's not in school.", HOUSEHOLD)
    assert got["spouse_student"] == ("false", "clear") and "half_time" not in got


@pytest.mark.parametrize("text,lang", [("I'm 23, married, we have our own place.", "en"),
                                       ("Tengo 23 años y vivo con mi esposa.", "es")])
def test_married_with_an_own_place_answers_the_age_question(parser: Parser, text: str, lang: str) -> None:
    got = read(parser, text, AGE, lang=lang)
    assert got["age"] == ("23", "clear") and got["lives_with_parent"] == ("false", "clear")
    assert got["spouse"] == ("true", "clear")


def test_married_parents_are_not_a_spouse(parser: Parser) -> None:
    assert "spouse" not in read(parser, "I'm 19 and I live with my parents, they're married.", AGE)


# ------------------------------------------------------------------------------------------------ unsure is not no
@pytest.mark.parametrize("text", ["No tengo idea.", "No recuerdo cuántas.", "No clue, honestly.", "No lo sé.",
                                  "I can't remember."])
def test_no_idea_is_not_a_no(parser: Parser, text: str) -> None:
    parsed = parser.parse(normalize(text), UNITS_CLOSED, {}, "en")
    assert parsed.observations == [] and parsed.answer is None and Intent.dont_know in parsed.intents


# ------------------------------------------------------------------------------------------------ the close question
@pytest.mark.parametrize("text,lang", [
    ("Nothing, thanks.", "en"), ("I'm all good, thank you!", "en"), ("Not really, thanks.", "en"),
    ("Nope, have a good one.", "en"), ("Okay, I'll apply today. Thanks!", "en"),
    ("Great, I'm going to apply right now.", "en"), ("Okay thanks!", "en"), ("Perfect, thank you.", "en"),
    ("No, but thanks for asking.", "en"), ("Alright, that was helpful, bye.", "en"),
    ("That's what I needed, thanks.", "en"), ("No thanks, I'll call if I have questions.", "en"),
    ("Nada, gracias.", "es"), ("Ya está, gracias.", "es"), ("Todo bien, gracias.", "es"),
    ("Perfecto, muchas gracias.", "es"), ("Bueno, voy a aplicar hoy, gracias.", "es"), ("Gracias, adiós.", "es"),
    ("No, pero gracias.", "es"), ("Creo que eso es todo, gracias.", "es"), ("No gracias, que tengas buen día.", "es"),
])
def test_common_closings_end_the_call(keywords: KeywordMatcher, text: str, lang: str) -> None:
    assert keywords.is_done_phrase(text, lang)


@pytest.mark.parametrize("text,lang", [
    ("No thanks, I have a question about the card.", "en"), ("No, thanks. What documents do I need", "en"),
    ("No thank you, how long does it take", "en"), ("No thanks, just one question, do I need my pay stubs", "en"),
    ("No thanks. Is it free", "en"), ("Nothing else, but what's the interview like", "en"),
    ("That's all, how do I apply", "en"), ("No thanks, tell me about the interview", "en"), ("Okay.", "en"),
    ("No, gracias, qué documentos necesito", "es"), ("No gracias, cuánto tarda", "es"),
    ("No gracias, que documentos necesito", "es"), ("Gracias, tengo una duda", "es"), ("¿Eso es todo?", "es"),
    ("Bueno.", "es"),
])
def test_a_question_without_a_question_mark_never_ends_the_call(keywords: KeywordMatcher, text: str,
                                                                 lang: str) -> None:
    assert not keywords.is_done_phrase(text, lang)


async def test_a_question_at_the_close_goes_to_the_model(settings_test) -> None:
    fake = FakeLLM()
    u = Understander(settings=settings_test, llm=fake)
    close = PendingQuestion(key="close.anything_else", slots=[], kind="open")
    await turn(u, "No thank you, how long does it take", close)
    assert fake.calls == 1  # not a closing: the model listens (no fast goodbye)


def test_the_prompt_says_where_each_amount_goes() -> None:
    """The model gets the same reading as the parser, so the two agree instead of forcing a confirm."""
    from gatorplate.extract.prompt import SYSTEM_PROMPT

    for needle in ("my mom gives me 200", "let me check my rent", "1000 saved", "until I get paid",
                   "Give me a second", "450 from each of my 2", "in the summer"):
        assert needle in SYSTEM_PROMPT, needle
