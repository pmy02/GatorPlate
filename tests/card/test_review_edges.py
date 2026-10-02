"""Edge cases of the card builder: the reporting line from the rules engine's own gross, every content line reachable
and filled in both languages, time zones and daylight-saving changes, idempotency, privacy of the card text, and the
unlocked part held to the route table (docs/SPEC.md §5.7, §6.2-§6.6)."""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from gatorplate.card import CardBuilder, cardview_strings
from gatorplate.contracts.card_api import CardView
from gatorplate.contracts.case import RuleStep, YellowLine
from gatorplate.contracts.rules_io import REASON_CODES

PLACEHOLDER = re.compile(r"\{[a-z_][a-z0-9_]*\}")


def block(view, block_id):
    return next(b for b in view.blocks if b.id == block_id)


def after_text(view) -> str:
    return " ".join(block(view, "after_approval").paragraphs)


# ---------------------------------------------------------------------------------------------- reporting line


def test_reporting_line_uses_the_engines_gross_at_the_estimate(builder, kit) -> None:
    """The rules engine writes its gross (for the same answers and defaults as the estimate) on its `income` step;
    the card's IRT or SAR 7 line follows that figure, not a re-sum of the slots."""
    over = [RuleStep(step="income", result="Monthly income: work $900.00 + other income $900.00 = gross $1,800.00",
                     value="1800.00"),
            RuleStep(step="gross_income_test", result="Gross $1,800.00 ≤ $2,660 (1 person)")]
    view = builder.build(kit.maria(rule_trace=over), lang="en", now=kit.NOW, base_url="")
    assert "Report all your income on your SAR 7" in after_text(view) and "$1,729" not in after_text(view)
    under = [RuleStep(step="income", result="Monthly income: work $0.00 = gross $0.00", value="0.00")]
    view = builder.build(kit.maria(rule_trace=under, slots=dict(kit.MARIA_SLOTS, earned_monthly="2000.00")),
                         lang="es", now=kit.NOW, base_url="")
    assert "pasa de $1,729 al mes" in after_text(view)


def test_reporting_line_falls_back_to_the_slots(builder, kit) -> None:
    trace = [RuleStep(step="gross_income_test", result="Gross $900.00 ≤ $2,660 (1 person)")]  # no value on it
    view = builder.build(kit.maria(rule_trace=trace), lang="en", now=kit.NOW, base_url="")
    assert "over $1,729 a month" in after_text(view)
    no_income = {k: v for k, v in kit.MARIA_SLOTS.items() if not k.endswith("_monthly")}
    view = builder.build(kit.maria(slots=no_income), lang="en", now=kit.NOW, base_url="")
    assert "$1,729" not in after_text(view) and "SAR 7." in after_text(view)  # unknown gross: neither IRT line


# ---------------------------------------------------------------------------------------------- every line


def _variants(kit) -> list:
    base = dict(kit.MARIA_SLOTS)
    grad = {"consent": "true", "level": "grad", "age": "27", "household_food": "alone", "earned_monthly": "1500.00",
            "rent_share": "1200.00", "cash_on_hand": "300.00"}
    abawd = YellowLine(id="y1", kind="policy", code="abawd_possible", reason="Fewer than 8 units.",
                       created_at=kit.CREATED)
    cases = [
        kit.maria(), kit.maria(floor=True), kit.maria(expedited="maybe"), kit.jamal(), kit.boundary(),
        kit.maria(slots=dict(base, units="4"), yellow=[abawd]),
        kit.maria(slots=dict(base, other_cash_monthly="300.00", heat_cool="true", other_utils="two_plus",
                             rent_paid_by_others_to_landlord="200.00", previously_denied="true")),
        kit.maria(slots=dict(base, heat_cool="false", other_utils="phone_only", work_study_monthly="400.00",
                             unearned_monthly="250.00")),
        kit.maria(slots=dict(base, other_utils="none", spouse="true", children_count="1"), estimate=562),
        kit.maria(slots=dict(base, children_count="2", household_food="alone"), estimate=808),
        kit.maria(slots={k: v for k, v in base.items() if k != "cash_on_hand"}, code="Z9Z-1AA"),
        kit.maria(slots=dict(base, earned_monthly="0.00", rent_share="0.00")),
        kit.jamal(slots={**{k.value: s.value for k, s in kit.jamal().slots.items()},
                         "homeless_shelter_cost_monthly": "150.00"}),
        kit.maria(flags=["ta_ra_income_type"], slots=dict(grad, grad_exemption="ta_ra")),
        kit.make_case(reason="coordinator.gig_income", slots=dict(base, gig_monthly="600.00")),
        kit.make_case(reason="coordinator.shared_household", slots=dict(base, household_food="shared")),
        kit.make_case(reason="coordinator.unresolved", slots=dict(base, units="6", half_time="false")),
        kit.make_case(reason="info.already_receiving", tier="likely", slots={"already_receiving": "true"}),
        kit.make_case(reason="info.interview_waiting", slots={"applied_waiting_interview": "true"}),
        kit.make_case(reason=None, slots={}),
    ]
    for exemption in ("campus_job", "work_study", "work20h", "child_under_6", "calworks", "under_half_time"):
        cases.append(kit.maria(slots=dict(grad, grad_exemption=exemption)))
    cases.append(kit.make_case(reason="coordinator.grad_no_exemption", slots=dict(grad, grad_exemption="none")))
    cases += [kit.make_case(reason=code, slots=dict(base)) for code in REASON_CODES
              if code.startswith(("coordinator.", "other_help."))]
    cases.append(kit.sofia())
    return cases


def _pattern(template: str) -> re.Pattern[str]:
    """The rendered form of a template: each placeholder is some text, and a closing period right after the last
    placeholder may be absorbed by a value that ends in its own period ("5 p. m.")."""
    literals = [re.escape(p) for p in PLACEHOLDER.split(template)]
    if len(literals) > 1 and literals[-1] == re.escape("."):
        literals[-1] = r"\.?"
    return re.compile("^" + ".+?".join(literals) + "$", re.DOTALL)


@pytest.mark.parametrize("lang", ["en", "es"])
def test_every_content_line_is_reachable_filled_and_clean(builder, kit, card_content, lang, caplog) -> None:
    """Across the persona variants every block line of card.{lang}.json is shown at least once, with every
    placeholder filled; no line is dropped for a missing value or a guard hit."""
    caplog.set_level(logging.WARNING, logger="gatorplate.card")
    shown: list[str] = []
    for case in _variants(kit):
        view = builder.build(case, lang=lang, now=kit.NOW, base_url="")
        strings = cardview_strings(view)
        for s in strings:
            assert not PLACEHOLDER.search(s), s
            assert builder._guard.hits(s) == [], s
        shown += strings
    assert not [r.getMessage() for r in caplog.records], "a card line was dropped"
    missing = []
    for spec in card_content[lang]["blocks"]:
        templates = [it["text"] for it in spec.get("items", [])]
        templates += [r["answer"] for r in spec.get("rows", [])]
        for template in templates:
            rx = _pattern(template)
            if not any(rx.match(s) for s in shown):
                missing.append(f"{spec['id']}: {template}")
    assert not missing, "\n".join(missing)


# ---------------------------------------------------------------------------------------------- dates


@pytest.mark.parametrize(("now", "filed"), [
    (datetime(2026, 11, 2, 0, 59, tzinfo=UTC), date(2026, 11, 2)),    # Sun Nov 1 16:59 PST (DST just ended) -> Mon
    (datetime(2026, 11, 3, 0, 59, tzinfo=UTC), date(2026, 11, 2)),    # Mon 16:59 PST counts that day
    (datetime(2026, 11, 3, 1, 1, tzinfo=UTC), date(2026, 11, 3)),     # Mon 17:01 PST -> Tue
    (datetime(2027, 3, 15, 23, 59, tzinfo=UTC), date(2027, 3, 15)),   # Mon 16:59 PDT (DST started Mar 14)
    (datetime(2027, 3, 16, 0, 1, tzinfo=UTC), date(2027, 3, 16)),     # Mon 17:01 PDT -> Tue
    (datetime(2026, 10, 10, 6, 59, tzinfo=UTC), date(2026, 10, 12)),  # Fri 23:59 PDT -> Mon
])
def test_filing_day_across_daylight_saving_changes(builder, now, filed) -> None:
    assert builder.filing_date(now) == filed


def test_first_month_moves_into_the_next_month(builder, kit) -> None:
    friday_evening = datetime(2026, 10, 31, 0, 30, tzinfo=UTC)  # Fri Oct 30 17:30 PT -> Mon Nov 2
    view = builder.build(kit.maria(), lang="es", now=friday_evening, base_url="")
    fm = view.first_month
    assert (fm.filed_on, fm.days_counted, fm.amount, fm.month_label) == (date(2026, 11, 2), 29, 306 * 29 // 30,
                                                                         "November")
    assert block(view, "today_action").paragraphs[-1].endswith(
        "cuenta desde el lun 2 de nov, y tu primer mes podría ser de unos $295 para noviembre.")


def test_first_month_is_never_moved_earlier(builder, kit) -> None:
    earlier = datetime(2026, 10, 1, 17, 0, tzinfo=UTC)  # a clock before the stored filing day keeps the stored one
    assert builder.build(kit.maria(), lang="en", now=earlier, base_url="").first_month == kit.maria().first_month


def test_programs_today_is_the_pacific_date_on_new_years_eve(kit) -> None:
    fake = kit.FakePrograms(kit.fixture_unlocked())
    CardBuilder(programs=fake).build(kit.maria(), lang="en", now=datetime(2027, 1, 1, 7, 30, tzinfo=UTC),
                                     base_url="")
    assert fake.calls[-1]["today"] == date(2026, 12, 31)


# ---------------------------------------------------------------------------------------------- idempotency


def test_build_and_calendar_are_idempotent(builder, kit) -> None:
    case = kit.maria()
    one = builder.build(case, lang="es", now=kit.NOW, base_url="")
    two = builder.build(case, lang="es", now=kit.NOW, base_url="")
    assert one == two
    assert CardView.model_validate_json(one.model_dump_json()) == one  # the JSON the API sends round-trips
    assert builder.ics(case, lang="es") == builder.ics(case, lang="es")
    assert builder.status(case) == builder.status(case)
    assert case == kit.maria()  # the builder never changes the case


def test_calendar_lines_fold_and_unfold_in_spanish(builder, kit) -> None:
    text = builder.ics(kit.maria(), lang="es")
    lines = text.split("\r\n")
    assert lines[-1] == "" and all(len(line.encode("utf-8")) <= 75 for line in lines)
    assert any(line.startswith(" ") for line in lines)  # the long Spanish titles are folded
    unfolded = text.replace("\r\n ", "")
    assert "SUMMARY;LANGUAGE=es:CalFresh: últimos días para hacer tu entrevista. ¿No te han llamado? Llama al " \
           "(855) 355-5757" in unfolded
    assert "BEGIN:VALARM" not in text and "RRULE" not in text


# ---------------------------------------------------------------------------------------------- content rules


@pytest.mark.parametrize("lang", ["en", "es"])
def test_every_amount_sits_next_to_the_estimate_wording(builder, kit, lang) -> None:
    for case in (kit.maria(), kit.maria(floor=True), kit.jamal(), kit.boundary()):
        view = builder.build(case, lang=lang, now=kit.NOW, base_url="")
        assert "$" in view.headline
        words = ("estimate", "county decides") if lang == "en" else ("estimación", "condado decide")
        assert all(w in view.subhead for w in words), view.subhead
        first = block(view, "today_action").paragraphs[-1]
        assert first.startswith("Our estimate:" if lang == "en" else "Nuestro cálculo:")


@pytest.mark.parametrize("lang", ["en", "es"])
def test_no_decision_promise_or_reminder_words(builder, kit, lang) -> None:
    banned = re.compile(r"\b(approved|aprobad[oa]s?|eligible|elegible|guarantee|garantiza|reminders?|"
                        r"recordatorios?|text message|mensaje de texto|we will call|te llamaremos)\b|/mo\b",
                        re.IGNORECASE)
    for case in _variants(kit):
        for s in cardview_strings(builder.build(case, lang=lang, now=kit.NOW, base_url="")):
            assert not banned.search(s), s


# ---------------------------------------------------------------------------------------------- privacy


def test_card_never_shows_routing_only_values_quotes_or_the_case_id(builder, kit) -> None:
    secret = kit.slot("asylum pending")
    secret.heard = "my status quote"
    heard = kit.slot("900.00")
    heard.heard = "I make like nine hundred at the library"
    heard.display = "$900/mo (console text)"
    case = kit.maria(slots=dict(kit.MARIA_SLOTS, volunteered_status=secret, earned_monthly=heard))
    for lang in ("en", "es"):
        dumped = builder.build(case, lang=lang, now=kit.NOW, base_url="").model_dump_json()
        for text in ("asylum", "my status quote", "nine hundred at the library", "console text", "/mo", case.id):
            assert text not in dumped, text
    status = builder.status(case).model_dump()
    assert set(status) == {"status", "reviewed", "reviewed_at", "tier", "estimate_monthly"}


# ---------------------------------------------------------------------------------------------- unlocked part


@pytest.mark.parametrize("route", ["other_help.status", "other_help.zero_benefit", None])
def test_no_unlocked_part_on_other_help_or_without_a_result(kit, route) -> None:
    fake = kit.FakePrograms(kit.fixture_unlocked().model_copy(update={"mode": "list_only"}))
    view = CardBuilder(programs=fake).build(kit.make_case(reason=route, slots={"level": "undergrad"}), lang="en",
                                            now=kit.NOW, base_url="")
    assert view.unlocked is None and fake.calls == []


def test_list_only_on_coordinator_and_info_routes(kit) -> None:
    listed = kit.fixture_unlocked().model_copy(update={
        "mode": "list_only", "total_text": None, "found_display": None, "question": None, "share_text": None,
        "segments": [], "chips": []})
    for case in (kit.sofia(lang="en"), kit.make_case(reason="info.interview_waiting", slots={})):
        view = CardBuilder(programs=kit.FakePrograms(listed)).build(case, lang="en", now=kit.NOW, base_url="")
        assert view.unlocked == listed
    full = kit.fixture_unlocked()  # amounts are for the likely route only
    view = CardBuilder(programs=kit.FakePrograms(full)).build(kit.sofia(lang="en"), lang="en", now=kit.NOW,
                                                              base_url="")
    assert view.unlocked is None
    view = CardBuilder(programs=kit.FakePrograms(listed)).build(kit.maria(), lang="en", now=kit.NOW, base_url="")
    assert view.unlocked is None  # the likely route shows the full part


def test_unlocked_in_another_language_is_dropped(kit) -> None:
    view = CardBuilder(programs=kit.FakePrograms(kit.fixture_unlocked("en"))).build(
        kit.maria(), lang="es", now=kit.NOW, base_url="")
    assert view.unlocked is None


@pytest.mark.parametrize("field", ["token", "code", "link"])
def test_share_text_never_carries_the_card_link_token_or_code(kit, field) -> None:
    case = kit.maria()
    leak = {"token": f"see {kit.TOKEN}", "code": f"code {case.code}", "link": "https://example.invalid/c/abc"}[field]
    bad = kit.fixture_unlocked().model_copy(update={"share_text": f"I found about $4,200 a year. {leak}"})
    view = CardBuilder(programs=kit.FakePrograms(bad)).build(case, lang="en", now=kit.NOW, base_url="")
    assert view.unlocked is None


# ---------------------------------------------------------------------------------------------- guard on titles


def test_a_title_that_fails_the_guard_never_reaches_the_card(kit, tmp_path: Path) -> None:
    content = Path(__file__).resolve().parents[2] / "data" / "content"
    for name in ("card.en.json", "card.es.json", "contacts.json", "guards.json"):
        shutil.copy(content / name, tmp_path / name)
    data = json.loads((tmp_path / "card.en.json").read_text(encoding="utf-8"))
    food = next(b for b in data["blocks"] if b["id"] == "food_today")
    food["title"] = "You're approved for food today"
    (tmp_path / "card.en.json").write_text(json.dumps(data), encoding="utf-8")
    view = CardBuilder(tmp_path).build(kit.maria(), lang="en", now=kit.NOW, base_url="")
    assert "food_today" not in [b.id for b in view.blocks]
    assert all("approved" not in s.lower() for s in cardview_strings(view))
