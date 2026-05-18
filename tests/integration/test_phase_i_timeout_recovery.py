"""Integration test: Phase I Timeout Handler Reduces Scope and Completes Story (US-1386).

Verifies that when Ralph times out mid-story:
  1. timeout_handler detects the signal and invokes scope_reducer().
  2. scope_reducer() removes @optional ACs, leaving only mandatory ones.
  3. Re-invoking the runner with the trimmed story produces status='completed'
     with ac_fulfilled_count < original_ac_count and retry_count=1.
"""

from __future__ import annotations

import csv
import io
import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))

from impl.scope_reducer import strip_optional_ac
from timeout_handler import timeout_scope_reducer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STORY_WITH_OPTIONAL_ACS: dict[str, Any] = {
    "id": "US-test-timeout",
    "title": "Timeout recovery test story",
    "priority": "medium",
    "passes": False,
    "dependencies": [],
    "acceptanceCriteria": [
        "Mandatory AC 1 — must always be fulfilled",
        "Mandatory AC 2 — must always be fulfilled",
        "Mandatory AC 3 — must always be fulfilled",
        "@optional Extra feature A — strip on timeout",
        "@optional Extra feature B — strip on timeout",
        "@optional Extra feature C — strip on timeout",
    ],
}


def _simulate_ralph_run(story: dict[str, Any], runner: Any) -> dict[str, Any]:
    """Run story with *runner*; on TimeoutError invoke scope_reducer and retry.

    This mirrors the Phase I retry logic:
      1. Attempt ralph_run(); if it times out catch the error.
      2. Call scope_reducer to strip @optional ACs from the story.
      3. Re-run with the reduced story, record retry_count=1.

    Returns:
        dict with 'status', 'ac_fulfilled_count', 'retry_count'.
    """
    original_ac_count = len(story.get("acceptanceCriteria", []))
    try:
        result: dict[str, Any] = runner.run(story)
        result["retry_count"] = 0
        return result
    except TimeoutError:
        # timeout_handler detects SIGALRM / TimeoutError → calls scope_reducer
        reduced_story = timeout_scope_reducer(str(story.get("id", "unknown")), story)
        # Re-invoke Ralph with reduced scope
        reduced_runner = runner.with_timeout(None)  # no timeout on retry
        result = reduced_runner.run(reduced_story)
        result["retry_count"] = 1
        result["original_ac_count"] = original_ac_count
        return result


def _write_results_tsv(result: dict[str, Any], story_id: str) -> str:
    """Render a results.tsv row and return it as a string."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t")
    writer.writerow(
        [
            story_id,
            "sonnet",
            result.get("status", "unknown"),
            result.get("ac_fulfilled_count", 0),
            result.get("retry_count", 0),
            0.001,
            30,
        ]
    )
    return output.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTimeoutTriggersScopeReduction:
    """AC1: MockClaudeRunner with timeout triggers scope_reducer()."""

    def test_timeout_triggers_scope_reduction(self, mock_claude_runner: Any) -> None:
        """Simulated 90s timeout causes scope_reducer to strip @optional ACs."""
        story = dict(_STORY_WITH_OPTIONAL_ACS)
        original_ac_count = len(story["acceptanceCriteria"])

        runner_with_timeout = mock_claude_runner.with_timeout(90)

        # Runner raises TimeoutError; _simulate_ralph_run catches it
        result = _simulate_ralph_run(story, runner_with_timeout)

        # scope_reducer must have been called (evidenced by ac_fulfilled_count shrink)
        assert result["status"] == "completed"
        assert result["ac_fulfilled_count"] < original_ac_count
        assert result["retry_count"] == 1

    def test_runner_raises_on_timeout(self, mock_claude_runner: Any) -> None:
        """MockClaudeRunner.with_timeout(90) raises TimeoutError on run()."""
        runner = mock_claude_runner.with_timeout(90)
        with pytest.raises(TimeoutError):
            runner.run(_STORY_WITH_OPTIONAL_ACS)

    def test_runner_without_timeout_succeeds(self, mock_claude_runner: Any) -> None:
        """MockClaudeRunner without timeout completes the story normally."""
        story = dict(_STORY_WITH_OPTIONAL_ACS)
        result = mock_claude_runner.run(story)
        assert result["status"] == "completed"
        assert result["ac_fulfilled_count"] == len(story["acceptanceCriteria"])


class TestScopeReducerRemovesOptionalACs:
    """AC2: scope_reducer() removes 3+ optional ACs, leaves mandatory ones."""

    def test_strips_exactly_three_optional_acs(self) -> None:
        """scope_reducer strips all 3 @optional ACs from the test story."""
        story = dict(_STORY_WITH_OPTIONAL_ACS)
        reduced = strip_optional_ac(story)
        optional_before = [ac for ac in story["acceptanceCriteria"] if ac.startswith("@optional")]
        reduced_acs = reduced.get("acceptanceCriteria") or []
        optional_after = [ac for ac in reduced_acs if isinstance(ac, str) and ac.startswith("@optional")]
        assert len(optional_before) >= 3, "Test story must have 3+ @optional ACs"
        assert len(optional_after) == 0, "All @optional ACs must be removed"

    def test_mandatory_acs_preserved(self) -> None:
        """Mandatory ACs are not removed after scope reduction."""
        story = dict(_STORY_WITH_OPTIONAL_ACS)
        reduced = strip_optional_ac(story)
        mandatory = [ac for ac in story["acceptanceCriteria"] if not ac.startswith("@optional")]
        assert reduced["acceptanceCriteria"] == mandatory

    def test_timeout_scope_reducer_delegates_to_strip_optional_ac(self) -> None:
        """timeout_scope_reducer() produces same result as strip_optional_ac()."""
        story = dict(_STORY_WITH_OPTIONAL_ACS)
        via_handler = timeout_scope_reducer(str(story["id"]), story)
        via_reducer = strip_optional_ac(story)
        assert via_handler["acceptanceCriteria"] == via_reducer["acceptanceCriteria"]


class TestRetryCountRecordedInResultsTsv:
    """AC3: after timeout retry, results.tsv row shows status=completed, retry_count=1."""

    def test_retry_count_is_one_after_timeout(self, mock_claude_runner: Any) -> None:
        """After one timeout + scope-reduction, retry_count equals 1."""
        story = dict(_STORY_WITH_OPTIONAL_ACS)
        runner_with_timeout = mock_claude_runner.with_timeout(90)
        result = _simulate_ralph_run(story, runner_with_timeout)
        assert result["retry_count"] == 1

    def test_ac_fulfilled_count_less_than_original(self, mock_claude_runner: Any) -> None:
        """Fulfilled AC count is less than original after scope reduction."""
        story = dict(_STORY_WITH_OPTIONAL_ACS)
        original_count = len(story["acceptanceCriteria"])
        runner_with_timeout = mock_claude_runner.with_timeout(90)
        result = _simulate_ralph_run(story, runner_with_timeout)
        assert result["ac_fulfilled_count"] < original_count

    def test_results_tsv_row_format(self, mock_claude_runner: Any) -> None:
        """results.tsv row contains correct story_id, status=completed, retry_count=1."""
        story = dict(_STORY_WITH_OPTIONAL_ACS)
        runner_with_timeout = mock_claude_runner.with_timeout(90)
        result = _simulate_ralph_run(story, runner_with_timeout)
        tsv_row = _write_results_tsv(result, str(story["id"]))
        assert "US-test-timeout" in tsv_row
        assert "completed" in tsv_row
        assert "\t1\t" in tsv_row  # retry_count column
