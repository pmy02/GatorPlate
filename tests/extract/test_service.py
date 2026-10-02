"""The Understander end to end with the fake model: every prepared line, the golden dialogues, the fast path,
closed mode, deadlines, failures, the keypad and the health counters."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest

from gatorplate.clock import FixedClock, default_test_clock
from gatorplate.contracts.common import Lang, SlotSource
from gatorplate.contracts.extraction import ExtractOutcome, Intent, PendingQuestion, Understanding
from gatorplate.contracts.slots import SlotName
from gatorplate.extract import Understander
from gatorplate.extract.llm.base import MemoryCounter
from gatorplate.extract.llm.fake import FakeLLM
from tests.extract.support import ROOT, per_slot, understand_row

S = SlotName
RENT = PendingQuestion(key="ask.rent", slots=[S.rent_share], kind="number")
INCOME = PendingQuestion(key="ask.income", slots=[S.earned_monthly, S.other_cash_monthly], kind="number")


async def call(u: Understander, text: str, pending: PendingQuestion | None = RENT, *, dtmf: str | None = None,
               closed_mode: bool = False, deadline_s: float = 2.6, known: dict | None = None,
               recent: list[str] | None = None, lang: Lang = Lang.en, masked: bool = False) -> Understanding:
    return await u.understand(text=text, masked=masked, confidence=0.9, dtmf=dtmf, pending=pending,
                              known=known or {}, recent=recent or [], last_prompt=None, lang=lang,
                              deadline=u.clock.monotonic() + deadline_s, closed_mode=closed_mode)


def test_implements_the_port() -> None:
    import inspect

    from gatorplate.contracts.ports import UnderstandingPort

    want = inspect.signature(UnderstandingPort.understand)
    got = inspect.signature(Understander.understand)
    assert list(got.parameters) == list(want.parameters)
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for name, p in got.parameters.items() if name != "self")
    assert inspect.iscoroutinefunction(Understander.understand)


async def test_every_line_matches_its_expected_extraction(understander: Understander, utterances: list[dict]) -> None:
    """Fake model + parser + keywords + merge reproduce every expected extraction of data/tests/utterances.jsonl."""
    for row in utterances:
        result = await understand_row(understander, row)
        expect = row["expect"]
        allow = set(row.get("allow_extra") or [])
        got = {k: v for k, v in per_slot([o.model_dump() for o in result.observations]).items()
               if k not in allow or k in {o["slot"] for o in expect["observations"]}}
        assert got == per_slot(expect["observations"]), row["id"]
        intents = {i.value for i in result.intents}
        assert set(expect["intents"]) <= intents, row["id"]
        assert not intents - set(expect["intents"]) - set(row.get("allow_extra_intents") or []), row["id"]
        assert result.redactions == expect["redactions"], row["id"]
        assert result.answered_pending == expect["answered_pending"], row["id"]
        assert result.side_question == expect["side_question"], row["id"]
        assert result.requested_language == expect["requested_language"], row["id"]


def _student_lines() -> list[tuple[str, str, dict | None]]:
    """(source, text, fake_llm) for every student utterance of the contract examples and the end-to-end scripts."""
    lines: list[tuple[str, str, dict | None]] = []

    def walk(node: Any, source: str) -> None:
        if isinstance(node, dict):
            if node.get("event") == "utterance" and isinstance(node.get("text"), str):
                lines.append((source, node["text"], None))
            for value in node.values():
                walk(value, source)
        elif isinstance(node, list):
            for value in node:
                walk(value, source)

    for path in sorted((ROOT / "contracts" / "examples").glob("*.json")):
        walk(json.loads(path.read_text(encoding="utf-8")), path.name)
    lines.extend(_script_lines(ROOT / "tests" / "e2e" / "scripts"))
    return lines


def _script_lines(folder: Any) -> list[tuple[str, str, dict | None]]:
    lines: list[tuple[str, str, dict | None]] = []
    for path in sorted(folder.glob("*.json")):
        for turn in json.loads(path.read_text(encoding="utf-8")).get("turns", []):
            if isinstance(turn.get("user"), str):
                lines.append((path.name, turn["user"], turn.get("fake_llm")))
    return lines


def _same_extraction(fake_llm: dict, want: dict, where: tuple[str, str]) -> None:
    assert per_slot(fake_llm["observations"]) == per_slot(want["observations"]), where
    assert sorted(fake_llm["intents"]) == sorted(want["intents"]), where


def test_every_student_line_of_the_examples_and_scripts_is_prepared(utterances: list[dict]) -> None:
    prepared = {row["utterance"]: row for row in utterances}
    lines = _student_lines()
    assert len(lines) >= 40
    for source, text, fake_llm in lines:
        assert text in prepared, (source, text)
        if fake_llm is not None:  # the script's fake extraction is the prepared expectation
            _same_extraction(fake_llm, prepared[text]["expect"], (source, text))


def test_adversarial_script_lines_agree_where_prepared(utterances: list[dict]) -> None:
    prepared = {row["utterance"]: row for row in utterances}
    for source, text, fake_llm in _script_lines(ROOT / "tests" / "adversarial" / "scripts"):
        if fake_llm is not None and text in prepared:
            _same_extraction(fake_llm, prepared[text]["expect"], (source, text))


def test_roommate_counts_are_prepared(utterances: list[dict]) -> None:
    by_id = {row["id"]: row for row in utterances}
    for line_id, count in (("u003", "2"), ("u036", "2"), ("u097", "2"), ("u124", "2"), ("u403", "4")):
        obs = {o["slot"]: o["value"] for o in by_id[line_id]["expect"]["observations"]}
        assert obs["roommates_count"] == count, line_id
    for row in utterances:  # a line that states a count expects the slot, or allows it
        if any(o["slot"] == "roommates" and o["value"] == "true" for o in row["expect"]["observations"]):
            stated = any(w in row["utterance"].lower() for w in ("two roommates", "dos roommates", "four roommates",
                                                                 "dos compañeros"))
            has = any(o["slot"] == "roommates_count" for o in row["expect"]["observations"])
            assert stated == has or "roommates_count" in (row.get("allow_extra") or []), row["id"]


async def test_maria_path(understander: Understander) -> None:
    """The demo path: every turn understood as the golden dialogue expects (no confirm-forcing disagreement)."""
    script = json.loads((ROOT / "tests" / "e2e" / "scripts" / "maria_g1.json").read_text(encoding="utf-8"))
    by_text = {json.loads(line)["utterance"]: json.loads(line) for line in
               (ROOT / "data" / "tests" / "utterances.jsonl").read_text(encoding="utf-8").splitlines()}
    for turn in script["turns"]:
        if "user" not in turn:
            continue
        row = by_text[turn["user"]]
        result = await understand_row(understander, row)
        assert all(o.state == "clear" for o in result.observations), turn["user"]
        assert per_slot([o.model_dump() for o in result.observations]) == per_slot(turn["fake_llm"]["observations"])
        assert not set(result.teen_ty) & {S.earned_monthly, S.rent_share, S.other_cash_monthly,
                                          S.rent_paid_by_others_to_landlord}
    two = await call(understander, "I'm 20, and I live with two roommates.",
                     PendingQuestion(key="ask.age_parent", slots=[S.age, S.lives_with_parent], kind="open"))
    assert {o.slot: o.value for o in two.observations}[S.roommates_count] == "2"


async def test_fast_path_skips_the_model(settings_test) -> None:
    fake = FakeLLM()
    u = Understander(settings=settings_test, llm=fake)
    consent = PendingQuestion(key="consent.ask", slots=[S.consent], kind="yes_no")
    result = await call(u, "Yes.", consent)
    assert result.llm.status == "skipped" and fake.calls == 0
    assert result.observations[0].value == "true" and result.sources[S.consent] == SlotSource.parser
    # a keyword intent, or more than three words, goes to the model
    await call(u, "Is this a real person?", consent)
    await call(u, "Yes, that's fine with me.", consent)
    assert fake.calls == 2


async def test_closed_mode_uses_the_parser_only(settings_test) -> None:
    fake = FakeLLM()
    u = Understander(settings=settings_test, llm=fake)
    result = await call(u, "I work at the campus library, about 900 a month. Nobody gives me cash.", INCOME,
                        closed_mode=True)
    assert fake.calls == 0 and result.llm.status == "skipped"
    assert {(o.slot, o.value) for o in result.observations} == {(S.earned_monthly, "900"),
                                                               (S.other_cash_monthly, "0")}


async def test_timeout_returns_within_the_deadline(settings_test) -> None:
    u = Understander(settings=settings_test, llm=FakeLLM(delay_s=10.0))
    started = time.monotonic()
    result = await call(u, "I make like 640 a month at the gym, and my mom sends me 50 a week.", INCOME,
                        deadline_s=0.4)
    elapsed = time.monotonic() - started
    assert result.llm.status == "timeout"
    assert elapsed <= 0.4 + 0.05
    # the parser still answers
    assert {o.slot for o in result.observations} == {S.earned_monthly, S.other_cash_monthly}


async def test_client_that_ignores_its_timeout_is_cut(settings_test) -> None:
    class Hanging:
        provider, model = "fake", "hanging"

        async def complete(self, system: str, user_json: str, schema: dict, timeout_s: float) -> ExtractOutcome:
            await asyncio.sleep(30)
            raise AssertionError("never")

    u = Understander(settings=settings_test, llm=Hanging())  # type: ignore[arg-type]
    started = time.monotonic()
    result = await call(u, "My rent is about nine fifty a month, I think.", deadline_s=0.5)
    assert result.llm.status == "timeout" and time.monotonic() - started <= 0.5 + 0.05


async def test_deadline_uses_the_injected_clock(settings_test) -> None:
    clock = default_test_clock()
    u = Understander(settings=settings_test, llm=FakeLLM(delay_s=10.0), clock=clock)
    started = time.monotonic()
    result = await u.understand(text="My rent is about nine fifty a month, I think.", masked=False, confidence=0.9,
                                dtmf=None, pending=RENT, known={}, recent=[], last_prompt=None, lang=Lang.en,
                                deadline=clock.monotonic() + 0.3, closed_mode=False)
    assert result.llm.status == "timeout" and time.monotonic() - started <= 0.3 + 0.05
    assert isinstance(clock, FixedClock)


async def test_failures_are_reported(settings_test) -> None:
    u = Understander(settings=settings_test, llm=FakeLLM(fail=["error", "invalid", "refused"]))
    statuses = [(await call(u, "My rent is about nine fifty a month, I think.")).llm.status for _ in range(4)]
    assert statuses == ["error", "invalid", "refused", "ok"]


async def test_daily_turn_cap(settings_test) -> None:
    """Over GP_LLM_DAILY_TURN_CAP the model is not called; new calls see no client (closed mode) until the next
    Pacific day. The count lives in the injected counter (the platform's counters table)."""
    clock = default_test_clock()
    counter = MemoryCounter()
    fake = FakeLLM()
    u = Understander(settings=settings_test.model_copy(update={"llm_daily_turn_cap": 2}), llm=fake,
                     counters=counter, clock=clock)
    text = "My rent is about nine fifty a month, I think."
    statuses = [(await call(u, text)).llm.status for _ in range(3)]
    assert statuses == ["ok", "ok", "skipped"] and fake.calls == 2
    assert u.llm is None and u.llm_health()["status"] != "no_key"
    assert counter.incr("llm_turns", clock.today()) == 4
    clock.advance(hours=24)  # the next Pacific day
    assert u.llm is fake and (await call(u, text)).llm.status == "ok"


async def test_zero_cap_means_closed_mode(settings_test) -> None:
    u = Understander(settings=settings_test.model_copy(update={"llm_daily_turn_cap": 0}))
    assert u.llm is None
    result = await call(u, "My rent is about nine fifty a month, I think.")
    assert result.llm.status == "skipped" and result.observations[0].value == "950"


async def test_provider_exception_never_breaks_a_turn(settings_test) -> None:
    class Broken:
        provider, model = "fake", "broken"

        async def complete(self, system: str, user_json: str, schema: dict, timeout_s: float) -> ExtractOutcome:
            raise RuntimeError("provider bug")

    u = Understander(settings=settings_test, llm=Broken())  # type: ignore[arg-type]
    result = await call(u, "It's eleven hundred a month, more or less.")
    assert result.llm.status == "error" and result.observations[0].value == "1100"


async def test_keypad_turns(understander: Understander) -> None:
    consent = PendingQuestion(key="consent.ask", slots=[S.consent], kind="yes_no")
    yes = await call(understander, "", consent, dtmf="1")
    assert yes.observations[0].value == "true" and yes.sources[S.consent] == SlotSource.keypad
    assert yes.llm.status == "skipped" and yes.answered_pending == "yes"
    bad = await call(understander, "", consent, dtmf="9x")
    assert bad.observations == [] and bad.answered_pending == "no"
    rent = PendingQuestion(key="ask.rent", slots=[S.rent_share], kind="choice", closed=True)
    band = await call(understander, "", rent, dtmf="2")
    assert (band.observations[0].value, band.observations[0].state) == ("1000", "unclear")


async def test_spoken_key_on_a_closed_question(understander: Understander) -> None:
    rent = PendingQuestion(key="ask.rent", slots=[S.rent_share], kind="choice", closed=True)
    result = await call(understander, "Two.", rent)
    assert result.observations[0].value == "1000"


async def test_empty_text(understander: Understander) -> None:
    result = await call(understander, "   ")
    assert result.observations == [] and result.answered_pending == "no" and result.llm.status == "skipped"


async def test_masked_turn(understander: Understander) -> None:
    result = await call(understander, "Do you need my social? It's #########.", masked=True)
    assert result.redactions == ["ssn"] and "#" not in result.redacted_text
    assert Intent.ssn_attempt in result.intents


async def test_status_utterance_keeps_no_quote(understander: Understander) -> None:
    result = await call(understander, "I have DACA, by the way. Rent is 800.")
    status = next(o for o in result.observations if o.slot == S.volunteered_status)
    assert status.value == "DACA" and status.quote == "" and status.quote_en is None


async def test_spanish_gloss(understander: Understander) -> None:
    result = await call(understander, "Mil cien.", lang=Lang.es)
    assert result.lang == Lang.es and result.observations[0].quote_en == "Eleven hundred"
    english = await call(understander, "Eleven hundred.")
    assert english.observations[0].quote_en is None


def test_health_counts(settings_test) -> None:
    u = Understander(settings=settings_test)
    health = u.llm_health()
    assert health["provider"] == "fake" and set(health["usage"]) == {"calls", "input_tokens", "output_tokens"}
    asyncio.run(call(u, "I make like 640 a month at the gym, and my mom sends me 50 a week.", INCOME))
    assert u.llm_health()["usage"]["calls"] == 1 and u.llm_health()["status"] == "ok"
    assert u.llm_health()["last_ok_at"].endswith("Z")


@pytest.mark.parametrize("closed", [True, False])
async def test_never_a_multi_key_amount(understander: Understander, closed: bool) -> None:
    for pending in (RENT.model_copy(update={"closed": closed}), INCOME.model_copy(update={"closed": closed})):
        for key in ("1100", "11", "#", "1#", "900#"):
            result = await call(understander, "", pending, dtmf=key)
            assert result.observations == [], (pending.key, key)
