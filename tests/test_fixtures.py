"""web/fixtures: every file validates against its contract model and index.json maps every page request to an
existing file; the W4 (card) fixtures hold the required totals."""

from __future__ import annotations

import json
from pathlib import Path

from gatorplate.contracts.card_api import CardView
from gatorplate.contracts.console_api import CaseDetail, CaseListResponse, ConsoleMeta
from gatorplate.contracts.programs import UnlockedView
from tools import validate_data as vd

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "web" / "fixtures"


def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def routes() -> dict:
    return load("index.json")["routes"]


def test_all_fixtures_validate() -> None:
    assert vd.check_fixtures() == []


def test_every_fixture_file_is_known() -> None:
    known = set(vd.FIXTURE_MODELS) | set(vd.PLAIN_FIXTURES) | {"index.json"}
    for path in FIX.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert path.name in known or (isinstance(data, dict) and "__status" in data), path.name


def test_index_maps_card_program_endpoints() -> None:
    r = routes()
    assert r["POST /api/card/{token}/answers"] == {"en": "unlocked_maria_steps.json",
                                                   "es": "unlocked_maria_steps_es.json"}
    assert r["POST /api/card/{token}/progress"] == {"en": "unlocked_maria_progress.json",
                                                    "es": "unlocked_maria_progress_es.json"}
    assert r["GET /api/card/{token}?lang=es"] == "card_maria_es.json"
    assert r["GET /api/cases"] == "cases.json" and r["GET /api/meta"] == "meta.json"
    for page_request in ("POST /api/web/sessions", "POST /v1/calls/{call_id}/start", "POST /v1/calls/{call_id}/turn",
                         "POST /v1/calls/{call_id}/end", "GET /api/public/info", "POST /api/card/lookup",
                         "GET /api/card/{token}/status", "POST /api/demo/seed", "POST /api/demo/reset"):
        assert page_request in r, page_request


def test_card_maria_unlocked() -> None:
    for lang in ("en", "es"):
        card = CardView.model_validate(load(f"card_maria_{lang}.json"))
        u = card.unlocked
        assert u is not None and u.mode == "full" and u.lang == lang
        assert (u.found_display, u.claimed_display, u.calfresh_display) == (3670, 0, 3670)
        assert u.question is not None and u.question.id == "break_transit"
        assert (u.question.index, u.question.total) == (1, 3)
        assert u.segments == [("calfresh", 3670)]
        assert [p.id for p in u.programs] == ["calfresh", "medi_cal", "clipper_start", "lifeline", "care",
                                              "tax_credits"]
        assert u.programs[0].apply_url == "#today_action"
        assert "{i}" in u.labels["ui.question_count"] and "{n}" in u.labels["ui.question_count"]
        assert card.estimate_monthly == 306 and [b.id for b in card.blocks][0] == "today_action"
    assert "Question {i} of {n}" == load("card_maria_en.json")["unlocked"]["labels"]["ui.question_count"]


def test_unlocked_steps_and_progress() -> None:
    for suffix in ("", "_es"):
        steps = [UnlockedView.model_validate(x) for x in load(f"unlocked_maria_steps{suffix}.json")]
        assert [s.found_display for s in steps] == [3830, 4050, 4220]
        assert [(s.question.index, s.question.total) if s.question else None for s in steps] == [(2, 3), (3, 3), None]
        assert [s.question.id if s.question else None for s in steps] == ["tax_dependent", "pge_bill", None]
        progress = UnlockedView.model_validate(load(f"unlocked_maria_progress{suffix}.json"))
        assert progress.claimed_display == 3670 and progress.found_display == 4220
        assert next(p for p in progress.programs if p.id == "calfresh").applied is True
        for view in steps + [progress]:
            share = view.share_text or ""
            assert "/c/" not in share and "K7Q-2FM" not in share and "fixture" not in share.lower()
    assert "$4,200" in UnlockedView.model_validate(load("unlocked_maria_progress.json")).share_text


def test_console_programs_fixtures() -> None:
    maria = CaseDetail.model_validate(load("case_maria.json"))
    jamal = CaseDetail.model_validate(load("case_jamal.json"))
    sofia = CaseDetail.model_validate(load("case_sofia.json"))
    assert maria.programs is not None and maria.programs.found_display == 3670 and maria.summary.found_display == 3670
    assert jamal.programs is not None and jamal.programs.found_display == 3980 and jamal.summary.found_display == 3980
    assert sofia.programs is not None and sofia.programs.mode == "list_only" and sofia.summary.found_display is None
    assert {k: a.source for k, a in jamal.case.program_answers.items()} == {"tax_dependent": "seed",
                                                                           "break_transit": "seed"}
    listing = CaseListResponse.model_validate(load("cases.json"))
    shown = {item.code: item.found_display for item in listing.items}
    assert shown["K7Q-2FM"] == 3670 and shown["P2X-6TC"] == 3980
    meta = ConsoleMeta.model_validate(load("meta.json"))
    assert meta.programs is not None and meta.programs.questions == ["break_transit", "tax_dependent", "pge_bill"]
    assert meta.programs.names["calfresh"] == "CalFresh"
    assert "care.utility_conflict" in meta.programs.console_texts
    assert meta.slot_specs["roommates_count"].label == "Number of roommates"


def test_live_replay_shape() -> None:
    entries = load("maria_live_events.json")
    types = [e["event"]["type"] for e in entries]
    assert types[0] == "case.created" and "live.ended" in types and types[-1] in ("case.updated", "live.ended")
    reasons = [e["event"]["asked_reason"] for e in entries if e["event"].get("asked_reason")]
    assert "could change the estimate by $151: $155 or $306" in reasons
    # every case event carries the detail the console shows at that moment; the last one is the ended call
    case_events = [e for e in entries if e["event"]["type"] in ("case.created", "case.updated")]
    assert all("detail" in e for e in case_events)
    last = CaseDetail.model_validate(case_events[-1]["detail"])
    assert last.case.live is False and last.case.estimate_monthly == 306
    assert all(e["delay_ms"] > 0 for e in entries)


def test_talk_replies() -> None:
    maria = load("talk_maria_en.json")
    sofia = load("talk_sofia_es.json")
    assert maria[0]["interruptible"] is False and maria[-1]["end"] is True
    assert maria[-1]["card_url"] and all(isinstance(r["display"], str) for r in maria)
    assert sofia[0]["lang"] == "es" and sofia[-1]["end"] is True
