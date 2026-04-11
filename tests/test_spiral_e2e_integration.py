"""E2E integration tests for SPIRAL.

Tests the complete SPIRAL loop: Phase A → Phase R/T → Phase S → Phase M → Phase I → Phase V → Phase C.
Uses mocked environment variables and ralph.sh to run without external dependencies.
"""

import json
from pathlib import Path


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
