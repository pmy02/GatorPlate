"""The card widget for the unlocked part (web/unlocked; docs/UI_SPEC.md A4.1, A4.2 row 2b, A9 items 15-16): size,
light only, CSP-safe, imports, and no words of its own."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
WIDGET = ROOT / "web" / "unlocked"
SHIPPED = ("unlocked.js", "unlocked-lib.mjs", "unlocked.css")  # what the card page loads
BUDGET = 12_000  # bytes, uncompressed: widget JS + CSS
# Hangul jamo, compatibility jamo and syllables, written as code points (no such characters in the repository)
HANGUL = re.compile("[{}-{}{}-{}{}-{}]".format(*(chr(c) for c in (0x1100, 0x11FF, 0x3130, 0x318F, 0xAC00, 0xD7AF))))


def text(name: str) -> str:
    return (WIDGET / name).read_text(encoding="utf-8")


def test_widget_js_and_css_fit_the_budget() -> None:
    size = sum(len((WIDGET / n).read_bytes()) for n in SHIPPED)
    assert size <= BUDGET, f"{size} bytes > {BUDGET}"


def test_the_card_contract() -> None:
    js = text("unlocked.js")
    assert "window.GPUnlocked = {" in js and "mount(el, v, o)" in js and "render," in js
    imports = re.findall(r'^import .* from "([^"]+)";$', js, flags=re.M)
    assert imports == ["/shared/api.js", "/unlocked/unlocked-lib.mjs"]
    assert "import" not in text("unlocked-lib.mjs").replace("export", "")
    for path in ("/api/card/", "/answers", "/progress"):
        assert path in js or path.strip("/") in js
    assert "beforeprint" in js and "prefers-reduced-motion" in js and 'role: "status"' in js


def test_light_only_tokens_only_csp_safe() -> None:
    for name in (*SHIPPED, "harness.js", "harness.css", "index.html"):
        body = text(name)
        assert "prefers-color-scheme" not in body, name
        assert not re.search(r"#[0-9a-fA-F]{6}\b|\brgba?\(|\bhsla?\(", body), name
        assert "font-family" not in body, name
        assert "style=" not in body and "onclick" not in body.lower(), name
        assert "innerHTML = `<svg" in body or "innerHTML" not in body, name
    html = text("index.html")
    assert '<meta name="color-scheme" content="only light">' in html and 'content="noindex"' in html
    assert html.index("/shared/tokens.css") < html.index("/shared/base.css") < html.index("/unlocked/unlocked.css")
    assert "<script>" not in html


def test_the_widget_owns_no_words() -> None:
    """Every visible word comes from UnlockedView (programs.*.json); the widget's string literals are code."""
    js = text("unlocked.js")
    content = json.loads((ROOT / "data" / "content" / "programs.en.json").read_text(encoding="utf-8"))["strings"]
    for phrase in ("Money you may be missing", "Your plan", "I applied", "Share", "Copied", "Question"):
        assert phrase not in js, phrase
    for value in content.values():
        if len(value) > 12:
            assert value not in js


def test_public_text_rules() -> None:
    for path in WIDGET.iterdir():
        if path.is_file():
            body = path.read_text(encoding="utf-8")
            assert not HANGUL.search(body), path.name
            assert "/Users/" not in body and "localhost" not in body, path.name
            assert not re.search(r"\b(?:chrome|safari|firefox|google|apple)\b", body, re.I), path.name
