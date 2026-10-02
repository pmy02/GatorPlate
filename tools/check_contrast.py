#!/usr/bin/env python3
"""Check GatorPlate's design system: contrast, token sync, light theme, color literals, one font family, icons, CSP.

Standard library only (Python 3.10+). Exit status 0 when every check passes, 1 otherwise.

Checks
  1. contrast   every pair in data/design/tokens.json "contrast_pairs" meets its minimum
                (WCAG 2.2 contrast ratio: "text" >= 4.5:1 (SC 1.4.3), "large" text >= 3:1 (SC 1.4.3),
                "ui" lines, borders and graphics >= 3:1 (SC 1.4.11)). Ratios are printed truncated to 2 decimals.
  2. coverage   every color token is used by at least one pair, or is listed in meta.decorative.
  3. css        web/shared/tokens.css defines every token as --gp-<key> in its first :root rule with
                exactly the same value, and defines no --gp-* property that tokens.json lacks; no stray text
                before :root. Every CSS file under web/: no comment that ends early ('*/' inside a comment) or
                never ends, and balanced braces (otherwise browsers drop the rules that follow).
  4. light      tokens.css declares "color-scheme: only light"; no file under web/ mentions prefers-color-scheme;
                no other CSS sets a different color-scheme; every HTML document under web/ has
                <meta name="color-scheme" content="only light">.
  5. literals   no color literal in .css/.js/.mjs/.svg files under web/ other than tokens.css: CSS #hex, color
                functions (rgb, hsl, hwb, lab, lch, oklab, oklch, color) and color names in color properties;
                JS quoted 6/8-digit #hex strings and color functions; SVG color attributes. Colors come from
                var(--gp-*) only.
  6. family     one font family (Archivo), no monospace font: no "mono" token in tokens.json; no
                monospace family (the generic monospace or ui-monospace, a family named "... Mono", or a common
                system monospace face) in the font tokens, in a font, font-family or custom property declaration of
                any CSS under web/ (tokens.css included), in HTML/SVG font attributes or styles, or in a JS string;
                no font file named Mono. Case codes: tokens.css has a .code rule with font-variant-numeric
                var(--gp-num) (which must contain tabular-nums), font-family var(--gp-font) if set, and
                letter-spacing var(--gp-tracking-code).
  7. fonts      @font-face appears only in tokens.css; every active @font-face src is a relative url() to an
                existing WOFF2 file (signature "wOF2") declared format("woff2"); every font file under web/ is WOFF2,
                is used by an active rule and has OFL.txt next to it; a family whose only active face is italic is
                not in --gp-font. tokens.json meta.fonts.files gives every font file a state that agrees with the
                disk, the active rules and the NOTICE.md font table:
                  present = the file exists, an active rule uses it, NOTICE.md has a table row for it, the note's
                            "version x.yyy" equals the row's version, and the row's copyright line is a line at
                            the top of the OFL.txt next to the file;
                  missing = no file, no active rule (no request for a missing file), a prepared rule inside a
                            comment in tokens.css, no NOTICE.md table row.
                (The version and copyright values themselves come from the font's name table and its release's
                OFL.txt; reading WOFF2 needs a Brotli decoder, which the standard library lacks, so the owner
                compares them when a font file is added or updated - docs/UI_SPEC.md A6.3.)
                Other CSS sets font-family only through var(--gp-font), var(--gp-font-italic) or inherit.
  8. icons      web/shared/icons.svg parses as SVG; every <symbol> has a unique id and a viewBox; the sprite has no
                license or copyright text (it is original work); every "icons.svg#id" reference in an
                .html/.js/.mjs/.css file under web/ names an existing symbol.
  9. csp        HTML under web/: no <style> element, no style="" attribute, no inline script (JSON data blocks are
                allowed), no on*="" event-handler attribute, no javascript: URL, no <base>, and no resource or form
                target on another site; CSS under web/: no @import and no url() to another site.

Usage
  python3 tools/check_contrast.py                 # all checks, table of pairs
  python3 tools/check_contrast.py --quiet         # failures and summary only
  python3 tools/check_contrast.py --matrix        # also print every text-color x background ratio (info)
  python3 tools/check_contrast.py --no-css --no-scan --no-assets --no-csp
  (--no-css skips 3, 4 and the case-code rule; --no-scan skips the web/ parts of 4, 5, 6 and 9; --no-assets skips
  7 and 8; the token parts of 6 always run.)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOKENS = ROOT / "data" / "design" / "tokens.json"
DEFAULT_CSS = ROOT / "web" / "shared" / "tokens.css"
DEFAULT_SCAN = ROOT / "web"
DEFAULT_NOTICE = ROOT / "NOTICE.md"
SPRITE_NAME = "icons.svg"
FONT_DIR_NAME = "fonts"

MINIMUM = {"text": 4.5, "large": 3.0, "ui": 3.0}
TOKEN_GROUPS = ("color", "font", "type", "space", "radius", "shadow", "motion", "effect", "size", "print")
HEX6 = re.compile(r"^#[0-9A-Fa-f]{6}$")
# Text colors and backgrounds for the --matrix report (information only, never a failure).
MATRIX_FG = ("text", "text-2", "text-3", "primary", "on-primary", "brand-ink",
             "likely-ink", "coord-ink", "other-ink", "yl-ink", "err-ink")
MATRIX_BG = ("bg", "surface", "sunken", "primary-tint", "likely-bg", "coord-bg", "other-bg", "yl-bg", "err-bg")
SKIP_DIRS = {"node_modules", "__pycache__"}

# CSS named colors (CSS Color 4), without transparent and currentcolor, which carry no color of their own.
_COLOR_NAMES_TEXT = (
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood "
    "cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod "
    "darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon "
    "darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray "
    "dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green "
    "greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon "
    "lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon "
    "lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen "
    "magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue "
    "mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy "
    "oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip "
    "peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown "
    "seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal "
    "thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen"
)
CSS_COLOR_NAMES = tuple(_COLOR_NAMES_TEXT.split())
COLOR_NAME = re.compile(r"(?<![\w-])(?:" + "|".join(CSS_COLOR_NAMES) + r")(?![\w-])", re.IGNORECASE)
# Properties whose values are colors (named colors are only flagged there; custom properties count too).
COLOR_PROP = re.compile(
    r"^(?:--[\w-]+|color|background(?:-color|-image)?|border(?:-(?:top|right|bottom|left|block|inline)"
    r"(?:-(?:start|end))?)?(?:-color)?|outline(?:-color)?|box-shadow|text-shadow|fill|stroke|caret-color|"
    r"accent-color|column-rule(?:-color)?|text-decoration(?:-color)?|text-emphasis(?:-color)?|scrollbar-color|"
    r"stop-color|flood-color|lighting-color|-webkit-tap-highlight-color)$",
    re.IGNORECASE,
)
COLOR_FN = r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\s*\("
CSS_HEX = r"#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3,4})(?![0-9A-Za-z_-])"
CSS_LITERAL = re.compile(CSS_HEX + "|" + COLOR_FN, re.IGNORECASE)
JS_LITERAL = re.compile(r"""["'`]#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6})["'`]|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\s*\(""",
                        re.IGNORECASE)
# A declaration: a property, a colon, and a value that ends with ";" or "}" (a selector would end with "{").
CSS_DECLARATION = re.compile(r"(?<![\w-])(--[\w-]+|-?[A-Za-z][\w-]*)\s*:\s*([^;{}]+?)\s*(?=[;}])")
SVG_COLOR_ATTR = re.compile(r"""\b(?:fill|stroke|stop-color|flood-color|lighting-color|color)\s*=\s*["']([^"']*)["']""",
                            re.IGNORECASE)
SVG_STYLE_ATTR = re.compile(r"""\bstyle\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
REMOTE = r"(?:https?:)?//"
# One font family: a monospace family is the generic keyword (monospace, ui-monospace), any family with the word
# "Mono" in its name, or a common system monospace face.
MONOSPACE = re.compile(
    r"(?<![\w-])(?:ui-)?monospace(?![\w-])"
    r"|(?<![A-Za-z0-9])mono(?![A-Za-z0-9])"
    r"|(?<![\w-])(?:menlo|consolas|monaco|courier(?:\s+new)?|lucida\s+console)(?![\w-])",
    re.IGNORECASE,
)
MONO_TOKEN = re.compile(r"(?:^|-)mono(?:-|$)", re.IGNORECASE)   # a token or custom property name like font-mono
JS_STRING = re.compile(r"""(["'`])((?:\\.|(?!\1)[^\\\n])*)\1""")
# Third-party license or copyright text in the icon sprite (the sprite is original work, so it has none).
LICENSE_TEXT = re.compile(r"\b(?:licen[cs]e[sd]?|copyright|spdx)\b|©", re.IGNORECASE)


def channel(c8: int) -> float:
    """sRGB channel (0-255) to linear light, WCAG 2.x relative luminance definition."""
    c = c8 / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def ratio(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def floor2(x: float) -> float:
    """Truncate to 2 decimals so a value is never rounded up past a threshold (4.496 -> 4.49)."""
    return int(x * 100) / 100


def load_tokens(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def flat_tokens(tokens: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for group in TOKEN_GROUPS:
        for key, value in tokens.get(group, {}).items():
            if key in out:
                raise SystemExit(f"tokens.json: key '{key}' appears in two groups")
            out[key] = str(value)
    return out


# ---------------------------------------------------------------------------------------------- helpers

def blank(match: re.Match) -> str:
    """Replace a comment with spaces but keep its line breaks, so offsets and line numbers stay right."""
    return re.sub(r"[^\n]", " ", match.group(0))


def strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", blank, css, flags=re.DOTALL)


def strip_html_comments(html: str) -> str:
    return re.sub(r"<!--.*?-->", blank, html, flags=re.DOTALL)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def web_files(scan_dir: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not scan_dir.exists():
        return []
    files = []
    for path in sorted(scan_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        parts = path.relative_to(scan_dir).parts
        if any(p in SKIP_DIRS or p.startswith(".") for p in parts):
            continue
        files.append(path)
    return files


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return path.name


def same(a: Path, b: Path) -> bool:
    return a.resolve() == b.resolve()


def without_var_and_strings(value: str) -> str:
    """Drop quoted strings, url(...) and var(--name) references so only literal words of a CSS value remain.

    A var() fallback is kept, because it is a literal too: var(--x, black) leaves "black"."""
    value = re.sub(r'"[^"]*"|\'[^\']*\'', " ", value)
    value = re.sub(r"url\([^)]*\)", " ", value, flags=re.IGNORECASE)
    previous = None
    while previous != value:  # var() can nest: var(--a, var(--b, white))
        previous = value
        value = re.sub(r"var\(\s*--[\w-]+\s*(?:,([^()]*))?\)", lambda m: " " + (m.group(1) or "") + " ", value,
                       flags=re.IGNORECASE)
    return value


def css_declarations(css: str):
    """Yield (offset, property, value) for every declaration in comment-free CSS, multi-line values included."""
    for m in CSS_DECLARATION.finditer(css):
        yield m.start(), m.group(1), m.group(2)


def tag_attrs(html: str):
    """Yield (offset, tag_name_lower, attribute_text) for every start tag."""
    for m in re.finditer(r"<([A-Za-z][A-Za-z0-9-]*)((?:\s[^<>]*?)?)\s*/?>", html):
        yield m.start(), m.group(1).lower(), m.group(2) or ""


def attr(attrs: str, name: str) -> str | None:
    m = re.search(r"(?:^|\s)" + re.escape(name) + r"""\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", attrs,
                  re.IGNORECASE)
    if not m:
        return None
    return next(g for g in m.groups() if g is not None)


# ---------------------------------------------------------------------------------------------- 1-3 tokens

def check_contrast(tokens: dict, quiet: bool) -> list[str]:
    colors = tokens.get("color", {})
    errors: list[str] = []
    bad = [k for k, v in colors.items() if not HEX6.match(str(v))]
    for key in bad:
        errors.append(f"color.{key} = {colors[key]!r} is not a #RRGGBB value")
    pairs = tokens.get("contrast_pairs", [])
    if not pairs:
        errors.append("tokens.json has no contrast_pairs")
    seen = set()
    rows = []
    for i, pair in enumerate(pairs):
        fg, bg, kind = pair.get("fg"), pair.get("bg"), pair.get("kind")
        where = f"contrast_pairs[{i}] ({fg} on {bg})"
        if kind not in MINIMUM:
            errors.append(f"{where}: kind must be one of {sorted(MINIMUM)}")
            continue
        if fg not in colors or bg not in colors:
            errors.append(f"{where}: unknown color token")
            continue
        if (fg, bg) in seen:
            errors.append(f"{where}: duplicate pair")
        seen.add((fg, bg))
        if fg in bad or bg in bad:
            continue
        r = ratio(colors[fg], colors[bg])
        need = MINIMUM[kind]
        ok = r >= need
        rows.append((ok, fg, bg, kind, floor2(r), need, pair.get("use", "")))
        if not ok:
            errors.append(f"{where}: {floor2(r):.2f}:1 is below {need}:1 for {kind}")
    if rows and not quiet:
        print(f"{'':2} {'foreground':<14} {'background':<14} {'kind':<6} {'ratio':>7}  {'min':>4}  use")
        for ok, fg, bg, kind, r, need, use in rows:
            print(f"{'ok' if ok else 'XX':2} {fg:<14} {bg:<14} {kind:<6} {r:>6.2f}:1 {need:>4}  {use}")
        print()
    return errors


def check_coverage(tokens: dict) -> list[str]:
    colors = tokens.get("color", {})
    used = set()
    for pair in tokens.get("contrast_pairs", []):
        used.add(pair.get("fg"))
        used.add(pair.get("bg"))
    decorative = set(tokens.get("meta", {}).get("decorative", []))
    errors = []
    for key in colors:
        if key not in used and key not in decorative:
            errors.append(f"color.{key} is in no contrast pair and not in meta.decorative")
    for key in decorative:
        if key not in colors:
            errors.append(f"meta.decorative lists unknown color '{key}'")
    return errors


def first_root_block(css: str) -> str | None:
    match = re.search(r"(^|[}\s;]):root\s*\{", css)
    if not match:
        return None
    start = match.end()
    depth = 1
    i = start
    while i < len(css) and depth:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
        i += 1
    return css[start:i - 1]


def norm(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    return value.lower() if HEX6.match(value) else value


def css_structure(path: Path) -> list[str]:
    """Comments that end early or never end, and unbalanced braces: a browser would drop the rules that follow."""
    css = strip_css_comments(read_text(path))
    errors = []
    for token, problem in (("*/", "a stray '*/' (a comment ended early, e.g. '*/' written inside a comment)"),
                           ("/*", "a comment that is never closed")):
        at = css.find(token)
        if at >= 0:
            errors.append(f"{rel(path)}:{line_of(css, at)}: {problem}; the text after it is parsed as CSS")
    depth = 0
    for i, ch in enumerate(css):
        depth += {"{": 1, "}": -1}.get(ch, 0)
        if depth < 0:
            errors.append(f"{rel(path)}:{line_of(css, i)}: '}}' without a matching '{{'")
            depth = 0
    if depth:
        errors.append(f"{rel(path)}: {depth} '{{' never closed")
    return errors


def check_css(tokens: dict, css_path: Path) -> list[str]:
    if not css_path.exists():
        return [f"{css_path} not found"]
    css = strip_css_comments(read_text(css_path))
    errors = css_structure(css_path)
    block = first_root_block(css)
    if block is None:
        return errors + [f"{css_path.name}: no :root rule"]
    root = re.search(r"(^|[}\s;]):root\s*\{", css)
    root_at = root.start() + len(root.group(1))
    before = css[:root_at]
    stray = before[max(before.rfind("}"), before.rfind(";")) + 1:]
    if stray.strip():
        errors.append(f"{css_path.name}:{line_of(css, root_at)}: text {stray.strip()[:40]!r} before :root makes "
                      f"its selector invalid, so browsers would drop every token")
    declared = {}
    for m in re.finditer(r"(--gp-[A-Za-z0-9-]+)\s*:\s*([^;]+);", block):
        if m.group(1) in declared:
            errors.append(f"{css_path.name}: {m.group(1)} declared twice in :root")
        declared[m.group(1)] = m.group(2)
    flat = flat_tokens(tokens)
    for key, value in flat.items():
        prop = f"--gp-{key}"
        if prop not in declared:
            errors.append(f"{css_path.name}: missing {prop} (tokens.json has {key})")
        elif norm(declared[prop]) != norm(value):
            errors.append(f"{css_path.name}: {prop} is {declared[prop].strip()!r}, tokens.json says {value!r}")
    for prop in declared:
        if prop[len("--gp-"):] not in flat:
            errors.append(f"{css_path.name}: {prop} is not in tokens.json")
    return errors


# ---------------------------------------------------------------------------------------------- 4 light theme

def check_light(css_path: Path) -> list[str]:
    """tokens.css itself: only light, no dark rule, no @import."""
    if not css_path.exists():
        return []
    css = strip_css_comments(read_text(css_path))
    errors = []
    if re.search(r"prefers-color-scheme", css):
        errors.append(f"{css_path.name}: has a prefers-color-scheme rule (light theme only)")
    if not re.search(r"color-scheme\s*:\s*only\s+light", css):
        errors.append(f"{css_path.name}: missing 'color-scheme: only light'")
    if re.search(r"@import", css):
        errors.append(f"{css_path.name}: has @import (fonts and styles are self-hosted <link>s)")
    return errors


def meta_color_scheme_ok(html: str) -> bool:
    for _, tag, attrs in tag_attrs(html):
        if tag == "meta" and (attr(attrs, "name") or "").strip().lower() == "color-scheme":
            return re.sub(r"\s+", " ", (attr(attrs, "content") or "").strip().lower()) == "only light"
    return False


def check_css_structure_web(scan_dir: Path, css_path: Path) -> list[str]:
    errors = []
    for path in web_files(scan_dir, (".css",)):
        if not same(path, css_path):
            errors += css_structure(path)
    return errors


def check_light_web(scan_dir: Path) -> list[str]:
    errors = []
    for path in web_files(scan_dir, (".css", ".js", ".mjs", ".html", ".htm", ".svg")):
        text = read_text(path)
        if path.suffix == ".css":
            text = strip_css_comments(text)
        for m in re.finditer(r"prefers-color-scheme", text):
            errors.append(f"{rel(path)}:{line_of(text, m.start())}: mentions prefers-color-scheme (light theme only)")
        if path.suffix == ".css":
            for off, prop, value in css_declarations(text):
                if prop.lower() == "color-scheme" and re.sub(r"\s+", " ", value.strip().lower()) != "only light":
                    errors.append(f"{rel(path)}:{line_of(text, off)}: color-scheme: {value.strip()} "
                                  f"(only 'only light' is allowed)")
        if path.suffix in (".html", ".htm"):
            html = strip_html_comments(text)
            if re.search(r"<html[\s>]", html, re.IGNORECASE) and not meta_color_scheme_ok(html):
                errors.append(f'{rel(path)}: missing <meta name="color-scheme" content="only light">')
    return errors


# ---------------------------------------------------------------------------------------------- 5 literals

def check_literals(scan_dir: Path, css_path: Path) -> list[str]:
    errors = []
    for path in web_files(scan_dir, (".css", ".js", ".mjs", ".svg")):
        if same(path, css_path):
            continue
        text = read_text(path)
        found: list[tuple[int, str]] = []
        if path.suffix == ".css":
            text = strip_css_comments(text)
            for off, prop, value in css_declarations(text):
                bare = re.sub(r'"[^"]*"|\'[^\']*\'', " ", value)
                bare = re.sub(r"url\([^)]*\)", " ", bare, flags=re.IGNORECASE)
                for m in CSS_LITERAL.finditer(bare):
                    found.append((off, m.group(0)))
                if COLOR_PROP.match(prop):
                    for m in COLOR_NAME.finditer(without_var_and_strings(value)):
                        found.append((off, m.group(0)))
        elif path.suffix == ".svg":
            text = strip_html_comments(text)
            for m in SVG_COLOR_ATTR.finditer(text):
                value = m.group(1)
                if CSS_LITERAL.search(value) or COLOR_NAME.search(value):
                    found.append((m.start(), value))
            for m in SVG_STYLE_ATTR.finditer(text):
                for _, prop, value in css_declarations(m.group(1) + ";"):
                    if CSS_LITERAL.search(value) or (COLOR_PROP.match(prop) and COLOR_NAME.search(value)):
                        found.append((m.start(), value.strip()))
        else:
            for m in JS_LITERAL.finditer(text):
                found.append((m.start(), m.group(0)))
        for off, literal in found:
            errors.append(f"{rel(path)}:{line_of(text, off)}: color literal {literal!r} "
                          f"(use var(--gp-*) from tokens.css)")
    return errors


# ---------------------------------------------------------------------------------------------- 6-7 fonts

def font_faces(css: str) -> list[dict]:
    """Every @font-face rule in a piece of comment-free CSS: offset, family, style and src (url, format) pairs."""
    faces = []
    for face in re.finditer(r"@font-face\s*\{([^}]*)\}", css):
        decls: dict[str, str] = {}
        for _, prop, value in css_declarations(face.group(1) + ";"):
            decls[prop.lower()] = value.strip()
        srcs = []
        for m in re.finditer(r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)\s*(?:format\(\s*['\"]?([\w-]+)['\"]?\s*\))?",
                             decls.get("src", "")):
            srcs.append((m.group(2).strip(), (m.group(3) or "").lower()))
        faces.append({
            "offset": face.start(),
            "family": decls.get("font-family", "").strip().strip("'\"").strip(),
            "style": (decls.get("font-style", "normal").split() or ["normal"])[0].lower(),
            "has_src": "src" in decls,
            "srcs": srcs,
        })
    return faces


def prepared_faces(raw_css: str) -> list[dict]:
    """@font-face rules that sit inside a comment (prepared, inactive)."""
    faces = []
    for comment in re.finditer(r"/\*(.*?)\*/", raw_css, flags=re.DOTALL):
        faces += font_faces(comment.group(1))
    return faces


def font_target(url: str, css_path: Path, scan_dir: Path) -> Path:
    return (scan_dir / url.lstrip("/")) if url.startswith("/") else (css_path.parent / url)


def family_list(stack: str) -> list[str]:
    return [f.strip().strip("'\"").strip().lower() for f in stack.split(",") if f.strip()]


def notice_font_rows(notice_path: Path) -> dict[str, str] | None:
    """Font file paths named in a table row of NOTICE.md (`...woff2` in a line that starts with "|"), with that row."""
    if not notice_path.exists():
        return None
    rows: dict[str, str] = {}
    for line in read_text(notice_path).splitlines():
        if line.lstrip().startswith("|"):
            for m in re.finditer(r"`([^`\s]+\.(?:woff2|woff|ttf|otf|eot))`", line, re.IGNORECASE):
                rows[m.group(1)] = line
    return rows


def ofl_copyright_lines(ofl_path: Path) -> set[str]:
    """The copyright lines at the top of an OFL.txt (every line before the license statement)."""
    if not ofl_path.exists():
        return set()
    lines = set()
    for line in read_text(ofl_path).splitlines():
        if line.startswith("This Font Software is licensed"):
            break
        if line.strip():
            lines.add(line.strip())
    return lines


def check_present_font_record(file_name: str, note: str, row: str | None, where: str, notice_name: str) -> list[str]:
    """A present file: its version in tokens.json equals its NOTICE.md row; the row's copyright line is in OFL.txt."""
    if row is None:
        return []
    errors = []
    version = re.search(r"\bversion\s+(\d+\.\d+)\b", note, re.IGNORECASE)
    row_versions = set(re.findall(r"\bversion\s+(\d+\.\d+)\b", row, re.IGNORECASE))
    if not version:
        errors.append(f"{where}: a present note must give the font's version (\"version <x.yyy>\", from its name "
                      f"table)")
    elif row_versions != {version.group(1)}:
        errors.append(f"{where}: version {version.group(1)}, but the {notice_name} row says "
                      f"{', '.join(sorted(row_versions)) or 'no version'} (compare with the font's release)")
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    notice_copyright = next((c for c in cells if c.startswith("Copyright")), None)
    ofl = (ROOT / file_name).parent / "OFL.txt"
    if notice_copyright is None:
        errors.append(f"{notice_name}: the row for {file_name} has no Copyright column text")
    elif notice_copyright not in ofl_copyright_lines(ofl):
        errors.append(f"{notice_name}: the copyright line of {file_name} ({notice_copyright[:60]!r}...) is not a line "
                      f"at the top of {rel(ofl)} (use the first line of the release's OFL.txt in both places)")
    return errors


def is_woff2(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(4) == b"wOF2"


def check_fonts(tokens: dict, css_path: Path, scan_dir: Path, notice_path: Path) -> list[str]:
    errors: list[str] = []
    if not css_path.exists():
        return errors
    raw = read_text(css_path)
    css = strip_css_comments(raw)
    name = css_path.name

    # Active @font-face rules: self-hosted WOFF2 files that exist.
    active: dict[Path, str] = {}
    faces = font_faces(css)
    for face in faces:
        where = f"{name}:{line_of(css, face['offset'])}"
        if not face["has_src"]:
            errors.append(f"{where}: @font-face without src")
        if not face["family"]:
            errors.append(f"{where}: @font-face without font-family")
        for url, fmt in face["srcs"]:
            if re.match(REMOTE, url) or url.startswith("data:"):
                errors.append(f"{where}: font source {url!r} is not a self-hosted file")
                continue
            if fmt != "woff2":
                errors.append(f"{where}: {url} must be declared with format(\"woff2\")")
            target = font_target(url, css_path, scan_dir)
            active[target.resolve()] = url
            if not target.exists():
                errors.append(f"{where}: @font-face src {url!r} does not exist ({rel(target)}); keep the rule "
                              f"commented out until the file is added")
            elif not is_woff2(target):
                errors.append(f"{rel(target)}: not a WOFF2 file (the file must start with 'wOF2')")
    prepared = {font_target(url, css_path, scan_dir).resolve()
                for face in prepared_faces(raw) for url, _ in face["srcs"]
                if not (re.match(REMOTE, url) or url.startswith("data:"))}

    # A family whose only active face is italic must not be in the upright stack: every upright letter in that family
    # would be drawn with the italic face.
    styles: dict[str, set[str]] = {}
    for face in faces:
        if face["family"]:
            styles.setdefault(face["family"].lower(), set()).add(face["style"])
    upright = family_list(str(tokens.get("font", {}).get("font", "")))
    for family, found in styles.items():
        if family in upright and not (found - {"italic", "oblique"}):
            errors.append(f"{name}: the family '{family}' has only an italic face but is in --gp-font; upright text "
                          f"would render in italics (activate the upright face's rule first)")

    # Font files on disk.
    font_files = web_files(scan_dir, (".woff2", ".woff", ".ttf", ".otf", ".eot"))
    for path in font_files:
        if path.suffix.lower() != ".woff2":
            errors.append(f"{rel(path)}: only WOFF2 fonts are served (convert it or remove it)")
        elif not is_woff2(path):
            errors.append(f"{rel(path)}: not a WOFF2 file (the file must start with 'wOF2')")
        if path.resolve() not in active:
            errors.append(f"{rel(path)}: no active @font-face rule in {name} uses this file (uncomment its prepared "
                          f"rule)")
        if not (path.parent / "OFL.txt").exists():
            errors.append(f"{rel(path)}: the font license OFL.txt must sit next to the font")

    # tokens.json meta.fonts.files: one state per file, matching the disk, the active rules and NOTICE.md.
    files_meta = tokens.get("meta", {}).get("fonts", {}).get("files", {})
    if not files_meta:
        errors.append("tokens.json meta.fonts.files is missing or empty")
    notice_rows = notice_font_rows(notice_path)
    if notice_rows is None:
        errors.append(f"{notice_path.name} not found (it lists the font and its license)")
        notice_rows = {}
    meta_paths: set[Path] = set()
    for file_name, note in files_meta.items():
        path = ROOT / file_name
        meta_paths.add(path.resolve())
        where = f"tokens.json meta.fonts.files[{file_name!r}]"
        state = str(note).split(":", 1)[0].strip().lower()
        exists = path.exists()
        is_active = path.resolve() in active
        in_notice = file_name in notice_rows
        if state not in ("present", "missing"):
            errors.append(f"{where}: the note must start with 'present:' or 'missing:'")
        elif state == "present":
            if not exists:
                errors.append(f"{where}: marked present but the file does not exist")
            if not is_active:
                errors.append(f"{where}: marked present but no active @font-face rule in {name} uses it "
                              f"(uncomment its prepared rule)")
            if not in_notice:
                errors.append(f"{where}: marked present but {notice_path.name} has no table row for it")
            errors += check_present_font_record(file_name, str(note), notice_rows.get(file_name), where,
                                                notice_path.name)
        else:
            if exists:
                errors.append(f"{where}: the file now exists; add its active @font-face rule in {name}, mark it "
                              f"present here and add its {notice_path.name} row (docs/UI_SPEC.md A6.3)")
            if is_active:
                errors.append(f"{where}: marked missing but an active @font-face rule requests it; keep that rule "
                              f"commented out until the file is added")
            elif path.resolve() not in prepared:
                errors.append(f"{where}: marked missing but {name} has no prepared (commented-out) @font-face rule "
                              f"for it")
            if in_notice:
                errors.append(f"{where}: marked missing but {notice_path.name} lists it in a table row")
    for target, url in active.items():
        if target not in meta_paths:
            errors.append(f"{name}: @font-face src {url!r} is not listed in tokens.json meta.fonts.files")
    for path in font_files:
        if path.resolve() not in meta_paths:
            errors.append(f"{rel(path)}: not listed in tokens.json meta.fonts.files")
    for row in sorted(notice_rows):
        if (ROOT / row).resolve() not in meta_paths:
            errors.append(f"{notice_path.name}: the table row for {row} has no entry in tokens.json meta.fonts.files")

    # Other style sheets: no @font-face, and font-family only through the font tokens.
    for path in web_files(scan_dir, (".css",)):
        if same(path, css_path):
            continue
        text = strip_css_comments(read_text(path))
        for m in re.finditer(r"@font-face", text):
            errors.append(f"{rel(path)}:{line_of(text, m.start())}: @font-face belongs in {name} only")
        for off, prop, value in css_declarations(text):
            if prop.lower() != "font-family":
                continue
            rest = without_var_and_strings(value).strip(" ,").lower()
            if rest not in ("", "inherit", "initial", "unset", "revert", "revert-layer") or re.search(r"['\"]", value):
                errors.append(f"{rel(path)}:{line_of(text, off)}: font-family {value.strip()!r} "
                              f"(use var(--gp-font) or var(--gp-font-italic))")
    return errors


def check_case_codes(tokens: dict, css_path: Path) -> list[str]:
    """Case codes (.code) use the text family with tabular figures and the code tracking token."""
    errors = []
    if "tabular-nums" not in str(tokens.get("font", {}).get("num", "")).split():
        errors.append("tokens.json font.num must contain tabular-nums (amounts and case codes use tabular figures)")
    if "tracking-code" not in tokens.get("type", {}):
        errors.append("tokens.json type.tracking-code is missing (letter spacing of case codes)")
    if not css_path.exists():
        return errors
    css = strip_css_comments(read_text(css_path))
    decls: dict[str, str] = {}
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        if re.search(r"\.code(?![\w-])", rule.group(1)):
            for _, prop, value in css_declarations(rule.group(2) + ";"):
                decls[prop.lower()] = re.sub(r"\s+", " ", value.strip())
    if not decls:
        return errors + [f"{css_path.name}: no .code rule (case codes need tabular figures and the code tracking)"]
    numeric = decls.get("font-variant-numeric", "")
    if "var(--gp-num)" not in numeric and "tabular-nums" not in numeric.split():
        errors.append(f"{css_path.name}: .code must set font-variant-numeric: var(--gp-num) (tabular figures)")
    if decls.get("font-family", "var(--gp-font)") != "var(--gp-font)":
        errors.append(f"{css_path.name}: .code font-family is {decls['font-family']!r}; case codes use the text "
                      f"family, var(--gp-font)")
    if decls.get("letter-spacing") != "var(--gp-tracking-code)":
        errors.append(f"{css_path.name}: .code must set letter-spacing: var(--gp-tracking-code)")
    return errors


def font_value_hits(css: str) -> list[tuple[int, str]]:
    """(offset, problem) for monospace families in font declarations and custom properties of comment-free CSS."""
    hits = []
    for off, prop, value in css_declarations(css):
        p = prop.lower()
        if p.startswith("--") and MONO_TOKEN.search(p):
            hits.append((off, f"custom property {prop}"))
        if p in ("font-family", "font") or p.startswith("--"):
            m = MONOSPACE.search(value)
            if m:
                hits.append((off, f"{prop}: {value.strip()!r} names {m.group(0)!r}"))
    return hits


def check_no_monospace(tokens: dict, scan_dir: Path, scan: bool) -> list[str]:
    """One font family: no monospace family in the tokens or anywhere under web/."""
    errors = []
    why = "(one font family; case codes use tabular figures)"
    for group in TOKEN_GROUPS:
        for key in tokens.get(group, {}):
            if MONO_TOKEN.search(key):
                errors.append(f"tokens.json {group}.{key}: no monospace font token {why}")
    for key, value in tokens.get("font", {}).items():
        m = MONOSPACE.search(str(value))
        if m:
            errors.append(f"tokens.json font.{key}: names the monospace family {m.group(0)!r} {why}")
    for file_name in tokens.get("meta", {}).get("fonts", {}).get("files", {}):
        if "mono" in Path(file_name).name.lower():
            errors.append(f"tokens.json meta.fonts.files: {file_name} is a monospace font {why}")
    if not scan:
        return errors
    for path in web_files(scan_dir, (".woff2", ".woff", ".ttf", ".otf", ".eot")):
        if "mono" in path.name.lower():
            errors.append(f"{rel(path)}: monospace font file {why}")
    for path in web_files(scan_dir, (".css",)):
        css = strip_css_comments(read_text(path))
        for off, problem in font_value_hits(css):
            errors.append(f"{rel(path)}:{line_of(css, off)}: {problem} {why}")
    for path in web_files(scan_dir, (".html", ".htm", ".svg")):
        html = strip_html_comments(read_text(path))
        for m in re.finditer(r"<style[^>]*>(.*?)</style\s*>", html, flags=re.DOTALL | re.IGNORECASE):
            body = strip_css_comments(m.group(1))
            for off, problem in font_value_hits(body):
                errors.append(f"{rel(path)}:{line_of(html, m.start(1) + off)}: {problem} {why}")
        for off, tag, attrs in tag_attrs(html):
            values = [v for v in (attr(attrs, "font-family"), attr(attrs, "face")) if v]
            style = attr(attrs, "style")
            problems = [f"<{tag}> {problem}" for _, problem in font_value_hits(style + ";")] if style else []
            problems += [f"<{tag}> font {v!r} names {MONOSPACE.search(v).group(0)!r}" for v in values
                         if MONOSPACE.search(v)]
            for problem in problems:
                errors.append(f"{rel(path)}:{line_of(html, off)}: {problem} {why}")
    for path in web_files(scan_dir, (".js", ".mjs")):
        text = read_text(path)
        for m in JS_STRING.finditer(text):
            hit = MONOSPACE.search(m.group(2))
            if hit:
                errors.append(f"{rel(path)}:{line_of(text, m.start())}: string {m.group(0)[:60]!r} names "
                              f"{hit.group(0)!r} {why}")
    return errors


# ---------------------------------------------------------------------------------------------- 8 icons

def sprite_ids(sprite: Path) -> tuple[set[str], list[str]]:
    errors: list[str] = []
    try:
        root = ET.parse(sprite).getroot()
    except ET.ParseError as exc:
        return set(), [f"{rel(sprite)}: not well-formed XML ({exc})"]
    ns = "{http://www.w3.org/2000/svg}"
    if root.tag != ns + "svg":
        errors.append(f"{rel(sprite)}: root element must be <svg xmlns=\"http://www.w3.org/2000/svg\">")
    ids: set[str] = set()
    for symbol in root.iter(ns + "symbol"):
        sid = symbol.get("id")
        if not sid:
            errors.append(f"{rel(sprite)}: a <symbol> has no id")
            continue
        if sid in ids:
            errors.append(f"{rel(sprite)}: symbol id '{sid}' appears twice")
        ids.add(sid)
        box = (symbol.get("viewBox") or "").split()
        if len(box) != 4 or not all(re.fullmatch(r"-?\d+(\.\d+)?", n) for n in box):
            errors.append(f"{rel(sprite)}: symbol '{sid}' needs a viewBox of four numbers")
        if len(list(symbol)) == 0:
            errors.append(f"{rel(sprite)}: symbol '{sid}' is empty")
    if not ids:
        errors.append(f"{rel(sprite)}: no <symbol> elements")
    return ids, errors


def check_icons(scan_dir: Path, sprite: Path) -> list[str]:
    if not sprite.exists():
        return [f"{rel(sprite)} not found"]
    ids, errors = sprite_ids(sprite)
    raw = read_text(sprite)
    for m in LICENSE_TEXT.finditer(raw):
        errors.append(f"{rel(sprite)}:{line_of(raw, m.start())}: {m.group(0)!r} - the sprite is original work with no "
                      f"third-party license or copyright text; third-party icons need an owner decision first")
    for path in web_files(scan_dir, (".html", ".htm", ".js", ".mjs", ".css")):
        text = read_text(path)
        for m in re.finditer(re.escape(SPRITE_NAME) + r"#([A-Za-z0-9_-]+)", text):
            if m.group(1) not in ids:
                errors.append(f"{rel(path)}:{line_of(text, m.start())}: icon '#{m.group(1)}' is not in {SPRITE_NAME}")
    return errors


# ---------------------------------------------------------------------------------------------- 9 csp

RESOURCE_TAGS = {"script", "link", "img", "iframe", "frame", "source", "video", "audio", "embed", "object", "track",
                 "input"}
RESOURCE_ATTRS = ("src", "href", "srcset", "data", "poster", "action", "formaction")


def check_csp(scan_dir: Path) -> list[str]:
    errors = []
    for path in web_files(scan_dir, (".html", ".htm")):
        html = strip_html_comments(read_text(path))
        where = rel(path)
        for m in re.finditer(r"<style[\s>]", html, re.IGNORECASE):
            errors.append(f"{where}:{line_of(html, m.start())}: <style> element (CSP style-src 'self': use a .css file)")
        for m in re.finditer(r"<base[\s>]", html, re.IGNORECASE):
            errors.append(f"{where}:{line_of(html, m.start())}: <base> element (CSP base-uri 'none')")
        for off, tag, attrs in tag_attrs(html):
            line = line_of(html, off)
            if re.search(r"(?:^|\s)style\s*=", attrs, re.IGNORECASE):
                errors.append(f"{where}:{line}: style=\"\" attribute on <{tag}> (CSP: use a class or "
                              f"element.style.setProperty())")
            handler = re.search(r"(?:^|\s)(on[a-z]+)\s*=", attrs, re.IGNORECASE)
            if handler:
                errors.append(f"{where}:{line}: {handler.group(1)}=\"\" on <{tag}> (CSP: use addEventListener)")
            if re.search(r"""(?:^|\s)(?:href|src|action|formaction)\s*=\s*["']?\s*javascript:""", attrs, re.IGNORECASE):
                errors.append(f"{where}:{line}: javascript: URL on <{tag}>")
            if tag == "script" and attr(attrs, "src") is None:
                kind = (attr(attrs, "type") or "").strip().lower()
                if "json" not in kind or "importmap" in kind:
                    errors.append(f"{where}:{line}: inline <script> (CSP script-src 'self': use a .js file)")
            if tag in RESOURCE_TAGS or tag == "form":
                for name in RESOURCE_ATTRS:
                    value = attr(attrs, name)
                    if value and re.match(r"\s*" + REMOTE, value):
                        errors.append(f"{where}:{line}: <{tag} {name}=\"{value.strip()}\"> loads from another site "
                                      f"(CSP 'self')")
    for path in web_files(scan_dir, (".css",)):
        css = strip_css_comments(read_text(path))
        for m in re.finditer(r"@import", css):
            errors.append(f"{rel(path)}:{line_of(css, m.start())}: @import (link each stylesheet; no remote CSS)")
        for m in re.finditer(r"url\(\s*['\"]?\s*" + REMOTE, css, re.IGNORECASE):
            errors.append(f"{rel(path)}:{line_of(css, m.start())}: url() to another site (CSP 'self')")
    return errors


# ---------------------------------------------------------------------------------------------- report

def print_matrix(tokens: dict) -> None:
    colors = tokens.get("color", {})
    fgs = [k for k in MATRIX_FG if k in colors]
    bgs = [k for k in MATRIX_BG if k in colors]
    print("Contrast matrix (information only; only contrast_pairs are allowed in the UI)")
    print(f"{'':12}" + "".join(f"{b[:11]:>12}" for b in bgs))
    for f in fgs:
        cells = "".join(f"{floor2(ratio(colors[f], colors[b])):>12.2f}" for b in bgs)
        print(f"{f:<12}{cells}")
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tokens", type=Path, default=DEFAULT_TOKENS)
    ap.add_argument("--css", type=Path, default=DEFAULT_CSS)
    ap.add_argument("--scan", type=Path, default=DEFAULT_SCAN, help="the web folder (pages, styles, scripts, assets)")
    ap.add_argument("--notice", type=Path, default=DEFAULT_NOTICE, help="the third-party notices (font table)")
    ap.add_argument("--no-css", action="store_true", help="skip the tokens.css sync and its light-theme check")
    ap.add_argument("--no-scan", action="store_true", help="skip the checks that read other files under web/")
    ap.add_argument("--no-assets", action="store_true", help="skip the font and icon checks")
    ap.add_argument("--no-csp", action="store_true", help="skip the CSP check of HTML and CSS under web/")
    ap.add_argument("--matrix", action="store_true", help="print all text x background ratios (info)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    tokens = load_tokens(args.tokens)
    errors: list[str] = []
    errors += check_contrast(tokens, args.quiet)
    errors += check_coverage(tokens)
    if not args.no_css:
        errors += check_css(tokens, args.css)
        errors += check_light(args.css)
    if not args.no_scan:
        errors += check_css_structure_web(args.scan, args.css)
        errors += check_light_web(args.scan)
        errors += check_literals(args.scan, args.css)
    errors += check_no_monospace(tokens, args.scan, not args.no_scan)
    if not args.no_css:
        errors += check_case_codes(tokens, args.css)
    if not args.no_assets:
        errors += check_fonts(tokens, args.css, args.scan, args.notice)
        errors += check_icons(args.scan, args.css.parent / SPRITE_NAME)
    if not args.no_csp and not args.no_scan:
        errors += check_csp(args.scan)
    if args.matrix:
        print_matrix(tokens)

    n_pairs = len(tokens.get("contrast_pairs", []))
    if errors:
        print(f"FAIL: {len(errors)} problem(s) ({n_pairs} contrast pairs checked)")
        for e in errors:
            print(f"  - {e}")
        return 1
    passed = [f"{n_pairs} contrast pairs meet WCAG 2.2 AA"]
    if not args.no_css:
        passed += ["tokens.json and tokens.css agree", "case codes use tabular figures"]
    passed.append("one font family, no monospace" + ("" if args.no_scan else " under web/"))
    if not args.no_scan:
        passed += ["light theme only", "no color literals outside tokens.css"]
    if not args.no_assets:
        passed.append("font files, tokens.json, @font-face rules and NOTICE.md agree; icons resolve")
    if not args.no_csp and not args.no_scan:
        passed.append("pages are CSP-safe")
    print("OK: " + "; ".join(passed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
