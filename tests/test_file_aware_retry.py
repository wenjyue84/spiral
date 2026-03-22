"""Integration tests for US-597: File-aware retry strategy.

Verifies:
1. failed_files column exists in results_tsv.ResultsRecord and HEADER
2. file_aware_retry.py extract correctly parses stderr for file paths
3. file_aware_retry.py get reads failed_files from results.tsv
4. 10-file story with 3 mocked failures: retry reads exactly those 3 files
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "impl"))

from file_aware_retry import extract_failed_files, get_failed_files_for_story, sanitize_failed_files
from results_tsv import HEADER, ResultsRecord

# ── Helpers ───────────────────────────────────────────────────────────────────


def _write_results_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a minimal results.tsv with header + rows."""
    fieldnames = [
        "timestamp",
        "spiral_iter",
        "ralph_iter",
        "story_id",
        "story_title",
        "status",
        "duration_sec",
        "model",
        "retry_num",
        "commit_sha",
        "run_id",
        "failed_files",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestResultsTsvSchema:
    """Acceptance criterion 1: failed_files column in ResultsRecord and HEADER."""

    def test_failed_files_in_header(self) -> None:
        """failed_files must appear in HEADER."""
        assert "failed_files" in HEADER, f"failed_files missing from HEADER: {HEADER}"

    def test_failed_files_in_results_record(self) -> None:
        """ResultsRecord must have a failed_files field with default empty string."""
        # Create with all required positional args; failed_files should default to ""
        record = ResultsRecord(
            timestamp="2026-01-01T00:00:00Z",
            spiral_iter="1",
            ralph_iter="1",
            story_id="US-597",
            story_title="Test",
            status="failed",
            duration_sec="10",
            model="sonnet",
            retry_num="0",
            commit_sha="abc123",
            run_id="run-1",
        )
        assert hasattr(record, "failed_files")
        assert record.failed_files == ""

    def test_failed_files_can_be_set(self) -> None:
        """failed_files can be set to a JSON array string."""
        record = ResultsRecord(
            timestamp="2026-01-01T00:00:00Z",
            spiral_iter="1",
            ralph_iter="1",
            story_id="US-597",
            story_title="Test",
            status="failed",
            duration_sec="10",
            model="sonnet",
            retry_num="0",
            commit_sha="abc123",
            run_id="run-1",
            failed_files='["src/a.py","lib/b.py"]',
        )
        assert record.failed_files == '["src/a.py","lib/b.py"]'


class TestExtractFailedFiles:
    """Test extract_failed_files() from stderr text."""

    def test_extract_pytest_failures(self, tmp_path: Path) -> None:
        """Detects FAILED tests/test_foo.py patterns."""
        stderr = tmp_path / "stderr.txt"
        stderr.write_text(
            "FAILED tests/test_utils.py::test_add\nFAILED tests/test_merge.py::test_dedup\n1 error in setup\n",
            encoding="utf-8",
        )
        files = extract_failed_files(str(stderr))
        assert "tests/test_utils.py" in files
        assert "tests/test_merge.py" in files

    def test_extract_mypy_errors(self, tmp_path: Path) -> None:
        """Detects mypy lib/foo.py:12: error: patterns."""
        stderr = tmp_path / "stderr.txt"
        stderr.write_text(
            "lib/results_tsv.py:42: error: Argument 1 to 'foo' has incompatible type\n"
            "lib/merge_stories.py:88: error: Name 'bar' is not defined\n",
            encoding="utf-8",
        )
        files = extract_failed_files(str(stderr))
        assert "lib/results_tsv.py" in files
        assert "lib/merge_stories.py" in files

    def test_deduplication(self, tmp_path: Path) -> None:
        """Same file appearing twice is returned only once."""
        stderr = tmp_path / "stderr.txt"
        stderr.write_text(
            "FAILED tests/test_foo.py::test_a\nFAILED tests/test_foo.py::test_b\n",
            encoding="utf-8",
        )
        files = extract_failed_files(str(stderr))
        assert files.count("tests/test_foo.py") == 1

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Returns [] for non-existent stderr file."""
        files = extract_failed_files(str(tmp_path / "nonexistent.txt"))
        assert files == []

    def test_no_matches_returns_empty(self, tmp_path: Path) -> None:
        """Returns [] when stderr has no recognizable file paths."""
        stderr = tmp_path / "stderr.txt"
        stderr.write_text("Some generic error without file paths\n", encoding="utf-8")
        files = extract_failed_files(str(stderr))
        assert files == []


class TestGetFailedFilesForStory:
    """Test get_failed_files_for_story() reading from results.tsv."""

    def test_returns_failed_files_for_story(self, tmp_path: Path) -> None:
        """Returns the failed_files from the last failed row for a story."""
        results = tmp_path / "results.tsv"
        expected = ["src/main.py", "lib/utils.py", "tests/test_utils.py"]
        _write_results_tsv(
            results,
            [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-597",
                    "story_title": "Test",
                    "status": "failed",
                    "duration_sec": "10",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc",
                    "run_id": "run-1",
                    "failed_files": json.dumps(expected),
                }
            ],
        )
        files = get_failed_files_for_story(str(results), "US-597")
        assert sorted(files) == sorted(expected)

    def test_returns_last_failed_row(self, tmp_path: Path) -> None:
        """When multiple failures exist, returns files from the LAST failed row."""
        results = tmp_path / "results.tsv"
        first_files = ["src/a.py"]
        last_files = ["src/b.py", "lib/c.py"]
        _write_results_tsv(
            results,
            [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-597",
                    "story_title": "Test",
                    "status": "failed",
                    "duration_sec": "10",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc",
                    "run_id": "run-1",
                    "failed_files": json.dumps(first_files),
                },
                {
                    "timestamp": "2026-01-01T00:01:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-597",
                    "story_title": "Test",
                    "status": "failed",
                    "duration_sec": "15",
                    "model": "sonnet",
                    "retry_num": "1",
                    "commit_sha": "def",
                    "run_id": "run-1",
                    "failed_files": json.dumps(last_files),
                },
            ],
        )
        files = get_failed_files_for_story(str(results), "US-597")
        assert sorted(files) == sorted(last_files)

    def test_returns_empty_for_missing_tsv(self, tmp_path: Path) -> None:
        """Returns [] when results.tsv doesn't exist."""
        files = get_failed_files_for_story(str(tmp_path / "nonexistent.tsv"), "US-597")
        assert files == []

    def test_returns_empty_when_no_failed_files_column(self, tmp_path: Path) -> None:
        """Returns [] when failed_files column is absent."""
        results = tmp_path / "results.tsv"
        # Write without failed_files column
        with open(results, "w", encoding="utf-8") as f:
            f.write("timestamp\tstory_id\tstatus\n")
            f.write("2026-01-01\tUS-597\tfailed\n")
        files = get_failed_files_for_story(str(results), "US-597")
        assert files == []

    def test_returns_empty_for_unknown_story(self, tmp_path: Path) -> None:
        """Returns [] when story_id doesn't match any row."""
        results = tmp_path / "results.tsv"
        _write_results_tsv(
            results,
            [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-100",
                    "story_title": "Other",
                    "status": "failed",
                    "duration_sec": "10",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc",
                    "run_id": "run-1",
                    "failed_files": '["src/a.py"]',
                }
            ],
        )
        files = get_failed_files_for_story(str(results), "US-597")
        assert files == []


class TestFileAwareRetryIntegration:
    """
    Acceptance criterion 3: 10-file story with 3 mocked failures.

    Verifies the full flow: failed_files stored in results.tsv → retry reads
    exactly those 3 files and would pass --files-only with them.
    """

    def test_10_file_story_3_file_retry(self, tmp_path: Path) -> None:
        """
        Simulate: story with 10 filesTouch. First attempt fails on 3 files.
        Verify that get_failed_files_for_story returns exactly those 3 files.
        """
        # 10-file story (filesTouch)
        all_files = [f"src/module_{i}.py" for i in range(10)]
        assert len(all_files) == 10

        # 3 files that failed
        failed = ["src/module_2.py", "src/module_5.py", "src/module_8.py"]
        assert len(failed) == 3

        # Write results.tsv with one failed row recording the 3 failed files
        results = tmp_path / "results.tsv"
        _write_results_tsv(
            results,
            [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-597",
                    "story_title": "10-file story",
                    "status": "failed",
                    "duration_sec": "120",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "failed_files": json.dumps(failed),
                }
            ],
        )

        # Retry reads only the 3 failed files
        retry_files = get_failed_files_for_story(str(results), "US-597")
        assert len(retry_files) == 3, f"Expected 3 retry files, got {len(retry_files)}: {retry_files}"
        assert sorted(retry_files) == sorted(failed)

        # Verify it's a strict subset of the original 10 files
        assert all(f in all_files for f in retry_files)

        # Token cost ratio: 3/10 = 30% of original — consistent with criterion
        cost_ratio = len(retry_files) / len(all_files)
        assert cost_ratio <= 0.30 + 1e-9, f"Expected retry cost <= 30% of original, got {cost_ratio:.0%}"


# ── Module-level test functions for pytest discovery ─────────────────────────


def test_failed_files_in_header() -> None:
    """AC1: failed_files column exists in HEADER."""
    TestResultsTsvSchema().test_failed_files_in_header()


def test_failed_files_in_results_record() -> None:
    """AC1: ResultsRecord has failed_files field."""
    TestResultsTsvSchema().test_failed_files_in_results_record()


def test_extract_parses_pytest_failures(tmp_path: Path) -> None:
    """AC1: extract_failed_files detects pytest FAILED patterns."""
    TestExtractFailedFiles().test_extract_pytest_failures(tmp_path)


def test_get_failed_files_reads_tsv(tmp_path: Path) -> None:
    """AC2: get_failed_files_for_story reads failed_files from results.tsv."""
    TestGetFailedFilesForStory().test_returns_failed_files_for_story(tmp_path)


def test_10_file_story_3_file_retry_integration(tmp_path: Path) -> None:
    """AC3: 10-file story, 3-file failure, retry processes only 3 files (~30% cost)."""
    TestFileAwareRetryIntegration().test_10_file_story_3_file_retry(tmp_path)


def test_security_no_path_traversal() -> None:
    """Path traversal entries are sanitised out of the failed_files list."""
    result = sanitize_failed_files(
        ["../../../etc/passwd", "/absolute/path.py", "src/valid.py", "lib/ok.sh"]
    )
    assert "../../../etc/passwd" not in result, "Path traversal must be rejected"
    assert "/absolute/path.py" not in result, "Absolute paths must be rejected"
    assert "src/valid.py" in result, "Safe relative paths must be kept"
    assert "lib/ok.sh" in result, "Safe relative paths must be kept"


def test_security_no_sensitive_data_in_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Retry error output does not expose env var secrets (sk-, ANTHROPIC_API_KEY, password, token)."""
    secret = "sk-test-secret-12345"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    monkeypatch.setenv("password", "test-password-secret")
    monkeypatch.setenv("token", "test-token-value")

    # Stderr that contains the secret (simulates a misconfigured tool leaking it)
    stderr_file = tmp_path / "stderr.txt"
    stderr_file.write_text(
        f"Error: ANTHROPIC_API_KEY={secret}\n"
        "FAILED tests/test_utils.py::test_add\n"
        "lib/merge_stories.py:42: error: Type mismatch\n",
        encoding="utf-8",
    )

    # extract_failed_files must return only file paths, never the secret
    files = extract_failed_files(str(stderr_file))
    output = json.dumps(files)

    assert not re.search(r"(sk-|ANTHROPIC_API_KEY|password|token)", output), (
        f"Retry output contains credential pattern: {output!r}"
    )
    assert secret not in output, f"Secret leaked into retry output: {output!r}"
