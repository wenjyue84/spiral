"""tests/test_cli_federated_cost.py — Tests for federated cost report (US-713)."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from lib.cli.federated_cost_report import (
    _calculate_cost,
    aggregate_by_group,
    federated_cost_report,
    format_markdown_table,
    read_results_tsv,
)


class TestCalculateCost:
    """Test cost calculation from tokens and model."""

    def test_haiku_cost_calculation(self) -> None:
        """Haiku: (input 0.80 + output 4.00) / 2 = 2.40 per million tokens."""
        cost = _calculate_cost(1_000_000, "haiku")
        expected = 2.40
        assert abs(cost - expected) < 0.01

    def test_sonnet_cost_calculation(self) -> None:
        """Sonnet: (input 3.00 + output 15.00) / 2 = 9.00 per million tokens."""
        cost = _calculate_cost(1_000_000, "sonnet")
        expected = 9.00
        assert abs(cost - expected) < 0.01

    def test_opus_cost_calculation(self) -> None:
        """Opus: (input 15.00 + output 75.00) / 2 = 45.00 per million tokens."""
        cost = _calculate_cost(1_000_000, "opus")
        expected = 45.00
        assert abs(cost - expected) < 0.01

    def test_partial_tokens(self) -> None:
        """500k tokens: cost scales linearly."""
        cost = _calculate_cost(500_000, "sonnet")
        expected = 4.50
        assert abs(cost - expected) < 0.01

    def test_zero_tokens(self) -> None:
        """Zero tokens should yield zero cost."""
        cost = _calculate_cost(0, "sonnet")
        assert cost == 0.0

    def test_unknown_model_defaults_to_sonnet(self) -> None:
        """Unknown model should default to sonnet pricing."""
        cost_unknown = _calculate_cost(1_000_000, "unknown")
        cost_sonnet = _calculate_cost(1_000_000, "sonnet")
        assert cost_unknown == cost_sonnet

    def test_case_insensitive_model(self) -> None:
        """Model names should be case-insensitive."""
        cost_lower = _calculate_cost(1_000_000, "haiku")
        cost_upper = _calculate_cost(1_000_000, "HAIKU")
        assert cost_lower == cost_upper


class TestReadResultsTsv:
    """Test reading results.tsv file."""

    def test_read_empty_file(self) -> None:
        """Reading a file with only headers returns empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = Path(tmpdir) / "results.tsv"
            with open(tsv_path, "w") as f:
                f.write("story_id\tmodel\tcache_read_tokens\tcache_creation_tokens\n")

            rows = read_results_tsv(tsv_path)
            assert rows == []

    def test_read_single_row(self) -> None:
        """Reading a single row returns list with one dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = Path(tmpdir) / "results.tsv"
            with open(tsv_path, "w") as f:
                f.write("story_id\tmodel\tcache_read_tokens\tcache_creation_tokens\n")
                f.write("US-123\thaiku\t1000\t2000\n")

            rows = read_results_tsv(tsv_path)
            assert len(rows) == 1
            assert rows[0]["story_id"] == "US-123"

    def test_file_not_found(self) -> None:
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            read_results_tsv(Path("/nonexistent/results.tsv"))

    def test_unicode_handling(self) -> None:
        """File with UTF-8 content reads correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = Path(tmpdir) / "results.tsv"
            with open(tsv_path, "w", encoding="utf-8") as f:
                f.write("story_id\tmodel\tcache_read_tokens\tcache_creation_tokens\n")
                f.write("US-123\tsonnet\t1000\t2000\n")

            rows = read_results_tsv(tsv_path)
            assert len(rows) == 1


class TestAggregateByGroup:
    """Test grouping and aggregation by (sub_project, phase)."""

    def test_single_row_aggregation(self) -> None:
        """Single row groups under default sub_project and unknown phase."""
        rows = [
            {
                "sub_project": "",
                "phase": "",
                "model": "sonnet",
                "cache_read_tokens": "1000",
                "cache_creation_tokens": "2000",
            }
        ]
        groups = aggregate_by_group(rows)
        assert ("default", "unknown") in groups
        assert groups[("default", "unknown")]["tokens_used"] == 3000

    def test_missing_sub_project_defaults_to_default(self) -> None:
        """Missing sub_project becomes 'default'."""
        rows = [
            {
                "model": "sonnet",
                "cache_read_tokens": "1000",
                "cache_creation_tokens": "2000",
                "phase": "R",
            }
        ]
        groups = aggregate_by_group(rows)
        assert ("default", "R") in groups

    def test_whitespace_sub_project_treated_as_missing(self) -> None:
        """Whitespace-only sub_project becomes 'default'."""
        rows = [
            {
                "sub_project": "   ",
                "phase": "I",
                "model": "sonnet",
                "cache_read_tokens": "1000",
                "cache_creation_tokens": "2000",
            }
        ]
        groups = aggregate_by_group(rows)
        assert ("default", "I") in groups

    def test_multiple_rows_same_group(self) -> None:
        """Multiple rows in same group aggregate correctly."""
        rows = [
            {
                "sub_project": "proj1",
                "phase": "R",
                "model": "sonnet",
                "cache_read_tokens": "1000",
                "cache_creation_tokens": "2000",
            },
            {
                "sub_project": "proj1",
                "phase": "R",
                "model": "sonnet",
                "cache_read_tokens": "500",
                "cache_creation_tokens": "1500",
            },
        ]
        groups = aggregate_by_group(rows)
        assert groups[("proj1", "R")]["tokens_used"] == 5000
        assert groups[("proj1", "R")]["story_count"] == 2

    def test_multiple_groups(self) -> None:
        """Multiple groups are aggregated separately."""
        rows = [
            {
                "sub_project": "proj1",
                "phase": "R",
                "model": "sonnet",
                "cache_read_tokens": "1000",
                "cache_creation_tokens": "2000",
            },
            {
                "sub_project": "proj1",
                "phase": "I",
                "model": "sonnet",
                "cache_read_tokens": "500",
                "cache_creation_tokens": "1500",
            },
            {
                "sub_project": "proj2",
                "phase": "R",
                "model": "sonnet",
                "cache_read_tokens": "100",
                "cache_creation_tokens": "200",
            },
        ]
        groups = aggregate_by_group(rows)
        assert len(groups) == 3
        assert groups[("proj1", "R")]["tokens_used"] == 3000
        assert groups[("proj1", "I")]["tokens_used"] == 2000
        assert groups[("proj2", "R")]["tokens_used"] == 300

    def test_invalid_token_counts_treated_as_zero(self) -> None:
        """Non-numeric token counts are treated as zero."""
        rows = [
            {
                "sub_project": "proj1",
                "phase": "R",
                "model": "sonnet",
                "cache_read_tokens": "invalid",
                "cache_creation_tokens": "2000",
            }
        ]
        groups = aggregate_by_group(rows)
        # Should have used only cache_creation_tokens
        assert groups[("proj1", "R")]["tokens_used"] == 2000

    def test_cost_calculation_in_aggregation(self) -> None:
        """Cost is calculated correctly from tokens and model."""
        rows = [
            {
                "sub_project": "proj1",
                "phase": "R",
                "model": "sonnet",
                "cache_read_tokens": "500000",
                "cache_creation_tokens": "500000",
            }
        ]
        groups = aggregate_by_group(rows)
        cost = groups[("proj1", "R")]["cost_usd"]
        expected_cost = _calculate_cost(1_000_000, "sonnet")
        assert abs(cost - expected_cost) < 0.01


class TestFormatMarkdownTable:
    """Test markdown table formatting."""

    def test_empty_groups(self) -> None:
        """Empty groups return 'No data to report'."""
        output = format_markdown_table({})
        assert "No data" in output

    def test_single_group_single_phase(self) -> None:
        """Single group with one phase formats correctly."""
        groups = {
            ("proj1", "R"): {
                "tokens_used": 1_000_000,
                "cost_usd": 9.0,
                "story_count": 1,
            }
        }
        output = format_markdown_table(groups)
        assert "| proj1 |" in output
        assert "$9.0000" in output

    def test_sorting_by_total_cost_descending(self) -> None:
        """Groups are sorted by total cost in descending order."""
        groups = {
            ("proj1", "R"): {"tokens_used": 500_000, "cost_usd": 4.5, "story_count": 1},
            ("proj1", "I"): {"tokens_used": 100_000, "cost_usd": 0.9, "story_count": 1},
            ("proj2", "R"): {
                "tokens_used": 2_000_000,
                "cost_usd": 18.0,
                "story_count": 1,
            },
        }
        output = format_markdown_table(groups)
        # proj2 (total 18) should appear before proj1 (total 5.4)
        assert output.index("proj2") < output.index("proj1")

    def test_phase_r_and_i_separation(self) -> None:
        """Phase R and I costs appear in separate columns."""
        groups = {
            ("proj1", "R"): {"tokens_used": 1_000_000, "cost_usd": 9.0, "story_count": 1},
            ("proj1", "I"): {"tokens_used": 500_000, "cost_usd": 4.5, "story_count": 1},
        }
        output = format_markdown_table(groups)
        assert "| proj1 | $9.0000 | $4.5000 | $13.5000 |" in output

    def test_totals_row_included(self) -> None:
        """Totals row is included at the bottom."""
        groups = {
            ("proj1", "R"): {"tokens_used": 1_000_000, "cost_usd": 9.0, "story_count": 1},
            ("proj1", "I"): {"tokens_used": 500_000, "cost_usd": 4.5, "story_count": 1},
        }
        output = format_markdown_table(groups)
        assert "**TOTAL**" in output
        assert "$13.5000" in output

    def test_missing_phase_not_included(self) -> None:
        """Phases without data show 0.0000."""
        groups = {("proj1", "R"): {"tokens_used": 1_000_000, "cost_usd": 9.0, "story_count": 1}}
        output = format_markdown_table(groups)
        # Phase I should show $0.0000
        assert "proj1 | $9.0000 | $0.0000 | $9.0000" in output


class TestIntegration:
    """Integration tests with real file I/O."""

    def test_full_pipeline_with_real_file(self) -> None:
        """Full pipeline from file to markdown table."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = Path(tmpdir) / "results.tsv"
            with open(tsv_path, "w") as f:
                writer = csv.DictWriter(
                    f,
                    delimiter="\t",
                    fieldnames=[
                        "story_id",
                        "sub_project",
                        "phase",
                        "model",
                        "cache_read_tokens",
                        "cache_creation_tokens",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "story_id": "US-1",
                        "sub_project": "proj1",
                        "phase": "R",
                        "model": "sonnet",
                        "cache_read_tokens": "500000",
                        "cache_creation_tokens": "500000",
                    }
                )
                writer.writerow(
                    {
                        "story_id": "US-2",
                        "sub_project": "proj1",
                        "phase": "I",
                        "model": "sonnet",
                        "cache_read_tokens": "250000",
                        "cache_creation_tokens": "250000",
                    }
                )

            output = federated_cost_report(tsv_path)
            assert "| proj1 |" in output
            assert "**TOTAL**" in output

    def test_cost_sum_validation(self) -> None:
        """Cost sum across aggregated rows equals sum of individual costs."""
        rows = [
            {
                "sub_project": "proj1",
                "phase": "R",
                "model": "sonnet",
                "cache_read_tokens": "100000",
                "cache_creation_tokens": "100000",
            },
            {
                "sub_project": "proj1",
                "phase": "I",
                "model": "sonnet",
                "cache_read_tokens": "50000",
                "cache_creation_tokens": "50000",
            },
        ]
        groups = aggregate_by_group(rows)

        # Total from aggregation
        total_aggregated = sum(g["cost_usd"] for g in groups.values())

        # Total from individual rows
        total_individual = sum(
            _calculate_cost(
                int(r.get("cache_read_tokens", 0) or 0) + int(r.get("cache_creation_tokens", 0) or 0),
                r.get("model", "sonnet"),
            )
            for r in rows
        )

        assert abs(total_aggregated - total_individual) < 0.001
