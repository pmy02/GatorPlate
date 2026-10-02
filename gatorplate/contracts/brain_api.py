"""Brain API v1 models: an exact mirror of contracts/brain_api.v1.schema.json (docs/BRAIN_API.md).

The JSON Schema is the only source: field names, types, enums, consts, required sets, nullability, defaults and
constraints match it (tests/test_schema_parity.py proves it). Requests a client sends ignore unknown properties
(tolerant reader); replies have exactly the schema's properties and always serialize every field.

Fields the schema makes optional but not nullable use the form `T = Field(default=None, ...)`: absent is fine, an
explicit null is rejected, exactly as the schema. Values that have a JSON type are validated strictly (no
string-to-number or number-to-bool coercion), so request bodies are validated with model_validate_json(raw_body).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from gatorplate.contracts.common import Channel, Lang

CALL_ID = r"^[a-f0-9]{32}$"
TOKEN_PATTERN = r"^[A-Za-z0-9_-]{22,128}$"
CARD_URL_PATTERN = r"^/c/[A-Za-z0-9_-]{22,64}$"
DTMF_PATTERN = r"^[0-9*#]{1,20}$"

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
ChoiceLabel = Annotated[str, StringConstraints(min_length=1, max_length=60)]


class TolerantModel(BaseModel):
    """Client requests: unknown properties are ignored."""

    model_config = ConfigDict(extra="ignore")


class ClosedModel(BaseModel):
    """Replies: exactly the schema's properties."""

    model_config = ConfigDict(extra="forbid")


def _json_int_const(value: Any, expected: int) -> Any:
    # pydantic's Literal[1] / Literal[0] accept true / false (bool is an int in Python); the schema's const does not.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"must be the JSON integer {expected}")
    return value


class StartRequest(TolerantModel):
    v: Literal[1]
    seq: Literal[0]
    channel: Channel  # must match the credentials (signature = phone, bearer = web)
    lang: Lang  # phone: always en
    test: StrictBool = False

    @field_validator("v", mode="before")
    @classmethod
    def _v_is_int(cls, value: Any) -> Any:
        return _json_int_const(value, 1)

    @field_validator("seq", mode="before")
    @classmethod
    def _seq_is_int(cls, value: Any) -> Any:
        return _json_int_const(value, 0)


class TurnRequest(TolerantModel):
    v: Literal[1]
    seq: StrictInt = Field(ge=1)
    lang: Lang = Field(default=None)  # absent: the call's language
    event: Literal["utterance", "dtmf", "silence"]
    text: StrictStr = Field(default=None, max_length=1000)  # may be "" (the brain re-asks)
    masked: StrictBool = False
    confidence: float | None = Field(default=None, ge=0, le=1)  # a JSON number or null, never a string or a bool
    interrupted: StrictBool = False
    typed: StrictBool = False
    # Schema tolerance: the gateway sends exactly one key; the brain reads a longer value as unclear.
    dtmf: StrictStr = Field(default=None, pattern=DTMF_PATTERN)
    silence_n: StrictInt = Field(default=None, ge=1)
    silence_ms: StrictInt = Field(default=None, ge=0)

    @field_validator("v", mode="before")
    @classmethod
    def _v_is_int(cls, value: Any) -> Any:
        return _json_int_const(value, 1)

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence_is_number(cls, value: Any) -> Any:
        if isinstance(value, bool) or isinstance(value, str):
            raise ValueError("confidence must be a JSON number or null")
        return value

    @model_validator(mode="after")
    def _event_fields(self) -> TurnRequest:
        # Exactly one event per request; fields that belong to another event are ignored.
        if self.event == "utterance" and self.text is None:
            raise ValueError("an utterance event needs text")
        if self.event == "dtmf" and self.dtmf is None:
            raise ValueError("a dtmf event needs dtmf")
        if self.event == "silence" and self.silence_n is None:
            raise ValueError("a silence event needs silence_n")
        return self


class EndRequest(TolerantModel):
    v: Literal[1]
    reason: Literal["completed", "caller_hangup", "no_input", "timeout", "max_duration", "declined", "error"]
    turns: StrictInt = Field(default=None, ge=0)  # optional, not nullable
    duration_ms: StrictInt = Field(default=None, ge=0)  # optional, not nullable

    @field_validator("v", mode="before")
    @classmethod
    def _v_is_int(cls, value: Any) -> Any:
        return _json_int_const(value, 1)


class EndResponse(ClosedModel):
    """{} — the body returned by /end."""


class ReplyDebug(BaseModel):
    """Schema: an object whose two properties are optional and whose extra properties are allowed."""

    model_config = ConfigDict(extra="allow")

    keys: list[NonEmptyStr] = Field(default_factory=list)
    phase: str = ""  # never null (schema type string); the brain always sets the phase


ReplyEndReason = Literal["completed", "no_input", "declined"]


class BrainReply(ClosedModel):
    """Every field is required; ask, display, choices, card_url, debug and end_reason are nullable."""

    say: str = Field(max_length=1000)
    ask: str | None = Field(min_length=1, max_length=300)
    end: bool
    end_reason: ReplyEndReason | None
    lang: Lang
    listen: Literal["normal", "long"]
    expect: Literal["open", "yes_no", "confirm", "number", "choice"]
    interruptible: bool
    hold_s: int = Field(ge=0, le=60)
    display: str | None = Field(max_length=1500)
    choices: list[ChoiceLabel] | None = Field(min_length=1, max_length=6)
    card_url: str | None = Field(pattern=CARD_URL_PATTERN)
    debug: ReplyDebug | None

    @model_validator(mode="after")
    def _reply_rules(self) -> BrainReply:
        # Schema allOf: end -> end_reason set, ask null, hold_s 0, not interruptible; not end -> end_reason null;
        # hold_s >= 1 -> ask null.
        if self.end:
            if self.end_reason is None:
                raise ValueError("end true needs an end_reason")
            if self.ask is not None:
                raise ValueError("end true needs ask null")
            if self.hold_s != 0:
                raise ValueError("end true needs hold_s 0")
            if self.interruptible:
                raise ValueError("end true needs interruptible false")
        elif self.end_reason is not None:
            raise ValueError("end_reason must be null unless end is true")
        if self.hold_s >= 1 and self.ask is not None:
            raise ValueError("hold_s 1-60 needs ask null")
        return self


class GatewayLines(ClosedModel):
    lang: Lang
    filler: list[NonEmptyStr] = Field(min_length=3, max_length=3)
    retry: str = Field(min_length=1)
    fatal: str = Field(min_length=1)
    fatal_start: str = Field(min_length=1)
    no_input_bye: str = Field(min_length=1)
    time_limit: str = Field(min_length=1)
    line_unavailable: str = Field(min_length=1)


class WebSessionRequest(TolerantModel):
    lang: Lang = Lang.en


class WebSessionResponse(ClosedModel):
    call_id: str = Field(pattern=CALL_ID)
    token: str = Field(pattern=TOKEN_PATTERN)
    expires_at: datetime  # RFC 3339, 30 minutes after issue


class HealthResponse(ClosedModel):
    ok: Literal[True]


ErrorCode = Literal["unknown_call", "bad_signature", "stale_timestamp", "unauthorized", "rate_limited",
                    "invalid_request", "stale_seq", "conflict", "locked", "not_found", "gone", "internal"]

# code -> (HTTP status, retryable): exactly the schema's x-errors.
ERROR_STATUS: dict[str, tuple[int, bool]] = {
    "unknown_call": (404, False),
    "bad_signature": (401, False),
    "stale_timestamp": (401, False),
    "unauthorized": (401, False),
    "rate_limited": (429, True),
    "invalid_request": (422, False),
    "stale_seq": (409, False),
    "conflict": (409, False),
    "locked": (409, False),
    "not_found": (404, False),
    "gone": (410, False),
    "internal": (500, True),
}


class ApiError(ClosedModel):
    code: ErrorCode
    message: str = Field(min_length=1, max_length=200)  # short and generic: no stack traces, no request text
    retryable: bool


class ErrorEnvelope(ClosedModel):
    error: ApiError


def error_envelope(code: str, message: str) -> ErrorEnvelope:
    """The error body for a code, with the schema's retryable flag."""
    _, retryable = ERROR_STATUS[code]
    return ErrorEnvelope(error=ApiError(code=code, message=message, retryable=retryable))
