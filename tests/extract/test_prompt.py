"""The extraction prompt and schema: strict structured output, compact user message, examples that validate."""

from __future__ import annotations

import json
import re

from gatorplate.contracts.extraction import ExtractionResult, Intent, PendingQuestion
from gatorplate.contracts.slots import SlotName
from gatorplate.extract.merge import Merger
from gatorplate.extract.prompt import SYSTEM_PROMPT, output_schema, user_message


def _objects(schema: dict) -> list[dict]:
    found = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return found


def test_schema_is_strict() -> None:
    schema = output_schema()
    objects = _objects(schema)
    assert objects, "no object in the schema"
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])  # every field required (nullable where optional)
    text = json.dumps(schema)
    for banned in ("maxLength", "minLength", "pattern"):  # validated in code, not in the model schema
        assert f'"{banned}"' not in text


def test_schema_enums_cover_the_contract() -> None:
    text = json.dumps(output_schema())
    for slot in SlotName:
        assert f'"{slot.value}"' in text
    for intent in Intent:
        assert f'"{intent.value}"' in text


def test_user_message_is_compact_json() -> None:
    pending = PendingQuestion(key="ask.rent", slots=[SlotName.rent_share], kind="number")
    msg = user_message(utterance="Eleven hundred.", pending=pending, known={SlotName.level: "undergrad"},
                       recent=["a", "b", "c"], last_prompt="How much is your share of the rent each month?")
    data = json.loads(msg)
    assert list(data) == ["pending", "known", "recent", "last_prompt", "utterance"]
    assert data["recent"] == ["b", "c"]  # the last two utterances only
    assert data["pending"] == {"key": "ask.rent", "slots": ["rent_share"], "kind": "number"}
    assert ": " not in msg and ", " not in msg.replace("Eleven hundred.", "").replace(
        "How much is your share of the rent each month?", "")


def test_examples_validate_and_are_fresh(utterances: list[dict]) -> None:
    outputs = re.findall(r"^-> (\{.*\})$", SYSTEM_PROMPT, flags=re.MULTILINE)
    inputs = re.findall(r"^(\{\"pending\".*\})$", SYSTEM_PROMPT, flags=re.MULTILINE)
    assert 8 <= len(outputs) <= 24 and len(inputs) == len(outputs)
    defaults = {"observations": [], "intents": [], "side_question": None, "requested_language": None}
    merger = Merger()
    for raw_in, raw_out in zip(inputs, outputs, strict=True):
        example = json.loads(raw_in)
        result = ExtractionResult.model_validate({**defaults, **json.loads(raw_out)})
        pending = PendingQuestion.model_validate(example["pending"])
        known = {SlotName(k): v for k, v in (example.get("known") or {}).items()}
        for ob in result.observations:  # every example passes the code's own grounding unchanged
            grounded = merger.ground(ob, example["utterance"], spanish=result.lang == "es", pending=pending,
                                     known=known)
            assert grounded is not None and grounded.value == ob.value, ob
            if ob.slot != SlotName.volunteered_status:
                assert grounded.quote == ob.quote and grounded.state == ob.state, ob
    inputs = [json.loads(raw)["utterance"] for raw in inputs]
    prepared = {row["utterance"] for row in utterances}
    assert not prepared & set(inputs), "prompt examples must not copy the evaluation lines"
    langs = {json.loads(raw)["lang"] for raw in outputs}
    assert langs == {"en", "es"}


def test_prompt_rules() -> None:
    for needle in ("never decide eligibility", "exact, contiguous substring", "quote_en", "off_topic",
                   "roommates_count", "A bare \"espera\"", "is this a real person?", "electricity counts"):
        assert needle in SYSTEM_PROMPT, needle
    assert "[REDACTED]" in SYSTEM_PROMPT
    assert not re.search(r"\d{7,}", SYSTEM_PROMPT)


def test_system_prompt_is_long_enough_to_be_cached() -> None:
    """The system block carries the cache marker, but the model caches only a prefix of at least 4,096 tokens
    (claude-haiku-4-5); a shorter prompt is billed and processed in full on every turn. About 4.4 characters per
    token is the cautious end for this English and JSON text, so the block must hold at least 4,096 x 4.4
    characters."""
    assert len(SYSTEM_PROMPT) >= 4096 * 44 // 10


def test_prompt_rules_for_the_observed_misses() -> None:
    """Rules that answer misses seen with the live model: who the student lives with, living alone, the student's own
    rent at the rent-paid-by-others question, numbers that are not money, plain zeros, closing words, unsure answers."""
    for needle in ('"20, two roommates"', 'household_food "alone" when the student lives alone',
                   '"No, I pay it all myself" -> "0"', "Not money: clock times", "A plain zero is an answer",
                   '"I\'ll apply today"', "Unsure is not no", "Keep quotes short"):
        assert needle in SYSTEM_PROMPT, needle
