"""Ids: all randomness goes through here so tests can pin values.

Case id "c_" + 10 base32 characters (internal); case code "ABC-234" without the look-alike characters 0, O, 1, I;
call id 32 lowercase hex characters; web token token_urlsafe(32) (stored only as a hash); card token
token_urlsafe(16) (22 characters); short code 6 digits.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Iterator

BASE32 = "abcdefghijklmnopqrstuvwxyz234567"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0, O, 1, I
URLSAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


class SystemIds:
    def case_id(self) -> str:
        return "c_" + "".join(secrets.choice(BASE32) for _ in range(10))

    def case_code(self) -> str:
        chars = [secrets.choice(CODE_ALPHABET) for _ in range(6)]
        return "".join(chars[:3]) + "-" + "".join(chars[3:])

    def call_id(self) -> str:
        return secrets.token_hex(16)

    def web_token(self) -> str:
        return secrets.token_urlsafe(32)

    def card_token(self) -> str:
        return secrets.token_urlsafe(16)

    def short_code(self) -> str:
        return f"{secrets.randbelow(1_000_000):06d}"


def _encode(n: int, alphabet: str, width: int) -> str:
    out = []
    for _ in range(width):
        n, r = divmod(n, len(alphabet))
        out.append(alphabet[r])
    return "".join(reversed(out))


class FixedIds:
    """Deterministic ids for tests. Each kind takes an optional list of values to hand out first (for example
    short_codes=["481206"]); after that a counter produces well-formed values."""

    def __init__(self, *, case_ids: Iterable[str] = (), case_codes: Iterable[str] = (), call_ids: Iterable[str] = (),
                 web_tokens: Iterable[str] = (), card_tokens: Iterable[str] = (),
                 short_codes: Iterable[str] = ()) -> None:
        self._given: dict[str, Iterator[str]] = {
            "case_id": iter(list(case_ids)), "case_code": iter(list(case_codes)), "call_id": iter(list(call_ids)),
            "web_token": iter(list(web_tokens)), "card_token": iter(list(card_tokens)),
            "short_code": iter(list(short_codes)),
        }
        self._n: dict[str, int] = dict.fromkeys(self._given, 0)

    def _next(self, kind: str) -> tuple[str | None, int]:
        self._n[kind] += 1
        return next(self._given[kind], None), self._n[kind]

    def case_id(self) -> str:
        given, n = self._next("case_id")
        return given or "c_" + _encode(n, BASE32, 10)

    def case_code(self) -> str:
        given, n = self._next("case_code")
        if given:
            return given
        raw = _encode(n, CODE_ALPHABET, 6)
        return raw[:3] + "-" + raw[3:]

    def call_id(self) -> str:
        given, n = self._next("call_id")
        return given or f"{n:032x}"

    def web_token(self) -> str:
        given, n = self._next("web_token")
        return given or "webtoken" + _encode(n, URLSAFE, 35)

    def card_token(self) -> str:
        given, n = self._next("card_token")
        return given or "card" + _encode(n, URLSAFE, 18)

    def short_code(self) -> str:
        given, n = self._next("short_code")
        return given or f"{n:06d}"
