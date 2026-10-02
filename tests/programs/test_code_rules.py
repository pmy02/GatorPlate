"""Code rules for gatorplate/programs (docs/SPEC.md §5.1 and §5.10): no numeric literal except 0 and 1 (numeric
strings included; every number lives in the table), no float, no round(), and the module imports only the contracts
(never rules, dialogue, card, store or api)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

PROGRAMS_DIR = Path(__file__).resolve().parent.parent.parent / "gatorplate" / "programs"
NUMERIC = re.compile(r"^\s*[+-]?(\d[\d_]*)?(\.\d+)?([eE][+-]?\d+)?\s*$")
FORBIDDEN_IMPORTS = ("gatorplate.rules", "gatorplate.dialogue", "gatorplate.card", "gatorplate.store",
                     "gatorplate.api", "gatorplate.extract", "gatorplate.wiring", "gatorplate.config")


def numeric_literals(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool) or v is None or v is Ellipsis:
                continue
            if isinstance(v, int | float | complex) and v not in (0, 1):
                found.append(f"{path.name}:{node.lineno}: {v!r}")
            if isinstance(v, str) and any(ch.isdigit() for ch in v) and NUMERIC.match(v) and v.strip() not in ("0",
                                                                                                                 "1"):
                found.append(f"{path.name}:{node.lineno}: {v!r}")
    return found


def files() -> list[Path]:
    out = sorted(PROGRAMS_DIR.rglob("*.py"))
    assert out, "no programs modules"
    return out


def test_no_numeric_literal_except_0_and_1() -> None:
    problems = [p for f in files() for p in numeric_literals(f)]
    assert problems == [], "\n".join(problems)


def test_the_literal_check_catches_literals(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text('A = 2\nB = "0.30"\nC = 1\nD = "x2"\nE = 0.5\nF = "1_000"\nG = "12"\n', encoding="utf-8")
    assert [p.split(": ")[1] for p in numeric_literals(sample)] == ["2", "'0.30'", "0.5", "'1_000'", "'12'"]


def test_no_float_or_round() -> None:
    for path in files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("round", "float"), f"{path.name}:{node.lineno}"
            if isinstance(node, ast.Constant):
                assert not isinstance(node.value, float), f"{path.name}:{node.lineno}: float literal"


def test_imports_only_the_contracts_and_itself() -> None:
    for path in files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert not name.startswith(FORBIDDEN_IMPORTS), f"{path.name}: imports {name}"
                if name.startswith("gatorplate"):
                    assert name.startswith(("gatorplate.contracts", "gatorplate.programs")), f"{path.name}: {name}"


def test_no_environment_reads_and_no_io_after_construction() -> None:
    for path in files():
        text = path.read_text(encoding="utf-8")
        assert "os.environ" not in text and "getenv" not in text, path.name
        if path.name not in ("table.py", "view.py", "guard.py"):  # the three loaders read their file once
            assert "read_text" not in text and "open(" not in text, path.name
