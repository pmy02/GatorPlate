"""Static checks of the card page (/c/{token}) and the code page (/go): docs/UI_SPEC.md A0, A4, A7.1 and A9."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
CARD = WEB / "card"
GO = WEB / "go"
SPEC = (ROOT / "docs" / "UI_SPEC.md").read_text(encoding="utf-8")
PAGE_FILES = [CARD / "index.html", CARD / "card.css", CARD / "card.js", CARD / "card-lib.mjs"]
SHARED_FILES = [WEB / "shared" / "tokens.css", WEB / "shared" / "base.css", WEB / "shared" / "api.js"]
WIDGET_FILES = [WEB / "unlocked" / "unlocked.js", WEB / "unlocked" / "unlocked.css"]
OWN = sorted(p for p in [*CARD.iterdir(), *GO.iterdir()] if p.is_file() and not p.name.endswith(".test.mjs"))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def spec_table(section: str) -> dict[str, tuple[str, str]]:
    """Key -> (English, Spanish) rows of a UI_SPEC string table."""
    start = SPEC.index(section)
    body = SPEC[start:SPEC.index("\n### ", start + 1)]
    rows = {}
    for line in body.splitlines():
        m = re.match(r"\| `([^`]+)`[^|]*\| (.+?) \| (.+?) \|$", line)
        if m:
            rows[m.group(1)] = (m.group(2), m.group(3))
    return rows


def test_card_page_strings_follow_ui_spec_a47() -> None:
    js, html = read(CARD / "card.js"), read(CARD / "index.html")
    rows = spec_table("### A4.7 Card UI strings")
    assert {"retry", "badlink", "status.reviewed", "noscript", "prototype"} <= set(rows)
    for key, (en, es) in rows.items():
        texts = [en, es]
        if " · " in en and key.startswith("delete.yes"):
            texts = en.split(" · ") + es.split(" · ")
        where = html if key in ("noscript", "lang.en") else js
        for text in texts:
            assert text in where, f"{key}: {text!r}"
    # the widget borrows exactly these two from the page's t() (card.*.json calls the second one ui.bad_link)
    assert 'retry: "Try again"' in js and 'badlink: "This card link doesn' in js


def test_go_page_strings_follow_ui_spec_a71() -> None:
    js = read(GO / "go.js")
    for key, (en, es) in spec_table("### A7.1 `/go`").items():
        assert en in js and es in js, key


@pytest.mark.parametrize("page", [CARD / "index.html", GO / "index.html"], ids=["card", "go"])
def test_page_head(page: Path) -> None:
    html = read(page)
    assert '<meta name="color-scheme" content="only light">' in html
    assert '<meta name="robots" content="noindex">' in html
    sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    assert sheets[0] == "/shared/tokens.css" and sheets[1] == "/shared/base.css"
    assert not re.search(r"<style|style=|\son[a-z]+=|<script(?![^>]*\bsrc=)", html)
    assert "prefers-color-scheme" not in html


def test_card_page_mounts_the_unlocked_part_under_the_hero() -> None:
    html = read(CARD / "index.html")
    scripts = re.findall(r'<script type="module" src="([^"]+)"', html)
    assert scripts == ["/unlocked/unlocked.js", "/card/card.js"]  # the widget sets window.GPUnlocked first
    assert '<link rel="stylesheet" href="/unlocked/unlocked.css">' in html
    assert re.search(r'<section id="hero"[^>]*></section>\s*<section id="unlocked" hidden></section>', html)
    js = read(CARD / "card.js")
    assert "GPUnlocked.mount($(\"unlocked\"), view.unlocked, { token, lang: view.lang, t, onGone:" in js
    assert "GPUnlocked.render(view.unlocked)" in js
    assert 'id: b.id' in js  # each block section carries its CardBlock.id (#today_action)


def test_card_page_weight() -> None:
    own = sum(p.stat().st_size for p in [*PAGE_FILES, *SHARED_FILES])
    assert own <= 48_000, f"card page HTML + CSS + JS is {own} bytes (budget 48,000 without the widget)"
    widget = sum(p.stat().st_size for p in WIDGET_FILES if p.exists())
    assert own + widget <= 60_000 or widget > 12_000


@pytest.mark.parametrize("path", OWN, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_forbidden_phrases_or_dark_theme(path: Path) -> None:
    text = read(path)
    for phrase in (r"not eligible", r"ineligible", r"don'?t qualify", r"denied", r"no califica", r"no eres elegible"):
        assert not re.search(rf"\b{phrase}\b", text, re.IGNORECASE), phrase
    assert "prefers-color-scheme" not in text
    assert not re.search(r"remind", text, re.IGNORECASE) or path.suffix == ".js" and "reminders_url" in text


def test_icon_ids_exist_in_the_sprite() -> None:
    sprite = set(re.findall(r'id="([^"]+)"', read(WEB / "shared" / "icons.svg")))
    used = set()
    for path in OWN:
        text = read(path)
        used |= set(re.findall(r'"(i-[a-z-]+)"', text)) | set(re.findall(r"icons\.svg#([\w-]+)", text))
    assert used and used <= sprite, used - sprite


def test_a_stored_language_is_checked_before_use() -> None:
    """localStorage may hold anything: the card and code pages accept only en or es from it."""
    for path in (CARD / "card.js", GO / "go.js"):
        text = read(path)
        assert "localStorage.getItem(KEY)" in text
        assert re.search(r"/\^\(en\|es\)\$/\.exec\(localStorage\.getItem\(KEY\)\)", text), path.name


def test_no_browser_or_company_names_in_own_files() -> None:
    """Only the web talk disclosure may name the browsers' speech services (docs/UI_SPEC.md A0)."""
    names = re.compile(r"\b(" + "|".join(["chr" + "ome", "saf" + "ari", "fire" + "fox", "goo" + "gle", "app" + "le",
                                          "iph" + "one", "andr" + "oid"]) + r")\b", re.IGNORECASE)
    files = [*OWN, *sorted((ROOT / "gatorplate" / "card").glob("*.py")),
             *sorted((ROOT / "data" / "content").glob("card.*.json"))]
    for path in files:
        hit = names.search(read(path))
        assert hit is None, f"{path.name}: {hit.group(0) if hit else ''}"


def test_the_calendar_download_is_never_called_reminders() -> None:
    js = read(CARD / "card.js")
    assert 'download: "gatorplate-dates.ics"' in js
    assert "reminders" not in js.replace("reminders_url", "")


def test_code_field_takes_a_code_typed_with_spaces() -> None:
    """"4 8 1 2 0 6" (11 characters) must fit the field; the page ignores spaces and dashes (docs/UI_SPEC.md A7.1)."""
    html = read(GO / "index.html")
    m = re.search(r'id="code"[^>]*maxlength="(\d+)"', html)
    assert m and int(m.group(1)) >= len("4 8 1 2 0 6")
    assert 'inputmode="numeric"' in html and 'autocomplete="one-time-code"' in html
