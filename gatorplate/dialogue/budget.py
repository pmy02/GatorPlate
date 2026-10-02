"""Phone word budgets (contracts/brain_api.v1.schema.json `x-word-budgets`, docs/BRAIN_API.md §7).

A word is a whitespace-separated token with at least one letter or digit ("student-built" and "isn't" are one word
each; a lone dash is none), counted on `say` + `ask` together. Opening 40, question 25, result 45. A reply whose say
gives an outcome or contact details to keep (a result line, the expedited outlook, the apply-today and card lines, or
a phone number) uses the result budget. A planned reply over its budget is split at a key boundary: the first part goes
out with `ask` null and the rest follows on the next request (docs/SPEC.md §3.2).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

WORD_BUDGETS: dict[str, int] = {"opening": 40, "question": 25, "result": 45}

# Keys whose line is a result, an outcome or carries a phone number (the same list the contract checker uses).
RESULT_KEY_PREFIXES: tuple[str, ...] = (
    "result.", "expedited.yes", "expedited.maybe", "first_month.", "card.", "close.anything_else", "close.silence",
    "consent.declined", "crisis.resources", "human.request", "stop.goodbye", "abuse.end", "error.generic",
)
CONTACT_WORDS = re.compile(r"\b(four one five|eight five five|eight seven seven|nine eight eight|nine one one)\b",
                           re.IGNORECASE)


def count_words(text: str) -> int:
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


def budget_class(keys: Sequence[str], spoken: str) -> str:
    if keys and keys[0] == "consent.ask":
        return "opening"
    if any(k.startswith(RESULT_KEY_PREFIXES) for k in keys) or CONTACT_WORDS.search(spoken):
        return "result"
    return "question"


def fits(keys: Sequence[str], spoken: str) -> bool:
    return count_words(spoken) <= WORD_BUDGETS[budget_class(keys, spoken)]


def split_point(n_steps: int, render_prefix: Callable[[int], tuple[list[str], str]]) -> int:
    """How many steps of a planned reply go out now: the longest prefix (at least one step) that fits its budget.
    `render_prefix(k)` returns the keys and the spoken text of the first k steps."""
    if n_steps <= 1:
        return n_steps
    keys, spoken = render_prefix(n_steps)
    if fits(keys, spoken):
        return n_steps
    for k in range(n_steps - 1, 0, -1):
        keys, spoken = render_prefix(k)
        if fits(keys, spoken):
            return k
    return 1
