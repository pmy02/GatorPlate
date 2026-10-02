"""The fake provider: deterministic replay of data/tests/utterances.jsonl, rules for anything else, injectable
delay and failures."""

from __future__ import annotations

import json
import time

import pytest

from gatorplate.contracts.extraction import PendingQuestion
from gatorplate.extract.llm.fake import FakeLLM
from gatorplate.extract.prompt import SYSTEM_PROMPT, output_schema, user_message


@pytest.fixture(scope="module")
def fake() -> FakeLLM:
    return FakeLLM()


def ask(utterance: str, pending: dict | None, known: dict | None = None) -> str:
    return user_message(utterance=utterance, pending=PendingQuestion.model_validate(pending) if pending else None,
                        known=known or {}, recent=[], last_prompt=None)


async def test_replays_every_line(fake: FakeLLM, utterances: list[dict], redactor) -> None:
    from gatorplate.extract.text import normalize

    for row in utterances:
        text = redactor.redact(normalize(row["utterance"]), masked=bool(row.get("masked"))).text
        out = await fake.complete(SYSTEM_PROMPT, ask(text, row["pending"], row.get("known")), output_schema(), 2.3)
        assert out.status == "ok" and out.result is not None
        want = {k: row["expect"][k] for k in ("observations", "intents", "answered_pending", "lang", "side_question",
                                              "requested_language")}
        assert out.result.model_dump(mode="json") == want, row["id"]


async def test_deterministic(fake: FakeLLM) -> None:
    prompt = ask("I make like 640 a month at the gym.", {"key": "ask.income", "slots": ["earned_monthly",
                                                                                         "other_cash_monthly"],
                                                         "kind": "number"})
    first = await fake.complete(SYSTEM_PROMPT, prompt, {}, 2.3)
    second = await fake.complete(SYSTEM_PROMPT, prompt, {}, 2.3)
    assert first.result == second.result
    assert [(o.slot.value, o.value, o.period) for o in first.result.observations] == [
        ("earned_monthly", "640", "month")]


async def test_entry_for_another_question_is_not_reused(fake: FakeLLM) -> None:
    """"No." was recorded for the rent flip; for the consent question it means consent false."""
    out = await fake.complete(SYSTEM_PROMPT, ask("No.", {"key": "consent.ask", "slots": ["consent"],
                                                        "kind": "yes_no"}), {}, 2.3)
    assert [(o.slot.value, o.value) for o in out.result.observations] == [("consent", "false")]
    same = await fake.complete(SYSTEM_PROMPT, ask("No.", {"key": "flip.rent_paid_by_others",
                                                         "slots": ["rent_paid_by_others_to_landlord"],
                                                         "kind": "yes_no"}), {}, 2.3)
    assert [(o.slot.value, o.value) for o in same.result.observations] == [("rent_paid_by_others_to_landlord", "0")]


async def test_all_of_it_follows_the_known_rent(fake: FakeLLM) -> None:
    pending = {"key": "flip.rent_paid_by_others_amount", "slots": ["rent_paid_by_others_to_landlord"],
               "kind": "number"}
    out = await fake.complete(SYSTEM_PROMPT, ask("All of it.", pending, {"rent_share": "950.00"}), {}, 2.3)
    assert out.result.observations[0].value == "950"


async def test_unknown_line_uses_rules(fake: FakeLLM) -> None:
    out = await fake.complete(SYSTEM_PROMPT, ask("Can I talk to a real person please?", None), {}, 2.3)
    assert [i.value for i in out.result.intents] == ["human_request"] and out.result.observations == []


@pytest.mark.parametrize("mode", ["error", "invalid", "refused"])
async def test_injected_failures(mode: str) -> None:
    fake = FakeLLM(fail=[mode])
    first = await fake.complete(SYSTEM_PROMPT, ask("Yes.", None), {}, 2.3)
    second = await fake.complete(SYSTEM_PROMPT, ask("Yes.", None), {}, 2.3)
    assert first.status == mode and second.status == "ok"


async def test_injected_delay_times_out() -> None:
    fake = FakeLLM(delay_s=5.0)
    started = time.monotonic()
    out = await fake.complete(SYSTEM_PROMPT, ask("Yes.", None), {}, 0.2)
    assert out.status == "timeout" and time.monotonic() - started < 0.4
    assert fake.metrics.snapshot()["status"] == "error"


def test_table_covers_every_line(fake: FakeLLM, utterances: list[dict]) -> None:
    assert sum(len(v) for v in fake.table.values()) == len(utterances)
    assert json.dumps(fake.metrics.snapshot())  # content-free and serializable
