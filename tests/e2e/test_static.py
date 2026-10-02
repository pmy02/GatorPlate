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
                only: list[str] | None = None, concurrency: int = 1) -> runner.Run:
    app = create_stub_app(card_delivery=card_delivery, debug_keys=debug_keys)
    with TestClient(app) as client:
        run = runner.Run(kind="scripts", mode="in-process", llm="fake")
        target = runner.Target(client=client, base="http://testserver", secret=runner.DEV_GATEWAY_SECRET,
                               passcode="dev", debug_keys=debug_keys, card_delivery=card_delivery)
        items = runner.build_items("scripts", scripts_dir=dirs, examples_dir=None, only=only, live=False)
        runner.run_items(items, target, run, group=card_delivery, concurrency=concurrency)
    return run


@pytest.mark.parametrize("mode", runner.CARD_MODES)
def test_every_script_plays_against_the_stub(mode: str) -> None:
    run = _in_process(mode)
    failed = {r.id: r.failures[:3] for r in run.results if r.status == "failed"}
    assert failed == {}
    skipped = {r.id: r.skip_reason for r in run.results if r.status == "skipped"}
    for r in run.results:
        script = next(s for p, s in runner.load_scripts(runner.SCRIPTS_DIRS) if s.id == r.id)
        other_mode_phone = script.channel == "phone" and script.card_mode != mode
        assert (r.id in skipped) == other_mode_phone, r.id
        if other_mode_phone:
            assert skipped[r.id].startswith("env:")
    assert run.executed and all(r.keys_asserted and r.console_checked for r in run.executed)


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


def test_metrics_count_silent_errors_only_without_a_yellow_line() -> None:
    from tools import simulate_student as sim

    truth = {"tier": "likely", "reason_code": "likely", "monthly": 306, "expedited": "no"}
    good = sim.Outcome("a", "en", "web", truth, case={"tier": "likely", "estimate_monthly": 306,
                                                      "expedited_possible": "no", "yellow_lines": [], "asked": [],
                                                      "turn_count": 9})
    flagged = sim.Outcome("b", "es", "web", truth, case={"tier": "coordinator", "estimate_monthly": None,
                                                         "yellow_lines": [{"code": "x", "resolved": None}]})
    silent = sim.Outcome("c", "en", "phone", truth, case={"tier": "likely", "estimate_monthly": 155,
                                                          "yellow_lines": [{"code": "x", "resolved": "confirm"}]})
    m = sim.metrics([good, flagged, silent], brain_cost_usd=0.03)
    assert m["silent_errors"] == [1, 3] and m["tier_agreement"] == [2, 3]
    assert m["amount_exact"] == [1, 2] and m["amount_mae"] == 75.5
    assert m["expedited_agreement"] == [1, 3] and m["brain_llm_cost_per_call_usd"] == 0.01


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
