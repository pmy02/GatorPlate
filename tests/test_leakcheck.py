"""tools/leakcheck.py: the --git-history reader reads `git log -p` as a diff (no diff prefix in the scanned text, the
real path and line of every finding, the config-file rule for unquoted values), and the tree rules stay as they were.

Every test value is built from pieces, so this file itself passes the tree scan."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import leakcheck as lc

SHA1 = "1a" * 20
SHA2 = "2b" * 20
SHA3 = "3c" * 20
AT = "@"
EMAIL = "someone" + AT + "example.org"
VALUE = "Zq7" * 8  # 24 key characters: a literal the secret rule reports
SESSION_NAME = "GP_SESSION_" + "SEC" + "RET"
CONSOLE_NAME = "GP_CONSOLE_" + "PASS" + "CODE"
DECORATOR = AT + "pytest.fixture"
ROUTE = AT + 'router.get("/api/cases/{case_id}")'


def commit(sha: str, *files: str, message: str = "Add files") -> str:
    """One commit as `git log -p --format=fuller` prints it (the message is indented by four spaces)."""
    head = [
        f"commit {sha}",
        "Author:     Test Author <test" + AT + "users.noreply.example>",
        "AuthorDate: Thu Oct 1 10:00:00 2026 -0700",
        "Commit:     Test Author <test" + AT + "users.noreply.example>",
        "CommitDate: Thu Oct 1 10:00:00 2026 -0700",
        "",
        *[f"    {line}" for line in message.splitlines()],
        "",
    ]
    return "\n".join(head + list(files))


def new_file(path: str, lines: list[str]) -> str:
    head = [f"diff --git a/{path} b/{path}", "new file mode 100644", "index 0000000..1111111", "--- /dev/null",
            f"+++ b/{path}", f"@@ -0,0 +1,{len(lines)} @@"]
    return "\n".join(head + ["+" + line for line in lines])


def changed(path: str, rows: list[tuple[str, str]], old_start: int = 1, new_start: int = 1) -> str:
    """A one-hunk change; rows are (mark, text) with mark " " (unchanged), "-" (removed) or "+" (added)."""
    old = sum(1 for mark, _ in rows if mark in " -")
    new = sum(1 for mark, _ in rows if mark in " +")
    head = [f"diff --git a/{path} b/{path}", "index 1111111..2222222 100644", f"--- a/{path}", f"+++ b/{path}",
            f"@@ -{old_start},{old} +{new_start},{new} @@ section"]
    return "\n".join(head + [mark + text for mark, text in rows])


def scan_log(tmp_path: Path, *commits: str) -> list[tuple[str, str, int]]:
    checker = lc.Checker(tmp_path, [])
    checker.scan_log("\n".join(commits) + "\n")
    return checker.findings


def where(sha: str, path: str = "", removed: bool = False) -> str:
    rev = sha[:12] + ("^" if removed else "")
    return f"git:{rev}:{path}" if path else f"git:{rev}"


# --- the diff prefix is not part of the scanned text --------------------------------------------------------------


def test_top_level_decorators_in_history_are_not_emails(tmp_path: Path) -> None:
    log = [
        commit(SHA1, new_file("tests/conftest.py", ["import pytest", "", DECORATOR, "def clock():", "    return 1"])),
        commit(SHA2, changed("gatorplate/api/routes_console.py",
                             [(" ", "router = make_router()"), ("-", ROUTE), ("+", ROUTE.replace(")", ", status_code=200)")),
                              (" ", "def case_detail(case_id: str):")], old_start=105, new_start=105)),
    ]
    assert scan_log(tmp_path, *log) == []
    # The same text read as plain lines (the old reader) turns each diff prefix into an email local part.
    plain = lc.Checker(tmp_path, [])
    plain.scan_text("git-history", "\n".join(log))
    assert [rule for rule, _, _ in plain.findings] == ["email", "email", "email"]


def test_blank_context_line_without_its_space_keeps_the_hunk(tmp_path: Path) -> None:
    hunk = changed("tests/test_x.py", [(" ", "import pytest"), (" ", ""), ("+", DECORATOR), ("+", "def f(): pass")])
    hunk = hunk.replace("\n \n", "\n\n")  # diff.suppressBlankEmpty prints an empty unchanged line as ""
    assert "\n\n+" + AT in hunk
    assert scan_log(tmp_path, commit(SHA1, hunk)) == []


def test_combined_diff_columns_are_stripped(tmp_path: Path) -> None:
    merge = "\n".join([
        "diff --cc tests/conftest.py", "index 1111111,2222222..3333333", "--- a/tests/conftest.py",
        "+++ b/tests/conftest.py", "@@@ -1,2 -1,2 +1,3 @@@",
        "  import pytest", " +# contact " + EMAIL, "+ " + DECORATOR,
    ])
    assert scan_log(tmp_path, commit(SHA1, merge)) == [("email", where(SHA1, "tests/conftest.py"), 2)]


# --- real paths and line numbers ----------------------------------------------------------------------------------


def test_finding_names_commit_path_and_line(tmp_path: Path) -> None:
    log = commit(SHA1, new_file("docs/notes.md", ["# Notes", "Write to " + EMAIL]),
                 changed("docs/other.md", [(" ", "a"), ("-", "old " + EMAIL), ("+", "new text")], old_start=40,
                         new_start=41))
    assert scan_log(tmp_path, log) == [
        ("email", where(SHA1, "docs/notes.md"), 2),
        ("email", where(SHA1, "docs/other.md", removed=True), 41),
    ]


def test_content_that_looks_like_a_header_stays_content(tmp_path: Path) -> None:
    # A removed "-- x" prints as "--- x" and an added "++ b/x" as "+++ b/x"; the hunk counts keep them content.
    first = changed("docs/a.md", [("-", "-- " + EMAIL), ("+", "++ b/elsewhere.md"), (" ", "end")], old_start=3,
                    new_start=3)
    second = new_file("docs/b.md", ["x " + EMAIL])
    log = commit(SHA1, first + "\n\\ No newline at end of file", second)
    assert scan_log(tmp_path, log) == [
        ("email", where(SHA1, "docs/a.md", removed=True), 3),
        ("email", where(SHA1, "docs/b.md"), 1),
    ]


def test_commit_messages_are_scanned_and_noreply_trailers_pass(tmp_path: Path) -> None:
    message = "Add notes\n\nAsk " + EMAIL + "\nCo-Authored-By: Helper <noreply" + AT + "example.org>"
    assert scan_log(tmp_path, commit(SHA1, message=message)) == [("email", where(SHA1), 9)]


def test_quoted_and_tab_terminated_paths() -> None:
    assert lc.unquote_git_path('"b/docs/caf\\303\\251.md"') == "b/docs/café.md"
    assert lc.unquote_git_path('"b/a\\"q\\\\.md"') == 'b/a"q\\.md'
    assert lc.diff_header_path("b/docs/my notes.md\t") == "docs/my notes.md"
    assert lc.diff_header_path("a/fly.toml") == "fly.toml"
    assert lc.diff_header_path("/dev/null") is None


# --- the config-file rule for unquoted values (a committed and later removed secret) -----------------------------


def test_unquoted_secret_in_config_files_is_found_in_history(tmp_path: Path) -> None:
    line = f"{SESSION_NAME}={VALUE}"
    toml_line = f"  {CONSOLE_NAME} = {VALUE}"
    log = [
        commit(SHA1, new_file(".env.example", [line]),
               changed("fly.toml", [(" ", "[env]"), ("+", toml_line)], old_start=9, new_start=9)),
        commit(SHA2, changed(".env.example", [("-", line), ("+", f"{SESSION_NAME}=")]),
               changed("fly.toml", [(" ", "[env]"), ("-", toml_line)], old_start=9, new_start=9)),
    ]
    assert scan_log(tmp_path, *log) == [
        ("secret", where(SHA1, ".env.example"), 1),
        ("secret", where(SHA1, "fly.toml"), 10),
        ("secret", where(SHA2, ".env.example", removed=True), 1),
        ("secret", where(SHA2, "fly.toml", removed=True), 10),
    ]
    # Parity with the tree scan of the same lines.
    tree = lc.Checker(tmp_path, [])
    tree.scan_line(".env.example", 1, line)
    tree.scan_line("fly.toml", 10, toml_line)
    assert [rule for rule, _, _ in tree.findings] == ["secret", "secret"]


def test_unquoted_name_in_code_is_not_a_literal_in_history(tmp_path: Path) -> None:
    # In code an unquoted value is a name; a quoted one is a literal (as in the tree scan).
    log = commit(SHA1, new_file("gatorplate/x.py", [f"{SESSION_NAME} = {VALUE}", f'{SESSION_NAME} = "{VALUE}"']))
    assert scan_log(tmp_path, log) == [("secret", where(SHA1, "gatorplate/x.py"), 2)]


def test_committed_env_file_is_reported_once_per_commit(tmp_path: Path) -> None:
    log = [commit(SHA1, new_file(".env", ["GP_ENV=dev", "GP_DEBUG_KEYS=1"])),
           commit(SHA3, changed("deploy/.env", [("+", "GP_TZ=America/Los_Angeles")]))]
    assert scan_log(tmp_path, *log) == [("env_file", where(SHA1, ".env"), 1),
                                        ("env_file", where(SHA3, "deploy/.env"), 1)]


# --- the command: git is called read-only with explicit options, failures stop it ---------------------------------


def fake_git(monkeypatch: pytest.MonkeyPatch, root: Path, log_text: str, log_status: int = 0) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(args: list[str], **_: object) -> SimpleNamespace:
        calls.append(list(args))
        if "rev-parse" in args:
            return SimpleNamespace(returncode=0, stdout=f"{root}\n", stderr="")
        if "-p" in args:
            return SimpleNamespace(returncode=log_status, stdout=log_text, stderr="")
        return SimpleNamespace(returncode=0, stdout="test" + AT + "users.noreply.example\n", stderr="")

    monkeypatch.setattr(lc, "subprocess", SimpleNamespace(run=run))
    return calls


def test_history_command_is_clean_for_decorators(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    calls = fake_git(monkeypatch, tmp_path, commit(SHA1, new_file("tests/conftest.py", [DECORATOR, "def f(): pass"])))
    assert lc.main(["--root", str(tmp_path), "--git-history"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "leakcheck: 0 findings"
    log_call = next(call for call in calls if "-p" in call)
    assert log_call[:3] == ["git", "-C", str(tmp_path.resolve())]
    for option in ("log", "--all", "--no-color", "--format=fuller", "--src-prefix=a/", "--dst-prefix=b/",
                   "--no-textconv", "core.quotePath=false"):
        assert option in log_call


def test_history_command_reports_location_never_the_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                          capsys: pytest.CaptureFixture[str]) -> None:
    fake_git(monkeypatch, tmp_path, commit(SHA1, new_file(".env.example", [f"{SESSION_NAME}={VALUE}"])))
    assert lc.main(["--root", str(tmp_path), "--git-history"]) == 1
    out = capsys.readouterr().out
    assert f"secret {where(SHA1, '.env.example')}:1" in out.splitlines()
    assert VALUE not in out


def test_history_command_stops_when_git_log_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    fake_git(monkeypatch, tmp_path, "", log_status=128)
    assert lc.main(["--root", str(tmp_path), "--git-history"]) == 1
    assert "git log failed" in capsys.readouterr().err


@pytest.mark.parametrize("breaker", ["\f", " ", "\x85", "\r", "\x1c", "\v"])
def test_a_line_with_an_inner_break_character_keeps_the_hunk_in_step(tmp_path: Path, breaker: str) -> None:
    """A committed line may hold a form feed, U+2028, NEL, a lone CR, ... : only "\\n" ends a diff line, so the hunk
    counts stay right — no false email from a decorator after it, no missed unquoted secret in a config file."""
    decorator_log = commit(SHA1, new_file("tests/conftest.py", [f"x = 1{breaker}y = 2", DECORATOR, "def f(): pass"]))
    assert scan_log(tmp_path, decorator_log) == []
    config_log = commit(SHA2, new_file("fly.toml", [f"# note{breaker}more", "[env]", f"{CONSOLE_NAME} = {VALUE}"]))
    assert ("secret", where(SHA2, "fly.toml"), 3) in scan_log(tmp_path, config_log)


def test_history_command_reads_the_root_commit_and_merges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_git(monkeypatch, tmp_path, commit(SHA1, new_file("README.md", ["# x"])))
    assert lc.main(["--root", str(tmp_path), "--git-history"]) == 0
    log_call = next(call for call in calls if "-p" in call)
    assert "--root" in log_call and "--cc" in log_call
