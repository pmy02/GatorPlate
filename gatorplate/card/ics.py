"""The calendar file of the student card (docs/SPEC.md §6.3): all-day events the student downloads.

GatorPlate sends nothing: the file only holds dated events (no alarms). Text values are escaped per RFC 5545
(backslash, semicolon, comma, newline), lines end with CRLF and are folded at 75 octets.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

LINE_OCTETS = 75


def escape_text(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line: str) -> list[str]:
    """Split one content line into chunks of at most 75 octets (continuations start with a space), never inside a
    multi-byte character."""
    out: list[str] = []
    current = ""
    limit = LINE_OCTETS
    for ch in line:
        if len((current + ch).encode("utf-8")) > limit:
            out.append(current)
            current = " " + ch
            limit = LINE_OCTETS
        else:
            current += ch
    out.append(current)
    return out


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_calendar(events: Sequence[tuple[date, str]], *, uid_seed: str, stamp: datetime, lang: str) -> str:
    """One VCALENDAR with an all-day VEVENT per (day, title)."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//GatorPlate//Student card//" + lang.upper(),
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for day, title in events:
        uid = hashlib.sha256(f"{uid_seed}|{day.isoformat()}".encode()).hexdigest()[:24]
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@gatorplate",
            f"DTSTAMP:{_stamp(stamp)}",
            f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY;LANGUAGE={lang}:{escape_text(title)}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(chunk + "\r\n" for line in lines for chunk in fold(line))
