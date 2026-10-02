#!/usr/bin/env python3
"""Validate GatorPlate's data files against the contracts (docs/SPEC.md §5, §5.10, §6, §8).

Checks: the CalFresh rules table parses into RulesTable (no float); the 78 golden cases load into Facts; the demo
cases decode (slot codecs, asked entries, seeded card answers); every utterance line parses; tokens.json and
tokens.css agree; the slot choice lists equal the rules table; the programs table (no float, every value row has
`valid`, every source id exists with a date, `effective` covers 2026-10-01); the programs golden file (count 14 =
its cases); programs.en.json and programs.es.json (same keys and placeholders, es marked for native review); the web
fixtures (every mapped file exists and validates against its contract model). Then it runs
data/content/check_content.py (skip with --no-content).

Run through `make validate-data` (clean environment, PYTHONPATH = repository root); it also runs directly.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import TypeAdapter, ValidationError  # noqa: E402

from gatorplate.contracts.brain_api import BrainReply, ErrorEnvelope, WebSessionResponse  # noqa: E402
from gatorplate.contracts.card_api import CardStatus, CardView  # noqa: E402
from gatorplate.contracts.case import CASE_CODE_PATTERN, AskedQuestion, Case, ProgramAnswer, Slot  # noqa: E402
from gatorplate.contracts.common import CaseStatus, Channel, Lang, SlotSource, SlotState  # noqa: E402
from gatorplate.contracts.console_api import (  # noqa: E402
    CardLookupResponse,
    CaseDetail,
    CaseEvent,
    CaseListResponse,
    ConsoleMeta,
    DemoResetResponse,
    DemoSeedResponse,
    LiveView,
    PublicInfo,
)
from gatorplate.contracts.extraction import ExtractionResult, PendingQuestion  # noqa: E402
from gatorplate.contracts.programs import UnlockedView  # noqa: E402
from gatorplate.contracts.rules_io import Facts, RulesTable  # noqa: E402
from gatorplate.contracts.slots import (  # noqa: E402
    GRAD_EXEMPTION_CHOICES,
    ROUTING_ONLY,
    STATUS_CHOICES,
    SlotName,
    decode_value,
    encode_value,
)
from gatorplate.contracts.summary import summary_line  # noqa: E402

DATA = ROOT / "data"
RULES_TABLE = DATA / "rules" / "ca_fy2027.json"
GOLDEN = DATA / "golden" / "golden_cases.json"
DEMO_CASES = DATA / "demo_cases"
UTTERANCES = DATA / "tests" / "utterances.jsonl"
TOKENS_JSON = DATA / "design" / "tokens.json"
TOKENS_CSS = ROOT / "web" / "shared" / "tokens.css"
PROGRAMS_TABLE = DATA / "rules" / "programs_2026.json"
PROGRAMS_GOLDEN = DATA / "golden" / "programs_golden.json"
PROGRAMS_CONTENT = {"en": DATA / "content" / "programs.en.json", "es": DATA / "content" / "programs.es.json"}
FIXTURES = ROOT / "web" / "fixtures"
CHECK_CONTENT = DATA / "content" / "check_content.py"

PACIFIC_OFFSET = "-07:00"  # PDT, the season of the demo; only used for the reference times below
TEST_NOW = datetime.fromisoformat("2026-10-02T10:00:00" + PACIFIC_OFFSET)
PROGRAMS_GOLDEN_COUNT = 14
GOLDEN_COUNT = 78
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class FloatFound(ValueError):
    pass


def _no_float(text: str) -> Any:
    raise FloatFound(f"float literal {text}")


def load_json(path: Path, *, allow_float: bool = True) -> Any:
    text = path.read_text(encoding="utf-8")
    if allow_float:
        return json.loads(text)
    return json.loads(text, parse_float=_no_float)


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(x) for x in err.get("loc", ()))
    return f"{loc}: {err.get('msg')}"


# ---------------------------------------------------------------------------------------------- CalFresh rules


def check_rules_table() -> list[str]:
    problems: list[str] = []
    try:
        raw = load_json(RULES_TABLE, allow_float=False)
    except FloatFound as exc:
        return [f"{_rel(RULES_TABLE)}: {exc} (money and rates are strings)"]
    try:
        table = RulesTable.model_validate(raw)
    except ValidationError as exc:
        return [f"{_rel(RULES_TABLE)}: does not parse into RulesTable ({_first_error(exc)})"]
    if not (table.effective[0] <= date(2026, 10, 1) <= table.effective[1]):
        problems.append(f"{_rel(RULES_TABLE)}: effective dates do not cover 2026-10-01")
    ids = [s.id for s in table.sources]
    if len(ids) != len(set(ids)):
        problems.append(f"{_rel(RULES_TABLE)}: duplicate source ids")
    for s in table.sources:
        if not s.date:
            problems.append(f"{_rel(RULES_TABLE)}: source {s.id} has no date")
    return problems


def check_slot_choices() -> list[str]:
    raw = load_json(RULES_TABLE)
    problems = []
    if GRAD_EXEMPTION_CHOICES != raw["grad"]["exemptions"] + ["none"]:
        problems.append("SLOT_SPECS grad_exemption choices differ from the rules table's grad.exemptions (+ none)")
    if STATUS_CHOICES != raw["status"]["other_help"] + raw["status"]["coordinator"]:
        problems.append("SLOT_SPECS volunteered_status choices differ from the rules table's status lists")
    return problems


def check_golden() -> list[str]:
    problems: list[str] = []
    try:
        data = load_json(GOLDEN, allow_float=False)
    except FloatFound as exc:
        return [f"{_rel(GOLDEN)}: {exc}"]
    cases = data.get("cases", [])
    if data.get("count") != len(cases) or len(cases) != GOLDEN_COUNT:
        problems.append(f"{_rel(GOLDEN)}: count {data.get('count')} / {len(cases)} cases, expected {GOLDEN_COUNT}")
    seen: set[str] = set()
    for case in cases:
        cid = case.get("id")
        if cid in seen:
            problems.append(f"{_rel(GOLDEN)}: duplicate id {cid}")
        seen.add(cid)
        for key in ("id", "source", "title", "facts", "expected", "hand_calc"):
            if key not in case:
                problems.append(f"{_rel(GOLDEN)} {cid}: missing {key}")
        try:
            Facts.model_validate(case.get("facts", {}))
        except ValidationError as exc:
            problems.append(f"{_rel(GOLDEN)} {cid}: facts do not load into Facts ({_first_error(exc)})")
    return problems


# ---------------------------------------------------------------------------------------------- demo cases


def demo_created_at(demo: dict, now: datetime) -> datetime:
    """created_at = min(now, max(now - minutes_ago, not_before)) (the demo files' `about`)."""
    not_before = datetime.fromisoformat(demo["not_before"])
    return min(now, max(now - timedelta(minutes=demo["minutes_ago"]), not_before))


def demo_program_answers(demo: dict, now: datetime) -> dict[str, ProgramAnswer]:
    """Seeded card answers: source seed, at = created_at + call_seconds, never later than now."""
    created = demo_created_at(demo, now)
    at = min(created + timedelta(seconds=demo["call_seconds"]), now)
    return {q: ProgramAnswer(value=v, at=at, source="seed") for q, v in (demo.get("program_answers") or {}).items()}


def demo_case(demo: dict, now: datetime = TEST_NOW) -> Case:
    """A contract Case built from a demo case file (slots clear, source seed), before the rules run."""
    created = demo_created_at(demo, now)
    ended = min(created + timedelta(seconds=demo["call_seconds"]), now)
    slots = {}
    for name, raw in demo["slots"].items():
        slot = SlotName(name)
        slots[slot] = Slot(value=raw, state=SlotState.clear, source=SlotSource.seed,
                           heard=demo.get("heard", {}).get(name), heard_en=demo.get("heard_en", {}).get(name),
                           turn=demo.get("turns", {}).get(name), confirmed=name in demo.get("confirmed", []),
                           updated_at=ended)
    case = Case(id="c_" + "demo" + "a" * 6, code=demo["code"], created_at=created, updated_at=ended,
                lang=Lang(demo["lang"]), channel=Channel(demo["channel"]), live=False,
                status=CaseStatus(demo["status"]), seeded=bool(demo.get("seed")), persona=demo.get("persona"),
                phase=None, ended_reason=demo.get("ended_reason"), slots=slots,
                asked=[AskedQuestion.model_validate(a) for a in demo.get("asked", [])],
                program_answers=demo_program_answers(demo, now))
    case.summary = summary_line(case)
    return case


def check_demo_cases() -> list[str]:
    problems: list[str] = []
    questions = load_json(PROGRAMS_TABLE)["questions"]
    files = sorted(DEMO_CASES.glob("*.json"))
    if not files:
        return [f"{_rel(DEMO_CASES)}: no demo cases"]
    for path in files:
        where = _rel(path)
        demo = load_json(path)
        if demo.get("id") != path.stem:
            problems.append(f"{where}: id {demo.get('id')!r} differs from the file name")
        if not re.fullmatch(CASE_CODE_PATTERN, demo.get("code", "")):
            problems.append(f"{where}: code {demo.get('code')!r} does not match {CASE_CODE_PATTERN}")
        for name, raw in demo.get("slots", {}).items():
            try:
                slot = SlotName(name)
            except ValueError:
                problems.append(f"{where}: unknown slot {name}")
                continue
            if slot in ROUTING_ONLY:
                problems.append(f"{where}: routing-only slot {name} must never be stored")
                continue
            try:
                if encode_value(slot, decode_value(slot, raw)) != raw:
                    problems.append(f"{where}: slot {name} value {raw!r} is not canonical")
            except (TypeError, ValueError) as exc:
                problems.append(f"{where}: slot {name}: {exc}")
        for mapping in ("heard", "heard_en", "turns"):
            extra = set(demo.get(mapping, {})) - set(demo.get("slots", {}))
            if extra:
                problems.append(f"{where}: {mapping} names slots the file does not set: {sorted(extra)}")
        keys = [a.get("key") for a in demo.get("asked", [])]
        if len(keys) != len(set(keys)):
            problems.append(f"{where}: asked lists a key twice")
        for q, choice in (demo.get("program_answers") or {}).items():
            if q not in questions:
                problems.append(f"{where}: program_answers: unknown question {q}")
            elif choice not in questions[q]["choices"]:
                problems.append(f"{where}: program_answers: {q} has no choice {choice!r}")
        for now in (TEST_NOW, datetime.fromisoformat(demo["not_before"]) + timedelta(seconds=30)):
            try:
                case = demo_case(demo, now)
            except (ValidationError, ValueError, KeyError) as exc:
                problems.append(f"{where}: does not build a Case ({exc})")
                break
            for q, answer in case.program_answers.items():
                if answer.at > now or answer.at < case.created_at:
                    problems.append(f"{where}: seeded answer {q} at {answer.at} is outside created_at..now")
            expected = demo.get("expect", {}).get("summary")
            if expected and case.summary != expected:
                problems.append(f"{where}: summary {case.summary!r}, expected {expected!r}")
    return problems


# ---------------------------------------------------------------------------------------------- utterances


def check_utterances() -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    adapter = TypeAdapter(list[str])
    for lineno, line in enumerate(UTTERANCES.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{_rel(UTTERANCES)}:{lineno}"
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"{where}: not JSON ({exc.msg})")
            continue
        uid = item.get("id")
        if uid in seen:
            problems.append(f"{where}: duplicate id {uid}")
        seen.add(uid)
        if item.get("lang") not in ("en", "es"):
            problems.append(f"{where}: lang must be en or es")
        try:
            PendingQuestion.model_validate(item.get("pending"))
            expect = dict(item.get("expect") or {})
            redactions = expect.pop("redactions", [])
            expect.pop("normalized", None)
            ExtractionResult.model_validate(expect)
            adapter.validate_python(redactions)
            if set(redactions) - {"ssn", "card_number"}:
                problems.append(f"{where}: unknown redaction kind")
        except ValidationError as exc:
            problems.append(f"{where}: {_first_error(exc)}")
    if not seen:
        problems.append(f"{_rel(UTTERANCES)}: no lines")
    return problems


# ---------------------------------------------------------------------------------------------- design tokens


def _check_contrast_module():
    spec = importlib.util.spec_from_file_location("gp_check_contrast", ROOT / "tools" / "check_contrast.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def check_tokens() -> list[str]:
    cc = _check_contrast_module()
    return [f"tokens: {p}" for p in cc.check_css(cc.load_tokens(TOKENS_JSON), TOKENS_CSS)]


# ---------------------------------------------------------------------------------------------- programs


def _iso_date(value: Any) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def check_programs_table() -> list[str]:
    where = _rel(PROGRAMS_TABLE)
    try:
        table = load_json(PROGRAMS_TABLE, allow_float=False)
    except FloatFound as exc:
        return [f"{where}: {exc} (rates are strings, whole dollars integers)"]
    problems: list[str] = []
    sources = {}
    for s in table.get("sources", []):
        if s.get("id") in sources:
            problems.append(f"{where}: duplicate source id {s.get('id')}")
        sources[s.get("id")] = s
        if not s.get("date"):
            problems.append(f"{where}: source {s.get('id')} has no date")
        if not s.get("title"):
            problems.append(f"{where}: source {s.get('id')} has no title")

    def need_source(sid: str, owner: str) -> None:
        if sid not in sources:
            problems.append(f"{where}: {owner} names source {sid!r}, which is not in sources")

    try:
        start, end = (_iso_date(x) for x in table["effective"])
        if start is None or end is None or not (start <= date(2026, 10, 1) <= end):
            problems.append(f"{where}: effective {table['effective']} does not cover 2026-10-01")
    except (KeyError, ValueError, TypeError):
        problems.append(f"{where}: effective must be [from, to] ISO dates")
    for rid, row in table.get("rows", {}).items():
        valid = row.get("valid")
        if not isinstance(valid, list) or len(valid) != 2:
            problems.append(f"{where}: row {rid} has no valid [from, to]")
        else:
            try:
                lo, hi = _iso_date(valid[0]), _iso_date(valid[1])
                if lo is None:
                    problems.append(f"{where}: row {rid} valid needs a start date")
                elif hi is not None and hi < lo:
                    problems.append(f"{where}: row {rid} valid ends before it starts")
            except (ValueError, TypeError):
                problems.append(f"{where}: row {rid} valid dates are not ISO dates")
        if not row.get("sources"):
            problems.append(f"{where}: row {rid} has no sources")
        for sid in row.get("sources", []):
            need_source(sid, f"row {rid}")
    if "source" in table.get("calfresh_key", {}):
        need_source(table["calfresh_key"]["source"], "calfresh_key")
    if "source" in table.get("ask_rule", {}):
        need_source(table["ask_rule"]["source"], "ask_rule")
    statuses = set(table.get("statuses", {}))
    for program in table.get("programs", []):
        pid = program.get("id")
        if not program.get("sources"):
            problems.append(f"{where}: program {pid} has no sources")
        for sid in program.get("sources", []):
            need_source(sid, f"program {pid}")
        for sid in (program.get("calfresh_link") or {}).get("sources", []):
            need_source(sid, f"program {pid} calfresh_link")
        for rule in program.get("status_rules", []):
            if rule.get("status") not in statuses:
                problems.append(f"{where}: program {pid} uses unknown status {rule.get('status')!r}")
        for key in ("row", "fares_row", "breaks_row", "caleitc_row", "federal_row", "yctc_row", "extra_display_row"):
            rid = (program.get("value") or {}).get(key)
            if rid and rid not in table.get("rows", {}):
                problems.append(f"{where}: program {pid} value {key} {rid!r} is not a row")
    for qid, q in table.get("questions", {}).items():
        if not q.get("choices"):
            problems.append(f"{where}: question {qid} has no choices")
    return problems


def check_programs_golden() -> list[str]:
    where = _rel(PROGRAMS_GOLDEN)
    try:
        data = load_json(PROGRAMS_GOLDEN, allow_float=False)
    except FloatFound as exc:
        return [f"{where}: {exc}"]
    problems: list[str] = []
    cases = data.get("cases", [])
    if not (data.get("count") == len(cases) == PROGRAMS_GOLDEN_COUNT):
        problems.append(f"{where}: count {data.get('count')} / {len(cases)} cases, expected {PROGRAMS_GOLDEN_COUNT}")
    seen: set[str] = set()
    for case in cases:
        cid = case.get("id")
        if cid in seen:
            problems.append(f"{where}: duplicate id {cid}")
        seen.add(cid)
        for key in ("facts", "today", "expected", "hand_calc"):
            if key not in case:
                problems.append(f"{where} {cid}: missing {key}")
        try:
            date.fromisoformat(case.get("today", ""))
        except ValueError:
            problems.append(f"{where} {cid}: today is not an ISO date")
    if "demo_sequence" not in data:
        problems.append(f"{where}: missing demo_sequence")
    return problems


def check_programs_content() -> list[str]:
    problems: list[str] = []
    docs = {}
    for lang, path in PROGRAMS_CONTENT.items():
        try:
            docs[lang] = load_json(path, allow_float=False)
        except FloatFound as exc:
            problems.append(f"{_rel(path)}: {exc}")
    if problems:
        return problems
    en, es = docs["en"], docs["es"]
    if en.get("lang") != "en" or es.get("lang") != "es":
        problems.append("programs.*.json: lang fields must be en and es")
    if es.get("native_review") is not True:
        problems.append("programs.es.json: native_review must be true")
    s_en, s_es = en.get("strings", {}), es.get("strings", {})
    for key in sorted(set(s_en) ^ set(s_es)):
        problems.append(f"programs.*.json: key {key} is in only one language")
    for key in sorted(set(s_en) & set(s_es)):
        if set(PLACEHOLDER.findall(s_en[key])) != set(PLACEHOLDER.findall(s_es[key])):
            problems.append(f"programs.*.json: {key} has different placeholders in en and es")
    for section in ("programs", "links", "console_keys"):
        if en.get(section) != es.get(section):
            problems.append(f"programs.*.json: section {section} differs between en and es")
    if set(en.get("sources", {})) != set(es.get("sources", {})):
        problems.append("programs.*.json: sources differ between en and es")
    return problems


# ---------------------------------------------------------------------------------------------- fixtures

# web/fixtures file -> (contract model, "one" | "list" | "events"). A file {"__status": n, "error": {...}} is an
# error answer (ErrorEnvelope); ok.json and empty.json are the plain {"ok": true} and {} bodies.
FIXTURE_MODELS: dict[str, tuple[Any, str]] = {
    "case_maria_reviewed.json": (CaseDetail, "one"),
    "meta.json": (ConsoleMeta, "one"),
    "cases.json": (CaseListResponse, "one"),
    "case_maria.json": (CaseDetail, "one"),
    "case_sofia.json": (CaseDetail, "one"),
    "case_jamal.json": (CaseDetail, "one"),
    "case_grad_ta.json": (CaseDetail, "one"),
    "case_dorm.json": (CaseDetail, "one"),
    "case_boundary.json": (CaseDetail, "one"),
    "case_sofia_confirmed.json": (CaseDetail, "one"),
    "case_sofia_reviewed.json": (CaseDetail, "one"),
    "live_maria.json": (LiveView, "one"),
    "maria_live_events.json": (CaseEvent, "events"),
    "card_maria_en.json": (CardView, "one"),
    "card_maria_es.json": (CardView, "one"),
    "card_status_maria.json": (CardStatus, "list"),
    "unlocked_maria_steps.json": (UnlockedView, "list"),
    "unlocked_maria_steps_es.json": (UnlockedView, "list"),
    "unlocked_maria_progress.json": (UnlockedView, "one"),
    "unlocked_maria_progress_es.json": (UnlockedView, "one"),
    "talk_maria_en.json": (BrainReply, "list"),
    "talk_sofia_es.json": (BrainReply, "list"),
    "web_session_en.json": (WebSessionResponse, "one"),
    "web_session_es.json": (WebSessionResponse, "one"),
    "public_info.json": (PublicInfo, "one"),
    "card_lookup.json": (CardLookupResponse, "one"),
    "demo_seed.json": (DemoSeedResponse, "one"),
    "demo_reset.json": (DemoResetResponse, "one"),
}


def fixture_files_from_index(index: dict) -> list[str]:
    names: list[str] = []
    for value in index.get("routes", index).values():
        if isinstance(value, str):
            names.append(value)
        elif isinstance(value, dict):
            names.extend(v for v in value.values() if isinstance(v, str))
    return names


ROUTE_KEY = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) /[^\s?]*(\?\S+)?$")
PLAIN_FIXTURES = {"ok.json": {"ok": True}, "empty.json": {}}


def check_fixtures() -> list[str]:
    problems: list[str] = []
    index_path = FIXTURES / "index.json"
    if not index_path.exists():
        return [f"{_rel(index_path)}: missing"]
    index = load_json(index_path)
    for key, value in index.get("routes", index).items():
        if not ROUTE_KEY.match(key):
            problems.append(f"{_rel(index_path)}: key {key!r} is not 'METHOD /path'")
        if isinstance(value, dict) and set(value) - {"en", "es"}:
            problems.append(f"{_rel(index_path)}: {key} maps to languages other than en and es")
    for name in fixture_files_from_index(index):
        if not (FIXTURES / name).exists():
            problems.append(f"{_rel(index_path)}: maps to {name}, which does not exist")
    for path in sorted(FIXTURES.glob("*.json")):
        if path.name == "index.json":
            continue
        where = _rel(path)
        data = load_json(path)
        if path.name in PLAIN_FIXTURES:
            if data != PLAIN_FIXTURES[path.name]:
                problems.append(f"{where}: must be {PLAIN_FIXTURES[path.name]}")
            continue
        if isinstance(data, dict) and "__status" in data:
            try:
                envelope = ErrorEnvelope.model_validate({"error": data.get("error")})
                if not isinstance(data["__status"], int) or data["__status"] < 400:
                    raise ValueError("__status must be an HTTP error status")
                from gatorplate.contracts.brain_api import ERROR_STATUS
                if ERROR_STATUS[envelope.error.code][0] != data["__status"]:
                    raise ValueError(f"{envelope.error.code} is not HTTP {data['__status']}")
            except (ValidationError, ValueError) as exc:
                problems.append(f"{where}: not a valid error fixture ({exc})")
            continue
        spec = FIXTURE_MODELS.get(path.name)
        if spec is None:
            problems.append(f"{where}: no contract model is known for this fixture")
            continue
        model, kind = spec
        try:
            if kind == "one":
                model.model_validate(data)
            elif kind == "list":
                if not isinstance(data, list) or not data:
                    raise ValueError("expected a non-empty JSON array")
                for item in data:
                    model.model_validate(item)
            else:
                if not isinstance(data, list) or not data:
                    raise ValueError("expected a non-empty JSON array of {delay_ms, event}")
                for item in data:
                    if not ({"delay_ms", "event"} <= set(item) <= {"delay_ms", "event", "detail"}) or not isinstance(
                            item["delay_ms"], int):
                        raise ValueError("each entry is {delay_ms: int, event: CaseEvent, detail?: CaseDetail}")
                    model.model_validate(item["event"])
                    if "detail" in item:
                        CaseDetail.model_validate(item["detail"])
        except (ValidationError, ValueError) as exc:
            detail = _first_error(exc) if isinstance(exc, ValidationError) else str(exc)
            problems.append(f"{where}: does not validate as {model.__name__} ({detail})")
    return problems


CHECKS = [
    ("rules table", check_rules_table),
    ("slot choices", check_slot_choices),
    ("golden cases", check_golden),
    ("demo cases", check_demo_cases),
    ("utterances", check_utterances),
    ("design tokens", check_tokens),
    ("programs table", check_programs_table),
    ("programs golden", check_programs_golden),
    ("programs content", check_programs_content),
    ("web fixtures", check_fixtures),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-content", action="store_true", help="skip data/content/check_content.py")
    args = ap.parse_args(argv)
    failed = 0
    for label, check in CHECKS:
        problems = check()
        for problem in problems:
            print(f"FAIL {label}: {problem}")
        failed += len(problems)
    if failed:
        print(f"validate_data: {failed} problem{'s' if failed != 1 else ''}")
        return 1
    print(f"validate_data: OK ({len(CHECKS)} checks)", flush=True)
    if not args.no_content:
        return subprocess.call([sys.executable, str(CHECK_CONTENT)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
