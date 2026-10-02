"""gatorplate/contracts/brain_api.py equals contracts/brain_api.v1.schema.json (the schema is the only source).

For every object definition: property names, required sets, enum and const values, nullability, string, number and
array constraints and additionalProperties match. Every request and response body in contracts/examples validates
through the models (bodies marked valid:false raise) and every response body round-trips."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import BaseModel, ValidationError

from gatorplate.contracts import brain_api as api
from gatorplate.contracts.common import Channel, Lang

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "contracts" / "brain_api.v1.schema.json").read_text(encoding="utf-8"))
EXAMPLES = ROOT / "contracts" / "examples"
DEFS = SCHEMA["$defs"]

OBJECT_MODELS: dict[str, type[BaseModel]] = {
    "StartRequest": api.StartRequest,
    "TurnRequest": api.TurnRequest,
    "EndRequest": api.EndRequest,
    "EndResponse": api.EndResponse,
    "BrainReply": api.BrainReply,
    "GatewayLines": api.GatewayLines,
    "WebSessionRequest": api.WebSessionRequest,
    "WebSessionResponse": api.WebSessionResponse,
    "HealthResponse": api.HealthResponse,
    "ErrorEnvelope": api.ErrorEnvelope,
}
CONSTRAINTS = ("minLength", "maxLength", "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
               "minItems", "maxItems", "format")


def _resolve(node: dict, defs: dict) -> dict:
    while "$ref" in node:
        target = defs[node["$ref"].split("/")[-1]]
        rest = {k: v for k, v in node.items() if k != "$ref"}
        node = {**target, **rest}
    return node


def facts(node: dict, defs: dict) -> dict[str, Any]:
    """A comparable summary of one JSON Schema node."""
    node = _resolve(node, defs)
    if "anyOf" in node:
        members = [facts(m, defs) for m in node["anyOf"]]
        nullable = any(m["types"] == {"null"} for m in members)
        real = [m for m in members if m["types"] != {"null"}]
        assert len(real) == 1, f"unexpected union {node}"
        out = dict(real[0])
        out["nullable"] = out["nullable"] or nullable
        for key in CONSTRAINTS:
            if key in node:
                out[key] = node[key]
        return out
    raw_type = node.get("type")
    types = set(raw_type) if isinstance(raw_type, list) else ({raw_type} if raw_type else set())
    out: dict[str, Any] = {"nullable": "null" in types, "types": types - {"null"} or ({"null"} if types else set())}
    if "const" in node:
        out["const"] = node["const"]
        out["types"] = set()
    if "enum" in node:
        out["enum"] = set(node["enum"])
        out["types"] = set()
    for key in CONSTRAINTS:
        if key in node:
            out[key] = node[key]
    if "items" in node:
        out["items"] = facts(node["items"], defs)
    if "properties" in node or out["types"] == {"object"}:
        out["object"] = object_facts(node, defs)
        out["types"] = {"object"}
    return out


def object_facts(node: dict, defs: dict) -> dict[str, Any]:
    node = _resolve(node, defs)
    props = node.get("properties", {})
    return {
        "properties": {name: facts(p, defs) for name, p in props.items()},
        "required": set(node.get("required", [])),
        "additional": node.get("additionalProperties", True) is not False,
    }


@pytest.mark.parametrize("name", list(OBJECT_MODELS))
def test_model_matches_schema(name: str) -> None:
    frozen = object_facts(DEFS[name], DEFS)
    generated = OBJECT_MODELS[name].model_json_schema(mode="validation")
    mine = object_facts(generated, generated.get("$defs", {}))
    assert set(mine["properties"]) == set(frozen["properties"]), name
    assert mine["required"] == frozen["required"], name
    assert mine["additional"] == frozen["additional"], name
    for prop, want in frozen["properties"].items():
        assert mine["properties"][prop] == want, f"{name}.{prop}: {mine['properties'][prop]} != {want}"


def test_enums_and_codes() -> None:
    assert {x.value for x in Lang} == set(DEFS["Lang"]["enum"])
    assert {x.value for x in Channel} == set(DEFS["Channel"]["enum"])
    assert set(get_args(api.ErrorCode)) == set(DEFS["ErrorCode"]["enum"])
    assert set(get_args(api.ReplyEndReason)) == set(DEFS["ReplyEndReason"]["enum"])
    assert api.CALL_ID == DEFS["CallId"]["pattern"] == SCHEMA["x-auth"]["call_id_pattern"]
    assert api.ERROR_STATUS == {code: (v["status"], v["retryable"]) for code, v in SCHEMA["x-errors"].items()}


def test_no_retired_fields() -> None:
    names = set()
    for model in OBJECT_MODELS.values():
        names |= set(model.model_fields)
    for retired in ("caller_hash", "final", "played_ms", "asr_confidence", "handoff"):
        assert retired not in names
    assert not hasattr(api, "Handoff")


def test_reply_rules() -> None:
    base = dict(say="Hi.", ask=None, end=True, end_reason="completed", lang="en", listen="normal", expect="open",
                interruptible=False, hold_s=0, display=None, choices=None, card_url=None, debug=None)
    api.BrainReply.model_validate(base)
    for bad in ({"ask": "More?"}, {"end_reason": None}, {"hold_s": 3}, {"interruptible": True},
                {"end": False}, {"end": False, "end_reason": None, "hold_s": 5, "ask": "Ready?"},
                {"choices": []}, {"card_url": "/c/short"}, {"debug": {"keys": [""]}}, {"debug": {"phase": None}},
                {"extra": 1}):
        with pytest.raises(ValidationError):
            api.BrainReply.model_validate({**base, **bad})
    api.BrainReply.model_validate({**base, "end": False, "end_reason": None, "hold_s": 30, "interruptible": True})


@pytest.mark.parametrize("body", [
    {"v": True, "seq": 1, "event": "silence", "silence_n": 1},
    {"v": 1, "seq": "1", "event": "silence", "silence_n": 1},
    {"v": 1, "seq": 1, "event": "utterance", "text": "x", "confidence": "0.5"},
    {"v": 1, "seq": 1, "event": "utterance", "text": "x", "masked": 1},
    {"v": 1, "seq": 1, "event": "utterance", "text": None},
    {"v": 1, "seq": 1, "event": "utterance", "text": "x", "lang": None},
    {"v": 1, "seq": 1, "event": "dtmf", "dtmf": None},
    {"v": 1, "seq": 1, "event": "silence", "silence_n": 0},
])
def test_turn_request_strict(body: dict) -> None:
    with pytest.raises(ValidationError):
        api.TurnRequest.model_validate_json(json.dumps(body))


def test_tolerant_requests() -> None:
    req = api.TurnRequest.model_validate_json(json.dumps(
        {"v": 1, "seq": 3, "event": "dtmf", "dtmf": "1", "text": "ignored", "unknown": {"x": 1}}))
    assert req.dtmf == "1" and not hasattr(req, "unknown")
    assert api.StartRequest.model_validate_json('{"v":1,"seq":0,"channel":"web","lang":"es","x":1}').lang == Lang.es
    assert api.WebSessionRequest.model_validate_json("{}").lang == Lang.en
    with pytest.raises(ValidationError):
        api.StartRequest.model_validate_json('{"v":1,"seq":false,"channel":"web","lang":"es"}')
    with pytest.raises(ValidationError):
        api.EndRequest.model_validate_json('{"v":1,"reason":"completed","turns":null}')


# ---------------------------------------------------------------------------------------------- example bodies

REQUEST_MODELS = {"start": api.StartRequest, "turn": api.TurnRequest, "end": api.EndRequest,
                  "web_session": api.WebSessionRequest}
RESPONSE_MODELS = {"start": api.BrainReply, "turn": api.BrainReply, "end": api.EndResponse,
                   "web_session": api.WebSessionResponse, "lines": api.GatewayLines, "health": api.HealthResponse}


def exchanges():
    for path in sorted(EXAMPLES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for scenario in data.get("scenarios", []):
            for i, exchange in enumerate(scenario["exchanges"]):
                yield pytest.param(exchange, id=f"{scenario['id']}-{i}-{exchange['step']}")


@pytest.mark.parametrize("exchange", list(exchanges()))
def test_example_bodies(exchange: dict) -> None:
    request = exchange["request"]
    model = REQUEST_MODELS.get(exchange["step"])
    if model is not None:
        raw = request["body_raw"] if "body_raw" in request else json.dumps(request.get("body"))
        if request.get("valid") is False:
            with pytest.raises(ValidationError):
                model.model_validate_json(raw)
        else:
            model.model_validate_json(raw)
    response = exchange["response"]
    body = response.get("body")
    if "body_ref" in response:
        body = json.loads((EXAMPLES / response["body_ref"]).read_text(encoding="utf-8"))
    out_model = RESPONSE_MODELS[exchange["step"]] if response["status"] == 200 else api.ErrorEnvelope
    parsed = out_model.model_validate(body)
    assert parsed.model_dump(mode="json") == body
