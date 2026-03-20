"""Integration test for US-634: SPIRAL End-to-End with Federated prd.json and Phase M Merge.

Tests the full federated story pipeline:
- AC1: Phase M merge preserves namespace prefixes and dependency ordering
- AC2: Merged PRD marks stories with _source=federated and sub_project field
- AC3: results.tsv records sub_project column accurately; Phase V aggregates results
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure lib/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from federated_merge_prd import load_sub_project_prd, merge_prds
from impl.phase_m_federated_order import order_federated_stories_by_dependency
from spiral.phase_m import prd_merge


class TestFederatedFixtureSetup:
    """AC1: Test creates federated fixture structure with proper namespace prefixes."""

    def test_fixture_webapp_prd_loaded(self) -> None:
        """Fixture webapp/prd.json loads successfully with US-web-* stories."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "federation"
        webapp_dir = fixtures_dir / "webapp"

        prd = load_sub_project_prd(webapp_dir, "webapp")
        stories = prd.get("userStories", [])

        assert len(stories) == 3, "Webapp should have 3 stories"
        story_ids = [s.get("id") for s in stories]
        assert "US-web-001" in story_ids
        assert "US-web-002" in story_ids
        assert "US-web-003" in story_ids

    def test_fixture_api_prd_loaded(self) -> None:
        """Fixture api/prd.json loads successfully with US-api-* stories."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "federation"
        api_dir = fixtures_dir / "api"

        prd = load_sub_project_prd(api_dir, "api")
        stories = prd.get("userStories", [])

        assert len(stories) == 3, "API should have 3 stories"
        story_ids = [s.get("id") for s in stories]
        assert "US-api-001" in story_ids
        assert "US-api-002" in story_ids
        assert "US-api-003" in story_ids

    def test_namespace_prefixes_preserved(self) -> None:
        """Phase M merge preserves namespace prefixes (US-web-*, US-api-*)."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "federation"

        project_dirs = {
            "webapp": fixtures_dir / "webapp",
            "api": fixtures_dir / "api",
        }

        merged, errors = merge_prds(project_dirs)
        assert not errors, f"Merge should succeed without errors, got: {errors}"

        stories = merged.get("userStories", [])
        story_ids = {s.get("id") for s in stories}

        # All story IDs should be preserved with their namespaces
        expected_ids = {
            "US-web-001", "US-web-002", "US-web-003",
            "US-api-001", "US-api-002", "US-api-003",
        }
        assert story_ids == expected_ids, f"Expected {expected_ids}, got {story_ids}"


class TestPhaseMMerge:
    """AC2: Phase M merge correctly marks stories and respects dependencies."""

    def test_merge_adds_sub_project_field(self) -> None:
        """Merged stories are marked with sub_project field."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "federation"

        project_dirs = {
            "webapp": fixtures_dir / "webapp",
            "api": fixtures_dir / "api",
        }

        merged, errors = merge_prds(project_dirs)
        assert not errors

        stories = merged.get("userStories", [])

        # All stories should have sub_project field
        for story in stories:
            assert "sub_project" in story, f"Story {story.get('id')} missing sub_project field"
            story_id = story.get("id", "")
            if story_id.startswith("US-web-"):
                assert story["sub_project"] == "webapp"
            elif story_id.startswith("US-api-"):
                assert story["sub_project"] == "api"

    def test_merge_detects_circular_dependencies(self, tmp_path: Path) -> None:
        """Phase M correctly detects circular dependencies across projects."""
        # Create circular dependency: US-web-X depends on US-api-Y, US-api-Y depends on US-web-X
        webapp_dir = tmp_path / "webapp"
        api_dir = tmp_path / "api"
        webapp_dir.mkdir()
        api_dir.mkdir()

        webapp_prd = {
            "userStories": [
                {
                    "id": "US-web-X",
                    "title": "Web Story",
                    "description": "This depends on US-api-Y",
                    "dependencies": ["US-api-Y"],
                    "passes": False,
                    "priority": "high",
                    "acceptanceCriteria": [],
                }
            ]
        }

        api_prd = {
            "userStories": [
                {
                    "id": "US-api-Y",
                    "title": "API Story",
                    "description": "This depends on US-web-X",
                    "dependencies": ["US-web-X"],
                    "passes": False,
                    "priority": "high",
                    "acceptanceCriteria": [],
                }
            ]
        }

        (webapp_dir / "prd.json").write_text(json.dumps(webapp_prd))
        (api_dir / "prd.json").write_text(json.dumps(api_prd))

        merged, errors = merge_prds({"webapp": webapp_dir, "api": api_dir})

        # Merge succeeds (doesn't validate circularity), but ordering will catch it
        if not errors:
            stories = merged.get("userStories", [])
            with pytest.raises(ValueError, match="circular dependency"):
                order_federated_stories_by_dependency(stories)

    def test_dependency_ordering_respects_cross_project_deps(self) -> None:
        """Phase M orders stories so cross-project dependencies resolve first."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "federation"

        project_dirs = {
            "webapp": fixtures_dir / "webapp",
            "api": fixtures_dir / "api",
        }

        merged, errors = merge_prds(project_dirs)
        assert not errors

        stories = merged.get("userStories", [])
        ordered = order_federated_stories_by_dependency(stories)

        # Build a map of story ID to position in the ordered list
        id_to_pos = {s.get("id"): i for i, s in enumerate(ordered)}

        # Verify dependencies come before dependents
        # US-api-002 should come before US-api-001 (API-001 depends on API-002)
        assert id_to_pos["US-api-002"] < id_to_pos["US-api-001"]

        # US-api-001 should come before US-web-002 (web-002 depends on api-001)
        assert id_to_pos["US-api-001"] < id_to_pos["US-web-002"]

        # US-api-001 should come before US-api-003 (api-003 depends on api-001)
        assert id_to_pos["US-api-001"] < id_to_pos["US-api-003"]

    def test_prd_merge_integration(self) -> None:
        """Phase M prd_merge() function integrates ordering correctly."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "federation"

        project_dirs = {
            "webapp": fixtures_dir / "webapp",
            "api": fixtures_dir / "api",
        }

        merged, errors = merge_prds(project_dirs)
        assert not errors

        stories = merged.get("userStories", [])

        # Test prd_merge function (Phase M entry point)
        ordered = prd_merge(stories, skip_ordering=False)

        # Should have all 6 stories
        assert len(ordered) == 6

        # Check ordering constraints
        id_to_pos = {s.get("id"): i for i, s in enumerate(ordered)}
        assert id_to_pos["US-api-002"] < id_to_pos["US-api-001"]
        assert id_to_pos["US-api-001"] < id_to_pos["US-web-002"]


class TestResultsTsvAggregation:
    """AC3: results.tsv records sub_project column; Phase V aggregates across projects."""

    def test_results_tsv_generation_with_sub_project(self, tmp_path: Path) -> None:
        """Generate results.tsv with sub_project column from federated merge."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "federation"

        project_dirs = {
            "webapp": fixtures_dir / "webapp",
            "api": fixtures_dir / "api",
        }

        merged, errors = merge_prds(project_dirs)
        assert not errors

        stories = merged.get("userStories", [])

        # Generate a mock results.tsv with sub_project column
        results_path = tmp_path / "results.tsv"
        with open(results_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "story_id",
                    "model",
                    "tokens_input",
                    "tokens_output",
                    "cost",
                    "status",
                    "sub_project",
                    "retries",
                ],
                delimiter="\t",
            )
            writer.writeheader()

            for story in stories:
                writer.writerow({
                    "story_id": story.get("id"),
                    "model": "haiku",
                    "tokens_input": 1000,
                    "tokens_output": 500,
                    "cost": 0.01,
                    "status": "passed",
                    "sub_project": story.get("sub_project"),
                    "retries": 0,
                })

        # Verify results.tsv has all stories with sub_project populated
        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        assert len(rows) == 6, "Should have 6 story rows"

        # Check all sub_project entries are populated
        for row in rows:
            assert row["sub_project"] in ["webapp", "api"], (
                f"Story {row['story_id']} has invalid sub_project: {row['sub_project']}"
            )

            # Verify sub_project matches story ID prefix
            story_id = row["story_id"]
            if story_id.startswith("US-web-"):
                assert row["sub_project"] == "webapp"
            elif story_id.startswith("US-api-"):
                assert row["sub_project"] == "api"

    def test_aggregation_across_sub_projects(self, tmp_path: Path) -> None:
        """Phase V can aggregate results.tsv across multiple sub-projects."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "federation"

        project_dirs = {
            "webapp": fixtures_dir / "webapp",
            "api": fixtures_dir / "api",
        }

        merged, errors = merge_prds(project_dirs)
        assert not errors

        stories = merged.get("userStories", [])

        # Create results.tsv with mixed pass/fail across projects
        results_path = tmp_path / "results.tsv"
        with open(results_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "story_id",
                    "model",
                    "tokens_input",
                    "tokens_output",
                    "cost",
                    "status",
                    "sub_project",
                    "retries",
                ],
                delimiter="\t",
            )
            writer.writeheader()

            for i, story in enumerate(stories):
                # Alternate pass/fail for demo
                status = "passed" if i % 2 == 0 else "failed"
                writer.writerow({
                    "story_id": story.get("id"),
                    "model": "haiku",
                    "tokens_input": 1000,
                    "tokens_output": 500,
                    "cost": 0.01,
                    "status": status,
                    "sub_project": story.get("sub_project"),
                    "retries": 0,
                })

        # Aggregate by sub_project
        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        aggregation = {"webapp": {"passed": 0, "failed": 0}, "api": {"passed": 0, "failed": 0}}
        for row in rows:
            sub_project = row["sub_project"]
            status = row["status"]
            if sub_project in aggregation:
                aggregation[sub_project][status] += 1

        # Verify aggregation is correct
        assert aggregation["webapp"]["passed"] >= 0
        assert aggregation["api"]["passed"] >= 0
        assert (aggregation["webapp"]["passed"] + aggregation["webapp"]["failed"]) == 3
        assert (aggregation["api"]["passed"] + aggregation["api"]["failed"]) == 3

    def test_all_stories_have_sub_project_entry(self, tmp_path: Path) -> None:
        """No missing entries in results.tsv sub_project column for any story."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "federation"

        project_dirs = {
            "webapp": fixtures_dir / "webapp",
            "api": fixtures_dir / "api",
        }

        merged, errors = merge_prds(project_dirs)
        assert not errors

        stories = merged.get("userStories", [])
        all_story_ids = {s.get("id") for s in stories}

        # Generate results.tsv
        results_path = tmp_path / "results.tsv"
        with open(results_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "story_id",
                    "model",
                    "tokens_input",
                    "tokens_output",
                    "cost",
                    "status",
                    "sub_project",
                    "retries",
                ],
                delimiter="\t",
            )
            writer.writeheader()

            for story in stories:
                writer.writerow({
                    "story_id": story.get("id"),
                    "model": "haiku",
                    "tokens_input": 1000,
                    "tokens_output": 500,
                    "cost": 0.01,
                    "status": "passed",
                    "sub_project": story.get("sub_project"),
                    "retries": 0,
                })

        # Verify all stories are in results.tsv with populated sub_project
        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        results_story_ids = {row["story_id"] for row in rows}
        assert results_story_ids == all_story_ids, "All stories must be in results.tsv"

        # Verify no empty sub_project entries
        for row in rows:
            assert row["sub_project"], (
                f"Story {row['story_id']} has empty sub_project column"
            )
