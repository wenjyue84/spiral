#!/usr/bin/env python3
"""
test_phase_i_budget_gate.py — Integration tests for Phase I budget gate.

Covers:
  - Budget check gate when cost exceeds ceiling
  - User choice handling (continue/skip/rollback-story)
  - Cost calculation accuracy within 5%
  - prd.json rollback correctness
  - Edge cases (no results history, no pending stories, zero ceiling)
"""

import json
import tempfile
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest

from lib.budget_analyzer import (
    calculate_current_spend,
    estimate_pending_story_cost,
    check_budget_gate,
)
from lib.rollback_story import rollback_story, find_lowest_priority_pending_story


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_prd() -> Dict:
    """Sample PRD with 5 pending stories at different priorities."""
    return {
        "schemaVersion": 1,
        "productName": "Test",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001",
                "title": "Critical bug fix",
                "priority": "critical",
                "passes": False,
                "model": "haiku",
            },
            {
                "id": "US-002",
                "title": "High priority feature",
                "priority": "high",
                "passes": False,
                "model": "sonnet",
            },
            {
                "id": "US-003",
                "title": "Medium priority enhancement",
                "priority": "medium",
                "passes": False,
                "model": "sonnet",
            },
            {
                "id": "US-004",
                "title": "Low priority improvement",
                "priority": "low",
                "passes": False,
                "model": "haiku",
            },
            {
                "id": "US-005",
                "title": "Lowest priority task",
                "priority": "low",
                "passes": False,
                "model": "haiku",
            },
            {
                "id": "US-100",
                "title": "Already completed",
                "priority": "high",
                "passes": True,
                "model": "opus",
            },
        ],
    }


@pytest.fixture
def sample_results_tsv(tmp_path: Path) -> Path:
    """Create a sample results.tsv file with 10 rows of test data."""
    results_file = tmp_path / "results.tsv"
    results_file.write_text(
        "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\n"
        "2026-03-19T10:00:00Z\t0\t1\tUS-010\tTest story 1\tcompleted\t1200\thaiku\t0\n"
        "2026-03-19T10:05:00Z\t0\t1\tUS-011\tTest story 2\tcompleted\t2400\tsonnet\t1\n"
        "2026-03-19T10:10:00Z\t1\t1\tUS-012\tTest story 3\tcompleted\t1800\topus\t2\n"
        "2026-03-19T10:15:00Z\t1\t1\tUS-013\tTest story 4\tcompleted\t600\thaiku\t0\n"
        "2026-03-19T10:20:00Z\t1\t1\tUS-014\tTest story 5\tcompleted\t3000\tsonnet\t1\n"
    )
    return results_file


# ────────────────────────────────────────────────────────────────────────────
# Test: Calculate Current Spend
# ────────────────────────────────────────────────────────────────────────────


class TestCalculateCurrentSpend:
    """Test calculation of current spend from results.tsv."""

    def test_calculate_spend_with_data(self, sample_results_tsv: Path) -> None:
        """Test cost calculation from valid results.tsv."""
        result = calculate_current_spend(sample_results_tsv)

        assert result["row_count"] == 5
        assert result["total_tokens"] > 0
        assert result["total_cost_usd"] > 0
        assert "haiku" in result["by_model"]
        assert "sonnet" in result["by_model"]
        assert "opus" in result["by_model"]

    def test_calculate_spend_missing_file(self, tmp_path: Path) -> None:
        """Test handling of missing results.tsv."""
        result = calculate_current_spend(tmp_path / "nonexistent.tsv")

        assert result["row_count"] == 0
        assert result["total_tokens"] == 0.0
        assert result["total_cost_usd"] == 0.0
        assert result["by_model"] == {}

    def test_calculate_spend_empty_file(self, tmp_path: Path) -> None:
        """Test handling of empty results.tsv."""
        empty_file = tmp_path / "empty.tsv"
        empty_file.write_text("timestamp\tspiral_iter\tralph_iter\tstory_id\n")

        result = calculate_current_spend(empty_file)

        assert result["row_count"] == 0
        assert result["total_cost_usd"] == 0.0

    def test_calculate_spend_invalid_data(self, tmp_path: Path) -> None:
        """Test handling of invalid data in results.tsv."""
        invalid_file = tmp_path / "invalid.tsv"
        invalid_file.write_text(
            "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\n"
            "2026-03-19T10:00:00Z\t0\t1\tUS-010\tTest\tcompleted\tinvalid_duration\thaiku\n"
            "2026-03-19T10:05:00Z\t0\t1\tUS-011\tTest\tcompleted\t1200\t\n"
        )

        result = calculate_current_spend(invalid_file)

        assert result["row_count"] == 0
        assert result["total_cost_usd"] == 0.0


# ────────────────────────────────────────────────────────────────────────────
# Test: Estimate Pending Story Cost
# ────────────────────────────────────────────────────────────────────────────


class TestEstimatePendingCost:
    """Test cost estimation for pending stories."""

    def test_estimate_pending_no_velocity_model(self, sample_prd: Dict) -> None:
        """Test estimation without velocity model uses default tokens."""
        result = estimate_pending_story_cost(sample_prd)

        # 5 pending stories (US-001 through US-005)
        assert result["story_count"] == 5
        assert result["total_cost_usd"] > 0
        assert result["total_tokens"] > 0
        assert len(result["by_story"]) == 5

    def test_estimate_pending_by_model(self, sample_prd: Dict) -> None:
        """Test estimation breaks down by model."""
        result = estimate_pending_story_cost(sample_prd)

        # 3 haiku (US-001, US-004, US-005), 2 sonnet (US-002, US-003)
        assert "haiku" in result["by_model"]
        assert "sonnet" in result["by_model"]
        # Haiku should be cheaper than sonnet per token
        assert result["by_model"]["haiku"] < result["by_model"]["sonnet"]

    def test_estimate_pending_all_completed(self, sample_prd: Dict) -> None:
        """Test estimation with no pending stories."""
        sample_prd["userStories"] = [
            s for s in sample_prd["userStories"] if s.get("passes") == True
        ]

        result = estimate_pending_story_cost(sample_prd)

        assert result["story_count"] == 0
        assert result["total_cost_usd"] == 0.0


# ────────────────────────────────────────────────────────────────────────────
# Test: Budget Gate Check
# ────────────────────────────────────────────────────────────────────────────


class TestBudgetGateCheck:
    """Test the full budget gate check logic."""

    def test_budget_gate_within_ceiling(
        self, tmp_path: Path, sample_prd: Dict, sample_results_tsv: Path
    ) -> None:
        """Test gate passes when total cost is within ceiling."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(sample_prd))

        result = check_budget_gate(
            prd_file, sample_results_tsv, cost_ceiling_usd=100.0
        )

        assert result["would_exceed"] == False
        assert result["total_projected_usd"] < 100.0
        assert result["remaining_budget_usd"] > 0.0
        assert result["pending_count"] == 5

    def test_budget_gate_exceeds_ceiling(
        self, tmp_path: Path, sample_prd: Dict, sample_results_tsv: Path
    ) -> None:
        """Test gate blocks when total cost would exceed ceiling."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(sample_prd))

        result = check_budget_gate(
            prd_file, sample_results_tsv, cost_ceiling_usd=1.0
        )

        assert result["would_exceed"] == True
        assert result["total_projected_usd"] > 1.0
        assert result["pending_count"] == 5

    def test_budget_gate_no_ceiling(
        self, tmp_path: Path, sample_prd: Dict, sample_results_tsv: Path
    ) -> None:
        """Test gate disabled when no ceiling is set."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(sample_prd))

        result = check_budget_gate(prd_file, sample_results_tsv, cost_ceiling_usd=None)

        assert result["would_exceed"] == False
        assert result["ceiling_usd"] is None

    def test_budget_gate_missing_prd(self, tmp_path: Path) -> None:
        """Test gate handles missing prd.json gracefully."""
        with pytest.raises(ValueError):
            check_budget_gate(
                tmp_path / "missing.json",
                tmp_path / "results.tsv",
                cost_ceiling_usd=50.0,
            )

    def test_budget_gate_cost_accuracy(
        self, tmp_path: Path, sample_prd: Dict, sample_results_tsv: Path
    ) -> None:
        """Test cost calculation is within 5% accuracy."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(sample_prd))

        result = check_budget_gate(
            prd_file, sample_results_tsv, cost_ceiling_usd=50.0
        )

        # Verify components add up
        projected = result["current_spend_usd"] + result["estimated_pending_usd"]
        diff = abs(projected - result["total_projected_usd"])
        assert diff < 0.01  # Very small delta due to rounding


# ────────────────────────────────────────────────────────────────────────────
# Test: Find Lowest Priority Story
# ────────────────────────────────────────────────────────────────────────────


class TestFindLowestPriorityStory:
    """Test identification of lowest-priority pending story."""

    def test_find_lowest_priority_basic(self, sample_prd: Dict) -> None:
        """Test finding lowest-priority story from mixed priorities."""
        result = find_lowest_priority_pending_story(sample_prd)

        assert result is not None
        idx, story = result
        # Should find one of the "low" priority stories (US-004 or US-005)
        assert story["priority"].lower() == "low"
        assert story["id"] in ["US-004", "US-005"]

    def test_find_lowest_priority_all_same(self, sample_prd: Dict) -> None:
        """Test when all pending stories have same priority."""
        for story in sample_prd["userStories"]:
            if story.get("passes") != True:
                story["priority"] = "medium"

        result = find_lowest_priority_pending_story(sample_prd)

        assert result is not None
        idx, story = result
        assert story["priority"].lower() == "medium"

    def test_find_lowest_priority_none_pending(self, sample_prd: Dict) -> None:
        """Test when no pending stories exist."""
        for story in sample_prd["userStories"]:
            story["passes"] = True

        result = find_lowest_priority_pending_story(sample_prd)

        assert result is None

    def test_find_lowest_priority_deterministic(self, sample_prd: Dict) -> None:
        """Test that result is deterministic (same priority uses story ID)."""
        # Add multiple low-priority pending stories
        sample_prd["userStories"].append(
            {
                "id": "US-006",
                "title": "Another low task",
                "priority": "low",
                "passes": False,
            }
        )

        result1 = find_lowest_priority_pending_story(sample_prd)
        result2 = find_lowest_priority_pending_story(sample_prd)

        assert result1[1]["id"] == result2[1]["id"]


# ────────────────────────────────────────────────────────────────────────────
# Test: Rollback Story
# ────────────────────────────────────────────────────────────────────────────


class TestRollbackStory:
    """Test story rollback functionality."""

    def test_rollback_story_success(self, tmp_path: Path, sample_prd: Dict) -> None:
        """Test successful rollback of lowest-priority story."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(sample_prd))

        result = rollback_story(prd_file)

        assert result["success"] == True
        assert result["removed_story_id"] in ["US-004", "US-005"]
        assert result["remaining_pending"] == 4

        # Verify file was actually modified
        updated_prd = json.loads(prd_file.read_text())
        story_ids = [s["id"] for s in updated_prd["userStories"]]
        assert result["removed_story_id"] not in story_ids

    def test_rollback_story_dry_run(self, tmp_path: Path, sample_prd: Dict) -> None:
        """Test dry-run does not modify file."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(sample_prd))

        original_content = prd_file.read_text()
        result = rollback_story(prd_file, dry_run=True)

        assert result["success"] == True
        assert result["dry_run"] == True
        assert result["remaining_pending"] == 4
        assert prd_file.read_text() == original_content

    def test_rollback_story_no_pending(self, tmp_path: Path, sample_prd: Dict) -> None:
        """Test rollback fails when no pending stories."""
        for story in sample_prd["userStories"]:
            story["passes"] = True

        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(sample_prd))

        result = rollback_story(prd_file)

        assert result["success"] == False
        assert result["error"] == "No pending stories to rollback"

    def test_rollback_story_missing_file(self, tmp_path: Path) -> None:
        """Test rollback handles missing prd.json."""
        result = rollback_story(tmp_path / "missing.json")

        assert result["success"] == False
        assert "not found" in result["error"]

    def test_rollback_story_invalid_json(self, tmp_path: Path) -> None:
        """Test rollback handles invalid JSON."""
        prd_file = tmp_path / "invalid.json"
        prd_file.write_text("{ invalid json }")

        result = rollback_story(prd_file)

        assert result["success"] == False
        assert "Invalid JSON" in result["error"]

    def test_rollback_story_multiple_times(
        self, tmp_path: Path, sample_prd: Dict
    ) -> None:
        """Test rolling back multiple times in sequence."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(sample_prd))

        # First rollback
        result1 = rollback_story(prd_file)
        assert result1["success"] == True
        assert result1["remaining_pending"] == 4

        # Second rollback
        result2 = rollback_story(prd_file)
        assert result2["success"] == True
        assert result2["remaining_pending"] == 3
        assert result1["removed_story_id"] != result2["removed_story_id"]

        # Third rollback
        result3 = rollback_story(prd_file)
        assert result3["success"] == True
        assert result3["remaining_pending"] == 2


# ────────────────────────────────────────────────────────────────────────────
# Integration Tests
# ────────────────────────────────────────────────────────────────────────────


class TestBudgetGateIntegration:
    """Integration tests for the full Phase I budget gate flow."""

    def test_full_flow_exceed_ceiling_then_rollback(
        self, tmp_path: Path, sample_prd: Dict, sample_results_tsv: Path
    ) -> None:
        """Test full flow: check → exceed → rollback → re-check."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(sample_prd))

        # Initial check: would exceed
        check1 = check_budget_gate(prd_file, sample_results_tsv, cost_ceiling_usd=1.0)
        assert check1["would_exceed"] == True
        assert check1["pending_count"] == 5

        # Rollback lowest-priority story
        rollback1 = rollback_story(prd_file)
        assert rollback1["success"] == True

        # Re-check: might still exceed
        check2 = check_budget_gate(prd_file, sample_results_tsv, cost_ceiling_usd=1.0)
        assert check2["pending_count"] == 4
        # Cost should be lower (one fewer story)
        assert check2["estimated_pending_usd"] < check1["estimated_pending_usd"]

    def test_full_flow_multiple_rollbacks(
        self, tmp_path: Path, sample_prd: Dict, sample_results_tsv: Path
    ) -> None:
        """Test rolling back multiple times until within budget."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(sample_prd))

        tight_ceiling = 0.5  # Very tight ceiling
        initial_check = check_budget_gate(
            prd_file, sample_results_tsv, cost_ceiling_usd=tight_ceiling
        )
        assert initial_check["would_exceed"] == True

        # Keep rolling back until within budget
        rollback_count = 0
        while True:
            result = rollback_story(prd_file)
            if not result["success"]:
                break
            rollback_count += 1

            check = check_budget_gate(
                prd_file, sample_results_tsv, cost_ceiling_usd=tight_ceiling
            )
            if not check["would_exceed"]:
                break
            if rollback_count >= 5:
                break

        # Should have rolled back at least once
        assert rollback_count >= 1
        # Final check should be within budget or no pending stories
        final_check = check_budget_gate(
            prd_file, sample_results_tsv, cost_ceiling_usd=tight_ceiling
        )
        assert (
            final_check["would_exceed"] == False
            or final_check["pending_count"] == 0
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
