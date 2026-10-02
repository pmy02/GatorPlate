"""Dialogue (BrainPort): global intents, the phase machine, rendering from the sentence bank, word budgets, the
output guard, per-call locks and seq rules (docs/SPEC.md §3, docs/BRAIN_API.md).

`Brain(*, settings, clock, ids, rules, understanding, cases, sessions, live, events, cards, content_dir=None)`: every
collaborator comes through its port; the brain imports only the contracts.
"""

from __future__ import annotations

from gatorplate.dialogue.orchestrator import Brain

__all__ = ["Brain"]
