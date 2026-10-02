"""Edge cases found in review: one amount never feeds two slots, amounts said by or for someone else, utility bills,
whole-home rent, Spanish price pairs, untrusted model values, written phone numbers, the Pacific day of the turn
cap, content-free logs, and a parser that never breaks a turn (docs/SPEC.md §3 and §8.7-§8.8)."""

from __future__ import annotations

import json
import logging
import random
import time
from decimal import Decimal
from typing import Any

import pytest

from gatorplate.clock import FixedClock
from gatorplate.contracts.common import Lang
from gatorplate.contracts.extraction import (
    ExtractionResult,
    ExtractOutcome,
    Intent,
    PendingQuestion,
    SlotObservation,
    Understanding,
)
from gatorplate.contracts.slots import SlotName
from gatorplate.extract import Understander
from gatorplate.extract.conversion import Conversion, in_range
from gatorplate.extract.llm.base import MemoryCounter
from gatorplate.extract.numbers import find_numbers
from gatorplate.extract.parser import Parsed, Parser
from gatorplate.extract.redact import Redactor
from tests.extract.support import DATA

S = SlotName
INCOME = PendingQuestion(key="ask.income", slots=[S.earned_monthly, S.other_cash_monthly], kind="number")
RENT = PendingQuestion(key="ask.rent", slots=[S.rent_share], kind="number")
CASH = PendingQuestion(key="expedited.intro_cash", slots=[S.cash_on_hand], kind="number")
RBO = PendingQuestion(key="flip.rent_paid_by_others", slots=[S.rent_paid_by_others_to_landlord], kind="yes_no")
OTHER_CASH = PendingQuestion(key="ask.other_cash", slots=[S.other_cash_monthly], kind="number")
# The SF State coordinator's public number (data/content/contacts.json), assembled at run time.
PHONE_PARENS = "(" + "415" + ") " + "338" + "-" + "1203"


def obs(parsed: Any) -> dict[str, tuple[str, str | None, str]]:
    return {o.slot.value: (o.value, o.period, o.state) for o in parsed.observations}


class Scripted:
    """A model stand-in that returns one fixed extraction and keeps the last user message it was sent."""

    provider = "scripted"
    model = "scripted"

    def __init__(self, observations: list[SlotObservation], *, lang: str = "en") -> None:
        self.result = ExtractionResult(observations=observations, intents=[], answered_pending="yes", lang=lang,
                                       side_question=None, requested_language=None)  # type: ignore[arg-type]
        self.sent: list[str] = []

    async def complete(self, system: str, user_json: str, schema: dict, timeout_s: float) -> ExtractOutcome:
        self.sent.append(user_json)
        return ExtractOutcome(status="ok", result=self.result, model=self.model)


def ob(slot: SlotName, value: str, quote: str, *, period: str | None = "month", hours: float | None = None,
       state: str = "clear") -> SlotObservation:
    return SlotObservation(slot=slot, value=value, period=period, hours_per_week=hours, state=state,  # type: ignore
                           quote=quote, quote_en=None)


async def turn(u: Understander, text: str, pending: PendingQuestion | None = INCOME, *,
               known: dict | None = None, recent: list[str] | None = None, closed_mode: bool = False,
               lang: Lang = Lang.en) -> Understanding:
    return await u.understand(text=text, masked=False, confidence=0.9, dtmf=None, pending=pending,
                              known=known or {}, recent=recent or [], last_prompt=None, lang=lang,
                              deadline=u.clock.monotonic() + 2.6, closed_mode=closed_mode)


# ------------------------------------------------------------------------------------------------ parser: who pays
@pytest.mark.parametrize(("text", "pending", "want"), [
    ("I get 300 from my mom and 200 from my dad", INCOME, {"other_cash_monthly": ("500", "month", "clear")}),
    ("my mom pays me 200 a month", INCOME, {"other_cash_monthly": ("200", "month", "clear")}),
    ("I make 1,200 every month and get 100 every week from my dad", INCOME,
     {"earned_monthly": ("1200", "month", "clear"), "other_cash_monthly": ("100", "week", "clear")}),
    ("my share is 1100 but my parents pay 300 of it", RENT, {"rent_share": ("1100", "month", "clear")}),
    ("I pay 1100 for rent and my roommate pays 1100", RENT, {"rent_share": ("1100", "month", "clear")}),
    ("Yeah, my mom pays 500 of it", RBO, {"rent_paid_by_others_to_landlord": ("500", "month", "clear")}),
    ("Yeah, mom pays 500", RBO, {"rent_paid_by_others_to_landlord": ("500", "month", "clear")}),
    ("Yeah, mom pays 500", RENT, {}),
    ("My parents paid 500 last month and I paid 600", RENT, {"rent_share": ("600", "month", "clear")}),
    ("I get paid 900 every two weeks", INCOME, {"earned_monthly": ("900", "biweek", "clear")}),
])
def test_money_said_by_or_for_someone_else(parser: Parser, text: str, pending: PendingQuestion,
                                           want: dict[str, tuple[str, str | None, str]]) -> None:
    got = {k: v for k, v in obs(parser.parse(text, pending, {S.rent_share: "1100"}, "en")).items()
           if k.endswith("_monthly") or k in ("rent_share", "rent_paid_by_others_to_landlord")}
    assert got == want


def test_someone_else_paying_is_never_the_students_own_amount(parser: Parser) -> None:
    for pending in (RENT, OTHER_CASH, INCOME):
        parsed = parser.parse("Mom pays 500", pending, {}, "en")
        assert parsed.observations == [] and not parsed.confident  # no fast path: the model decides


@pytest.mark.parametrize(("text", "value"), [
    ("my rent is 1100 and utilities are 100", "1100"),
    ("rent 1100 plus 100 utilities", "1100"),
    ("my rent with utilities is 1200", "1200"),
    ("1100 utilities included", "1100"),
    ("it's 1200 including utilities", "1200"),
])
def test_utility_bills_are_not_rent(parser: Parser, text: str, value: str) -> None:
    assert obs(parser.parse(text, RENT, {}, "en"))["rent_share"] == (value, "month", "clear")


def test_utility_bill_in_spanish(parser: Parser) -> None:
    got = obs(parser.parse("pago mil cien de renta y cien de luz", RENT, {}, "es"))
    assert got["rent_share"] == ("1100", "month", "clear")


@pytest.mark.parametrize(("text", "value", "state"), [
    ("we pay 3300 split three ways", "3300", "unclear"),  # never 3303 ("three ways" is not money)
    ("half of 2200", "2200", "unclear"),
    ("the whole apartment is 3300 and my share is 1100", "1100", "clear"),
    ("my half is 1100", "1100", "clear"),
    ("we pay 1100 each", "1100", "clear"),
    ("my roommates and I pay 1100 each", "1100", "clear"),
])
def test_whole_home_rent_is_not_a_clear_share(parser: Parser, text: str, value: str, state: str) -> None:
    assert obs(parser.parse(text, RENT, {}, "en"))["rent_share"] == (value, "month", state)


def test_two_rent_amounts_are_never_a_clear_sum(parser: Parser) -> None:
    assert obs(parser.parse("1100 for rent, 50 for parking", RENT, {}, "en"))["rent_share"][2] == "unclear"


def test_ssi_mentions_only_route(parser: Parser) -> None:
    for text in ("my SSI is 900 a month", "I get about 900 a month in SSI", "I get SSI, it's 900 a month"):
        got = obs(parser.parse(text, INCOME, {}, "en"))
        assert got == {"elderly_or_disabled": ("true", None, "clear")}, text


# ------------------------------------------------------------------------------------------------ numbers
def test_spanish_price_pair_keeps_the_cents_reading() -> None:
    (n,) = find_numbers("doce cincuenta", spanish=True)
    assert (n.value, n.alt, n.teen_ty) == (Decimal(1250), Decimal("12.50"), True)
    (n,) = find_numbers("diecinueve noventa y nueve", spanish=True)
    assert (n.value, n.alt) == (Decimal(1999), Decimal("19.99"))


@pytest.mark.parametrize(("text", "values"), [
    ("doscientos cincuenta", ["250"]),
    ("mil doscientos cincuenta", ["1250"]),
    ("diecinueve con cincuenta", ["19.5"]),
    ("tengo veinte, doce unidades", ["20", "12"]),
    ("dos mil", ["2000"]),
])
def test_spanish_numbers_that_are_not_pairs(text: str, values: list[str]) -> None:
    found = find_numbers(text, spanish=True)
    assert [str(n.value) for n in found] == values and all(n.alt is None for n in found)


def test_spanish_hourly_pair(parser: Parser) -> None:
    got = parser.parse("gano doce cincuenta la hora, veinte horas a la semana", INCOME, {}, "es")
    (earned,) = [o for o in got.observations if o.slot == S.earned_monthly]
    assert (earned.value, earned.period, earned.hours_per_week) == ("12.50", "hour", 20)


# ------------------------------------------------------------------------------------------------ redaction
@pytest.mark.parametrize("text", [
    f"You can reach me at {PHONE_PARENS}.",
    "my social is " + " - ".join(("123", "45", "6789")),
    "+1 " + PHONE_PARENS,
])
def test_written_numbers_with_parentheses_or_spaced_dashes(redactor: Redactor, text: str) -> None:
    red = redactor.redact(text)
    assert red.kinds == ["ssn"] and not any(ch.isdigit() for ch in red.text.replace("+1", ""))


@pytest.mark.parametrize("text", [
    "I make $900 - $1,100 a month", "rent is 1100 (1200 with utilities)", "between 1000 and 1200",
    "I'm 20 (21 in May) and take 12 units", "I applied on 10/02/2026",
])
def test_amounts_and_dates_stay(redactor: Redactor, text: str) -> None:
    assert redactor.redact(text).kinds == []


def test_masked_groups_are_one_removed_number(redactor: Redactor) -> None:
    red = redactor.redact("My social is ###-##-####, and my card is #### #### #### ####.", masked=True)
    assert red.text == "My social is [REDACTED], and my card is [REDACTED]."
    assert red.kinds == ["card_number"]  # the utterance names a card


async def test_parenthesized_phone_never_reaches_the_model(settings_test) -> None:
    model = Scripted([])
    u = Understander(settings=settings_test, llm=model)
    result = await turn(u, f"Call me at {PHONE_PARENS} if you need anything", RENT,
                        recent=[f"my number is {PHONE_PARENS}"])
    assert result.redactions == ["ssn"]
    sent = "".join(model.sent)
    assert model.sent and not any(part in sent for part in ("415", "338", "1203"))
    assert "415" not in result.redacted_text


# ------------------------------------------------------------------------------------------------ merge
async def test_one_amount_never_feeds_two_slots(settings_test) -> None:
    """The model files the amounts as cash from family; a parser reading of the same words as earnings is not
    added on top (that would count the money twice)."""
    text = "I get 300 from my mom and 200 from my dad"
    model = Scripted([ob(S.other_cash_monthly, "300", "300 from my mom"),
                      ob(S.other_cash_monthly, "200", "200 from my dad")])
    u = Understander(settings=settings_test, llm=model)
    misread = Parsed(observations=[ob(S.earned_monthly, "500", "300 from my mom and 200")])
    u.parser.parse = lambda *_a, **_k: misread  # type: ignore[method-assign]  # a parser that misfiles the amounts
    result = await turn(u, text)
    assert {o.slot.value: o.value for o in result.observations} == {"other_cash_monthly": "500"}


async def test_parser_keeps_a_pending_answer_the_model_missed(settings_test) -> None:
    """A parser reading whose words the model did not use stays (the pending question's own answer)."""
    text = "I work at the campus library, about 900 a month. Nobody gives me cash."
    model = Scripted([ob(S.earned_monthly, "900", "about 900 a month")])
    u = Understander(settings=settings_test, llm=model)
    result = await turn(u, text)
    assert {o.slot.value: o.value for o in result.observations} == {"earned_monthly": "900",
                                                                    "other_cash_monthly": "0"}


async def test_a_repeated_model_observation_is_one_amount(settings_test) -> None:
    same = ob(S.earned_monthly, "900", "900 a month")
    u = Understander(settings=settings_test, llm=Scripted([same, same]))
    result = await turn(u, "I make 900 a month at the library", closed_mode=False)
    assert [(o.slot.value, o.value) for o in result.observations] == [("earned_monthly", "900")]


@pytest.mark.parametrize("hours", [1e30, float("inf"), float("nan"), -5.0, 0.0, 500.0])
async def test_impossible_hours_from_the_model_never_break_a_turn(settings_test, hours: float) -> None:
    u = Understander(settings=settings_test, llm=Scripted([ob(S.earned_monthly, "18", "18 an hour", period="hour",
                                                              hours=hours)]))
    result = await turn(u, "I make 18 an hour, long hours")
    (earned,) = result.observations
    assert (earned.value, earned.period, earned.hours_per_week, earned.state) == ("18", "hour", None, "unclear")


async def test_ssi_amount_without_the_word_in_its_quote_is_dropped(settings_test) -> None:
    model = Scripted([ob(S.unearned_monthly, "900", "it's 900 a month"),
                      ob(S.elderly_or_disabled, "true", "I get SSI", period=None)])
    u = Understander(settings=settings_test, llm=model)
    result = await turn(u, "I get SSI, it's 900 a month")
    assert [(o.slot.value, o.value, o.quote) for o in result.observations] == [("elderly_or_disabled", "true", "")]


async def test_status_the_model_missed_still_routes(settings_test) -> None:
    """The parser's routing-only reading is a backstop: the dialogue needs it to route the case and to drop that
    utterance from short-term memory, even when the model returned other facts only. Its quote is never kept."""
    model = Scripted([ob(S.rent_share, "975", "my part of the rent is 975")])
    u = Understander(settings=settings_test, llm=model)
    result = await turn(u, "I'm undocumented, and my part of the rent is 975.", RENT)
    got = {o.slot.value: (o.value, o.quote, o.quote_en) for o in result.observations}
    assert got["rent_share"][0] == "975"
    assert got["volunteered_status"] == ("undocumented", "", None)


async def test_other_benefits_next_to_ssi_stay_when_both_readers_agree(settings_test) -> None:
    model = Scripted([ob(S.unearned_monthly, "200", "child support 200")])
    u = Understander(settings=settings_test, llm=model)
    result = await turn(u, "I get SSI and child support 200 a month")
    assert ("unearned_monthly", "200") in [(o.slot.value, o.value) for o in result.observations]


async def test_all_of_it_grounds_only_on_the_known_rent_share(settings_test) -> None:
    model = Scripted([ob(S.rent_paid_by_others_to_landlord, "900", "All of it")])
    u = Understander(settings=settings_test, llm=model)
    result = await turn(u, "All of it.", RBO, known={S.earned_monthly: "900", S.rent_share: "1100"})
    assert all(o.value != "900" for o in result.observations)
    model = Scripted([ob(S.rent_paid_by_others_to_landlord, "1100", "All of it")])
    u = Understander(settings=settings_test, llm=model)
    result = await turn(u, "All of it.", RBO, known={S.earned_monthly: "900", S.rent_share: "1100"})
    assert [(o.slot.value, o.value) for o in result.observations] == [("rent_paid_by_others_to_landlord", "1100")]


# ------------------------------------------------------------------------------------------------ conversion
def test_conversion_matches_the_rules_table_examples() -> None:
    table = json.loads((DATA / "rules" / "ca_fy2027.json").read_text(encoding="utf-8"))["conversion"]
    conv = Conversion.load(DATA / "rules" / "ca_fy2027.json")
    for example in table["examples"]:
        basis = example["basis"]
        assert conv.monthly(basis["amount"], basis["period"], basis["hours_per_week"]) == Decimal(example["monthly"])


@pytest.mark.parametrize(("value", "hours"), [("1e40", None), ("NaN", None), ("18", "1e30"), ("Infinity", None)])
def test_conversion_cannot_tell_rather_than_raise(value: str, hours: str | None) -> None:
    conv = Conversion.load(DATA / "rules" / "ca_fy2027.json")
    period = "hour" if hours else "month"
    assert conv.monthly(value, period, Decimal(hours) if hours else None) is None
    assert in_range(S.earned_monthly, value, period, Decimal(hours) if hours else None, conv) is None


# ------------------------------------------------------------------------------------------------ service
async def test_a_parser_bug_never_breaks_a_turn(settings_test, caplog: pytest.LogCaptureFixture) -> None:
    u = Understander(settings=settings_test, llm=Scripted([ob(S.rent_share, "950", "nine fifty a month")]))

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("parser bug")

    u.parser.parse = broken  # type: ignore[method-assign]
    text = "My rent is about nine fifty a month, I think."
    with caplog.at_level(logging.DEBUG):
        result = await turn(u, text, RENT)
    assert result.llm.status == "ok" and result.observations  # the model still listened
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "parser_error" in logged and "nine fifty" not in logged and "950" not in logged


async def test_unknown_known_keys_are_ignored(settings_test) -> None:
    u = Understander(settings=settings_test)
    result = await turn(u, "eleven hundred", RENT, known={"not_a_slot": "x", S.age: "20"})  # type: ignore[dict-item]
    assert [(o.slot.value, o.value) for o in result.observations] == [("rent_share", "1100")]


async def test_turn_cap_counts_the_pacific_day(settings_test) -> None:
    """23:30 PT on Friday is already Saturday in UTC: it is still Friday's count."""
    clock = FixedClock.pacific(2026, 10, 2, 10, 0)
    counter = MemoryCounter()
    u = Understander(settings=settings_test.model_copy(update={"llm_daily_turn_cap": 2}), counters=counter,
                     clock=clock)
    text = "My rent is about nine fifty a month, I think."
    assert (await turn(u, text, RENT)).llm.status == "ok"
    clock.advance(hours=13, minutes=30)  # 23:30 PT, 06:30 UTC on Saturday
    assert clock.today().isoformat() == "2026-10-02"
    assert (await turn(u, text, RENT)).llm.status == "ok"
    assert (await turn(u, text, RENT)).llm.status == "skipped"  # the third turn of the same Pacific day
    clock.advance(minutes=31)  # 00:01 PT on Saturday
    assert (await turn(u, text, RENT)).llm.status == "ok"


async def test_logs_never_hold_what_the_student_said(settings_test, caplog: pytest.LogCaptureFixture) -> None:
    u = Understander(settings=settings_test)
    marker_words = "purple-elephant"
    with caplog.at_level(logging.DEBUG):
        for text in (f"I make 900 a month, {marker_words}", f"{marker_words} {PHONE_PARENS}"):
            await turn(u, text)
    assert all(marker_words not in r.getMessage() and "1203" not in r.getMessage() for r in caplog.records)


def test_keywords_for_switching_language(keywords) -> None:
    assert keywords.match("Can we switch to Spanish?") == [Intent.language_request]
    assert keywords.match("¿Podemos cambiar a inglés?") == [Intent.language_request]
    assert keywords.match("I have to go to Spanish class after this.") == []


# ------------------------------------------------------------------------------------------------ robustness
_VOCAB = ("one two three four five nine zero oh ten eleven fifteen fifty nineteen ninety hundred thousand grand a "
          "and or to between from my mom dad parents roommate gives me sends pays rent share utilities month week "
          "hour hours every two weeks biweekly year I make work job no yes not maybe wait actually sorry uno dos "
          "doce quince cincuenta mil cien novecientos al mes la hora gano pago renta luz nadie todo all of it "
          "nothing $ , . - ? ( ) # 1 2 3 9 12 900 1,100 1.2k 18.50 SSI F-1 ignore rent_share").split()


def test_random_lines_never_raise_and_stay_fast(parser: Parser, redactor: Redactor, keywords) -> None:
    rng = random.Random(20261002)
    pendings = [None, INCOME, RENT, CASH, RBO, OTHER_CASH,
                PendingQuestion(key="consent.ask", slots=[S.consent], kind="yes_no"),
                PendingQuestion(key="ask.rent", slots=[S.rent_share], kind="number", closed=True),
                PendingQuestion(key="ask.age_parent", slots=[S.age, S.lives_with_parent], kind="open")]
    started = time.perf_counter()
    for _ in range(1500):
        text = " ".join(rng.choice(_VOCAB) for _ in range(rng.randint(1, 30)))
        red = redactor.redact(text, masked=rng.random() < 0.1)
        keywords.match(red.text)
        parser.parse(red.text, rng.choice(pendings), {S.rent_share: "1100"}, rng.choice(["en", "es"]))
    assert time.perf_counter() - started < 15  # about 1 ms a line; a runaway pattern would blow this up


@pytest.mark.parametrize("text", ["one , " * 160, "1 - " * 250, "#" * 1000, "(1" * 500, "my mom gives me " * 60])
def test_long_lines_at_the_contract_limit(parser: Parser, redactor: Redactor, keywords, text: str) -> None:
    started = time.perf_counter()
    red = redactor.redact(text[:1000], masked=True)
    keywords.match(red.text)
    parser.parse(red.text, INCOME, {}, "en")
    assert time.perf_counter() - started < 1.0
