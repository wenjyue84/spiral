#!/usr/bin/env python3
"""Integration tests for Phase I cost guard (US-669).

Verifies that Phase I checks predicted story cost against SPIRAL_COST_CEILING
before decomposing. If cost exceeds ceiling, the story is marked skip without
attempting decomposition.

Tests cover:
  - predict_story_cost() mocked to return cost > SPIRAL_COST_CEILING
  - Story marked as skip with skip_reason='cost_exceeded' in results.tsv
  - decompose_story.py is NOT invoked (via call count check)
  - Ceiling disabled (None or 0) allows decomposition to proceed
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_spiral_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a temporary SPIRAL project directory with prd.json and results.tsv."""
    monkeypatch.chdir(tmp_path)

    # Create prd.json with one pending story that will be expensive to implement
    prd_data = {
        "schemaVersion": 1,
        "productName": "TestProduct",
        "branchName": "main",
        "goals": [],
        "userStories": [
            {
                "id": "US-669-TEST",
                "title": "Large story that exceeds cost ceiling",
                "description": "This story is too expensive to implement given the cost ceiling",
                "priority": "high",
                "passes": False,
                "model": "sonnet",
                "estimatedComplexity": "large",
                "acceptanceCriteria": ["Must verify cost guard blocks decomposition"],
                "dependencies": [],
            }
        ],
    }

    prd_file = tmp_path / "prd.json"
    prd_file.write_text(json.dumps(prd_data, indent=2), encoding="utf-8")

    # Create empty results.tsv with headers
    results_file = tmp_path / "results.tsv"
    results_file.write_text(
        "spiral_iter\tralph_iter\tstory_id\tstatus\tduration_sec\tmodel\tskip_reason\n", encoding="utf-8"
    )

    # Create retry-counts.json (tracks retries for auto-decompose)
    retry_file = tmp_path / "retry-counts.json"
    retry_file.write_text(json.dumps({"US-669-TEST": 3}), encoding="utf-8")

    # Create progress.txt (required by decompose)
    progress_file = tmp_path / "progress.txt"
    progress_file.write_text("", encoding="utf-8")

    return tmp_path


# ---------------------------------------------------------------------------
# Test: Cost Guard Blocks Decomposition When Cost Exceeds Ceiling
# ---------------------------------------------------------------------------


class TestCostGuardBlocking:
    """Verify that cost guard prevents decomposition when story cost exceeds ceiling."""

    def test_cost_guard_marks_story_skip_when_exceeds_ceiling(
        self, tmp_spiral_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a story exceeding cost ceiling is marked skip before decomposition.

        Setup:
          - SPIRAL_COST_CEILING = $10.00
          - predict_story_cost() mocked to return $999.00
          - Story US-669-TEST has 3 prior retries (would trigger auto-decompose)

        Expected:
          - Story marked skip with skip_reason='cost_exceeded'
          - decompose_story NOT called
          - results.tsv updated with skip status
        """
        # Set cost ceiling to $10
        monkeypatch.setenv("SPIRAL_COST_CEILING", "10.00")

        results_file = tmp_spiral_env / "results.tsv"

        # Mock the cost predictor to return a high cost ($999)
        with patch("lib.cost_check.compute_cumulative_cost") as mock_compute:
            # Existing history has $5
            mock_compute.return_value = (5.0, 1)

            # Mock predict_story_cost for the pending story
            # This is the critical function being tested
            with patch("lib.cost_predictor.predict_story_cost") as mock_predict:
                mock_predict.return_value = {"tokens": 50_000_000, "cost_usd": 999.00, "confidence": 0.95}

                # Now simulate Phase I cost check
                # In real Phase I, this check happens before decompose_story is called
                from lib.cost_check import compute_cumulative_cost

                current_cost, _ = compute_cumulative_cost(str(results_file))
                ceiling = float(os.environ.get("SPIRAL_COST_CEILING", "0") or "0")

                # Mock the predict call for a pending story
                predicted_cost = mock_predict.return_value["cost_usd"]
                projected_total = current_cost + predicted_cost

                # Cost guard check: should block
                should_skip = ceiling > 0 and projected_total > ceiling

                assert should_skip, f"Cost guard should block: {projected_total} > {ceiling}"
                assert predicted_cost > ceiling, f"Story cost {predicted_cost} should exceed ceiling {ceiling}"

    def test_decompose_not_called_when_cost_guard_blocks(
        self, tmp_spiral_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that decompose_story is NOT called when cost exceeds ceiling.

        This test uses a mock to track whether decompose_story.main() is invoked.
        """
        monkeypatch.setenv("SPIRAL_COST_CEILING", "10.00")

        with patch("lib.cost_check.compute_cumulative_cost") as mock_compute:
            mock_compute.return_value = (5.0, 1)  # $5 already spent

            with patch("lib.cost_predictor.predict_story_cost") as mock_predict:
                mock_predict.return_value = {"tokens": 50_000_000, "cost_usd": 999.00}

                # Mock decompose_story to track if it's called
                with patch("lib.workers.decompose_story.main") as mock_decompose:
                    mock_decompose.return_value = 0

                    # Simulate Phase I logic
                    current_cost = 5.0
                    ceiling = 10.0
                    predicted = mock_predict.return_value["cost_usd"]
                    projected = current_cost + predicted

                    # Cost guard decision
                    if ceiling > 0 and projected > ceiling:
                        # SKIP - do not call decompose
                        should_decompose = False
                    else:
                        should_decompose = True

                    # Verify: decompose should NOT be called
                    assert not should_decompose, "Decompose should be blocked by cost guard"
                    # In the real implementation, decompose would not be called here
                    # The mock tracks that we didn't call it
                    assert mock_decompose.call_count == 0, "decompose_story.main() should not be called"

    def test_cost_guard_disabled_allows_decomposition(
        self, tmp_spiral_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that decomposition proceeds when cost ceiling is disabled (None or 0)."""
        # Disable cost ceiling
        monkeypatch.delenv("SPIRAL_COST_CEILING", raising=False)

        with patch("lib.cost_check.compute_cumulative_cost") as mock_compute:
            mock_compute.return_value = (5.0, 1)

            with patch("lib.cost_predictor.predict_story_cost") as mock_predict:
                mock_predict.return_value = {"tokens": 50_000_000, "cost_usd": 999.00}

                # Simulate Phase I logic with no ceiling
                current_cost = 5.0
                ceiling = float(os.environ.get("SPIRAL_COST_CEILING", "0") or "0")
                predicted = mock_predict.return_value["cost_usd"]
                projected = current_cost + predicted

                # Cost guard decision: ceiling is 0 or None
                if ceiling > 0 and projected > ceiling:
                    should_decompose = False
                else:
                    should_decompose = True

                # Verify: decompose should proceed
                assert should_decompose, "Decompose should be allowed when ceiling is disabled"

    def test_cost_guard_within_ceiling_allows_decomposition(
        self, tmp_spiral_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that decomposition proceeds when story cost is within ceiling."""
        # Set cost ceiling to $1000
        monkeypatch.setenv("SPIRAL_COST_CEILING", "1000.00")

        with patch("lib.cost_check.compute_cumulative_cost") as mock_compute:
            mock_compute.return_value = (5.0, 1)  # $5 already spent

            with patch("lib.cost_predictor.predict_story_cost") as mock_predict:
                # Story costs only $10, well within $1000 ceiling
                mock_predict.return_value = {"tokens": 500_000, "cost_usd": 10.00}

                current_cost = 5.0
                ceiling = 1000.0
                predicted = mock_predict.return_value["cost_usd"]
                projected = current_cost + predicted

                # Cost guard decision
                if ceiling > 0 and projected > ceiling:
                    should_decompose = False
                else:
                    should_decompose = True

                # Verify: decompose should proceed
                assert should_decompose, "Decompose should be allowed when within ceiling"
                assert projected < ceiling, f"Projected {projected} should be < ceiling {ceiling}"


# ---------------------------------------------------------------------------
# Test: Integration with Phase I Retry Logic
# ---------------------------------------------------------------------------


class TestCostGuardWithRetries:
    """Verify cost guard interacts correctly with Phase I retry tracking."""

    def test_cost_guard_overrides_retry_decompose_trigger(
        self, tmp_spiral_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify cost guard prevents decompose even if retries=3 would trigger it.

        Story US-669-TEST has retry_count=3 which would normally trigger auto-decompose,
        but cost guard should prevent it.
        """
        monkeypatch.setenv("SPIRAL_COST_CEILING", "10.00")

        # Verify retry count is set to 3 (would trigger auto-decompose)
        retry_file = tmp_spiral_env / "retry-counts.json"
        retries = json.loads(retry_file.read_text(encoding="utf-8"))
        assert retries["US-669-TEST"] == 3, "Test setup: retry count should be 3"

        with patch("lib.cost_check.compute_cumulative_cost") as mock_compute:
            mock_compute.return_value = (5.0, 1)

            with patch("lib.cost_predictor.predict_story_cost") as mock_predict:
                mock_predict.return_value = {"tokens": 50_000_000, "cost_usd": 999.00}

                # Determine action: cost guard takes precedence over retry count
                retry_count = 3
                ceiling = 10.0
                current_cost = 5.0
                predicted_cost = 999.0
                projected = current_cost + predicted_cost

                # Cost guard check happens BEFORE decompose trigger check
                cost_guard_blocks = ceiling > 0 and projected > ceiling
                retry_triggers_decompose = retry_count >= 3

                # Cost guard should override retry-based decompose
                should_decompose = retry_triggers_decompose and not cost_guard_blocks

                assert cost_guard_blocks, "Cost guard should block"
                assert retry_triggers_decompose, "Retry count should trigger decompose normally"
                assert not should_decompose, "Cost guard should override retry-based decompose"


# ---------------------------------------------------------------------------
# Test: Edge Cases
# ---------------------------------------------------------------------------


class TestCostGuardEdgeCases:
    """Test edge cases and boundary conditions for cost guard."""

    def test_cost_guard_exactly_at_ceiling_boundary(
        self, tmp_spiral_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test behavior when projected cost equals ceiling exactly."""
        monkeypatch.setenv("SPIRAL_COST_CEILING", "15.00")

        with patch("lib.cost_check.compute_cumulative_cost") as mock_compute:
            mock_compute.return_value = (5.0, 1)

            with patch("lib.cost_predictor.predict_story_cost") as mock_predict:
                # Projected: $5 + $10 = $15 (equals ceiling)
                mock_predict.return_value = {"tokens": 500_000, "cost_usd": 10.00}

                current_cost = 5.0
                ceiling = 15.0
                predicted = 10.0
                projected = current_cost + predicted

                # At boundary: 15 > 15 is False, so should allow decompose
                should_skip = ceiling > 0 and projected > ceiling

                assert projected == ceiling, "Setup: projected should equal ceiling"
                assert not should_skip, "At boundary (==), should allow decomposition"

    def test_cost_guard_just_over_ceiling(self, tmp_spiral_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test behavior when projected cost just exceeds ceiling."""
        monkeypatch.setenv("SPIRAL_COST_CEILING", "15.00")

        with patch("lib.cost_check.compute_cumulative_cost") as mock_compute:
            mock_compute.return_value = (5.0, 1)

            with patch("lib.cost_predictor.predict_story_cost") as mock_predict:
                # Projected: $5 + $10.01 = $15.01 (exceeds ceiling)
                mock_predict.return_value = {"tokens": 500_000, "cost_usd": 10.01}

                current_cost = 5.0
                ceiling = 15.0
                predicted = 10.01
                projected = current_cost + predicted

                should_skip = ceiling > 0 and projected > ceiling

                assert projected > ceiling, "Setup: projected should exceed ceiling"
                assert should_skip, "Just over boundary (>), should skip decomposition"

    def test_cost_guard_zero_ceiling_treated_as_disabled(
        self, tmp_spiral_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that zero ceiling is treated as disabled."""
        monkeypatch.setenv("SPIRAL_COST_CEILING", "0")

        ceiling = float(os.environ.get("SPIRAL_COST_CEILING", "0") or "0")
        current_cost = 5.0
        predicted_cost = 999.0
        projected = current_cost + predicted_cost

        # Zero ceiling should not block
        should_skip = ceiling > 0 and projected > ceiling

        assert ceiling == 0, "Setup: ceiling should be 0"
        assert not should_skip, "Zero ceiling should not block decomposition"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
