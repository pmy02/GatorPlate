#!/usr/bin/env python3
"""File ownership check for the parallel build (standard library only; no git).

Reads the `owners` block of OWNERS.md. Glob rules: paths relative to the repository root; `*` matches within one path
segment (never `/`), `**` matches any depth (also zero folders), `{a,b}` lists alternatives.

  --baseline              write var/baseline.json (a hash of every checked file, plus the text of the shared file)
  (no option)             compare the tree with the baseline: a changed or new file outside every owner glob, a
                          changed or deleted frozen file, or an edit of the shared file that is not an append fails
  --agent ID              compare the tree with the baseline, judging every change as made by agent ID
  --agent ID --files F..  check that the files an agent reports are inside its globs (no baseline needed for that;
                          with a baseline, the shared file must only have grown by an append)
  --tree                  check that every checked file in the tree has exactly one owner group (disjoint globs)

Exit status 0 when clean, 1 on any finding, 2 on a usage problem (for example a missing baseline).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNERS_FILE = "OWNERS.md"
BASELINE = Path("var") / "baseline.json"
UNRESTRICTED = {"INT", "FREEZE"}  # single writers: may edit any file, frozen ones included
PRE_FREEZE = {"S0"}  # writes the frozen files before the foundation gate


def expand_braces(glob: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", glob)
    if not m:
        return [glob]
    out: list[str] = []
    for alt in m.group(1).split(","):
        out.extend(expand_braces(glob[: m.start()] + alt + glob[m.end():]))
    return out


def glob_regex(glob: str) -> re.Pattern[str]:
    parts: list[str] = []
    for single in expand_braces(glob):
        i, rx = 0, ""
        while i < len(single):
            if single.startswith("**/", i):
                rx += "(?:.*/)?"
                i += 3
            elif single.startswith("/**", i) and i + 3 == len(single):
                rx += "(?:/.*)?"
                i += 3
            elif single.startswith("**", i):
                rx += ".*"
                i += 2
            elif single[i] == "*":
                rx += "[^/]*"
                i += 1
            elif single[i] == "?":
                rx += "[^/]"
                i += 1
            else:
                rx += re.escape(single[i])
                i += 1
        parts.append(rx)
    return re.compile("^(?:" + "|".join(parts) + ")$")


@dataclass
class Rules:
    owners: list[tuple[frozenset[str], str, re.Pattern[str]]] = field(default_factory=list)
    frozen: list[re.Pattern[str]] = field(default_factory=list)
    shared: list[re.Pattern[str]] = field(default_factory=list)
    shared_names: list[str] = field(default_factory=list)
    anyfile: set[str] = field(default_factory=set)
    skip: list[re.Pattern[str]] = field(default_factory=list)

    def owner_groups(self, path: str) -> list[frozenset[str]]:
        groups: list[frozenset[str]] = []
        for agents, _, rx in self.owners:
            if rx.match(path) and agents not in groups:
                groups.append(agents)
        return groups

    def is_frozen(self, path: str) -> bool:
        return any(rx.match(path) for rx in self.frozen)

    def is_shared(self, path: str) -> bool:
        return any(rx.match(path) for rx in self.shared)

    def is_skipped(self, path: str) -> bool:
        return any(rx.match(path) for rx in self.skip)

    def agent_may_write(self, agent: str, path: str) -> bool:
        if agent in self.anyfile or agent in UNRESTRICTED:
            return True
        return any(agent in agents and rx.match(path) for agents, _, rx in self.owners)

    def known_agents(self) -> set[str]:
        names = set(self.anyfile) | UNRESTRICTED
        for agents, _, _ in self.owners:
            names |= set(agents)
        return names


def load_rules(root: Path) -> Rules:
    text = (root / OWNERS_FILE).read_text(encoding="utf-8")
    m = re.search(r"```owners\n(.*?)```", text, re.DOTALL)
    if not m:
        raise SystemExit(f"{OWNERS_FILE}: no ```owners block")
    rules = Rules()
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kind, agents, glob = line.split()
        if kind == "owner":
            rules.owners.append((frozenset(agents.split(",")), glob, glob_regex(glob)))
        elif kind == "frozen":
            rules.frozen.append(glob_regex(glob))
        elif kind == "shared":
            rules.shared.append(glob_regex(glob))
            rules.shared_names.append(glob)
        elif kind == "anyfile":
            rules.anyfile |= set(agents.split(","))
        elif kind == "skip":
            rules.skip.append(glob_regex(glob))
        else:
            raise SystemExit(f"{OWNERS_FILE}: unknown kind {kind!r}")
    return rules


def tree_files(root: Path, rules: Rules) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rules.is_skipped(rel):
            continue
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def normalize(root: Path, name: str) -> str | None:
    p = Path(name)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return None
    rel = Path(*[part for part in p.parts if part not in (".",)]).as_posix()
    if rel.startswith("../") or rel == "..":
        return None
    return rel


def read_shared(root: Path, rules: Rules) -> dict[str, str]:
    out = {}
    for name in rules.shared_names:
        path = root / name
        if path.exists():
            out[name] = path.read_text(encoding="utf-8")
    return out


def write_baseline(root: Path, rules: Rules) -> int:
    data = {"files": tree_files(root, rules), "shared": read_shared(root, rules)}
    out = root / BASELINE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"ownership: baseline written ({len(data['files'])} files) to {BASELINE.as_posix()}")
    return 0


def load_baseline(root: Path) -> dict | None:
    path = root / BASELINE
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def shared_problem(root: Path, rules: Rules, rel: str, baseline: dict | None, agent: str | None) -> str | None:
    """None when the shared file only grew by an append (or the agent is unrestricted)."""
    if agent in UNRESTRICTED:
        return None
    if baseline is None:
        return None
    before = baseline.get("shared", {}).get(rel)
    path = root / rel
    if before is None or not path.exists():
        return None
    now = path.read_text(encoding="utf-8")
    if now.startswith(before):
        return None
    return "shared file edited (only appends are allowed; the integrator edits existing text)"


def check_changes(root: Path, rules: Rules, baseline: dict, agent: str | None) -> list[str]:
    problems: list[str] = []
    before: dict[str, str] = baseline.get("files", {})
    now = tree_files(root, rules)
    changed = [p for p, h in now.items() if before.get(p) != h]
    deleted = [p for p in before if p not in now]
    for rel in changed:
        state = "new" if rel not in before else "changed"
        if rules.is_shared(rel):
            problem = shared_problem(root, rules, rel, baseline, agent)
            if problem:
                problems.append(f"{problem}: {rel}")
            continue
        if agent is None:
            if not rules.owner_groups(rel):
                problems.append(f"{state} file outside every owner glob: {rel}")
            elif rules.is_frozen(rel):
                problems.append(f"frozen file {state}: {rel}")
        else:
            if not rules.agent_may_write(agent, rel):
                problems.append(f"{state} file outside {agent}'s globs: {rel}")
            elif rules.is_frozen(rel) and agent not in UNRESTRICTED | PRE_FREEZE:
                problems.append(f"frozen file {state}: {rel}")
    for rel in deleted:
        if rules.is_frozen(rel) and agent not in UNRESTRICTED:
            problems.append(f"frozen file deleted: {rel}")
        elif agent is not None and not rules.agent_may_write(agent, rel):
            problems.append(f"deleted file outside {agent}'s globs: {rel}")
    return problems


def check_files(root: Path, rules: Rules, agent: str, files: list[str], baseline: dict | None) -> list[str]:
    problems: list[str] = []
    for name in files:
        rel = normalize(root, name)
        if rel is None:
            problems.append(f"outside the repository: {name}")
            continue
        if rules.is_skipped(rel):
            continue
        if rules.is_shared(rel):
            problem = shared_problem(root, rules, rel, baseline, agent)
            if problem:
                problems.append(f"{problem}: {rel}")
            continue
        if not rules.agent_may_write(agent, rel):
            problems.append(f"outside {agent}'s globs: {rel}")
        elif rules.is_frozen(rel) and agent not in UNRESTRICTED | PRE_FREEZE:
            problems.append(f"frozen file: {rel}")
    return problems


def check_tree(root: Path, rules: Rules) -> list[str]:
    problems: list[str] = []
    for rel in tree_files(root, rules):
        if rules.is_shared(rel):
            continue
        groups = rules.owner_groups(rel)
        if not groups:
            problems.append(f"no owner: {rel}")
        elif len(groups) > 1:
            names = " and ".join(",".join(sorted(g)) for g in groups)
            problems.append(f"more than one owner group ({names}): {rel}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--baseline", action="store_true", help="write var/baseline.json")
    ap.add_argument("--agent", help="agent id (S0, A1-A9, INT, FREEZE, ...)")
    ap.add_argument("--files", nargs="+", help="files the agent reports as written")
    ap.add_argument("--tree", action="store_true", help="every checked file has exactly one owner group")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    rules = load_rules(root)

    if args.baseline:
        return write_baseline(root, rules)

    problems: list[str] = []
    if args.tree:
        problems += check_tree(root, rules)
    baseline = load_baseline(root)
    if args.files:
        if not args.agent:
            print("ownership: --files needs --agent", file=sys.stderr)
            return 2
        problems += check_files(root, rules, args.agent, args.files, baseline)
    elif not args.tree:
        if baseline is None:
            print("ownership: no baseline yet (run `make ownership BASELINE=1` after the foundation commit)",
                  file=sys.stderr)
            return 2
        problems += check_changes(root, rules, baseline, args.agent)
    if args.agent and args.agent not in rules.known_agents() and not re.fullmatch(r"V[1-6]", args.agent):
        print(f"ownership: unknown agent {args.agent!r}", file=sys.stderr)
        return 2

    for problem in problems:
        print(f"FAIL {problem}")
    print(f"ownership: {len(problems)} problem{'s' if len(problems) != 1 else ''}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
