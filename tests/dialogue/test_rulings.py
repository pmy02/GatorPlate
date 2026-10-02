"""The conversation rulings of docs/SPEC.md §3 and docs/BRAIN_API.md §5-§7 that the brain enforces: the 40-word
phone opening, single keypad keys, the apply-today rule, flip.intro, explicit confirms only for the four critical
money slots, no read-back of cash on hand, the crisis choice and the close-phase "that's all"; plus the
never-asked slot roommates_count (docs/SPEC.md §3.10)."""

from __future__ import annotations

import re

import pytest

from gatorplate.contracts.common import Channel, Lang, Phase, Tier
from gatorplate.contracts.slots import Slot, SlotName
from gatorplate.dialogue.budget import count_words
from gatorplate.dialogue.machine import FLIP_KEYS
from gatorplate.dialogue.policy import Ctx
from gatorplate.dialogue.templates import Step
from tests.dialogue.replay import ROOT, phone_reply_problems
from tests.dialogue.support import FakeUnderstanding
from tests.dialogue.test_flows import consented, maria_to_rent
from tests.dialogue.test_global_intents import at, keys, x

S = SlotName
MARIA = ["Yes, that's fine.", "I'm an SF State undergrad, a junior, and I'm taking 12 units.",
         "I'm 20, and I live with two roommates.", "Separately.",
         "I work at the campus library, about 900 a month. Nobody gives me cash.", "Eleven hundred.", "No.",
         "About a thousand.", "No, thanks."]
KEYPAD_ENTRY = re.compile(r"\bpound\b|\bhash\b|\bkeypad\b|\btype\b|\bdial\b|\benter (?:the|your|an?) "
                          r"(?:amount|number|age|units?)\b|\bdigits?\b", re.IGNORECASE)


async def test_phone_opening_is_the_forty_word_text(rig) -> None:
    reply = await rig.start()
    assert reply.say == ("Hi, this is GatorPlate, a student-built AI assistant, not an official SF State service. "
                         "An AI turns what you say into text to check CalFresh for you; the call audio isn't recorded.")
    assert reply.ask == "Okay to start? Say yes, or press one."
    assert count_words(reply.say + " " + reply.ask) == 40
    assert not reply.interruptible and not phone_reply_problems(reply, ["consent.ask"], start=True)


def test_no_phone_text_asks_for_a_typed_entry(rig) -> None:
    for key, msg in rig.brain.bank.messages[Lang.en].items():
        for form in ("main", "closed", "short"):
            node = msg if form == "main" else msg.get(form)
            if not isinstance(node, dict):
                continue
            for field in ("phone", "all"):
                for variant in node.get(field) or []:
                    text = variant if isinstance(variant, str) else " ".join(v or "" for v in variant.values())
                    assert not KEYPAD_ENTRY.search(text), (key, form, text)


@pytest.mark.parametrize(("tier", "code", "apply_today"), [
    (Tier.likely, "likely", True),
    (Tier.coordinator, "coordinator.shared_household", True),
    (Tier.coordinator, "coordinator.grad_no_exemption", True),
    (Tier.coordinator, "coordinator.unresolved", True),
    (Tier.coordinator, "coordinator.parent_household", False),
    (Tier.other_help, "other_help.status", False),
    (Tier.other_help, "other_help.over_gross_limit", False),
    (None, "info.already_receiving", False),
    (None, "info.interview_waiting", False),
])
async def test_apply_today_rule(rig, tier, code: str, apply_today: bool) -> None:
    await rig.start()
    session = rig.session()
    case = rig.case()
    case.tier, case.reason_code = tier, code
    ctx = Ctx(call_id=rig.call_id, case=case, session=session, now=rig.clock.now(), today=rig.clock.today(), turn=3,
              channel=Channel.phone, settings=rig.settings)
    steps = [s.key for s in rig.brain.policy.card_steps(ctx)]
    assert ("first_month.apply_today" in steps) is apply_today
    assert steps[-1] == "card.phone_code" and case.card is not None


async def test_maria_flip_reply_carries_flip_intro(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria_to_rent(rig)
    reply = await rig.say("Eleven hundred.")
    assert keys(reply) == ["readback.rent", "flip.intro", "flip.rent_paid_by_others"]
    assert count_words(reply.say + " " + reply.ask) <= 25


async def test_flip_intro_is_dropped_when_it_does_not_fit(rig) -> None:
    await consented(rig)
    session, case = rig.session(), rig.case()
    case.slots[S.rent_share] = Slot(value="1975.00", state="clear")
    ctx = Ctx(call_id=rig.call_id, case=case, session=session, now=rig.clock.now(), today=rig.clock.today(), turn=6,
              channel=Channel.phone, settings=rig.settings)
    steps = [Step("readback.rent"), Step("flip.intro"), Step("flip.other_utils")]
    rendered = rig.brain._render(ctx, steps, Lang.en)
    kept, out = rig.brain._fit(ctx, steps, Lang.en, rendered)
    assert [s.key for s in kept] == ["readback.rent", "flip.other_utils"]
    assert count_words(out.say + " " + (out.ask or "")) <= 25


async def test_low_confidence_confirms_a_critical_amount(rig) -> None:
    await at(rig, "ask.income")
    reply = await rig.say("I work at the campus library, about 900 a month. Nobody gives me cash.", confidence=0.6)
    assert keys(reply) == ["confirm.money"] and reply.expect == "confirm" and reply.say == ""
    assert "nine hundred dollars a month" in reply.ask
    assert rig.case().asked[-1].kind == "confirm"
    yes = await rig.key("1")
    assert keys(yes) == ["ack.short", "ask.rent"]
    item = rig.case().slots[S.earned_monthly]
    assert item.confirmed and item.state == "clear"


async def test_teen_ty_rent_is_confirmed_once(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "Fifteen hundred.": x(("rent_share", "1500", "month", "Fifteen hundred"))}))
    await at(rig, "ask.rent")
    first = await rig.say("Fifteen hundred.")
    assert keys(first) == ["confirm.money"] and "fifteen hundred dollars a month" in first.ask
    assert rig.session().confirms[S.rent_share] == 1
    second = await rig.key("2")  # a bare no: the value stays unclear with a yellow line, no second confirm
    assert "confirm.money" not in keys(second)
    case = rig.case()
    assert case.slots[S.rent_share].state == "unclear"
    assert [y.code for y in case.yellow_lines] == ["unclear.rent_share"]


async def test_correction_during_confirm_is_read_back(rig) -> None:
    await at(rig, "ask.income", channel="web", lang="es")
    session = rig.session()
    from gatorplate.contracts.extraction import PendingQuestion
    from gatorplate.contracts.slots import Slot

    case = rig.case()
    case.slots[S.rent_share] = Slot(value="1100.00", state="unclear", heard="mil cien")
    rig.cases.save(case)
    session.pending = PendingQuestion(key="confirm.money", slots=[S.rent_share], kind="confirm")
    session.phase = Phase.housing
    session.confirms = {S.rent_share: 1}
    rig.sessions.put(session)
    reply = await rig.say("No, espera, son mil doscientos, no mil cien.", lang="es")
    assert keys(reply)[0] == "readback.rent" and "hold.ok" not in keys(reply)
    item = rig.case().slots[S.rent_share]
    assert item.value == "1200.00" and item.changed_from == "1100.00" and item.heard_en


async def test_non_critical_teen_ty_is_accepted_as_heard(rig) -> None:
    await at(rig, "ask.level_units")
    reply = await rig.say("Nineteen, and I live with my mom.")
    assert "confirm.money" not in keys(reply)
    assert rig.case().slots[S.age].value == "19"


async def test_cash_on_hand_is_never_read_back_or_confirmed(rig_factory) -> None:
    rig = rig_factory(card_delivery="code", short_codes=["481206"])
    await rig.start()
    seen: list[str] = []
    for text in ("Yeah, sure.", "I'm a senior at SF State, twelve units.",
                 "I'm 24. I don't live with my parents. I've been sleeping on a friend's couch since August, and I "
                 "buy my own food.", "I don't have a job right now, and nobody gives me money.", "No, nothing."):
        seen += keys(await rig.say(text))
    reply = await rig.say("Like forty bucks.", confidence=0.6)
    assert keys(reply) == ["expedited.yes", "first_month.apply_today", "card.phone_code"]
    assert "readback.cash" not in seen + keys(reply) and "confirm.money" not in keys(reply)


async def test_crisis_choice_has_two_options(rig) -> None:
    await at(rig, "ask.rent", channel="web")
    reply = await rig.say("Honestly, sometimes I think about hurting myself.")
    assert reply.expect == "choice" and reply.choices == ["Keep going", "Stop here"]


async def test_under_18_with_a_parent_is_the_parent_household(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "I'm 17 and I live with my parents.": x(("age", "17"), ("lives_with_parent", "true"))}))
    await consented(rig)
    await rig.say("I'm an SF State undergrad, a junior, and I'm taking 12 units.")
    reply = await rig.say("I'm 17 and I live with my parents.")
    assert keys(reply)[0] == "result.coordinator.parent_household"
    assert "first_month.apply_today" not in keys(reply)


async def test_sofia_gets_no_amount_and_no_apply_today(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await rig.start(channel="web", lang="es")
    for text in ("Sí, está bien.", "Estudio una licenciatura en SF State y tomo doce unidades."):
        await rig.say(text, lang="es")
    reply = await rig.say("Tengo diecinueve años y vivo con mis papás.", lang="es")
    assert keys(reply) == ["result.coordinator.parent_household", "card.web", "close.anything_else"]
    assert reply.card_url and reply.choices == ["No, gracias"] and "(415) 338-1203" in reply.display
    assert "cuatro uno cinco" in reply.say


# ------------------------------------------------------------------------------------------ roommates_count

async def test_roommates_count_is_stored_never_asked_or_read_back(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await consented(rig)
    await rig.say("I'm an SF State undergrad, a junior, and I'm taking 12 units.")
    reply = await rig.say("I'm 20, and I live with two roommates.")
    assert keys(reply) == ["ack.short", "ask.household_food_roommates"]
    item = rig.case().slots[S.roommates_count]
    assert item.value == "2" and item.state == "clear" and not item.confirmed
    event = rig.events.events[-1]
    assert S.roommates_count in event.changed_slots


async def test_four_roommates(rig) -> None:
    await at(rig, "ask.level_units")
    await rig.say("I live with four roommates.")
    assert rig.case().slots[S.roommates_count].value == "4"


def test_roommates_count_is_never_a_question_or_a_flip(rig) -> None:
    bank = rig.brain.bank
    for lang in (Lang.en, Lang.es):
        for key in bank.messages[lang]:
            for form in ("main", "closed"):
                expect = bank.expect(key, form, lang) or {}
                assert "roommates_count" not in (expect.get("slots") or []), key
    assert S.roommates_count not in FLIP_KEYS
    assert "roommates_count" not in bank.confirm_policy["confirm_slots"]
    from gatorplate.dialogue.machine import PHASES

    assert all(S.roommates_count not in spec.goals for spec in PHASES.values())


async def test_maria_call_unchanged_by_the_upgrade(rig_factory) -> None:
    """The call stays as it was: nine student turns, the same keys as contracts/examples/maria_phone.json."""
    import json

    example = json.loads((ROOT / "contracts" / "examples" / "maria_phone.json").read_text(encoding="utf-8"))
    want = [ex["keys"] for ex in example["scenarios"][0]["exchanges"] if ex["step"] in ("start", "turn")]
    rig = rig_factory(card_delivery="screen")
    got = [keys(await rig.start())] + [keys(await rig.say(text)) for text in MARIA]
    assert got == want
    case = rig.case()
    assert case.turn_count == 9 and case.program_answers == {} and case.program_progress == {}

