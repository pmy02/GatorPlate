"""Answers that arrive at an unexpected moment (verification findings of the simulated-student and adversarial runs).

- A hold phrase and an answer in one breath ("One sec... okay, it's eleven hundred."): the answer is handled as an
  answer — read back (docs/SPEC.md §3.4), confirmed when needed, then the next question — never applied silently
  behind `hold.ok`. A hold phrase that brings nothing new still holds the line (docs/SPEC.md §3.3 row 8).
- On-campus housing said after the age question (in the household or the rent answer): `ask.meal_plan` is still asked
  before the result (docs/SPEC.md §3.2 phase 2, §4.3 row 3.12), and more than ten meals a week goes straight to
  `other_help.dorm_meal_plan` — never a silent "likely" estimate.
- A confirmed critical amount corrected later with a teen word ("Actually it's fourteen hundred."): the slot's one
  explicit confirm is used, so there is no second confirm, but the new value is read back (docs/SPEC.md §3.3
  corrections, §3.4) and stays unclear with one yellow line that shows it. The confirmed amount said again stays
  confirmed (a hold phrase with it still holds).
- A done phrase at the close question with something after it ("Nothing else. Actually my rent is twelve hundred.",
  "No thanks, I'm on an F-1 visa."): the correction is applied and read back, the volunteered status routes and its
  result is said, and the close question comes again — never a goodbye that drops it (docs/SPEC.md §3.2, §3.3).
"""

from __future__ import annotations

import pytest

from gatorplate.contracts.common import Phase, SlotState, Tier
from gatorplate.contracts.slots import SlotName
from tests.dialogue.support import FakeUnderstanding
from tests.dialogue.test_global_intents import at, keys, x
from tests.dialogue.test_review import maria

S = SlotName
HOLD_AND_ANSWER = "One sec... okay, it's eleven hundred."
LEVEL = "I'm an SF State undergrad, a junior, and I'm taking 12 units."
# The understanding's output for these lines (gatorplate/extract: the parser and the fake model agree): a teen word
# sets teen_ty (the fake understanding reads it from the quote), "Actually" is a correction, "One sec" a hold.
RENT_1300 = {"Thirteen hundred.": x(("rent_share", "1300", "month", "Thirteen hundred"))}
EARNED_1300 = {"I make thirteen hundred a month, nobody gives me cash.": x(
    ("earned_monthly", "1300", "month", "thirteen hundred"), ("other_cash_monthly", "0", "month", "nobody gives me"))}


def asked(case) -> list[str]:
    return [a.key for a in case.asked]


def lines(case, code: str) -> list:
    return [y for y in case.yellow_lines if y.code == code]


# ------------------------------------------------------------------------------------------ a hold phrase + an answer

async def test_a_hold_phrase_with_the_rent_answer_reads_the_rent_back(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        HOLD_AND_ANSWER: x(("rent_share", "1100", "month", "eleven hundred"))}))
    await at(rig, "ask.rent")
    reply = await rig.say(HOLD_AND_ANSWER)
    assert "hold.ok" not in keys(reply) and reply.hold_s == 0
    assert keys(reply) == ["readback.rent", "flip.intro", "flip.rent_paid_by_others"]
    assert rig.case().slots[S.rent_share].value == "1100.00"


async def test_a_hold_phrase_never_changes_a_confirmed_amount_silently(rig_factory) -> None:
    """The live call: earnings confirmed at $900, then at the age question "One sec... okay, it's eleven hundred."
    The new amount is read back (the student hears it and can correct it), and the age question follows."""
    level_and_pay = "I'm an SF State undergrad, 12 units, and I make about nine hundred a month."
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        level_and_pay: x(("level", "undergrad"), ("units", "12"), ("earned_monthly", "900", "month", "nine hundred")),
        "Yes, nine hundred.": x(("earned_monthly", "900", "month", "nine hundred")),
        HOLD_AND_ANSWER: x(("earned_monthly", "1100", "month", "eleven hundred"))}))
    await rig.start()
    await rig.say("Yes, that's fine.")
    assert keys(await rig.say(level_and_pay, confidence=0.6)) == ["confirm.money"]
    assert keys(await rig.say("Yes, nine hundred."))[-1] == "ask.age_parent"
    assert rig.case().slots[S.earned_monthly].confirmed
    reply = await rig.say(HOLD_AND_ANSWER)
    assert "hold.ok" not in keys(reply) and reply.hold_s == 0
    assert keys(reply)[0] == "readback.earned"
    # the age question follows in the same reply, or in the next part when the reply is split for the word budget
    assert (keys(reply) + rig.session().deferred_keys)[-1] == "ask.age_parent"
    item = rig.case().slots[S.earned_monthly]
    assert item.value == "1100.00" and item.changed_from == "900.00" and not item.confirmed


async def test_a_hold_phrase_that_says_nothing_new_still_holds(rig_factory) -> None:
    said_again = "Hold on, I make 900 a month, let me check my rent."
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        said_again: x(("earned_monthly", "900", "month", "900 a month"))}))
    await at(rig, "ask.rent")
    reply = await rig.say(said_again)
    assert keys(reply) == ["hold.ok"] and reply.hold_s == 30 and reply.ask is None
    assert rig.session().pending.key == "ask.rent"


async def test_a_hold_phrase_with_a_correction_at_the_close_reads_it_back(rig_factory) -> None:
    correction = "Hold on, actually I make 2000 a month."
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        correction: x(("earned_monthly", "2000", "month", "2000 a month"), intents=["correction"])}))
    await maria(rig, 8)
    reply = await rig.say(correction)
    assert "hold.ok" not in keys(reply) and reply.hold_s == 0
    assert keys(reply)[:2] == ["readback.earned", "result.likely"]
    assert rig.case().slots[S.earned_monthly].changed_from == "900.00"


# ------------------------------------------------------------------------------------------ on-campus housing said late

async def test_a_dorm_said_in_the_household_answer_still_gets_the_meal_plan_question(rig_factory) -> None:
    household = "I live alone in the campus dorm, and I buy my own food."
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "I'm 18 and I live on my own.": x(("age", "18"), ("lives_with_parent", "false")),
        household: x(("dorm_on_campus", "true"), ("household_food", "alone"))}))
    await rig.start()
    await rig.say("Yes, that's fine.")
    await rig.say(LEVEL)
    assert keys(await rig.say("I'm 18 and I live on my own."))[-1] == "ask.household"
    assert keys(await rig.say(household))[-1] == "ask.meal_plan"
    reply = await rig.say("I have the 14-meal plan.")
    assert keys(reply)[0] == "result.other_help.dorm_meal_plan"
    case = rig.case()
    assert case.tier == Tier.other_help and case.reason_code == "other_help.dorm_meal_plan"
    assert case.estimate_monthly is None
    assert "ask.meal_plan" in asked(case) and "ask.income" not in asked(case)


async def test_a_late_meal_plan_answer_over_ten_goes_straight_to_the_result(rig_factory) -> None:
    """The dorm alone (no answer to the household question yet): the meal plan comes first, and more than ten meals a
    week ends the questions at once — the household question is not asked after it."""
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "I'm 18 and I live on my own.": x(("age", "18"), ("lives_with_parent", "false")),
        "I live in the campus dorm.": x(("dorm_on_campus", "true"))}))
    await rig.start()
    await rig.say("Yes, that's fine.")
    await rig.say(LEVEL)
    await rig.say("I'm 18 and I live on my own.")
    assert keys(await rig.say("I live in the campus dorm."))[-1] == "ask.meal_plan"
    reply = await rig.say("I have the 14-meal plan.")
    assert keys(reply)[0] == "result.other_help.dorm_meal_plan"
    assert asked(rig.case()).count("ask.household") == 1  # asked once, before the dorm came up


async def test_a_dorm_said_at_the_rent_question_asks_the_meal_plan_before_the_result(rig_factory) -> None:
    no_rent = "I don't pay rent, I live in the campus dorm."
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        no_rent: x(("rent_share", "0", "month", "I don't pay rent"), ("dorm_on_campus", "true"))}))
    await at(rig, "ask.rent")
    reply = await rig.say(no_rent)
    assert keys(reply)[-1] == "ask.meal_plan"
    assert rig.session().phase in (Phase.housing, Phase.flip)
    after = await rig.say("Ten meals a week.")  # ten or fewer: the estimate goes on
    assert "ask.meal_plan" not in keys(after)
    assert rig.case().reason_code != "other_help.dorm_meal_plan"
    assert asked(rig.case()).count("ask.meal_plan") == 1


async def test_the_spanish_dorm_regression_asks_the_meal_plan(rig_factory) -> None:
    """The simulated student p30 (web, Spanish): the dorm came with the household answer, after the age question."""
    age = "Tengo 18 años y vivo solo."
    household = "Vivo solo en la residencia del campus y compro mi comida por separado."
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "Sí, está bien.": x(("consent", "true"), lang="es"),
        "Estudio licenciatura en SF State, con 12 unidades.": x(("level", "undergrad"), ("units", "12"), lang="es"),
        age: x(("age", "18"), ("lives_with_parent", "false"), lang="es"),
        household: x(("dorm_on_campus", "true"), ("household_food", "alone"), lang="es")}))
    await rig.start(channel="web", lang="es")
    await rig.say("Sí, está bien.")
    await rig.say("Estudio licenciatura en SF State, con 12 unidades.")
    assert keys(await rig.say(age))[-1] == "ask.household"
    assert keys(await rig.say(household))[-1] == "ask.meal_plan"
    reply = await rig.say("Tengo el plan de catorce comidas a la semana.")
    assert keys(reply)[0] == "result.other_help.dorm_meal_plan"
    assert rig.case().reason_code == "other_help.dorm_meal_plan"


# ------------------------------------------------------------------------------------------ a confirmed amount corrected

CORRECTIONS_AT_THE_FLIP = [
    pytest.param("Actually it's fourteen hundred.", ["correction"], id="actually"),
    pytest.param("One sec... Actually it's fourteen hundred.", ["correction", "hold"], id="hold-phrase"),
    pytest.param("Actually my rent is fourteen hundred.", ["correction"], id="my-rent-is"),
]


@pytest.mark.parametrize(("text", "intents"), CORRECTIONS_AT_THE_FLIP)
async def test_a_teen_word_correction_of_a_confirmed_rent_is_read_back(rig_factory, text: str,
                                                                      intents: list[str]) -> None:
    """Rent $1,300 confirmed, then at the flip "Actually it's fourteen hundred.": the one confirm is used, so the new
    value is read back (never a bare "Got it."), stays unclear with a yellow line, and the flip is asked again."""
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        **RENT_1300, text: x(("rent_share", "1400", "month", "fourteen hundred"), intents=intents)}))
    await at(rig, "ask.rent")
    assert keys(await rig.say("Thirteen hundred.")) == ["confirm.money"]
    assert keys(await rig.say("Yes."))[-1] == "flip.rent_paid_by_others"
    assert rig.case().slots[S.rent_share].confirmed
    reply = await rig.say(text)
    assert keys(reply) == ["readback.rent", "flip.rent_paid_by_others"]
    assert reply.hold_s == 0 and "fourteen hundred" in reply.say
    case = rig.case()
    item = case.slots[S.rent_share]
    assert (item.value, item.state, item.changed_from, item.confirmed) == ("1400.00", SlotState.unclear, "1300.00",
                                                                          False)
    found = lines(case, "unclear.rent_share")
    assert len(found) == 1 and found[0].assumed == "$1,400/mo"
    assert rig.session().confirms[S.rent_share] == 1  # still the one explicit confirm


@pytest.mark.parametrize("text", ["Actually I make fourteen hundred a month.",
                                  "Sorry, I meant fourteen hundred a month from work.",
                                  "Actually I make fifteen hundred a month."])
async def test_a_teen_word_correction_of_confirmed_earnings_is_read_back(rig_factory, text: str) -> None:
    amount = "1500" if "fifteen" in text else "1400"
    words = "fifteen hundred" if "fifteen" in text else "fourteen hundred"
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        **EARNED_1300, text: x(("earned_monthly", amount, "month", words), intents=["correction"])}))
    await at(rig, "ask.income")
    assert keys(await rig.say("I make thirteen hundred a month, nobody gives me cash.")) == ["confirm.money"]
    assert keys(await rig.say("Yes."))[-1] == "ask.rent"
    reply = await rig.say(text)
    assert keys(reply) == ["readback.earned", "ask.rent"]
    assert words in reply.say
    item = rig.case().slots[S.earned_monthly]
    assert (item.value, item.state, item.changed_from) == (f"{amount}.00", SlotState.unclear, "1300.00")
    assert len(lines(rig.case(), "unclear.earned_monthly")) == 1


async def test_a_second_correction_updates_the_open_yellow_line(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        **EARNED_1300,
        "Actually I make fourteen hundred a month.": x(("earned_monthly", "1400", "month", "fourteen hundred")),
        "No wait, fifteen hundred a month.": x(("earned_monthly", "1500", "month", "fifteen hundred"))}))
    await at(rig, "ask.income")
    await rig.say("I make thirteen hundred a month, nobody gives me cash.")
    await rig.say("Yes.")
    await rig.say("Actually I make fourteen hundred a month.")
    reply = await rig.say("No wait, fifteen hundred a month.")
    assert keys(reply)[0] == "readback.earned"
    found = lines(rig.case(), "unclear.earned_monthly")
    assert len(found) == 1 and found[0].assumed == "$1,500/mo" and "$1,500" in found[0].reason


async def test_the_confirmed_amount_said_again_stays_confirmed(rig_factory) -> None:
    """The same amount with a teen word after its confirm is not a new answer: it stays confirmed and clear, no yellow
    line, and with a hold phrase the line still waits."""
    again = "One sec... okay, I make thirteen hundred a month."
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        **EARNED_1300, again: x(("earned_monthly", "1300", "month", "thirteen hundred"), intents=["hold"])}))
    await at(rig, "ask.income")
    await rig.say("I make thirteen hundred a month, nobody gives me cash.")
    await rig.say("Yes.")
    reply = await rig.say(again)
    assert keys(reply) == ["hold.ok"] and reply.hold_s == 30
    item = rig.case().slots[S.earned_monthly]
    assert (item.value, item.state, item.confirmed, item.changed_from) == ("1300.00", SlotState.clear, True, None)
    assert lines(rig.case(), "unclear.earned_monthly") == []


async def test_a_plain_correction_of_a_confirmed_amount_is_still_read_back_clear(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        **RENT_1300, "Actually it's 1200.": x(("rent_share", "1200", "month", "1200"), intents=["correction"])}))
    await at(rig, "ask.rent")
    await rig.say("Thirteen hundred.")
    await rig.say("Yes.")
    reply = await rig.say("Actually it's 1200.")
    assert keys(reply) == ["readback.rent", "flip.rent_paid_by_others"]
    item = rig.case().slots[S.rent_share]
    assert (item.value, item.state, item.changed_from) == ("1200.00", SlotState.clear, "1300.00")
    assert lines(rig.case(), "unclear.rent_share") == []


# ------------------------------------------------------------------------------------------ a done phrase and more

async def at_close_es(rig, extra_cash: str = "Unos mil.") -> None:
    """A Spanish web call at the close question (Maria's answers, then no rent paid by others and the cash answer)."""
    await at(rig, "flip.rent_paid_by_others", channel="web", lang="es")
    await rig.say("No.")
    reply = await rig.say(extra_cash)
    assert keys(reply)[-1] == "close.anything_else", keys(reply)


CLOSE_CORRECTIONS = [
    "Nothing else. Actually my rent is twelve hundred, not eleven hundred.",
    "Nothing else, oh wait, my rent is twelve hundred.",
]


@pytest.mark.parametrize("text", CLOSE_CORRECTIONS)
async def test_a_rent_correction_after_a_done_phrase_is_applied(rig_factory, text: str) -> None:
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        text: x(("rent_share", "1200", "month", "twelve hundred"), intents=["correction"])}))
    await maria(rig, 8)
    assert rig.session().pending.key == "close.anything_else"
    reply = await rig.say(text)
    assert not reply.end
    assert keys(reply)[0] == "readback.rent" and keys(reply)[-1] == "close.anything_else"
    item = rig.case().slots[S.rent_share]
    assert (item.value, item.changed_from) == ("1200.00", "1100.00")
    bye = await rig.say("No, thanks.")
    assert bye.end and keys(bye) == ["close.goodbye"]


@pytest.mark.parametrize("text", ["No thanks, I'm on an F-1 visa.", "No thanks. I'm undocumented."])
async def test_a_status_after_a_done_phrase_routes(rig_factory, text: str) -> None:
    status = "F-1" if "F-1" in text else "undocumented"
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        text: x(("volunteered_status", status, None, ""))}))
    await maria(rig, 8)
    assert rig.case().reason_code == "likely"
    reply = await rig.say(text)
    assert not reply.end
    assert keys(reply) == ["result.other_help.status", "close.anything_else"]
    case = rig.case()
    assert case.reason_code == "other_help.status" and case.tier == Tier.other_help
    assert S.volunteered_status not in case.slots  # it only routes; the value is never stored


async def test_a_spanish_rent_correction_after_a_done_phrase_is_applied(rig_factory) -> None:
    text = "Nada más. Ah, mi renta es de mil doscientos."
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "Unos mil.": x(("cash_on_hand", "1000"), lang="es"),
        text: x(("rent_share", "1200", "month", "mil doscientos"), lang="es")}))
    await at_close_es(rig)
    reply = await rig.say(text)
    assert not reply.end
    assert keys(reply)[0] == "readback.rent" and keys(reply)[-1] == "close.anything_else"
    assert rig.case().slots[S.rent_share].value == "1200.00"


async def test_a_spanish_status_after_a_done_phrase_routes(rig_factory) -> None:
    text = "No, gracias. Soy indocumentada."
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "Unos mil.": x(("cash_on_hand", "1000"), lang="es"),
        text: x(("volunteered_status", "undocumented", None, ""), lang="es")}))
    await at_close_es(rig)
    reply = await rig.say(text)
    assert not reply.end
    assert keys(reply) == ["result.other_help.status", "close.anything_else"]
    assert rig.case().reason_code == "other_help.status"


@pytest.mark.parametrize("text", ["No, thanks.", "No, that's all. Thanks.", "That's all."])
async def test_a_bare_done_phrase_still_says_goodbye(rig_factory, text: str) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria(rig, 8)
    reply = await rig.say(text)
    assert reply.end and keys(reply) == ["close.goodbye"] and reply.end_reason == "completed"


async def test_a_done_phrase_with_a_value_said_again_says_goodbye(rig_factory) -> None:
    """Nothing new (the rent as it is): the done phrase ends the call at once."""
    text = "No thanks, my rent is eleven hundred like I said."
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        text: x(("rent_share", "1100", "month", "eleven hundred"))}))
    await maria(rig, 8)
    reply = await rig.say(text)
    assert reply.end and keys(reply) == ["close.goodbye"]
    assert rig.case().slots[S.rent_share].changed_from is None


async def test_a_risky_amount_after_a_done_phrase_gets_its_confirm(rig_factory) -> None:
    text = "Nothing else, oh wait, my rent is thirteen hundred."
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        text: x(("rent_share", "1300", "month", "thirteen hundred"), intents=["correction"])}))
    await maria(rig, 8)
    reply = await rig.say(text)
    assert not reply.end and keys(reply) == ["confirm.money"]
    after = await rig.say("Yes.")
    assert keys(after)[-1] == "close.anything_else"
    assert rig.case().slots[S.rent_share].confirmed

