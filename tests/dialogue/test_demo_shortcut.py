"""The live demo's shortcut (GP_DEMO_SHORTCUT, only with GP_DEMO_MODE, phone only): the short opening, the demo
script's answers filled in at consent (never before), the caller's own value winning, the result reply ending the call,
and nothing changed with the setting off or on the web."""

from __future__ import annotations

import json
from pathlib import Path

from gatorplate.contracts.brain_api import EndRequest
from gatorplate.contracts.common import SlotSource, SlotState
from gatorplate.contracts.slots import SlotName
from gatorplate.dialogue.budget import count_words
from gatorplate.dialogue.policy import DEMO_SHORTCUT_SLOTS
from tests.dialogue.support import FakeUnderstanding
from tests.dialogue.test_global_intents import keys

ROOT = Path(__file__).resolve().parents[2]
BANK = json.loads((ROOT / "data" / "content" / "sentences.en.json").read_text(encoding="utf-8"))["messages"]
MARIA = json.loads((ROOT / "tests" / "e2e" / "scripts" / "maria_g1.json").read_text(encoding="utf-8"))
OPENING_ASK = "Okay to start? Say yes, or press one."
FIVE = [
    ("Yes, that's fine.", ["ack.short", "ask.level_units"]),
    ("I'm an SF State undergraduate, a junior, and I'm taking 12 units.", ["ack.short", "ask.income"]),
    ("I work at the campus library, about 900 a month. Nobody gives me cash.", ["readback.earned", "ask.rent"]),
    ("Eleven hundred.", ["readback.rent", "flip.intro", "flip.rent_paid_by_others"]),
    ("No.", ["result.likely", "card.phone_screen", "close.goodbye"]),
]


def shortcut_rig(rig_factory, *, on: bool = True, demo_mode: bool = True, **kwargs):
    rig = rig_factory(card_delivery="screen", **kwargs)
    rig.settings = rig.settings.model_copy(update={"demo_shortcut": on, "demo_mode": demo_mode})
    rig.brain.settings = rig.settings
    return rig


def test_prefill_is_the_demo_scripts_answers() -> None:
    final = MARIA["final"]["slots"]
    assert {slot.value: raw for slot, raw in DEMO_SHORTCUT_SLOTS.items()} == {
        name: final[name] for name in ("age", "lives_with_parent", "roommates", "roommates_count", "household_food",
                                       "cash_on_hand")}


def test_opening_word_counts() -> None:
    msg = BANK["consent.ask"]
    base, short = msg["phone"][0], msg["demo"]["phone"][0]
    assert short["ask"] == base["ask"] == OPENING_ASK
    for phrase in ("GatorPlate", "AI", "student-built", "not an official SF State service", "into text", "CalFresh",
                   "audio isn't recorded"):
        assert phrase in short["say"]
    assert count_words(f"{short['say']} {short['ask']}") <= 34 < count_words(f"{base['say']} {base['ask']}") <= 40
    assert set(msg["demo"]) == {"phone"}  # the web opening has no demo form


async def test_five_utterance_demo_call(rig_factory) -> None:
    rig = shortcut_rig(rig_factory)
    opening = await rig.start()
    assert keys(opening) == ["consent.ask"]
    assert opening.say == BANK["consent.ask"]["demo"]["phone"][0]["say"] and opening.ask == OPENING_ASK
    assert rig.case().slots == {}  # nothing before consent
    replies = []
    for text, want in FIVE:
        reply = await rig.say(text)
        assert keys(reply) == want, text
        replies.append(reply)
    case = rig.case()
    for slot, raw in DEMO_SHORTCUT_SLOTS.items():
        item = case.slots[slot]
        assert (item.value, item.state, item.source, item.heard) == (raw, SlotState.clear, SlotSource.seed, None)
    asked = {s for a in case.asked for s in a.slots}
    assert asked.isdisjoint(DEMO_SHORTCUT_SLOTS)
    assert [a.slots for a in case.asked if a.kind == "flip"] == [[SlotName.rent_paid_by_others_to_landlord]]
    last = replies[-1]
    assert last.end and last.end_reason == "completed" and last.ask is None and last.hold_s == 0
    assert not last.interruptible and last.card_url is None
    assert "three hundred six dollars a month" in last.say and count_words(last.say) <= 45
    assert case.tier == "likely" and case.estimate_monthly == 306 and case.card is not None
    assert case.expedited_possible == "no" and not [y for y in case.yellow_lines if y.resolved is None]
    await rig.brain.end(rig.call_id, EndRequest(v=1, reason="caller_hangup", duration_ms=60000, turns=5))
    ended = rig.case()
    assert ended.tier == "likely" and ended.estimate_monthly == 306 and ended.card is not None
    assert not ended.ended_early


async def test_declined_call_keeps_no_answers(rig_factory) -> None:
    rig = shortcut_rig(rig_factory)
    await rig.start()
    reply = await rig.key("2")
    assert reply.end and reply.end_reason == "declined"
    case = rig.case()
    assert case.consent.given is False and case.slots == {}


async def test_caller_value_wins(rig_factory) -> None:
    said = "Actually I'm nineteen."
    extraction = {"observations": [{"slot": "age", "value": "19", "period": None, "hours_per_week": None,
                                    "state": "clear", "quote": "I'm nineteen", "quote_en": None}],
                  "intents": [], "answered_pending": "no", "lang": "en", "side_question": None,
                  "requested_language": None, "redactions": []}
    rig = shortcut_rig(rig_factory, understanding=FakeUnderstanding(extra={said: extraction}))
    await rig.start()
    await rig.say("Yes, that's fine.")
    await rig.say(said)
    item = rig.case().slots[SlotName.age]
    assert (item.value, item.source, item.changed_from) == ("19", SlotSource.llm, "20")


async def test_flag_off_or_web_is_unchanged(rig_factory) -> None:
    for rig in (shortcut_rig(rig_factory, on=False), shortcut_rig(rig_factory, demo_mode=False)):
        opening = await rig.start()
        assert opening.say == BANK["consent.ask"]["phone"][0]["say"] and opening.ask == OPENING_ASK
        for turn in MARIA["turns"][1:]:
            assert keys(await rig.say(turn["user"])) == turn["expect_keys"], turn["user"]
        assert rig.case().slots[SlotName.age].source != SlotSource.seed
    web = shortcut_rig(rig_factory)
    web.call_id = "0a000000000000000000000000000002"
    opening = await web.start(channel="web")
    assert opening.say == BANK["consent.ask"]["web"][0]["say"]
    await web.say("Yes, that's fine.")
    assert SlotName.age not in web.case().slots
