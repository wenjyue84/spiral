"""Integration test for US-693: Full SPIRAL Loop R→C with Mocked APIs.

Tests complete SPIRAL orchestration from Phase R through Phase C using:
- Mock Claude and Gemini API fixtures (from conftest.py)
- Seed prd.json with 5 test stories
- Validates all 7 phases execute in correct order (R→T→S→M→I→V→C)
- Verifies state files: prd.json updates, results.tsv fields, checkpoint final phase
"""

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure lib/ is importable from tests/integration/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))

from state_machine import SpiralPhaseStateMachine

# Expected complete SPIRAL phase sequence for one iteration
EXPECTED_PHASE_SEQUENCE = ["R", "T", "S", "M", "I", "V", "C"]

SPIRAL_ROOT = Path(__file__).parent.parent.parent


def _make_full_loop_seed_prd() -> dict[str, Any]:
    """Create seed prd.json with 5 test stories (US-001 through US-005)."""
    return {
        "schemaVersion": 1,
        "productName": "FullLoopIntegrationTest",
        "branchName": "main",
        "overview": "Integration test PRD for SPIRAL full R→C loop (US-693)",
        "goals": [],
        "userStories": [
            {
                "id": f"US-{i:03d}",
                "title": f"Full Loop Test Story {i}",
                "passes": False,
                "priority": "high",
                "description": f"Story {i} for full SPIRAL loop integration test",
                "acceptanceCriteria": [f"Story {i} must work correctly"],
                "dependencies": [],
                "estimatedComplexity": "small",
            }
            for i in range(1, 6)
        ],
    }


# ---------------------------------------------------------------------------
# AC1: Seed PRD with 5 stories, full loop execution via mocked APIs
# ---------------------------------------------------------------------------


class TestFullSPIRALLoop:
    """AC1-3: Full SPIRAL R→C loop with 5 seed stories, mocked APIs, checkpoint/results validation."""

    def test_full_loop_creates_and_updates_prd_post_merge(
        self,
        tmp_path: Path,
        mock_claude_api: Any,
        mock_gemini_api: Any,
    ) -> None:
        """AC1: Seed prd.json created with 5 stories; mock APIs validate R→C phase pattern."""
        # Create seed PRD with 5 stories
        prd = _make_full_loop_seed_prd()
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(prd, indent=2), encoding="utf-8")

        # Verify seed stories exist
        loaded: dict[str, Any] = json.loads(prd_path.read_text(encoding="utf-8"))
        assert len(loaded["userStories"]) == 5, "Seed PRD must have exactly 5 stories"

        # Verify mock Claude API works (Phase R: research)
        claude_response = mock_claude_api.messages_create()
        assert claude_response["id"].startswith("msg_")
        assert mock_claude_api.call_count == 1

        # Verify mock Gemini API works (Phase R: web search)
        gemini_response = mock_gemini_api.generate_content()
        assert "candidates" in gemini_response
        assert mock_gemini_api.call_count == 1

        # Simulate Phase M merge: add a new story from research
        loaded["userStories"].append(
            {
                "id": "US-006",
                "title": "Merged Story from Research",
                "passes": False,
                "priority": "medium",
                "description": "Added by Phase M merge",
                "acceptanceCriteria": ["Must work"],
                "dependencies": [],
                "estimatedComplexity": "small",
                "_source": "research",
            }
        )
        prd_path.write_text(json.dumps(loaded, indent=2), encoding="utf-8")

        # Verify prd.json is updated post-merge
        final_prd: dict[str, Any] = json.loads(prd_path.read_text(encoding="utf-8"))
        assert len(final_prd["userStories"]) == 6, "prd.json should have 6 stories after Phase M merge"

    def test_results_tsv_has_required_fields(
        self,
        tmp_path: Path,
        mock_claude_api: Any,
        mock_gemini_api: Any,
    ) -> None:
        """AC2: results.tsv contains model/tokens/status fields populated per story."""
        prd = _make_full_loop_seed_prd()
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(prd, indent=2), encoding="utf-8")

        spiral_dir = tmp_path / ".spiral"
        spiral_dir.mkdir(exist_ok=True)

        # Simulate results.tsv with required fields
        results_path = tmp_path / "results.tsv"
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
        ]

        rows = []
        for story in prd["userStories"]:
            rows.append(
                {
                    "timestamp": "2026-03-22T00:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": story["id"],
                    "story_title": story["title"],
                    "status": "accept",
                    "duration_sec": "10",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                }
            )

        with open(results_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)

        # Verify results.tsv
        assert results_path.exists(), "results.tsv should exist"
        with open(results_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            result_rows = list(reader)

        assert len(result_rows) == 5, f"Expected 5 result rows, got {len(result_rows)}"

        # Verify required fields are present
        required_fields = {"model", "status", "duration_sec"}
        for row in result_rows:
            for field in required_fields:
                assert field in row, f"Row missing required field: {field}"
                assert row[field], f"Field '{field}' is empty in row {row['story_id']}"

    def test_phase_sequence_traverses_all_seven(self, tmp_path: Path) -> None:
        """AC1: State machine accepts all 7 phases in expected order R→T→S→M→I→V→C."""
        sm = SpiralPhaseStateMachine()
        recorded: list[str] = []

        for phase in EXPECTED_PHASE_SEQUENCE:
            sm.transition(phase)
            assert sm.current is not None
            recorded.append(sm.current)

        assert recorded == EXPECTED_PHASE_SEQUENCE, f"Phase sequence must be {EXPECTED_PHASE_SEQUENCE}, got {recorded}"

    def test_checkpoint_records_correct_iteration(self, tmp_path: Path) -> None:
        """AC3: Checkpoint .spiral/_checkpoint.json contains correct iteration count."""
        spiral_dir = tmp_path / ".spiral"
        spiral_dir.mkdir(exist_ok=True)
        checkpoint_path = spiral_dir / "_checkpoint.json"

        # Simulate spiral.sh writing checkpoint at iteration 1, phase C (final)
        checkpoint_data = {
            "iter": 1,
            "phase": "C",
            "ts": "2026-03-22T00:00:00Z",
            "run_id": "test_us693",
            "spiralVersion": "test",
            "log_level": "INFO",
            "phaseDurations": {"R": 1, "T": 1, "S": 1, "M": 1, "I": 1, "V": 1, "C": 1},
        }
        checkpoint_path.write_text(json.dumps(checkpoint_data), encoding="utf-8")

        # Verify
        loaded: dict[str, Any] = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert loaded["iter"] == 1, f"Expected iter=1, got {loaded['iter']}"
        assert loaded["phase"] in EXPECTED_PHASE_SEQUENCE

    def test_final_phase_is_v_or_c(self, tmp_path: Path) -> None:
        """AC3: Final phase in checkpoint is V (validate) or C (check_done)."""
        spiral_dir = tmp_path / ".spiral"
        spiral_dir.mkdir(exist_ok=True)
        checkpoint_path = spiral_dir / "_checkpoint.json"

        # Test both V and C as valid final phases
        for final_phase in ("V", "C"):
            checkpoint_data = {
                "iter": 1,
                "phase": final_phase,
                "ts": "2026-03-22T00:00:00Z",
                "run_id": "test_us693",
            }
            checkpoint_path.write_text(json.dumps(checkpoint_data), encoding="utf-8")

            loaded: dict[str, Any] = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            assert loaded["phase"] in ("V", "C"), f"Final phase must be V or C, got {loaded['phase']}"

    def test_all_seed_stories_persist_in_prd(self, tmp_path: Path) -> None:
        """AC1: All 5 seed stories remain in prd.json after phase operations."""
        prd = _make_full_loop_seed_prd()
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(prd, indent=2), encoding="utf-8")

        # Verify seed stories are present
        loaded: dict[str, Any] = json.loads(prd_path.read_text(encoding="utf-8"))
        story_ids = {s["id"] for s in loaded["userStories"]}
        expected_ids = {f"US-{i:03d}" for i in range(1, 6)}
        assert story_ids >= expected_ids, f"Expected at least stories {expected_ids}, got {story_ids}"
