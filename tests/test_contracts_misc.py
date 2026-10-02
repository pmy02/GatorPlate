"""Console wording, the one-line summary, clocks and ids."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from gatorplate.clock import FixedClock, SystemClock, default_test_clock
from gatorplate.contracts import console_text as ct
from gatorplate.contracts.case import CASE_CODE_PATTERN, Case, Slot
from gatorplate.contracts.common import Channel, Lang
from gatorplate.contracts.summary import case_summary, summary_line
from gatorplate.ids import FixedIds, SystemIds


def test_console_texts() -> None:
    assert ct.flip_reason(151, 155, 306) == "could change the estimate by $151: $155 or $306"
    assert ct.skip_detail_no_effect("heating or cooling bill") == (
        "Not asked — heating or cooling bill, same estimate either way")
    assert ct.coordinator_reason("coordinator.parent_household") == (
        "Under 22 and living with a parent — the parent's household is counted together. Confirm, then help with a "
        "household application.")
    assert ct.assumed("Other utility bills", "none", hi=159) == "Other utility bills: assumed none (could be up to $159)"
    assert ct.assumed("Rent", "$1,100", lo=900) == "Rent: assumed $1,100 (could be as low as $900)"
    assert ct.abawd_possible(8, 80) == ("Fewer than 8 units: the county may apply the 3-month work rule unless the "
                                        "student works 80 hours a month.")
    assert ct.abawd_possible(8, 80, graduate=True) == ("Less than half-time: the county may apply the 3-month work "
                                                       "rule unless the student works 80 hours a month.")
    assert ct.student_question("Can I use a relay service?") == 'Student asked: "Can I use a relay service?"'
    assert ct.INCOMPLETE == "Call ended before the result."
    assert ct.flip_reason(1500, 0, 1500) == "could change the estimate by $1,500: $0 or $1,500"


def make_case(**slots: str) -> Case:
    at = datetime(2026, 10, 2, 17, tzinfo=UTC)
    return Case(id="c_aaaaaaaaaa", code="K7Q-2FM", created_at=at, updated_at=at, lang=Lang.en, channel=Channel.phone,
                slots={k: Slot(value=v) for k, v in slots.items()})


def test_summary_line() -> None:
    maria = make_case(level="undergrad", earned_monthly="900.00", other_cash_monthly="0.00", rent_share="1100.00")
    assert summary_line(maria) == "Undergrad · 1 person · work $900 · rent $1,100"
    jamal = make_case(level="undergrad", homeless="true", earned_monthly="0.00")
    assert summary_line(jamal) == "Undergrad · 1 person · no fixed home"
    family = make_case(level="grad", spouse="true", children_count="2", other_cash_monthly="300.00")
    assert summary_line(family) == "Grad · 4 people · cash $300"
    assert summary_line(make_case()) == ""


def test_case_summary_label_is_code() -> None:
    case = make_case(level="undergrad")
    s = case_summary(case)
    assert s.label == s.code == "K7Q-2FM" and s.found_display is None and s.yellow_open == 0


def test_clocks() -> None:
    clock = default_test_clock()
    assert clock.today() == date(2026, 10, 2)
    assert clock.now() == datetime(2026, 10, 2, 17, 0, tzinfo=UTC)
    late = FixedClock.pacific(2026, 10, 2, 23, 30)
    assert late.today() == date(2026, 10, 2) and late.now().date() == date(2026, 10, 3)
    m = late.monotonic()
    late.advance(seconds=90)
    assert late.monotonic() == m + 90 and late.now().minute == 31
    system = SystemClock()
    assert system.now().tzinfo is not None


def test_ids() -> None:
    ids = FixedIds(short_codes=["481206"], case_codes=["K7Q-2FM"])
    assert ids.short_code() == "481206" and re.fullmatch(r"\d{6}", ids.short_code())
    assert ids.case_code() == "K7Q-2FM" and re.fullmatch(CASE_CODE_PATTERN, ids.case_code())
    assert re.fullmatch(r"[a-f0-9]{32}", ids.call_id())
    assert re.fullmatch(r"c_[a-z2-7]{10}", ids.case_id())
    assert re.fullmatch(r"[A-Za-z0-9_-]{22}", ids.card_token())
    assert re.fullmatch(r"[A-Za-z0-9_-]{22,128}", ids.web_token())
    real = SystemIds()
    for _ in range(50):
        code = real.case_code()
        assert re.fullmatch(CASE_CODE_PATTERN, code) and not set(code) & set("0O1I")
    assert len(real.card_token()) == 22 and re.fullmatch(r"\d{6}", real.short_code())
    assert re.fullmatch(r"[a-f0-9]{32}", real.call_id())
