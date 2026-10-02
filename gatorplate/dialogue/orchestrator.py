"""Brain (BrainPort): per-call locks, seq rules, stored replies, deadlines, rendering, persistence and events.

docs/BRAIN_API.md §4: a repeated /start returns the stored first reply; the same seq as the last accepted turn returns
the identical stored reply (bodies are not compared); an older seq is 409 stale_seq; gaps are accepted; after the brain
sent end:true a new turn gets an empty closing reply; after /end a turn is 409 conflict; an unknown call is 404. One
asyncio.Lock per call keeps requests in arrival order (an /end that arrives during /start is applied after it).

Nothing here writes request or reply text to the logs. Short-term memory (the last two redacted utterances) and the
live transcript live in process memory only.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from gatorplate.contracts.brain_api import (
    BrainReply,
    EndRequest,
    GatewayLines,
    ReplyDebug,
    StartRequest,
    TurnRequest,
)
from gatorplate.contracts.case import AskedQuestion, Case
from gatorplate.contracts.common import Channel, Lang, Phase, SlotSource
from gatorplate.contracts.console_api import LiveTurn
from gatorplate.contracts.errors import Conflict, StaleSeq, UnknownCall
from gatorplate.contracts.extraction import ExtractOutcome, Intent, PendingQuestion, Understanding
from gatorplate.contracts.session import SessionState
from gatorplate.contracts.slots import SlotName
from gatorplate.dialogue import machine, verbalize, yellow
from gatorplate.dialogue.budget import CONTACT_WORDS, WORD_BUDGETS, budget_class, count_words, split_point
from gatorplate.dialogue.intents import Routing
from gatorplate.dialogue.lines import gateway_lines
from gatorplate.dialogue.output_guard import OutputGuard
from gatorplate.dialogue.policy import Ctx, Dialogue, Plan, forget_unconsented, outcome, value_of
from gatorplate.dialogue.templates import Bank, Rendered, Renderer, Step, fill

IDLE_TIMEOUT = timedelta(minutes=10)  # docs/BRAIN_API.md §4: an idle call is closed as a timeout
MEMORY_TURNS = 2  # short-term memory: the last two redacted utterances
LLM_FAILED = frozenset({"timeout", "error", "refused", "invalid"})
NON_INTERRUPTIBLE_KEYS = frozenset({"result.likely", "result.likely_floor", "card.phone_code", "crisis.resources"})
CHOICE_MAX = 6


class Brain:
    def __init__(self, *, settings: Any, clock: Any, ids: Any, rules: Any, understanding: Any, cases: Any,
                 sessions: Any, live: Any, events: Any, cards: Any, content_dir: Path | None = None) -> None:
        self.settings = settings
        self.clock = clock
        self.ids = ids
        self.rules = rules
        self.understanding = understanding
        self.cases = cases
        self.sessions = sessions
        self.live = live
        self.events = events
        self.cards = cards
        self.content_dir = content_dir or settings.content_dir
        self.bank = Bank(self.content_dir)
        guards_path = self.content_dir / "guards.json"
        self.routing = Routing(guards_path)
        self.guard = OutputGuard(guards_path)
        table = json.loads(Path(settings.rules_table_path).read_text(encoding="utf-8"))
        self.policy = Dialogue(bank=self.bank, routing=self.routing, rules=rules, table=table, ids=ids, cases=cases)
        self.renderer = Renderer(self.bank, self._values_unbound)
        self._locks: dict[str, asyncio.Lock] = {}
        self._memory: dict[str, deque[str]] = {}
        self._ctx: Ctx | None = None
        self.metrics: dict[str, int] = {"guard_hits": 0, "llm_failures": 0}

    # ======================================================================================== BrainPort

    def lines(self, lang: Lang) -> GatewayLines:
        return gateway_lines(self.bank, Lang(lang))

    async def start(self, call_id: str, req: StartRequest) -> BrainReply:
        async with self._lock(call_id):
            existing = self.sessions.get(call_id)
            if existing is not None and existing.first_reply is not None:
                return existing.first_reply
            now = self.clock.now()
            channel = Channel(req.channel)
            lang = Lang.en if channel == Channel.phone else Lang(req.lang)
            case = Case(id=self.ids.case_id(), code=self.ids.case_code(), created_at=now, updated_at=now, lang=lang,
                        channel=channel, test=req.test, live=True, phase=Phase.consent)
            session = SessionState(call_id=call_id, case_id=case.id, channel=channel, lang=lang, test=req.test,
                                   started_at=now, last_activity_at=now, closed_mode=not self._model_available())
            if session.closed_mode:
                case.flags.append("closed_mode")
            ctx = self._context(call_id, case, session, now)
            plan = self.policy.start(ctx)
            reply, rendered, question = self._finish(ctx, plan, start=True)
            case.phase = session.phase
            case = self.cases.create(case)
            session.first_reply = reply
            session.last_reply = reply
            session.last_keys = rendered.keys
            self.sessions.put(session)
            self.events.publish("case.created", case=case, now_asking=question.key if question else None,
                                now_asking_text=self._english_question(ctx, question), asked_reason=None)
            self._live_lines(ctx, None, reply, question)
            return reply

    async def turn(self, call_id: str, req: TurnRequest) -> BrainReply:
        async with self._lock(call_id):
            session = self.sessions.get(call_id)
            if session is None:
                raise UnknownCall("No such call.")
            now = self.clock.now()
            if session.ended:
                raise Conflict("The call has ended.")
            if now - session.last_activity_at > IDLE_TIMEOUT:
                self._close(session, "timeout", now)
                raise Conflict("The call has ended.")
            if req.seq == session.last_seq and session.last_reply is not None:
                return session.last_reply
            if req.seq < session.last_seq:
                raise StaleSeq("seq is older than the last accepted turn.")
            if session.ended_by_brain is not None or self.cases.get(session.case_id) is None:
                reply = self._closing_reply(session)
                session.last_seq = req.seq
                session.last_reply = reply
                session.last_keys = []
                session.last_activity_at = now
                self.sessions.put(session)
                return reply
            case = self.cases.get(session.case_id)
            assert case is not None
            if req.event in ("utterance", "dtmf"):
                session.turn_count += 1
                case.turn_count = session.turn_count
            if session.channel == Channel.web and req.lang is not None and Lang(req.lang) != session.lang:
                session.lang = Lang(req.lang)
                case.lang = session.lang
            session.last_activity_at = now
            ctx = self._context(call_id, case, session, now)
            student_text, plan = await self._decide(ctx, req)
            reply, rendered, question = self._finish(ctx, plan)
            session.last_seq = req.seq
            if not plan.repeat:
                session.last_reply = reply
                session.last_keys = rendered.keys
            if not plan.delete_case:  # the lines reach the console before the case update that they explain
                self._live_lines(ctx, student_text, reply, question)
            self._persist(ctx, plan, question)
            if reply.end:  # nothing more to understand: short-term memory goes now, not at /end
                self._memory.pop(call_id, None)
            self.sessions.put(session)
            return reply

    async def end(self, call_id: str, req: EndRequest) -> None:
        async with self._lock(call_id):
            session = self.sessions.get(call_id)
            if session is None:
                raise UnknownCall("No such call.")
            if session.ended:
                return None
            self._close(session, req.reason, self.clock.now())
            return None

    # ======================================================================================== one turn

    async def _decide(self, ctx: Ctx, req: TurnRequest) -> tuple[str | None, Plan]:
        """The plan for one turn event, and the redacted student text for the live transcript (None = not shown)."""
        s = ctx.session
        if req.event == "silence":
            return None, self.policy.silence(ctx, int(req.silence_n or 1))
        if req.event == "dtmf":
            return None, self.policy.keypad(ctx, str(req.dtmf or ""))
        text = req.text or ""
        choice = self._quick_reply(ctx, text) if req.typed else None
        if choice is not None:
            return text, self.policy.apply_entry(ctx, choice, source=SlotSource.parser)
        if not text.strip():
            if s.deferred_keys:
                return None, self.policy.deliver_deferred(ctx)
            return None, self.policy.unclear(ctx)
        u = await self._understand(ctx, req)
        failed = u.llm.status in LLM_FAILED
        if failed:
            s.llm_failures += 1
            self.metrics["llm_failures"] += 1
            if s.llm_failures >= 2:
                s.closed_mode = True
                if "closed_mode" not in ctx.case.flags:
                    ctx.case.flags.append("closed_mode")
        elif u.llm.status == "ok":
            s.llm_failures = 0
        intents = {i.value for i in u.intents} | {i.value for i in u.keyword_intents}
        crisis = Intent.crisis.value in intents
        redacted = bool(u.redactions) or req.masked
        status_said = any(o.slot == SlotName.volunteered_status for o in u.observations)
        if req.interrupted and not u.observations and intents <= {Intent.repeat.value} and not s.deferred_keys \
                and s.phase != Phase.consent:
            question = self.policy._pending_step(ctx, "main")
            if question is not None:
                plan = Plan([Step("reprompt.after_interrupt", question=question)],
                            record=self.policy._reask_kind(ctx, question))
                return u.redacted_text, plan
        if failed and not u.observations and not (intents - {Intent.off_topic.value}) and not s.deferred_keys \
                and s.phase != Phase.consent:
            question = self.policy._pending_step(ctx, "closed")
            if question is not None:
                return u.redacted_text, Plan([question], record="closed")
        if not u.observations and not intents and not s.deferred_keys and s.last_reply is not None \
                and s.last_reply.ask is None and not s.last_reply.end and s.phase != Phase.consent:
            # the last reply asked nothing (hold, the Spanish notice): ask the question again, normally
            question = self.policy._pending_step(ctx, "main")
            if question is not None:
                return u.redacted_text, Plan([Step("ack.short"), question])
        plan = self.policy.utterance(ctx, u, masked=req.masked, interrupted=req.interrupted,
                                     confidence=req.confidence, text=u.redacted_text or text)
        memory = self._memory.setdefault(ctx.call_id, deque(maxlen=MEMORY_TURNS))
        if not (crisis or redacted or status_said or plan.drop_from_memory):
            memory.append(u.redacted_text)
        shown = None if (crisis or status_said or plan.drop_from_memory) else u.redacted_text
        return shown, plan

    async def _understand(self, ctx: Ctx, req: TurnRequest) -> Understanding:
        s = ctx.session
        budget = float(getattr(self.settings, "turn_budget_s", 2.6))
        deadline = self.clock.monotonic() + budget
        known = {slot: item.value for slot, item in ctx.case.slots.items() if item.value is not None}
        last = s.last_reply
        last_prompt = (last.ask or last.say or None) if last is not None else None
        recent = list(self._memory.get(ctx.call_id, ()))
        try:
            return await asyncio.wait_for(
                self.understanding.understand(
                    text=req.text or "", masked=req.masked, confidence=req.confidence, dtmf=None, pending=s.pending,
                    known=known, recent=recent, last_prompt=last_prompt, lang=s.lang, deadline=deadline,
                    closed_mode=s.closed_mode),
                timeout=budget)
        except TimeoutError:
            return Understanding(redacted_text="", observations=[], intents=[], lang=s.lang, answered_pending="no",
                                 llm=ExtractOutcome(status="timeout"))
        except Exception:  # noqa: BLE001 - a failing understanding is a model failure: the closed question follows
            # nothing from this text is kept (it was never redacted), so the live transcript shows nothing either
            return Understanding(redacted_text="", observations=[], intents=[], lang=s.lang, answered_pending="no",
                                 llm=ExtractOutcome(status="error"))

    def _quick_reply(self, ctx: Ctx, text: str) -> dict[str, Any] | None:
        """A web quick reply: the typed text equals a choice label of the pending question."""
        pending = ctx.session.pending
        if pending is None:
            return None
        expect = self.bank.expect(pending.key, "closed" if pending.closed else "main", ctx.lang) or {}
        wanted = " ".join(text.split()).casefold()
        for choice in expect.get("choices") or []:
            label = self._choice_label(ctx, pending.key, choice)
            if label.casefold() == wanted:
                return {k: v for k, v in choice.items() if k != "label"}
        return None

    # ======================================================================================== rendering

    def _finish(self, ctx: Ctx, plan: Plan, *, start: bool = False) -> tuple[BrainReply, Rendered, Step | None]:
        """Render the plan, keep it within the phone word budget, run the output guard, update the pending question
        and the case's asked list."""
        s, case = ctx.session, ctx.case
        if plan.repeat and s.last_reply is not None:
            return s.last_reply, self._rendered_from(s.last_keys), None
        lang = plan.reply_lang or s.lang
        steps = list(plan.steps)
        rendered = self._render(ctx, steps, lang)
        if ctx.channel == Channel.phone and not start:
            steps, rendered = self._fit(ctx, steps, lang, rendered)
        texts = [rendered.say, rendered.ask, rendered.display_say, rendered.display_ask]
        choices = self._choices(ctx, rendered) if ctx.channel == Channel.web else None
        if self.guard.blocked(texts + list(choices or [])):
            self.metrics["guard_hits"] += 1
            if "guard_hit" not in case.flags:
                case.flags.append("guard_hit")
            # the caller persists this same plan object: the blocked reply neither ends the call nor records a
            # question (a requested deletion still happens)
            plan.steps = [Step("error.generic")]
            plan.end_reason, plan.hold_s, plan.reply_lang = None, 0, None
            plan.keep_pending, plan.record, plan.flip = True, None, None
            steps = plan.steps
            s.deferred_keys = []
            rendered = self._render(ctx, steps, lang)
            choices = None
        end = plan.end_reason is not None
        question = rendered.question if rendered.ask is not None and not end else None
        expect = rendered.expect if question is not None else None
        interruptible = not (start or end or self._holds_contact(rendered.keys, rendered.say, ctx.channel))
        listen = str((expect or {}).get("listen") or "normal")
        if plan.hold_s:
            listen = "long"
        display = None
        if ctx.channel == Channel.web:
            display = " ".join(p for p in (rendered.display_say, rendered.display_ask or "") if p) or rendered.say
        card_url = f"/c/{case.card.token}" if ctx.channel == Channel.web and case.card is not None \
            and not plan.delete_case else None  # a deleted case has no card to open
        debug = ReplyDebug(keys=rendered.keys, phase=s.phase.value) if getattr(self.settings, "debug_keys", False) \
            else None
        reply = BrainReply(
            say=rendered.say, ask=None if end else rendered.ask, end=end, end_reason=plan.end_reason, lang=lang,
            listen=listen if not end else "normal", expect=str((expect or {}).get("expect") or "open"),
            interruptible=interruptible, hold_s=plan.hold_s if not end else 0, display=display,
            choices=(choices or None) if question is not None else None, card_url=card_url, debug=debug)
        if end:
            s.ended_by_brain = plan.end_reason  # type: ignore[assignment]
            s.pending = None
            s.phase = Phase.end
            s.deferred_keys = []
        elif question is not None:
            s.pending = self._pending(ctx, question, expect)
            self._record_asked(ctx, plan, question)
        elif not plan.keep_pending and not s.deferred_keys:
            s.pending = None if s.phase in (Phase.end,) else s.pending
        return reply, rendered, question

    def _render(self, ctx: Ctx, steps: list[Step], lang: Lang) -> Rendered:
        self._ctx = ctx
        rendered = self.renderer.render(steps, lang, ctx.channel, call_id=ctx.call_id, turn=ctx.turn)
        if ctx.channel == Channel.phone:  # the phone says the name as verbalize.PHONE_SPOKEN_NAME, before word budgets
            rendered.say = verbalize.name_spoken(rendered.say)
            rendered.ask = verbalize.name_spoken(rendered.ask) if rendered.ask is not None else None
        return rendered

    def _fit(self, ctx: Ctx, steps: list[Step], lang: Lang, rendered: Rendered) -> tuple[list[Step], Rendered]:
        """Phone budgets: drop flip.intro when it does not fit (docs/SPEC.md §3.2 phase 6), then split at a key
        boundary; the rest is delivered on the next request."""
        def spoken(r: Rendered) -> str:
            return " ".join(p for p in (r.say, r.ask or "") if p)

        if any(st.key == "flip.intro" for st in steps):
            if count_words(spoken(rendered)) > WORD_BUDGETS[budget_class(rendered.keys, spoken(rendered))]:
                steps = [st for st in steps if st.key != "flip.intro"]
                rendered = self._render(ctx, steps, lang)

        def prefix(k: int) -> tuple[list[str], str]:
            r = self._render(ctx, steps[:k], lang)
            return r.keys, spoken(r)

        k = split_point(len(steps), prefix)
        if k < len(steps):
            ctx.session.deferred_keys = [st.encode() for st in steps[k:]]
            steps = steps[:k]
            rendered = self._render(ctx, steps, lang)
            rendered.ask = None
            rendered.display_ask = None
            rendered.question = None
        return steps, rendered

    def _rendered_from(self, keys: list[str]) -> Rendered:
        return Rendered(keys=list(keys), say="", ask=None, display_say="", display_ask=None, question=None, expect=None)

    def _holds_contact(self, keys: list[str], say: str, channel: Channel) -> bool:
        """Replies with an amount, a card code, a phone number or crisis resources are heard in full."""
        if any(k in NON_INTERRUPTIBLE_KEYS or k.startswith("result.") for k in keys):
            return True
        for key in keys:
            if any(kind in ("phone", "code") for kind in self.bank.var_types(key).values()):
                return True
        return channel == Channel.phone and bool(CONTACT_WORDS.search(say))

    def _choices(self, ctx: Ctx, rendered: Rendered) -> list[str] | None:
        question = rendered.question
        if question is None or rendered.expect is None:
            return None
        labels = [self._choice_label(ctx, question.key, c) for c in rendered.expect.get("choices") or []]
        labels = [label[:60] for label in labels if label][:CHOICE_MAX]
        return labels or None

    def _choice_label(self, ctx: Ctx, key: str, choice: dict[str, Any]) -> str:
        label = str(choice.get("label") or "")
        if "{" in label:
            values = self._values(ctx, Step(key), "display", ctx.lang)
            try:
                label = fill(label, values)
            except KeyError:
                return ""
        return label

    def _pending(self, ctx: Ctx, question: Step, expect: dict[str, Any] | None) -> PendingQuestion:
        expect = expect or {}
        slots: list[SlotName] = []
        if question.key == "confirm.money" and question.vars.get("slot"):
            slots = [SlotName(question.vars["slot"])]
        else:
            for name in expect.get("slots") or []:
                try:
                    slots.append(SlotName(name))
                except ValueError:
                    continue
        kind = str(expect.get("expect") or "open")
        # labels with their numbers filled in ("Under $1,000"): the understanding reads band edges from them
        choices = [label for c in expect.get("choices") or [] if (label := self._choice_label(ctx, question.key, c))]
        choices = choices or None
        return PendingQuestion(key=question.key, slots=slots, kind=kind, choices=choices,  # type: ignore[arg-type]
                               closed=question.form == "closed")

    def _record_asked(self, ctx: Ctx, plan: Plan, question: Step) -> None:
        """Case questions go into Case.asked (docs/UI_SPEC.md A3.10): standard, flip (with its reason), confirm, band,
        closed and reprompt; the conversation's own questions (consent, crisis, delete, keep going, close) do not."""
        case = ctx.case
        if plan.record is None or not question.key.startswith(machine.CASE_QUESTION_PREFIXES):
            return
        kind = plan.record
        if question.key in machine.BAND_KEYS and kind == "standard":
            kind = "band"
        if question.form == "closed" and kind == "standard":
            kind = "closed"
        last = case.asked[-1] if case.asked else None
        if last is not None and last.key == question.key and last.turn == ctx.turn and last.kind == kind:
            return
        slots = list(ctx.session.pending.slots) if ctx.session.pending else []
        entry = AskedQuestion(turn=ctx.turn, key=question.key, slots=slots, kind=kind)  # type: ignore[arg-type]
        if plan.flip is not None:
            entry.reason = plan.flip.reason
            entry.delta_usd = plan.flip.spread_usd
            entry.outcomes = [o.label for o in plan.flip.outcomes]
        elif kind == "flip":
            earlier = [a for a in case.asked if a.kind == "flip" and set(a.slots) & set(slots)]
            if earlier:
                entry.reason, entry.delta_usd, entry.outcomes = earlier[-1].reason, earlier[-1].delta_usd, list(
                    earlier[-1].outcomes)
        case.asked.append(entry)

    # ---------------------------------------------------------------------------------------- vars

    def _values_unbound(self, step: Step, mode: str, lang: Lang) -> dict[str, str]:
        assert self._ctx is not None
        return self._values(self._ctx, step, mode, lang)

    def _values(self, ctx: Ctx, step: Step, mode: str, lang: Lang) -> dict[str, str]:
        out: dict[str, str] = {}
        types = self.bank.var_types(step.key)
        names = set(types)
        if step.key in ("ask.income_band", "flip.other_cash_band"):
            names |= {"a", "b"}
        for name in names:
            if name == "question":
                continue
            kind = types.get(name, "money")
            out[name] = self._format(ctx, step, name, kind, mode, lang)
        return out

    def _format(self, ctx: Ctx, step: Step, name: str, kind: str, mode: str, lang: Lang) -> str:
        spoken = mode == "spoken"
        base = str(getattr(self.settings, "public_base_url", "") or "")
        if name in ("coordinator_phone", "county_phone"):
            entry = self.bank.contact("coordinator" if name == "coordinator_phone" else "county")
            return str(entry["spoken"][lang.value] if spoken else entry["display"])
        if name == "coordinator_hours":
            hours = self.bank.contact("coordinator.hours")
            return str(hours["spoken" if spoken else "text"][lang.value])
        if name in ("talk_url", "short_url"):
            path = "/talk" if name == "talk_url" else "/go"
            return verbalize.url_spoken(base, path, lang) if spoken else verbalize.url_display(base, path)
        if name == "code":
            code = (ctx.case.card.short_code if ctx.case.card is not None else None) or ""
            return verbalize.digits_spoken(code, lang) if spoken else verbalize.code_display(code)
        if name == "period":
            return self.bank.spoken_period(self._confirm_period(ctx, step), lang)
        if name == "hours":
            basis = self._earned_basis(ctx)
            hours = basis.hours_per_week if basis is not None and basis.hours_per_week is not None else Decimal(0)
            return verbalize.number_words(hours, lang) if spoken else verbalize.number_display(hours)
        raw = step.vars.get(name)
        amount: Decimal | None = Decimal(str(raw)) if raw is not None and name != "slot" else None
        cents = False
        if amount is None:
            amount, cents = self._amount(ctx, step, name)
        if spoken:
            return verbalize.money_words(amount, lang, cents=cents)
        return verbalize.money_display(amount, cents=cents)

    def _amount(self, ctx: Ctx, step: Step, name: str) -> tuple[Decimal, bool]:
        case = ctx.case
        key = step.key
        if name in ("a", "b"):
            a, b = self.policy.band_edges(ctx, key)
            return (a if name == "a" else b), False
        if name == "x":
            return self.policy._earned_split(ctx), False
        if name == "rate":
            basis = self._earned_basis(ctx)
            return (basis.amount if basis is not None else Decimal(0)), True
        if key in ("result.likely", "result.likely_floor"):
            return Decimal(case.estimate_monthly or 0), False
        slot = {"readback.earned": SlotName.earned_monthly, "readback.rent": SlotName.rent_share,
                "readback.other_cash": SlotName.other_cash_monthly, "readback.cash": SlotName.cash_on_hand}.get(key)
        if key == "confirm.money":
            slot = SlotName(step.vars.get("slot") or (ctx.session.pending.slots[0].value if ctx.session.pending
                                                      and ctx.session.pending.slots else "earned_monthly"))
            item = case.slots.get(slot)
            if item is not None and item.basis is not None and item.basis.period not in ("month",):
                return item.basis.amount, item.basis.period == "hour"
        if slot is not None:
            value = value_of(case, slot)
            return (Decimal(value) if value is not None else Decimal(0)), False
        return Decimal(0), False

    def _confirm_period(self, ctx: Ctx, step: Step) -> str:
        slot_name = step.vars.get("slot")
        if slot_name:
            item = ctx.case.slots.get(SlotName(slot_name))
            if item is not None and item.basis is not None:
                return item.basis.period
        return "month"

    def _earned_basis(self, ctx: Ctx):
        item = ctx.case.slots.get(SlotName.earned_monthly)
        return item.basis if item is not None else None

    def _english_question(self, ctx: Ctx, question: Step | None) -> str | None:
        """The question in English for the console (now_asking_text)."""
        if question is None:
            return None
        try:
            r = self._render(ctx, [Step(question.key, question.form, vars=dict(question.vars))], Lang.en)
        except KeyError:
            return None
        return r.ask or r.say or None

    # ======================================================================================== persistence

    def _context(self, call_id: str, case: Case, session: SessionState, now: datetime) -> Ctx:
        return Ctx(call_id=call_id, case=case, session=session, now=now, today=self.clock.today(),
                   turn=session.turn_count, channel=session.channel, settings=self.settings,
                   outcome_before=outcome(case))

    def _persist(self, ctx: Ctx, plan: Plan, question: Step | None) -> None:
        case, s = ctx.case, ctx.session
        if plan.delete_case:
            self.cases.delete(case.id)
            self.events.publish("case.deleted", case_id=case.id)
            self._wipe_live(case.id)
            return
        case.phase = s.phase
        case.updated_at = ctx.now
        case.turn_count = s.turn_count
        if plan.end_reason is not None:
            case.ended_reason = plan.end_reason
        saved = self.cases.save(case)
        if isinstance(saved, Case):
            ctx.case = saved
        reason = None
        if question is not None and question.key.startswith("flip."):
            asked = [a for a in ctx.case.asked if a.key == question.key and a.reason]
            reason = plan.flip.reason if plan.flip is not None else (asked[-1].reason if asked else None)
        self.events.publish("case.updated", case=ctx.case, changed_slots=list(ctx.changed),
                            now_asking=question.key if question else None,
                            now_asking_text=self._english_question(ctx, question), asked_reason=reason)

    def _close(self, session: SessionState, reason: str, now: datetime) -> None:
        """/end (or the idle timeout): the case is no longer live; before a result it is incomplete."""
        session.ended = True
        session.last_activity_at = now
        case = self.cases.get(session.case_id)
        if case is not None:
            case.live = False
            case.updated_at = now
            case.ended_reason = case.ended_reason or session.ended_by_brain or reason
            if case.consent.given is not True:  # no consent: nothing said in the call is kept
                forget_unconsented(case)
            elif session.phase in machine.BEFORE_RESULT:
                case.ended_early = True
                yellow.incomplete(case, now)
                try:  # no result before the end: the rules clear the tier and the estimate
                    updated = self.rules.apply(case, now=now, turn=None)
                    if isinstance(updated, Case):
                        case = updated
                except Exception:  # noqa: BLE001 - the end of a call never fails on the rules
                    self.policy.rules_errors += 1
            if session.phase != Phase.end:
                case.phase = session.phase
            saved = self.cases.save(case)
            self.events.publish("case.updated", case=saved if isinstance(saved, Case) else case)
            self._wipe_live(case.id)
        self._memory.pop(session.call_id, None)
        self.sessions.put(session)

    def _closing_reply(self, session: SessionState) -> BrainReply:
        """After the brain ended the call: an empty closing reply. On the web the card link stays set
        (docs/BRAIN_API.md §6: once set, card_url stays set in every later reply of the call)."""
        debug = ReplyDebug(keys=[], phase=Phase.end.value) if getattr(self.settings, "debug_keys", False) else None
        card_url = None
        if session.channel == Channel.web:
            case = self.cases.get(session.case_id)
            if case is not None and case.card is not None:
                card_url = f"/c/{case.card.token}"
        return BrainReply(say="", ask=None, end=True, end_reason=session.ended_by_brain or "completed",
                          lang=session.lang, listen="normal", expect="open", interruptible=False, hold_s=0,
                          display="" if session.channel == Channel.web else None, choices=None,
                          card_url=card_url, debug=debug)

    # ---------------------------------------------------------------------------------------- live transcript

    def _live_on(self) -> bool:
        return bool(getattr(self.settings, "live_transcript", False)) and self.live is not None

    def _live_lines(self, ctx: Ctx, student: str | None, reply: BrainReply, question: Step | None) -> None:
        if not self._live_on() or ctx.case is None:
            return
        case_id = ctx.case.id
        lines: list[LiveTurn] = []
        if student:
            lines.append(LiveTurn(case_id=case_id, turn=ctx.turn, who="student", text=student,
                                  lang=ctx.session.lang, at=ctx.now))
        text = reply.display if reply.display else " ".join(p for p in (reply.say, reply.ask or "") if p)
        if text and ctx.channel == Channel.phone:  # the screen keeps the display name, not the spoken form
            text = verbalize.name_display(text)
        if text:
            lines.append(LiveTurn(case_id=case_id, turn=ctx.turn, who="assistant", text=text, lang=reply.lang,
                                  at=ctx.now))
        for line in lines:  # memory only, and an SSE `live.turn` event that the bus never buffers or replays
            self.live.append(line)
            self.events.publish("live.turn", case_id=case_id, line=line)
        reason = None
        if question is not None and ctx.case.asked and ctx.case.asked[-1].key == question.key:
            reason = ctx.case.asked[-1].reason
        self.live.set_now_asking(case_id, key=question.key if question else None,
                                 text=self._english_question(ctx, question), reason=reason)

    def _wipe_live(self, case_id: str) -> None:
        if self._live_on():
            self.live.wipe(case_id)
            self.events.publish("live.ended", case_id=case_id)

    def _model_available(self) -> bool:
        """False when the understanding has no language-model client (no key): every call then runs in closed mode
        (docs/SPEC.md §3.7). The port has no such method, so a missing hint means the model is available."""
        health = getattr(self.understanding, "llm_health", None)
        if callable(health):
            try:
                if (health() or {}).get("status") == "no_key":
                    return False
            except Exception:  # noqa: BLE001 - a health probe never blocks a call
                return True
        return getattr(self.understanding, "llm", True) is not None

    def _lock(self, call_id: str) -> asyncio.Lock:
        lock = self._locks.get(call_id)
        if lock is None:
            lock = self._locks[call_id] = asyncio.Lock()
        return lock

