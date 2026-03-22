"""Tests for dead weight detection and auto-archival (US-779)."""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


def _make_valid_prd(stories: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Create a valid prd.json structure with required fields."""
    return {
        "productName": "Test",
        "branchName": "main",
        "schemaVersion": 1,
        "userStories": stories or [],
    }


class TestDeadWeightIteration:
    """Test _pending_iterations counter increment."""

    def test_new_story_initialized_with_zero_iterations(self) -> None:
        """New stories added via merge_stories should have _pending_iterations=0."""
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create a valid prd.json
            prd = _make_valid_prd()
            prd_file = tmp_path / "prd.json"
            with open(prd_file, "w", encoding="utf-8") as f:
                json.dump(prd, f)

            # Create research output with one story
            research = {
                "stories": [
                    {
                        "title": "Test Story",
                        "description": "A test story",
                        "priority": "medium",
                        "acceptanceCriteria": ["AC1"],
                        "technicalNotes": [],
                        "filesTouch": [],
                        "dependencies": [],
                        "estimatedComplexity": "small",
                        "_source": "research",
                    }
                ]
            }
            research_file = tmp_path / "research.json"
            with open(research_file, "w", encoding="utf-8") as f:
                json.dump(research, f)

            test_stories_file = tmp_path / "test_stories.json"
            with open(test_stories_file, "w", encoding="utf-8") as f:
                json.dump({"stories": []}, f)

            # Run merge_stories
            cmd = [
                sys.executable,
                "-m",
                "lib.prd.merge_stories",
                "--prd",
                str(prd_file),
                "--research",
                str(research_file),
                "--test-stories",
                str(test_stories_file),
            ]
            result = subprocess.run(
                cmd,
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert result.returncode == 0, f"merge_stories failed: {result.stderr}"

            # Check that new story has _pending_iterations=0
            with open(prd_file, encoding="utf-8") as f:
                updated_prd = json.load(f)

            assert len(updated_prd["userStories"]) == 1
            story = updated_prd["userStories"][0]
            assert story["_pending_iterations"] == 0

    def test_pending_story_increments_iterations_each_merge(self) -> None:
        """Existing non-passed story should increment _pending_iterations on each merge."""
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create prd.json with one pending story (no _pending_iterations yet)
            prd = _make_valid_prd(
                [
                    {
                        "id": "US-001",
                        "title": "Pending Story",
                        "description": "A story",
                        "priority": "high",
                        "acceptanceCriteria": ["AC1"],
                        "technicalNotes": [],
                        "filesTouch": [],
                        "dependencies": [],
                        "estimatedComplexity": "small",
                        "passes": False,
                    }
                ]
            )
            prd_file = tmp_path / "prd.json"
            with open(prd_file, "w", encoding="utf-8") as f:
                json.dump(prd, f)

            # Create empty research and test outputs
            research_file = tmp_path / "research.json"
            with open(research_file, "w", encoding="utf-8") as f:
                json.dump({"stories": []}, f)

            test_stories_file = tmp_path / "test_stories.json"
            with open(test_stories_file, "w", encoding="utf-8") as f:
                json.dump({"stories": []}, f)

            # First merge: should increment from 0 to 1
            cmd = [
                sys.executable,
                "-m",
                "lib.prd.merge_stories",
                "--prd",
                str(prd_file),
                "--research",
                str(research_file),
                "--test-stories",
                str(test_stories_file),
            ]
            subprocess.run(
                cmd,
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

            with open(prd_file, encoding="utf-8") as f:
                prd = json.load(f)

            story = prd["userStories"][0]
            assert story["_pending_iterations"] == 1

            # Second merge: should increment to 2
            subprocess.run(
                cmd,
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

            with open(prd_file, encoding="utf-8") as f:
                prd = json.load(f)

            story = prd["userStories"][0]
            assert story["_pending_iterations"] == 2


class TestDeadWeightArchival:
    """Test auto-archival at threshold."""

    def test_story_archived_at_threshold(self) -> None:
        """Story reaching 5+ iterations without passing should be archived."""
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create prd.json with a story at iteration 5
            prd = _make_valid_prd(
                [
                    {
                        "id": "US-001",
                        "title": "Stuck Story",
                        "description": "A story",
                        "priority": "high",
                        "acceptanceCriteria": ["AC1"],
                        "technicalNotes": [],
                        "filesTouch": [],
                        "dependencies": [],
                        "estimatedComplexity": "small",
                        "passes": False,
                        "_pending_iterations": 4,  # Will become 5 on this merge
                    }
                ]
            )
            prd_file = tmp_path / "prd.json"
            with open(prd_file, "w", encoding="utf-8") as f:
                json.dump(prd, f)

            research_file = tmp_path / "research.json"
            with open(research_file, "w", encoding="utf-8") as f:
                json.dump({"stories": []}, f)

            test_stories_file = tmp_path / "test_stories.json"
            with open(test_stories_file, "w", encoding="utf-8") as f:
                json.dump({"stories": []}, f)

            # Run merge with default threshold (5)
            cmd = [
                sys.executable,
                "-m",
                "lib.prd.merge_stories",
                "--prd",
                str(prd_file),
                "--research",
                str(research_file),
                "--test-stories",
                str(test_stories_file),
            ]
            subprocess.run(
                cmd,
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

            with open(prd_file, encoding="utf-8") as f:
                prd = json.load(f)

            story = prd["userStories"][0]
            assert story["_pending_iterations"] == 5
            assert story.get("_archived") is True
            assert "_archiveReason" in story

    def test_passed_story_not_archived(self) -> None:
        """Passed stories should not be incremented or archived."""
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            prd = _make_valid_prd(
                [
                    {
                        "id": "US-001",
                        "title": "Passed Story",
                        "description": "A story",
                        "priority": "high",
                        "acceptanceCriteria": ["AC1"],
                        "technicalNotes": [],
                        "filesTouch": [],
                        "dependencies": [],
                        "estimatedComplexity": "small",
                        "passes": True,
                        "_pending_iterations": 10,  # Should not change
                    }
                ]
            )
            prd_file = tmp_path / "prd.json"
            with open(prd_file, "w", encoding="utf-8") as f:
                json.dump(prd, f)

            research_file = tmp_path / "research.json"
            with open(research_file, "w", encoding="utf-8") as f:
                json.dump({"stories": []}, f)

            test_stories_file = tmp_path / "test_stories.json"
            with open(test_stories_file, "w", encoding="utf-8") as f:
                json.dump({"stories": []}, f)

            cmd = [
                sys.executable,
                "-m",
                "lib.prd.merge_stories",
                "--prd",
                str(prd_file),
                "--research",
                str(research_file),
                "--test-stories",
                str(test_stories_file),
            ]
            subprocess.run(
                cmd,
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

            with open(prd_file, encoding="utf-8") as f:
                prd = json.load(f)

            story = prd["userStories"][0]
            assert story["_pending_iterations"] == 10  # Unchanged
            assert story.get("_archived") is not True


class TestShowArchivedCLI:
    """Test the spiral show-archived CLI command."""

    def test_show_archived_lists_archived_stories(self) -> None:
        """CLI should list all archived stories with their metadata."""
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            prd = _make_valid_prd(
                [
                    {
                        "id": "US-001",
                        "title": "Archived Story 1",
                        "description": "First archived",
                        "priority": "high",
                        "acceptanceCriteria": ["AC1"],
                        "technicalNotes": [],
                        "filesTouch": [],
                        "dependencies": [],
                        "estimatedComplexity": "small",
                        "passes": False,
                        "_archived": True,
                        "_pending_iterations": 5,
                        "_archiveReason": "Stuck 5 iterations (threshold: 5)",
                    },
                    {
                        "id": "US-002",
                        "title": "Still Pending",
                        "description": "Not archived yet",
                        "priority": "medium",
                        "acceptanceCriteria": ["AC1"],
                        "technicalNotes": [],
                        "filesTouch": [],
                        "dependencies": [],
                        "estimatedComplexity": "small",
                        "passes": False,
                        "_pending_iterations": 2,
                    },
                ]
            )
            prd_file = tmp_path / "prd.json"
            with open(prd_file, "w", encoding="utf-8") as f:
                json.dump(prd, f)

            # Run spiral show-archived directly via main.py script
            main_py = Path(__file__).parent.parent / "main.py"
            cmd = [
                sys.executable,
                str(main_py),
                "show-archived",
                "--prd",
                str(prd_file),
            ]
            result = subprocess.run(
                cmd,
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert result.returncode == 0, f"CLI failed: {result.stderr}"
            output = result.stdout

            # Should show the archived story
            assert "US-001" in output
            assert "Archived Story 1" in output
            assert "5" in output  # iterations count
            assert "Total archived: 1" in output

            # Should NOT show the pending story
            assert "US-002" not in output

    def test_show_archived_no_archived_stories(self) -> None:
        """CLI should handle case with no archived stories."""
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            prd = _make_valid_prd(
                [
                    {
                        "id": "US-001",
                        "title": "Pending Story",
                        "description": "No archives yet",
                        "priority": "medium",
                        "acceptanceCriteria": ["AC1"],
                        "technicalNotes": [],
                        "filesTouch": [],
                        "dependencies": [],
                        "estimatedComplexity": "small",
                        "passes": False,
                    }
                ]
            )
            prd_file = tmp_path / "prd.json"
            with open(prd_file, "w", encoding="utf-8") as f:
                json.dump(prd, f)

            main_py = Path(__file__).parent.parent / "main.py"
            cmd = [
                sys.executable,
                str(main_py),
                "show-archived",
                "--prd",
                str(prd_file),
            ]
            result = subprocess.run(
                cmd,
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert result.returncode == 0, f"CLI failed: {result.stderr}"
            assert "No archived stories found" in result.stdout


class TestExcludedFromPending:
    """Test that archived stories are excluded from pending count."""

    def test_archived_stories_excluded_from_pending_count(self) -> None:
        """Pending count should not include archived stories."""
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            prd = _make_valid_prd(
                [
                    {
                        "id": "US-001",
                        "title": "Archived",
                        "description": "Old",
                        "priority": "high",
                        "acceptanceCriteria": ["AC1"],
                        "technicalNotes": [],
                        "filesTouch": [],
                        "dependencies": [],
                        "estimatedComplexity": "small",
                        "passes": False,
                        "_archived": True,
                        "_pending_iterations": 5,
                    },
                    {
                        "id": "US-002",
                        "title": "Pending",
                        "description": "Active",
                        "priority": "high",
                        "acceptanceCriteria": ["AC1"],
                        "technicalNotes": [],
                        "filesTouch": [],
                        "dependencies": [],
                        "estimatedComplexity": "small",
                        "passes": False,
                        "_pending_iterations": 1,
                    },
                ]
            )
            prd_file = tmp_path / "prd.json"
            with open(prd_file, "w", encoding="utf-8") as f:
                json.dump(prd, f)

            research_file = tmp_path / "research.json"
            with open(research_file, "w", encoding="utf-8") as f:
                json.dump({"stories": []}, f)

            test_stories_file = tmp_path / "test_stories.json"
            with open(test_stories_file, "w", encoding="utf-8") as f:
                json.dump({"stories": []}, f)

            cmd = [
                sys.executable,
                "-m",
                "lib.prd.merge_stories",
                "--prd",
                str(prd_file),
                "--research",
                str(research_file),
                "--test-stories",
                str(test_stories_file),
            ]
            result = subprocess.run(
                cmd,
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert result.returncode == 0, f"merge_stories failed: {result.stderr}"
            # Check output mentions 1 pending (not 2)
            assert "1 pending" in result.stdout
            assert "1 archived" in result.stdout
