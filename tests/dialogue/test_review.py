"""Adversarial review of the dialogue: the paths a judge or a real student takes off the golden script.

A bare yes or no to the one explicit confirm (the understanding reports it as "true" / "false" on the confirmed
slot); a detour (a person, crisis, delete) or a correction while a flip or the cash question is open (the question is
asked again, never answered by default); corrections after the result (the rules run again and the new result is
said); unclear answers that are given up (conservative value + a yellow line, docs/SPEC.md §3.7 and §5.6); a split
reply whose question arrives on the next turn (still a case question); band choices the understanding can read; the
web card link after the end; nothing kept from a call without consent (docs/SPEC.md §3, §8).
"""

from __future__ import annotations

from gatorplate.contracts.brain_api import EndRequest
from gatorplate.contracts.common import Phase
from gatorplate.contracts.extraction import PendingQuestion
from gatorplate.contracts.slots import SlotName
from tests.dialogue.replay import phone_reply_problems
from tests.dialogue.support import FakeUnderstanding
from tests.dialogue.test_global_intents import at, keys, x

S = SlotName

MARIA = ("Yes, that's fine.", "I'm an SF State undergrad, a junior, and I'm taking 12 units.",
         "I'm 20, and I live with two roommates.", "Separately.",
         "I work at the campus library, about 900 a month. Nobody gives me cash.", "Eleven hundred.", "No.",
         "About a thousand.")
FIFTEEN = {"Actually my rent is fifteen hundred.": x(("rent_share", "1500", "month", "fifteen hundred"),
                                                     intents=["correction"])}


async def maria(rig, upto: int) -> None:
    """Maria's call up to (not including) answer number `upto` (0 = consent ... 7 = the cash answer)."""
    await rig.start()
    for text in MARIA[:upto]:
        await rig.say(text)


def flips(case) -> list[str]:
    return [a.slots[0].value for a in case.asked if a.kind == "flip"]


# ------------------------------------------------------------------------------------------ the one explicit confirm

async def test_a_bare_yes_to_the_confirm_confirms_the_amount(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "Fifteen hundred.": x(("rent_share", "1500", "month", "Fifteen hundred"))}))
    await at(rig, "ask.rent")
    assert keys(await rig.say("Fifteen hundred.")) == ["confirm.money"]
    reply = await rig.say("Yes.")
    assert "reprompt.unclear" not in keys(reply) and "confirm.money" not in keys(reply)
    item = rig.case().slots[S.rent_share]
    assert item.value == "1500.00" and item.confirmed and item.state == "clear"


async def test_a_bare_no_to_the_confirm_never_zeroes_the_amount(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "Fifteen hundred.": x(("rent_share", "1500", "month", "Fifteen hundred"))}))
    await at(rig, "ask.rent")
    await rig.say("Fifteen hundred.")
    reply = await rig.say("No.")
    assert "confirm.money" not in keys(reply)
    case = rig.case()
    item = case.slots[S.rent_share]
    assert item.value == "1500.00" and item.state == "unclear" and item.changed_from is None
    assert [y.code for y in case.yellow_lines] == ["unclear.rent_share"]


# ------------------------------------------------------------------------------------------ detours keep the question

async def test_a_person_at_the_flip_then_keep_going_asks_the_flip_again(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria(rig, 6)
    assert keys(await rig.say("Can I talk to a real person?")) == ["human.request"]
    again = await rig.say("Yes.")
    assert keys(again) == ["flip.rent_paid_by_others"] and again.expect == "yes_no"
    assert rig.session().flips_asked == 1
    heat = await rig.say("Yes, my parents pay all of it straight to the landlord.")
    assert keys(heat) == ["ack.short", "flip.heat_cool"]
    rig.understanding.table["No, no heating bill."] = x(("heat_cool", "false"))
    result = await rig.say("No, no heating bill.")
    assert keys(result)[0] == "result.likely" and rig.case().estimate_monthly == 155  # G1-b, not the default $306
    assert flips(rig.case()) == ["rent_paid_by_others_to_landlord", "heat_cool"]


async def test_crisis_at_the_cash_question_then_keep_going_asks_it_again(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria(rig, 7)
    await rig.say("I don't really see the point of living anymore.")
    again = await rig.key("1")
    assert keys(again) == ["expedited.intro_cash"]
    done = await rig.say("About a thousand.")
    assert keys(done)[:2] == ["first_month.apply_today", "card.phone_screen"]
    assert rig.case().slots[S.cash_on_hand].value == "1000.00"


async def test_delete_cancelled_at_the_flip_asks_the_flip_again(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria(rig, 6)
    assert keys(await rig.say("Please delete my data.")) == ["delete.confirm_ask"]
    reply = await rig.key("2")
    assert keys(reply) == ["delete.cancelled", "flip.rent_paid_by_others"]


async def test_a_correction_instead_of_the_flip_answer_asks_the_flip_again(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        "Wait, my rent is actually 1200.": x(("rent_share", "1200", "month", "1200"), intents=["correction"])}))
    await maria(rig, 6)
    reply = await rig.say("Wait, my rent is actually 1200.")
    assert keys(reply) == ["readback.rent", "flip.rent_paid_by_others"]
    assert rig.case().slots[S.rent_share].changed_from == "1100.00"
    assert rig.session().flips_asked == 1 and flips(rig.case()) == ["rent_paid_by_others_to_landlord"]


# ------------------------------------------------------------------------------------------ after the result

async def test_a_correction_at_the_cash_question_keeps_the_cash_question(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        "Actually my rent is 1250 a month.": x(("rent_share", "1250", "month", "1250 a month"),
                                               intents=["correction"])}))
    await maria(rig, 7)
    reply = await rig.say("Actually my rent is 1250 a month.")
    assert keys(reply)[0] == "readback.rent" and keys(reply)[-1] == "expedited.intro_cash"
    assert rig.session().phase == Phase.expedited


async def test_a_correction_at_the_close_runs_the_rules_and_says_the_new_result(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        "Actually I make 2000 a month.": x(("earned_monthly", "2000", "month", "2000 a month"),
                                           intents=["correction"])}))
    await maria(rig, 8)
    before = rig.case().estimate_monthly
    reply = await rig.say("Actually I make 2000 a month.")
    case = rig.case()
    assert case.slots[S.earned_monthly].changed_from == "900.00"
    assert case.estimate_monthly != before  # the rules ran again
    assert keys(reply)[:2] == ["readback.earned", "result.likely"] and keys(reply)[-1] == "close.anything_else" or \
        rig.session().deferred_keys  # a long reply is split for the budget
    assert not phone_reply_problems(reply, keys(reply))


async def test_a_confirm_at_the_close_is_answered_not_taken_as_goodbye(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra=FIFTEEN))
    await maria(rig, 8)
    assert keys(await rig.say("Actually my rent is fifteen hundred.")) == ["confirm.money"]
    reply = await rig.say("No.")
    assert not reply.end and keys(reply)[-1] == "close.anything_else"
    item = rig.case().slots[S.rent_share]
    assert item.value == "1500.00" and item.state == "unclear"
    assert any(y.code == "unclear.rent_share" for y in rig.case().yellow_lines)


async def test_volunteered_cash_still_gets_the_outlook(rig_factory) -> None:
    jamal = "I don't have a job right now, nobody gives me money, and I have like forty bucks."
    rig = rig_factory(card_delivery="code", short_codes=["481206"], understanding=FakeUnderstanding(extra={
        jamal: x(("earned_monthly", "0", "month"), ("other_cash_monthly", "0", "month"), ("cash_on_hand", "40"))}))
    await rig.start()
    for text in ("Yeah, sure.", "I'm a senior at SF State, twelve units.",
                 "I'm 24. I don't live with my parents. I've been sleeping on a friend's couch since August, and I "
                 "buy my own food.", jamal):
        await rig.say(text)
    reply = await rig.say("No, nothing.")
    assert "expedited.intro_cash" not in keys(reply)  # already answered
    said = keys(reply) + (keys(await rig.say("Okay.")) if rig.session().deferred_keys else [])
    assert "expedited.yes" in said


# ------------------------------------------------------------------------------------------ unclear answers

async def test_a_given_up_answer_leaves_a_yellow_line(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={"Banana.": x()}))
    await at(rig, "ask.rent")
    await rig.say("Banana.")
    await rig.say("Banana.")
    case = rig.case()
    assert case.slots[S.rent_share].state == "unclear"
    assert [y.code for y in case.yellow_lines if y.resolved is None] == ["unclear.rent_share"]


async def test_a_given_up_cash_answer_leaves_a_yellow_line(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={"Banana.": x()}))
    await maria(rig, 7)
    await rig.say("Banana.")
    reply = await rig.say("Banana.")
    assert keys(reply)[0] == "first_month.apply_today"
    assert any(y.code == "unclear.cash_on_hand" for y in rig.case().yellow_lines)


# ------------------------------------------------------------------------------------------ split replies and bands

async def test_a_question_delivered_after_a_split_is_a_case_question(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria(rig, 7)
    s = rig.session()  # the result reply went out without its question (budget): the cash question follows
    case = rig.case()
    case.asked = [a for a in case.asked if a.key != "expedited.intro_cash"]
    rig.cases.save(case)
    s.deferred_keys = ["expedited.intro_cash"]
    rig.sessions.put(s)
    reply = await rig.silence(1)
    assert keys(reply) == ["expedited.intro_cash"]
    last = rig.case().asked[-1]
    assert last.key == "expedited.intro_cash" and last.kind == "standard" and last.slots == [S.cash_on_hand]
    assert rig.session().pending.key == "expedited.intro_cash"


async def test_a_flip_delivered_after_a_split_keeps_its_reason(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria(rig, 5)
    await rig.say("Eleven hundred.")
    case = rig.case()
    case.asked = [a for a in case.asked if a.kind != "flip"]
    rig.cases.save(case)
    s = rig.session()
    s.deferred_keys = ["flip.rent_paid_by_others"]
    rig.sessions.put(s)
    reply = await rig.say("Okay.")
    assert keys(reply) == ["flip.rent_paid_by_others"]
    last = rig.case().asked[-1]
    assert last.kind == "flip" and last.reason == "could change the estimate by $151: $155 or $306"


async def test_band_choices_reach_the_understanding_with_their_numbers(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={"I'm not sure.": x(intents=["dont_know"])}))
    await at(rig, "ask.income")
    await rig.say("I'm not sure.")
    pending = rig.session().pending
    assert pending.key == "ask.income_band"
    assert pending.choices and not any("{" in c for c in pending.choices)
    assert "$1,000" in pending.choices[0]


# ------------------------------------------------------------------------------------------ the end of a call

async def test_the_web_closing_reply_keeps_the_card_link(rig_factory) -> None:
    rig = rig_factory()
    await rig.start(channel="web", lang="es")
    for text in ("Sí, está bien.", "Estudio una licenciatura en SF State y tomo doce unidades.",
                 "Tengo diecinueve años y vivo con mis papás.", "No, gracias."):
        last = await rig.say(text)
    assert last.end and last.card_url
    after = await rig.say("Hola?")
    assert after.end and after.card_url == last.card_url and after.display == ""


async def test_a_declined_call_keeps_nothing_said_before_consent(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "What can EBT buy?": x(intents=["side_question"], side_question="What can EBT buy?")}))
    await rig.start()
    assert keys(await rig.say("What can EBT buy?")) == ["side_question.noted", "consent.reask"]
    reply = await rig.key("2")
    assert reply.end_reason == "declined"
    case = rig.case()
    assert case.yellow_lines == [] and case.slots == {} and case.consent.given is False


async def test_a_hangup_before_consent_keeps_nothing_said(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "What can EBT buy?": x(intents=["side_question"], side_question="What can EBT buy?")}))
    await rig.start()
    await rig.say("What can EBT buy?")
    await rig.brain.end(rig.call_id, EndRequest(v=1, reason="caller_hangup"))
    case = rig.case()
    assert case.yellow_lines == [] and not case.live


async def test_the_delete_reply_has_no_card_link(rig_factory) -> None:
    rig = rig_factory()
    await rig.start(channel="web", lang="es")
    for text in ("Sí, está bien.", "Estudio una licenciatura en SF State y tomo doce unidades.",
                 "Tengo diecinueve años y vivo con mis papás."):
        await rig.say(text)
    assert rig.case().card is not None
    ask = await rig.say("Borra mis datos, por favor.", lang="es")
    assert keys(ask) == ["delete.confirm_ask"] and ask.card_url  # the card still exists while asking
    done = await rig.say("Sí.", lang="es", typed=False)
    assert keys(done) == ["delete.done"] and done.end and done.card_url is None
    assert rig.case() is None


class Broken(FakeUnderstanding):
    async def understand(self, **kwargs):  # noqa: ANN003, ANN201 - test double
        raise RuntimeError("provider bug")


async def test_an_understanding_crash_gives_the_closed_question(rig_factory) -> None:
    rig = rig_factory(understanding=Broken())
    await at(rig, "ask.rent")
    reply = await rig.say("Something about my rent.")
    assert keys(reply) == ["ask.rent"] and "press one" in reply.ask.lower()
    assert rig.session().llm_failures == 1


async def test_short_term_memory_is_dropped_when_the_brain_ends_the_call(rig_factory) -> None:
    rig = rig_factory(card_delivery="screen")
    await maria(rig, 8)
    assert rig.brain._memory.get(rig.call_id)
    bye = await rig.say("No, thanks.")
    assert bye.end and rig.call_id not in rig.brain._memory


async def test_pending_question_survives_a_confirm_detour_kind(rig_factory) -> None:
    """A person request during the confirm: 'keep going' asks the confirm again (one explicit confirm per slot)."""
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "Fifteen hundred.": x(("rent_share", "1500", "month", "Fifteen hundred"))}))
    await at(rig, "ask.rent")
    await rig.say("Fifteen hundred.")
    await rig.say("Can I talk to a real person?")
    reply = await rig.key("1")
    assert keys(reply) == ["confirm.money"]
    assert rig.session().confirms[S.rent_share] == 1
    assert isinstance(rig.session().pending, PendingQuestion) and rig.session().pending.slots == [S.rent_share]


async def test_a_guard_hit_on_a_goodbye_does_not_end_the_call(settings_test, tmp_path) -> None:
    import json
    import shutil

    from gatorplate.dialogue import Brain
    from tests.dialogue.conftest import make_rig
    from tests.dialogue.replay import ROOT

    content = tmp_path / "content"
    shutil.copytree(ROOT / "data" / "content", content)
    bank = json.loads((content / "sentences.en.json").read_text(encoding="utf-8"))
    bank["messages"]["close.goodbye"]["phone"] = ["You're approved! Goodbye."]
    (content / "sentences.en.json").write_text(json.dumps(bank), encoding="utf-8")
    rig = make_rig(settings_test.model_copy(update={"card_delivery": "screen"}), card_delivery="screen")
    rig.brain = Brain(settings=rig.settings, clock=rig.clock, ids=rig.ids, rules=rig.rules,
                      understanding=rig.understanding, cases=rig.cases, sessions=rig.sessions, live=rig.live,
                      events=rig.events, cards=None, content_dir=content)
    await maria(rig, 8)
    reply = await rig.say("No, thanks.")
    assert keys(reply) == ["error.generic"] and not reply.end and reply.end_reason is None
    assert rig.case().ended_reason is None and rig.session().ended_by_brain is None


def test_disclosure_answers_never_start_with_yes_or_no() -> None:
    """answer.is_ai also answers "Is this a real person?" and "Is this official?" (docs/SPEC.md §3.3 row 6), and
    answer.is_recorded also answers "Where does my information go?" (§4.10 item 10.7): a leading yes or no would say
    the opposite of the truth to one of them."""
    import json

    from tests.dialogue.replay import ROOT

    for lang in ("en", "es"):
        bank = json.loads((ROOT / "data" / "content" / f"sentences.{lang}.json").read_text(encoding="utf-8"))
        for key in ("answer.is_ai", "answer.is_recorded"):
            message = bank["messages"][key]
            for channel in ("all", "phone", "web"):
                for variant in message.get(channel) or []:
                    text = variant if isinstance(variant, str) else (variant.get("say") or "")
                    first = text.split()[0].strip(",.").lower()
                    assert first not in ("yes", "no", "sí", "si"), (lang, key, text)


async def test_is_this_a_real_person_is_answered_truthfully(rig) -> None:
    await at(rig, "ask.level_units")
    reply = await rig.say("Is this a real person?")
    assert keys(reply)[0] == "answer.is_ai"
    assert "AI" in reply.say and not reply.say.lower().startswith("yes")


# ------------------------------------------------------------------------------------------ income bands (docs/SPEC.md §4.4 item 4.11)

def _assume_earned(rig, value: str = "2000.00") -> None:
    from gatorplate.contracts.common import SlotState
    from gatorplate.contracts.slots import Slot

    case = rig.case()
    case.slots[S.earned_monthly] = Slot(value=value, display=f"${value[:-3]}", state=SlotState.assumed, turn=1)
    rig.cases.save(case)


async def test_a_band_answer_never_takes_the_gross_limit_route_before_the_flips(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={
        "My mom gives me 900 a month.": x(("other_cash_monthly", "900", "month"))}))
    await at(rig, "ask.income")
    s = rig.session()
    s.pending = PendingQuestion(key="ask.other_cash", slots=[S.other_cash_monthly], kind="number")
    rig.sessions.put(s)
    _assume_earned(rig)  # "between $1,000 and $2,000": the top, assumed
    reply = await rig.say("My mom gives me 900 a month.")
    assert rig.case().reason_code == "other_help.over_gross_limit"  # at the band's top only
    assert not any(k.startswith("result.") for k in keys(reply))  # the question plan narrows the band first
    assert keys(reply)[-1] == "ask.rent"


async def test_no_to_the_earned_split_keeps_the_band_top(rig_factory) -> None:
    rig = rig_factory(understanding=FakeUnderstanding(extra={"No, it's more.": x(("earned_monthly", "0", "month"))}))
    await at(rig, "ask.rent")
    _assume_earned(rig)
    s = rig.session()
    s.phase = Phase.flip
    s.pending = PendingQuestion(key="flip.earned_split", slots=[S.earned_monthly], kind="yes_no")
    rig.sessions.put(s)
    await rig.say("No, it's more.")  # the understanding reads a bare no on a money slot as "0": never the amount
    item = rig.case().slots[S.earned_monthly]
    assert item.value == "2000.00" and item.state == "assumed"


async def test_yes_to_the_earned_split_takes_the_split_point(rig_factory) -> None:
    rig = rig_factory()
    await at(rig, "ask.rent")
    _assume_earned(rig)
    s = rig.session()
    s.phase = Phase.flip
    s.pending = PendingQuestion(key="flip.earned_split", slots=[S.earned_monthly], kind="yes_no")
    rig.sessions.put(s)
    split = rig.brain.policy.band_edges(rig.brain._context(rig.call_id, rig.case(), s, rig.clock.now()),
                                        "flip.earned_split")[0]
    await rig.say("Yes.")
    item = rig.case().slots[S.earned_monthly]
    assert item.value == f"{split:.2f}" and item.state == "assumed"


class SplitRules:
    """Rules double whose question plan asks the work-income split while that answer is a band (as the rules
    module does: an assumed band answer is still open)."""

    def __init__(self, inner) -> None:
        self.inner = inner

    def __getattr__(self, name):  # noqa: ANN001, ANN204 - delegate everything else
        return getattr(self.inner, name)

    def flip_plan(self, case, *, today, budget):  # noqa: ANN001, ANN201
        from gatorplate.contracts.common import Tier
        from gatorplate.contracts.rules_io import FlipCandidate, FlipOutcome

        plan = self.inner.flip_plan(case, today=today, budget=budget)
        item = case.slots.get(S.earned_monthly)
        asked = any(a.kind == "flip" and S.earned_monthly in a.slots for a in case.asked)
        if item is not None and item.state == "assumed" and not asked and budget > 0:
            cand = FlipCandidate(slot=S.earned_monthly, default_value="2000.00", outcomes=[
                FlipOutcome(value="1000.00", tier=Tier.likely, monthly=200, label="Yes"),
                FlipOutcome(value="2000.00", tier=Tier.likely, monthly=25, label="No")],
                tier_changes=False, spread_usd=175, decision="ask", reason="could change the estimate by $175")
            plan = plan.model_copy(update={"ask": [cand, *plan.ask]})
        return plan


async def test_a_band_answer_is_narrowed_by_the_split_question(rig_factory) -> None:
    rig = rig_factory()
    rig.brain.policy.rules = SplitRules(rig.rules)
    await at(rig, "ask.rent")
    _assume_earned(rig)
    reply = await rig.say("Eleven hundred.")
    assert keys(reply)[-1] == "flip.earned_split"


async def test_an_unclear_answer_to_a_flip_about_an_unclear_answer_is_given_up_once(rig_factory) -> None:
    unclear_food = dict(x(), observations=[{"slot": "household_food", "value": "separate", "period": None,
                                            "hours_per_week": None, "state": "unclear", "quote": "kind of both",
                                            "quote_en": None}])
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        "Kind of both, it depends.": unclear_food, "Banana.": x()}))
    await rig.start()
    for text in ("Yes, that's fine.", "I'm an SF State undergrad, a junior, and I'm taking 12 units.",
                 "I'm 20, and I live with two roommates.", "Kind of both, it depends.",
                 "I work at the campus library, about 900 a month. Nobody gives me cash."):
        await rig.say(text)
    assert keys(await rig.say("Eleven hundred."))[-1] == "flip.household_food"
    first = await rig.say("Banana.")
    assert keys(first) == ["reprompt.unclear", "flip.household_food"]
    second = await rig.say("Banana.")
    assert "flip.household_food" not in keys(second)  # given up once, never asked again
    assert sum(1 for a in rig.case().asked if a.key == "flip.household_food") == 2  # the flip and its closed form
    assert any(y.slot == S.household_food for y in rig.case().yellow_lines)


async def test_unclear_answers_left_at_the_result_get_a_line_but_not_the_roommate_count(rig_factory) -> None:
    def unclear(slot: str, value: str, quote: str) -> dict:
        return {"slot": slot, "value": value, "period": None, "hours_per_week": None, "state": "unclear",
                "quote": quote, "quote_en": None}

    level = dict(x(), observations=[{**unclear("level", "undergrad", "SF State"), "state": "clear"},
                                    unclear("units", "12", "like twelve-ish")])
    home = dict(x(), observations=[{**unclear("age", "20", "20"), "state": "clear"},
                                   {**unclear("lives_with_parent", "false", "roommates"), "state": "clear"},
                                   {**unclear("roommates", "true", "roommates"), "state": "clear"},
                                   unclear("roommates_count", "2", "a couple of roommates")])
    rig = rig_factory(card_delivery="screen", understanding=FakeUnderstanding(extra={
        "SF State, like twelve-ish units.": level, "I'm 20 with a couple of roommates.": home}))
    await rig.start()
    for text in ("Yes, that's fine.", "SF State, like twelve-ish units.", "I'm 20 with a couple of roommates.",
                 "Separately.", "I work at the campus library, about 900 a month. Nobody gives me cash.",
                 "Eleven hundred.", "No."):
        await rig.say(text)
    case = rig.case()
    assert case.slots[S.units].state == "unclear" and case.slots[S.roommates_count].state == "unclear"
    codes = [y.code for y in case.yellow_lines]
    assert "unclear.units" in codes and "unclear.roommates_count" not in codes


async def test_live_lines_are_published_before_the_case_update(rig_factory) -> None:
    rig = rig_factory(live=True, card_delivery="screen")
    await maria(rig, 2)
    types = [e.type for e in rig.events.events]
    assert types[:3] == ["case.created", "live.turn", "case.updated"] or types[:2] == ["case.created", "live.turn"]
    last_turn = [e for e in rig.events.events if e.type in ("live.turn", "case.updated")][-3:]
    assert [e.type for e in last_turn] == ["live.turn", "live.turn", "case.updated"]
    assert [e.line.who for e in last_turn[:2]] == ["student", "assistant"]
    assert all(e.line is not None and e.case_id == rig.session().case_id for e in last_turn[:2])


async def test_no_live_events_without_the_live_transcript(rig) -> None:
    await maria(rig, 2)
    assert not any(e.type.startswith("live.") for e in rig.events.events)


async def test_a_request_for_english_on_the_spanish_web_switches_back(rig) -> None:
    await rig.start(channel="web", lang="es")
    await rig.say("Sí, está bien.", lang="es")
    reply = await rig.say("¿Podemos hablar en inglés?", lang="es")
    assert "language.unsupported" not in keys(reply)
    assert reply.lang == "en" and rig.session().lang == "en"
    assert rig.case().language_request.asked == "en" and rig.case().language_request.offered == "switched"
