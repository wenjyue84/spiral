"""tests/test_dry_run_planner.py -- Tests for dry-run planning"""

import json
import sys
from pathlib import Path

import pytest

# Add lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.dry_run_planner import (
    format_ascii_tree,
    format_json_plan,
    plan_execution,
)


@pytest.fixture
def sample_prd() -> dict[str, list[dict[str, str]]]:
    """Sample PRD with 5 stories for testing."""
    return {
        "userStories": [
            {"id": "US-1", "title": "Feature A", "estimatedComplexity": "small"},
            {"id": "US-2", "title": "Feature B", "estimatedComplexity": "medium"},
            {"id": "US-3", "title": "Feature C", "estimatedComplexity": "large"},
            {"id": "US-4", "title": "Feature D", "estimatedComplexity": "small"},
            {"id": "US-5", "title": "Feature E", "estimatedComplexity": "medium"},
        ]
    }


def test_dry_run_plan_structure(sample_prd: dict[str, list[dict[str, str]]]) -> None:
    """Test that plan_execution produces all phases in correct order with non-zero tokens."""
    plan = plan_execution(sample_prd, num_iterations=5)

    # Verify all 12 phases present
    assert len(plan.phases) == 12, f"Expected 12 phases, got {len(plan.phases)}"

    # Verify phases are in expected order
    expected_phase_starts = [
        "A: AI Suggestions",
        "R: Research",
        "T: Test Synthesis",
        "S: Story Validate",
        "E: Enrichment",
        "M: Merge",
        "X: Context Build",
        "G: Gate",
        "I: Implement",
        "V: Validate",
        "C: Check Done",
        "L: Learning",
    ]

    for i, expected_start in enumerate(expected_phase_starts):
        assert plan.phases[i].name.startswith(expected_start.split(":")[0]), (
            f"Phase {i}: expected {expected_start}, got {plan.phases[i].name}"
        )

    # Verify all phases have non-zero tokens
    for phase in plan.phases:
        assert phase.estimated_tokens > 0, f"Phase {phase.name} has 0 tokens"

    # Verify total tokens > 0
    assert plan.total_estimated_tokens > 0

    # Verify worker_plan is set
    assert plan.worker_plan == "1 worker (sequential)"


def test_format_ascii_tree(sample_prd: dict[str, list[dict[str, str]]]) -> None:
    """Test ASCII tree formatting."""
    plan = plan_execution(sample_prd, num_iterations=3)
    output = format_ascii_tree(plan)

    # Verify key strings present
    assert "SPIRAL Dry-Run Execution Plan" in output
    assert "Iterations" in output
    assert "Stories" in output
    assert "Workers" in output
    assert "Phase Breakdown" in output
    assert "TOTAL" in output
    assert "Estimated Cost" in output

    # Verify numeric output
    assert "3" in output  # iterations
    assert "5" in output  # story count
    assert "$" in output  # cost estimate

    # Verify it's not empty and has reasonable length
    assert len(output) > 200


def test_format_json_plan(sample_prd: dict[str, list[dict[str, str]]]) -> None:
    """Test JSON plan formatting."""
    plan = plan_execution(sample_prd, num_iterations=2)
    json_output = format_json_plan(plan)

    # Verify top-level keys
    assert "num_iterations" in json_output
    assert "phases" in json_output
    assert "total_estimated_cost" in json_output
    assert "worker_plan" in json_output

    # Verify values
    assert json_output["num_iterations"] == 2
    assert json_output["num_iterations"] == 2
    assert json_output["worker_plan"] == "1 worker (sequential)"

    # Verify phases array
    assert isinstance(json_output["phases"], list)
    assert len(json_output["phases"]) == 12

    # Verify each phase has required fields
    for phase in json_output["phases"]:
        assert "name" in phase
        assert "estimated_tokens" in phase
        assert "story_count" in phase
        assert phase["estimated_tokens"] > 0

    # Verify can serialize to JSON
    json_str = json.dumps(json_output)
    assert len(json_str) > 0

    # Verify can deserialize back
    parsed = json.loads(json_str)
    assert parsed["num_iterations"] == 2


def test_plan_scales_with_iterations(sample_prd: dict[str, list[dict[str, str]]]) -> None:
    """Test that token estimates scale with iteration count."""
    plan_1 = plan_execution(sample_prd, num_iterations=1)
    plan_5 = plan_execution(sample_prd, num_iterations=5)

    # 5 iterations should have ~5x tokens
    ratio = plan_5.total_estimated_tokens / plan_1.total_estimated_tokens
    assert 4.5 < ratio < 5.5, f"Expected ~5x scaling, got {ratio}x"


def test_empty_prd(temp_path: Path | None = None) -> None:
    """Test plan with empty PRD."""
    empty_prd: dict[str, list[dict[str, str]]] = {"userStories": []}
    plan = plan_execution(empty_prd, num_iterations=1)

    # Should still generate all phases with reasonable tokens
    assert len(plan.phases) == 12
    assert plan.total_estimated_tokens > 0

    # Output should still format correctly
    ascii_out = format_ascii_tree(plan)
    assert "0" in ascii_out  # 0 stories


def test_large_prd(sample_prd: dict[str, list[dict[str, str]]]) -> None:
    """Test plan with large number of stories."""
    large_prd = sample_prd.copy()
    # Add 95 more stories (total 100)
    for i in range(6, 101):
        large_prd["userStories"].append({"id": f"US-{i}", "title": f"Feature {i}", "estimatedComplexity": "small"})

    plan = plan_execution(large_prd, num_iterations=2)

    # Should have higher token estimates due to scaling
    assert plan.total_estimated_tokens > 0
    assert plan.phases[8].story_count == 100  # Implement phase shows story count
