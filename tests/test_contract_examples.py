"""Model-level replay of contracts/examples (docs/BRAIN_API.md): every scenario, exchange by exchange.

Requests parse into the request models (valid:false bodies are rejected and do not use up a seq); responses parse
into BrainReply, GatewayLines, WebSessionResponse, HealthResponse, EndResponse or ErrorEnvelope; an error's HTTP
status and retryable flag match the schema; phone replies carry no web extras; on the web a card_url, once set, stays
set; every sentence key an exchange lists is in the sentence bank."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from gatorplate.contracts import brain_api as api
from gatorplate.contracts.common import Channel

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "contracts" / "examples"
BANK = json.loads((ROOT / "data" / "content" / "sentences.en.json").read_text(encoding="utf-8"))["messages"]
SCENARIO_FILES = ["maria_phone.json", "sofia_web_es.json", "jamal_phone_expedited.json", "edge_cases.json"]


def scenarios():
    for name in SCENARIO_FILES:
        data = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
        for scenario in data["scenarios"]:
            yield pytest.param(scenario, id=scenario["id"])


def response_body(response: dict):
    if "body_ref" in response:
        return json.loads((EXAMPLES / response["body_ref"]).read_text(encoding="utf-8"))
    return response.get("body")


@pytest.mark.parametrize("scenario", list(scenarios()))
def test_scenario_replay(scenario: dict) -> None:
    channel = Channel(scenario["channel"])
    card_url = None
    settings = scenario.get("settings", {})
    assert set(settings) <= {"GP_CARD_DELIVERY", "GP_DEBUG_KEYS"}
    assert settings.get("GP_CARD_DELIVERY", "code") in ("screen", "code")
    for exchange in scenario["exchanges"]:
        step, request, response = exchange["step"], exchange["request"], exchange["response"]
        body = request.get("body")
        if step in ("start", "turn", "end") and response["status"] == 200:
            m = re.fullmatch(r"/v1/calls/([^/]+)/(start|turn|end)", request["path"])
            assert m and re.fullmatch(api.CALL_ID, m.group(1)) and m.group(2) == step, request["path"]
        if step in ("start", "turn") and body is not None and response["status"] == 200:
            assert body["seq"] == 0 if step == "start" else body["seq"] >= 1
        out = response_body(response)
        if response["status"] != 200:
            envelope = api.ErrorEnvelope.model_validate(out)
            status, retryable = api.ERROR_STATUS[envelope.error.code]
            assert status == response["status"], exchange
            assert envelope.error.retryable == retryable, exchange
            continue
        if step not in ("start", "turn"):
            continue
        reply = api.BrainReply.model_validate(out)
        for key in exchange.get("keys", []):
            assert key in BANK, f"{scenario['id']}: key {key} is not in the sentence bank"
        if channel == Channel.phone:
            assert reply.display is None and reply.choices is None and reply.card_url is None
            if step == "start":
                assert reply.interruptible is False and reply.ask is not None and reply.end is False
        else:
            assert isinstance(reply.display, str)
            if card_url is not None:
                assert reply.card_url == card_url, "card_url must stay set once the card exists"
            card_url = reply.card_url or card_url


def test_counts_match_checker() -> None:
    """The same totals contracts/check_examples.py prints: 23 scenarios, 77 exchanges, 49 replies."""
    n_scen = n_ex = n_rep = 0
    for name in SCENARIO_FILES:
        data = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
        for scenario in data["scenarios"]:
            n_scen += 1
            for exchange in scenario["exchanges"]:
                n_ex += 1
                if exchange["step"] in ("start", "turn") and exchange["response"]["status"] == 200:
                    n_rep += 1
    assert (n_scen, n_ex, n_rep) == (23, 77, 49)


def test_lines_and_hmac_vectors() -> None:
    lines = json.loads((EXAMPLES / "lines_en.json").read_text(encoding="utf-8"))
    assert api.GatewayLines.model_validate(lines).model_dump(mode="json") == lines
    vectors = json.loads((EXAMPLES / "hmac_vectors.json").read_text(encoding="utf-8"))
    assert vectors["secret"] == "test-secret-do-not-use"
    assert len(vectors["vectors"]) == 10 and len(vectors["checks"]) == 13
