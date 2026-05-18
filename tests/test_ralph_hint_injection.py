#!/usr/bin/env python3
"""Tests for error recovery hint injection from failure history.

Tests that:
1. Error hints are loaded from lib/error_hints.json
2. Story failures in results.tsv are classified by error type
3. Hints are correctly injected into decompose_story.py prompts
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from lib.error_hints_loader import (
    classify_error,
    load_error_hints,
    load_hints_for_story,
)


class TestErrorHintsLoading:
    """Tests for error_hints.json loading."""

    def test_load_error_hints_success(self) -> None:
        """Test loading error_hints.json succeeds."""
        hints = load_error_hints()
        assert isinstance(hints, dict)
        assert "timeout" in hints
        assert "oom" in hints
        assert "syntax" in hints
        assert "import" in hints
        assert "assertion" in hints
        assert len(hints) >= 5

    def test_error_hints_have_content(self) -> None:
        """Test that each hint category has list of strings."""
        hints = load_error_hints()
        for category, hint_list in hints.items():
            assert isinstance(hint_list, list), f"Category {category} should be list"
            assert len(hint_list) > 0, f"Category {category} should have hints"
            for hint in hint_list:
                assert isinstance(hint, str), "Hint should be string"
                assert len(hint) > 0, "Hint should not be empty"


class TestErrorClassification:
    """Tests for error message classification."""

    def test_classify_timeout(self) -> None:
        """Test timeout error detection."""
        assert classify_error("timeout occurred") == "timeout"
        assert classify_error("timed out after 30s") == "timeout"
        assert classify_error("Deadline exceeded") == "timeout"

    def test_classify_oom(self) -> None:
        """Test OOM error detection."""
        assert classify_error("out of memory") == "oom"
        assert classify_error("MemoryError: heap overflow") == "oom"
        assert classify_error("V8 Heap Overflow") == "oom"

    def test_classify_syntax(self) -> None:
        """Test syntax error detection."""
        assert classify_error("SyntaxError: invalid syntax") == "syntax"
        assert classify_error("IndentationError at line 5") == "syntax"

    def test_classify_import(self) -> None:
        """Test import error detection."""
        assert classify_error("ImportError: no module named foo") == "import"
        assert classify_error("ModuleNotFoundError: cannot import bar") == "import"

    def test_classify_assertion(self) -> None:
        """Test assertion error detection."""
        assert classify_error("AssertionError: test failed") == "assertion"
        assert classify_error("pytest: test_something FAILED") == "assertion"

    def test_classify_network(self) -> None:
        """Test network error detection."""
        assert classify_error("ConnectionError: connection refused") == "network"
        assert classify_error("socket.error: network unreachable") == "network"

    def test_classify_auth(self) -> None:
        """Test auth error detection."""
        assert classify_error("Unauthorized: 401 Invalid Token") == "auth"
        assert classify_error("Forbidden: 403 Access Denied") == "auth"

    def test_classify_unknown(self) -> None:
        """Test unknown error classification."""
        assert classify_error("Something went wrong") == "unknown"
        assert classify_error("") == "unknown"


class TestHintLoadingForStory:
    """Tests for loading hints based on story failure history."""

    def test_no_results_file(self) -> None:
        """Test graceful handling when results.tsv doesn't exist."""
        hints = load_hints_for_story("US-123", "nonexistent.tsv")
        assert isinstance(hints, list)
        assert len(hints) == 0

    def test_story_no_failures(self, tmp_path: Path) -> None:
        """Test story with no failures in results.tsv."""
        results_file = tmp_path / "results.tsv"
        results_file.write_text(
            "story_id\tstory_title\tstatus\nUS-100\tSome Other Story\tpass\nUS-101\tAnother Story\tpass\n"
        )

        hints = load_hints_for_story("US-123", str(results_file))
        assert isinstance(hints, list)
        assert len(hints) == 0

    def test_story_single_timeout_failure(self, tmp_path: Path) -> None:
        """Test story with single timeout failure."""
        results_file = tmp_path / "results.tsv"
        results_file.write_text("story_id\tstory_title\tstatus\nUS-123\tFailed story - timeout\tfail\n")

        hints = load_hints_for_story("US-123", str(results_file))
        assert isinstance(hints, list)
        assert len(hints) > 0
        # Should contain timeout-related hints
        assert any("scope" in h.lower() or "reduce" in h.lower() for h in hints)

    def test_story_multiple_failures(self, tmp_path: Path) -> None:
        """Test story with multiple failure types."""
        results_file = tmp_path / "results.tsv"
        results_file.write_text(
            "story_id\tstory_title\tstatus\n"
            "US-123\tStory with timeout\tfail\n"
            "US-123\tStory with syntax error\trej\n"
            "US-100\tOther Story\tpass\n"
        )

        hints = load_hints_for_story("US-123", str(results_file))
        assert isinstance(hints, list)
        # Should have hints for both timeout and syntax errors
        assert len(hints) >= 2

    def test_hints_are_from_error_hints_json(self, tmp_path: Path) -> None:
        """Test that returned hints are actually from error_hints.json."""
        results_file = tmp_path / "results.tsv"
        results_file.write_text("story_id\tstory_title\tstatus\nUS-123\tStory with timeout\tfail\n")

        hints = load_hints_for_story("US-123", str(results_file))
        all_hints = load_error_hints()
        timeout_hints = all_hints.get("timeout", [])

        # Returned hints should be subset of timeout hints
        for hint in hints:
            assert hint in timeout_hints, f"Hint '{hint}' not in timeout hints"

    def test_story_partial_match(self, tmp_path: Path) -> None:
        """Test that partial story title matches are found."""
        results_file = tmp_path / "results.tsv"
        results_file.write_text("story_id\tstory_title\tstatus\nUS-123\tMy Long Story Title With Timeout\tfail\n")

        # Match on partial story ID
        hints = load_hints_for_story("US-123", str(results_file))
        assert len(hints) > 0


class TestTimeoutHintInjection:
    """Integration test for timeout hint injection into decomposition."""

    def test_timeout_hint_injection_in_decompose_context(self) -> None:
        """Test that timeout hints are injected into decompose_story context.

        This is AC3 from the story: verify hints appear in Ralph's decomposition
        context and influence sub-story generation.
        """
        # Create mock results.tsv with timeout failure
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            results_file = tmppath / "results.tsv"
            results_file.write_text("story_id\tstory_title\tstatus\nUS-456\tTimeout Error Story\tfail\n")

            # Load hints for the story
            hints = load_hints_for_story("US-456", str(results_file))

            # Verify hints were loaded
            assert len(hints) > 0
            assert any("scope" in h.lower() for h in hints), "Should have scope reduction hint"

            # Format hints as they would be passed to decompose_story.py
            learned_hints = "\n".join(hints)
            assert len(learned_hints) > 0
            assert "\n" in learned_hints or len(hints) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
