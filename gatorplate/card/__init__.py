"""Student card (CardBuilderPort): CardView, CardStatus and the calendar file from a Case and the card content
(docs/SPEC.md §6). The unlocked part comes from the injected ProgramsPort, never from importing the programs module.
"""

from __future__ import annotations

from gatorplate.card.builder import CardBuilder, cardview_strings, unlocked_strings

__all__ = ["CardBuilder", "cardview_strings", "unlocked_strings"]
