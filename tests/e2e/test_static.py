"""E2E scripts and the E2E runner (tools/e2e_run.py): every script validates, and the runner's self-test passes
against a stub Brain API (tests/e2e/stub_app.py) — in-process, and as a server on a free port the OS assigns.

The stub answers each call with exactly what the matching script expects, so these tests prove the runner's own
behaviour (one server per declared environment, never two card-delivery modes in one server, every server stopped,
--only, remote-mode skips and counts, keys not asserted with debug keys off, the live-replay skip list, the report)
without depending on the real brain. The real brain is exercised by `make e2e`, `make adversarial` and
`make examples`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import warnings
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.e2e.stub_app import create_stub_app
from tools import e2e_run as runner

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_FILES = sorted(p for d in runner.SCRIPTS_DIRS for p in d.glob("*.json"))
UTTERANCES = {}
for _line in (ROOT / "data" / "tests" / "utterances.jsonl").read_text(encoding="utf-8").splitlines():
    if _line.strip():
        _row = json.loads(_line)
        UTTERANCES.setdefault(_row["utterance"], _row)
STUB_APP = "tests.e2e.stub_app:app"


def _load(name: str) -> dict:
    path = next(p for p in SCRIPT_FILES if p.stem == name)
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------ the scripts

@pytest.mark.parametrize("path", SCRIPT_FILES, ids=[p.stem for p in SCRIPT_FILES])
def test_script_is_valid(path: Path) -> None:
    script = runner.load_script(path)
    assert runner.check_script_names(script) == []
    if script.channel == "web":
        assert all(t.dtmf is None for t in script.turns)


def test_script_ids_unique_and_appendix_covered() -> None:
    scripts = [runner.load_script(p) for p in SCRIPT_FILES]
    ids = [s.id for s in scripts]
    assert len(ids) == len(set(ids))
    appendix = [s.appendix for s in scripts if s.appendix]
    assert len(appendix) == len(set(appendix)), "one script per scenario-list entry"
    want = {f"S{n:02d}" for n in range(1, 23)} | {f"A{n:02d}" for n in range(1, 41)}
    # A25 (a model answer later than 2.3 s) needs an injected delay: tests/adversarial/test_llm_faults.py.
    # A32 (three concurrent calls) is the runner's --concurrency (make e2e CONC=3), self-tested below.
    assert want - set(appendix) == {"A25", "A32"}
    e2e = {s.appendix for s in scripts if s.appendix and s.appendix.startswith("S")}
    assert e2e == {f"S{n:02d}" for n in range(1, 23)}


def test_prepared_golden_dialogues_declare_their_environment() -> None:
    want = {"maria_g1": "screen", "sofia_g3": "screen", "jamal_g4": "code"}
    for name, mode in want.items():
        data = _load(name)
        assert data["env"]["GP_CARD_DELIVERY"] == mode
        assert data["env"]["GP_DEBUG_KEYS"] == "1"
        assert data["fake_llm_ok"] is True
        assert "settings" not in data or data["settings"] == data["env"]


@pytest.mark.parametrize("mutate", ["drop_card_delivery", "bad_card_delivery", "settings_differs", "secret",
                                    "no_start", "phone_spanish", "two_events", "error_without_code"])
def test_invalid_scripts_fail(mutate: str, tmp_path: Path) -> None:
    data = _load("maria_g1")
    if mutate == "drop_card_delivery":
        del data["env"]["GP_CARD_DELIVERY"]
    elif mutate == "bad_card_delivery":
        data["env"]["GP_CARD_DELIVERY"] = "sms"
    elif mutate == "settings_differs":
        data["settings"] = {"GP_CARD_DELIVERY": "code"}
    elif mutate == "secret":
        data["env"]["GP_GATEWAY_SECRET"] = "x"
    elif mutate == "no_start":
        data["turns"] = data["turns"][1:]
    elif mutate == "phone_spanish":
        data["lang"] = "es"
    elif mutate == "two_events":
        data["turns"][1]["dtmf"] = "1"
    elif mutate == "error_without_code":
        data["turns"][1]["expect_status"] = 409
    path = tmp_path / "maria_g1.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        runner.load_script(path)


def test_unknown_sentence_key_is_reported(tmp_path: Path) -> None:
    data = _load("maria_g1")
    data["turns"][1]["expect_keys"] = ["ack.short", "ask.nonexistent"]
    path = tmp_path / "maria_g1.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("ask.nonexistent" in p for p in runner.check_script_names(runner.load_script(path)))


def test_maria_carries_roommates_count() -> None:
    """docs/SPEC.md §3.10: 'two roommates' also yields the never-asked slot roommates_count = 2; nothing else in
    the call changes."""
    data = _load("maria_g1")
    turn = next(t for t in data["turns"] if t.get("user") == "I'm 20, and I live with two roommates.")
    obs = {o["slot"]: o for o in turn["fake_llm"]["observations"]}
    assert obs["roommates_count"]["value"] == "2" and obs["roommates_count"]["quote"] == "two roommates"
    assert turn["case"]["slots"]["roommates_count"] == "2"
    assert data["final"]["slots"]["roommates_count"] == "2"
    assert turn["expect_keys"] == ["ack.short", "ask.household_food_roommates"]
    assert [t.get("expect_keys") for t in data["turns"]][:3] == [
        ["consent.ask"], ["ack.short", "ask.level_units"], ["ack.short", "ask.age_parent"]]


def test_scripts_stating_a_roommate_count_carry_it() -> None:
    for path in SCRIPT_FILES:
        for turn in json.loads(path.read_text(encoding="utf-8"))["turns"]:
            if "two roommates" in (turn.get("user") or "") and turn.get("fake_llm"):
                slots = {o["slot"] for o in turn["fake_llm"]["observations"]}
                assert "roommates_count" in slots, path.name


def _observations(block: dict) -> list[tuple]:
    return sorted((o["slot"], o["value"], o["period"], o["state"]) for o in block["observations"])


def test_fake_llm_blocks_match_the_utterance_table() -> None:
    """A script's fake_llm block for an utterance in data/tests/utterances.jsonl equals that table's extraction
    (the fake model replays the table). Utterances not yet in the table are listed as a warning."""
    missing = set()
    for path in SCRIPT_FILES:
        for i, turn in enumerate(json.loads(path.read_text(encoding="utf-8"))["turns"]):
            text, block = turn.get("user"), turn.get("fake_llm")
            if text is None or block is None:
                continue
            row = UTTERANCES.get(text)
            if row is None:
                missing.add(text)
                continue
            expect = row["expect"]
            where = f"{path.name} turn {i}"
            assert _observations(block) == _observations(expect), where
            assert sorted(block["intents"]) == sorted(expect["intents"]), where
            assert block["answered_pending"] == expect["answered_pending"], where
    if missing:
        warnings.warn(f"{len(missing)} script utterances are not in data/tests/utterances.jsonl yet "
                      "(the fake model falls back to the parser for them)", stacklevel=1)


# ------------------------------------------------------------------------------------------------ reply checks

def test_sign_matches_the_contract_vectors() -> None:
    data = json.loads((ROOT / "contracts" / "examples" / "hmac_vectors.json").read_text(encoding="utf-8"))
    for v in data["vectors"]:
        body = v["body"].encode("utf-8") if isinstance(v.get("body"), str) else b""
        headers = runner.sign(data["secret"], v["method"], v["path"], body, ts=int(v["timestamp"]))
        assert headers == v["headers"], v["name"]


def _reply(**over) -> dict:
    base = {"say": "Got it.", "ask": "How much is your rent?", "end": False, "end_reason": None, "lang": "en",
            "listen": "long", "expect": "number", "interruptible": True, "hold_s": 0, "display": None,
            "choices": None, "card_url": None, "debug": None}
    base.update(over)
    return base


def test_reply_checks() -> None:
    guard = runner.OutputGuard()
    ok = runner.reply_problems(_reply(), channel="phone", keys=["ack.short", "ask.rent"], budget="question",
                               is_start=False, guard=guard, state={})
    assert ok == []
    assert runner.count_words("Hi, this is GatorPlate — a student-built AI") == 7

    def problems(**over):
        return runner.reply_problems(_reply(**over), channel="phone", keys=None, budget="question", is_start=False,
                                     guard=guard, state={})

    assert any("symbols or digits" in p for p in problems(say="It is $306."))
    assert any("guard" in p for p in problems(say="You are approved."))
    assert any("words" in p for p in problems(say=" ".join(["word"] * 30)))
    ended = problems(end=True, end_reason="completed", ask=None, expect="open", interruptible=True)
    assert any("not interruptible" in p or "schema" in p for p in ended)  # the reply model enforces it too
    web = runner.reply_problems(_reply(display=None), channel="web", keys=None, budget=None, is_start=False,
                                guard=guard, state={})
    assert any("display" in p for p in web)
    state = {"card_url": "/c/" + "a" * 22}
    sticky = runner.reply_problems(_reply(display="x"), channel="web", keys=None, budget=None, is_start=False,
                                   guard=guard, state=state)
    assert any("stays set" in p for p in sticky)
    assert any("schema" in p for p in problems(extra_field=1))


def test_case_checks_read_the_console_detail() -> None:
    expect = runner.CaseExpect.model_validate({
        "slots": {"rent_share": "1100.00"}, "yellow_open": 0, "asked_flip": [
            {"slot": "rent_paid_by_others_to_landlord", "reason": "r"}],
        "skipped": [{"slot": "heat_cool", "reason": "no_effect"}], "privacy_events": [], "heard_excludes": ["F-1"]})
    case = {"slots": {"rent_share": {"value": "1100.00", "heard": "Eleven hundred"}}, "yellow_lines": [],
            "asked": [{"key": "flip.rent_paid_by_others", "kind": "flip",
                       "slots": ["rent_paid_by_others_to_landlord"], "reason": "r"}],
            "skipped": [{"slot": "heat_cool", "reason": "no_effect"}, {"slot": "x", "reason": "hard_stop"}],
            "privacy_events": []}
    assert runner.case_problems(expect, {"case": case}, 200, []) == []
    case["skipped"].append({"slot": "other_utils", "reason": "no_effect"})
    case["slots"]["age"] = {"value": "20", "heard": "I'm on an F-1"}
    found = runner.case_problems(expect, {"case": case}, 200, [])
    assert any("unexpected skipped" in p for p in found) and any("F-1" in p for p in found)
    assert runner.case_problems(runner.CaseExpect(deleted=True), None, 404, []) == []


# ------------------------------------------------------------------------------------------------ in-process

def _in_process(card_delivery: str, *, debug_keys: bool = True, dirs: list[Path] | None = None,
                only: list[str] | None = None, concurrency: int = 1, live: bool = False,
                stub_dirs: list[Path] | None = None) -> runner.Run:
    app = create_stub_app(card_delivery=card_delivery, debug_keys=debug_keys, script_dirs=stub_dirs)
    with TestClient(app) as client:
        run = runner.Run(kind="scripts", mode="in-process", llm="live" if live else "fake")
        target = runner.Target(client=client, base="http://testserver", secret=runner.DEV_GATEWAY_SECRET,
                               passcode="dev", debug_keys=debug_keys, card_delivery=card_delivery)
        items = runner.build_items("scripts", scripts_dir=dirs, examples_dir=None, only=only, live=live)
        runner.run_items(items, target, run, group=card_delivery, concurrency=concurrency)
    return run


def _skip_problems(run: runner.Run, mode: str, live: bool, dirs: list[Path] | None = None) -> list[str]:
    """Every skip has its reason: a phone script of the other card-delivery mode ("env:"), or — in a fake-model run
    only — a script that needs a live language model (fake_llm_ok false: regression scripts made from live
    conversations, docs/SPEC.md §10). Nothing else is skipped, and nothing that should be skipped runs."""
    scripts = {s.id: s for _, s in runner.load_scripts(dirs or runner.SCRIPTS_DIRS)}
    problems = []
    for r in run.results:
        script = scripts[r.id]
        other_mode_phone = script.channel == "phone" and script.card_mode != mode
        needs_live = not script.fake_llm_ok and not live
        if (r.status == "skipped") != (other_mode_phone or needs_live):
            problems.append(f"{r.id}: status {r.status} ({r.skip_reason})")
        elif other_mode_phone and not (r.skip_reason or "").startswith("env:"):
            problems.append(f"{r.id}: skipped for {r.skip_reason!r}, expected an env reason")
        elif needs_live and not other_mode_phone and "live language model" not in (r.skip_reason or ""):
            problems.append(f"{r.id}: skipped for {r.skip_reason!r}, expected the live-model reason")
    return problems


@pytest.mark.parametrize("live", [False, True], ids=["fake", "live"])
@pytest.mark.parametrize("mode", runner.CARD_MODES)
def test_every_script_plays_against_the_stub(mode: str, live: bool) -> None:
    run = _in_process(mode, live=live)
    failed = {r.id: r.failures[:3] for r in run.results if r.status == "failed"}
    assert failed == {}
    assert _skip_problems(run, mode, live) == []
    assert run.executed and all(r.keys_asserted and r.console_checked for r in run.executed)


@pytest.mark.parametrize("mode", runner.CARD_MODES)
def test_a_regression_script_that_needs_a_live_model_keeps_the_stub_test_green(mode: str, tmp_path: Path) -> None:
    """A regression script from a live conversation sets fake_llm_ok false (docs/SPEC.md §10): the fake-model run
    skips it with the live-model reason and the skip check accepts that; a live run plays it."""
    data = _load("sofia_g3")
    data["id"] = "regression_needs_live"
    data["fake_llm_ok"] = False
    (tmp_path / "regression_needs_live.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for live in (False, True):
        run = _in_process(mode, dirs=[tmp_path], live=live, stub_dirs=[tmp_path])
        (result,) = run.results
        assert result.status == ("passed" if live else "skipped"), (live, result.failures[:3])
        assert _skip_problems(run, mode, live, dirs=[tmp_path]) == []


def test_runner_detects_a_wrong_expectation(tmp_path: Path) -> None:
    data = _load("maria_g1")
    data["turns"][3]["expect_keys"] = ["ack.short", "ask.household"]
    data["final"]["estimate_monthly"] = 155
    (tmp_path / "maria_g1.json").write_text(json.dumps(data), encoding="utf-8")
    run = _in_process("screen", dirs=[tmp_path])
    (result,) = run.results
    assert result.status == "failed"
    assert any("turn 3" in f and "keys" in f for f in result.failures)
    assert any(f.startswith("final") and "estimate_monthly" in f for f in result.failures)
    summary = runner.summarize(run)
    assert summary["ok"] is False


def test_keys_not_asserted_with_debug_keys_off(tmp_path: Path) -> None:
    data = _load("maria_g1")
    data["turns"][3]["expect_keys"] = ["ack.short", "ask.household"]  # would fail if keys were asserted
    (tmp_path / "maria_g1.json").write_text(json.dumps(data), encoding="utf-8")
    run = _in_process("screen", debug_keys=False, dirs=[tmp_path])
    (result,) = run.results
    assert result.status == "passed" and result.keys_asserted is False
    report = runner.format_report(runner.summarize(run))
    assert "Sentence keys not asserted" in report


def test_conditional_scripts_skip_without_debug_keys() -> None:
    run = _in_process("code", debug_keys=False, only=["hourly_g12", "sofia_g3"])
    by_id = {r.id: r for r in run.results}
    assert by_id["hourly_g12"].status == "skipped" and "debug keys" in by_id["hourly_g12"].skip_reason
    assert by_id["sofia_g3"].status == "passed"


def test_only_selects_exactly_and_rejects_unknown_ids() -> None:
    items = runner.build_items("scripts", scripts_dir=None, examples_dir=None, only=["maria_g1", "a21_duplicate_seq"],
                               live=False)
    assert sorted(i.id for i in items) == ["a21_duplicate_seq", "maria_g1"]
    with pytest.raises(SystemExit):
        runner.build_items("scripts", scripts_dir=None, examples_dir=None, only=["maria_g1", "nope"], live=False)


def test_fake_llm_ok_false_is_skipped_and_counted(tmp_path: Path) -> None:
    data = _load("sofia_g3")
    data["fake_llm_ok"] = False
    (tmp_path / "sofia_g3.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    items = runner.build_items("scripts", scripts_dir=[tmp_path], examples_dir=None, only=None, live=False)
    assert items[0].skip and "live" in items[0].skip
    assert runner.build_items("scripts", scripts_dir=[tmp_path], examples_dir=None, only=None, live=True)[0].skip is None


def test_live_replay_skip_list() -> None:
    items = runner.build_items("examples", scripts_dir=None, examples_dir=None, only=None, live=False)
    replayed = {i.id for i in items if not i.skip}
    assert replayed == {"maria_phone", "sofia_web_es", "jamal_phone_expedited", "dtmf_consent",
                        "consent_declined_voice", "idempotent_seq", "unknown_call", "health"}
    skipped = {i.id: i.skip for i in items if i.skip}
    assert "rate limit" in skipped["web_session_rate_limited"]
    assert "clock" in skipped["bad_signature"] and "clock" in skipped["stale_timestamp"]
    assert all("seeded" in reason for sid, reason in skipped.items()
               if sid not in ("web_session_rate_limited", "bad_signature", "stale_timestamp"))
    envs = {i.id: i.env["GP_CARD_DELIVERY"] for i in items}
    assert envs["maria_phone"] == "screen" and envs["jamal_phone_expedited"] == "code" and envs["health"] == "code"


def test_report_format_is_readable() -> None:
    run = _in_process("code", only=["jamal_g4", "maria_g1", "sofia_g3"])
    summary = runner.summarize(run)
    text = runner.format_report(summary)
    assert "PASS jamal_g4" in text and "SKIP maria_g1: env:" in text and "Summary: 2 executed" in text
    assert "Result: OK" in text and summary["ok"] is True
    assert summary["counts"]["skipped"] == {"env": 1}
    assert summary["latency_ms"]["n"] > 0 and summary["latency_ms"]["p50"] is not None


# ------------------------------------------------------------------------------------------------ servers

def _free_port() -> int:
    return runner.free_port()


def _run_cli(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "tools" / "e2e_run.py"), *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=timeout)


def test_local_mode_one_server_per_declared_environment(tmp_path: Path) -> None:
    port = _free_port()
    report = tmp_path / "report.json"
    proc = _run_cli(["--scripts", "tests/e2e/scripts", "--serve", "--port", str(port), "--app", STUB_APP,
                     "--only", "maria_g1,sofia_g3,jamal_g4", "--db-dir", str(tmp_path), "--report-json", str(report),
                     "--concurrency", "3"])
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    summary = json.loads(report.read_text(encoding="utf-8"))
    groups = {g["label"]: g for g in summary["groups"]}
    assert set(groups) == {"card=screen", "card=code"}
    assert sorted(groups["card=screen"]["items"]) == ["maria_g1", "sofia_g3"]
    assert groups["card=code"]["items"] == ["jamal_g4"]
    pids = set()
    for label, g in groups.items():
        server = g["server"]
        assert server["started"] and server["stopped"], label
        assert server["card_delivery"] == g["env"]["GP_CARD_DELIVERY"], "never two modes in one server run"
        pids.add(server["pid"])
    assert len(pids) == 2
    assert summary["counts"] == {**summary["counts"], "executed": 3, "passed": 3, "failed": 0}
    assert not runner.port_in_use(port), "every server the runner started is stopped"
    assert "Result: OK" in proc.stdout


def test_local_mode_unknown_only_id_exits_nonzero(tmp_path: Path) -> None:
    port = _free_port()
    proc = _run_cli(["--scripts", "tests/e2e/scripts", "--serve", "--port", str(port), "--app", STUB_APP,
                     "--only", "maria_g1,no_such_script", "--db-dir", str(tmp_path)])
    assert proc.returncode != 0
    assert "no_such_script" in proc.stderr
    assert not runner.port_in_use(port)


class _StubServer:
    """A stub server started by the test itself for remote mode (the runner never starts one there)."""

    def __init__(self, card_delivery: str, debug_keys: bool, folder: Path) -> None:
        self.port = _free_port()
        env = {k: v for k, v in runner.LocalServer(app=STUB_APP, port=self.port, env={"GP_CARD_DELIVERY": card_delivery}, llm="fake",
                                                   db_dir=folder).child_env().items()
               if not k.startswith("GP_")}
        env.update(GP_CARD_DELIVERY=card_delivery, GP_DEBUG_KEYS="1" if debug_keys else "0")
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", STUB_APP, "--host", "127.0.0.1", "--port",
                                      str(self.port), "--workers", "1", "--no-access-log"], cwd=ROOT, env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.base = f"http://127.0.0.1:{self.port}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{self.base}/v1/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        self.stop()
        raise RuntimeError("stub server did not start")

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def test_remote_mode_skips_counts_and_never_starts_a_server(tmp_path: Path) -> None:
    screen = _StubServer("screen", debug_keys=True, folder=tmp_path)
    code = _StubServer("code", debug_keys=False, folder=tmp_path)
    try:
        # a phone script that declares code against a screen server: skipped and counted; nothing executed → non-zero
        report = tmp_path / "r1.json"
        p1 = _run_cli(["--scripts", "tests/e2e/scripts", "--base", screen.base, "--only", "jamal_g4",
                       "--report-json", str(report)])
        s1 = json.loads(report.read_text(encoding="utf-8"))
        assert p1.returncode != 0 and s1["counts"]["executed"] == 0 and s1["counts"]["skipped"] == {"env": 1}
        assert "Nothing was executed" in p1.stdout
        # sofia_g3 (web, declares screen) runs against a code server; maria_g1 (phone, screen) is skipped;
        # debug keys are off there, so keys are not asserted (everything else is)
        report = tmp_path / "r2.json"
        p2 = _run_cli(["--scripts", "tests/e2e/scripts", "--base", code.base, "--only", "sofia_g3,maria_g1",
                       "--report-json", str(report)])
        s2 = json.loads(report.read_text(encoding="utf-8"))
        items = {i["id"]: i for i in s2["items"]}
        assert p2.returncode == 0, p2.stdout[-2000:]
        assert items["sofia_g3"]["status"] == "passed" and items["sofia_g3"]["keys_asserted"] is False
        assert items["maria_g1"]["status"] == "skipped" and items["maria_g1"]["skip_reason"].startswith("env:")
        assert s2["groups"][0]["server"]["started"] is False
    finally:
        screen.stop()
        code.stop()


# ------------------------------------------------------------------------------------------------ say_call

def test_say_call_plays_a_script_then_ends_the_call() -> None:
    from tools import say_call

    app = create_stub_app(card_delivery="screen", debug_keys=True)
    with TestClient(app) as client:
        target = runner.Target(client=client, base="http://testserver", secret=runner.DEV_GATEWAY_SECRET,
                               passcode="dev")
        out = _Sink()
        script = next(s for _, s in runner.load_scripts(runner.SCRIPTS_DIRS) if s.id == "maria_g1")
        caller = say_call.Caller(target, "phone", "en", retry_s=1, out=out)
        assert target.console_ready()
        before = target.case_ids()
        assert say_call.play_script(caller, script) == 0
        (case_id,) = target.case_ids() - before
        _, detail = target.case_detail(case_id)
        assert detail["case"]["live"] is False, "the script's /end block was sent"
        assert caller.ended and caller.turns == 9
        assert "[end completed] HTTP 200" in out.text


def test_say_call_retries_with_the_same_call_and_seq() -> None:
    from tools import say_call

    app = create_stub_app(card_delivery="code", debug_keys=True)
    with TestClient(app) as client:
        target = runner.Target(client=client, base="http://testserver", secret=runner.DEV_GATEWAY_SECRET,
                               passcode=None)
        caller = say_call.Caller(target, "phone", "en", retry_s=5, out=_Sink())
        caller.start()
        calls = []
        real_post = target.post

        def flaky(path, body=None, **kwargs):
            calls.append((path, (body or {}).get("seq")))
            if len(calls) == 1:
                raise httpx.ConnectError("server restarting")
            return real_post(path, body, **kwargs)

        target.post = flaky  # type: ignore[method-assign]
        reply = caller.turn({"event": "utterance", "text": "Yeah, sure.", "masked": False, "confidence": 0.94,
                             "interrupted": False, "typed": False})
        assert reply["debug"]["keys"] == ["ack.short", "ask.level_units"]
        assert calls[0] == calls[1] and calls[0][1] == 1


class _Sink:
    def __init__(self) -> None:
        self.text = ""

    def write(self, s: str) -> int:
        self.text += s
        return len(s)

    def flush(self) -> None:
        pass


# ------------------------------------------------------------------------------------------------ evaluation

PERSONAS = json.loads((ROOT / "data" / "eval" / "personas.json").read_text(encoding="utf-8"))


def test_personas_cover_the_evaluation_plan() -> None:
    from gatorplate.contracts.rules_io import Facts

    personas = PERSONAS["personas"]
    assert PERSONAS["count"] == len(personas) >= 30
    spanish = [p for p in personas if p["lang"] == "es"]
    assert len(spanish) >= 10 and all(p["channels"] == ["web"] for p in spanish)
    assert all(p["channels"] == ["web", "phone"] for p in personas if p["lang"] == "en")
    ids = [p["id"] for p in personas]
    assert len(ids) == len(set(ids))
    golden = {p["golden_case"] for p in personas}
    want_g = {"G1", "G1-b", "G1-c", "G2", "G3", "G4", "G5", "G6", "G6-b", "G7", "G8", "G9", "G10", "G11", "G12", "G13"}
    assert want_g <= golden
    for n in ("N1", "N3", "N5", "N6-b", "N7", "N10", "N12", "N13", "N18"):
        assert any(g == n or g.startswith(n + "-") for g in golden), n
    covers = " ".join(c for p in personas for c in p["covers"])
    for behavior in ("several facts at once", "corrections", "ranges", "hourly", "biweekly", "'sometimes' family cash",
                     "parents paying the landlord", "shared food", "under 22 with a parent", "a volunteered status"):
        assert behavior in covers, behavior
    keys = runner.sentence_keys()
    for p in personas:
        Facts.model_validate(p["facts"])
        assert p["facts"]["lang"] == p["lang"]
        assert set(p["answers"]) <= keys, p["id"]
        assert "crisis" not in " ".join(p["covers"]), "crisis is tested with fixed scripts only"


def test_wilson_upper_bound() -> None:
    from tools import simulate_student as sim

    assert f"{100 * sim.wilson_upper(0, 30):.1f}" == "11.4"
    assert f"{100 * sim.wilson_upper(0, 40):.1f}" == "8.8"
    assert sim.wilson_upper(0, 0) is None


def test_metrics_count_a_wrong_result_as_flagged_only_by_a_related_yellow_line() -> None:
    """docs/SPEC.md §10 silent errors: an open yellow line flags a wrong result only when it names the route, a slot
    that made it wrong, or the call ended incomplete; the truth inside the estimate range also flags it. An unrelated
    open line (a half-time question on a rent error) does not — the old count took any open line."""
    from tools import simulate_student as sim

    truth = {"tier": "likely", "reason_code": "likely", "monthly": 306, "expedited": "no"}
    good = sim.Outcome("a", "en", "web", truth, case={"tier": "likely", "estimate_monthly": 306,
                                                      "expedited_possible": "no", "yellow_lines": [], "asked": [],
                                                      "turn_count": 9})
    route = sim.Outcome("b", "es", "web", truth, case={
        "tier": "coordinator", "reason_code": "coordinator.shared_household", "estimate_monthly": None,
        "yellow_lines": [{"code": "coordinator.shared_household", "slot": "household_food", "resolved": None}]})
    resolved = sim.Outcome("c", "en", "phone", truth, case={"tier": "likely", "estimate_monthly": 155,
                                                            "yellow_lines": [{"code": "x", "resolved": "confirm"}]})
    unrelated = sim.Outcome("d", "en", "web", truth, case={
        "tier": "likely", "estimate_monthly": 155, "estimate_range": {"lo": 155, "hi": 285, "settled": False},
        "yellow_lines": [{"code": "unclear.half_time", "slot": "half_time", "resolved": None}]})
    in_range = sim.Outcome("e", "en", "web", truth, case={
        "tier": "likely", "estimate_monthly": 155, "estimate_range": {"lo": 155, "hi": 306, "settled": False},
        "yellow_lines": [{"code": "student_question", "resolved": None}]})
    incomplete = sim.Outcome("f", "en", "web", truth, case={
        "tier": None, "estimate_monthly": None, "yellow_lines": [{"code": "incomplete", "resolved": None}]})
    m = sim.metrics([good, route, resolved, unrelated, in_range, incomplete], brain_cost_usd=0.06)
    assert m["silent_errors"] == [2, 6], "the resolved line and the unrelated line leave their errors silent"
    assert m["silent_errors_any_line"] == [1, 6], "counting any open line hides the unrelated-line error"
    assert m["tier_agreement"] == [4, 6]
    assert m["amount_exact"] == [1, 4] and m["amount_mae"] == 113.25
    assert m["expedited_agreement"] == [1, 6] and m["brain_llm_cost_per_call_usd"] == 0.01


@pytest.fixture(scope="module")
def real_rules():
    from gatorplate.config import Settings
    from gatorplate.rules import Rules

    return Rules.from_settings(Settings(env="test", llm_provider="fake"))


def _persona(pid: str) -> dict:
    return next(p for p in PERSONAS["personas"] if p["id"] == pid)


def _heard(pid: str, **changes) -> dict:
    from gatorplate.contracts.rules_io import Facts

    facts = {**_persona(pid)["facts"], **changes}
    return Facts.model_validate(facts).model_dump(mode="json")


def test_a_yellow_line_must_name_the_slot_that_made_the_result_wrong(real_rules) -> None:
    """Three wrong live calls rebuilt from their final cases; the old count called all three flagged because each had
    an open yellow line. The dorm and parent-cash calls have lines only on unrelated slots: silent. The heating-bill
    call's open line is the heating-bill assumption, and confirming that one slot with the student moves the estimate
    to $285, within $50 of the true $306: flagged. A line on the slot that made a result wrong flags it."""
    from tools import simulate_student as sim

    def outcome(pid: str, heard: dict, case: dict) -> sim.Outcome:
        persona = _persona(pid)
        return sim.Outcome(pid, persona["lang"], "web", sim.truth_for(real_rules, persona), case=case,
                           truth_facts=sim.persona_facts(persona), heard_facts=heard)

    # heating bill persona: the brain heard "a parent pays all the rent" (the student said nobody does); the open
    # line is the heating-bill assumption the question limit left over
    heat = outcome("p03_heat_bill", _heard("p03_heat_bill", rent_paid_by_others_to_landlord="1100", utility="none",
                                           household_food="alone"),
                   {"tier": "likely", "reason_code": "likely", "estimate_monthly": 155,
                    "estimate_range": {"lo": 155, "hi": 285, "settled": False},
                    "yellow_lines": [{"code": "assumed.heat_cool", "slot": "heat_cool", "resolved": None}]})
    # dorm persona: the meal plan was never asked; the open lines are about units and cash
    dorm = outcome("p30_dorm_es", _heard("p30_dorm_es", meals_per_week=0, household_food="separate", units=None),
                   {"tier": "likely", "reason_code": "likely", "estimate_monthly": 306,
                    "estimate_range": {"lo": 306, "hi": 306, "settled": True},
                    "yellow_lines": [{"code": "unclear.half_time", "slot": "half_time", "resolved": None},
                                     {"code": "unclear.cash_on_hand", "slot": "cash_on_hand", "resolved": None}]})
    # parent-cash persona: the parent's $300 a month was not heard
    cash = outcome("p31_parent_cash_es", _heard("p31_parent_cash_es", incomes=[
        {"amount": "1200", "freq": "monthly", "kind": "earned", "excluded": False, "label": ""}]),
                   {"tier": "likely", "reason_code": "likely", "estimate_monthly": 241,
                    "estimate_range": {"lo": 241, "hi": 294, "settled": False},
                    "yellow_lines": [{"code": "unclear.half_time", "slot": "half_time", "resolved": None},
                                     {"code": "assumed.other_utils", "slot": "other_utils", "resolved": None}]})
    calls = [heat, dorm, cash]
    scores = [sim.score(o, rules=real_rules) for o in calls]
    assert [s["decisive_slots"] for s in scores] == [
        ["heat_cool", "other_utils", "rent_paid_by_others_to_landlord"], ["dorm_meals_over_10", "meals_per_week"],
        sorted(sim.FACT_SLOTS["incomes"])]
    assert "household_food" in scores[0]["differing"], "a differing fact that changes nothing is not decisive"
    m = sim.metrics(calls, None, rules=real_rules)
    assert m["silent_errors"] == [2, 3] and m["silent_errors_any_line"] == [0, 3]
    assert [s["silent"] for s in scores] == [False, True, True]
    heat.case["yellow_lines"] = [{"code": "unclear.household_food", "slot": "household_food", "resolved": None}]
    assert sim.score(heat, rules=real_rules)["silent"], "a line on a fact that changes nothing does not flag"
    heat.case["yellow_lines"].append({"code": "unclear.rent_paid_by_others_to_landlord", "slot": None,
                                      "resolved": None})
    dorm.case["yellow_lines"].append({"code": "unclear.meals_per_week", "slot": "meals_per_week", "resolved": None})
    assert sim.metrics(calls, None, rules=real_rules)["silent_errors"] == [1, 3]


def test_fact_slots_cover_every_engine_fact() -> None:
    from gatorplate.contracts.rules_io import Facts
    from gatorplate.contracts.slots import SlotName
    from tools import simulate_student as sim

    assert set(sim.FACT_SLOTS) == set(Facts.model_fields) - {"lang", "apply_date", "status_route"}
    names = {s.value for s in SlotName}
    assert all(slot in names for slots in sim.FACT_SLOTS.values() for slot in slots)


class _GoldenRules:
    """Answers every golden case with its expected values (so the refusal check passes) and a persona with a fixed
    likely result."""

    def __init__(self, fail: bool = False) -> None:
        from gatorplate.contracts.rules_io import Facts

        data = json.loads((ROOT / "data" / "golden" / "golden_cases.json").read_text(encoding="utf-8"))
        self.cases = [(Facts.model_validate(c["facts"]), c["expected"]) for c in data["cases"]]
        self.fail = fail

    def evaluate(self, facts, *, today):
        from types import SimpleNamespace

        exp = next((e for f, e in self.cases if f == facts), None)
        if exp is None or self.fail:
            exp = {"tier": "likely", "reason_code": "likely", "amount": 1 if self.fail else 306, "expedited": None}
        return SimpleNamespace(tier=exp["tier"], reason_code=exp["reason_code"], monthly=exp.get("amount"),
                               expedited=exp.get("expedited"))


def test_simulate_student_refuses_unless_the_golden_cases_pass() -> None:
    from tools import simulate_student as sim

    class NotBuilt:
        def evaluate(self, facts, *, today):
            raise NotImplementedError

    assert sim.main(["--base", "http://testserver"], client=object(), rules=NotBuilt()) == 2
    assert sim.main(["--base", "http://testserver"], client=object(), rules=_GoldenRules(fail=True)) == 2


def test_simulate_student_scripted_run_writes_the_report(tmp_path: Path) -> None:
    from tools import simulate_student as sim

    rules = _GoldenRules()
    assert sim.check_golden(rules) == []
    app = create_stub_app(card_delivery="screen", debug_keys=True)
    report = tmp_path / "eval.md"
    with TestClient(app) as client:
        code = sim.main(["--base", "http://127.0.0.1:8000", "--only", "p01_maria,p25_sofia", "--report", str(report)],
                        client=client, rules=rules)
    assert code == 0
    text = report.read_text(encoding="utf-8")
    assert text.startswith("# Text-level evaluation with simulated students")
    assert "Silent errors (k/n, Wilson 95 % upper bound)" in text and "| Overall | English | Spanish |" in text
    data = json.loads(report.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["calls"] == 3  # Maria on web and phone, Sofia on web
    assert {c["channel"] for c in data["per_call"]} == {"web", "phone"}
    assert "Yes, go ahead." not in text and "I'm a junior" not in text, "no utterance in the report"


def test_a_declared_provider_never_gets_the_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GP_LLM_API_KEY", "placeholder-not-a-key")
    live = runner.LocalServer(app=STUB_APP, port=1, env={"GP_CARD_DELIVERY": "code"}, llm="anthropic",
                              db_dir=tmp_path).child_env()
    assert live["GP_LLM_API_KEY"] == "placeholder-not-a-key" and live["GP_LLM_PROVIDER"] == "anthropic"
    closed = runner.LocalServer(app=STUB_APP, port=1, env={"GP_CARD_DELIVERY": "code", "GP_LLM_PROVIDER": "anthropic"},
                                llm="anthropic", db_dir=tmp_path).child_env()
    assert "GP_LLM_API_KEY" not in closed and closed["GP_LLM_PROVIDER"] == "anthropic"
    fake = runner.LocalServer(app=STUB_APP, port=1, env={"GP_CARD_DELIVERY": "code"}, llm="fake",
                              db_dir=tmp_path).child_env()
    assert "GP_LLM_API_KEY" not in fake and fake["GP_LLM_PROVIDER"] == "fake"
    assert all(k.startswith("GP_") or k in ("PATH", "HOME", "TMPDIR", "PYTHONUTF8", "PYTHONPATH", "HTTPS_PROXY",
                                            "HTTP_PROXY", "NO_PROXY") for k in fake)


def test_remote_mode_skips_scripts_that_need_a_local_setting() -> None:
    app = create_stub_app(card_delivery="code", debug_keys=True)
    with TestClient(app) as client:
        run = runner.Run(kind="scripts", mode="remote", llm="server's")
        target = runner.Target(client=client, base="http://testserver", secret=runner.DEV_GATEWAY_SECRET,
                               passcode="dev", debug_keys=True, card_delivery="code", remote=True)
        items = runner.build_items("scripts", scripts_dir=None, examples_dir=None,
                                   only=["a26_closed_mode", "jamal_g4"], live=False)
        runner.run_items(items, target, run, group="")
    by_id = {r.id: r for r in run.results}
    assert by_id["a26_closed_mode"].status == "skipped"
    assert by_id["a26_closed_mode"].skip_reason == "env: declares GP_LLM_PROVIDER (local server only)"
    assert by_id["jamal_g4"].status == "passed"


# ------------------------------------------------------------------------------------------------ review additions

def test_opening_reply_rules() -> None:
    """docs/BRAIN_API.md §6: the /start reply has words, a consent question, no end and is never interruptible."""
    guard = runner.OutputGuard()

    def opening(**over):
        return runner.reply_problems(_reply(**{"expect": "yes_no", "interruptible": False, **over}), channel="phone",
                                     keys=["consent.ask"], budget="opening", is_start=True, guard=guard, state={})

    assert opening() == []
    assert any("never empty" in p for p in opening(say="  "))
    assert any("consent" in p for p in opening(ask=None, expect="open"))
    assert any("interruptible" in p for p in opening(interruptible=True))


def test_phone_reply_language_and_card_fields() -> None:
    guard = runner.OutputGuard()

    def phone(keys, **over):
        return runner.reply_problems(_reply(**over), channel="phone", keys=keys, budget=None, is_start=False,
                                     guard=guard, state={})

    assert any("lang must be en" in p for p in phone(["ack.short", "ask.rent"], lang="es"))
    assert phone(["language.offer_web"], lang="es", ask=None, expect="open", say="Hola.") == []
    assert any("card_url null" in p for p in phone(["ack.short"], card_url="/c/" + "a" * 22))
    assert any("written URL" in p for p in phone(None, say="Go to www.gatorplate.org."))  # spoken, never written
    assert any("symbols" in p for p in phone(None, say="Call four one five – now."))  # en dash


def test_forbidden_wording_never_passes() -> None:
    """docs/BRAIN_API.md §7 and data/content/guards.json: rejections, promises and program promises, both
    languages."""
    guard = runner.OutputGuard()
    for text in ("You're not eligible.", "You don't qualify for CalFresh.", "I'll text you the card.",
                 "I sent it to the coordinator.", "You will save $200 a year.", "No eres elegible.",
                 "You're covered by Medi-Cal."):
        assert guard.hits(text), text
    for text in ("The county makes the final decision.", "Estimates. Each agency decides. Not a promise."):
        assert guard.hits(text) == [], text


def test_declared_budget_must_match_the_reply_class(tmp_path: Path) -> None:
    """A turn that declares a question budget while the brain answers with a result (or the reverse) fails, so a
    script cannot hide a result reply behind the 25-word class or a question behind the 45-word class."""
    data = _load("maria_g1")
    i = next(n for n, t in enumerate(data["turns"]) if "result.likely" in (t.get("expect_keys") or []))
    assert data["turns"][i]["budget"] == "result"
    data["turns"][i]["budget"] = "question"
    (tmp_path / "maria_g1.json").write_text(json.dumps(data), encoding="utf-8")
    run = _in_process("screen", dirs=[tmp_path])
    (result,) = run.results
    assert any(f"turn {i}" in f and "declares a question turn" in f for f in result.failures), result.failures


def test_privacy_check_scans_every_stored_text() -> None:
    """heard_excludes: a volunteered status or a number may survive nowhere in the stored case (a yellow line's
    quote, the summary), while ids and timestamps never count as student text."""
    expect = runner.CaseExpect(heard_excludes=["F-1", "123"])
    clean = {"case": {"id": "c_abc123defg", "created_at": "2026-10-02T17:00:00.123Z", "code": "ABC-234",
                      "slots": {"age": {"value": "20", "heard": "I'm 20"}}, "yellow_lines": []},
             "summary": {"id": "c_abc123defg", "summary": "Undergrad · 1 person"}, "card_url": "/c/x123"}
    assert runner.case_problems(expect, clean, 200, []) == []
    leaky = json.loads(json.dumps(clean))
    leaky["case"]["yellow_lines"] = [{"code": "student_question", "heard": "I'm on an F-1, can I apply?"}]
    found = runner.case_problems(expect, leaky, 200, [])
    assert any("F-1" in p and "yellow_lines[0].heard" in p for p in found), found
    leaky["summary"]["summary"] = "Undergrad · SSN 123"
    assert any("'123'" in p for p in runner.case_problems(expect, leaky, 200, []))


def test_remote_mode_skips_phone_scripts_when_the_mode_is_unknown() -> None:
    app = create_stub_app(card_delivery="code", debug_keys=True)
    with TestClient(app) as client:
        run = runner.Run(kind="scripts", mode="remote", llm="server's")
        target = runner.Target(client=client, base="http://testserver", secret=runner.DEV_GATEWAY_SECRET,
                               passcode="dev", debug_keys=True, card_delivery=None, remote=True)
        items = runner.build_items("scripts", scripts_dir=None, examples_dir=None,
                                   only=["jamal_g4", "sofia_g3"], live=False)
        runner.run_items(items, target, run, group="")
    by_id = {r.id: r for r in run.results}
    assert by_id["jamal_g4"].status == "skipped" and by_id["jamal_g4"].skip_reason.startswith("env:")
    assert by_id["sofia_g3"].status == "passed", "web scripts run in every mode"


def test_local_mode_refuses_a_server_that_does_not_confirm_its_mode(tmp_path: Path) -> None:
    port = _free_port()
    report = tmp_path / "report.json"
    proc = _run_cli(["--scripts", "tests/e2e/scripts", "--serve", "--port", str(port), "--app",
                     "tests.e2e.stub_app:app_without_mode", "--only", "jamal_g4", "--db-dir", str(tmp_path),
                     "--report-json", str(report)])
    assert proc.returncode != 0
    summary = json.loads(report.read_text(encoding="utf-8"))
    (group,) = summary["groups"]
    assert "card_delivery" in group["error"] and group["server"]["stopped"] is True
    assert summary["items"][0]["status"] == "failed"
    assert not runner.port_in_use(port)


def test_local_mode_refuses_a_busy_port(tmp_path: Path) -> None:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        port = busy.getsockname()[1]
        proc = _run_cli(["--scripts", "tests/e2e/scripts", "--serve", "--port", str(port), "--app", STUB_APP,
                         "--only", "jamal_g4", "--db-dir", str(tmp_path), "--report-json",
                         str(tmp_path / "r.json")])
    assert proc.returncode != 0 and "in use" in proc.stdout


def test_a_terminated_runner_stops_its_server(tmp_path: Path) -> None:
    """SIGTERM (a closed terminal, a killed make) still stops the local server: the server lives in its own session,
    so without the runner's handler it would keep the port."""
    import os
    import signal as sig

    port = _free_port()
    report = tmp_path / "report.json"
    proc = subprocess.Popen([sys.executable, str(ROOT / "tools" / "e2e_run.py"), "--scripts", "tests/e2e/scripts",
                             "--scripts", "tests/adversarial/scripts", "--serve", "--port", str(port), "--app",
                             STUB_APP, "--db-dir", str(tmp_path), "--report-json", str(report)], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not runner.port_in_use(port) and proc.poll() is None:
            time.sleep(0.05)
        assert proc.poll() is None, "the run ended before the test could stop it"
        time.sleep(0.3)
        proc.send_signal(sig.SIGTERM)
        out, _ = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 130, out[-1500:]
    assert "interrupted" in out
    summary = json.loads(report.read_text(encoding="utf-8"))
    for group in summary["groups"]:
        server = group["server"] or {}
        if server.get("started"):
            assert server["stopped"] is True
            try:
                os.kill(server["pid"], 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("the server process is still running")
    deadline = time.monotonic() + 5
    while runner.port_in_use(port) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not runner.port_in_use(port)


def test_say_call_ends_with_the_reason_of_the_reply_that_ended_the_call(tmp_path: Path) -> None:
    from tools import say_call

    data = _load("a01_consent_no")
    data.pop("end", None)
    (tmp_path / "a01_consent_no.json").write_text(json.dumps(data), encoding="utf-8")
    script = runner.load_script(tmp_path / "a01_consent_no.json")
    app = create_stub_app(card_delivery="code", debug_keys=True)
    with TestClient(app) as client:
        target = runner.Target(client=client, base="http://testserver", secret=runner.DEV_GATEWAY_SECRET,
                               passcode=None)
        out = _Sink()
        caller = say_call.Caller(target, "phone", "en", retry_s=1, out=out)
        assert say_call.play_script(caller, script) == 0
    assert "[end declined] HTTP 200" in out.text


def test_simulate_student_truth_has_no_outlook_without_the_cash_question() -> None:
    from types import SimpleNamespace

    from tools import simulate_student as sim

    persona = next(p for p in PERSONAS["personas"] if p["id"] == "p01_maria")

    class Rules:
        def __init__(self, screen):
            self.screen = screen

        def evaluate(self, facts, *, today):
            return SimpleNamespace(tier="likely", reason_code="likely", monthly=306, expedited=False,
                                   expedited_screen=self.screen)

    assert sim.truth_for(Rules(True), persona)["expedited"] == "no"
    assert sim.truth_for(Rules(False), persona)["expedited"] is None
    # the engine's outlook stays available for a call that asked the cash question anyway (docs/SPEC.md §5.8)
    assert sim.truth_for(Rules(False), persona)["expedited_if_asked"] == "no"


def test_expedited_truth_follows_the_cash_question_and_maybe_is_counted_apart(real_rules) -> None:
    """The call asks the cash question when the screen applies in any world still open (docs/SPEC.md §5.5, §5.8), so
    a correct "no" after that question is an agreement even when the true world's screen is off; "maybe" is the
    designed hedge and is counted on its own line, not as a disagreement."""
    from tools import simulate_student as sim

    hourly = sim.truth_for(real_rules, _persona("p14_hourly"))
    assert hourly["expedited"] is None and hourly["expedited_if_asked"] == "no"
    asked = [{"key": "ask.rent", "kind": "standard", "slots": ["rent_share"]},
             {"key": "expedited.intro_cash", "kind": "standard", "slots": ["cash_on_hand"]}]

    def call(truth: dict, outlook: str | None, questions: list[dict]) -> sim.Outcome:
        return sim.Outcome("p", "en", "web", truth, case={"tier": truth["tier"], "estimate_monthly": truth["monthly"],
                                                          "expedited_possible": outlook, "yellow_lines": [],
                                                          "asked": questions})

    no_after_cash = call(hourly, "no", asked)
    maybe = call(sim.truth_for(real_rules, _persona("p17_grad_work_study")), "maybe", asked)
    not_asked = call(hourly, None, asked[:1])
    wrong = call(sim.truth_for(real_rules, _persona("p05_couch")), "no", asked)
    m = sim.metrics([no_after_cash, maybe, not_asked, wrong], None, rules=real_rules)
    assert m["expedited_agreement"] == [1, 2], "the correct 'no' agrees; the couch persona's 'no' does not"
    assert m["expedited_maybe"] == [1, 3]
    unknown_cash = dict(hourly, expedited_if_asked=None)
    assert sim.expected_outlook(unknown_cash, no_after_cash.case) is None, "no truth when the cash is unknown"


def test_scripted_personas_state_the_cash_their_facts_hold() -> None:
    """A persona whose scripted answer gives its cash on hand carries that cash in its facts, so the expedited truth
    and the call agree on what was said."""
    for p in PERSONAS["personas"]:
        if "expedited.intro_cash" in p["answers"]:
            assert p["facts"]["cash_on_hand"] is not None, p["id"]


# ------------------------------------------------------------------------------------------------ model-played students

_FACT_WORDS = {
    "en": {"parent": ("parent", "mom", "dad"), "shared": ("together",), "couch": ("couch",), "dorm": ("dorm",)},
    "es": {"parent": ("papás", "mamá", "papá", "padres"), "shared": ("juntos",), "couch": ("sofá",),
           "dorm": ("residencia",)},
}
_PERIODS = {"en": {"weekly": ("a week",), "biweekly": ("every two weeks",)},
            "es": {"weekly": ("a la semana", "cada semana"), "biweekly": ("cada dos semanas",)}}


def _story_numbers(story: str) -> set:
    import re
    from decimal import Decimal

    plain = re.sub(r"(?<=\d),(?=\d{3}\b)", "", story)
    return {Decimal(n) for n in re.findall(r"\d+(?:\.\d+)?", plain)}


def test_every_persona_story_states_its_facts_in_plain_words() -> None:
    """The model-played student gets each persona's story, not its facts: every amount with its own period, the
    units, the age and the situations the rules route on are in it, in the persona's language."""
    from decimal import Decimal

    for p in PERSONAS["personas"]:
        story, f, lang = p.get("story") or "", p["facts"], p["lang"]
        assert story.strip(), p["id"]
        numbers = _story_numbers(story)
        assert f["age"] in numbers and (f["units"] is None or f["units"] in numbers), p["id"]
        for name in ("rent_share", "rent_paid_by_others_to_landlord", "homeless_shelter_cost", "cash_on_hand"):
            if f[name] is not None and Decimal(f[name]) > 0:
                assert Decimal(f[name]) in numbers, (p["id"], name)
        for income in f["incomes"]:
            amount = Decimal(income["amount"])
            label = [Decimal(x) for x in __import__("re").findall(r"\d+(?:\.\d+)?", income["label"])]
            pair = next(((a, b) for a in label for b in label if a * b == amount), None)
            assert amount in numbers or (pair and set(pair) <= numbers), (p["id"], income)
            if income["freq"] in _PERIODS[lang]:
                assert any(w in story for w in _PERIODS[lang][income["freq"]]), (p["id"], income["freq"])
        words = _FACT_WORDS[lang]
        if f["under22_with_parent"]:
            assert any(w in story for w in words["parent"]), p["id"]
        if f["household_food"] == "shared":
            assert any(w in story for w in words["shared"]), p["id"]
        if f["homeless"]:
            assert any(w in story for w in words["couch"]), p["id"]
        if f["dorm_on_campus"]:
            assert any(w in story for w in words["dorm"]) and f["meals_per_week"] in numbers, p["id"]
        if f["volunteered_status"]:
            assert f["volunteered_status"] in story, p["id"]


def test_the_model_student_gets_the_story_never_the_facts(monkeypatch) -> None:
    from gatorplate.contracts.rules_io import Facts
    from tools import simulate_student as sim

    for p in PERSONAS["personas"]:
        prompt = sim.student_system_prompt(p)
        assert prompt.endswith(p["story"]) and "{" not in prompt, p["id"]
        leaked = [name for name in Facts.model_fields if "_" in name and name in prompt]
        assert leaked == [], (p["id"], leaked)
        assert ("Spanish" if p["lang"] == "es" else "English") in prompt
    assert "never convert an amount to another period" in sim.student_system_prompt(_persona("p32_biweekly_es"))
    with pytest.raises(ValueError):
        sim.student_system_prompt({**_persona("p01_maria"), "story": " "})
    placeholder = "placeholder-not-a-key"  # never sent: the client is built, no request is made
    student = sim.ModelStudent(_persona("p25_sofia"), model="m", api_key=placeholder,
                               base_url="http://127.0.0.1:9", price_in=1.0, price_out=5.0)
    assert student.system == sim.student_system_prompt(_persona("p25_sofia")) and "under22_with_parent" not in student.system


def test_answers_of_what_was_said_rescore_a_run_without_a_call(real_rules, tmp_path: Path) -> None:
    """A model-played student that departs from its persona is adjudicated: the report scores every metric against
    the persona and against what was said, and --rescore applies an adjudication file to a finished run."""
    from tools import simulate_student as sim

    by_id = {p["id"]: p for p in PERSONAS["personas"]}
    biweekly = _persona("p32_biweekly_es")
    monthly_1800 = [{"amount": "1800", "freq": "monthly", "kind": "earned", "excluded": False, "label": ""}]
    said = sim.truth_for(real_rules, biweekly, {"incomes": monthly_1800})
    heard = _heard("p32_biweekly_es", incomes=monthly_1800)
    o = sim.Outcome("p32_biweekly_es", "es", "web", sim.truth_for(real_rules, biweekly),
                    case={"tier": "likely", "reason_code": "likely", "estimate_monthly": said["monthly"],
                          "yellow_lines": [], "asked": []},
                    truth_facts=sim.persona_facts(biweekly), heard_facts=heard)
    adj = tmp_path / "adj.json"
    adj.write_text(json.dumps({"adjudications": [{"persona": "p32_biweekly_es", "channel": "web",
                                                  "said": {"incomes": monthly_1800},
                                                  "note": "said a monthly amount"}]}), encoding="utf-8")
    entries = sim.load_adjudications(adj, by_id)
    assert sim.apply_adjudications([o], entries, by_id, real_rules) == 1
    persona_view = sim.metrics([o], None, rules=real_rules)
    said_view = sim.metrics([o], None, against="said", rules=real_rules)
    assert persona_view["amount_exact"] == [0, 1] and persona_view["silent_errors"] == [1, 1]
    assert said_view["amount_exact"] == [1, 1] and said_view["silent_errors"] == [0, 1]
    assert said_view["student_departures"] == [1, 1]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"persona": "p32_biweekly_es", "said": {"pay": "1800"}}]), encoding="utf-8")
    with pytest.raises(ValueError):
        sim.load_adjudications(bad, by_id)

    # --rescore: a finished run's JSON report, no client at all
    report = {"started_at": "t", "base": "http://127.0.0.1:8006", "mode": "live", "order": "coverage",
              "persona_ids": ["p32_biweekly_es"], "planned_calls": 1, "stopped_by_cap": False, "max_usd": 1.5,
              "brain_llm": "anthropic", "skipped": {}, "student_cost_usd": 0.01,
              "cost_usd": {"student": 0.01, "brain": 0.05, "total": 0.06, "per_call": 0.06},
              "per_call": [{"outcome": dict(o.to_row())}]}
    old = tmp_path / "eval-live.json"
    old.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "rescored.md"
    assert sim.main(["--rescore", str(old), "--adjudicate", str(adj), "--report", str(out)], client=object(),
                    rules=real_rules) == 0
    text = out.read_text(encoding="utf-8")
    assert "Rescored from eval-live.json with 1 adjudicated call(s)" in text
    assert "Against what the students said" in text and "said a monthly amount" not in text
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["metrics_said"]["all"]["silent_errors"] == [0, 1] and data["metrics"]["all"]["silent_errors"] == [1, 1]
    report["per_call"] = [{"persona": "p32_biweekly_es"}]
    old.write_text(json.dumps(report), encoding="utf-8")
    assert sim.main(["--rescore", str(old), "--report", str(out)], client=object(), rules=real_rules) == 2


# ------------------------------------------------------------------------------------------------ order, cap, record

def test_coverage_order_reaches_both_languages_before_any_second_channel() -> None:
    """A run stopped by the spending cap still covers both languages and as many personas as it can: every persona
    once (web, languages interleaved, the smaller language first), then the phone calls."""
    from tools import simulate_student as sim

    personas = PERSONAS["personas"]
    n_es = sum(1 for p in personas if p["lang"] == "es")
    plan = sim.plan_calls(personas, {"web", "phone"}, "coverage")
    assert len(plan) == len(sim.plan_calls(personas, {"web", "phone"}, "file"))
    first = plan[: len(personas)]
    assert {p["id"] for p, _ in first} == {p["id"] for p in personas} and {c for _, c in first} == {"web"}
    assert [p["lang"] for p, _ in plan[: 2 * n_es]] == ["es", "en"] * n_es
    capped = plan[:24]  # what a $1.5 cap allowed at the measured $0.061 per call
    assert sum(1 for p, _ in capped if p["lang"] == "es") == n_es
    assert all(c == "phone" for _, c in plan[len(personas):])
    file_order = sim.plan_calls(personas, {"web", "phone"}, "file")
    assert not any(p["lang"] == "es" for p, _ in file_order[:24]), "the file order reaches no Spanish persona"


def test_a_live_run_never_starts_a_call_that_would_pass_the_cap(monkeypatch, tmp_path: Path) -> None:
    """The cap stops the run before a call whose measured cost would push the spend over it, and the report keeps the
    measured cost; the conversation record keeps every call for regression scripts."""
    from tools import simulate_student as sim

    class PricedStudent(sim.ScriptedStudent):
        def __init__(self, persona, **kwargs) -> None:
            super().__init__(json.loads(json.dumps(persona)))
            self.cost_usd = 0.40

    monkeypatch.setattr(sim, "ModelStudent", PricedStudent)
    monkeypatch.setenv("GP_LLM_API_KEY", "placeholder-not-a-key")
    app = create_stub_app(card_delivery="screen", debug_keys=True)
    report = tmp_path / "eval.md"
    with TestClient(app) as client:
        code = sim.main(["--base", "http://127.0.0.1:8000", "--only", "p01_maria,p25_sofia", "--live",
                         "--max-usd", "1.0", "--report", str(report)], client=client, rules=_GoldenRules())
    assert code == 0
    data = json.loads(report.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["calls"] == 2 and data["stopped_by_cap"] is True and data["cost_usd"]["total"] <= 1.0
    assert [(c["persona"], c["channel"]) for c in data["per_call"]] == [("p01_maria", "web"), ("p25_sofia", "web")]
    assert data["metrics"]["all"]["personas_reached"] == [2, 2]
    text = report.read_text(encoding="utf-8")
    assert "Measured cost of this run: student model $0.8000" in text and "the cap allows about 2 calls" in text
    record = [json.loads(line) for line in report.with_suffix(".calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["persona"] for r in record] == ["p01_maria", "p25_sofia"]
    said = [e["event"]["text"] for e in record[0]["exchanges"] if (e.get("event") or {}).get("event") == "utterance"]
    assert said[0] == "Yes, go ahead." and all("failed" in r for r in record)
    assert "Yes, go ahead." not in text and "Yes, go ahead." not in report.with_suffix(".json").read_text("utf-8")


def test_the_evaluation_reads_what_the_real_brain_understood(settings_test) -> None:
    """Against the real wiring (fake language model, in process): the evaluator reads the final case as the case
    contract and keeps the engine facts the brain built, so a wrong result can be traced to its slot."""
    from gatorplate.rules import Rules
    from tests.e2e import inprocess
    from tools import simulate_student as sim

    h = inprocess.build(settings_test.model_copy(update={"card_delivery": "screen"}), fixed_clock=False)
    try:
        rules = Rules.from_settings(settings_test)
        report = Path(settings_test.db_path).with_name("eval.md")
        code = sim.main(["--base", "http://testserver", "--only", "p01_maria", "--channels", "web", "--report",
                         str(report)], client=h.client, rules=rules)
    finally:
        inprocess.close(h)
    assert code == 0
    data = json.loads(report.with_suffix(".json").read_text(encoding="utf-8"))
    (row,) = data["per_call"]
    assert row["outcome"]["heard_facts"] is not None and row["persona_vs_heard"] is not None
    assert row["tier"] == "likely" and row["estimate_monthly"] == 306 and row["failed"] is False
    assert data["metrics"]["all"]["no_slot_comparison"] == 0


def test_remote_replay_without_a_secret_still_runs_unsigned_scenarios() -> None:
    """Against a non-local base without the gateway secret, signed phone scenarios are skipped and counted, but the
    unsigned ones (health) still run."""
    app = create_stub_app(card_delivery="code", debug_keys=False)
    with TestClient(app) as client:
        run = runner.Run(kind="examples", mode="remote", llm="server's")
        target = runner.Target(client=client, base="https://example.invalid", secret=None, passcode=None,
                               debug_keys=False, card_delivery="code", remote=True)
        items = runner.build_items("examples", scripts_dir=None, examples_dir=None, only=None, live=False)
        runner.run_items(items, target, run, group="")
    by_id = {r.id: r for r in run.results}
    assert by_id["health"].status == "passed"
    assert by_id["maria_phone"].status == "skipped" and "gateway secret" in by_id["maria_phone"].skip_reason
    assert by_id["sofia_web_es"].status != "skipped", "web scenarios need no gateway secret"


def test_a_port_left_in_time_wait_counts_as_free() -> None:
    """The server closed a connection first, so the port sits in TIME_WAIT with nothing listening: the runner's
    port check must call it free (the server binds with SO_REUSEADDR and would start)."""
    import socket

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port), timeout=1)
    conn, _addr = listener.accept()
    conn.close()  # the server side closes first: its end of the connection waits in TIME_WAIT
    client.close()
    listener.close()
    assert not runner.port_in_use(port)


def test_the_brain_cost_prices_prompt_cache_tokens_apart() -> None:
    """/healthz counts cache reads and writes inside input_tokens and on their own: the evaluation prices reads at
    0.1x and one-hour writes at 2x the input price, the rest at the full price (as tools/bench_llm.py does)."""
    from tools import simulate_student as sim

    before = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
              "cache_creation_input_tokens": 0}
    warm = {"calls": 10, "input_tokens": 50_000, "output_tokens": 850, "cache_read_input_tokens": 42_300,
            "cache_creation_input_tokens": 4_700}
    cost = sim._cost(before, warm, 1.0, 5.0)
    plain = 50_000 - 42_300 - 4_700
    assert abs(cost - (plain + 42_300 * 0.1 + 4_700 * 2.0 + 850 * 5.0) / 1_000_000) < 1e-12
    # an older server without the cache keys: every input token at the full price
    assert sim._cost({"input_tokens": 0, "output_tokens": 0}, {"input_tokens": 1000, "output_tokens": 10}, 1.0, 5.0) \
        == (1000 + 50) / 1_000_000
