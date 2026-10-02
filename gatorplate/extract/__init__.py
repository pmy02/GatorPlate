"""Understanding (UnderstandingPort): redaction, keyword intents, parser, one language-model call, merge.

docs/SPEC.md §3 (conversation) and §8.7-§8.8 (redaction, what the language model sees).
"""

from __future__ import annotations

from gatorplate.extract.service import Understander

__all__ = ["Understander"]
