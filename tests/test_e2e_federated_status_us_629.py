"""E2E test for federated-status feature (US-629).

Tests the full user flow for aggregating story status across federated sub-projects:
- Reads .spiral/prd.json federated structure
- Iterates sub_project_path entries
- Aggregates story counts and tokens from sub-project results.tsv files
- Outputs unified health dashboard in JSON or table format

Test discovery: uv run pytest tests/ -k us_629 -v
"""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from lib.federated_status import (
    aggregate_federated_status,
    aggregate_federated_stories,
    calculate_project_metrics,
    format_json_output,
    format_table_output,
)

pytestmark = pytest.mark.us_629


class TestAggregateProjectMetrics:
    """AC1: Calculate per-project metrics from result rows."""

    def test_single_passing_story(self) -> None:
        """Single passing story yields passed=1, failed=0, pending=0."""
        results: list[dict[str, Any]] = [
            {
                "status": "pass",
                "cache_read_tokens": "1000",
                "cache_creation_tokens": "500",
                "model": "haiku",
                "duration_sec": "10.5",
            }
        ]
        metrics = calculate_project_metrics("project-a", results)
        assert metrics["passed"] == 1
        assert metrics["failed"] == 0
        assert metrics["pending"] == 0
        assert metrics["total_stories"] == 1
        assert metrics["tokens_used"] == 1500

    def test_mixed_status_stories(self) -> None:
        """Multiple stories with different statuses are counted correctly."""
        results: list[dict[str, Any]] = [
            {"status": "pass", "cache_read_tokens": "1000", "cache_creation_tokens": "500", "model": "sonnet"},
            {"status": "pass", "cache_read_tokens": "2000", "cache_creation_tokens": "1000", "model": "sonnet"},
            {"status": "reject", "cache_read_tokens": "500", "cache_creation_tokens": "200", "model": "haiku"},
            {"status": "pending", "cache_read_tokens": "0", "cache_creation_tokens": "0", "model": "haiku"},
        ]
        metrics = calculate_project_metrics("project-b", results)
        assert metrics["passed"] == 2
        assert metrics["failed"] == 1
        assert metrics["pending"] == 1
        assert metrics["total_stories"] == 4
        assert metrics["tokens_used"] == 5200  # 1500 + 3000 + 700 + 0

    def test_missing_token_fields_defaults_to_zero(self) -> None:
        """Missing or empty token fields are treated as 0."""
        results: list[dict[str, Any]] = [
            {"status": "pass", "cache_read_tokens": None, "cache_creation_tokens": None, "model": "sonnet"},
            {"status": "pass", "model": "sonnet"},
        ]
        metrics = calculate_project_metrics("project-c", results)
        assert metrics["tokens_used"] == 0

    def test_cost_calculation_by_model(self) -> None:
        """Cost is calculated correctly for different models."""
        # 1M tokens: haiku costs (0.80+4.00)/2 = 2.40
        results_haiku = [
            {"status": "pass", "cache_read_tokens": "500000", "cache_creation_tokens": "500000", "model": "haiku"}
        ]
        metrics_haiku = calculate_project_metrics("proj-h", results_haiku)
        expected_haiku = 2.40
        assert abs(metrics_haiku["cost_usd"] - expected_haiku) < 0.01

        # 1M tokens: sonnet costs (3.00+15.00)/2 = 9.00
        results_sonnet = [
            {"status": "pass", "cache_read_tokens": "500000", "cache_creation_tokens": "500000", "model": "sonnet"}
        ]
        metrics_sonnet = calculate_project_metrics("proj-s", results_sonnet)
        expected_sonnet = 9.00
        assert abs(metrics_sonnet["cost_usd"] - expected_sonnet) < 0.01

    def test_average_duration_calculation(self) -> None:
        """Average duration is calculated from valid duration_sec values."""
        results = [
            {"status": "pass", "cache_read_tokens": "0", "cache_creation_tokens": "0", "model": "sonnet", "duration_sec": "10.0"},
            {"status": "pass", "cache_read_tokens": "0", "cache_creation_tokens": "0", "model": "sonnet", "duration_sec": "20.0"},
            {"status": "pass", "cache_read_tokens": "0", "cache_creation_tokens": "0", "model": "sonnet", "duration_sec": "30.0"},
        ]
        metrics = calculate_project_metrics("proj-d", results)
        assert metrics["avg_duration_s"] == 20.0


class TestAggregateFederatedStories:
    """AC2: Aggregate story status across federated sub-projects."""

    def test_empty_prd_returns_empty_summary(self) -> None:
        """Non-existent PRD file returns empty projects and zero summary."""
        result = aggregate_federated_stories(Path("/nonexistent/prd.json"))
        assert result["projects"] == []
        assert result["summary"]["total_projects"] == 0
        assert result["summary"]["total_stories"] == 0

    def test_prd_with_no_stories(self) -> None:
        """PRD with empty userStories returns empty projects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prd_file = Path(tmpdir) / "prd.json"
            prd_file.write_text(json.dumps({"userStories": []}), encoding="utf-8")

            result = aggregate_federated_stories(prd_file)
            assert result["projects"] == []
            assert result["summary"]["total_stories"] == 0

    def test_single_sub_project_with_stories(self) -> None:
        """Single sub-project with multiple stories is aggregated correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            prd_file = tmpdir_path / "prd.json"

            # Create PRD with stories in 'project-a'
            prd_data = {
                "userStories": [
                    {"id": "US-001", "sub_project": "project-a", "title": "Story 1"},
                    {"id": "US-002", "sub_project": "project-a", "title": "Story 2"},
                ]
            }
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

            # Create results.tsv
            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["story_id", "status", "cache_read_tokens", "cache_creation_tokens", "model", "duration_sec"], delimiter="\t")
                writer.writeheader()
                writer.writerow({"story_id": "US-001", "status": "pass", "cache_read_tokens": "1000", "cache_creation_tokens": "500", "model": "sonnet", "duration_sec": "10"})
                writer.writerow({"story_id": "US-002", "status": "pass", "cache_read_tokens": "2000", "cache_creation_tokens": "1000", "model": "sonnet", "duration_sec": "20"})

            result = aggregate_federated_stories(prd_file, results_globs=["results.tsv"])
            assert len(result["projects"]) == 1
            assert result["projects"][0]["project"] == "project-a"
            assert result["projects"][0]["total_stories"] == 2
            assert result["projects"][0]["passed"] == 2

    def test_multiple_sub_projects(self) -> None:
        """Multiple sub-projects are aggregated separately."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            prd_file = tmpdir_path / "prd.json"

            prd_data = {
                "userStories": [
                    {"id": "US-001", "sub_project": "project-a"},
                    {"id": "US-002", "sub_project": "project-a"},
                    {"id": "US-003", "sub_project": "project-b"},
                    {"id": "US-004", "sub_project": "project-b"},
                ]
            }
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["story_id", "status", "cache_read_tokens", "cache_creation_tokens", "model", "duration_sec"], delimiter="\t")
                writer.writeheader()
                writer.writerow({"story_id": "US-001", "status": "pass", "cache_read_tokens": "1000", "cache_creation_tokens": "500", "model": "sonnet", "duration_sec": "10"})
                writer.writerow({"story_id": "US-002", "status": "pass", "cache_read_tokens": "1000", "cache_creation_tokens": "500", "model": "sonnet", "duration_sec": "10"})
                writer.writerow({"story_id": "US-003", "status": "reject", "cache_read_tokens": "500", "cache_creation_tokens": "250", "model": "haiku", "duration_sec": "5"})

            result = aggregate_federated_stories(prd_file, results_globs=["results.tsv"])
            assert len(result["projects"]) == 2

            proj_a = next(p for p in result["projects"] if p["project"] == "project-a")
            assert proj_a["total_stories"] == 2
            assert proj_a["passed"] == 2

            proj_b = next(p for p in result["projects"] if p["project"] == "project-b")
            assert proj_b["total_stories"] == 2
            assert proj_b["failed"] == 1
            assert proj_b["pending"] == 1  # US-004 has no results

    def test_stories_without_results(self) -> None:
        """Stories with no corresponding results.tsv entries are marked as pending."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            prd_file = tmpdir_path / "prd.json"

            prd_data = {
                "userStories": [
                    {"id": "US-001", "sub_project": "project-a"},
                    {"id": "US-002", "sub_project": "project-a"},
                ]
            }
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["story_id", "status"], delimiter="\t")
                writer.writeheader()
                writer.writerow({"story_id": "US-001", "status": "pass"})

            result = aggregate_federated_stories(prd_file, results_globs=["results.tsv"])
            assert result["projects"][0]["total_stories"] == 2
            assert result["projects"][0]["passed"] == 1
            assert result["projects"][0]["pending"] == 1

    def test_summary_aggregation_across_projects(self) -> None:
        """Summary correctly totals across all projects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            prd_file = tmpdir_path / "prd.json"

            prd_data = {
                "userStories": [
                    {"id": "US-001", "sub_project": "proj-a"},
                    {"id": "US-002", "sub_project": "proj-a"},
                    {"id": "US-003", "sub_project": "proj-b"},
                ]
            }
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["story_id", "status", "cache_read_tokens", "cache_creation_tokens", "model"], delimiter="\t")
                writer.writeheader()
                writer.writerow({"story_id": "US-001", "status": "pass", "cache_read_tokens": "1000", "cache_creation_tokens": "500", "model": "sonnet"})
                writer.writerow({"story_id": "US-002", "status": "reject", "cache_read_tokens": "500", "cache_creation_tokens": "250", "model": "haiku"})
                writer.writerow({"story_id": "US-003", "status": "pass", "cache_read_tokens": "2000", "cache_creation_tokens": "1000", "model": "sonnet"})

            result = aggregate_federated_stories(prd_file, results_globs=["results.tsv"])
            summary = result["summary"]
            assert summary["total_projects"] == 2
            assert summary["total_stories"] == 3
            assert summary["passed"] == 2
            assert summary["failed"] == 1
            assert summary["pending"] == 0
            assert summary["tokens_used"] == 5250


class TestAggregateFederatedStatus:
    """AC3: Backward compatibility wrapper for aggregate_federated_status."""

    def test_backward_compat_status_key(self) -> None:
        """Output has 'status' key (backward compat) instead of 'projects'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            prd_file = tmpdir_path / "prd.json"

            prd_data = {
                "userStories": [
                    {"id": "US-001", "sub_project": "project-a"},
                ]
            }
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["story_id", "status"], delimiter="\t")
                writer.writeheader()
                writer.writerow({"story_id": "US-001", "status": "pass"})

            result = aggregate_federated_status(prd_file, results_globs=["results.tsv"])
            assert "status" in result  # Backward compat key
            assert "summary" in result
            assert isinstance(result["status"], list)

    def test_backward_compat_summary_keys(self) -> None:
        """Summary keys match backward compat names (total_passed, etc)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            prd_file = tmpdir_path / "prd.json"

            prd_data = {"userStories": [{"id": "US-001", "sub_project": "proj-a"}]}
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["story_id", "status"], delimiter="\t")
                writer.writeheader()
                writer.writerow({"story_id": "US-001", "status": "pass"})

            result = aggregate_federated_status(prd_file, results_globs=["results.tsv"])
            summary = result["summary"]
            assert "total_projects" in summary
            assert "total_stories" in summary
            assert "total_passed" in summary
            assert "total_failed" in summary
            assert "total_pending" in summary


class TestFormatOutputs:
    """AC4: Format output as JSON and human-readable table."""

    def test_format_json_output(self) -> None:
        """JSON output is valid and matches input structure."""
        data = {
            "projects": [
                {
                    "project": "proj-a",
                    "total_stories": 2,
                    "passed": 2,
                    "failed": 0,
                    "pending": 0,
                    "tokens_used": 3000,
                    "cost_usd": 9.0,
                    "avg_duration_s": 15.0,
                }
            ],
            "summary": {"total_projects": 1, "total_stories": 2, "passed": 2, "failed": 0, "pending": 0, "tokens_used": 3000, "cost_usd": 9.0},
        }

        json_str = format_json_output(data)
        parsed = json.loads(json_str)
        assert parsed == data

    def test_format_table_output_has_headers(self) -> None:
        """Table output includes column headers and separator."""
        data = {
            "projects": [
                {
                    "project": "proj-a",
                    "total_stories": 1,
                    "passed": 1,
                    "failed": 0,
                    "pending": 0,
                    "tokens_used": 1000,
                    "cost_usd": 3.0,
                    "avg_duration_s": 10.0,
                }
            ]
        }

        table_str = format_table_output(data)
        assert "Sub-Project" in table_str
        assert "Total Stories" in table_str
        assert "proj-a" in table_str

    def test_format_table_output_includes_totals(self) -> None:
        """Table output includes TOTAL row."""
        data = {
            "projects": [
                {
                    "project": "proj-a",
                    "total_stories": 1,
                    "passed": 1,
                    "failed": 0,
                    "pending": 0,
                    "tokens_used": 1000,
                    "cost_usd": 3.0,
                    "avg_duration_s": 10.0,
                }
            ]
        }

        table_str = format_table_output(data)
        assert "TOTAL" in table_str

    def test_format_table_output_multiple_projects(self) -> None:
        """Table output correctly formats multiple projects."""
        data = {
            "projects": [
                {
                    "project": "proj-a",
                    "total_stories": 2,
                    "passed": 2,
                    "failed": 0,
                    "pending": 0,
                    "tokens_used": 2000,
                    "cost_usd": 6.0,
                    "avg_duration_s": 10.0,
                },
                {
                    "project": "proj-b",
                    "total_stories": 1,
                    "passed": 0,
                    "failed": 1,
                    "pending": 0,
                    "tokens_used": 500,
                    "cost_usd": 1.2,
                    "avg_duration_s": 5.0,
                },
            ]
        }

        table_str = format_table_output(data)
        assert "proj-a" in table_str
        assert "proj-b" in table_str
        assert "2" in table_str
        assert "1" in table_str


class TestEdgeCases:
    """AC5: Edge cases and error handling."""

    def test_stories_with_no_sub_project_default_to_default(self) -> None:
        """Stories without sub_project field default to 'default' project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            prd_file = tmpdir_path / "prd.json"

            prd_data = {"userStories": [{"id": "US-001"}]}  # No sub_project field
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["story_id", "status"], delimiter="\t")
                writer.writeheader()
                writer.writerow({"story_id": "US-001", "status": "pass"})

            result = aggregate_federated_stories(prd_file, results_globs=["results.tsv"])
            assert result["projects"][0]["project"] == "default"

    def test_multiple_results_files_merged(self) -> None:
        """Multiple results.tsv files are merged correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            prd_file = tmpdir_path / "prd.json"

            prd_data = {
                "userStories": [
                    {"id": "US-001", "sub_project": "proj-a"},
                    {"id": "US-002", "sub_project": "proj-a"},
                ]
            }
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

            # Create worker-1 results.tsv
            worker1_dir = tmpdir_path / ".spiral-workers" / "worker-1"
            worker1_dir.mkdir(parents=True)
            results_file1 = worker1_dir / "results.tsv"
            with open(results_file1, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["story_id", "status"], delimiter="\t")
                writer.writeheader()
                writer.writerow({"story_id": "US-001", "status": "pass"})

            # Create worker-2 results.tsv
            worker2_dir = tmpdir_path / ".spiral-workers" / "worker-2"
            worker2_dir.mkdir(parents=True)
            results_file2 = worker2_dir / "results.tsv"
            with open(results_file2, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["story_id", "status"], delimiter="\t")
                writer.writeheader()
                writer.writerow({"story_id": "US-002", "status": "pass"})

            result = aggregate_federated_stories(
                prd_file,
                results_globs=[".spiral-workers/worker-*/results.tsv"],
            )
            assert result["projects"][0]["passed"] == 2

    def test_duplicate_story_ids_uses_first_result(self) -> None:
        """If same story_id appears in multiple results files, first one wins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            prd_file = tmpdir_path / "prd.json"

            prd_data = {"userStories": [{"id": "US-001", "sub_project": "proj"}]}
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["story_id", "status"], delimiter="\t")
                writer.writeheader()
                writer.writerow({"story_id": "US-001", "status": "pass"})
                writer.writerow({"story_id": "US-001", "status": "reject"})  # Duplicate, should be ignored

            result = aggregate_federated_stories(prd_file, results_globs=["results.tsv"])
            assert result["projects"][0]["passed"] == 1
            assert result["projects"][0]["failed"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
