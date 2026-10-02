"""A25: a language-model answer later than 2.3 s → the closed question within the 2.6 s turn budget, and a second
failure in a row → closed mode for the rest of the call (docs/SPEC.md §3.7; docs/BRAIN_API.md §9).

In process over the real wiring with the fake model, whose test hook adds the delay. Skipped, with the reason, while
the wiring is still the foundation stub or when the fake model exposes no delay hook (closed mode itself is also
covered over HTTP by tests/adversarial/scripts/a26_closed_mode.json).
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from tests.e2e import inprocess

DELAY_NAMES = ("delay_s", "delay", "delay_seconds")


def _find_fake_model(root: Any) -> Any | None:
    seen: set[int] = set()
    todo = [root]
    for _ in range(5):
        nxt = []
        for obj in todo:
            if id(obj) in seen or obj is None or isinstance(obj, str | int | float | bool | bytes):
                continue
            seen.add(id(obj))
            if type(obj).__module__.startswith("gatorplate.extract.llm.fake"):
                return obj
            values = vars(obj).values() if hasattr(obj, "__dict__") else []
            nxt += [v for v in values if not callable(v) or hasattr(v, "__dict__")]
        todo = nxt
    return None


def test_slow_model_gives_the_closed_question_within_the_turn_budget(settings_test) -> None:
    h = inprocess.build(settings_test, fixed_clock=False)
    try:
        fake = _find_fake_model(h.deps.understanding)
        name = next((n for n in DELAY_NAMES if fake is not None and hasattr(fake, n)), None)
        if name is None:
            pytest.skip("the fake model exposes no delay hook (delay_s) for this test")
        h.login()
        call = "a" * 31 + "5"
        start = h.target.post(f"/v1/calls/{call}/start", {"v": 1, "seq": 0, "channel": "phone", "lang": "en"},
                              channel="phone")
        assert start.status_code == 200
        ok = h.target.post(f"/v1/calls/{call}/turn", {"v": 1, "seq": 1, "lang": "en", "event": "dtmf", "dtmf": "1"},
                           channel="phone")
        assert ok.status_code == 200
        setattr(fake, name, 3.0)
        timings = []
        for seq, text in ((2, "So, um, I guess I'm in my third year here and taking a normal load."),
                          (3, "Like I said, third year, normal load of classes.")):
            t0 = time.monotonic()
            r = h.target.post(f"/v1/calls/{call}/turn", {"v": 1, "seq": seq, "lang": "en", "event": "utterance",
                                                          "text": text, "confidence": 0.9}, channel="phone")
            timings.append(time.monotonic() - t0)
            assert r.status_code == 200
            reply = r.json()
            assert reply["ask"], "a closed question, never an empty reply"
            assert "press" in reply["ask"].lower(), "the phone closed form names its single-key options"
        assert max(timings) <= 2.6 + 0.4, timings
        setattr(fake, name, 0)
        after = h.target.post(f"/v1/calls/{call}/turn", {"v": 1, "seq": 4, "lang": "en", "event": "dtmf",
                                                          "dtmf": "1"}, channel="phone")
        assert after.status_code == 200 and "press" in (after.json()["ask"] or "").lower(), "closed mode stays on"
    finally:
        inprocess.close(h)
