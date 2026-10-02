"""Noise, line checks, background speech and weak stops on a speakerphone (extract/noise.py, Dialogue.noise).

A turn that carries nothing usable ("[inaudible]", "uh", "", a cut-off word) or only checks the line ("hello?") never
ends the call, never gives up a question and never stores a value; background speech (a TV) is handled the same way;
a goodbye heard at the end of other talk, or a bare end word heard with low confidence, is asked about first.
"""

from __future__ import annotations

from gatorplate.contracts.slots import SlotName
from tests.dialogue.support import FakeUnderstanding
from tests.dialogue.test_global_intents import at, keys, x

S = SlotName


async def test_noise_at_consent_never_declines(rig) -> None:
    await rig.start()
    for text in ("[inaudible]", "hello? hello?", "", "uh"):  # a line check is not counted: three noise turns
        reply = await rig.say(text)
        assert keys(reply) == ["consent.reask"] and not reply.end
    assert rig.session().consent_reasks == 0
    reply = await rig.say("Yes, that's fine.")
    assert keys(reply)[-1] == "ask.level_units"
    assert rig.case().consent.given is True


async def test_noise_at_consent_is_bounded(rig) -> None:
    await rig.start()
    for _ in range(3):
        assert keys(await rig.say("[inaudible]")) == ["consent.reask"]
    assert keys(await rig.say("[inaudible]")) == ["consent.reask"]  # the fourth one counts as unclear
    reply = await rig.say("[inaudible]")
    assert keys(reply) == ["consent.declined"] and reply.end


async def test_noise_reasks_and_stores_nothing(rig) -> None:
    await at(rig, "ask.rent")
    for text in ("uh", "[inaudible]", "mm"):
        reply = await rig.say(text)
        assert keys(reply) == ["reprompt.unclear", "ask.rent"], text
        assert S.rent_share not in rig.case().slots
    assert rig.understanding.calls == []  # no model call for noise


async def test_more_noise_is_still_nothing_heard(rig) -> None:
    await at(rig, "ask.rent")
    for text in ("under-", "...", "[music]"):
        assert keys(await rig.say(text)) == ["reprompt.unclear", "ask.rent"], text
    assert S.rent_share not in rig.case().slots


async def test_noise_never_counts_toward_giving_up(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={"Banana.": x()}))
    await at(rig, "ask.rent")
    assert keys(await rig.say("uh")) == ["reprompt.unclear", "ask.rent"]
    assert keys(await rig.say("[inaudible]")) == ["reprompt.unclear", "ask.rent"]
    first = await rig.say("Banana.")  # the first real unclear answer: one closed re-ask
    assert keys(first) == ["reprompt.unclear", "ask.rent"] and "press one" in first.ask.lower()
    assert S.rent_share not in rig.case().slots


async def test_noise_keeps_the_unclear_ladder(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={"Banana.": x()}))
    await at(rig, "ask.rent")
    assert keys(await rig.say("Banana.")) == ["reprompt.unclear", "ask.rent"]
    await rig.say("uh")  # noise between two unclear answers changes nothing
    second = await rig.say("Banana.")
    assert "reprompt.unclear" not in keys(second)
    assert rig.case().slots[S.rent_share].state == "unclear"


async def test_a_repeat_request_hears_the_last_reply(rig) -> None:
    await at(rig, "ask.rent")
    before = await rig.say("uh")
    for text in ("sorry what", "what?", "hello?", "say that again?"):
        again = await rig.say(text)
        assert again.say == before.say and again.ask == before.ask, text
    assert S.rent_share not in rig.case().slots


async def test_noise_said_over_the_reply_reasks(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("[inaudible]", interrupted=True)
    assert keys(reply) == ["reprompt.after_interrupt", "ask.rent"]


async def test_background_speech_is_noise(rig_factory) -> None:
    tv = "tonight's jackpot is now four hundred million dollars"
    rig = rig_factory(understanding=FakeUnderstanding(extra={tv: x()}))
    await at(rig, "ask.rent")
    reply = await rig.say(tv)
    assert keys(reply) == ["reprompt.unclear", "ask.rent"]
    assert S.rent_share not in rig.case().slots
    assert "reprompt.unclear" not in rig.session().last_keys  # no unclear answer


async def test_background_goodbye_does_not_end_the_call(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("thanks for watching everybody, see you tomorrow, bye bye")
    assert not reply.end and keys(reply) == ["crisis.continue_or_stop"]


async def test_a_long_stop_request_is_never_background(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("Please end this call now, no more questions here")
    assert reply.end and keys(reply) == ["stop.goodbye"]


async def test_a_goodbye_after_other_talk_is_asked_about_first(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("Okay so I think that's it for me, bye")
    assert keys(reply) == ["crisis.continue_or_stop"] and not reply.end
    reply = await rig.say("Keep going.")
    assert not reply.end and keys(reply)[-1] == "ask.rent"


async def test_a_low_confidence_bare_stop_is_asked_about_first(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("stop", confidence=0.5)
    assert keys(reply) == ["crisis.continue_or_stop"] and not reply.end
    reply = await rig.say("Stop.")
    assert keys(reply) == ["stop.goodbye"] and reply.end


async def test_a_clear_stop_still_ends_at_once(rig) -> None:
    await at(rig, "ask.rent")
    reply = await rig.say("I have to go, bye")
    assert keys(reply) == ["stop.goodbye"] and reply.end


async def test_a_model_timeout_on_background_speech_is_no_failure(rig_factory) -> None:
    tv = "and the Giants won it four to two in the ninth"
    rig = rig_factory(understanding=FakeUnderstanding(status="timeout"))
    await at(rig, "ask.rent")
    for _ in range(2):
        reply = await rig.say(tv)
        assert keys(reply) == ["reprompt.unclear", "ask.rent"]
    assert rig.session().llm_failures == 0 and not rig.session().closed_mode
