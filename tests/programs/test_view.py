"""UnlockedView in English and Spanish (docs/SPEC.md §6.6, docs/UI_SPEC.md A4.2 row 2b): the fixture replies, the
output guard on every string, the content budgets, the share text, list_only, expired rows and dates."""

from __future__ import annotations

import itertools
import json
import re
from datetime import date
from pathlib import Path

import pytest

from gatorplate.contracts.common import Lang
from gatorplate.contracts.programs import UnlockedView
from gatorplate.programs import ProgramFacts, Programs
from gatorplate.programs.guard import view_strings
from gatorplate.programs.view import ViewInput, build_view, site_origin

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = ROOT / "web" / "fixtures"
GOLDEN = json.loads((ROOT / "data" / "golden" / "programs_golden.json").read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in GOLDEN["cases"]}
TODAY = date(2026, 10, 2)
MARIA_TAPS = [("break_transit", "weekdays_muni"), ("tax_dependent", "no"), ("pge_bill", "own_roommate")]
BUDGETS = {"question": 18, "choice": 5, "line": 30, "note": 25, "share": 30, "footnote": 25, "label": 18,
           "button": 5, "name": 6, "prefill": 18}


def words(text: str) -> int:
    """Contract word: a whitespace-separated token with at least one letter or digit."""
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


def view_of(engine: Programs, facts: dict, answers: dict[str, str], lang: Lang, today: date = TODAY,
            progress: dict[str, bool] | None = None) -> UnlockedView | None:
    computed = engine.compute(ProgramFacts.model_validate(facts), answers=answers, progress=progress or {},
                              today=today)
    if computed is None:
        return None
    return build_view(ViewInput(computed=computed, table=engine.table, content=engine.content[lang],
                                site=engine.public_base_url, household_food="separate"))


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def site_of(share_text: str) -> str:
    return re.search(r"https?://\S+$", share_text).group(0)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------------------------- fixture replies

@pytest.mark.parametrize("lang", ["en", "es"])
def test_maria_views_equal_the_card_fixtures(make_case, lang: str) -> None:
    """The replies the widget's harness replays (card_maria_*, unlocked_maria_steps*, unlocked_maria_progress*)."""
    sfx = "" if lang == "en" else "_es"
    start = fixture(f"card_maria_{lang}.json")["unlocked"]
    engine = Programs(public_base_url=site_of(start["share_text"]))
    answers: dict[str, str] = {}
    got = engine.view(make_case("maria_g1", answers={}), lang=Lang(lang), today=TODAY)
    assert got is not None and got.model_dump(mode="json") == start
    steps = fixture(f"unlocked_maria_steps{sfx}.json")
    for (qid, choice), want in zip(MARIA_TAPS, steps, strict=True):
        answers[qid] = choice
        got = engine.view(make_case("maria_g1", answers=dict(answers)), lang=Lang(lang), today=TODAY)
        assert got is not None and got.model_dump(mode="json") == want
    progress = fixture(f"unlocked_maria_progress{sfx}.json")
    got = engine.view(make_case("maria_g1", answers=dict(answers), progress={"calfresh": True}), lang=Lang(lang),
                      today=TODAY)
    assert got is not None and got.model_dump(mode="json") == progress


def test_the_w4_walk(engine, make_case) -> None:
    answers: dict[str, str] = {}
    view = engine.view(make_case("maria_g1", answers={}), lang=Lang.en, today=TODAY)
    seen = [(view.total_text, view.question.index, view.question.total, view.question.id)]
    for qid, choice in MARIA_TAPS:
        answers[qid] = choice
        view = engine.view(make_case("maria_g1", answers=dict(answers)), lang=Lang.en, today=TODAY)
        q = view.question
        seen.append((view.total_text, q.index if q else None, q.total if q else None, q.id if q else None))
    assert seen == [("About $3,670 a year", 1, 3, "break_transit"), ("About $3,830 a year", 2, 3, "tax_dependent"),
                    ("About $4,050 a year", 3, 3, "pge_bill"), ("About $4,220 a year", None, None, None)]
    assert view.share_text is not None and "about $4,200" in view.share_text
    assert sum(v for _id, v in view.segments) == view.found_display == 4220
    assert [s[0] for s in view.segments] == ["calfresh", "clipper_start", "lifeline", "care"]
    care = next(p for p in view.programs if p.id == "care")
    assert "Assumed bill: $140 a month split 3 ways" in care.line


# ---------------------------------------------------------------------------------------------- sweep

QUESTION_CHOICES = {"break_transit": ["none", "two_days", "weekdays_muni", "weekdays_bart"],
                    "tax_dependent": ["no", "yes", "not_sure"],
                    "pge_bill": ["own_mine", "own_roommate", "in_rent", "not_sure"]}


def answer_sets(*, partial: bool = True) -> list[dict[str, str]]:
    """Every combination of the three card answers (each unanswered or one of its choices); with partial=False,
    only no answer at all and the combinations where all three are answered."""
    options = [[None, *c] for c in QUESTION_CHOICES.values()]
    combos = [{q: a for q, a in zip(QUESTION_CHOICES, combo, strict=True) if a} for combo in itertools.product(*options)]
    return [c for c in combos if partial or len(c) in (0, len(QUESTION_CHOICES))]


def sweep(engine: Programs) -> list[tuple[str, Lang, UnlockedView]]:
    """Maria with every answer combination (also on a day with expired rows), six more fact sets (every status and
    both tax variants), Sofia (list_only) and PG1-b (marks), in both languages."""
    runs = [("PG2", answers, TODAY) for answers in answer_sets()]
    runs += [(cid, answers, TODAY) for cid in ("PG4", "PG6", "PG7", "PG8", "PG9", "PG13")
             for answers in answer_sets(partial=False)]
    runs += [("PG2", answers, date(2027, 1, 15)) for answers in answer_sets(partial=False)]
    out = []
    for cid, answers, today in runs:
        for lang in (Lang.en, Lang.es):
            view = view_of(engine, CASES[cid]["facts"], answers, lang, today)
            assert view is not None
            out.append((cid, lang, view))
    for lang in (Lang.en, Lang.es):
        out.append(("PG5", lang, view_of(engine, CASES["PG5"]["facts"], {}, lang)))
        out.append(("PG1-b", lang, view_of(engine, CASES["PG1"]["facts"], CASES["PG1"]["answers"], lang,
                                            progress={"calfresh": True, "clipper_start": True})))
    return out


@pytest.fixture(scope="module")
def swept(engine) -> list[tuple[str, Lang, UnlockedView]]:
    return sweep(engine)


def test_the_sweep_covers_every_status(swept) -> None:
    statuses = {p.status for _c, _l, v in swept for p in v.programs}
    assert statuses == {"likely", "maybe", "check", "coverage", "zero", "note"}
    assert {v.mode for _c, _l, v in swept} == {"full", "list_only"}
    variants = {p.line for _c, lang, v in swept if lang == Lang.en for p in v.programs if p.id == "tax_credits"}
    assert any("CalEITC and federal EITC" in t for t in variants)
    assert any("Young Child Tax Credit" in t for t in variants)


def test_every_view_string_passes_the_output_guard(engine, swept) -> None:
    texts = {text for _cid, _lang, view in swept for text in view_strings(view)}
    assert len(texts) > 300
    for text in sorted(texts):
        assert engine.guard.hits(text) == [], text


def test_the_guard_catches_promises(engine) -> None:
    for bad in ("You'll save $200 a year.", "You will get a refund", "You're covered.", "Free money!",
                "Ahorrarás $200 al año.", "Estás cubierta.", "Dinero gratis", "You are approved"):
        assert engine.guard.hits(bad), bad


def test_no_placeholder_or_verify_marker_is_left(swept) -> None:
    for cid, lang, view in swept:
        for text in view_strings(view):
            if text in view.labels.values() and "{i}" in text:
                continue  # ui.question_count keeps {i} / {n} for the widget
            assert not re.search(r"\{[a-z_]+\}", text), f"{cid} {lang}: {text!r}"
            assert "[verify]" not in text, f"{cid} {lang}: {text!r}"


def test_budgets(swept) -> None:
    by_class: dict[str, set[str]] = {k: set() for k in BUDGETS}
    for _cid, _lang, view in swept:
        if view.question:
            by_class["question"].add(view.question.text)
            by_class["choice"].update(c.label for c in view.question.choices)
        for p in view.programs:
            by_class["line"].add(p.line)
            by_class["note"].update(p.notes)
            by_class["name"].add(p.name)
            by_class["button"].add(p.apply_label)
            by_class["prefill"].update(x for row in p.prefill for x in (row.question, row.answer))
            by_class["label"].update(x for x in (p.value_text, p.status_label, p.stage_label, p.apply_by_text) if x)
        by_class["share"].update([view.share_text] if view.share_text else [])
        by_class["footnote"].add(view.footnote)
        by_class["label"].update(view.labels.values())
        by_class["label"].update(view.chips)
        by_class["label"].add(view.title)
    for cls, texts in by_class.items():
        assert texts, cls
        for text in texts:
            assert words(text) <= BUDGETS[cls], f"{cls} {words(text)} words: {text!r}"


def test_amounts_are_hedged(swept) -> None:
    hedge = {Lang.en: re.compile(r"\b(?:about|up to|maybe|may|could|roughly)\b", re.I),
             Lang.es: re.compile(r"\b(?:unos|hasta|quizá|podría|puede|cerca de)\b", re.I)}
    for cid, lang, view in swept:
        for p in view.programs:
            for text in [p.line, p.value_text, *p.notes]:
                if text and "$" in text:
                    assert hedge[lang].search(text), f"{cid} {lang}: {text!r}"


def test_parts_add_up_to_the_headline(swept) -> None:
    for cid, _lang, view in swept:
        if view.mode != "full":
            continue
        assert sum(v for _id, v in view.segments) == view.found_display, cid
        applied = {p.id for p in view.programs if p.applied}
        assert sum(v for pid, v in view.segments if pid in applied) == view.claimed_display, cid
        assert view.segments[0][0] == "calfresh" and view.calfresh_display == view.segments[0][1]


def test_zero_and_note_lines_have_no_button_or_form(swept) -> None:
    for _cid, _lang, view in swept:
        for p in view.programs:
            if p.status in ("zero", "note") or view.mode == "list_only":
                assert p.can_mark_applied is False and p.prefill == [] and p.apply_by_text is None


# ---------------------------------------------------------------------------------------------- share text

def test_the_share_text_never_leaks(engine, make_case) -> None:
    token, code = "Zq9xTokenOnlyForThisTest", "K7Q-2FM"
    site = site_origin(engine.public_base_url)
    for answers in answer_sets(partial=False)[::4]:
        case = make_case("maria_g1", answers=answers, token=token, code=code)
        for lang in (Lang.en, Lang.es):
            view = engine.view(case, lang=lang, today=TODAY)
            assert view is not None and view.share_text is not None and view.found_display is not None
            text = view.share_text
            assert "/c/" not in text and token not in text and code not in text and case.id not in text
            share = (view.found_display // 100) * 100
            template = engine.content[lang].text("share.text")
            # exactly the template with the floored total and the site origin: no answer can be in it
            assert text == template.replace("{share}", f"${share:,}").replace("{site}", site)


def test_share_site_is_only_the_origin() -> None:
    assert site_origin("https://gatorplate.fly.dev/c/abc?x=1") == "https://gatorplate.fly.dev"
    assert site_origin("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    assert site_origin("") == ""


def test_no_site_means_no_share(make_case) -> None:
    view = Programs(public_base_url="").view(make_case("maria_g1", answers={}), lang=Lang.en, today=TODAY)
    assert view is not None and view.share_text is None


# ---------------------------------------------------------------------------------------------- list_only, expiry

@pytest.mark.parametrize("lang", [Lang.en, Lang.es])
def test_sofia_list_only(engine, make_case, lang: Lang) -> None:
    view = engine.view(make_case("sofia_g3"), lang=lang, today=TODAY)
    assert view is not None and view.mode == "list_only"
    content = engine.content[lang]
    assert view.title == content.text("ui.list_only_title")
    assert view.total_text is None and view.found_display is None and view.question is None
    assert view.chips == [] and view.segments == [] and view.share_text is None
    assert [p.id for p in view.programs] == ["medi_cal", "clipper_start"]
    for p in view.programs:
        assert p.line == content.text(f"list_only.{p.id}")
        assert p.status == "check" and p.value_text is None and p.notes == [] and not p.can_mark_applied
        assert "$" not in p.line
    assert view.labels["ui.list_only_intro"] == content.text("ui.list_only_intro")
    assert "ui.claimed" not in view.labels


def test_an_expired_row_shows_no_dollars(engine, make_case) -> None:
    case = make_case("maria_g1", answers=dict(MARIA_TAPS))
    view = engine.view(case, lang=Lang.en, today=date(2027, 1, 15))
    assert view is not None
    by = {p.id: p for p in view.programs}
    life = by["lifeline"]
    assert life.status == "check" and life.value_text is None and "$" not in life.line
    assert life.line == engine.content[Lang.en].text("list_only.lifeline")
    assert by["medi_cal"].status == "check" and by["medi_cal"].value_text is None
    assert by["clipper_start"].apply_by_text == "Apply by about April 22"
    assert view.total_text == "About $4,000 a year"


# ---------------------------------------------------------------------------------------------- dates, labels

def test_dates_in_both_languages(engine, make_case) -> None:
    case = make_case("maria_g1", answers={})
    en = engine.view(case, lang=Lang.en, today=TODAY)
    es = engine.view(case, lang=Lang.es, today=TODAY)
    clip_en = next(p for p in en.programs if p.id == "clipper_start")
    clip_es = next(p for p in es.programs if p.id == "clipper_start")
    assert clip_en.apply_by_text == "Apply by about November 19"
    assert clip_es.apply_by_text == "Solicítalo antes del 19 de noviembre"
    assert "checked Oct 1, 2026." in en.footnote and "revisadas el 1 oct 2026." in es.footnote


def test_labels(engine, make_case) -> None:
    view = engine.view(make_case("maria_g1", answers={}, progress={"calfresh": True}), lang=Lang.en, today=TODAY)
    assert view.labels["ui.question_count"] == "Question {i} of {n}"
    assert view.labels["ui.claimed"] == "You've started $3,670 of $3,670"
    assert view.labels["ui.calfresh_part"] == "CalFresh: about $3,670 a year ($306 a month)"
    assert set(view.labels) == {"ui.claimed", "ui.calfresh_part", "ui.key_line", "ui.question_count",
                                "ui.plan_title", "ui.answers_title", "ui.new_tab", "ui.mark_applied", "ui.undo",
                                "ui.share_button", "ui.copied", "ui.list_only_intro"}
    calfresh = view.programs[0]
    assert calfresh.apply_url == "#today_action" and calfresh.apply_label == "See today's steps"
    assert all(p.apply_url.startswith("https://") for p in view.programs[1:])


def test_prefill_never_asks_for_ssn_or_status(swept) -> None:
    rx = re.compile(r"social security|\bssn\b|immigration|inmigra|citizenship|ciudadan", re.I)
    for _cid, _lang, view in swept:
        for p in view.programs:
            for row in p.prefill:
                assert not rx.search(row.question) and not rx.search(row.answer)
                assert "[verify]" not in row.screen


def test_a_small_tax_credit_shows_no_number(engine) -> None:
    facts = {**CASES["PG7"]["facts"], "earned_monthly": "3000", "magi_monthly": "3000", "earned_annual": "36000"}
    view = view_of(engine, facts, {"tax_dependent": "no"}, Lang.en)
    assert view is not None
    tax = next(p for p in view.programs if p.id == "tax_credits")
    assert tax.status == "maybe" and tax.value_text is None and tax.line == engine.content[Lang.en].text("tax.small")
    assert not any(chip.startswith("maybe +$0") for chip in view.chips)
