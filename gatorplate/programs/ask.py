"""The card's ask rule: only ask what can change the yearly total (docs/SPEC.md §5.10 "Card questions").

spread(q) = max - min of found_yearly over q's choices, with the answered questions kept and every other unanswered
question held at "unanswered". A question is open when its spread is more than `ask_rule.threshold_usd` (a yearly
card threshold, not the CalFresh question picker's monthly one). Open questions go highest spread first, then by
`ask_rule.priority`; at most `max_questions` card questions in all; re-planned on every call.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from gatorplate.programs.table import AskRule, Question


@dataclass
class AskPlan:
    spreads: dict[str, int]
    open: list[str]

    @property
    def next(self) -> str | None:
        return self.open[0] if self.open else None


def plan_questions(questions: Mapping[str, Question], rule: AskRule, answered: Mapping[str, str],
                   askable: Callable[[Question], bool],
                   found_yearly: Callable[[Mapping[str, str]], int]) -> AskPlan:
    spreads: dict[str, int] = {}
    for qid, question in questions.items():
        if qid in answered or not askable(question):
            continue
        totals = [found_yearly({**answered, qid: choice}) for choice in question.choices]
        spreads[qid] = max(totals) - min(totals)
    threshold = rule.threshold_usd

    def clears(spread: int) -> bool:
        return spread > threshold if rule.strictly_greater else spread >= threshold

    rank = {qid: i for i, qid in enumerate(rule.priority)}
    open_ids = sorted((q for q, s in spreads.items() if clears(s)), key=lambda q: (-spreads[q], rank[q]))
    room = max(0, rule.max_questions - len(answered))
    return AskPlan(spreads=spreads, open=open_ids[:room])
