"""tests/test_failure_categorizer.py — Tests for US-608 failure categorizer.

Validates that 10 sample error messages are categorized with >80% accuracy,
and tests the iteration-level grouping from results.tsv.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Add lib/ to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from failure_categorizer import (  # noqa: E402
    categorize_iteration,
    categorize_message,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

TSV_HEADER = (
    "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
    "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit\t"
    "cache_read_tokens\tcache_creation_tokens\treview_tokens\twall_seconds\t"
    "user_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id"
)


def _make_tsv_row(
    story_id: str,
    story_title: str,
    status: str = "fail",
    spiral_iter: int = 1,
    retry_num: int = 1,
) -> str:
    return (
        f"2026-01-01T00:00:00Z\t{spiral_iter}\t1\t{story_id}\t{story_title}\t"
        f"{status}\t60\tsonnet\t{retry_num}\t\t\ttrue\t0\t0\t0\t0\t0\t0\t0\t"
    )


# ── Unit tests: categorize_message (10 error messages) ───────────────────────


# These 10 cases form the ">80% accuracy" corpus.
# We assert all 10 so actual accuracy = 100% >= 80%.
ERROR_MESSAGE_CASES: list[tuple[str, str]] = [
    # test-failure
    ("AssertionError: expected True got False", "test-failure"),
    ("FAILED tests/test_foo.py::test_bar - assert 1 == 2", "test-failure"),
    # compilation-error
    ("SyntaxError: invalid syntax at line 42", "compilation-error"),
    ("ImportError: cannot import name 'foo' from 'bar'", "compilation-error"),
    # missing-dependency
    ("ModuleNotFoundError: No module named 'requests'", "missing-dependency"),
    ("npm install failed: package not found", "missing-dependency"),
    # timeout
    ("TimeoutError: operation timed out after 30s", "timeout"),
    ("execution timed out: deadline exceeded", "timeout"),
    # token-limit
    ("out of memory: context_length exceeds max", "token-limit"),
    ("MemoryError: token limit reached", "token-limit"),
]


@pytest.mark.parametrize("message,expected", ERROR_MESSAGE_CASES)
def test_categorize_message_known_errors(message: str, expected: str) -> None:
    """Each of the 10 sample error messages must match its expected category."""
    assert categorize_message(message) == expected


def test_categorize_message_type_error() -> None:
    result = categorize_message("TypeError: unsupported operand type(s) for +: 'int' and 'str'")
    assert result == "type-error"


def test_categorize_message_attribute_error() -> None:
    result = categorize_message("AttributeError: 'NoneType' object has no attribute 'split'")
    assert result == "type-error"


def test_categorize_message_other_fallback() -> None:
    """Unknown error text should map to 'other'."""
    result = categorize_message("something went completely wrong in an unexpected way")
    assert result == "other"


def test_categorize_message_empty_string() -> None:
    assert categorize_message("") == "other"


# ── Unit tests: categorize_iteration ─────────────────────────────────────────


def test_categorize_iteration_empty_file(tmp_path: Path) -> None:
    tsv = tmp_path / "results.tsv"
    tsv.write_text(TSV_HEADER + "\n", encoding="utf-8")
    result = categorize_iteration(iteration=1, results_tsv=tsv)
    assert result == []


def test_categorize_iteration_missing_file(tmp_path: Path) -> None:
    tsv = tmp_path / "nonexistent.tsv"
    result = categorize_iteration(iteration=1, results_tsv=tsv)
    assert result == []


def test_categorize_iteration_filters_by_iteration(tmp_path: Path) -> None:
    """Only rows matching the given spiral_iter should be included."""
    rows = [
        _make_tsv_row("US-100", "AssertionError in test_foo", spiral_iter=1),
        _make_tsv_row("US-200", "SyntaxError found", spiral_iter=2),
    ]
    tsv = tmp_path / "results.tsv"
    tsv.write_text(TSV_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")

    result = categorize_iteration(iteration=1, results_tsv=tsv)
    story_ids = [r["story"] for r in result]
    assert story_ids == ["US-100"]
    assert result[0]["retry1"] == "test-failure"


def test_categorize_iteration_multiple_retries(tmp_path: Path) -> None:
    """Multiple rows for same story become retry1, retry2, ..."""
    rows = [
        _make_tsv_row("US-100", "AssertionError retry 1", spiral_iter=1, retry_num=1),
        _make_tsv_row("US-100", "TimeoutError retry 2", spiral_iter=1, retry_num=2),
    ]
    tsv = tmp_path / "results.tsv"
    tsv.write_text(TSV_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")

    result = categorize_iteration(iteration=1, results_tsv=tsv)
    assert len(result) == 1
    rec = result[0]
    assert rec["story"] == "US-100"
    assert rec["retry1"] == "test-failure"
    assert rec["retry2"] == "timeout"


def test_categorize_iteration_none_returns_all(tmp_path: Path) -> None:
    """iteration=None includes rows from all spiral iterations."""
    rows = [
        _make_tsv_row("US-100", "SyntaxError", spiral_iter=1),
        _make_tsv_row("US-200", "ModuleNotFoundError", spiral_iter=5),
    ]
    tsv = tmp_path / "results.tsv"
    tsv.write_text(TSV_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")

    result = categorize_iteration(iteration=None, results_tsv=tsv)
    story_ids = [r["story"] for r in result]
    assert "US-100" in story_ids
    assert "US-200" in story_ids


def test_categorize_iteration_skips_passing_rows(tmp_path: Path) -> None:
    """Rows with status 'pass' should not appear in output."""
    rows = [
        _make_tsv_row("US-100", "AssertionError", status="pass", spiral_iter=1),
        _make_tsv_row("US-200", "SyntaxError", status="fail", spiral_iter=1),
    ]
    tsv = tmp_path / "results.tsv"
    tsv.write_text(TSV_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")

    result = categorize_iteration(iteration=1, results_tsv=tsv)
    story_ids = [r["story"] for r in result]
    assert "US-100" not in story_ids
    assert "US-200" in story_ids


def test_categorize_iteration_output_sorted(tmp_path: Path) -> None:
    """Output should be sorted by story_id alphabetically."""
    rows = [
        _make_tsv_row("US-300", "AssertionError", spiral_iter=1),
        _make_tsv_row("US-100", "SyntaxError", spiral_iter=1),
        _make_tsv_row("US-200", "TimeoutError", spiral_iter=1),
    ]
    tsv = tmp_path / "results.tsv"
    tsv.write_text(TSV_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")

    result = categorize_iteration(iteration=1, results_tsv=tsv)
    story_ids = [r["story"] for r in result]
    assert story_ids == sorted(story_ids)


# ── CLI integration test ──────────────────────────────────────────────────────


def test_cli_categorize_failures_json_output(tmp_path: Path) -> None:
    """spiral categorize-failures <iter> outputs valid JSON list."""
    rows = [
        _make_tsv_row("US-111", "AssertionError in test_auth", spiral_iter=3),
        _make_tsv_row("US-222", "ModuleNotFoundError: No module named 'foo'", spiral_iter=3),
    ]
    tsv = tmp_path / "results.tsv"
    tsv.write_text(TSV_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")

    main_py = Path(__file__).resolve().parent.parent / "main.py"
    proc = subprocess.run(
        [sys.executable, str(main_py), "categorize-failures", "3", "--results", str(tsv)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    output = json.loads(proc.stdout)
    assert isinstance(output, list)
    stories = {r["story"] for r in output}
    assert "US-111" in stories
    assert "US-222" in stories
    us111 = next(r for r in output if r["story"] == "US-111")
    assert us111["retry1"] == "test-failure"
    us222 = next(r for r in output if r["story"] == "US-222")
    assert us222["retry1"] == "missing-dependency"


def test_cli_categorize_failures_all_iterations(tmp_path: Path) -> None:
    """spiral categorize-failures with no iteration returns all rows."""
    rows = [
        _make_tsv_row("US-111", "SyntaxError", spiral_iter=1),
        _make_tsv_row("US-222", "TimeoutError", spiral_iter=7),
    ]
    tsv = tmp_path / "results.tsv"
    tsv.write_text(TSV_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")

    main_py = Path(__file__).resolve().parent.parent / "main.py"
    proc = subprocess.run(
        [sys.executable, str(main_py), "categorize-failures", "--results", str(tsv)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    output = json.loads(proc.stdout)
    story_ids = {r["story"] for r in output}
    assert "US-111" in story_ids
    assert "US-222" in story_ids
