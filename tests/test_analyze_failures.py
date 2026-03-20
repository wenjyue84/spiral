"""Tests for lib/analyze_failures.py (US-547)."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest

from lib.analyze_failures import FailureAnalyzer, categorize_text


# ── categorize_text ────────────────────────────────────────────────────────────


class TestCategorizeText:
    def test_scope_exceeded_max_tokens(self) -> None:
        assert categorize_text("exceeds max_tokens limit") == "scope_exceeded"

    def test_scope_exceeded_context_length(self) -> None:
        assert categorize_text("context_length is too long") == "scope_exceeded"

    def test_api_rate_limit(self) -> None:
        assert categorize_text("rate_limit hit, please retry") == "api_rate_limit"

    def test_api_rate_limit_429(self) -> None:
        assert categorize_text("HTTP 429 too many requests") == "api_rate_limit"

    def test_type_error(self) -> None:
        assert categorize_text("TypeError: unsupported operand type") == "type_error"

    def test_import_error(self) -> None:
        assert categorize_text("ImportError: cannot import name foo") == "type_error"

    def test_validation_timeout(self) -> None:
        assert categorize_text("timed out after 60s") == "validation_timeout"

    def test_timeout_error(self) -> None:
        assert categorize_text("TimeoutError: deadline exceeded") == "validation_timeout"

    def test_model_capability_gap(self) -> None:
        assert categorize_text("model is not capable of this task") == "model_capability_gap"

    def test_unknown(self) -> None:
        assert categorize_text("something went wrong") == "unknown"

    def test_empty_string(self) -> None:
        assert categorize_text("") == "unknown"


# ── FailureAnalyzer ────────────────────────────────────────────────────────────


class TestFailureAnalyzer:
    def _write_results_tsv(self, tmp_dir: Path, rows: list[dict[str, str]]) -> Path:
        tsv_path = tmp_dir / "results.tsv"
        fieldnames = ["timestamp", "story_id", "story_title", "status", "failure_root_cause"]
        with open(tsv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return tsv_path

    def test_analyze_empty_returns_valid_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fa = FailureAnalyzer(repo_root=Path(tmp))
            result = fa.analyze()
        assert "by_category" in result
        assert "by_phase" in result
        assert "recommendation" in result

    def test_analyze_missing_files_graceful(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fa = FailureAnalyzer(repo_root=Path(tmp))
            result = fa.analyze()
        assert result["recommendation"] == "No failures found — nothing to tune."

    def test_analyze_results_tsv_with_fail_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rows = [
                {"timestamp": "2026-01-01T00:00:00Z", "story_id": "US-1", "story_title": "Test", "status": "fail", "failure_root_cause": "scope_exceeded"},
                {"timestamp": "2026-01-01T00:01:00Z", "story_id": "US-2", "story_title": "Test2", "status": "retry", "failure_root_cause": "scope_exceeded"},
                {"timestamp": "2026-01-01T00:02:00Z", "story_id": "US-3", "story_title": "Test3", "status": "keep", "failure_root_cause": ""},
            ]
            self._write_results_tsv(tmp_path, rows)
            fa = FailureAnalyzer(repo_root=tmp_path)
            result = fa.analyze()
        # Only fail/retry rows counted
        assert result["by_category"].get("scope_exceeded", 0) == 2

    def test_recommendation_scope_exceeded_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rows = [
                {"timestamp": f"2026-01-01T00:0{i}:00Z", "story_id": f"US-{i}", "story_title": "T", "status": "fail", "failure_root_cause": "scope_exceeded"}
                for i in range(4)
            ]
            self._write_results_tsv(tmp_path, rows)
            fa = FailureAnalyzer(repo_root=tmp_path)
            result = fa.analyze()
        assert "SPIRAL_DECOMPOSE_THRESHOLD" in result["recommendation"]

    def test_analyze_with_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            logs_dir = tmp_path / ".spiral" / "logs"
            logs_dir.mkdir(parents=True)
            log_file = logs_dir / "phase-i-1.log"
            log_file.write_text("[2026-01-01T00:00:00Z] FAILURE_ROOT_CAUSE: api_rate_limit\n  story_id=US-99 retry=1 reason=rate_limit\n", encoding="utf-8")
            fa = FailureAnalyzer(repo_root=tmp_path)
            result = fa.analyze()
        assert result["by_category"].get("api_rate_limit", 0) >= 1

    def test_json_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fa = FailureAnalyzer(repo_root=Path(tmp))
            result = fa.analyze()
        # Should be serializable without error
        json.dumps(result)

    def test_analyze_failures_cli_format_json(self) -> None:
        """CLI --format json returns valid JSON."""
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-m", "lib.analyze_failures", "--format", "json", "--repo", tmp],
                capture_output=True,
                text=True,
            )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "by_category" in data
        assert "by_phase" in data
        assert "recommendation" in data
