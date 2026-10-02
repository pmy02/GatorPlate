"""Student card API (docs/UI_SPEC.md A8.2-A8.3, docs/SPEC.md §6): public by its unguessable token; 404 for an
unknown token, 410 once the card expired.

The two card programs endpoints (`/answers`, `/progress`; docs/SPEC.md §6.6) are not part of the Brain API. They store
the student's taps on the case (`program_answers`, `program_progress`), never a CalFresh slot, bump the case version
like any save, publish `case.updated` with `changed_programs: true` and answer the re-planned UnlockedView. They share
one bucket of 30 requests a minute per card token. With GP_PROGRAMS=0, or when the case has no programs part, they
answer 404.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError

from gatorplate.api.context import AppContext
from gatorplate.api.errors import ApiProblem, read_body
from gatorplate.contracts.case import Case, ProgramAnswer, ProgramProgress
from gatorplate.contracts.common import Lang
from gatorplate.contracts.console_api import CardLookup, CardLookupResponse
from gatorplate.contracts.errors import InvalidRequest, VersionConflict
from gatorplate.contracts.programs import ProgramAnswersRequest, ProgramProgressRequest

router = APIRouter()
log = logging.getLogger("gatorplate.api")


def _ctx(request: Request) -> AppContext:
    return request.app.state.ctx


async def _body[M: BaseModel](request: Request, model: type[M]) -> M:
    try:
        return model.model_validate_json(await read_body(request))
    except (ValidationError, ValueError) as exc:
        raise ApiProblem("invalid_request") from exc


def _lang(value: str | None, default: Lang) -> Lang:
    if value in (None, ""):
        return default
    try:
        return Lang(value)
    except ValueError as exc:
        raise ApiProblem("invalid_request", "Unsupported lang.") from exc


def _card_case(ctx: AppContext, token: str, *, allow_expired: bool = False) -> Case:
    case = ctx.deps.cases.get_by_card_token(token) if token else None
    if case is None or case.card is None:
        raise ApiProblem("not_found", "No such card.")
    if not allow_expired and case.card.expires_at <= ctx.now():
        raise ApiProblem("gone", "This card has expired.")
    return case


def _json(model: BaseModel) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"))


# ---------------------------------------------------------------------------------------------- card


@router.get("/api/card/{token}")
async def get_card(token: str, request: Request, lang: str | None = None) -> JSONResponse:
    ctx = _ctx(request)
    case = _card_case(ctx, token)
    language = _lang(lang, case.lang)
    view = ctx.deps.cards.build(case, lang=language, now=ctx.now(), base_url=ctx.settings.public_base_url)
    if not ctx.settings.programs and view.unlocked is not None:
        view = view.model_copy(update={"unlocked": None})
    return _json(view)


@router.get("/api/card/{token}/status")
async def card_status(token: str, request: Request) -> JSONResponse:
    ctx = _ctx(request)
    return _json(ctx.deps.cards.status(_card_case(ctx, token)))


@router.get("/api/card/{token}/reminders.ics")
async def reminders(token: str, request: Request, lang: str | None = None) -> Response:
    """The three calendar dates (docs/SPEC.md §6.3). The card builder decides the filing day — the application date
    the coordinator recorded, else the filing-date estimate — and raises NotFound (404) when there is none, the same
    rule that sets `CardView.reminders_url`. The dates follow the estimate the card shows today (`now`); the file
    name never calls them reminders (docs/SPEC.md §6.3)."""
    ctx = _ctx(request)
    case = _card_case(ctx, token)
    language = _lang(lang, case.lang)
    text = ctx.deps.cards.ics(case, lang=language, now=ctx.now())
    return Response(content=text.encode("utf-8"), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="gatorplate-dates.ics"'})


@router.delete("/api/card/{token}")
async def delete_card(token: str, request: Request) -> JSONResponse:
    """The student's own delete: the case and its card go at once, with the card answers and marks."""
    ctx = _ctx(request)
    case = _card_case(ctx, token, allow_expired=True)
    ctx.deps.cases.delete(case.id)
    ctx.deps.live.wipe(case.id)
    ctx.deps.events.publish("case.deleted", case_id=case.id)
    return JSONResponse({})


@router.post("/api/card/lookup")
async def lookup(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    if not ctx.limits.by_ip(ctx.limits.card_lookup, request):
        raise ApiProblem("rate_limited", headers={"Retry-After": "60"})
    req = await _body(request, CardLookup)
    now = ctx.now()
    case = ctx.deps.cases.get_by_short_code(req.code, now=now)
    if case is None or case.card is None or case.card.expires_at <= now:
        raise ApiProblem("not_found", "No card with this code.")
    return _json(CardLookupResponse(url=f"/c/{case.card.token}"))


# ---------------------------------------------------------------------------------------------- programs


def _programs_gate(ctx: AppContext, token: str) -> Case:
    """404 with GP_PROGRAMS=0, 404 / 410 for an unknown or expired card, then the shared bucket of the card's
    token (only real cards get a bucket, so made-up tokens cannot fill the limiter's memory)."""
    if not ctx.settings.programs:
        raise ApiProblem("not_found")
    case = _card_case(ctx, token)
    if not ctx.limits.card_programs.allow(token):
        raise ApiProblem("rate_limited", headers={"Retry-After": "60"})
    return case


def _write(ctx: AppContext, token: str, case: Case, change: Callable[[Case], None]) -> Case:
    """Applies `change` and saves with the case's current version; on a version conflict reloads the case, applies
    the change again and retries once."""
    for attempt in (1, 2):
        change(case)
        try:
            return ctx.deps.cases.save(case, expected_version=case.version)
        except VersionConflict as exc:
            if attempt == 2:
                raise ApiProblem("conflict", "The card changed meanwhile. Try again.") from exc
            case = _card_case(ctx, token)
    raise AssertionError("unreachable")  # pragma: no cover


def _respond(ctx: AppContext, saved: Case, language: Lang) -> JSONResponse:
    ctx.deps.events.publish("case.updated", case=saved, changed_programs=True)
    view = ctx.programs_view(saved, language)
    if view is None:
        raise ApiProblem("not_found")
    return _json(view)


@router.post("/api/card/{token}/answers")
async def answers(token: str, request: Request, lang: str | None = None) -> JSONResponse:
    ctx = _ctx(request)
    case = _programs_gate(ctx, token)
    language = _lang(lang, case.lang)
    req = await _body(request, ProgramAnswersRequest)
    today = ctx.deps.clock.today()

    def change(target: Case) -> None:
        if target.live:
            raise ApiProblem("conflict", "Answers open after the call ends.")
        if ctx.programs_view(target, language) is None:
            raise ApiProblem("not_found")
        try:
            valid = ctx.deps.programs.validate_answers(target, dict(req.answers), today=today)
        except InvalidRequest as exc:
            raise ApiProblem("invalid_request", "Answer not valid for this card.") from exc
        now = ctx.now()
        for question, choice in valid.items():
            target.program_answers[question] = ProgramAnswer(value=choice, at=now, source="card")

    return _respond(ctx, _write(ctx, token, case, change), language)


@router.post("/api/card/{token}/progress")
async def progress(token: str, request: Request, lang: str | None = None) -> JSONResponse:
    ctx = _ctx(request)
    case = _programs_gate(ctx, token)
    language = _lang(lang, case.lang)
    req = await _body(request, ProgramProgressRequest)
    today = ctx.deps.clock.today()

    def change(target: Case) -> None:
        if ctx.programs_view(target, language) is None:
            raise ApiProblem("not_found")
        if not ctx.deps.programs.can_mark(target, req.program, today=today):
            raise ApiProblem("invalid_request", "This program cannot be marked here.")
        target.program_progress[req.program] = ProgramProgress(applied=req.applied, at=ctx.now())

    return _respond(ctx, _write(ctx, token, case, change), language)
