"""Adversarial checks on the card's programs endpoints (docs/SPEC.md §6.6; POST /api/card/{token}/answers and
/progress): unknown questions and choices, questions not open for the case, answers on a live case, the per-token
rate limit, "I applied" for a hidden program, GP_PROGRAMS=0, and what the share text and the logs may never hold.
In process over the real wiring; skipped, with that reason, while the wiring is still the foundation stub.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from tests.e2e import inprocess

ROOT = Path(__file__).resolve().parents[2]
JAMAL_CODE = json.loads((ROOT / "data" / "demo_cases" / "jamal_g4.json").read_text(encoding="utf-8"))["code"]


def _harness(settings, **update):
    return inprocess.build(settings.model_copy(update={"card_delivery": "screen", **update}))


@pytest.fixture
def h(settings_test):
    harness = _harness(settings_test)
    harness.login()
    yield harness
    inprocess.close(harness)


def _maria(h, *, send_end: bool = True):
    result = h.play("maria_g1", send_end=send_end)
    return result, h.card_token(result.case_id)


def _seeded_jamal(h) -> tuple[str, str]:
    r = h.client.post("/api/demo/seed")
    assert r.status_code == 200, r.status_code
    items = h.client.get("/api/cases").json()["items"]
    case_id = next(i["id"] for i in items if i["code"] == JAMAL_CODE)
    return case_id, h.card_token(case_id)


def _code(r) -> str:
    return r.json()["error"]["code"]


def test_unknown_question_or_choice_is_422(h) -> None:
    _, token = _maria(h)
    for body in ({"answers": {"favorite_color": "blue"}}, {"answers": {"break_transit": "rocket"}},
                 {"answers": {"break_transit": "weekdays_muni; DROP TABLE cases"}},
                 {"answers": {"break_transit": "none", "tax_dependent": "no", "pge_bill": "in_rent",
                              "favorite_color": "blue"}},
                 {"answers": {}}, {"answer": {"break_transit": "none"}}):
        r = inprocess.answers(h, token, body)
        assert r.status_code == 422 and _code(r) == "invalid_request", body


def test_question_not_open_for_the_case_is_422(h) -> None:
    _, token = _seeded_jamal(h)
    r = inprocess.answers(h, token, {"answers": {"pge_bill": "own_mine"}})  # Jamal is homeless: never asked
    assert r.status_code == 422 and _code(r) == "invalid_request"


def test_answers_while_the_call_is_live_are_409(h) -> None:
    # docs/SPEC.md §6.6: only /answers has the live-call 409 (answers only after the call ended); /progress lists no
    # 409, so it is not asserted here. A refused answer is not stored.
    result, token = _maria(h, send_end=False)
    r = inprocess.answers(h, token, {"answers": {"break_transit": "weekdays_muni"}})
    assert r.status_code == 409 and _code(r) == "conflict"
    h.end(result)
    assert h.detail(result.case_id)["case"].get("program_answers") in ({}, None)
    r = inprocess.answers(h, token, {"answers": {"break_transit": "weekdays_muni"}})
    assert r.status_code == 200 and r.json()["found_display"] == 3830


def test_the_31st_request_in_a_minute_on_one_token_is_429(h) -> None:
    _, token = _maria(h)
    for i in range(30):
        call = inprocess.answers if i % 2 == 0 else inprocess.progress
        body = {"answers": {"break_transit": "two_days"}} if i % 2 == 0 else {"program": "calfresh",
                                                                              "applied": bool(i % 4 == 1)}
        assert call(h, token, body).status_code == 200, i
    r = inprocess.answers(h, token, {"answers": {"break_transit": "two_days"}})
    assert r.status_code == 429 and _code(r) == "rate_limited"


def test_progress_for_a_hidden_or_unknown_program_is_422(h) -> None:
    _, token = _seeded_jamal(h)
    for program in ("care", "favorite_program"):  # PG&E CARE is hidden for a homeless student
        r = inprocess.progress(h, token, {"program": program, "applied": True})
        assert r.status_code == 422 and _code(r) == "invalid_request", program


def test_share_text_and_logs_hold_no_token_code_or_answer(h, caplog, capsys) -> None:
    result, token = _maria(h)
    code = h.detail(result.case_id)["case"]["code"]
    caplog.set_level(logging.DEBUG)
    view = None
    for question, choice in (("break_transit", "weekdays_muni"), ("tax_dependent", "no"), ("pge_bill", "own_roommate")):
        r = inprocess.answers(h, token, {"answers": {question: choice}})
        assert r.status_code == 200
        view = r.json()
    inprocess.progress(h, token, {"program": "calfresh", "applied": True})
    share = view["share_text"]
    for needle in ("/c/", token, code, "weekdays_muni", "own_roommate"):
        assert needle not in share, needle
    out = capsys.readouterr()
    # The test's own HTTP client (httpx/httpcore loggers) logs the URLs it requests; that is this test process, not
    # the server, so its records are left out. Every other record (the app's request log included) is checked.
    records = [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
    assert records, "the app's request log is captured"
    logged = "\n".join([*(r.getMessage() for r in records), *(str(vars(r)) for r in records), out.out, out.err])
    for needle in (token, "weekdays_muni", "own_roommate", share):
        assert needle not in logged, "a log line holds a card token, an answer or the share text"


def test_programs_off_answers_404_on_both_endpoints(settings_test) -> None:
    h = _harness(settings_test, programs=False)
    try:
        h.login()
        result, token = _maria(h)
        card = h.client.get(f"/api/card/{token}", params={"lang": "en"})
        assert card.status_code == 200 and card.json()["unlocked"] is None
        r = inprocess.answers(h, token, {"answers": {"break_transit": "weekdays_muni"}})
        assert r.status_code == 404 and _code(r) == "not_found"
        r = inprocess.progress(h, token, {"program": "calfresh", "applied": True})
        assert r.status_code == 404 and _code(r) == "not_found"
        items = h.client.get("/api/cases").json()["items"]
        assert all(item.get("found_display") is None for item in items)
        assert h.detail(result.case_id).get("programs") is None
        # the call itself is unchanged with the programs part off (the CalFresh estimate stays)
        case = h.detail(result.case_id)["case"]
        assert (case["tier"], case["estimate_monthly"]) == ("likely", 306)
    finally:
        inprocess.close(h)


def test_a_re_answer_replaces_the_older_one(h) -> None:
    _, token = _maria(h)
    first = inprocess.answers(h, token, {"answers": {"break_transit": "weekdays_muni"}})
    assert first.status_code == 200 and first.json()["found_display"] == 3830
    again = inprocess.answers(h, token, {"answers": {"break_transit": "none"}})
    assert again.status_code == 200
    view = again.json()
    assert view["found_display"] == 3670, "the newer answer replaces the older one"
    assert (view["question"] or {}).get("id") == "tax_dependent", "an answered question is not asked again"


def test_list_only_card_shows_no_amounts_and_takes_no_answers(h) -> None:
    # docs/SPEC.md §6.6: coordinator routes (Sofia, parent household) get the list only: no bar, no questions, no
    # share, no dollars; an answer is 422 in list_only mode.
    result = h.play("sofia_g3")
    token = h.card_token(result.case_id)
    for lang in ("es", "en"):
        view = h.client.get(f"/api/card/{token}", params={"lang": lang}).json()["unlocked"]
        assert view["mode"] == "list_only", lang
        assert view["question"] is None and view["share_text"] is None and view["found_display"] is None
        assert view["segments"] == [] and view["claimed_display"] == 0
        assert not any("$" in (p["value_text"] or "") + p["line"] for p in view["programs"]), lang
    r = inprocess.answers(h, token, {"answers": {"break_transit": "none"}}, lang="es")
    assert r.status_code == 422 and _code(r) == "invalid_request"


def test_other_help_card_has_no_programs_part(settings_test) -> None:
    # docs/SPEC.md §5.10 / §6.6: mode none on other_help routes: no unlocked part, no console programs, and both
    # card endpoints answer 404.
    h = inprocess.build(settings_test.model_copy(update={"card_delivery": "code"}))
    try:
        h.login()
        result = h.play("over_limit_g7")
        token = h.card_token(result.case_id)
        assert h.client.get(f"/api/card/{token}", params={"lang": "en"}).json()["unlocked"] is None
        assert h.detail(result.case_id).get("programs") is None
        r = inprocess.answers(h, token, {"answers": {"break_transit": "none"}})
        assert r.status_code == 404 and _code(r) == "not_found"
        r = inprocess.progress(h, token, {"program": "calfresh", "applied": True})
        assert r.status_code == 404 and _code(r) == "not_found"
    finally:
        inprocess.close(h)


def test_a_deleted_card_takes_no_answers(h) -> None:
    result, token = _maria(h)
    assert inprocess.answers(h, token, {"answers": {"tax_dependent": "no"}}).status_code == 200
    assert h.client.delete(f"/api/card/{token}").status_code == 200
    assert h.client.get(f"/api/cases/{result.case_id}").status_code == 404, "the answers go with the case"
    for r in (inprocess.answers(h, token, {"answers": {"tax_dependent": "no"}}),
              inprocess.progress(h, token, {"program": "calfresh", "applied": True})):
        assert r.status_code in (404, 410) and _code(r) in ("not_found", "gone")
