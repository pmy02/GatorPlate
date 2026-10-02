"""Wiring: builds Deps from Settings (real rules, understanding, brain, stores, live store, event bus, card builder,
programs engine, system clock and ids). Completed at integration."""

from __future__ import annotations

from gatorplate.config import Settings
from gatorplate.deps import Deps


def build_deps(settings: Settings) -> Deps:
    raise NotImplementedError("build_deps is wired at integration")
