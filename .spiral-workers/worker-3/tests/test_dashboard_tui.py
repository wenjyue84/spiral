"""Tests for spiral_dashboard.py TUI mode (US-271)."""

import json
import os
import sys

import pytest

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

# Import after path setup
from spiral_dashboard import HAS_TEXTUAL, load_prd


# Fixtures for PRD data
@pytest.fixture
def fixture_prd():
    """Minimal fixture prd.json for testing."""
    return {
        "userStories": [
            {
                "id": "US-271",
                "title": "Add Textual-based interactive TUI mode",
                "priority": "medium",
                "passes": False,
                "acceptanceCriteria": [
                    "Running 'python spiral_dashboard.py --tui' launches a Textual app",
                    "Arrow keys navigate the story list",
                ],
            },
            {
                "id": "US-272",
                "title": "Example second story",
                "priority": "high",
                "passes": True,
                "acceptanceCriteria": ["Test story for TUI"],
            },
        ]
    }


@pytest.fixture
def temp_prd_file(fixture_prd, tmp_path):
    """Create a temporary prd.json file."""
    prd_path = tmp_path / "prd.json"
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(fixture_prd, f)
    return str(prd_path)


@pytest.mark.skipif(not HAS_TEXTUAL, reason="Textual not installed")
class TestSpiralDashboardTUI:
    """Tests for TUI components."""

    def test_tui_module_imports(self):
        """Verify Textual components are available when HAS_TEXTUAL is True."""
        from spiral_dashboard import LogPanel, SpiralDashboardApp, StoriesTable

        assert SpiralDashboardApp is not None
        assert StoriesTable is not None
        assert LogPanel is not None

    def test_stories_table_widget_creation(self, fixture_prd):
        """Test StoriesTable widget can be instantiated with stories."""
        from spiral_dashboard import StoriesTable

        stories = fixture_prd["userStories"]
        table = StoriesTable(stories)
        assert table.stories == stories
        assert table.selected_index == 0
        assert len(table.stories) == 2

    def test_stories_table_population_from_fixture(self, fixture_prd):
        """Test StoriesTable is properly populated from fixture prd.json."""
        from spiral_dashboard import StoriesTable

        stories = fixture_prd["userStories"]
        table = StoriesTable(stories)
        # Verify stories are loaded
        assert table.stories[0]["id"] == "US-271"
        assert table.stories[0]["title"] == "Add Textual-based interactive TUI mode"
        assert table.stories[1]["id"] == "US-272"
        # Verify rendering produces output
        rendered = table.render()
        assert "US-271" in rendered
        assert "US-272" in rendered

    def test_stories_table_navigation(self, fixture_prd):
        """Test StoriesTable arrow key navigation."""
        from spiral_dashboard import StoriesTable

        stories = fixture_prd["userStories"]
        table = StoriesTable(stories)
        assert table.selected_index == 0
        # Move down
        table.action_next_story()
        assert table.selected_index == 1
        # Move back up
        table.action_prev_story()
        assert table.selected_index == 0
        # Boundary check: can't go below 0
        table.action_prev_story()
        assert table.selected_index == 0

    def test_stories_table_get_selected_story(self, fixture_prd):
        """Test getting the currently selected story."""
        from spiral_dashboard import StoriesTable

        stories = fixture_prd["userStories"]
        table = StoriesTable(stories)
        # First story
        selected = table.get_selected_story()
        assert selected["id"] == "US-271"
        # Move to second
        table.action_next_story()
        selected = table.get_selected_story()
        assert selected["id"] == "US-272"

    def test_log_panel_widget_creation(self):
        """Test LogPanel widget can be instantiated."""
        from spiral_dashboard import LogPanel

        panel = LogPanel("")
        assert panel.log_path == ""
        assert panel.auto_refresh is True

    def test_log_panel_with_missing_file(self):
        """Test LogPanel gracefully handles missing log files."""
        from spiral_dashboard import LogPanel

        panel = LogPanel("/nonexistent/path/to/log.txt")
        rendered = panel.render()
        assert "No log file" in rendered or "Could not read" in rendered

    def test_spiral_dashboard_app_creation(self, fixture_prd):
        """Test SpiralDashboardApp can be instantiated."""
        from spiral_dashboard import SpiralDashboardApp

        app = SpiralDashboardApp(fixture_prd, ".spiral")
        assert app.prd == fixture_prd
        assert app.scratch_dir == ".spiral"
        assert len(app.stories) == 2

    def test_spiral_dashboard_app_with_empty_prd(self):
        """Test SpiralDashboardApp handles empty PRD gracefully."""
        from spiral_dashboard import SpiralDashboardApp

        empty_prd = {"userStories": []}
        app = SpiralDashboardApp(empty_prd)
        assert app.stories == []

    def test_load_prd_missing_file(self, tmp_path):
        """Test load_prd returns empty structure for missing file."""
        result = load_prd(str(tmp_path / "nonexistent.json"))
        assert result == {"userStories": []}

    def test_load_prd_from_file(self, temp_prd_file, fixture_prd):
        """Test load_prd successfully loads a real prd.json file."""
        result = load_prd(temp_prd_file)
        assert len(result["userStories"]) == 2
        assert result["userStories"][0]["id"] == "US-271"


@pytest.mark.skipif(HAS_TEXTUAL, reason="Test TTY degradation without Textual")
class TestTUIGracefulDegradation:
    """Tests for non-TTY degradation path."""

    def test_tui_imports_optional(self):
        """Verify TUI imports are optional."""
        # HAS_TEXTUAL should be False in this test group
        from spiral_dashboard import HAS_TEXTUAL as textual_available

        assert textual_available is False
