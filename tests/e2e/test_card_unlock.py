"""W4 "CalFresh is the key" end to end, in process (docs/UI_SPEC.md A1 W4; docs/SPEC.md §5.10 and §6.6).

Maria's golden dialogue runs through the real wiring with the fake language model and card delivery `screen`; the
card's `unlocked` part then takes Maria's three taps one at a time ($3,670 → $3,830 → $4,050 → $4,220), the share
text says about $4,200 and carries nothing that identifies the card, CalFresh is marked applied (claimed $3,670), and
the console sees $4,220 in the case detail and in the list, with a `case.updated` event flagged `changed_programs`.
Skipped, with that reason, while the wiring is still the foundation stub.
"""

from __future__ import annotations

import pytest

from tests.e2e import inprocess
from tools import e2e_run as runner

TAPS = [("break_transit", "weekdays_muni", 3830, "tax_dependent"),
        ("tax_dependent", "no", 4050, "pge_bill"),
        ("pge_bill", "own_roommate", 4220, None)]


@pytest.fixture
def harness(settings_test):
    h = inprocess.build(settings_test.model_copy(update={"card_delivery": "screen"}))
    yield h
    inprocess.close(h)


def test_w4_three_taps_share_and_console(harness) -> None:
    h = harness
    h.login()
    result = h.play("maria_g1", send_end=False)
    case_id = result.case_id
    token = h.card_token(case_id)

    card = h.client.get(f"/api/card/{token}", params={"lang": "en"})
    assert card.status_code == 200
    unlocked = card.json()["unlocked"]
    assert unlocked["mode"] == "full"
    assert unlocked["found_display"] == 3670 and unlocked["calfresh_display"] == 3670
    assert unlocked["question"]["id"] == "break_transit"

    # a live case takes no card answers; the script's end block ends the call first
    live = inprocess.answers(h, token, {"answers": {"break_transit": "weekdays_muni"}})
    assert live.status_code == 409 and live.json()["error"]["code"] == "conflict"
    h.end(result)

    labels: list[str] = []
    for question, choice, found, next_question in TAPS:
        r = inprocess.answers(h, token, {"answers": {question: choice}})
        assert r.status_code == 200, (question, r.status_code)
        view = r.json()
        assert view["found_display"] == found, question
        assert (view["question"] or {}).get("id") == next_question, question
        before = [c for q in [unlocked["question"]] if q for c in q["choices"] if c["value"] == choice]
        labels += [c["label"] for c in before if len(c["label"]) > 3]
        unlocked = view

    share = unlocked["share_text"]
    assert share and "$4,200" in share
    assert runner.count_words(share) <= 30, "share text budget (docs/SPEC.md §6.6)"
    detail = h.detail(case_id)
    code = detail["case"]["code"]
    for needle in ("/c/", token, code, "weekdays_muni", "own_roommate", *labels):
        assert needle not in share, needle
    # the parts on screen add up to the headline; nothing counted is a maybe, check, coverage or note line
    assert sum(value for _, value in unlocked["segments"]) == unlocked["found_display"] == 4220
    assert all(p["counted"] == (p["status"] == "likely") for p in unlocked["programs"])
    assert "Each agency decides. Not a promise." in unlocked["footnote"]

    applied = inprocess.progress(h, token, {"program": "calfresh", "applied": True})
    assert applied.status_code == 200
    assert applied.json()["claimed_display"] == 3670

    detail = h.detail(case_id)
    assert detail["programs"]["found_display"] == 4220
    listing = h.client.get("/api/cases").json()["items"]
    summary = next(item for item in listing if item["id"] == case_id)
    assert summary["found_display"] == 4220
    assert any(e["type"] == "case.updated" and e["changed_programs"] for e in h.bus.published)
    # the console's live list line ("Found about $4,220/yr") comes from the event summary
    last = [e for e in h.bus.published if e["type"] == "case.updated" and e["changed_programs"]][-1]
    assert last["found_display"] == 4220

    # a card answer never touches a CalFresh slot or the estimate
    case = detail["case"]
    assert case["estimate_monthly"] == 306 and case["tier"] == "likely"
    assert set(case["program_answers"]) == {"break_transit", "tax_dependent", "pge_bill"}
    assert case["yellow_lines"] == [] or all(y["resolved"] for y in case["yellow_lines"]), "no yellow line (W3 lock)"

    # every card string, in both languages, passes the output guard (no promise of savings, refunds or coverage)
    guard = runner.OutputGuard()
    for lang in ("en", "es"):
        view = h.client.get(f"/api/card/{token}", params={"lang": lang}).json()
        hits = [(path, guard.hits(text)) for path, text in runner._stored_texts(view) if guard.hits(text)]
        assert hits == [], (lang, hits[:3])
        assert view["unlocked"]["found_display"] == 4220 and view["unlocked"]["claimed_display"] == 3670


def test_w4_spanish_view_keeps_the_answers(harness) -> None:
    h = harness
    h.login()
    result = h.play("maria_g1")
    token = h.card_token(result.case_id)
    r = inprocess.answers(h, token, {"answers": {"break_transit": "weekdays_muni"}}, lang="es")
    assert r.status_code == 200 and r.json()["lang"] == "es" and r.json()["found_display"] == 3830
    card = h.client.get(f"/api/card/{token}", params={"lang": "es"}).json()
    assert card["unlocked"]["found_display"] == 3830 and card["unlocked"]["lang"] == "es"
