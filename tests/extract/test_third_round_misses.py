"""Misreadings found by the third verification round (fresh rewordings of the adversarial and simulated-student
probes), each pinned by the smallest check that would have caught it: the rule parser alone (the path closed mode,
model timeouts and the fake model use), the input guard, and one understanding turn.

The rules behind them:
- An answer to one question never erases an amount said to another: a zero phrase said while another question is
  pending fills only a slot not answered yet ("No, no rent help from anybody", "my mom is not working", "nadie me da
  dinero para la renta"); "nobody gives me money for that" is about the question asked.
- The student paying the landlord ("I pay my landlord 1100", "mi casero me cobra mil cien") is the student's own rent.
- When the student gets paid is a time, and one paycheck to come is no monthly pay.
- The same money said again ("that's about 225 a week"), a part of it ("300 of that is tips") and net pay said with
  gross pay are never added on top.
- Unsure ("No, I'm not sure", "No, no estoy segura") is never a no.
- "Nobody but me", "Just me", "Solo yo" to the landlord question are a no.
- A done phrase that says more goes to the model; crisis statements reworded are still caught without a model.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from gatorplate.contracts.common import Lang
from gatorplate.contracts.extraction import Intent, PendingQuestion
from gatorplate.contracts.slots import SlotName
from gatorplate.extract import Understander
from gatorplate.extract.keywords import KeywordMatcher
from gatorplate.extract.llm.fake import FakeLLM
from gatorplate.extract.parser import Parser
from gatorplate.extract.text import guess_lang, normalize

S = SlotName
RBO = PendingQuestion(key="flip.rent_paid_by_others", slots=[S.rent_paid_by_others_to_landlord], kind="yes_no")
HEAT = PendingQuestion(key="flip.heat_cool", slots=[S.heat_cool], kind="yes_no")
CASH = PendingQuestion(key="expedited.intro_cash", slots=[S.cash_on_hand], kind="number")
RENT = PendingQuestion(key="ask.rent", slots=[S.rent_share], kind="number")
INCOME = PendingQuestion(key="ask.income", slots=[S.earned_monthly, S.other_cash_monthly], kind="number")
UNITS_CLOSED = PendingQuestion(key="ask.units", slots=[S.half_time], kind="yes_no", closed=True)
HOUSEHOLD = PendingQuestion(key="ask.household", slots=[S.household_food], kind="open")
AGE = PendingQuestion(key="ask.age_parent", slots=[S.age, S.lives_with_parent], kind="open")
CLOSE = PendingQuestion(key="close.anything_else", slots=[], kind="open")
FAMILY_CASH = {S.rent_share: "1100.00", S.other_cash_monthly: "300.00", S.earned_monthly: "1200.00"}
MARIA = {S.rent_share: "1100.00", S.other_cash_monthly: "0.00", S.earned_monthly: "900.00"}
ABSENT = None


def read(parser: Parser, text: str, pending: PendingQuestion, known: dict | None = None) -> dict[SlotName, str]:
    parsed = parser.parse(normalize(text), pending, known or {}, guess_lang(text))
    return {o.slot: o.value for o in parsed.observations}


def check(got: dict[SlotName, str], want: dict[SlotName, str | None]) -> None:
    for slot, value in want.items():
        if value is None:
            assert slot not in got, (slot, got)
        else:
            assert slot in got, (slot, got)
            try:
                assert Decimal(got[slot]) == Decimal(value), (slot, got)
            except ArithmeticError:
                assert got[slot] == value, (slot, got)


async def turn(u: Understander, text: str, pending: PendingQuestion, known: dict | None = None,
               lang: Lang = Lang.en) -> Any:
    return await u.understand(text=text, masked=False, confidence=0.9, dtmf=None, pending=pending,
                              known=known or {}, recent=[], last_prompt=None, lang=lang,
                              deadline=u.clock.monotonic() + 2.6, closed_mode=False)


# ------------------------------------------------------------------------------------------ an answer to another question
@pytest.mark.parametrize("pending,text,want", [
    (RBO, "No, nobody gives me money for that, I pay it myself.", {S.other_cash_monthly: ABSENT}),
    (RBO, "No. Nobody gives me any money toward it.", {S.other_cash_monthly: ABSENT}),
    (RBO, "No, nobody helps me out with money for rent.", {S.other_cash_monthly: ABSENT}),
    (RBO, "No, my mom doesn't give me money for the rent, she sends it for food.", {S.other_cash_monthly: ABSENT}),
    (RBO, "No, nobody gives me cash to pay the landlord.", {S.other_cash_monthly: ABSENT}),
    (RBO, "No, nadie me da dinero para la renta.", {S.other_cash_monthly: ABSENT}),
    (RBO, "No, mis papás no me dan dinero para la renta, solo para comida.", {S.other_cash_monthly: ABSENT}),
    (RBO, "No, nadie me ayuda con dinero para la renta.", {S.other_cash_monthly: ABSENT}),
    (HEAT, "No, it's included. Nobody gives me money for that.", {S.other_cash_monthly: ABSENT}),
    (HEAT, "No, nadie me da dinero para la calefacción, está incluida.", {S.other_cash_monthly: ABSENT}),
    (RBO, "No, no rent help from anybody.", {S.rent_share: ABSENT, S.rent_paid_by_others_to_landlord: "0"}),
    (RBO, "No, I get no rent assistance.", {S.rent_share: ABSENT}),
    (HEAT, "No, it's in the rent. The heat is not working anyway.", {S.earned_monthly: ABSENT}),
])
def test_an_answer_to_another_question_never_erases_family_cash_rent_or_pay(parser: Parser, pending, text, want):
    check(read(parser, text, pending, FAMILY_CASH), want)


@pytest.mark.parametrize("pending,text,want", [
    (RBO, "No, my mom is not working right now, so she can't.", {S.earned_monthly: ABSENT}),
    (RBO, "No, mis papás están sin trabajo.", {S.earned_monthly: ABSENT}),
    (RBO, "No, my dad has no job right now.", {S.earned_monthly: ABSENT}),
    (CASH, "Right now nothing.", {S.earned_monthly: ABSENT, S.cash_on_hand: "0"}),
    (CASH, "Like 80 bucks, I'm not working this week.", {S.earned_monthly: ABSENT, S.cash_on_hand: "80"}),
])
def test_someone_elses_job_or_this_week_is_never_the_students_pay(parser: Parser, pending, text, want):
    check(read(parser, text, pending, MARIA), want)


@pytest.mark.parametrize("text,want", [
    ("I'm not working right now, nobody gives me money.", {S.earned_monthly: "0", S.other_cash_monthly: "0"}),
    ("Right now nothing.", {S.earned_monthly: "0"}),
    ("No job.", {S.earned_monthly: "0"}),
    ("Ahorita no trabajo, nadie me da dinero.", {S.earned_monthly: "0", S.other_cash_monthly: "0"}),
    ("I make 900 a month, nobody gives me cash.", {S.earned_monthly: "900", S.other_cash_monthly: "0"}),
])
def test_the_students_own_zero_still_answers_the_income_question(parser: Parser, text, want):
    check(read(parser, text, INCOME), want)


# ------------------------------------------------------------------------------------------ the landlord
@pytest.mark.parametrize("text,rent", [
    ("I pay my landlord 1100 a month.", "1100"), ("My landlord charges me eleven hundred.", "1100"),
    ("The landlord wants 1100 from me.", "1100"), ("I give my landlord eleven hundred every month.", "1100"),
    ("Le pago 1100 al dueño.", "1100"), ("Mi casero me cobra mil cien.", "1100"),
    ("My landlord gives me a break, I pay a thousand.", "1000"),
])
def test_the_student_paying_the_landlord_is_the_rent_share(parser: Parser, text: str, rent: str) -> None:
    check(read(parser, text, RENT, {S.earned_monthly: "900.00"}),
          {S.rent_share: rent, S.rent_paid_by_others_to_landlord: ABSENT})


# ------------------------------------------------------------------------------------------ cash and pay day
@pytest.mark.parametrize("text,cash", [
    ("About sixty dollars, I get paid on the first.", "60"),
    ("I have like 30 dollars left until my paycheck on the 15th.", "30"),
    ("About forty dollars, I get paid 450 next Friday.", "40"),
    ("About forty dollars until I get paid.", "40"),
])
def test_when_the_student_gets_paid_never_becomes_the_pay(parser: Parser, text: str, cash: str) -> None:
    check(read(parser, text, CASH, MARIA), {S.cash_on_hand: cash, S.earned_monthly: ABSENT})


# ------------------------------------------------------------------------------------------ one amount said twice
@pytest.mark.parametrize("text,value", [
    ("I make 900 a month, that's about 225 a week.", "900"), ("About 900 a month, 300 of that is tips.", "900"),
    ("I make 1000 a month gross, 900 net.", "1000"), ("600 at the library and 300 at the cafe.", "900"),
])
def test_a_restatement_a_part_or_net_pay_is_never_added(parser: Parser, text: str, value: str) -> None:
    check(read(parser, text, INCOME), {S.earned_monthly: value})


def test_pay_from_a_job_is_never_family_cash(parser: Parser) -> None:
    check(read(parser, "My job gives me about 900 a month.", INCOME),
          {S.earned_monthly: "900", S.other_cash_monthly: ABSENT})


# ------------------------------------------------------------------------------------------ unsure, only me, a spouse
@pytest.mark.parametrize("text", ["No, I'm not sure.", "Not really sure.", "No, no estoy segura.",
                                  "No sabría decirte.", "No, no me acuerdo."])
def test_unsure_is_never_a_no(parser: Parser, text: str) -> None:
    parsed = parser.parse(normalize(text), UNITS_CLOSED, {}, guess_lang(text))
    assert parsed.answer is None and S.half_time not in {o.slot for o in parsed.observations}
    assert Intent.dont_know in parsed.intents


@pytest.mark.parametrize("text", ["Nobody but me.", "No one except me.", "Only me.", "Just me.", "Not anyone.",
                                  "Solo yo.", "Yo nada más.", "Nomás yo.", "Nadie más que yo."])
def test_only_me_to_the_landlord_question_is_a_no(parser: Parser, text: str) -> None:
    check(read(parser, text, RBO, MARIA), {S.rent_paid_by_others_to_landlord: "0", S.household_food: ABSENT})


def test_nobody_but_a_parent_is_not_a_no(parser: Parser) -> None:
    check(read(parser, "Nobody but my mom.", RBO, MARIA), {S.rent_paid_by_others_to_landlord: ABSENT})


@pytest.mark.parametrize("pending,text,want", [
    (AGE, "I'm 23 and married.", {S.age: "23", S.spouse: "true"}),
    (HOUSEHOLD, "Just the two of us, me and my wife. She works, she's not a student.",
     {S.household_food: "alone", S.spouse: "true"}),
    (HOUSEHOLD, "Vivo con mi mujer.", {S.spouse: "true", S.household_food: "alone"}),
    (AGE, "Tengo 23 y vivo con mi mujer.", {S.age: "23", S.spouse: "true", S.lives_with_parent: "false"}),
])
def test_a_spouse_said_plainly(parser: Parser, pending, text, want) -> None:
    check(read(parser, text, pending), want)


# ------------------------------------------------------------------------------------------ status and home said briefly
@pytest.mark.parametrize("pending,text,want", [
    (INCOME, "Nine hundred, undocumented.", {S.volunteered_status: "undocumented", S.earned_monthly: "900"}),
    (AGE, "20, F-1 visa.", {S.volunteered_status: "F-1", S.age: "20"}),
    (CLOSE, "That's all. I'm actually undocumented.", {S.volunteered_status: "undocumented"}),
    (CLOSE, "Nada más, pero tengo visa de estudiante.", {S.volunteered_status: "F-1"}),
    (AGE, "My roommate is on a student visa, I'm 20.", {S.volunteered_status: ABSENT}),
    (AGE, "Seventeen, with mom.", {S.age: "17", S.lives_with_parent: "true"}),
])
def test_a_status_or_a_parent_said_briefly(parser: Parser, pending, text, want) -> None:
    check(read(parser, text, pending), want)


# ------------------------------------------------------------------------------------------ crisis and the close
CRISIS = [
    "I'm going to hang myself.", "I'm going to jump off a bridge.",
    "I have pills saved up and I'm going to take them all.", "I've been thinking about taking my own life.",
    "Maybe I should just end it.", "I'm thinking about ending things.", "I want it all to be over.",
    "Nobody would care if I died.", "Nobody would miss me if I was gone.", "I wrote a goodbye note to my family.",
    "I'm so tired of being alive.", "I'm tired of living.", "I wish I'd never been born.",
    "I don't want to go on living.", "I feel hopeless, like there's no way out except dying.",
    "I keep thinking everyone would be happier if I were dead.", "That's all. Honestly I'm tired of living.",
    "No, that's it. I'm going to end it tonight.", "No. Wanna die.", "Nope, kill me.", "No. Want death.",
    "Me quiero ahorcar.", "Me voy a tirar de un puente.", "Tengo pastillas guardadas para tomármelas todas.",
    "Estoy cansada de vivir.", "La vida ya no tiene sentido.", "Ya no le encuentro sentido a la vida.",
    "Mejor me muero.", "Nadie me extrañaría si me muero.", "Quisiera dormir y no despertar nunca.",
    "Ya no aguanto más, quiero que todo termine.", "Sería mejor si yo no estuviera.",
]
NOT_CRISIS = [
    "I just want to disappear for the weekend, finals are brutal.", "Quiero desaparecer de las redes un rato.",
    "I can't go on, I have class at three. I make about 900.",
    "There's no point in going on with this question, I make 900.",
    "I don't want to wake up tomorrow at six for the interview, but okay, 900 a month.",
    "I'm done with life admin for today, I make 900 a month.", "No quiero despertarme el sábado, pero gano 900 al mes.",
    "My mom will kill me if I don't apply.", "I'm tired of living with my parents.",
    "I'm sick of living paycheck to paycheck.", "No, let's end it here, thanks.",
]


@pytest.mark.parametrize("text", CRISIS)
def test_reworded_crisis_statements_are_caught_without_a_model(keywords: KeywordMatcher, text: str) -> None:
    assert Intent.crisis in keywords.match(text)


@pytest.mark.parametrize("text", NOT_CRISIS)
def test_ordinary_lines_with_crisis_words_are_not_a_crisis(keywords: KeywordMatcher, text: str) -> None:
    assert Intent.crisis not in keywords.match(text)


@pytest.mark.parametrize("text,lang", [
    ("No, that's all. Thanks!", "en"), ("Nope, that should do it. Thanks!", "en"), ("No, I'm all good here.", "en"),
    ("I think I'm set, thanks.", "en"), ("No, you've been super helpful.", "en"), ("Eso es todo, gracias.", "es"),
    ("Por ahora no, gracias.", "es"), ("Gracias, eso es todo por hoy.", "es"),
])
def test_a_plain_closing_is_only_a_done_phrase(keywords: KeywordMatcher, text: str, lang: str) -> None:
    assert keywords.is_only_done(text, lang)


@pytest.mark.parametrize("text,lang", [
    ("That's all. Oh, I forgot, I'm a grad student.", "en"), ("No thanks, my roommate wants to know if she can apply",
                                                             "en"),
    ("Nothing else. My roommate moved out so I pay the whole 2200 now.", "en"),
    ("Nada más. Estoy cansada de vivir.", "es"), ("No, gracias, necesito llevar mi contrato", "es"),
])
def test_a_done_phrase_that_says_more_is_not_a_plain_closing(keywords: KeywordMatcher, text: str, lang: str) -> None:
    assert not keywords.is_only_done(text, lang)


async def test_a_done_phrase_that_says_more_goes_to_the_model(settings_test) -> None:
    fake = FakeLLM()
    u = Understander(settings=settings_test, llm=fake)
    result = await turn(u, "No, that's all. Thanks!", CLOSE)
    assert fake.calls == 0 and result.answered_pending == "yes"
    await turn(u, "That's all. Oh, I forgot, I'm a grad student.", CLOSE)
    await turn(u, "No, gracias. Por cierto, tengo visa de estudiante.", CLOSE, lang=Lang.es)
    assert fake.calls == 2
