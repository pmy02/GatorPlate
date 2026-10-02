"""Brain-level replay of contracts/examples (docs/BRAIN_API.md §14) with the fake understanding and debug keys on.

Each 200 exchange must reproduce the example's sentence keys, `end`, `end_reason`, `lang`, `hold_s`, `expect`,
`interruptible` and `listen`; wording is illustrative in the examples, so it is not compared, but every phone reply
passes the phone text rules and its word budget. Error exchanges that the brain itself decides (unknown call, stale
seq, a turn after /end) raise the matching domain error; authentication, schema and rate-limit exchanges belong to the
API layer and are skipped here.
"""

from __future__ import annotations

import json

import pytest

from gatorplate.contracts.brain_api import EndRequest, StartRequest, TurnRequest
from gatorplate.contracts.errors import Conflict, StaleSeq, UnknownCall
from tests.dialogue.conftest import make_rig
from tests.dialogue.replay import load, phone_reply_problems, prime

FILES = ["maria_phone.json", "sofia_web_es.json", "jamal_phone_expedited.json", "edge_cases.json"]
API_ONLY = {401, 422, 429}
FIELDS = ("end", "end_reason", "lang", "hold_s", "expect", "interruptible", "listen")


def scenarios():
    for name in FILES:
        for scenario in load(name)["scenarios"]:
            yield pytest.param(scenario, id=scenario["id"])


def _body(request: dict):
    if "body" in request:
        return request["body"]
    raw = request.get("body_raw")
    return json.loads(raw) if raw else None


@pytest.mark.parametrize("scenario", list(scenarios()))
async def test_contract_scenario(settings_test, scenario: dict) -> None:
    settings = scenario.get("settings") or {}
    short_codes = ["481206"] if scenario["id"] == "jamal_phone_expedited" else []
    rig = make_rig(settings_test, card_delivery=settings.get("GP_CARD_DELIVERY", "code"), short_codes=short_codes)
    rig.call_id = scenario.get("call_id", rig.call_id)
    await prime(rig, scenario)
    replies: dict[str, object] = {}
    phone = scenario["channel"] == "phone"
    card_url = None
    for i, ex in enumerate(scenario["exchanges"]):
        req, resp = ex["request"], ex["response"]
        status = resp["status"]
        label = f"{scenario['id']}#{i} {ex['step']}"
        if ex["step"] in ("lines", "health", "web_session") or status in API_ONLY or req.get("valid") is False:
            continue
        if req.get("auth") == "gateway" and "headers" in req:
            continue
        body = _body(req)
        if ex["step"] == "end":
            if status == 404:
                with pytest.raises(UnknownCall):
                    await rig.brain.end(rig.call_id, EndRequest.model_validate(body))
            else:
                assert await rig.brain.end(rig.call_id, EndRequest.model_validate(body)) is None, label
            continue
        if ex["step"] == "start":
            reply = await rig.brain.start(rig.call_id, StartRequest.model_validate(body))
        else:
            turn = TurnRequest.model_validate(body)
            if status == 404:
                with pytest.raises(UnknownCall):
                    await rig.brain.turn(rig.call_id, turn)
                continue
            if status == 409:
                code = resp["body"]["error"]["code"]
                with pytest.raises(StaleSeq if code == "stale_seq" else Conflict):
                    await rig.brain.turn(rig.call_id, turn)
                continue
            reply = await rig.brain.turn(rig.call_id, turn)
        expected = resp["body"]
        assert reply.debug is not None and reply.debug.keys == ex["keys"], (label, reply.debug, ex["keys"])
        for field in FIELDS:
            assert getattr(reply, field) == expected[field], (label, field, getattr(reply, field), expected[field])
        for field in ("ask", "display", "card_url"):
            assert (getattr(reply, field) is None) == (expected[field] is None), (label, field)
        if expected["choices"] is not None:  # quick replies the example shows are always there
            assert reply.choices is not None, label
        if phone:
            problems = phone_reply_problems(reply, ex["keys"], start=ex["step"] == "start")
            assert not problems, (label, problems)
        else:
            assert isinstance(reply.display, str), label
            if card_url:
                assert reply.card_url == card_url, label
            card_url = reply.card_url or card_url
        if "id" in ex:
            replies[ex["id"]] = reply
        if "same_as" in ex:
            assert reply == replies[ex["same_as"]], label
    final = scenario.get("expect_final")
    if final:
        case = rig.case()
        assert case is not None
        if "tier" in final:
            assert case.tier.value == final["tier"]
        if "estimate_monthly" in final:
            assert case.estimate_monthly == final["estimate_monthly"]
        if "reason_code" in final:
            assert case.reason_code == final["reason_code"]
        if "expedited" in final:
            assert case.expedited_possible == final["expedited"]
        if "cash_on_hand" in final:
            assert case.slots["cash_on_hand"].value == f"{int(final['cash_on_hand'])}.00"
        if "flips_asked" in final:
            assert [a.slots[0].value for a in case.asked if a.kind == "flip"] == final["flips_asked"]
        if "flip_reason" in final:
            assert [a.reason for a in case.asked if a.kind == "flip"] == [final["flip_reason"]]
        if "skipped_no_effect" in final:
            assert sorted(s.slot.value for s in case.skipped if s.reason == "no_effect") == \
                sorted(final["skipped_no_effect"])
        if "yellow_open" in final:
            assert sum(1 for y in case.yellow_lines if y.resolved is None) == final["yellow_open"]
        if "student_turns" in final:
            assert case.turn_count == final["student_turns"]
        if "card_created" in final:
            assert (case.card is not None) == final["card_created"]
        if "console_reason_text" in final:
            assert final["console_reason_text"] in [y.reason for y in case.yellow_lines]
        if final.get("amount_said") is False:
            assert not any(k.startswith("result.likely") for k in rig.session().last_keys)


def test_lines_en_equal_contract_file(rig) -> None:
    expected = load("lines_en.json")
    assert rig.brain.lines("en").model_dump(mode="json") == expected


def test_lines_es_have_every_field(rig) -> None:
    lines = rig.brain.lines("es")
    assert lines.lang == "es" and len(lines.filler) == 3
    assert all(getattr(lines, f) for f in ("retry", "fatal", "fatal_start", "no_input_bye", "time_limit",
                                           "line_unavailable"))
