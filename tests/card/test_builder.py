"""CardBuilder: the golden personas, the one block table (docs/SPEC.md §6.2), conditions, placeholders, the IRT and
SAR 7 lines, the filing-date estimate and the card status."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from gatorplate.card import cardview_strings
from gatorplate.contracts.card_api import BLOCK_ORDER
from gatorplate.contracts.case import Tracking, YellowLine
from gatorplate.contracts.errors import NotFound
from gatorplate.contracts.rules_io import REASON_CODES

COORD_CODES = [r for r in REASON_CODES if r.startswith("coordinator.") and r != "coordinator.parent_household"]
OTHER_CODES = [r for r in REASON_CODES if r.startswith("other_help.")]
LIKELY_BLOCKS = ["today_action", "why", "answer_sheet", "documents", "interview", "after_approval", "food_today",
                 "contact"]
COORD_BLOCKS = ["today_action", "why", "answer_sheet", "documents", "interview", "food_today", "contact"]
SHORT_BLOCKS = ["why", "food_today", "contact"]
# docs/SPEC.md §6.2: tone and starting state per block
STYLE = {"today_action": ("accent", False), "expedited": ("accent", False), "why": ("default", False),
         "answer_sheet": ("default", False), "documents": ("default", True), "interview": ("default", True),
         "after_approval": ("default", True), "food_today": ("muted", False), "contact": ("default", False)}
UNDERGRAD = {"consent": "true", "level": "undergrad", "units": "12", "age": "21", "household_food": "alone",
             "earned_monthly": "1200.00", "rent_share": "1000.00"}


def ids(view):
    return [b.id for b in view.blocks]


def block(view, block_id):
    return next(b for b in view.blocks if b.id == block_id)


def text_of(view):
    return " ".join(cardview_strings(view))


def route_case(kit, route: str, lang: str = "en"):
    """A case for one row of the route table (docs/SPEC.md §6.2)."""
    if route == "likely":
        return kit.maria(lang=lang)
    if route == "likely_expedited_yes":
        return kit.jamal(lang=lang)
    if route == "likely_expedited_maybe":
        return kit.maria(expedited="maybe", lang=lang)
    if route == "incomplete":
        return kit.make_case(reason=None, slots={"level": "undergrad", "half_time": "true"}, lang=lang)
    if route == "info.already_receiving":
        return kit.make_case(reason=route, tier="likely", lang=lang,
                             slots={"level": "undergrad", "already_receiving": "true"})
    if route == "info.interview_waiting":
        return kit.make_case(reason=route, lang=lang, slots={"level": "undergrad", "applied_waiting_interview": "true"})
    return kit.make_case(reason=route, lang=lang, slots=dict(UNDERGRAD))


ROUTE_TABLE = (
    [("likely", LIKELY_BLOCKS), ("likely_expedited_yes", BLOCK_ORDER),
     ("likely_expedited_maybe", ["today_action", "expedited", *LIKELY_BLOCKS[1:]])]
    + [(code, COORD_BLOCKS) for code in COORD_CODES]
    + [("coordinator.parent_household", SHORT_BLOCKS)]
    + [(code, SHORT_BLOCKS) for code in OTHER_CODES]
    + [("info.already_receiving", ["why", "after_approval", "contact"]),
       ("info.interview_waiting", ["why", "interview", "contact"]),
       ("incomplete", ["food_today", "contact"])]
)
ALL_ROUTES = [r for r, _ in ROUTE_TABLE]


# ---------------------------------------------------------------------------------------------- golden personas

def test_g1_maria_en(builder, kit) -> None:
    view = builder.build(kit.maria(), lang="en", now=kit.NOW, base_url="http://127.0.0.1:8000")
    assert ids(view) == LIKELY_BLOCKS
    assert view.headline == "You may get about $306 a month for groceries."
    assert view.subhead == "This is an estimate. The county decides."
    assert view.estimate_monthly == 306 and view.expedited == "no" and view.tier == "likely"
    today = block(view, "today_action").paragraphs
    assert today[-1] == ("Our estimate: if you send it now, it counts from Fri, Oct 2, and your first month may be "
                         "about $296 for October.")
    after = block(view, "after_approval").paragraphs
    assert "If your household's total income goes over $1,729 a month, tell the county within 10 days." in after
    assert not any("Report all your income on your SAR 7" in p for p in after)
    why = block(view, "why")
    assert why.title == "Why you may qualify"
    assert any("8 or more units" in p for p in why.paragraphs)  # half-time derived from 12 units
    assert any("highest amount for your household size" in p for p in why.paragraphs)
    answers = {(r.screen, r.question): r.answer for r in block(view, "answer_sheet").rows}
    assert answers[("Job and Income", "Jobs and pay")] == "My job pays about $900 a month before taxes."
    assert answers[("Expenses", "Rent")] == "My share of the rent: $1,100 a month."
    assert answers[("Assets", "Money in cash and in the bank")] == "About $1,000."
    assert answers[("People", "Who do you buy and cook food with?")].startswith("Just me. The people I live with")
    assert block(view, "contact").paragraphs[2] == "Your case code: K7Q-2FM. Share it so they can find your answers."
    sources = {s.id: s for s in view.sources}
    assert sources["ACL-15-42"].date == "2015-04-15"
    assert "MPP-63-301" not in sources  # only the sources of the blocks shown
    assert view.rules_label == "CalFresh FY2027 (Oct 1, 2026 – Sep 30, 2027)"


def test_g1_maria_es(builder, kit) -> None:
    view = builder.build(kit.maria(), lang="es", now=kit.NOW, base_url="")
    assert view.lang == "es" and ids(view) == LIKELY_BLOCKS
    assert view.headline == "Podrías recibir hasta $306 al mes para comprar comida."
    assert "Si el ingreso total de tu hogar pasa de $1,729 al mes, avísale al condado en 10 días." in \
        block(view, "after_approval").paragraphs
    assert block(view, "today_action").paragraphs[-1].endswith(
        "cuenta desde el vie 2 de oct, y tu primer mes podría ser de unos $296 para octubre.")
    assert block(view, "why").title == "Por qué podrías calificar"
    assert view.rules_label == "CalFresh año fiscal 2027 (1 oct 2026 – 30 sep 2027)"
    # BenefitsCal screen names stay in English in both languages
    assert {r.screen for r in block(view, "answer_sheet").rows} >= {"Your Information", "Job and Income", "Expenses"}


def test_g3_sofia_es_parent_household(builder, kit) -> None:
    view = builder.build(kit.sofia(), lang="es", now=kit.NOW, base_url="")
    assert ids(view) == SHORT_BLOCKS  # no today_action: talk to the coordinator first
    assert view.estimate_monthly is None and view.first_month is None and view.expedited is None
    assert view.headline == "Un detalle necesita que lo revise una persona."
    assert "$" not in view.headline + view.subhead
    why = block(view, "why")
    assert why.title == "Por qué una persona tiene que revisar"
    assert any("menos de 22" in p for p in why.paragraphs)
    assert view.reminders_url is None
    assert view.code == "S4F-9Q2"


def test_g4_jamal_en_expedited(builder, kit) -> None:
    view = builder.build(kit.jamal(), lang="en", now=kit.NOW, base_url="")
    assert ids(view) == BLOCK_ORDER
    exp = block(view, "expedited")
    assert exp.title == "Help within 3 days" and exp.tone == "accent"
    assert exp.paragraphs[0] == "You may get CalFresh within 3 days. The county checks this when you apply."
    assert "No proof of address is needed if you don't have a fixed home." in block(view, "documents").paragraphs
    assert any("$1,729" in p for p in block(view, "after_approval").paragraphs)  # no income: under the 130% line
    assert any("little or no income" in p for p in block(view, "why").paragraphs)
    housing = [r.answer for r in block(view, "answer_sheet").rows if r.question == "Housing"]
    assert housing == ["I don't have a fixed home, and I don't pay to stay where I sleep."]


def test_g5_other_help_status(builder, kit) -> None:
    case = kit.make_case(reason="other_help.status", slots={"level": "undergrad", "age": "21"})
    view = builder.build(case, lang="en", now=kit.NOW, base_url="")
    assert ids(view) == SHORT_BLOCKS
    assert view.headline == "Food help is still here for you."
    assert view.subhead == "CalFresh rules for your situation are complicated, so we won't guess."
    assert block(view, "why").title == "Why we won't guess"
    assert view.estimate_monthly is None and "$" not in view.headline


def test_g7_over_gross_limit(builder, kit) -> None:
    case = kit.make_case(reason="other_help.over_gross_limit",
                         slots={"level": "undergrad", "age": "21", "earned_monthly": "3500.00"})
    view = builder.build(case, lang="en", now=kit.NOW, base_url="")
    assert ids(view) == SHORT_BLOCKS
    assert any("over the CalFresh limit" in p for p in block(view, "why").paragraphs)
    assert view.estimate_monthly is None and view.first_month is None


def test_g8_minimum_sar7_line(builder, kit) -> None:
    view = builder.build(kit.boundary(), lang="en", now=kit.NOW, base_url="")
    after = block(view, "after_approval").paragraphs
    assert ("You don't need to report income changes between reports. Report all your income on your SAR 7."
            in after)
    assert "$1,729" not in text_of(view)
    assert view.headline == "You may get about $25 a month for groceries."
    assert not any("highest amount" in p for p in block(view, "why").paragraphs)
    assert block(view, "today_action").paragraphs[-1].endswith("about $24 for October.")
    es = builder.build(kit.boundary(), lang="es", now=kit.NOW, base_url="")
    assert "Reporta todo tu ingreso en tu SAR 7." in " ".join(block(es, "after_approval").paragraphs)


# ---------------------------------------------------------------------------------------------- the block table

@pytest.mark.parametrize(("route", "expected"), ROUTE_TABLE, ids=[r for r, _ in ROUTE_TABLE])
@pytest.mark.parametrize("lang", ["en", "es"])
def test_route_table(builder, kit, route, expected, lang) -> None:
    view = builder.build(route_case(kit, route, lang), lang=lang, now=kit.NOW, base_url="")
    assert ids(view) == expected
    assert ids(view) == [b for b in BLOCK_ORDER if b in ids(view)]  # one order, never reordered
    for b in view.blocks:
        assert (b.tone, b.collapsed) == STYLE[b.id]
        assert b.paragraphs or b.rows


@pytest.mark.parametrize("route", [r for r in ALL_ROUTES if not r.startswith("likely")])
def test_no_amount_off_the_likely_route(builder, kit, route) -> None:
    case = route_case(kit, route)
    case = case.model_copy(update={"estimate_monthly": 306, "first_month": kit.first_month(296)})
    view = builder.build(case, lang="en", now=kit.NOW, base_url="")
    assert view.estimate_monthly is None and view.first_month is None and view.expedited is None
    assert "$" not in view.headline + view.subhead
    assert "$306" not in text_of(view) and "$296" not in text_of(view)
    assert view.status.estimate_monthly is None


def test_hero_keys(builder, kit) -> None:
    floor = builder.build(kit.maria(floor=True), lang="en", now=kit.NOW, base_url="")
    assert floor.headline == "You may get about $306 a month or more for groceries." and floor.estimate_is_floor
    info = builder.build(route_case(kit, "info.already_receiving"), lang="en", now=kit.NOW, base_url="")
    assert info.headline == "You already get CalFresh." and block(info, "why").title == "What to keep up with"
    waiting = builder.build(route_case(kit, "info.interview_waiting"), lang="en", now=kit.NOW, base_url="")
    assert waiting.headline == "Get ready for your phone interview."
    assert block(waiting, "why").title == "What comes next"
    incomplete = builder.build(route_case(kit, "incomplete"), lang="en", now=kit.NOW, base_url="")
    assert incomplete.headline == "We didn't finish your check." and incomplete.tier is None
    coord = builder.build(route_case(kit, "coordinator.shared_household"), lang="en", now=kit.NOW, base_url="")
    assert coord.headline == "One detail needs a person to check."
    assert block(coord, "why").title == "Why a person needs to check"


# ---------------------------------------------------------------------------------------------- guard and text

@pytest.mark.parametrize("route", ALL_ROUTES)
@pytest.mark.parametrize("lang", ["en", "es"])
def test_every_string_passes_the_guard(builder, kit, route, lang) -> None:
    view = builder.build(route_case(kit, route, lang), lang=lang, now=kit.NOW, base_url="")
    strings = cardview_strings(view)
    assert strings
    for s in strings:
        assert builder._guard.hits(s) == [], s
        assert "{" not in s and "}" not in s, s
        assert "approved" not in s.lower() and "aprobad" not in s.lower(), s


def test_flags_and_yellow_lines(builder, kit) -> None:
    abawd = YellowLine(id="y1", kind="policy", code="abawd_possible", reason="Fewer than 8 units.",
                       created_at=kit.CREATED)
    slots = dict(kit.MARIA_SLOTS, units="4")
    view = builder.build(kit.maria(slots=slots, yellow=[abawd]), lang="en", now=kit.NOW, base_url="")
    why = block(view, "why").paragraphs
    assert any(p.startswith("A work rule may apply") for p in why)
    assert "With fewer than 8 units, CalFresh's student rule doesn't apply to you." in why
    edited = abawd.model_copy(update={"resolved": "edit"})
    view = builder.build(kit.maria(slots=slots, yellow=[edited]), lang="en", now=kit.NOW, base_url="")
    assert not any(p.startswith("A work rule may apply") for p in block(view, "why").paragraphs)
    ta = builder.build(kit.maria(flags=["ta_ra_income_type"]), lang="en", now=kit.NOW, base_url="")
    assert any(p.startswith("TA or RA pay counts as income") for p in block(ta, "why").paragraphs)


def test_answered_versus_default(builder, kit) -> None:
    defaults = dict(kit.MARIA_SLOTS, heat_cool=kit.slot("false", source="default", state="assumed"),
                    other_utils=kit.slot("none", source="default", state="assumed"))
    rows = {r.question: r.answer for r in block(builder.build(kit.maria(slots=defaults), lang="en", now=kit.NOW,
                                                              base_url=""), "answer_sheet").rows}
    assert rows["Heating or cooling bill apart from rent"] == "Answer yes if you pay one."
    assert rows["Other bills (water, trash, electric, phone)"] == "List the ones you pay yourself. Internet doesn't count."
    answered = dict(kit.MARIA_SLOTS, heat_cool="false", other_utils="two_plus")
    rows = {r.question: r.answer for r in block(builder.build(kit.maria(slots=answered), lang="en", now=kit.NOW,
                                                              base_url=""), "answer_sheet").rows}
    assert rows["Heating or cooling bill apart from rent"] == "No."
    assert rows["Other bills (water, trash, electric, phone)"] == "I pay two or more of these."


def test_irt_line_follows_the_130_percent_line(builder, kit) -> None:
    def after(**slots: str) -> str:
        view = builder.build(kit.maria(slots=dict(kit.MARIA_SLOTS, **slots)), lang="en", now=kit.NOW, base_url="")
        return " ".join(block(view, "after_approval").paragraphs)

    at_line = after(earned_monthly="1729.00")  # at the 130% line: the IRT line
    assert "over $1,729 a month" in at_line and "Report all your income on your SAR 7" not in at_line
    above = after(earned_monthly="1729.01")
    assert "Report all your income on your SAR 7" in above and "$1,729" not in above
    # two people (a spouse): the 2-person line
    assert "over $2,345 a month" in after(earned_monthly="1800.00", spouse="true")


def test_household_size_rows() -> None:
    from gatorplate.card.builder import _size_row

    rows = {"1": 1729, "8": 6037, "each_over_8": 616, "18_plus": 12197}
    assert _size_row(rows, 1) == 1729 and _size_row(rows, 8) == 6037
    assert _size_row(rows, 9) == 6037 + 616 and _size_row(rows, 18) == 12197
    assert _size_row({"8": 1841, "each_over_8": 225}, 20) == 1841 + 225 * 12


# ---------------------------------------------------------------------------------------------- dates

@pytest.mark.parametrize("example", range(4))
def test_filing_date_examples_from_the_rules_table(builder, example) -> None:
    ex = builder._table.filing_date_estimate.examples[example]
    assert builder.filing_date(datetime.fromisoformat(ex.now)) == ex.filed_on


@pytest.mark.parametrize(("now", "filed", "amount", "days"), [
    (datetime(2026, 10, 2, 23, 59, tzinfo=UTC), date(2026, 10, 2), 296, 30),   # Fri 16:59 PT
    (datetime(2026, 10, 3, 0, 1, tzinfo=UTC), date(2026, 10, 5), 266, 27),     # Fri 17:01 PT -> Mon
    (datetime(2026, 10, 3, 17, 0, tzinfo=UTC), date(2026, 10, 5), 266, 27),    # Sat 10:00 PT -> Mon
    (datetime(2026, 10, 2, 6, 30, tzinfo=UTC), date(2026, 10, 2), 296, 30),    # Thu 23:30 PT: already Fri Oct 2
])
def test_first_month_is_refreshed_for_later_filing_days(builder, kit, now, filed, amount, days) -> None:
    view = builder.build(kit.maria(), lang="en", now=now, base_url="")
    assert view.first_month is not None and view.first_month.estimate
    assert (view.first_month.filed_on, view.first_month.amount, view.first_month.days_counted) == (filed, amount, days)
    assert view.first_month.month_label == "October"


def test_first_month_below_minimum_and_outside_the_table(builder, kit) -> None:
    late = datetime(2026, 10, 30, 23, 0, tzinfo=UTC)  # Fri Oct 30 16:00 PT -> 2 days of $306 -> $19
    view = builder.build(kit.maria(), lang="en", now=late, base_url="")
    assert view.first_month.amount == (306 * 2) // 31 == 19
    g8 = builder.build(kit.boundary(), lang="en", now=late, base_url="")
    assert g8.first_month.amount == 0  # (25 x 2) // 31 = 1, under the $10 minimum issue
    after = datetime(2027, 10, 4, 17, 0, tzinfo=UTC)
    gone = builder.build(kit.maria(), lang="en", now=after, base_url="")
    assert gone.first_month is None
    assert not any(p.startswith("Our estimate: if you send it now") for p in block(gone, "today_action").paragraphs)


# ---------------------------------------------------------------------------------------------- status and urls

def test_status_and_urls(builder, kit) -> None:
    case = kit.maria()
    st = builder.status(case)
    assert (st.status, st.reviewed, st.reviewed_at, st.tier, st.estimate_monthly) == ("new", False, None, "likely", 306)
    at = datetime(2026, 10, 3, 0, 3, tzinfo=UTC)
    reviewed = kit.maria(status="reviewed", reviewed_at=at)
    st = builder.status(reviewed)
    assert st.reviewed and st.reviewed_at == at
    view = builder.build(reviewed, lang="es", now=kit.NOW, base_url="https://example.invalid")
    assert view.status == st
    assert view.reminders_url == f"/api/card/{kit.TOKEN}/reminders.ics?lang=es"
    assert view.delete_url == f"/api/card/{kit.TOKEN}"
    assert view.generated_at == kit.NOW and view.expires_at == case.card.expires_at
    coord = builder.status(kit.sofia())
    assert coord.tier == "coordinator" and coord.estimate_monthly is None


def test_no_card_ref_is_not_found(builder, kit) -> None:
    with pytest.raises(NotFound):
        builder.build(kit.maria(card=False), lang="en", now=kit.NOW, base_url="")


def test_calendar_link_only_where_the_calendar_endpoint_serves_it(builder, kit) -> None:
    """The calendar endpoint serves every case with a filing day (docs/UI_SPEC.md A4.3): a first-month estimate or
    the application day the coordinator recorded. No link elsewhere, so the page never offers a download that answers
    404."""
    tracking = Tracking(applied_at=date(2026, 10, 1), filed_on=date(2026, 10, 1))
    case = kit.make_case(reason="coordinator.shared_household", slots=dict(UNDERGRAD), tracking=tracking)
    view = builder.build(case, lang="en", now=kit.NOW, base_url="")
    assert view.reminders_url == f"/api/card/{kit.TOKEN}/reminders.ics?lang=en"
    assert "interview" in ids(view)
    assert "DTSTART;VALUE=DATE:20261004" in builder.ics(case, lang="en")
    untracked = kit.make_case(reason="coordinator.shared_household", slots=dict(UNDERGRAD))
    if untracked.first_month is None:
        assert builder.build(untracked, lang="en", now=kit.NOW, base_url="").reminders_url is None
    likely = builder.build(kit.maria(tracking=tracking), lang="en", now=kit.NOW, base_url="")
    assert likely.reminders_url == f"/api/card/{kit.TOKEN}/reminders.ics?lang=en"
    for route in ("other_help.status", "coordinator.parent_household", "info.interview_waiting"):
        assert builder.build(route_case(kit, route), lang="en", now=kit.NOW, base_url="").reminders_url is None


def test_no_double_period_after_an_abbreviated_value(builder, kit) -> None:
    for lang in ("en", "es"):
        view = builder.build(kit.maria(), lang=lang, now=kit.NOW, base_url="")
        for s in cardview_strings(view):
            assert ".." not in s and "…" not in s, s
    es = builder.build(kit.maria(), lang="es", now=kit.NOW, base_url="")
    contact = block(es, "contact").paragraphs
    assert "CalFresh de San Francisco (condado): (855) 355-5757, lunes a viernes, 8 a. m.–5 p. m." in contact
