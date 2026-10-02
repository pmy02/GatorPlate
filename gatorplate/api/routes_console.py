"""Coordinator console API (docs/UI_SPEC.md A3 and A8.3): login, meta, cases, yellow lines, slot edits, status,
tracking, delete, QR codes, the live transcript and Server-Sent Events. Every route but login and logout needs the
console's signed session cookie.

Review lock: entering `reviewed` needs zero open yellow lines (409 locked). A live case cannot change status or be
edited (409 conflict); every edit carries the version the coordinator saw (409 conflict when it is stale).
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ValidationError

import gatorplate
from gatorplate.api.auth import CONSOLE_KEY, require_console
from gatorplate.api.context import TRANSITIONS, AppContext
from gatorplate.api.errors import ApiProblem, read_body
from gatorplate.api.qr import qr_svg
from gatorplate.api.sse import event_stream, parse_last_event_id
from gatorplate.contracts.case import Case
from gatorplate.contracts.common import CaseStatus, Lang, SlotSource, SlotState, YellowKind, YellowResolution
from gatorplate.contracts.console_api import (
    CaseListResponse,
    ConsoleMeta,
    LiveView,
    LoginRequest,
    SlotEdit,
    StatusChange,
    TrackingPatch,
    YellowAction,
)
from gatorplate.contracts.errors import VersionConflict
from gatorplate.contracts.slots import ROUTING_ONLY, SLOT_SPECS, Slot, SlotName, encode_value, format_display

router = APIRouter()
FIXABLE_KINDS = (YellowKind.unclear, YellowKind.conflict, YellowKind.assumed)


def _ctx(request: Request) -> AppContext:
    return request.app.state.ctx


async def _body[M: BaseModel](request: Request, model: type[M]) -> M:
    raw = await read_body(request)
    try:
        return model.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        raise ApiProblem("invalid_request") from exc


def _json(model: BaseModel) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"))


def _case(ctx: AppContext, case_id: str) -> Case:
    case = ctx.deps.cases.get(case_id)
    if case is None:
        raise ApiProblem("not_found", "No such case.")
    return case


def _editable(case: Case, expected_version: int) -> None:
    if case.live:
        raise ApiProblem("conflict", "The call is still live.")
    if case.version != expected_version:
        raise ApiProblem("conflict", "The case was changed by someone else. Reload it.")


def _save(ctx: AppContext, case: Case, expected_version: int) -> Case:
    try:
        return ctx.deps.cases.save(case, expected_version=expected_version)
    except VersionConflict as exc:
        raise ApiProblem("conflict", "The case was changed by someone else. Reload it.") from exc


def _rerun_rules(ctx: AppContext, case: Case, now: datetime) -> Case:
    return ctx.deps.rules.apply(case, now=now)


def _set_slot(case: Case, name: SlotName, value: str, *, now: datetime) -> None:
    if name in ROUTING_ONLY:
        raise ApiProblem("invalid_request", "This answer is never stored.")
    try:
        raw = encode_value(name, value)
    except (ValueError, TypeError) as exc:
        raise ApiProblem("invalid_request", "Value not valid for this answer.") from exc
    old = case.slots.get(name)
    changed_from = old.changed_from if old is not None else None
    if old is not None and old.value is not None and old.value != raw:
        changed_from = old.value
    case.slots[name] = Slot(value=raw, display=format_display(name, raw), state=SlotState.clear,
                            heard=old.heard if old else None, heard_en=old.heard_en if old else None,
                            confirmed=True, changed_from=changed_from, turn=old.turn if old else None,
                            source=SlotSource.coordinator, basis=None, updated_at=now)


# ---------------------------------------------------------------------------------------------- login


@router.post("/api/console/login")
async def login(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    if not ctx.limits.by_ip(ctx.limits.console_login, request):
        raise ApiProblem("rate_limited", headers={"Retry-After": "60"})
    req = await _body(request, LoginRequest)
    expected = ctx.settings.console_passcode.get_secret_value().encode("utf-8")
    if not expected or not hmac.compare_digest(req.passcode.encode("utf-8"), expected):
        raise ApiProblem("unauthorized", "Wrong passcode.")
    request.session.clear()
    request.session[CONSOLE_KEY] = True
    return JSONResponse({"ok": True})


@router.post("/api/console/logout")
async def logout(request: Request) -> JSONResponse:
    request.session.clear()
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------------------------- reads


@router.get("/api/meta")
async def meta(request: Request) -> JSONResponse:
    require_console(request)
    ctx = _ctx(request)
    settings = ctx.settings
    rules = ctx.rules_meta()
    out = ConsoleMeta(rules=rules, rules_valid_today=bool(ctx.deps.rules.valid_on(ctx.deps.clock.today())),
                      slot_specs=dict(SLOT_SPECS), demo_mode=bool(settings.demo_mode),
                      live_transcript=bool(settings.live_transcript), card_delivery=settings.card_delivery,
                      app_version=gatorplate.__version__, demo_phone_display=settings.demo_phone_display or None,
                      programs=ctx.programs_meta())
    return _json(out)


@router.get("/api/cases")
async def list_cases(request: Request, status: str | None = None, since_seq: str | None = None,
                     limit: str | None = None) -> JSONResponse:
    require_console(request)
    ctx = _ctx(request)
    try:
        wanted = CaseStatus(status) if status else None
        since = int(since_seq) if since_seq not in (None, "") else None
        count = int(limit) if limit not in (None, "") else 200
    except ValueError as exc:
        raise ApiProblem("invalid_request", "Bad query.") from exc
    if count < 1 or count > 500 or (since is not None and since < 0):
        raise ApiProblem("invalid_request", "Bad query.")
    seq = ctx.deps.events.current_seq()
    changed = None
    if since is not None and hasattr(ctx.deps.events, "changed_since"):
        changed = ctx.deps.events.changed_since(since)
    if changed is None:  # no since_seq, or the caller must refetch everything (reset, buffer overrun, restart)
        cases = ctx.deps.cases.list(status=wanted, limit=count)
    else:
        # Only the cases with an event after since_seq, however old they are (a card answer on last week's case).
        found = [c for c in (ctx.deps.cases.get(cid) for cid in changed) if c is not None]
        found = [c for c in found if wanted is None or c.status == wanted]
        cases = sorted(found, key=lambda c: (c.created_at, c.id), reverse=True)[:count]
    out = CaseListResponse(items=[ctx.summarize(c) for c in cases], seq=seq, server_time=ctx.now())
    return _json(out)


@router.get("/api/cases/{case_id}")
async def get_case(case_id: str, request: Request) -> JSONResponse:
    require_console(request)
    ctx = _ctx(request)
    return _json(ctx.detail(_case(ctx, case_id)))


@router.get("/api/cases/{case_id}/live")
async def get_live(case_id: str, request: Request) -> JSONResponse:
    require_console(request)
    ctx = _ctx(request)
    if not ctx.settings.live_transcript:
        raise ApiProblem("not_found")
    case = _case(ctx, case_id)
    if not case.live:
        raise ApiProblem("not_found", "The call has ended.")
    view = ctx.deps.live.get(case_id) or LiveView(case_id=case_id, lines=[])
    return _json(view)


# ---------------------------------------------------------------------------------------------- edits


@router.post("/api/cases/{case_id}/yellow/{yid}")
async def yellow_action(case_id: str, yid: str, request: Request) -> JSONResponse:
    require_console(request)
    ctx = _ctx(request)
    req = await _body(request, YellowAction)
    case = _case(ctx, case_id)
    line = next((y for y in case.yellow_lines if y.id == yid), None)
    if line is None:
        raise ApiProblem("not_found", "No such yellow line.")
    _editable(case, req.expected_version)
    if line.resolved is not None:
        raise ApiProblem("conflict", "This line is already checked.")
    now = ctx.now()
    changed: list[SlotName] = []
    if req.action is YellowResolution.edit:
        if req.value is None or line.slot is None:
            raise ApiProblem("invalid_request", "An edit needs a value for the line's answer.")
        _set_slot(case, line.slot, req.value, now=now)
        changed.append(line.slot)
    line.resolved = req.action
    line.resolved_at = now
    line.resolved_note = req.note
    if changed:
        case = _rerun_rules(ctx, case, now)
    saved = _save(ctx, case, req.expected_version)
    ctx.deps.events.publish("case.updated", case=saved, changed_slots=changed)
    return _json(ctx.detail(saved))


@router.put("/api/cases/{case_id}/slots/{slot}")
async def edit_slot(case_id: str, slot: str, request: Request) -> JSONResponse:
    require_console(request)
    ctx = _ctx(request)
    try:
        name = SlotName(slot)
    except ValueError as exc:
        raise ApiProblem("invalid_request", "Unknown answer.") from exc
    req = await _body(request, SlotEdit)
    case = _case(ctx, case_id)
    _editable(case, req.expected_version)
    now = ctx.now()
    _set_slot(case, name, req.value, now=now)
    for line in case.yellow_lines:
        if line.slot == name and line.resolved is None and line.kind in FIXABLE_KINDS:
            line.resolved = YellowResolution.edit
            line.resolved_at = now
            line.resolved_note = req.note
    case = _rerun_rules(ctx, case, now)
    saved = _save(ctx, case, req.expected_version)
    ctx.deps.events.publish("case.updated", case=saved, changed_slots=[name])
    return _json(ctx.detail(saved))


@router.post("/api/cases/{case_id}/status")
async def change_status(case_id: str, request: Request) -> JSONResponse:
    require_console(request)
    ctx = _ctx(request)
    req = await _body(request, StatusChange)
    case = _case(ctx, case_id)
    _editable(case, req.expected_version)
    if req.status not in TRANSITIONS[case.status]:
        raise ApiProblem("conflict", "This status change is not allowed.")
    if req.status is CaseStatus.reviewed:
        open_lines = sum(1 for y in case.yellow_lines if y.resolved is None)
        if open_lines:
            raise ApiProblem("locked", f"Check {open_lines} line{'s' if open_lines != 1 else ''} first.")
        case.reviewed_at = ctx.now()
    case.status = req.status
    saved = _save(ctx, case, req.expected_version)
    ctx.deps.events.publish("case.updated", case=saved)
    return _json(ctx.detail(saved))


@router.patch("/api/cases/{case_id}/tracking")
async def patch_tracking(case_id: str, request: Request) -> JSONResponse:
    require_console(request)
    ctx = _ctx(request)
    req = await _body(request, TrackingPatch)
    case = _case(ctx, case_id)
    _editable(case, req.expected_version)
    updates: dict[str, Any] = req.model_dump(exclude_unset=True, exclude={"expected_version"})
    if updates.get("interview_missed", False) is None:
        updates.pop("interview_missed")
    interview_at = updates.get("interview_at")
    if isinstance(interview_at, datetime):
        # Stored in UTC; a time without an offset is the coordinator's Pacific wall-clock time.
        if interview_at.tzinfo is None:
            interview_at = interview_at.replace(tzinfo=ZoneInfo(ctx.settings.tz))
        updates["interview_at"] = interview_at.astimezone(UTC)
    tracking = case.tracking.model_copy(update=updates)
    case.tracking = ctx.deps.rules.compute_tracking(tracking)
    saved = _save(ctx, case, req.expected_version)
    ctx.deps.events.publish("case.updated", case=saved)
    return _json(ctx.detail(saved))


@router.delete("/api/cases/{case_id}")
async def delete_case(case_id: str, request: Request) -> JSONResponse:
    require_console(request)
    ctx = _ctx(request)
    if not ctx.deps.cases.delete(case_id):
        raise ApiProblem("not_found", "No such case.")
    ctx.deps.live.wipe(case_id)
    ctx.deps.events.publish("case.deleted", case_id=case_id)
    return JSONResponse({})


# ---------------------------------------------------------------------------------------------- QR codes


def _svg(data: bytes) -> Response:
    return Response(content=data, media_type="image/svg+xml")


@router.get("/api/cases/{case_id}/qr.svg")
async def case_qr(case_id: str, request: Request) -> Response:
    require_console(request)
    ctx = _ctx(request)
    case = _case(ctx, case_id)
    if case.card is None:
        raise ApiProblem("not_found", "This case has no card.")
    return _svg(qr_svg(f"{ctx.settings.public_base_url.rstrip('/')}/c/{case.card.token}"))


@router.get("/api/qr/talk.svg")
async def talk_qr(request: Request, lang: str = "en") -> Response:
    require_console(request)
    ctx = _ctx(request)
    try:
        language = Lang(lang)
    except ValueError as exc:
        raise ApiProblem("invalid_request", "Unsupported lang.") from exc
    return _svg(qr_svg(f"{ctx.settings.public_base_url.rstrip('/')}/talk?lang={language.value}"))


# ---------------------------------------------------------------------------------------------- events


@router.get("/api/events")
async def events(request: Request, last_event_id: str | None = None) -> StreamingResponse:
    require_console(request)
    ctx = _ctx(request)
    last = parse_last_event_id(request.headers.get("last-event-id") or last_event_id)
    sub = ctx.deps.events.open(last_seq=last)
    # No proxy buffering, caching or transforming (compression would hold the stream back).
    return StreamingResponse(event_stream(sub, ping_s=ctx.sse_ping_s), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache, no-transform"})
