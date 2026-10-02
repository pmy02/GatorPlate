"""Every brain-owned global intent (docs/SPEC.md §3.3) and the routing vectors of data/content/guards.json.

The highest-precedence intent of a turn wins the reply (delete before stop; crisis and privacy first); slot
observations from the same turn are still applied, except from a turn with masked or redacted digits, a delete turn,
or a volunteered status (route only)."""

from __future__ import annotations

import json

import pytest

from gatorplate.contracts.common import Phase
from gatorplate.contracts.slots import SlotName
from tests.dialogue.conftest import make_rig
from tests.dialogue.replay import ROOT, phone_reply_problems, prime
from tests.dialogue.support import FakeUnderstanding

GUARDS = json.loads((ROOT / "data" / "content" / "guards.json").read_text(encoding="utf-8"))


def x(*obs, intents=(), lang="en", side_question=None, requested_language=None, answered="no") -> dict:
    """A custom extraction for the fake understanding: obs = (slot, value[, period[, quote]])."""
    observations = []
    for o in obs:
        slot, value = o[0], o[1]
        period = o[2] if len(o) > 2 else None
        quote = o[3] if len(o) > 3 else value
        observations.append({"slot": slot, "value": value, "period": period, "hours_per_week": None,
                             "state": "clear", "quote": quote, "quote_en": None})
    return {"observations": observations, "intents": list(intents), "answered_pending": answered, "lang": lang,
            "side_question": side_question, "requested_language": requested_language}


async def at(rig, pending: str, *, channel: str = "phone", lang: str = "en") -> None:
    scenario = {"channel": channel, "lang": lang, "given": {"started": True, "last_seq": 5, "pending": pending}}
    await prime(rig, scenario)


def keys(reply) -> list[str]:
    return list(reply.debug.keys)


# ------------------------------------------------------------------------------------------ routing vectors

def routing_vectors():
    for i, v in enumerate(GUARDS["tests"]["routing"]):
        yield pytest.param(v, id=f"{i}-{v['text'][:30]}")


PENDING_PHASE = {"ask.rent", "ask.income", "flip.rent_paid_by_others", "close.anything_else"}


@pytest.mark.parametrize("vector", list(routing_vectors()))
async def test_routing_vector(settings_test, vector: dict) -> None:
    """The reply key a guards.json routing vector names is the first key of the brain's reply; a null vector is left
    to the phase machine (no global reply key)."""
    rig = make_rig(settings_test)
    pending = vector["pending"]
    lang = vector["lang"]
    channel = "web" if lang == "es" else "phone"
    if pending == "close.anything_else":
        await prime(rig, {"channel": channel, "lang": lang, "given": {"started": True, "last_seq": 5,
                                                                     "pending": "flip.rent_paid_by_others"}})
        s = rig.session()
        s.phase = Phase.close
        from gatorplate.contracts.extraction import PendingQuestion

        s.pending = PendingQuestion(key="close.anything_else", slots=[], kind="open")
        rig.sessions.put(s)
    else:
        await prime(rig, {"channel": channel, "lang": lang, "given": {"started": True, "last_seq": 5,
                                                                     "pending": pending}})
    reply = await rig.say(vector["text"], masked=bool(vector.get("masked")), lang=lang)
    got = keys(reply)
    global_keys = {str(v) for v in GUARDS["input"]["routing"]["reply"].values() if isinstance(v, str)} | {
        "ssn.block", "card_number.block", "close.goodbye", "stop.goodbye"}
    if vector["expect"] is None:
        assert got[0] not in global_keys - {"close.goodbye"} or got[0] == "close.anything_else", got
        if pending == "close.anything_else":
            assert "close.goodbye" not in got
    else:
        assert got[0] == vector["expect"], got


# ------------------------------------------------------------------------------------------ each trigger

async def test_crisis_en_resources_then_continue(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("Honestly, sometimes I think about hurting myself.")
    assert keys(reply) == ["crisis.resources", "crisis.continue_or_stop"]
    assert reply.expect == "choice" and not reply.interruptible
    case = rig.case()
    assert "crisis_resources_given" in case.flags
    reply = await rig.say("Let's keep going.")
    assert keys(reply) == ["ask.rent"] and reply.ask
    assert rig.session().awaiting == "none"


async def test_crisis_then_stop(rig) -> None:
    await at(rig, "ask.rent")
    await rig.say("Honestly, sometimes I think about hurting myself.")
    reply = await rig.key("2")
    assert keys(reply) == ["stop.goodbye"] and reply.end and reply.end_reason == "completed"


async def test_crisis_es_web_two_choices(rig) -> None:
    await at(rig, "ask.income", channel="web", lang="es")
    reply = await rig.say("La verdad, ya no le veo sentido a vivir.", lang="es")
    assert keys(reply) == ["crisis.resources", "crisis.continue_or_stop"]
    assert reply.lang == "es" and reply.expect == "choice" and len(reply.choices) == 2
    assert "9-8-8" in reply.display


async def test_crisis_utterance_is_never_quoted(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "I'm 20 and honestly I want to die.": x(("age", "20", None, "I'm 20"), intents=["crisis"])}))
    await at(rig, "ask.level_units")
    await rig.say("I'm 20 and honestly I want to die.")
    case = rig.case()
    assert case.slots[SlotName.age].value == "20" and case.slots[SlotName.age].heard is None


async def test_masked_digits_store_nothing(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "My rent is 1100 and my social is #########.": x(("rent_share", "1100", "month"))}))
    await at(rig, "ask.rent")
    reply = await rig.say("My rent is 1100 and my social is #########.", masked=True)
    assert keys(reply) == ["ssn.block", "ask.rent"]
    case = rig.case()
    assert SlotName.rent_share not in case.slots
    assert [e.kind for e in case.privacy_events] == ["ssn_blocked"]


async def test_masked_card_number(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("My card number is ################.", masked=True)
    assert keys(reply)[0] == "card_number.block"
    assert [e.kind for e in rig.case().privacy_events] == ["card_number_blocked"]


async def test_ssn_question_without_digits(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("Do you need my social? It's #########.", masked=True)
    assert keys(reply) == ["ssn.block", "ask.rent"]


async def test_stop_before_result_is_incomplete(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("Bye!")
    assert keys(reply) == ["stop.goodbye"] and reply.end and reply.end_reason == "completed"
    case = rig.case()
    assert case.ended_early and any(y.code == "incomplete" for y in case.yellow_lines)


async def test_delete_yes_deletes_the_case(rig) -> None:
    await at(rig, "ask.rent")
    case_id = rig.session().case_id
    reply = await rig.say("Please delete everything I told you.")
    assert keys(reply) == ["delete.confirm_ask"] and reply.expect == "yes_no"
    reply = await rig.key("1")
    assert keys(reply) == ["delete.done"] and reply.end and reply.end_reason == "completed"
    assert rig.cases.get(case_id) is None
    assert any(e.type == "case.deleted" and e.case_id == case_id for e in rig.events.events)
    after = await rig.say("Hello?")
    assert after.end and after.say == "" and after.ask is None


async def test_delete_no_keeps_the_case(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={"No, keep it.": x()}))
    await at(rig, "ask.rent")
    await rig.say("Please delete everything I told you.")
    reply = await rig.say("No, keep it.")
    assert keys(reply) == ["delete.cancelled", "ask.rent"]
    assert rig.case() is not None


async def test_delete_outranks_stop(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("Can you erase my information and then hang up?")
    assert keys(reply) == ["delete.confirm_ask"]


async def test_abuse_twice_ends(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={"you're useless": x(intents=["abuse"])}))
    await at(rig, "ask.rent")
    reply = await rig.say("you're useless")
    assert keys(reply) == ["abuse.warn", "ask.rent"]
    reply = await rig.say("you're useless")
    assert keys(reply) == ["abuse.end"] and reply.end and reply.end_reason == "completed"
    assert "abuse_ended" in rig.case().flags


async def test_abuse_with_an_answer_keeps_the_value_without_quote(rig) -> None:
    await at(rig, "ask.rent")
    await rig.say("It's eleven hundred, you stupid machine.")
    item = rig.case().slots[SlotName.rent_share]
    assert item.value == "1100.00" and item.heard is None


async def test_human_request_then_keep_going(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={"Yes, okay.": x()}))
    await at(rig, "ask.rent")
    reply = await rig.say("Can I just talk to a real person?")
    assert keys(reply) == ["human.request"] and reply.expect == "yes_no" and not reply.interruptible
    assert "human_requested" in rig.case().flags
    assert not phone_reply_problems(reply, keys(reply))
    reply = await rig.say("Yes, okay.")
    assert keys(reply) == ["ask.rent"]


async def test_human_request_then_no_stops(rig) -> None:
    await at(rig, "ask.rent")
    await rig.say("Can I just talk to a real person?")
    reply = await rig.key("2")
    assert keys(reply) == ["stop.goodbye"] and reply.end


async def test_is_ai_and_is_recorded(rig) -> None:
    await at(rig, "ask.level_units")
    reply = await rig.say("Is this a real person?")
    assert keys(reply) == ["answer.is_ai", "ask.level_units"]
    reply = await rig.say("Is this call being recorded?")
    assert keys(reply) == ["answer.is_recorded", "ask.level_units"]


async def test_is_ai_during_consent_reasks(rig) -> None:
    await rig.start()
    reply = await rig.say("Wait, is this a robot?")
    assert keys(reply) == ["answer.is_ai", "consent.reask"]
    reply = await rig.key("1")
    assert keys(reply) == ["ack.short", "ask.level_units"]


async def test_language_request_phone(rig) -> None:
    await at(rig, "ask.level_units")
    reply = await rig.say("Can we do this in Spanish? Español, por favor.")
    assert keys(reply) == ["language.offer_web"] and reply.lang == "es" and reply.ask is None
    assert rig.case().language_request.model_dump() == {"asked": "es", "offered": "web"}
    reply = await rig.say("Okay, English is fine.")
    assert reply.lang == "en" and keys(reply) == ["ack.short", "ask.level_units"]


async def test_language_request_other_language_phone(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "Can we do this in French?": x(intents=["language_request"], requested_language="fr")}))
    await at(rig, "ask.level_units")
    reply = await rig.say("Can we do this in French?")
    assert keys(reply)[0] == "language.unsupported" and reply.lang == "en"
    assert rig.case().language_request.offered == "none"


async def test_language_switch_web(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "¿Podemos hablar en inglés?": x(intents=["language_request"], requested_language="en", lang="es")}))
    await at(rig, "ask.income", channel="web", lang="es")
    reply = await rig.say("¿Podemos hablar en inglés?", lang="es")
    assert reply.lang == "en" and rig.session().lang == "en"
    assert rig.case().language_request.offered == "switched"


async def test_hold(rig) -> None:
    await at(rig, "ask.income")
    reply = await rig.say("Hold on, let me check my pay stub.")
    assert keys(reply) == ["hold.ok"] and reply.hold_s == 30 and reply.ask is None and reply.listen == "long"
    assert rig.session().pending.key == "ask.income"


async def test_repeat_sends_the_last_reply_again(rig) -> None:
    await at(rig, "ask.level_units")
    first = await rig.say("Is this a real person?")
    again = await rig.say("Sorry, can you say that again?")
    assert again.say == first.say and again.ask == first.ask


@pytest.mark.parametrize(("text", "intent", "key"), [
    ("Can you just apply for me?", "apply_for_me", "apply_for_me"),
    ("Will this affect my immigration status?", "immigration_question", "immigration.question"),
    ("I'm hungry today, is there food?", "food_today", "food_today"),
    ("They said no last year.", "previously_denied", "info.previously_denied"),
    ("I'm calling for my son.", "proxy_caller", "proxy.caller"),
])
async def test_info_intents(rig_factory, text: str, intent: str, key: str) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={text: x(intents=[intent])}))
    await at(rig, "ask.rent")
    reply = await rig.say(text)
    assert keys(reply) == [key, "ask.rent"]
    assert not phone_reply_problems(reply, keys(reply))
    case = rig.case()
    assert case.route_override is None
    if intent == "previously_denied":
        assert case.slots[SlotName.previously_denied].value == "true"


async def test_side_question_yellow(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "Does this affect my financial aid?": x(intents=["side_question"],
                                                side_question="Does CalFresh affect financial aid?")}))
    await at(rig, "ask.rent")
    reply = await rig.say("Does this affect my financial aid?")
    assert keys(reply) == ["side_question.noted", "ask.rent"]
    lines = [y for y in rig.case().yellow_lines if y.code == "student_question"]
    assert len(lines) == 1 and lines[0].reason == 'Student asked: "Does CalFresh affect financial aid?"'


async def test_relay_not_claimed(rig_factory) -> None:
    text = "Can I do this through a relay service?"
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        text: x(intents=["side_question"], side_question="Can the student use a relay service?")}))
    await at(rig, "ask.rent")
    reply = await rig.say(text)
    assert keys(reply)[0] == "side_question.noted"
    spoken_text = (reply.say + " " + (reply.ask or "")).lower()
    assert "relay" not in spoken_text and "tty" not in spoken_text and "711" not in spoken_text


async def test_already_receiving_routes_to_info_result(rig) -> None:
    await at(rig, "ask.level_units")
    reply = await rig.say("I already get CalFresh, I just want to know if the amount is right.")
    assert keys(reply)[0] == "result.info.already_receiving"
    assert "first_month.apply_today" not in keys(reply)
    assert rig.case().reason_code == "info.already_receiving"


async def test_interview_waiting_routes_to_info_result(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("I applied two weeks ago and I'm still waiting for my interview.")
    assert keys(reply)[0] == "result.info.interview_waiting"
    assert "first_month.apply_today" not in keys(reply)
    assert rig.case().reason_code == "info.interview_waiting"


async def test_never_promise_probes(rig_factory) -> None:
    probes = {
        "Did you send it to the coordinator?": x(intents=["side_question"], side_question="Was it sent?"),
        "Can you text me the card?": x(intents=["side_question"], side_question="Can the card be texted?"),
        "Can you call me back later?": x(intents=["side_question"], side_question="Can GatorPlate call back?"),
    }
    rig = rig_factory(understanding=FakeUnderstanding(extra=probes))
    await at(rig, "ask.rent")
    for text in probes:
        reply = await rig.say(text)
        low = (reply.say + " " + (reply.ask or "")).lower()
        for banned in ("sent to the coordinator", "text you", "call you back", "callback", "transfer"):
            assert banned not in low
