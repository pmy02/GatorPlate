"""Fakes of the ports the platform calls (rules, brain, card builder, programs, understanding) and a Deps builder on
the real stores. The platform is tested against these; the integrator runs the same API against the real modules.

The fake brain follows docs/BRAIN_API.md §4 (seq rules, stored replies, end) so the HTTP behavior can be tested end to
end; the fake programs port mirrors Maria's three card questions (docs/SPEC.md §6.6) with simple numbers.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from gatorplate.config import Settings
from gatorplate.contracts.brain_api import BrainReply, EndRequest, GatewayLines, StartRequest, TurnRequest
from gatorplate.contracts.card_api import CardBlock, CardStatus, CardView
from gatorplate.contracts.case import Case, EstimateRange, FirstMonth, TimelinePoint, Tracking, YellowLine
from gatorplate.contracts.common import CaseStatus, Lang, Tier, YellowKind
from gatorplate.contracts.console_api import LiveTurn
from gatorplate.contracts.console_text import PARENT_HOUSEHOLD_TEXT
from gatorplate.contracts.errors import Conflict, InvalidRequest, NotFound, StaleSeq, UnknownCall
from gatorplate.contracts.programs import (
    ProgramLine,
    ProgramsMeta,
    ProgramsResult,
    UnlockedChoice,
    UnlockedProgram,
    UnlockedQuestion,
    UnlockedView,
)
from gatorplate.contracts.rules_io import RulesMeta
from gatorplate.contracts.session import SessionState
from gatorplate.contracts.slots import SlotName, decode_value
from gatorplate.deps import Deps
from gatorplate.store import CaseStore, Database, EventBus, LiveStore, SessionStore

ROOT = Path(__file__).resolve().parents[2]
LINES_EN = json.loads((ROOT / "contracts" / "examples" / "lines_en.json").read_text(encoding="utf-8"))
EFFECTIVE_FROM = date(2026, 10, 1)
EFFECTIVE_TO = date(2027, 9, 30)


def _value(case: Case, name: SlotName) -> Any:
    slot = case.slots.get(name)
    return decode_value(name, slot.value) if slot is not None and slot.value is not None else None


class FakeRules:
    """Enough of RulesPort for the platform: parent-household routing with its yellow line, dorm meal plans to other
    help, everything else likely at $306 (a range $155-$306 while rent paid by others is unknown)."""

    def __init__(self) -> None:
        self.applied = 0

    def meta(self) -> RulesMeta:
        return RulesMeta(table_id="CA-CalFresh-FFY2027", label="Rules FY2027", effective_from=EFFECTIVE_FROM,
                         effective_to=EFFECTIVE_TO, sources=[])

    def valid_on(self, day: date) -> bool:
        return EFFECTIVE_FROM <= day <= EFFECTIVE_TO

    def apply(self, case: Case, *, now: datetime, turn: int | None = None) -> Case:
        self.applied += 1
        case = case.model_copy(deep=True)
        age = _value(case, SlotName.age)
        with_parent = _value(case, SlotName.lives_with_parent)
        lo = hi = None
        if with_parent is True and isinstance(age, int) and age < 22:
            case.tier, case.reason_code, case.estimate_monthly = Tier.coordinator, "coordinator.parent_household", None
            if not any(y.code == "coordinator.parent_household" for y in case.yellow_lines):
                case.yellow_lines.append(YellowLine(
                    id=f"y{len(case.yellow_lines) + 1}", slot=SlotName.lives_with_parent, kind=YellowKind.policy,
                    code="coordinator.parent_household", reason=PARENT_HOUSEHOLD_TEXT,
                    heard=case.slots[SlotName.lives_with_parent].heard, created_at=now))
        elif _value(case, SlotName.dorm_on_campus) is True:
            case.tier, case.reason_code, case.estimate_monthly = Tier.other_help, "other_help.dorm_meal_plan", None
        elif SlotName.earned_monthly in case.slots or SlotName.homeless in case.slots:
            if SlotName.rent_share in case.slots and SlotName.rent_paid_by_others_to_landlord not in case.slots:
                lo, hi = 155, 306
            else:
                lo, hi = 306, 306
            case.tier, case.reason_code, case.estimate_monthly = Tier.likely, "likely", 306
            case.estimate_range = EstimateRange(lo=lo, hi=hi, settled=lo == hi)
            day = now.astimezone(UTC).date()
            case.first_month = FirstMonth(apply_date=day, filed_on=day, amount=296, days_counted=29,
                                          month_label="October")
        else:
            case.tier = case.reason_code = case.estimate_monthly = None
        case.table_id = "CA-CalFresh-FFY2027"
        if turn is not None:
            case.timeline.append(TimelinePoint(turn=turn, at=now, slots=[], lo=lo, hi=hi))
        case.summary = case.summary or ""
        return case

    def compute_tracking(self, tracking: Tracking) -> Tracking:
        out = tracking.model_copy()
        if out.applied_at is not None:
            out.filed_on = out.applied_at
            out.deadline_30d = out.applied_at + timedelta(days=30)
        return out

    def filing_date(self, now: datetime) -> date:
        return now.date()


class FakePrograms:
    """ProgramsPort with Maria's three questions; values: CalFresh 12 x the estimate, transit +160 for most weekdays
    (Muni), tax_dependent "no" +220, a roommate's PG&E bill +170. Mode full for likely, list_only for coordinator and
    info routes, none otherwise."""

    QUESTIONS = {"break_transit": ["none", "two_days", "weekdays_muni", "weekdays_bart"],
                 "tax_dependent": ["no", "yes", "not_sure"],
                 "pge_bill": ["own_mine", "own_roommate", "in_rent", "not_sure"]}
    ORDER = ["break_transit", "tax_dependent", "pge_bill"]
    VALUE = {("break_transit", "weekdays_muni"): ("clipper_start", 160),
             ("tax_dependent", "no"): ("lifeline", 220),
             ("pge_bill", "own_roommate"): ("care", 170)}

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.calls = 0

    def _mode(self, case: Case) -> str | None:
        if not self.enabled or case.live or case.tier is None:
            return None
        if case.tier == Tier.likely:
            return "full"
        if case.tier == Tier.coordinator or (case.reason_code or "").startswith("info."):
            return "list_only"
        return None

    def evaluate(self, case: Case, *, today: date) -> ProgramsResult | None:
        self.calls += 1
        mode = self._mode(case)
        if mode is None:
            return None
        if mode == "list_only":
            line = ProgramLine(id="medi_cal", status="check", value_yearly=None, display_yearly=None, counted=False,
                               stage="today", order=1)
            return ProgramsResult(table_id="GP-Programs-2026", checked=EFFECTIVE_FROM, mode="list_only",
                                  calfresh_yearly=None, found_yearly=None, found_display=None, share_display=None,
                                  claimed_display=0, lines=[line], open_questions=[], next_question=None,
                                  question_spreads={}, console_notes=[])
        calfresh = 12 * (case.estimate_monthly or 0)
        lines = [ProgramLine(id="calfresh", status="likely", value_yearly=calfresh, display_yearly=calfresh // 10 * 10,
                             counted=True, stage="today", order=1,
                             applied=bool(case.program_progress.get("calfresh") and
                                          case.program_progress["calfresh"].applied))]
        for (question, choice), (program, value) in self.VALUE.items():
            answer = case.program_answers.get(question)
            if answer is not None and answer.value == choice:
                lines.append(ProgramLine(id=program, status="likely", value_yearly=value, display_yearly=value // 10 * 10,
                                         counted=True, stage="after_approval", order=len(lines) + 1))
        open_questions = [q for q in self.ORDER if q not in case.program_answers]
        found = sum(line.display_yearly or 0 for line in lines)
        claimed = sum(line.display_yearly or 0 for line in lines if line.applied)
        return ProgramsResult(table_id="GP-Programs-2026", checked=EFFECTIVE_FROM, mode="full", calfresh_yearly=calfresh,
                              found_yearly=sum(line.value_yearly or 0 for line in lines), found_display=found,
                              share_display=found // 100 * 100 or None, claimed_display=claimed, lines=lines,
                              open_questions=open_questions, next_question=open_questions[0] if open_questions else None,
                              question_spreads={q: 100 for q in open_questions}, console_notes=[])

    def view(self, case: Case, *, lang: Lang, today: date) -> UnlockedView | None:
        result = self.evaluate(case, today=today)
        if result is None:
            return None
        question = None
        if result.next_question:
            answered = len(case.program_answers)
            question = UnlockedQuestion(id=result.next_question, text=f"Question {result.next_question}",
                                        choices=[UnlockedChoice(value=c, label=c)
                                                 for c in self.QUESTIONS[result.next_question]],
                                        index=answered + 1, total=answered + len(result.open_questions))
        programs = [UnlockedProgram(id=line.id, name=line.id, status=line.status, status_label=line.status,
                                    value_text=f"About ${line.display_yearly}" if line.counted else None,
                                    counted=line.counted, line="line", notes=[], stage=line.stage, stage_label="Today",
                                    apply_by_text=None, apply_url="#today_action", apply_label="Apply",
                                    applied=line.applied, can_mark_applied=True, prefill=[], source_text="Source")
                    for line in result.lines]
        return UnlockedView(mode=result.mode, title="Money you may be missing",
                            total_text=f"About ${result.found_display} a year" if result.found_display else None,
                            found_display=result.found_display, claimed_display=result.claimed_display,
                            calfresh_display=(result.calfresh_yearly or 0) // 10 * 10 if result.mode == "full" else None,
                            segments=[(line.id, line.display_yearly or 0) for line in result.lines if line.counted],
                            question=question, chips=[], programs=programs,
                            share_text=f"about ${result.share_display}" if result.share_display else None,
                            footnote="Estimates. Each agency decides. Not a promise.", labels={}, lang=lang)

    def validate_answers(self, case: Case, answers: dict[str, str], *, today: date) -> dict[str, str]:
        result = self.evaluate(case, today=today)
        if result is None or result.mode != "full":
            raise InvalidRequest("No questions on this card.")
        for question, choice in answers.items():
            if question not in self.QUESTIONS or choice not in self.QUESTIONS[question]:
                raise InvalidRequest("Unknown question or choice.")
            if question not in result.open_questions and question not in case.program_answers:
                raise InvalidRequest("Question not open.")
        return dict(answers)

    def can_mark(self, case: Case, program: str, *, today: date) -> bool:
        result = self.evaluate(case, today=today)
        return result is not None and result.mode == "full" and program in {line.id for line in result.lines}

    def meta(self) -> ProgramsMeta | None:
        if not self.enabled:
            return None
        return ProgramsMeta(table_id="GP-Programs-2026", label="Programs 2026", checked=EFFECTIVE_FROM,
                            effective_from=EFFECTIVE_FROM, effective_to=EFFECTIVE_TO,
                            programs=["calfresh", "medi_cal"], names={"calfresh": "CalFresh"}, console_texts={},
                            questions=list(self.ORDER), sources=[])


class FakeCards:
    """CardBuilderPort: a small CardView whose `unlocked` part comes from the injected programs port."""

    def __init__(self, programs: Any) -> None:
        self.programs = programs

    def build(self, case: Case, *, lang: Lang, now: datetime, base_url: str) -> CardView:
        assert case.card is not None
        today = now.astimezone(UTC).date()
        return CardView(lang=lang, code=case.code, tier=case.tier, reason_code=case.reason_code,
                        headline="Headline", subhead="Estimate — the county decides.",
                        estimate_monthly=case.estimate_monthly, estimate_is_floor=case.estimate_is_floor,
                        expedited=case.expedited_possible, first_month=case.first_month,
                        blocks=[CardBlock(id="why", title="Why")], footer=[], sources=[], rules_label="Rules FY2027",
                        status=self.status(case), generated_at=now, expires_at=case.card.expires_at,
                        reminders_url=f"/api/card/{case.card.token}/reminders.ics"
                        if case.first_month or case.tracking.filed_on else None,
                        delete_url=f"/api/card/{case.card.token}",
                        unlocked=self.programs.view(case, lang=lang, today=today))

    def status(self, case: Case) -> CardStatus:
        return CardStatus(status=case.status, reviewed=case.status != CaseStatus.new and case.reviewed_at is not None,
                          reviewed_at=case.reviewed_at, tier=case.tier, estimate_monthly=case.estimate_monthly)

    def ics(self, case: Case, *, lang: Lang, now: datetime | None = None) -> str:
        # Like the real builder: the recorded application date, else the call's filing-date estimate, else 404.
        base = case.tracking.filed_on or (case.first_month.filed_on if case.first_month else None)
        if base is None:
            raise NotFound("This card has no filing day for calendar dates.")
        events = "".join(f"BEGIN:VEVENT\r\nUID:{i}@gatorplate\r\nDTSTART;VALUE=DATE:"
                         f"{(base + timedelta(days=d)).strftime('%Y%m%d')}\r\n"
                         f"SUMMARY:Reminder {i}\r\nEND:VEVENT\r\n" for i, d in enumerate((7, 20, 30), start=1))
        return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//GatorPlate//EN\r\n{events}END:VCALENDAR\r\n"


class FakeUnderstanding:
    def __init__(self, health: dict | None = None) -> None:
        self._health = health

    def llm_health(self) -> dict | None:
        return self._health

    async def understand(self, **kwargs: Any) -> Any:  # pragma: no cover - the fake brain never calls it
        raise NotImplementedError


def _reply(say: str, ask: str | None, *, lang: Lang, web: bool, end: bool = False, end_reason: str | None = None,
           interruptible: bool = True, card_url: str | None = None) -> BrainReply:
    return BrainReply(say=say, ask=ask, end=end, end_reason=end_reason, lang=lang, listen="normal",  # type: ignore[arg-type]
                      expect="yes_no" if ask else "open", interruptible=interruptible and not end, hold_s=0,
                      display=(say + (" " + ask if ask else "")) if web else None, choices=None,
                      card_url=card_url if web else None, debug=None)


class FakeBrain:
    """BrainPort following docs/BRAIN_API.md §4: a repeated /start returns the first reply; the same seq returns
    the stored reply; an older seq is stale; a gap is processed; after end:true a turn gets an empty closing reply;
    after /end a turn is a conflict; an unknown call is 404. The text "bye" ends the call."""

    def __init__(self, *, settings: Settings, clock: Any, ids: Any, cases: Any, sessions: Any, live: Any,
                 events: Any) -> None:
        self.settings, self.clock, self.ids = settings, clock, ids
        self.cases, self.sessions, self.live, self.events = cases, sessions, live, events
        self.processed: list[int] = []
        self.ended: list[str] = []

    def _live(self, case_id: str, turn: int, who: str, text: str, lang: Lang) -> None:
        if self.settings.live_transcript:
            line = LiveTurn(case_id=case_id, turn=turn, who=who, text=text, lang=lang, at=self.clock.now())  # type: ignore[arg-type]
            self.live.append(line)
            self.events.publish("live.turn", line=line)

    async def start(self, call_id: str, req: StartRequest) -> BrainReply:
        state = self.sessions.get(call_id)
        if state is not None and state.first_reply is not None:
            return state.first_reply
        now = self.clock.now()
        case = self.cases.create(Case(id=self.ids.case_id(), code=self.ids.case_code(), created_at=now,
                                      updated_at=now, lang=req.lang, channel=req.channel, test=req.test, live=True))
        web = req.channel.value == "web"
        reply = _reply("Hi, this is a test opening.", "Okay to start?", lang=req.lang, web=web, interruptible=False)
        self.sessions.put(SessionState(call_id=call_id, case_id=case.id, channel=req.channel, lang=req.lang,
                                       test=req.test, started_at=now, last_activity_at=now, first_reply=reply,
                                       last_reply=reply, last_seq=0))
        self.events.publish("case.created", case=case)
        self._live(case.id, 0, "assistant", reply.say, req.lang)
        return reply

    async def turn(self, call_id: str, req: TurnRequest) -> BrainReply:
        state = self.sessions.get(call_id)
        if state is None:
            raise UnknownCall("No such call.")
        if state.ended:
            raise Conflict("The call has ended.")
        if req.seq == state.last_seq and state.last_reply is not None and req.seq > 0:
            return state.last_reply
        if req.seq < state.last_seq:
            raise StaleSeq("seq is older than the last accepted turn.")
        web = state.channel.value == "web"
        lang = req.lang or state.lang
        if state.ended_by_brain:
            reply = BrainReply(say="", ask=None, end=True, end_reason=state.ended_by_brain, lang=lang,
                               listen="normal", expect="open", interruptible=False, hold_s=0,
                               display="" if web else None, choices=None, card_url=None, debug=None)
        elif (req.text or "").strip().lower() == "bye":
            reply = _reply("Goodbye.", None, lang=lang, web=web, end=True, end_reason="completed")
            state.ended_by_brain = "completed"
        else:
            reply = _reply("Got it.", "Next question?", lang=lang, web=web)
        self.processed.append(req.seq)
        state.last_seq, state.last_reply = req.seq, reply
        state.turn_count += 1
        state.last_activity_at = self.clock.now()
        self.sessions.put(state)
        case = self.cases.get(state.case_id)
        if case is not None:
            case.turn_count += 1
            saved = self.cases.save(case)
            self.events.publish("case.updated", case=saved)
            if req.text:
                self._live(case.id, req.seq, "student", req.text, lang)
            self._live(case.id, req.seq, "assistant", reply.say, lang)
        return reply

    async def end(self, call_id: str, req: EndRequest) -> None:
        state = self.sessions.get(call_id)
        if state is None:
            raise UnknownCall("No such call.")
        if state.ended:
            return
        state.ended = True
        self.sessions.put(state)
        self.ended.append(req.reason)
        case = self.cases.get(state.case_id)
        if case is not None and case.live:
            case.live = False
            case.ended_reason = req.reason
            saved = self.cases.save(case)
            self.live.wipe(case.id)
            self.events.publish("live.ended", case_id=case.id)
            self.events.publish("case.updated", case=saved)

    def lines(self, lang: Lang) -> GatewayLines:
        return GatewayLines.model_validate({**LINES_EN, "lang": lang.value})


def make_settings(tmp_db: Path, **overrides: Any) -> Settings:
    from pydantic import SecretStr

    base: dict[str, Any] = dict(env="test", llm_provider="fake", llm_api_key=SecretStr(""), debug_keys=True,
                                demo_mode=True, live_transcript=False, card_delivery="code", daily_reset=False,
                                db_path=tmp_db, public_base_url="http://127.0.0.1:8000", programs=True)
    base.update(overrides)
    return Settings(**base)


def make_deps(settings: Settings, *, clock: Any, ids: Any, programs: Any = None, rules: Any = None,
              brain: Any = None, understanding: Any = None) -> Deps:
    db = Database(settings.db_file)
    cases = CaseStore(db, clock=clock)
    sessions = SessionStore(db)
    live = LiveStore()
    events = EventBus(clock=clock, tz=settings.tz)
    programs = programs if programs is not None else FakePrograms(enabled=settings.programs)
    brain = brain or FakeBrain(settings=settings, clock=clock, ids=ids, cases=cases, sessions=sessions, live=live,
                               events=events)
    return Deps(settings=settings, clock=clock, ids=ids, rules=rules or FakeRules(),
                understanding=understanding or FakeUnderstanding(), brain=brain, cases=cases, sessions=sessions,
                live=live, events=events, cards=FakeCards(programs), programs=programs)
