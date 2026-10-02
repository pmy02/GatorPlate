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
that `git -C <root> rev-parse --show-toplevel` is exactly the root. The log is read as a diff, not as plain text: every
added or removed line is scanned without its one-character diff prefix and under the path of the file it belongs to
(so the config-file rule for unquoted values applies as in the tree scan), a .env file added or changed in any commit
is an env_file finding, and commit headers, messages and diff headers are scanned as they are. History findings are
named `git:<commit>:<path>:<line>` (an added line, as in `git show <commit>:<path>`), `git:<commit>^:<path>:<line>` (a
removed line, in the parent's file) or `git:<commit>:<line>` (a header or message line, counted from the commit line).

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

# `git log -p` read as a diff: explicit options, so the reader does not depend on the user's git configuration
# (pretty format, decorations, path quoting, blank context lines, prefixes, textconv filters; the root commit's diff
# with --root whatever log.showRoot says, and merge resolutions as dense combined diffs with --cc).
GIT_LOG_ARGS = ["-c", "core.quotePath=false", "-c", "diff.suppressBlankEmpty=false",
                "log", "-p", "--root", "--cc", "--all", "--no-color", "--no-decorate", "--format=fuller",
                "--no-textconv", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/"]
# A hunk header: "@@ -a,b +c,d @@" (one parent) or "@@@ -a,b -c,d +e,f @@@" (a combined diff with two parents).
HUNK_HEADER = re.compile(r"^(?P<at>@@+) (?P<ranges>[-+][0-9, +-]*?) (?P=at)(?: |$)")
_C_ESCAPES = {"a": "\a", "b": "\b", "t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}
_OCTAL = re.compile(r"[0-7]{3}")


def unquote_git_path(raw: str) -> str:
    """A path as git prints it in diff headers: C-quoted when it holds special characters, and followed by a tab
    when it holds a space."""
    raw = raw.removesuffix("\t")
    if len(raw) < 2 or not (raw.startswith('"') and raw.endswith('"')):
        return raw
    body, out, i = raw[1:-1], bytearray(), 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and _OCTAL.match(body, i + 1):
            out.append(int(body[i + 1:i + 4], 8))
            i += 4
        elif ch == "\\" and i + 1 < len(body) and body[i + 1] in _C_ESCAPES:
            out += _C_ESCAPES[body[i + 1]].encode("utf-8")
            i += 2
        else:
            out += ch.encode("utf-8")
            i += 1
    return out.decode("utf-8", errors="replace")


def diff_header_path(raw: str) -> str | None:
    """The repository path of a `--- a/<path>` or `+++ b/<path>` header (None for /dev/null)."""
    path = unquote_git_path(raw)
    if path == "/dev/null":
        return None
    return path[2:] if path.startswith(("a/", "b/")) else path


class Hunk:
    """Line bookkeeping for one hunk: how many lines each side still has, and the next line number on each side."""

    def __init__(self, header: str) -> None:
        m = HUNK_HEADER.match(header)
        if m is None:
            raise ValueError("not a hunk header")
        self.parents = len(m.group("at")) - 1
        self.old_no: list[int] = []
        self.old_left: list[int] = []
        self.new_no = self.new_left = 0
        for token in m.group("ranges").split():
            start, _, count = token[1:].partition(",")
            first, size = int(start or "0"), int(count) if count else 1
            if token.startswith("-"):
                self.old_no.append(first)
                self.old_left.append(size)
            else:
                self.new_no, self.new_left = first, size
        if len(self.old_no) != self.parents:
            raise ValueError("hunk header ranges do not match its parents")

    def done(self) -> bool:
        return self.new_left <= 0 and all(left <= 0 for left in self.old_left)

    def take(self, raw: str) -> tuple[str, str, int, int] | None:
        """Consume one content line and return (kind, text without the diff prefix, line number, parent index).
        kind is "added" (a line of the new file; the number is in the new file), "removed" (the number is in the file
        of the parent with that index) or "context" (unchanged; not scanned). None: `raw` is not a content line."""
        raw = raw or " " * self.parents  # an empty context line printed without its space
        prefix, text = raw[:self.parents], raw[self.parents:]
        if len(prefix) < self.parents or any(mark not in " +-" for mark in prefix):
            return None
        # One column per parent: "-" = in that parent, not in the result; "+" = in the result, not in that parent;
        # " " = in both for a line of the result, in neither for a removed line (combined diffs).
        in_new = "-" not in prefix
        result: tuple[str, str, int, int] = ("context", text, self.new_no, 0)
        if in_new and "+" in prefix:
            result = ("added", text, self.new_no, 0)
        if in_new:
            self.new_no += 1
            self.new_left -= 1
        for i, mark in enumerate(prefix):
            if mark == "-" or (mark == " " and in_new):
                if mark == "-" and result[0] == "context":
                    result = ("removed", text, self.old_no[i], i)
                self.old_no[i] += 1
                self.old_left[i] -= 1
        return result


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

    def scan_line(self, where: str, lineno: int, line: str, path: str | None = None) -> None:
        """Scan one line. `where` is the location printed with a finding; `path` (default: `where`) is the file path
        that decides whether unquoted values are literals."""
        literal_bare_values = self.bare_values_are_literals(where if path is None else path)
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
                if not m.group("q") and not literal_bare_values:
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

    def scan_log(self, text: str) -> None:
        """Scan the output of `git log -p` (GIT_LOG_ARGS). Hunk line counts decide what is content, so a content line
        that looks like a header (a removed "-- x" prints as "--- x") is still read as content."""
        commit = "unknown"
        block_line = 0
        old_path: str | None = None
        new_path: str | None = None
        hunk: Hunk | None = None
        env_files: set[tuple[str, str]] = set()
        # split on "\n" only: a committed line may hold a form feed, a lone CR, NEL or U+2028, which str.splitlines()
        # would also break on and so throw the hunk line counts off
        for raw in text.removesuffix("\n").split("\n"):
            block_line += 1
            if hunk is not None:
                if raw.startswith("\\"):  # "\ No newline at end of file"
                    continue
                taken = hunk.take(raw)
                if taken is not None:
                    kind, content, lineno, parent = taken
                    if kind == "added":
                        self.scan_line(f"git:{commit}:{new_path}", lineno, content, path=new_path or "")
                    elif kind == "removed":
                        rev = "^" if hunk.parents == 1 else f"^{parent + 1}"
                        self.scan_line(f"git:{commit}{rev}:{old_path}", lineno, content, path=old_path or "")
                    if hunk.done():
                        hunk = None
                    continue
                hunk = None  # a short or malformed hunk: read this line as a header line
            if raw.startswith("commit "):
                commit = (raw.split()[1:2] or ["unknown"])[0][:12]
                block_line = 1
                old_path = new_path = None
            if raw.startswith("diff "):
                old_path = new_path = None
            elif raw.startswith("--- "):
                old_path = diff_header_path(raw[4:])
            elif raw.startswith("+++ "):
                new_path = diff_header_path(raw[4:])
            elif raw.startswith(("rename to ", "copy to ")):
                new_path = unquote_git_path(raw.split(" ", 2)[2])
            elif raw.startswith(("rename from ", "copy from ")):
                old_path = unquote_git_path(raw.split(" ", 2)[2])
            elif HUNK_HEADER.match(raw):
                try:
                    hunk = Hunk(raw)
                except ValueError:
                    hunk = None
                if hunk is not None and hunk.done():
                    hunk = None
                continue
            if new_path and Path(new_path).name == ".env" and (commit, new_path) not in env_files:
                env_files.add((commit, new_path))
                self.add("env_file", f"git:{commit}:{new_path}", 1)
            self.scan_line(f"git:{commit}", block_line, raw)

    def scan_history(self) -> bool:
        top = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != self.root.resolve():
            print("leakcheck: --git-history needs the repository root itself; stopping", file=sys.stderr)
            return False
        # bytes, decoded without newline translation (text mode would turn a lone CR into a line break)
        log = subprocess.run(["git", "-C", str(self.root), *GIT_LOG_ARGS], capture_output=True)
        if log.returncode != 0:
            print("leakcheck: git log failed; stopping", file=sys.stderr)
            return False
        out = log.stdout
        self.scan_log(out.decode("utf-8", errors="replace") if isinstance(out, bytes) else str(out))
        people = subprocess.run(["git", "-C", str(self.root), "log", "--all", "--format=%ae%n%ce"],
                                capture_output=True, text=True, errors="replace")
        if people.returncode != 0:
            print("leakcheck: git log of the author emails failed; stopping", file=sys.stderr)
            return False
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
