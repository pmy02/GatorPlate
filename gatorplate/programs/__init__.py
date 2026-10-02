"""Other programs on the student card (ProgramsPort): "money you may be missing", computed by code from
data/rules/programs_2026.json and spoken by data/content/programs.{en,es}.json (docs/SPEC.md §5.10 and §6.6).

Pure: everything is loaded once at construction. An engine built with enabled=False (GP_PROGRAMS=0) needs no files
and answers None / False everywhere. The module imports only the contracts (never rules, dialogue, card, store or
api) and never writes a CalFresh slot.
"""

from __future__ import annotations

from gatorplate.programs.engine import Computed, Programs
from gatorplate.programs.facts import ProgramFacts, facts_from_case

__all__ = ["Computed", "ProgramFacts", "Programs", "facts_from_case"]
