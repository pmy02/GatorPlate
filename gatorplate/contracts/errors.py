"""Domain errors. The API maps each one to its error code (contracts/brain_api.v1.schema.json x-errors); no other
codes exist (no 403, no 423)."""

from __future__ import annotations

from typing import ClassVar


class GatorPlateError(Exception):
    """Base class: `code` is the API error code, `status` its HTTP status."""

    code: ClassVar[str] = "internal"
    status: ClassVar[int] = 500

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = message


class VersionConflict(GatorPlateError):
    """A save with an expected_version that is no longer current."""

    code = "conflict"
    status = 409


class NotFound(GatorPlateError):
    code = "not_found"
    status = 404


class Locked(GatorPlateError):
    """Mark reviewed while a yellow line is open."""

    code = "locked"
    status = 409


class Gone(GatorPlateError):
    """A card past its time to live."""

    code = "gone"
    status = 410


class Conflict(GatorPlateError):
    """A turn after the call ended, a status change on a live case, a transition that is not allowed."""

    code = "conflict"
    status = 409


class StaleSeq(GatorPlateError):
    code = "stale_seq"
    status = 409


class UnknownCall(GatorPlateError):
    code = "unknown_call"
    status = 404


class InvalidRequest(GatorPlateError):
    """A body or value the endpoint cannot accept (for example an unknown card question or choice)."""

    code = "invalid_request"
    status = 422


__all__ = ["GatorPlateError", "VersionConflict", "NotFound", "Locked", "Gone", "Conflict", "StaleSeq",
           "UnknownCall", "InvalidRequest"]
