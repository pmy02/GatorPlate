"""The platform with the real rules engine and card builder (and the real programs engine once it answers): every
demo case seeds or injects to the values its file's `expect` states, the console shows the W1 data for Maria, and
the card endpoints work end to end. Each part skips while the module it needs is still a stub."""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from gatorplate.api.app import create_app
from gatorplate.config import REPO_ROOT
from gatorplate.ids import FixedIds
from tests.api.fakes import FakePrograms, make_deps, make_settings

DEMO = REPO_ROOT / "data" / "demo_cases"


def real_rules(settings):
    from gatorplate.rules import Rules

    rules = Rules(settings.rules_table_path, tz=settings.tz)
    try:
        rules.meta()
        rules.valid_on(date(2026, 10, 2))
    except NotImplementedError:
        pytest.skip("the rules engine is not built yet")
    return rules


def real_programs(settings):
    from gatorplate.programs import Programs

    programs = Programs.from_settings(settings)
    try:
        programs.meta()
    except NotImplementedError:
        return None
    return programs


def real_cards(settings, programs):
    from gatorplate.card import CardBuilder

    return CardBuilder(settings.content_dir, programs, guards_path=settings.guards_path, tz=settings.tz)


@pytest.fixture
def real(clean_gp_env, tmp_db, fixed_clock):
    settings = make_settings(tmp_db)
    rules = real_rules(settings)
    programs = real_programs(settings)
    deps = make_deps(settings, clock=fixed_clock, ids=FixedIds(), rules=rules, programs=programs or FakePrograms())
    try:
        deps = type(deps)(**{**deps.__dict__, "cards": real_cards(settings, deps.programs)})
    except NotImplementedError:
        pytest.skip("the card builder is not built yet")
    app = create_app(deps)
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/console/login", json={"passcode": "dev"}).status_code == 200
    yield client, deps, programs is not None
    client.close()


def demo_file(name: str) -> dict:
    return json.loads((DEMO / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(p.stem for p in DEMO.glob("*.json")))
def test_demo_cases_match_their_expect(real, name) -> None:
    client, deps, _ = real
    expect = demo_file(name)["expect"]
    detail = client.post("/api/demo/inject", json={"id": name}).json()
    case, summary = detail["case"], detail["summary"]
    assert (case["tier"], case["reason_code"], case["estimate_monthly"]) == (
        expect["tier"], expect["reason_code"], expect["estimate_monthly"])
    assert summary["yellow_open"] == expect["yellow_open"]
    for key in ("estimate_is_floor", "expedited_possible"):
        if key in expect:
            assert case[key] == expect[key], key
    if "estimate_range" in expect:
        assert case["estimate_range"] == expect["estimate_range"]
    if "yellow_total" in expect:
        assert summary["yellow_total"] == expect["yellow_total"]
    if "can_review" in expect:
        assert detail["can_review"] is expect["can_review"]
    if "summary" in expect:
        assert case["summary"] == expect["summary"]
    for line in expect.get("yellow", []):
        found = [y for y in case["yellow_lines"] if y["code"] == line["code"]]
        assert found and all(found[0][k] == v for k, v in line.items()), line
    for skipped in expect.get("skipped", []):
        assert {"slot": skipped["slot"], "reason": skipped["reason"]} in [
            {"slot": s["slot"], "reason": s["reason"]} for s in case["skipped"]], skipped
    asked = [a["key"] for a in case["asked"]]
    assert len(asked) == len(set(asked))
    card = client.get(detail["card_url"].replace("/c/", "/api/card/"))
    assert card.status_code == 200 and card.json()["code"] == case["code"]
    if case["first_month"]:
        ics = client.get(detail["card_url"].replace("/c/", "/api/card/") + "/reminders.ics")
        assert ics.status_code == 200 and ics.text.count("BEGIN:VEVENT") == 3


def test_maria_w1_data_and_seeded_list(real) -> None:
    client, _, programs_real = real
    assert client.post("/api/demo/seed").json() == {"seeded": 5, "replaced": 0}
    maria = client.post("/api/demo/inject", json={"id": "maria_g1"}).json()["case"]
    ranges = {p["turn"]: (p["lo"], p["hi"]) for p in maria["timeline"]}
    assert ranges[6] == (155, 306) and ranges[7] == (306, 306)
    flip = next(a for a in maria["asked"] if a["key"] == "flip.rent_paid_by_others")
    assert flip["reason"] == "could change the estimate by $151: $155 or $306"
    details = {s["slot"]: s["detail"] for s in maria["skipped"]}
    assert details["heat_cool"] == "Not asked — heating or cooling bill, same estimate either way"
    rows = {i["code"]: i for i in client.get("/api/cases").json()["items"]}
    assert rows["R8W-3ND"]["yellow_open"] == 1 and rows["P2X-6TC"]["asked_count"] == 5
    if programs_real:
        assert rows["P2X-6TC"]["found_display"] == 3980 and rows["K7Q-2FM"]["found_display"] == 3670
    assert client.post("/api/demo/reset").json() == {"deleted": 1, "kept": 5}
    client.post("/api/demo/seed")
    rows = {i["code"]: i for i in client.get("/api/cases").json()["items"]}
    assert set(rows) == {"R8W-3ND", "P2X-6TC", "H5V-9KB", "Z4M-7QE", "D7L-8RW"} and rows["R8W-3ND"]["yellow_open"] == 1
    if programs_real:
        assert rows["P2X-6TC"]["found_display"] == 3980  # the seeded card answers come back with the sample


def test_maria_card_taps_with_the_real_engine(real) -> None:
    client, _, programs_real = real
    if not programs_real:
        pytest.skip("the programs engine is not built yet")
    detail = client.post("/api/demo/inject", json={"id": "maria_g1"}).json()
    token = detail["card_url"].removeprefix("/c/")
    totals = []
    for question, choice in (("break_transit", "weekdays_muni"), ("tax_dependent", "no"), ("pge_bill", "own_roommate")):
        r = client.post(f"/api/card/{token}/answers?lang=en", json={"answers": {question: choice}})
        assert r.status_code == 200, r.text
        totals.append(r.json()["found_display"])
    assert totals == [3830, 4050, 4220]
    progress = client.post(f"/api/card/{token}/progress", json={"program": "calfresh", "applied": True}).json()
    assert progress["claimed_display"] == 3670


def test_switched_off_programs_engine(make_client) -> None:
    """GP_PROGRAMS=0 with the real engine built disabled: every programs surface is null and both card programs
    endpoints answer 404."""
    from gatorplate.programs import Programs

    h = make_client(programs=False, programs_port=Programs(enabled=False))
    c = h.login()
    case = h.add_case()
    token = case.card.token
    assert c.get("/api/meta").json()["programs"] is None
    assert c.get(f"/api/cases/{case.id}").json()["programs"] is None
    assert c.get("/api/cases").json()["items"][0]["found_display"] is None
    assert h.client.get(f"/api/card/{token}").json()["unlocked"] is None
    for path, body in ((f"/api/card/{token}/answers", {"answers": {"tax_dependent": "no"}}),
                       (f"/api/card/{token}/progress", {"program": "calfresh", "applied": True})):
        r = h.client.post(path, json=body)
        assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")
    assert h.client.get("/healthz").json()["programs"] == {"enabled": False, "table_id": None, "valid_today": False}
