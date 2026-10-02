"""Answers that come while part of the call is still waiting, and amounts set to $0 by an answer to another question.

- A phone reply over its word budget is split; the rest follows on the next request (docs/SPEC.md §3.2). Something
  new said before the rest arrives — a correction, a fact, "Is this a real person?", a hold — is never discarded:
  every turn applies the new observations (§3.2), the correction is read back (§3.4) and the rest follows. A bare
  "okay" still gets the rest.
- A known critical amount set to $0 by an answer to another question is never applied silently: the $0 is read back
  and a yellow line asks a person to check it (§3.3 corrections, §3.4).
- At the close question, a plain closing ends the call; a done phrase that says more than a plain closing is never a
  goodbye at once (a question said without a question mark keeps the call open), and an intent the model noted with
  it (a side question, "is this recorded?") is answered first.
"""

from __future__ import annotations

from gatorplate.contracts.common import Phase
from gatorplate.contracts.slots import SlotName
from tests.dialogue.support import FakeUnderstanding
from tests.dialogue.test_global_intents import keys, x
from tests.dialogue.test_review import maria

S = SlotName
CASH_40 = {"About forty dollars.": x(("cash_on_hand", "40", None, "forty dollars"))}


async def split_after_cash(rig_factory, extra: dict) -> object:
    """Maria (phone, screen card) up to the cash answer "About forty dollars.": the expedited reply is split and the
    close question waits for the next request."""
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={**CASH_40, **extra}))
    await maria(rig, 7)
    reply = await rig.say("About forty dollars.")
    assert reply.ask is None and "expedited.yes" in keys(reply)
    assert rig.session().deferred_keys, "the reply should be split for the phone word budget"
    return rig


async def test_a_bare_okay_gets_the_rest_of_a_split_reply(rig_factory) -> None:
    rig = await split_after_cash(rig_factory, {"Okay.": x()})
    reply = await rig.say("Okay.")
    assert keys(reply)[-1] == "close.anything_else"


async def test_a_correction_before_the_rest_is_applied_and_the_rest_follows(rig_factory) -> None:
    text = "Wait, my rent is actually twelve hundred."
    rig = await split_after_cash(rig_factory, {text: x(("rent_share", "1200", "month", "twelve hundred"),
                                                       intents=["correction"])})
    reply = await rig.say(text)
    item = rig.case().slots[S.rent_share]
    assert item.value == "1200.00" and item.changed_from == "1100.00"
    said = keys(reply) + rig.session().deferred_keys
    assert said[0] == "readback.rent" and said[-1] == "close.anything_else"


async def test_a_cash_correction_before_the_rest_is_applied(rig_factory) -> None:
    text = "Sorry, I meant four hundred dollars, not forty."
    rig = await split_after_cash(rig_factory, {text: x(("cash_on_hand", "400", None, "four hundred dollars"),
                                                       intents=["correction"])})
    reply = await rig.say(text)
    assert rig.case().slots[S.cash_on_hand].value == "400.00"
    assert (keys(reply) + rig.session().deferred_keys)[-1] == "close.anything_else"


async def test_is_this_a_real_person_before_the_rest_is_answered(rig_factory) -> None:
    rig = await split_after_cash(rig_factory, {})
    reply = await rig.say("Is this a real person?")
    said = keys(reply) + rig.session().deferred_keys
    assert said[0] == "answer.is_ai" and said[-1] == "close.anything_else"


async def test_a_hold_before_the_rest_keeps_the_rest_waiting(rig_factory) -> None:
    rig = await split_after_cash(rig_factory, {"Hold on, let me write that down.": x()})
    reply = await rig.say("Hold on, let me write that down.")
    assert keys(reply) == ["hold.ok"] and reply.hold_s > 0
    assert rig.session().deferred_keys
    reply = await rig.say("Okay.")
    assert keys(reply)[-1] == "close.anything_else"


# ------------------------------------------------------------------------------------------ amounts set to $0

async def test_an_earnings_zero_said_to_another_question_is_read_back_and_flagged(rig_factory) -> None:
    text = "No, and I'm not working anymore."
    rig = rig_factory(understanding=FakeUnderstanding(extra={text: x(("earned_monthly", "0", "month", "not working"))}))
    await maria(rig, 6)  # at the rent-paid-by-others question
    assert rig.session().pending.key == "flip.rent_paid_by_others"
    reply = await rig.say(text)
    item = rig.case().slots[S.earned_monthly]
    assert item.value == "0.00" and item.changed_from == "900.00"
    assert "readback.earned" in keys(reply)
    assert [y.code for y in rig.case().yellow_lines if y.resolved is None and y.slot == S.earned_monthly] == \
        ["conflict.earned_monthly"]


async def test_a_new_nonzero_amount_said_to_another_question_is_read_back_without_a_line(rig_factory) -> None:
    text = "No. Oh, and I make 1,000 now."
    rig = rig_factory(understanding=FakeUnderstanding(extra={text: x(("earned_monthly", "1000", "month", "1,000"))}))
    await maria(rig, 6)
    reply = await rig.say(text)
    assert rig.case().slots[S.earned_monthly].value == "1000.00"
    assert "readback.earned" in keys(reply)
    assert not [y for y in rig.case().yellow_lines if y.code.startswith("conflict.")]


# ------------------------------------------------------------------------------------------ the close question

async def test_a_plain_closing_says_goodbye(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria(rig, 8)
    reply = await rig.say("No, that's all, thanks!")
    assert reply.end and keys(reply) == ["close.goodbye"]


async def test_a_question_without_a_question_mark_keeps_the_call_open(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria(rig, 8)
    reply = await rig.say("No thanks, so I still need to bring my lease right")
    assert not reply.end and keys(reply)[-1] == "close.anything_else"
    reply = await rig.say("No.")
    assert reply.end and keys(reply) == ["close.goodbye"]


async def test_a_side_question_with_a_done_phrase_is_noted(rig_factory) -> None:
    text = "No thanks, my roommate wants to know if she can apply too"
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        text: x(intents=["side_question"], side_question="Can the student's roommate apply too?")}))
    await maria(rig, 8)
    reply = await rig.say(text)
    assert not reply.end and keys(reply)[0] == "side_question.noted"
    assert any(y.code == "student_question" for y in rig.case().yellow_lines)
    assert rig.session().phase == Phase.close


async def test_closed_mode_correction_before_the_split_question_is_not_lost(rig_factory) -> None:
    """Closed mode (no model): the earnings read-back is split from the closed rent question. "No, I said nineteen
    hundred." before the rent question arrives corrects the earnings (with its one confirm for the teen word)."""
    text = "No, I said nineteen hundred."
    income = "I work at the campus library, about 900 a month. Nobody gives me cash."
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        text: x(("earned_monthly", "1900", "month", "nineteen hundred"), intents=["correction"])}))
    await maria(rig, 4)
    session = rig.session()
    session.closed_mode = True
    rig.sessions.put(session)
    reply = await rig.say(income)
    assert rig.session().deferred_keys == ["ask.rent:closed"] and reply.ask is None
    reply = await rig.say(text)
    item = rig.case().slots[S.earned_monthly]
    assert item.value == "1900.00" and item.changed_from == "900.00"
    assert keys(reply)[-1] in ("confirm.money", "ask.rent")


async def test_another_language_named_only_by_the_keyword_list_gets_the_unsupported_line(rig_factory) -> None:
    """No model (or no language named by it): "Can we do this in Vietnamese?" on the phone still gets the line."""
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "Can we do this in Vietnamese?": x(intents=["language_request"])}))
    await maria(rig, 2)
    reply = await rig.say("Can we do this in Vietnamese?")
    assert keys(reply)[0] == "language.unsupported" and reply.lang == "en"
    assert rig.case().language_request.offered == "none"
