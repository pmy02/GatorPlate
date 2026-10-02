"""Golden dialogues maria_g1, sofia_g3 and jamal_g4 (tests/e2e/scripts; docs/SPEC.md §3.9) through the Brain.

Per turn: the sentence keys (debug keys), the reply fields, the phone word budget and the case checks the script
lists. After /end: the script's final state (tier, estimate, range, outlook, slots, flips asked with their reason,
skipped questions, yellow lines, card, summary, turns, privacy events, live flag). Run with the development address
and with the deployed one, so the spoken web address never changes a budget split.
"""

from __future__ import annotations

import json

import pytest

from gatorplate.contracts.brain_api import EndRequest
from gatorplate.contracts.common import Channel
from gatorplate.dialogue.budget import WORD_BUDGETS, count_words
from tests.dialogue.conftest import make_rig
from tests.dialogue.replay import SCRIPTS, budget_of, phone_reply_problems, spoken

SCRIPT_IDS = ["maria_g1", "sofia_g3", "jamal_g4"]
BASES = ["http://127.0.0.1:8000", "https://gatorplate.fly.dev"]


def _script(name: str) -> dict:
    return json.loads((SCRIPTS / f"{name}.json").read_text(encoding="utf-8"))


def _check_case(case, checks: dict, label: str) -> None:
    for slot, raw in (checks.get("slots") or {}).items():
        assert case.slots[slot].value == raw, (label, slot, case.slots.get(slot))
    for field in ("tier", "reason_code", "estimate_monthly", "expedited_possible", "estimate_is_floor"):
        if field in checks:
            got = getattr(case, field)
            got = got.value if hasattr(got, "value") else got
            assert got == checks[field], (label, field, got)
    if "estimate_range" in checks:
        assert case.estimate_range is not None and case.estimate_range.model_dump() == checks["estimate_range"], label
    if "asked_last" in checks:
        last = case.asked[-1]
        want = checks["asked_last"]
        assert last.key == want["key"] and last.kind == want["kind"], (label, last)
        assert [s.value for s in last.slots] == want["slots"], (label, last)
        if "reason" in want:
            assert last.reason == want["reason"], (label, last)


@pytest.mark.parametrize("base", BASES)
@pytest.mark.parametrize("name", SCRIPT_IDS)
async def test_golden_dialogue(settings_test, name: str, base: str) -> None:
    script = _script(name)
    env = script["env"]
    settings = settings_test.model_copy(update={"public_base_url": base})
    rig = make_rig(settings, card_delivery=env["GP_CARD_DELIVERY"],
                   short_codes=["481206"] if name == "jamal_g4" else [])
    phone = script["channel"] == "phone"
    said: list[str] = []
    for i, turn in enumerate(script["turns"]):
        label = f"{name}#{i}"
        if turn.get("start"):
            reply = await rig.start(channel=script["channel"], lang=script["lang"])
        else:
            reply = await rig.say(turn["user"], confidence=turn.get("confidence"), lang=script["lang"])
        assert reply.debug is not None and reply.debug.keys == turn["expect_keys"], (label, reply.debug)
        said += reply.debug.keys
        for field, want in turn["reply"].items():
            got = getattr(reply, field)
            if want == "present":
                assert got is not None, (label, field)
            elif want == "null":
                assert got is None, (label, field)
            else:
                got = got.value if hasattr(got, "value") else got
                assert got == want, (label, field, got, want)
        if phone:
            assert not phone_reply_problems(reply, turn["expect_keys"], start=bool(turn.get("start"))), label
            if "budget" in turn:
                text = spoken(reply)
                assert count_words(text) <= WORD_BUDGETS[turn["budget"]], (label, text)
                assert budget_of(turn["expect_keys"], text, start=bool(turn.get("start"))) == turn["budget"], label
        if "case" in turn:
            _check_case(rig.case(), turn["case"], label)
    end = script["end"]
    await rig.brain.end(rig.call_id, EndRequest(v=1, reason=end["reason"], turns=end["turns"],
                                                duration_ms=end["duration_ms"]))
    case = rig.case()
    final = script["final"]
    _check_case(case, final, f"{name} final")
    assert [{"slot": a.slots[0].value, "reason": a.reason} for a in case.asked if a.kind == "flip"] == \
        final["asked_flip"]
    for want in final["skipped"]:
        assert any(s.slot.value == want["slot"] and s.reason == want["reason"] for s in case.skipped), want
    for extra in case.skipped:
        assert any(w["slot"] == extra.slot.value for w in final["skipped"]) or extra.reason in (
            "hard_stop", "not_applicable"), extra
    assert sum(1 for y in case.yellow_lines if y.resolved is None) == final["yellow_open"]
    for want in final.get("yellow", []):
        assert any(y.kind == want["kind"] and y.code == want["code"] and (y.slot.value if y.slot else None)
                   == want.get("slot") and y.reason == want["reason"] for y in case.yellow_lines), want
    assert (case.card is not None) == final["card_created"]
    if "summary" in final:
        assert case.summary == final["summary"]
    assert case.turn_count == final["student_turns"] <= final["max_student_turns"]
    assert [e.kind for e in case.privacy_events] == final["privacy_events"]
    assert case.ended_reason == final["ended_reason"]
    assert case.live is final["live"]
    if "lang" in final:
        assert case.lang.value == final["lang"]
    for slot in final.get("heard_en_present", []):
        assert case.slots[slot].heard_en, slot
    if final.get("amount_said") is False:
        assert not any(k.startswith("result.likely") for k in said)
    if script["channel"] == Channel.web.value:
        assert rig.session().last_reply.card_url is not None
