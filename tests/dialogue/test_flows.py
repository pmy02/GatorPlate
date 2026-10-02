"""Conversation flows: silence ladder, interruptions, language-model failures, closed mode, seq rules, the end of a
call, consent, single keypad keys, the result chain and the dialogue paths of the golden cases (docs/SPEC.md §3)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from gatorplate.contracts.brain_api import EndRequest, StartRequest, TurnRequest
from gatorplate.contracts.common import Channel, Lang
from gatorplate.contracts.errors import Conflict, StaleSeq, UnknownCall
from gatorplate.contracts.slots import SlotName
from tests.dialogue.conftest import make_rig
from tests.dialogue.replay import phone_reply_problems
from tests.dialogue.support import FakeUnderstanding
from tests.dialogue.test_global_intents import at, keys, x

S = SlotName


async def consented(rig) -> None:
    await rig.start()
    await rig.say("Yes, that's fine.")


async def maria_to_rent(rig) -> None:
    await consented(rig)
    for text in ("I'm an SF State undergrad, a junior, and I'm taking 12 units.", "I'm 20, and I live with two roommates.",
                 "Separately.", "I work at the campus library, about 900 a month. Nobody gives me cash."):
        await rig.say(text)


# ------------------------------------------------------------------------------------------ silence, interruptions

async def test_silence_ladder(rig) -> None:
    await at(rig, "ask.rent")
    r1 = await rig.silence(1)
    assert keys(r1) == ["reprompt.silence_1", "ask.rent"] and r1.listen == "long"
    r2 = await rig.silence(2)
    assert keys(r2) == ["reprompt.silence_2", "ask.rent"] and "press one" in r2.ask.lower()
    r3 = await rig.silence(3)
    assert keys(r3) == ["close.silence"] and r3.end and r3.end_reason == "no_input" and not r3.interruptible
    case = rig.case()
    assert case.ended_early and any(y.code == "incomplete" for y in case.yellow_lines)
    assert [a.kind for a in case.asked[-2:]] == ["reprompt", "closed"]


async def test_silence_at_consent(rig) -> None:
    await rig.start()
    r1 = await rig.silence(1)
    assert keys(r1) == ["reprompt.silence_1", "consent.ask"]
    r2 = await rig.silence(2)
    assert keys(r2) == ["reprompt.silence_2", "consent.ask"] and "press one" in r2.ask.lower()
    r3 = await rig.silence(3)
    assert r3.end_reason == "no_input"


async def test_silence_at_close_says_goodbye(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria_to_rent(rig)
    for text in ("Eleven hundred.", "No.", "About a thousand."):
        await rig.say(text)
    reply = await rig.silence(1)
    assert keys(reply) == ["close.goodbye"] and reply.end_reason == "completed"


async def test_interrupted_without_answer(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("Wait, what?", interrupted=True)
    assert keys(reply) == ["reprompt.after_interrupt", "ask.rent"]


async def test_interrupted_with_an_answer_is_processed(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("Eleven hundred.", interrupted=True)
    assert keys(reply)[0] == "readback.rent"


async def test_unclear_twice_moves_on(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={"Hmm.": x()}))
    await at(rig, "ask.rent")
    first = await rig.say("Hmm.")
    assert keys(first) == ["reprompt.unclear", "ask.rent"] and "press one" in first.ask.lower()
    second = await rig.say("Hmm.")
    assert "reprompt.unclear" not in keys(second)
    assert rig.case().slots[S.rent_share].state == "unclear"


async def test_empty_text_is_unclear(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("")
    assert keys(reply) == ["reprompt.unclear", "ask.rent"]


async def test_dont_know_income_asks_the_band(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={"I'm not sure.": x(intents=["dont_know"])}))
    await at(rig, "ask.income")
    reply = await rig.say("I'm not sure.")
    assert keys(reply) == ["ask.income_band"]
    assert "one thousand dollars" in reply.ask and "two thousand dollars" in reply.ask
    assert rig.case().asked[-1].kind == "band"
    band = await rig.key("2")
    assert rig.case().slots[S.earned_monthly].value == "2000.00"
    assert rig.case().slots[S.earned_monthly].state == "assumed"
    assert any(y.code == "unclear.earned_monthly" for y in rig.case().yellow_lines)
    assert not phone_reply_problems(band, keys(band))


# ------------------------------------------------------------------------------------------ language model failures

async def test_llm_timeout_gives_the_closed_question(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(status="timeout"))
    await at(rig, "ask.rent")
    reply = await rig.say("Something long and unclear about my rent.")
    assert keys(reply) == ["ask.rent"] and "press one" in reply.ask.lower()
    assert rig.session().llm_failures == 1 and not rig.session().closed_mode


async def test_two_failures_close_mode(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(status="error"))
    await at(rig, "ask.income")
    await rig.say("Something the model fails on.")
    await rig.say("Something else it fails on.")
    s = rig.session()
    assert s.closed_mode and "closed_mode" in rig.case().flags
    reply = await rig.key("2")  # closed ask.income: no work income
    assert rig.case().slots[S.earned_monthly].value == "0.00"
    assert "press one" in (reply.ask or "").lower()  # the next question in its closed form too


async def test_slow_model_hits_the_turn_budget(settings_test) -> None:
    settings = settings_test.model_copy(update={"turn_budget_s": 0.05})
    rig = make_rig(settings, understanding=FakeUnderstanding(delay_s=1.0))
    await at(rig, "ask.rent")
    import time

    began = time.monotonic()
    reply = await rig.say("Eleven hundred.")
    assert time.monotonic() - began < 0.5
    assert keys(reply) == ["ask.rent"] and "press one" in reply.ask.lower()


async def test_recent_memory_is_two_redacted_utterances(rig) -> None:
    await maria_to_rent(rig)
    call = rig.understanding.calls[-1]
    assert len(call["recent"]) == 2
    assert call["pending"] == "ask.income"


async def test_volunteered_status_is_dropped_and_routes(rig) -> None:
    await at(rig, "ask.income")
    reply = await rig.say(
        "I'm an international student on an F-1 visa, so I can only work on campus. I make about 700 a month.")
    case = rig.case()
    assert keys(reply)[0] == "result.other_help.status"
    assert "first_month.apply_today" not in keys(reply)
    assert S.volunteered_status not in case.slots
    assert all("F-1" not in (slot.heard or "") for slot in case.slots.values())
    assert case.route_override == "other_help.status" and case.reason_code == "other_help.status"
    await rig.say("No, thanks.")
    assert not any("F-1" in t for t in rig.understanding.calls[-1]["recent"])


# ------------------------------------------------------------------------------------------ seq rules and the end

async def test_duplicate_and_stale_seq(rig) -> None:
    await rig.start()
    first = await rig.say("Yes, that's fine.")
    again = await rig.brain.turn(rig.call_id, TurnRequest(v=1, seq=1, event="utterance", text="Different"))
    assert again == first
    rig.seq = 2
    await rig.say("I'm a junior, 12 units.")
    with pytest.raises(StaleSeq):
        await rig.brain.turn(rig.call_id, TurnRequest(v=1, seq=1, event="utterance", text="Yes."))


async def test_repeated_start_returns_the_first_reply(rig) -> None:
    first = await rig.start()
    again = await rig.start()
    assert again == first
    assert len(rig.cases.rows) == 1


async def test_unknown_call(rig) -> None:
    with pytest.raises(UnknownCall):
        await rig.brain.turn("f" * 32, TurnRequest(v=1, seq=1, event="utterance", text="Yes."))
    with pytest.raises(UnknownCall):
        await rig.brain.end("f" * 32, EndRequest(v=1, reason="caller_hangup"))


async def test_turn_after_brain_end_and_after_end(rig) -> None:
    await rig.start()
    declined = await rig.say("No, I don't want to do this.")
    assert declined.end and declined.end_reason == "declined"
    empty = await rig.say("Bye!")
    assert empty.say == "" and empty.ask is None and empty.end and empty.end_reason == "declined"
    await rig.brain.end(rig.call_id, EndRequest(v=1, reason="declined"))
    await rig.brain.end(rig.call_id, EndRequest(v=1, reason="declined"))
    with pytest.raises(Conflict):
        await rig.say("Hello?")


async def test_hangup_before_result_is_incomplete(rig_factory) -> None:
    rig = rig_factory(live=True)
    await maria_to_rent(rig)
    case_id = rig.session().case_id
    assert rig.live.get(case_id) is not None
    await rig.brain.end(rig.call_id, EndRequest(v=1, reason="caller_hangup"))
    case = rig.case()
    assert not case.live and case.ended_early and case.ended_reason == "caller_hangup"
    assert [y.code for y in case.yellow_lines if y.code == "incomplete"] == ["incomplete"]
    assert rig.live.get(case_id) is None and case_id in rig.live.wiped
    assert any(e.type == "live.ended" for e in rig.events.events)


async def test_idle_call_is_closed(rig) -> None:
    await rig.start()
    rig.clock.advance(minutes=11)
    with pytest.raises(Conflict):
        await rig.say("Yes, that's fine.")
    assert not rig.case().live


async def test_end_during_start_waits(rig) -> None:
    import asyncio

    start = asyncio.create_task(rig.brain.start(rig.call_id, StartRequest(v=1, seq=0, channel="phone", lang="en")))
    end = asyncio.create_task(rig.brain.end(rig.call_id, EndRequest(v=1, reason="caller_hangup")))
    await asyncio.gather(start, end)
    assert rig.session().ended and not rig.case().live


# ------------------------------------------------------------------------------------------ consent

async def test_consent_declined_stores_nothing(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "No, I'm 20 and I don't want this.": x(("consent", "false"), ("age", "20"))}))
    await rig.start()
    reply = await rig.say("No, I'm 20 and I don't want this.")
    assert keys(reply) == ["consent.declined"] and reply.end_reason == "declined"
    case = rig.case()
    assert case.slots == {} and case.consent.given is False


async def test_consent_unclear_twice_is_no(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={"Hmm.": x()}))
    await rig.start()
    first = await rig.say("Hmm.")
    assert keys(first) == ["consent.reask"]
    second = await rig.say("Hmm.")
    assert keys(second) == ["consent.declined"] and second.end_reason == "declined"


async def test_consent_keeps_facts_said_with_it(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "Sure, I'm an SF State junior with 12 units.": x(("consent", "true"), ("level", "undergrad"),
                                                         ("units", "12"))}))
    await rig.start()
    reply = await rig.say("Sure, I'm an SF State junior with 12 units.")
    assert keys(reply) == ["ack.short", "ask.age_parent"]
    case = rig.case()
    assert case.consent.given is True and case.consent.disclosure_key == "consent.ask"


# ------------------------------------------------------------------------------------------ single keys

@pytest.mark.parametrize("bad", ["7", "1100#", "*"])
async def test_single_keys_only(rig, bad: str) -> None:
    await at(rig, "flip.rent_paid_by_others")
    reply = await rig.brain.turn(rig.call_id, TurnRequest(v=1, seq=rig.seq + 1, event="dtmf", dtmf=bad))
    rig.seq += 1
    assert keys(reply) == ["reprompt.unclear", "flip.rent_paid_by_others"] and reply.ask
    assert "press one for yes, two for no" in reply.ask.lower()
    text = (reply.say + " " + reply.ask).lower()
    assert "pound" not in text and "type" not in text and S.rent_paid_by_others_to_landlord not in rig.case().slots
    no = await rig.key("2")
    assert rig.case().slots[S.rent_paid_by_others_to_landlord].value == "0.00"
    assert rig.case().slots[S.rent_paid_by_others_to_landlord].source == "keypad"
    assert keys(no)[0] == "result.likely"


async def test_keypad_band_choice(rig) -> None:
    await at(rig, "ask.rent")
    await rig.silence(1)
    await rig.silence(2)  # closed form: a spoken band choice
    reply = await rig.key("2")
    item = rig.case().slots[S.rent_share]
    assert item.value == "1000.00" and item.state == "assumed"
    assert reply.ask or reply.say


async def test_web_quick_reply(rig) -> None:
    await rig.start(channel="web", lang="en")
    reply = await rig.say("Yes", typed=True)
    assert keys(reply) == ["ack.short", "ask.level_units"]
    assert reply.display.startswith(reply.say.split()[0])


# ------------------------------------------------------------------------------------------ result chain

async def test_code_delivery_splits_the_card_reply(rig_factory) -> None:
    rig = rig_factory(card_delivery="code", short_codes=["481206"])
    await maria_to_rent(rig)
    await rig.say("Eleven hundred.")
    await rig.say("No.")
    reply = await rig.say("About a thousand.")
    assert keys(reply) == ["first_month.apply_today", "card.phone_code"] and reply.ask is None
    assert "four eight one, two zero six" in reply.say and not reply.interruptible
    assert rig.session().deferred_keys == ["close.anything_else"]
    nxt = await rig.say("Okay, got it.")
    assert keys(nxt) == ["close.anything_else"]
    bye = await rig.say("No, that's all. Thanks.")
    assert keys(bye) == ["close.goodbye"]
    card = rig.case().card
    assert card.short_code == "481206" and card.expires_at > card.created_at


async def test_close_loops_at_most_twice(rig_factory) -> None:
    extra = {"When would I actually get the card?": x(intents=["side_question"], side_question="When is the card?")}
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra=extra))
    await maria_to_rent(rig)
    for text in ("Eleven hundred.", "No.", "About a thousand."):
        await rig.say(text)
    one = await rig.say("When would I actually get the card?")
    assert keys(one) == ["side_question.noted", "close.anything_else"]
    two = await rig.say("When would I actually get the card?")
    assert keys(two)[-1] == "close.anything_else"
    three = await rig.say("When would I actually get the card?")
    assert keys(three)[-1] == "close.goodbye" and three.end


async def test_shared_food_coordinator_route(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        "We buy food together.": x(("household_food", "shared"))}))
    await consented(rig)
    await rig.say("I'm an SF State undergrad, a junior, and I'm taking 12 units.")
    await rig.say("I'm 20, and I live with two roommates.")
    reply = await rig.say("We buy food together.")
    assert keys(reply) == ["result.coordinator.shared_household", "first_month.apply_today", "card.phone_screen"]
    assert reply.ask is None and rig.session().deferred_keys == ["close.anything_else"]  # 45-word result budget
    case = rig.case()
    assert case.reason_code == "coordinator.shared_household"
    assert [y.code for y in case.yellow_lines if y.resolved is None] == ["coordinator.shared_household"]
    assert not phone_reply_problems(reply, keys(reply))


# ------------------------------------------------------------------------------------------ golden dialogue paths

async def test_g1b_parents_pay_all_the_rent(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria_to_rent(rig)
    await rig.say("Eleven hundred.")
    reply = await rig.say("Yes, my parents pay all of it straight to the landlord.")
    assert keys(reply) == ["ack.short", "flip.heat_cool"]
    rig.understanding.table["No, no heating bill."] = x(("heat_cool", "false"))
    result = await rig.say("No, no heating bill.")
    assert keys(result)[0] == "result.likely" and "one hundred fifty-five dollars" in result.say
    assert rig.case().estimate_monthly == 155
    assert [a.slots[0].value for a in rig.case().asked if a.kind == "flip"] == [
        "rent_paid_by_others_to_landlord", "heat_cool"]


async def test_rent_paid_by_others_yes_without_amount(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria_to_rent(rig)
    await rig.say("Eleven hundred.")
    reply = await rig.say("Yeah, they do.")
    assert keys(reply) == ["ack.short", "flip.rent_paid_by_others_amount"]
    reply = await rig.say("All of it.")
    assert rig.case().slots[S.rent_paid_by_others_to_landlord].value == "1100.00"
    assert keys(reply)[-1] == "flip.heat_cool"
    assert rig.session().flips_asked == 2


G6B = {
    "I'm a grad student and a TA, about nine units.": x(("level", "grad"), ("units", "9"), ("grad_exemption", "ta_ra"),
                                                        ("ta_ra", "true")),
    "I'm 26 and I live alone.": x(("age", "26"), ("lives_with_parent", "false"), ("household_food", "alone")),
    "I make 1800 a month as a TA, and nobody gives me money.": x(("earned_monthly", "1800", "month"),
                                                                  ("other_cash_monthly", "0", "month")),
    "A thousand.": x(("rent_share", "1000", "month")),
    "No heating bill.": x(("heat_cool", "false")),
    "None of those.": x(("other_utils", "none")),
}


async def test_g6b_grad_ta_two_flips(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra=G6B))
    await consented(rig)
    replies = [await rig.say(text) for text in G6B]
    assert keys(replies[0]) == ["ack.short", "ask.age_parent"]
    assert keys(replies[3]) == ["readback.rent", "flip.intro", "flip.heat_cool"]
    assert keys(replies[4]) == ["ack.short", "flip.other_utils"]
    assert keys(replies[5])[0] == "result.likely" and "fifty-five dollars" in replies[5].say
    case = rig.case()
    assert case.estimate_monthly == 55
    assert [s.reason for s in case.skipped if s.slot == S.rent_paid_by_others_to_landlord] == ["below_threshold"]
    for reply in replies:
        assert not phone_reply_problems(reply, keys(reply))


G10 = {
    "I'm a senior, 12 units.": x(("level", "undergrad"), ("units", "12")),
    "I'm 21 and I live alone.": x(("age", "21"), ("lives_with_parent", "false"), ("household_food", "alone")),
    "I make 1200 a month and my mom sends me 300 a month.": x(("earned_monthly", "1200", "month"),
                                                              ("other_cash_monthly", "300", "month")),
    "Nine hundred.": x(("rent_share", "900", "month")),
    "No heating bill.": x(("heat_cool", "false")),
    "No, I pay it all.": x(("rent_paid_by_others_to_landlord", "0", "month")),
}


async def test_g10_heat_then_rent_by_others_floor(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra=G10))
    await consented(rig)
    replies = [await rig.say(text) for text in G10]
    assert keys(replies[3])[-1] == "flip.heat_cool"
    assert keys(replies[4])[-1] == "flip.rent_paid_by_others"
    assert keys(replies[5])[0] == "result.likely_floor" and "maybe more" in replies[5].say
    case = rig.case()
    assert case.estimate_monthly == 106 and case.estimate_is_floor
    assert any(y.code == "assumed.other_utils" for y in case.yellow_lines)
    assert [s.reason for s in case.skipped if s.slot == S.other_utils] == ["max_questions"]


async def test_g11_under_half_time_work_rule_note(rig_factory) -> None:
    extra = {"I'm an SF State undergrad taking 4 units.": x(("level", "undergrad"), ("units", "4"))}
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra=extra))
    await consented(rig)
    await rig.say("I'm an SF State undergrad taking 4 units.")
    for text in ("I'm 20, and I live with two roommates.", "Separately.",
                 "I work at the campus library, about 900 a month. Nobody gives me cash.", "Eleven hundred."):
        await rig.say(text)
    reply = await rig.say("No.")
    got = keys(reply)
    assert got[:2] == ["result.likely", "result.note.abawd"]
    assert not phone_reply_problems(reply, got)
    assert any(y.code == "abawd_possible" for y in rig.case().yellow_lines)
    if got[-1] != "expedited.intro_cash":  # split for the budget: the cash question follows on the next turn
        assert reply.ask is None and rig.session().deferred_keys


async def test_g5_status_other_help_card(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await consented(rig)
    await rig.say("I'm an SF State undergrad, a junior, and I'm taking 12 units.")
    await rig.say("I'm 20, and I live with two roommates.")
    await rig.say("Separately.")
    reply = await rig.say(
        "I'm an international student on an F-1 visa, so I can only work on campus. I make about 700 a month.")
    assert keys(reply) == ["result.other_help.status", "card.phone_screen"]  # the close follows (budget)
    assert not phone_reply_problems(reply, keys(reply))
    assert keys(await rig.say("Okay, got it.")) == ["close.anything_else"]


async def test_maria_g1_phone_texts_pass_everywhere(rig_factory) -> None:
    for delivery in ("screen", "code"):
        rig = rig_factory(card_delivery=delivery)
        replies = [await rig.start()]
        for text in ("Yes, that's fine.", "I'm an SF State undergrad, a junior, and I'm taking 12 units.",
                     "I'm 20, and I live with two roommates.", "Separately.",
                     "I work at the campus library, about 900 a month. Nobody gives me cash.", "Eleven hundred.",
                     "No.", "About a thousand.", "Okay, got it.", "No, thanks."):
            replies.append(await rig.say(text))
            if replies[-1].end:
                break
        for i, reply in enumerate(replies):
            assert not phone_reply_problems(reply, keys(reply), start=i == 0), (delivery, i, reply)


async def test_events_and_live_lines(rig_factory) -> None:
    rig = rig_factory(live=True, card_delivery="screen")
    await maria_to_rent(rig)
    await rig.say("Eleven hundred.")
    flip_events = [e for e in rig.events.events if e.now_asking == "flip.rent_paid_by_others"]
    assert flip_events and flip_events[-1].asked_reason == "could change the estimate by $151: $155 or $306"
    assert flip_events[-1].now_asking_text.startswith("Does anyone")
    assert S.rent_share in flip_events[-1].changed_slots
    view = rig.live.get(rig.session().case_id)
    assert view.now_asking == "flip.rent_paid_by_others" and view.asked_reason
    assert [line.who for line in view.lines[:2]] == ["assistant", "student"]
    assert rig.events.events[0].type == "case.created"


async def test_live_transcript_off_by_default(rig) -> None:
    await maria_to_rent(rig)
    assert rig.live.lines == {}


async def test_turn_cap_gives_the_result(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={"Hmm.": x()}))
    await at(rig, "ask.rent")
    s = rig.session()
    s.turn_count = 24
    rig.sessions.put(s)
    rig.understanding.table["Eleven hundred."] = x(("rent_share", "1100", "month"))
    reply = await rig.say("Eleven hundred.")
    assert keys(reply)[1].startswith("result.") or keys(reply)[0].startswith("result.")
    assert "turn_cap" in rig.case().flags


@pytest.mark.parametrize("channel", ["phone", "web"])
async def test_start_reply_shape(rig, channel: str) -> None:
    reply = await rig.start(channel=channel, lang="en")
    assert keys(reply) == ["consent.ask"] and not reply.interruptible and reply.expect == "yes_no"
    if channel == "phone":
        assert reply.say + " " + reply.ask == (
            "Hi, this is Refri Gator, a student-built AI assistant, not an official SF State service. An AI turns "
            "what you say into text to check CalFresh; the call audio isn't recorded. Okay to start? Say "
            "yes, or press one.")
        assert len((reply.say + " " + reply.ask).split()) == 39
    else:
        web_opening = rig.brain.bank.variants("consent.ask", Lang.en, Channel.web)[0]
        assert reply.choices == ["Yes", "No"] and reply.say == web_opening["say"] and reply.display
        assert "refriGator" in reply.say and "Refri Gator" not in reply.say + reply.display


async def test_phone_start_ignores_a_spanish_lang(settings_test) -> None:
    rig = make_rig(settings_test)
    reply = await rig.brain.start(rig.call_id, StartRequest(v=1, seq=0, channel="phone", lang="es"))
    assert reply.lang == "en"


async def test_case_is_not_persisted_with_routing_slots(rig) -> None:
    await at(rig, "ask.income")
    await rig.say(
        "I'm an international student on an F-1 visa, so I can only work on campus. I make about 700 a month.")
    for row in rig.cases.rows.values():
        assert S.volunteered_status not in row.slots and S.elderly_or_disabled not in row.slots


async def test_debug_null_without_debug_keys(settings_test) -> None:
    rig = make_rig(settings_test, debug_keys=False)
    reply = await rig.start()
    assert reply.debug is None


async def test_restart_resumes_from_stored_session(rig) -> None:
    await rig.start()
    await rig.say("Yes, that's fine.")
    from tests.dialogue.conftest import Rig

    clone = Rig(brain=type(rig.brain)(settings=rig.settings, clock=rig.clock, ids=rig.ids, rules=rig.rules,
                                      understanding=rig.understanding, cases=rig.cases, sessions=rig.sessions,
                                      live=rig.live, events=rig.events, cards=None), settings=rig.settings,
                clock=rig.clock, ids=rig.ids, rules=rig.rules, understanding=rig.understanding, cases=rig.cases,
                sessions=rig.sessions, live=rig.live, events=rig.events, call_id=rig.call_id, seq=rig.seq)
    reply = await clone.say("I'm an SF State undergrad, a junior, and I'm taking 12 units.")
    assert keys(reply) == ["ack.short", "ask.age_parent"]


def test_idle_constant_is_ten_minutes() -> None:
    from gatorplate.dialogue.orchestrator import IDLE_TIMEOUT

    assert IDLE_TIMEOUT == timedelta(minutes=10)


def test_the_phone_rule_sweep_catches_a_bad_reply(rig) -> None:
    from gatorplate.contracts.brain_api import BrainReply, ReplyDebug

    bad = BrainReply(say="You may get $306.", ask=None, end=False, end_reason=None, lang="en", listen="normal",
                     expect="open", interruptible=True, hold_s=0, display=None, choices=None, card_url=None,
                     debug=ReplyDebug(keys=["result.likely"], phase="result"))
    from tests.dialogue.replay import phone_reply_problems

    assert phone_reply_problems(bad, ["result.likely"])


async def test_golden_maria_with_the_live_transcript(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen", live=True)
    await rig.start()
    for text in ("Yes, that's fine.", "I'm an SF State undergrad, a junior, and I'm taking 12 units.",
                 "I'm 20, and I live with two roommates.", "Separately.",
                 "I work at the campus library, about 900 a month. Nobody gives me cash.", "Eleven hundred.", "No.",
                 "About a thousand.", "No, thanks."):
        await rig.say(text)
    case_id = rig.session().case_id
    lines = rig.live.get(case_id).lines
    assert [line.who for line in lines].count("student") == 9
    assert all("[REDACTED]" not in line.text or line.who == "student" for line in lines)
    await rig.brain.end(rig.call_id, EndRequest(v=1, reason="completed", turns=9, duration_ms=118000))
    assert rig.live.get(case_id) is None and not rig.case().live
    assert not rig.case().ended_early


async def test_live_transcript_shows_the_display_name_on_phone_calls(rig_factory) -> None:
    """The phone says the name as two words; the console's live transcript keeps the display name."""
    rig = rig_factory(card_delivery="screen", live=True)
    opening = await rig.start()
    assert "Refri Gator" in opening.say
    await rig.say("Yes, that's fine.")
    assistant = [line.text for line in rig.live.get(rig.session().case_id).lines if line.who == "assistant"]
    assert assistant and "refriGator" in assistant[0]
    assert not any("Refri Gator" in text for text in assistant)


def _obs(slot: str, value: str, state: str, quote: str, period: str | None = None) -> dict:
    return {"slot": slot, "value": value, "period": period, "hours_per_week": None, "state": state, "quote": quote,
            "quote_en": None}


async def test_unclear_food_answer_is_decided_by_the_question_plan(rig_factory) -> None:
    unclear_food = dict(x(), observations=[_obs("household_food", "separate", "unclear", "kind of both")])
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        "Kind of both, it depends.": unclear_food,
        "Mostly separately.": x(("household_food", "separate"))}))
    await consented(rig)
    await rig.say("I'm an SF State undergrad, a junior, and I'm taking 12 units.")
    await rig.say("I'm 20, and I live with two roommates.")
    reply = await rig.say("Kind of both, it depends.")
    assert keys(reply) == ["ack.short", "ask.income"]  # no hard stop on an unclear answer
    await rig.say("I work at the campus library, about 900 a month. Nobody gives me cash.")
    reply = await rig.say("Eleven hundred.")
    assert keys(reply)[-1] == "flip.household_food"  # it changes the tier, so it is asked first
    assert rig.case().asked[-1].reason.startswith("could change the result")
    reply = await rig.say("Mostly separately.")
    assert keys(reply)[-1] == "flip.rent_paid_by_others"


async def test_words_and_number_disagree_twice_leaves_a_conflict_line(rig_factory) -> None:
    disagree = dict(x(), observations=[_obs("earned_monthly", "900", "unclear", "nine hundred", "month"),
                                       _obs("earned_monthly", "1900", "unclear", "nineteen hundred", "month")])
    rig = rig_factory(understanding=FakeUnderstanding(extra={"Nine hundred, nineteen hundred.": disagree,
                                                             "Like I said, nine or nineteen hundred.": disagree}))
    await at(rig, "ask.income")
    first = await rig.say("Nine hundred, nineteen hundred.")
    assert keys(first) == ["confirm.money"]
    await rig.say("Like I said, nine or nineteen hundred.")
    lines = [y for y in rig.case().yellow_lines if y.code == "conflict.earned_monthly"]
    assert len(lines) == 1 and "($900 or $1,900)" in lines[0].reason


async def test_invalid_keys_always_get_the_closed_form_again(rig) -> None:
    await rig.start()
    first = await rig.key("1")
    assert keys(first) == ["ack.short", "ask.level_units"]
    for bad in ("7", "1100#"):
        reply = await rig.brain.turn(rig.call_id, TurnRequest(v=1, seq=rig.seq + 1, event="dtmf", dtmf=bad))
        rig.seq += 1
        assert keys(reply) == ["reprompt.unclear", "ask.level_units"] and "press" in reply.ask.lower()
        assert "pound" not in reply.ask.lower()
    assert S.age not in rig.case().slots


class NoModel(FakeUnderstanding):
    """An understanding without a language-model client (no key): the brain runs every call in closed mode."""

    llm = None


async def test_no_model_client_means_closed_mode_from_the_start(rig_factory) -> None:
    rig = rig_factory(understanding=NoModel())
    opening = await rig.start()
    assert keys(opening) == ["consent.ask"] and rig.session().closed_mode
    replies = [await rig.key("1") for _ in range(3)]
    assert keys(replies[0]) == ["ack.short", "ask.level_units"] and "press one, two, or three" in replies[0].ask.lower()
    for reply in replies:
        text = (reply.say + " " + (reply.ask or "")).lower()
        assert reply.ask and "press" in text and "pound" not in text and "type the amount" not in text
    assert "closed_mode" in rig.case().flags


async def test_a_band_answer_is_assumed_not_confirmed(rig) -> None:
    await at(rig, "ask.income")
    s = rig.session()
    from gatorplate.contracts.extraction import PendingQuestion

    s.pending = PendingQuestion(key="ask.income_band", slots=[S.earned_monthly], kind="choice")
    rig.sessions.put(s)
    reply = await rig.say("Between one and two thousand.")
    assert "confirm.money" not in keys(reply) and keys(reply)[-1] == "ask.other_cash"
    item = rig.case().slots[S.earned_monthly]
    assert item.value == "2000.00" and item.state == "assumed"
    assert any(y.code == "unclear.earned_monthly" for y in rig.case().yellow_lines)


async def test_a_volunteered_status_wins_over_an_info_line(rig_factory) -> None:
    text = "I'm on an F-1, am I even allowed to apply?"
    extraction = dict(x(intents=["immigration_question"]), observations=[
        _obs("volunteered_status", "F-1", "clear", "I'm on an F-1")])
    rig = rig_factory(understanding=FakeUnderstanding(extra={text: extraction}))
    await at(rig, "ask.income")
    reply = await rig.say(text)
    assert keys(reply)[0] == "result.other_help.status"
    case = rig.case()
    assert S.volunteered_status not in case.slots and case.reason_code == "other_help.status"
    assert all("F-1" not in (item.heard or "") for item in case.slots.values())
