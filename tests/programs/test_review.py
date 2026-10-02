"""Edge cases for the programs engine and its view (docs/SPEC.md §5.10 and §6.6; docs/UI_SPEC.md A4.2 row 2b and A9):
the golden CalFresh inputs, no dependence on the caller's Decimal context, floors on every answer set, Pacific dates,
idempotency, privacy of every view string, the forbidden-phrase grep, the share origin, the yearly ask threshold read
from the table, row expiry later in the year and households beyond the limit rows."""

from __future__ import annotations

import decimal
import itertools
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from gatorplate.clock import FixedClock
from gatorplate.contracts.common import Lang
from gatorplate.programs import ProgramFacts, Programs
from gatorplate.programs.guard import view_strings
from gatorplate.programs.view import ViewInput, build_view, site_origin, usd_exact

ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN = json.loads((ROOT / "data" / "golden" / "programs_golden.json").read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in GOLDEN["cases"]}
TODAY = date(2026, 10, 2)
CHOICES = {"break_transit": ["none", "two_days", "weekdays_muni", "weekdays_bart"],
           "tax_dependent": ["no", "yes", "not_sure"],
           "pge_bill": ["own_mine", "own_roommate", "in_rent", "not_sure"]}
MARIA_TAPS = {"break_transit": "weekdays_muni", "tax_dependent": "no", "pge_bill": "own_roommate"}


def every_answer_set() -> list[dict[str, str]]:
    options = [[None, *c] for c in CHOICES.values()]
    return [{q: a for q, a in zip(CHOICES, combo, strict=True) if a} for combo in itertools.product(*options)]


def compute(engine: Programs, case_id: str, answers: dict[str, str] | None = None, *, today: date | None = None,
            facts: dict | None = None, progress: dict[str, bool] | None = None):
    case = CASES[case_id]
    return engine.compute(ProgramFacts.model_validate(facts or case["facts"]),
                          answers=case["answers"] if answers is None else answers, progress=progress or {},
                          today=today or date.fromisoformat(case["today"]))


# ---------------------------------------------------------------------------------------------- golden inputs

def test_golden_calfresh_block_is_the_facts_route_and_estimate() -> None:
    """Each case's `calfresh` (the CalFresh result to use as given) is what its facts carry."""
    for case in GOLDEN["cases"]:
        assert case["facts"]["route"] == case["calfresh"]["route"], case["id"]
        assert case["facts"]["calfresh_monthly"] == case["calfresh"]["monthly"], case["id"]


# ---------------------------------------------------------------------------------------------- Decimal context

HOSTILE = [decimal.Context(prec=3, rounding=decimal.ROUND_CEILING),
           decimal.Context(prec=6, rounding=decimal.ROUND_UP, traps=[decimal.Inexact]),
           decimal.Context(prec=60, rounding=decimal.ROUND_FLOOR)]


@pytest.mark.parametrize("ctx", HOSTILE, ids=["prec3-ceiling", "prec6-up-inexact-trap", "prec60-floor"])
def test_results_never_depend_on_the_callers_decimal_context(engine, make_case, ctx: decimal.Context) -> None:
    """The rounding convention is exact Decimal with explicit floors: a precision or rounding mode set by another
    part of the process must not move a value by a dollar (172 instead of 168) or crash the console trace."""
    plain = {cid: compute(engine, cid) for cid in CASES}
    taps_case = make_case("maria_g1", answers=MARIA_TAPS, slots={
        "age": "26", "lives_with_parent": "false", "roommates": "true", "earned_monthly": "1169.10",
        "work_study_monthly": "200.00", "unearned_monthly": "50.00"}, reason_code="likely", estimate=211)
    plain_eval = engine.evaluate(taps_case, today=TODAY)
    plain_view = {lang: engine.view(taps_case, lang=lang, today=TODAY) for lang in (Lang.en, Lang.es)}
    with decimal.localcontext(ctx):
        for cid, want in plain.items():
            got = compute(engine, cid)
            assert (got is None) == (want is None), cid
            if want is not None:
                assert got.result.model_dump() == want.result.model_dump(), cid
        assert engine.evaluate(taps_case, today=TODAY).model_dump() == plain_eval.model_dump()
        for lang, want_view in plain_view.items():
            assert engine.view(taps_case, lang=lang, today=TODAY).model_dump() == want_view.model_dump()
    assert decimal.getcontext().prec != 3  # the test's context is gone again


# ---------------------------------------------------------------------------------------------- floors and sums

@pytest.mark.parametrize("case_id", ["PG2", "PG4", "PG7", "PG8", "PG9", "PG13"])
def test_floors_and_sums_on_every_answer_set(engine, case_id: str) -> None:
    money = engine.table.money
    monthly = CASES[case_id]["facts"]["calfresh_monthly"]
    for answers in every_answer_set():
        r = compute(engine, case_id, answers, progress={"calfresh": True, "care": True}).result
        for line in r.lines:
            if line.value_yearly is not None:
                assert line.display_yearly == line.value_yearly // money.display_round_down_to * \
                    money.display_round_down_to, (case_id, answers, line.id)
            assert line.counted == (line.status == "likely"), (case_id, answers, line.id)
        counted = [ln for ln in r.lines if ln.counted]
        assert r.found_yearly == sum(ln.value_yearly for ln in counted)
        assert r.found_display == sum(ln.display_yearly for ln in counted)
        want_share = r.found_display // money.share_round_down_to * money.share_round_down_to
        assert r.share_display == (want_share or None)
        assert r.claimed_display == sum(ln.display_yearly for ln in counted if ln.id in ("calfresh", "care"))
        assert r.claimed_display <= r.found_display
        # a card answer never changes CalFresh: the key line stays 12 x the monthly estimate, likely and counted
        key = r.lines[0]
        assert (key.id, key.status, key.counted) == ("calfresh", "likely", True)
        assert key.value_yearly == r.calfresh_yearly == money.horizon_months * monthly


# ---------------------------------------------------------------------------------------------- Pacific dates

def test_the_table_is_pacific() -> None:
    assert Programs().table.timezone == "America/Los_Angeles"


@pytest.mark.parametrize(("utc", "pacific", "result", "apply_by"), [
    (datetime(2026, 10, 1, 6, 59, tzinfo=UTC), date(2026, 9, 30), False, None),        # 11:59 PM PT, the day before
    (datetime(2026, 10, 1, 7, 0, tzinfo=UTC), date(2026, 10, 1), True, date(2026, 11, 19)),
    (datetime(2026, 11, 20, 7, 30, tzinfo=UTC), date(2026, 11, 19), True, date(2026, 11, 19)),  # still Nov 19 in PT
    (datetime(2026, 11, 20, 8, 30, tzinfo=UTC), date(2026, 11, 20), True, date(2027, 4, 22)),
    (datetime(2027, 10, 1, 6, 59, tzinfo=UTC), date(2027, 9, 30), True, None),          # the table's last day
    (datetime(2027, 10, 1, 7, 0, tzinfo=UTC), date(2027, 10, 1), False, None),
])
def test_the_pacific_date_decides(engine, make_case, utc: datetime, pacific: date, result: bool,
                                  apply_by: date | None) -> None:
    """Callers pass the America/Los_Angeles date (gatorplate.clock); the UTC date would be a day late at night."""
    today = FixedClock(utc).today()
    assert today == pacific
    out = engine.evaluate(make_case("maria_g1", answers=MARIA_TAPS), today=today)
    assert (out is not None) == result
    if out is not None:
        clipper = next(ln for ln in out.lines if ln.id == "clipper_start")
        assert clipper.apply_by == apply_by


def test_after_the_last_break_deadline_there_is_no_apply_by(engine, make_case) -> None:
    case = make_case("maria_g1", answers=MARIA_TAPS)
    for lang in (Lang.en, Lang.es):
        view = engine.view(case, lang=lang, today=date(2027, 4, 23))
        clipper = next(p for p in view.programs if p.id == "clipper_start")
        assert clipper.apply_by_text is None and clipper.status == "likely"


def test_later_in_the_year_more_rows_end(engine) -> None:
    """2027-06-01: the LifeLine and Medi-Cal rows ended on 2026-12-31 and the CARE rates on 2027-05-31, so those
    lines are `check` with no dollars; Clipper START keeps its 2026 fares (open-ended) and has no deadline left.
    Hand calculation: CalFresh 3,672 + Clipper START 168 = 3,840 (display 3,670 + 160 = 3,830; share 3,800)."""
    r = compute(engine, "PG1", today=date(2027, 6, 1)).result
    lines = {ln.id: ln for ln in r.lines}
    for pid in ("medi_cal", "lifeline", "care"):
        assert lines[pid].status == "check" and lines[pid].value_yearly is None, pid
        assert lines[pid].display_yearly is None and not lines[pid].counted, pid
    assert lines["care"].note_keys == []  # the status rule's note went with the dollars
    assert (lines["clipper_start"].status, lines["clipper_start"].value_yearly) == ("likely", 168)
    assert lines["clipper_start"].apply_by is None
    assert (r.found_yearly, r.found_display, r.share_display) == (3840, 3830, 3800)


def test_a_household_beyond_the_limit_rows_shows_no_dollars(engine) -> None:
    """The Medi-Cal limit rows stop at 6 people: a household of 7 has no number to compare with, so `check` with no
    dollars; the status rule's notes go, the note rules (a child may get Medi-Cal too) stay."""
    facts = {**CASES["PG9"]["facts"], "children_count": 6, "household_size": 7, "people_in_home": 7}
    computed = compute(engine, "PG9", facts=facts)
    medi = next(ln for ln in computed.result.lines if ln.id == "medi_cal")
    assert medi.status == "check" and medi.value_yearly is None and medi.note_keys == ["medi_cal.child_too"]
    for lang in (Lang.en, Lang.es):
        view = build_view(ViewInput(computed=computed, table=engine.table, content=engine.content[lang],
                                    site=engine.public_base_url, household_food="alone"))
        assert all(engine.guard.hits(s) == [] for s in view_strings(view))


# ---------------------------------------------------------------------------------------------- idempotency

def test_the_same_inputs_give_the_same_part(engine, make_case) -> None:
    case = make_case("maria_g1", answers={"tax_dependent": "no", "break_transit": "two_days"},
                     progress={"calfresh": True})
    first = engine.evaluate(case, today=TODAY).model_dump()
    assert engine.evaluate(case, today=TODAY).model_dump() == first
    assert engine.view(case, lang=Lang.es, today=TODAY) == engine.view(case, lang=Lang.es, today=TODAY)
    reordered = make_case("maria_g1", answers={"break_transit": "two_days", "tax_dependent": "no"},
                          progress={"calfresh": True})
    assert engine.evaluate(reordered, today=TODAY).model_dump() == first


def test_answering_or_marking_twice_changes_nothing(engine, make_case) -> None:
    once = make_case("maria_g1", answers={"break_transit": "weekdays_muni"})
    # the same tap sent again (a retry after a lost reply) is a valid re-answer with the same effect
    assert engine.validate_answers(once, {"break_transit": "weekdays_muni"}, today=TODAY) == {
        "break_transit": "weekdays_muni"}
    again = make_case("maria_g1", answers={"break_transit": "weekdays_muni"})
    assert engine.evaluate(again, today=TODAY) == engine.evaluate(once, today=TODAY)
    marked = make_case("maria_g1", answers=MARIA_TAPS, progress={"calfresh": True})
    assert engine.can_mark(marked, "calfresh", today=TODAY)  # Undo and a repeated mark are both allowed
    assert engine.evaluate(marked, today=TODAY).claimed_display == 3670


def test_both_languages_show_the_same_numbers_and_order(engine, make_case) -> None:
    for answers in ({}, MARIA_TAPS, {"tax_dependent": "yes", "pge_bill": "own_mine"}):
        case = make_case("maria_g1", answers=answers, progress={"calfresh": True})
        en, es = (engine.view(case, lang=lang, today=TODAY) for lang in (Lang.en, Lang.es))
        same = ("mode", "found_display", "claimed_display", "calfresh_display", "segments")
        assert {k: getattr(en, k) for k in same} == {k: getattr(es, k) for k in same}
        assert (en.question is None) == (es.question is None)
        if en.question:
            assert (en.question.id, en.question.index, en.question.total) == (es.question.id, es.question.index,
                                                                               es.question.total)
            assert [c.value for c in en.question.choices] == [c.value for c in es.question.choices]
        key = ("id", "status", "counted", "stage", "applied", "can_mark_applied", "apply_url")
        assert [[getattr(p, k) for k in key] for p in en.programs] == [[getattr(p, k) for k in key]
                                                                      for p in es.programs]
        assert len(en.chips) == len(es.chips) and (en.share_text is None) == (es.share_text is None)


def test_stored_marks_for_lines_that_are_not_counted_change_no_total(engine, make_case) -> None:
    case = make_case("maria_g1", answers={}, progress={"medi_cal": True, "lifeline": True, "nope": True})
    r = engine.evaluate(case, today=TODAY)
    assert r.claimed_display == 0 and r.found_display == 3670
    view = engine.view(case, lang=Lang.en, today=TODAY)
    assert view.labels["ui.claimed"] == "You've started $0 of $3,670"


# ---------------------------------------------------------------------------------------------- privacy

def test_no_view_string_carries_the_token_code_or_case_id(engine, make_case) -> None:
    token, code = "Tk9qPrivateCardToken_xyz", "Q4Z-7WB"
    for name, answers in (("maria_g1", {}), ("maria_g1", MARIA_TAPS), ("jamal_g4", None), ("sofia_g3", None)):
        case = make_case(name, answers=answers, token=token, code=code, progress={"calfresh": True})
        for lang in (Lang.en, Lang.es):
            view = engine.view(case, lang=lang, today=TODAY)
            texts = [*view_strings(view), *(p.apply_url for p in view.programs)]
            for text in texts:
                assert token not in text and code not in text and case.id not in text, (name, lang, text)
                assert "/c/" not in text, (name, lang, text)


def test_list_only_shows_no_amount_even_with_stored_answers(engine, make_case) -> None:
    """A route that turned coordinator after card answers were stored still shows no dollars at all."""
    for route in ("coordinator.unresolved", "coordinator.parent_household", "info.already_receiving",
                  "info.interview_waiting"):
        case = make_case("maria_g1", answers=MARIA_TAPS, progress={"calfresh": True}, reason_code=route,
                         estimate=306)
        for lang in (Lang.en, Lang.es):
            view = engine.view(case, lang=lang, today=TODAY)
            assert view.mode == "list_only" and view.claimed_display == 0
            assert [s for s in view_strings(view) if "$" in s] == [], (route, lang)


FORBIDDEN_WORDS = re.compile(r"\b(?:not eligible|ineligible|don'?t qualify|denied|no califica|no eres elegible)\b",
                             re.IGNORECASE)


def test_forbidden_phrase_grep_over_the_programs_files() -> None:
    """docs/UI_SPEC.md A9 item 6 for A9's own files: whole words, code comments included."""
    files = [p for p in (ROOT / "web" / "unlocked").iterdir() if p.is_file()]
    files += [ROOT / "data" / "content" / f"programs.{lang}.json" for lang in ("en", "es")]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert FORBIDDEN_WORDS.findall(text) == [], path.name


# Spanish promises of a refund, credit, discount, Medi-Cal or coverage (the Spanish equivalents of the English
# output patterns in guards.json); a local check until guards.json carries them too (CONTRACT_REQUESTS.md).
SPANISH_PROMISES = re.compile(
    r"\b(?:recibir[áa]s|(?:vas|va) a (?:recibir|tener)|tendr[áa]s) (?:un |una |tu )?"
    r"(?:reembolso|cr[ée]dito|descuento|medi-cal|cobertura)\b|\byou(?: will|'ll) be (?:covered|enrolled)\b",
    re.IGNORECASE)


def test_no_promise_of_coverage_or_cash_in_any_language(engine, make_case) -> None:
    for name, answers in (("maria_g1", {}), ("maria_g1", MARIA_TAPS), ("jamal_g4", None), ("sofia_g3", None),
                          ("maria_g1", {"tax_dependent": "yes", "pge_bill": "own_mine", "break_transit": "none"})):
        for lang in (Lang.en, Lang.es):
            view = engine.view(make_case(name, answers=answers), lang=lang, today=TODAY)
            for text in view_strings(view):
                assert not SPANISH_PROMISES.search(text), text
                assert not re.search(r"\$0 (?:premium|prima)|prima de \$0|\bdental\b|\bvision\b|\bvisi[óo]n\b", text, re.I), text
    for lang in ("en", "es"):
        strings = json.loads((ROOT / "data" / "content" / f"programs.{lang}.json").read_text(encoding="utf-8"))
        for key, text in strings["strings"].items():
            assert not SPANISH_PROMISES.search(text), key
    assert SPANISH_PROMISES.search("Recibirás un reembolso") and SPANISH_PROMISES.search("Vas a tener cobertura")


def test_medi_cal_is_coverage_never_cash(engine, make_case) -> None:
    view = engine.view(make_case("maria_g1", answers={}), lang=Lang.en, today=TODAY)
    medi = next(p for p in view.programs if p.id == "medi_cal")
    assert medi.status == "coverage" and not medi.counted and "at no cost for most students today" in medi.line
    assert "medi_cal" not in [pid for pid, _v in view.segments]
    assert "+ health coverage (Medi-Cal)" in view.chips


def test_federal_lifeline_is_shown_floored_and_never_counted(engine, make_case) -> None:
    case = make_case("maria_g1", answers=MARIA_TAPS)
    result = engine.evaluate(case, today=TODAY)
    life = next(ln for ln in result.lines if ln.id == "lifeline")
    assert life.value_yearly == 228 and life.vars["fed"] == "111"  # 12 x $9.25 = $111, display only
    assert result.found_yearly == 4238  # 228, never 228 + 111
    view = engine.view(case, lang=Lang.en, today=TODAY)
    notes = next(p for p in view.programs if p.id == "lifeline").notes
    assert "Federal Lifeline may add up to $110 a year more." in notes


# ---------------------------------------------------------------------------------------------- share origin

# A user name and password inside the setting's URL ("https://name:word" + "@" + host); written in parts so that the
# text never looks like an address.
USERINFO = "deploy:" + "pw-not-real" + "@"


def test_share_origin_never_carries_a_path_or_a_secret() -> None:
    assert site_origin("https://" + USERINFO + "gatorplate.fly.dev/c/abc?t=1#x") == "https://gatorplate.fly.dev"
    assert site_origin("HTTPS://GatorPlate.fly.dev/") == "https://gatorplate.fly.dev"
    assert site_origin("http://[::1]:8000/x") == "http://[::1]:8000"
    for bad in ("javascript:alert(1)", "ftp://gatorplate.fly.dev", "gatorplate.fly.dev", "http://h:99999/", "   "):
        assert site_origin(bad) == "", bad


def test_share_text_with_credentials_in_the_setting(make_case) -> None:
    engine = Programs(public_base_url="https://" + USERINFO + "gatorplate.fly.dev/c/tok?x=1")
    view = engine.view(make_case("maria_g1", answers={}), lang=Lang.en, today=TODAY)
    assert view.share_text.endswith("Check yours in 2 minutes: https://gatorplate.fly.dev")
    assert "pw-not-real" not in view.share_text and "deploy" not in view.share_text and "/c/" not in view.share_text


def test_exact_money_always_shows_cents_as_two_digits() -> None:
    assert usd_exact(Decimal("900.00")) == "$900" and usd_exact(140) == "$140"
    assert usd_exact(Decimal("1169.10")) == "$1,169.10" and usd_exact(Decimal("900.5")) == "$900.50"


# ---------------------------------------------------------------------------------------------- the ask rule

@pytest.mark.parametrize(("threshold", "pge_open"), [(169, True), (170, False)])
def test_the_yearly_card_threshold_is_read_from_the_table(tmp_path: Path, threshold: int, pge_open: bool) -> None:
    """Maria's PG&E question moves the yearly total by exactly $170: open above a $169 rule, not at $170 (strictly
    greater). The number comes from the table's ask_rule, never from the CalFresh question picker's monthly $50."""
    raw = json.loads((ROOT / "data" / "rules" / "programs_2026.json").read_text(encoding="utf-8"))
    raw["ask_rule"]["threshold_usd"] = threshold
    table = tmp_path / "programs.json"
    table.write_text(json.dumps(raw), encoding="utf-8")
    engine = Programs(table_path=table, public_base_url="https://gatorplate.fly.dev")
    r = engine.compute(ProgramFacts.model_validate(CASES["PG2"]["facts"]), answers={}, progress={}, today=TODAY).result
    assert r.question_spreads["pge_bill"] == 170
    assert ("pge_bill" in r.open_questions) is pge_open


def test_spreads_measure_the_yearly_value_not_the_display(engine) -> None:
    """tax_dependent moves found_yearly by 228 (LifeLine) but the display by 220: the rule measures 228."""
    r = compute(engine, "PG2", {}).result
    assert r.question_spreads["tax_dependent"] == 228
    no = compute(engine, "PG2", {"tax_dependent": "no"}).result
    assert no.found_display - r.found_display == 220 and no.found_yearly - r.found_yearly == 228


# ---------------------------------------------------------------------------------------------- the widget

def test_the_widget_renders_a_reply_only_in_the_language_on_screen() -> None:
    """A reply to a tap that arrives after the card switched language is not drawn over the new language."""
    js = (ROOT / "web" / "unlocked" / "unlocked.js").read_text(encoding="utf-8")
    assert "if (next.lang == view.lang) focusTo = focus, render(next), say(next.total_text);" in js


def test_screen_readers_get_only_the_final_total() -> None:
    """After the last answer focus lands on the total while it still counts up (docs/UI_SPEC.md A4.2 row 2b, A6.8):
    the counting amount is hidden from screen readers and a visually hidden copy holds the final amount."""
    js = (ROOT / "web" / "unlocked" / "unlocked.js").read_text(encoding="utf-8")
    assert 'h("span.amount.num", { "aria-hidden": "true" }, parts[1])' in js
    assert '[parts[0], amt, h("span.sr-only", parts[1]), parts[2]]' in js
    assert 'h("p.unl-total", { tabindex: -1 })' in js and 'live: h("p.sr-only", { role: "status" })' in js
