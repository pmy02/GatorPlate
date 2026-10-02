#!/usr/bin/env python3
"""Generic public leak check for the GatorPlate repository (standard library only).

Scans the text files that `git add -A` would stage: it walks the tree and skips .git/, .build/, .claude/, .venv/,
var/, caches and the other .gitignore patterns (no git call without --git-history). Binary files are skipped.

Rules (generic only; project-specific terms are checked by the owner's private checker outside the repository):
  hangul       Hangul anywhere in a text file.
  local_path   an absolute path into a home directory (macOS, Linux, Windows) or a tilde path into a home-folder
               directory such as Desktop, Documents or Downloads. The repository uses relative paths only.
  secret       private-key blocks; provider-style key prefixes; JWT-like tokens; hosting-platform tokens; an
               assignment of a literal of 12+ key characters to a name that contains API_KEY, AUTH_TOKEN,
               ACCESS_TOKEN, SECRET, PASSCODE, PASSWORD or PRIVATE (any case). A value that is itself a GP_* name is
               not a secret; the public development and test values are allowed by exact value.
  env_file     a .env file in the tree (only .env.example, with names, may exist).
  email        an email address other than calfresh@sfsu.edu and noreply addresses.
  phone        a US-style phone number written with separators or parentheses (or +1 and such a number) other
               than the numbers in data/content/contacts.json, 988 and 911 (--allow-phone adds one).
With --git-history the rules also run over `git log -p --all` and the author and committer emails, after checking
that `git -C <root> rev-parse --show-toplevel` is exactly the root.

Output: rule id and file:line only, never the matched text. Exit status 1 on any finding.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {".git", ".build", ".claude", ".venv", "var", "__pycache__", ".pytest_cache", ".ruff_cache",
             "node_modules"}
SKIP_FILE_PATTERNS = ["*.db", "*.sqlite*", ".DS_Store", "*.pyc", "CLAUDE.md", "CLAUDE.local.md", "AGENTS.md"]
BINARY_SUFFIXES = {".woff2", ".woff", ".ttf", ".otf", ".eot", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf",
                   ".zip", ".gz", ".db", ".sqlite", ".pyc"}

HANGUL = re.compile("[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff\uffa0-\uffdc]")

# Built from pieces so this file does not match itself.
_HOME_MAC = "/" + "Users" + "/"
_HOME_LINUX = "/" + "home" + "/"
_HOME_DIRS = "(?:" + "|".join(["Desk" + "top", "Docu" + "ments", "Down" + "loads"]) + ")"
LOCAL_PATH = re.compile(
    re.escape(_HOME_MAC) + r"[A-Za-z0-9._-]+"
    + "|" + re.escape(_HOME_LINUX) + r"[a-z_][a-z0-9._-]*/"
    + "|" + r"\b[A-Za-z]:\\" + "Users" + r"\\[A-Za-z0-9._ -]+"
    + "|" + r"~/" + _HOME_DIRS + r"\b"
)

SECRET_PATTERNS = [
    re.compile("-----BEGIN [A-Z ]*" + "PRIVATE KEY-----"),
    re.compile(r"(?<![A-Za-z0-9])s" + r"k-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])g" + r"h[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"(?<![A-Za-z0-9])A" + r"KIA[A-Z0-9]{16}(?![A-Z0-9])"),
    re.compile(r"ey" + r"J[A-Za-z0-9_-]+\.ey" + r"J[A-Za-z0-9_-]+"),
    re.compile(r"Fly" + r"V1 [A-Za-z0-9]"),
]
SECRET_NAME = re.compile(r"(?:API_KEY|AUTH_TOKEN|ACCESS_TOKEN|SECRET|PASSCODE|PASSWORD|PRIVATE)", re.IGNORECASE)
# NAME (optionally quoted) = or : then an optional quote and the literal.
ASSIGNMENT = re.compile(
    r"""(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)["']?\s*(?::|=)\s*(?:[A-Za-z_][\w\[\], .|]*\s*=\s*)?(?P<q>["'`]?)"""
    r"""(?P<value>[^\s"'`,;)}\]]*)""")
# Files whose unquoted values are literals (in code, an unquoted value is a name, not a literal).
CONFIG_SUFFIXES = {".env", ".example", ".toml", ".ini", ".cfg", ".yml", ".yaml", ".sh", ".txt", ".lock", ".conf"}
CONFIG_NAMES = {"Makefile", "Dockerfile", ".dockerignore", ".gitignore"}
SECRET_VALUE = re.compile(r"^[A-Za-z0-9_+/=.-]{12,}$")
GP_NAME = re.compile(r"^\$*\{?GP_[A-Z0-9_]+\}?$")
# Public development and test values (gatorplate/config.py dev defaults; contracts/examples/hmac_vectors.json).
ALLOWED_SECRET_VALUES = {"test-secret-do-not-use", "dev-session-secret", "dev"}

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ALLOWED_EMAILS = {"calfresh@sfsu.edu"}
PHONE = re.compile(r"(?<![\d.])(?:\+1[ .-]?)?(?:\(\d{3}\)\s?|\d{3}[ .-])\d{3}[ .-]\d{4}(?![\d])")
ALWAYS_ALLOWED_PHONES = {"988", "911"}


def load_contact_numbers(root: Path) -> set[str]:
    numbers: set[str] = set()
    path = root / "data" / "content" / "contacts.json"
    if not path.exists():
        return numbers

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            for m in PHONE.finditer(node):
                numbers.add(re.sub(r"\D", "", m.group(0))[-10:])

    walk(json.loads(path.read_text(encoding="utf-8")))
    return numbers


def skipped(rel_parts: tuple[str, ...]) -> bool:
    if any(part in SKIP_DIRS for part in rel_parts[:-1]):
        return True
    name = rel_parts[-1]
    if name in SKIP_DIRS:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in SKIP_FILE_PATTERNS)


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if skipped(rel.parts):
            continue
        yield path, rel


def read_text(path: Path) -> str | None:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return None
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class Checker:
    def __init__(self, root: Path, allow_phones: list[str]) -> None:
        self.root = root
        self.allowed_phones = load_contact_numbers(root) | {re.sub(r"\D", "", p)[-10:] for p in allow_phones}
        self.findings: list[tuple[str, str, int]] = []

    def add(self, rule: str, where: str, line: int) -> None:
        self.findings.append((rule, where, line))

    @staticmethod
    def bare_values_are_literals(where: str) -> bool:
        name = Path(where).name
        return name in CONFIG_NAMES or name.startswith(".env") or Path(where).suffix.lower() in CONFIG_SUFFIXES

    def scan_line(self, where: str, lineno: int, line: str) -> None:
        if HANGUL.search(line):
            self.add("hangul", where, lineno)
        if LOCAL_PATH.search(line):
            self.add("local_path", where, lineno)
        if any(p.search(line) for p in SECRET_PATTERNS):
            self.add("secret", where, lineno)
        else:
            for m in ASSIGNMENT.finditer(line):
                if not SECRET_NAME.search(m.group("name")):
                    continue
                value = m.group("value")
                if not value or GP_NAME.match(value) or value in ALLOWED_SECRET_VALUES:
                    continue
                if not m.group("q") and not self.bare_values_are_literals(where):
                    continue
                if SECRET_VALUE.match(value):
                    self.add("secret", where, lineno)
                    break
        for m in EMAIL.finditer(line):
            address = m.group(0).lower()
            if address in ALLOWED_EMAILS or "noreply" in address:
                continue
            self.add("email", where, lineno)
            break
        for m in PHONE.finditer(line):
            digits = re.sub(r"\D", "", m.group(0))[-10:]
            if digits in self.allowed_phones or digits in ALWAYS_ALLOWED_PHONES:
                continue
            self.add("phone", where, lineno)
            break

    def scan_text(self, where: str, text: str) -> None:
        for lineno, line in enumerate(text.splitlines(), start=1):
            self.scan_line(where, lineno, line)

    def scan_tree(self) -> None:
        for path, rel in iter_files(self.root):
            if rel.name == ".env":
                self.add("env_file", str(rel), 1)
                continue
            text = read_text(path)
            if text is not None:
                self.scan_text(str(rel), text)

    def scan_history(self) -> bool:
        top = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != self.root.resolve():
            print("leakcheck: --git-history needs the repository root itself; stopping", file=sys.stderr)
            return False
        log = subprocess.run(["git", "-C", str(self.root), "log", "-p", "--all", "--no-color"], capture_output=True,
                             text=True, errors="replace")
        self.scan_text("git-history", log.stdout)
        people = subprocess.run(["git", "-C", str(self.root), "log", "--all", "--format=%ae%n%ce"],
                                capture_output=True, text=True)
        for lineno, address in enumerate(people.stdout.splitlines(), start=1):
            address = address.strip().lower()
            if address and "noreply" not in address and address not in ALLOWED_EMAILS:
                self.add("email", "git-authors", lineno)
        return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT), help="repository root (default: this file's repository)")
    ap.add_argument("--git-history", action="store_true", help="also scan git history and author emails")
    ap.add_argument("--allow-phone", action="append", default=[], help="an extra allowed phone number")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    checker = Checker(root, args.allow_phone)
    checker.scan_tree()
    ok = True
    if args.git_history:
        ok = checker.scan_history()
    for rule, where, line in checker.findings:
        print(f"{rule} {where}:{line}")
    count = len(checker.findings)
    print(f"leakcheck: {count} finding{'s' if count != 1 else ''}")
    return 1 if count or not ok else 0


if __name__ == "__main__":
    sys.exit(main())
