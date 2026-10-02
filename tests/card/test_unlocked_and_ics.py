"""The card's unlocked part through a fake ProgramsPort (docs/SPEC.md §6.2 and §6.6) and the calendar file (§6.3)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

import pytest

from gatorplate.card import CardBuilder, cardview_strings
from gatorplate.card.ics import escape_text, fold
from gatorplate.contracts.case import Tracking
from gatorplate.contracts.common import Lang
from gatorplate.contracts.errors import NotFound

# ---------------------------------------------------------------------------------------------- unlocked


def test_unlocked_comes_from_the_port(kit) -> None:
    for lang in ("en", "es"):
        fake = kit.FakePrograms(kit.fixture_unlocked(lang))
        b = CardBuilder(programs=fake)
        view = b.build(kit.maria(), lang=lang, now=kit.NOW, base_url="")
        assert view.unlocked == kit.fixture_unlocked(lang)
        assert view.unlocked.lang == lang
        assert fake.calls == [{"case": "c_card000001", "lang": Lang(lang), "today": date(2026, 10, 2)}]
        assert [blk.id for blk in view.blocks][0] == "today_action"  # unlocked is not a block


def test_today_is_the_pacific_date(kit) -> None:
    fake = kit.FakePrograms(kit.fixture_unlocked())
    b = CardBuilder(programs=fake)
    late = datetime(2026, 10, 3, 6, 30, tzinfo=UTC)  # still Fri Oct 2 at 23:30 in Pacific time
    b.build(kit.maria(), lang="en", now=late, base_url="")
    assert fake.calls[-1]["today"] == date(2026, 10, 2)


@pytest.mark.parametrize("fake_args", [
    {"view": None},                                        # mode none (other_help, incomplete, GP_PROGRAMS=0)
    {"error": NotImplementedError()},                     # the engine is not there yet
    {"error": RuntimeError("boom")},                      # a failing engine never takes the card down
])
def test_unlocked_is_null_without_a_view(kit, fake_args) -> None:
    b = CardBuilder(programs=kit.FakePrograms(**fake_args))
    view = b.build(kit.maria(), lang="en", now=kit.NOW, base_url="")
    assert view.unlocked is None
    assert [blk.id for blk in view.blocks][:2] == ["today_action", "why"]


def test_no_port_means_no_unlocked_part(kit) -> None:
    view = CardBuilder().build(kit.maria(), lang="en", now=kit.NOW, base_url="")
    assert view.unlocked is None


def test_unlocked_guard_hit_drops_the_part(kit) -> None:
    bad = kit.fixture_unlocked().model_copy(update={"footnote": "You're covered. Free money!"})
    view = CardBuilder(programs=kit.FakePrograms(bad)).build(kit.maria(), lang="en", now=kit.NOW, base_url="")
    assert view.unlocked is None


def test_unlocked_strings_pass_the_guard(kit) -> None:
    for lang in ("en", "es"):
        b = CardBuilder(programs=kit.FakePrograms(kit.fixture_unlocked(lang)))
        view = b.build(kit.maria(), lang=lang, now=kit.NOW, base_url="")
        assert view.unlocked is not None
        for s in cardview_strings(view):
            assert b._guard.hits(s) == [], s


# ---------------------------------------------------------------------------------------------- calendar file

def events(text: str) -> list[dict[str, str]]:
    unfolded = text.replace("\r\n ", "")
    out, cur = [], None
    for line in unfolded.split("\r\n"):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            out.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, value = line.split(":", 1)
            cur[key.split(";")[0]] = value
    return out


def test_ics_three_events_from_filed_on(builder, kit) -> None:
    text = builder.ics(kit.maria(), lang="en")
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")
    assert all(len(line.encode("utf-8")) <= 75 for line in text.split("\r\n"))
    evs = events(text)
    assert [e["DTSTART"] for e in evs] == ["20261005", "20261012", "20261030"]  # Oct 2 + 3, 10, 28 days
    assert [e["DTEND"] for e in evs] == ["20261006", "20261013", "20261031"]
    assert evs[0]["SUMMARY"] == "CalFresh: check BenefitsCal and answer calls from unknown numbers"
    assert evs[1]["SUMMARY"] == "CalFresh: no interview call yet? Call (855) 355-5757"
    assert "(855) 355-5757" in evs[2]["SUMMARY"]
    assert len({e["UID"] for e in evs}) == 3
    assert "VALARM" not in text  # dated events only; GatorPlate sends nothing
    assert not re.search(r"remind|recordatorio", text, re.IGNORECASE)


def test_ics_spanish_titles(builder, kit) -> None:
    evs = events(builder.ics(kit.sofia().model_copy(update={"first_month": kit.first_month(296)}), lang="es"))
    assert evs[0]["SUMMARY"] == "CalFresh: revisa BenefitsCal y contesta llamadas de números desconocidos"
    assert evs[1]["SUMMARY"] == "CalFresh: ¿aún no te llaman para la entrevista? Llama al (855) 355-5757"


def test_ics_same_uids_in_both_languages(builder, kit) -> None:
    uids = [[e["UID"] for e in events(builder.ics(kit.maria(), lang=lang))] for lang in ("en", "es")]
    assert uids[0] == uids[1]


def test_ics_prefers_the_recorded_filing_day(builder, kit) -> None:
    case = kit.maria(tracking=Tracking(applied_at=date(2026, 10, 1), filed_on=date(2026, 10, 1)))
    assert [e["DTSTART"] for e in events(builder.ics(case, lang="en"))] == ["20261004", "20261011", "20261029"]


def test_ics_follows_the_card_when_now_is_given(builder, kit) -> None:
    sat = datetime(2026, 10, 3, 17, 0, tzinfo=UTC)
    assert events(builder.ics(kit.maria(), lang="en", now=sat))[0]["DTSTART"] == "20261008"  # Mon Oct 5 + 3


def test_ics_without_a_filing_day(builder, kit) -> None:
    with pytest.raises(NotFound):
        builder.ics(kit.sofia(), lang="en")


def test_ics_text_rules() -> None:
    assert escape_text("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
    long = "SUMMARY:" + "é" * 60
    chunks = fold(long)
    assert "".join(c.removeprefix(" ") if i else c for i, c in enumerate(chunks)) == long
    assert all(len(c.encode("utf-8")) <= 75 for c in chunks) and all(c.startswith(" ") for c in chunks[1:])
