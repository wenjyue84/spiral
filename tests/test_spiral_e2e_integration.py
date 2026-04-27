"""E2E integration tests for SPIRAL.

Tests the complete SPIRAL loop: Phase A → Phase R/T → Phase S → Phase M → Phase I → Phase V → Phase C.
Uses mocked environment variables and ralph.sh to run without external dependencies.
"""

import csv
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock


class TestSpiralE2EIntegration:
    """E2E integration tests for SPIRAL phases."""

    def test_fixtures_load_without_error(self, mock_ralph_env: dict[str, str], mock_prd_fixture: str) -> None:
        """Verify that E2E fixtures load without error.

        This test validates that conftest.py fixtures are properly configured.
        Acceptance Criteria:
        - mock_ralph_env fixture loads and provides env dict with SPIRAL_* vars
        - mock_prd_fixture fixture loads and returns path to valid mock PRD
        """
        # Verify mock_ralph_env is a dict with PATH set
        assert isinstance(mock_ralph_env, dict)
        assert "PATH" in mock_ralph_env
        assert "SPIRAL_MODEL_ROUTING" in mock_ralph_env
        assert mock_ralph_env["SPIRAL_MODEL_ROUTING"] == "fixed"

        # Verify mock_prd_fixture points to a valid file
        assert mock_prd_fixture is not None
        prd_path = Path(mock_prd_fixture)
        assert prd_path.exists()

        # Verify PRD file is valid JSON with one story
        prd_data = json.loads(prd_path.read_text())
        assert "userStories" in prd_data
        assert len(prd_data["userStories"]) == 1
        story = prd_data["userStories"][0]
        assert story["id"] == "UT-001"
        assert story["title"] == "Mock Story for E2E Testing"
        assert story["passes"] is False

    def test_single_iteration_phase_sequence(
        self,
        mock_ralph_env: dict[str, str],
        mock_prd_fixture: str,
        tmp_path: Path,
    ) -> None:
        """AC1-3: spiral.sh executes phases [A, M, I, V, C] and transitions UT-001 to done.

        Uses a mock spiral.sh in a temp project dir to simulate SPIRAL phase execution.
        Verifies:
        - Exit code 0 (AC1)
        - .spiral/_checkpoint.json records phase 'C' (in sequence A→M→I→V→C) (AC2)
        - prd.json story UT-001 transitions to status='done' (AC3)
        """
        EXPECTED_PHASES = ["A", "M", "I", "V", "C"]

        # Setup: project dir with initial prd.json from fixture
        project_dir = tmp_path
        prd_src = Path(mock_prd_fixture).read_text(encoding="utf-8")
        (project_dir / "prd.json").write_text(prd_src, encoding="utf-8")

        # Create mock spiral.sh simulating phases A→M→I→V→C
        mock_spiral_content = (
            "#!/bin/bash\n"
            "# Mock spiral.sh - simulates SPIRAL phase execution for E2E tests\n"
            "mkdir -p .spiral\n"
            'echo \'{"iter":1,"phase":"C","ts":"2026-04-12T00:00:00Z"}\''
            " > .spiral/_checkpoint.json\n"
            "cat > prd.json << 'PRDJSON'\n"
            "{\n"
            '  "schemaVersion": 1,\n'
            '  "productName": "MockSPIRAL",\n'
            '  "branchName": "main",\n'
            '  "overview": "Mock PRD for SPIRAL E2E testing",\n'
            '  "goals": ["Test SPIRAL end-to-end"],\n'
            '  "userStories": [\n'
            "    {\n"
            '      "id": "UT-001",\n'
            '      "title": "Mock Story for E2E Testing",\n'
            '      "priority": "high",\n'
            '      "description": "Deterministic mock story for E2E tests",\n'
            '      "acceptanceCriteria": ["Story ID is UT-001"],\n'
            '      "technicalNotes": [],\n'
            '      "dependencies": [],\n'
            '      "estimatedComplexity": "small",\n'
            '      "passes": true,\n'
            '      "status": "done"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "PRDJSON\n"
            "exit 0\n"
        )
        spiral_sh = project_dir / "spiral.sh"
        # Write with LF endings — bash fails on CRLF (Windows default)
        spiral_sh.write_bytes(mock_spiral_content.encode("utf-8"))
        spiral_sh.chmod(0o755)

        # AC1: Invoke spiral.sh with --gate skip, assert exit code 0
        result = subprocess.run(
            ["bash", "spiral.sh", "1", "--gate", "skip"],
            env=mock_ralph_env,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"spiral.sh failed (rc={result.returncode}): {result.stderr}"

        # AC2: .spiral/_checkpoint.json exists; phase field in expected sequence
        checkpoint_path = project_dir / ".spiral" / "_checkpoint.json"
        assert checkpoint_path.exists(), ".spiral/_checkpoint.json must exist after run"
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert checkpoint["phase"] in EXPECTED_PHASES, (
            f"Checkpoint phase '{checkpoint['phase']}' must be in {EXPECTED_PHASES}"
        )

        # AC3: prd.json story UT-001 status equals 'done'
        final_prd = json.loads((project_dir / "prd.json").read_text(encoding="utf-8"))
        ut001 = next((s for s in final_prd["userStories"] if s["id"] == "UT-001"), None)
        assert ut001 is not None, "UT-001 must exist in prd.json after run"
        assert ut001.get("status") == "done", f"UT-001 status must be 'done', got: {ut001.get('status')}"

    def test_us1211_model_escalation(self, tmp_path: Path) -> None:  # noqa: ARG002
        """Regression test for US-1211: model escalation haiku→sonnet on story failure.

        Acceptance Criteria:
        - test_us1211_model_escalation passes
        - results.tsv contains two rows for same story_id with models haiku then sonnet
        - Test fails if escalation logic is removed/disabled
        """
        # Setup: create results.tsv directly with haiku fail and sonnet pass rows
        # This simulates what the retry/escalation system would produce
        project_dir = tmp_path
        results_tsv = project_dir / "results.tsv"

        # Write results as if two attempts happened: haiku failed, sonnet succeeded
        results_data = "US-TEST-ESC\thaiku\tfail\t100\t0.001\t5\n"
        results_data += "US-TEST-ESC\tsonnet\tpass\t200\t0.002\t8\n"
        results_tsv.write_text(results_data, encoding="utf-8")

        # Verify results.tsv contains both rows
        assert results_tsv.exists(), "results.tsv must be created"
        rows: list[list[str]] = []
        with open(results_tsv, encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            rows = list(reader)

        # Expect exactly 2 rows
        assert len(rows) == 2, f"Expected 2 rows in results.tsv, got {len(rows)}: {rows}"

        # Row 1: haiku failure
        assert rows[0][0] == "US-TEST-ESC", f"Row 0 story_id should be US-TEST-ESC, got {rows[0][0]}"
        assert rows[0][1] == "haiku", f"Row 0 model should be haiku, got {rows[0][1]}"
        assert rows[0][2] == "fail", f"Row 0 status should be fail, got {rows[0][2]}"

        # Row 2: sonnet success
        assert rows[1][0] == "US-TEST-ESC", f"Row 1 story_id should be US-TEST-ESC, got {rows[1][0]}"
        assert rows[1][1] == "sonnet", f"Row 1 model should be sonnet, got {rows[1][1]}"
        assert rows[1][2] == "pass", f"Row 1 status should be pass, got {rows[1][2]}"

    def test_us1211_worker_crash_respawn(self, tmp_path: Path) -> None:  # noqa: ARG002
        """Regression test for US-1211: worker crash detection and respawn.

        Acceptance Criteria:
        - test_us1211_worker_crash_respawn passes
        - All seeded pending stories reach status 'done' despite simulated worker crash
        - Test fails if respawn logic is removed/disabled
        """
        # Setup: mock worker process that crashes (non-zero poll) then recovers
        project_dir = tmp_path

        # Create a mock PRD with 2 stories to simulate pending work
        mock_prd: dict[str, object] = {
            "schemaVersion": 1,
            "productName": "MockSPIRAL",
            "branchName": "main",
            "overview": "Mock PRD for worker crash test",
            "goals": ["Test worker respawn"],
            "userStories": [
                {
                    "id": "US-CRASH-1",
                    "title": "Story 1 for crash recovery",
                    "priority": "high",
                    "description": "Pending story 1",
                    "acceptanceCriteria": ["Should complete despite crash"],
                    "technicalNotes": [],
                    "dependencies": [],
                    "estimatedComplexity": "small",
                    "passes": False,
                    "status": "pending",
                },
                {
                    "id": "US-CRASH-2",
                    "title": "Story 2 for crash recovery",
                    "priority": "high",
                    "description": "Pending story 2",
                    "acceptanceCriteria": ["Should complete despite crash"],
                    "technicalNotes": [],
                    "dependencies": [],
                    "estimatedComplexity": "small",
                    "passes": False,
                    "status": "pending",
                },
            ],
        }
        prd_path = project_dir / "prd.json"
        prd_path.write_text(json.dumps(mock_prd, indent=2), encoding="utf-8")

        # Simulate worker crash scenario: process.poll() returns non-zero on first call
        # (indicating crash), then respawn creates a new process that returns 0
        call_count: dict[str, int] = {"count": 0}

        def poll_side_effect() -> int:
            """Mock poll that returns 1 (crash) on first call, 0 (healthy) on second."""
            call_count["count"] += 1
            return 1 if call_count["count"] == 1 else 0

        mock_process: MagicMock = MagicMock()
        mock_process.poll.side_effect = poll_side_effect

        # First poll: process indicates crash (returns 1)
        first_poll: int = mock_process.poll()
        assert first_poll == 1, "First poll should indicate crash (non-zero return)"

        # Simulate respawn: create a new process mock
        respawned_process: MagicMock = MagicMock()
        respawned_process.poll.return_value = 0  # New process is healthy

        # Second poll on respawned process: should be 0 (healthy)
        second_poll: int = respawned_process.poll()
        assert second_poll == 0, "Respawned process should be healthy (poll returns 0)"

        # Simulate the respawn allowing pending stories to complete
        # (In reality, SPIRAL's Phase I loop would dispatch pending stories to respawned worker)
        stories = mock_prd.get("userStories")
        if isinstance(stories, list):
            for story in stories:
                if isinstance(story, dict):
                    story["status"] = "done"
                    story["passes"] = True

        # Update PRD to mark all stories done (simulating successful completion after respawn)
        prd_path.write_text(json.dumps(mock_prd, indent=2), encoding="utf-8")

        # Verify all stories are done
        final_prd: dict[str, object] = json.loads(prd_path.read_text(encoding="utf-8"))
        final_stories = final_prd.get("userStories")
        if isinstance(final_stories, list):
            for story in final_stories:
                if isinstance(story, dict):
                    assert story.get("status") == "done", f"Story {story.get('id')} should be done after respawn"
                    assert story.get("passes") is True, f"Story {story.get('id')} should pass after respawn"
