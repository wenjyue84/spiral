"""Tests for metrics_export.py."""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.metrics_export import (
    _cost_per_token,
    _model_tier_score,
    _total_tokens_from_duration,
    aggregate_timeseries,
    export_timeseries,
    parse_results_tsv,
    parse_spiral_events,
)


class TestTokensFromDuration:
    """Test _total_tokens_from_duration."""

    def test_tokens_positive_duration(self) -> None:
        """Test token calculation for positive duration."""
        # 1 second should give TOKENS_PER_SEC_OUTPUT * (1 + INPUT_OUTPUT_RATIO) tokens
        # = 20 * (1 + 3) = 80 tokens
        tokens = _total_tokens_from_duration(1.0)
        assert tokens == 80.0

    def test_tokens_zero_duration(self) -> None:
        """Test token calculation for zero duration."""
        tokens = _total_tokens_from_duration(0.0)
        assert tokens == 0.0

    def test_tokens_scales_linearly(self) -> None:
        """Test that tokens scale linearly with duration."""
        t1 = _total_tokens_from_duration(1.0)
        t2 = _total_tokens_from_duration(2.0)
        assert t2 == pytest.approx(t1 * 2)


class TestCostPerToken:
    """Test _cost_per_token."""

    def test_haiku_pricing(self) -> None:
        """Test haiku model pricing."""
        cost = _cost_per_token("haiku")
        # haiku: $0.80 per million tokens = 0.80e-6 per token
        assert cost == pytest.approx(0.80 / 1_000_000)

    def test_sonnet_pricing(self) -> None:
        """Test sonnet model pricing."""
        cost = _cost_per_token("sonnet")
        # sonnet: $3.00 per million tokens = 3.00e-6 per token
        assert cost == pytest.approx(3.00 / 1_000_000)

    def test_opus_pricing(self) -> None:
        """Test opus model pricing."""
        cost = _cost_per_token("opus")
        # opus: $15.00 per million tokens = 15.00e-6 per token
        assert cost == pytest.approx(15.00 / 1_000_000)

    def test_case_insensitive(self) -> None:
        """Test that model name matching is case-insensitive."""
        cost_lower = _cost_per_token("haiku")
        cost_upper = _cost_per_token("HAIKU")
        assert cost_lower == cost_upper

    def test_unknown_model_defaults_to_sonnet(self) -> None:
        """Test that unknown model defaults to sonnet pricing."""
        cost = _cost_per_token("unknown-model")
        sonnet_cost = _cost_per_token("sonnet")
        assert cost == sonnet_cost


class TestModelTierScore:
    """Test _model_tier_score."""

    def test_haiku_score(self) -> None:
        """Test haiku gets score 1."""
        assert _model_tier_score("haiku") == 1

    def test_sonnet_score(self) -> None:
        """Test sonnet gets score 2."""
        assert _model_tier_score("sonnet") == 2

    def test_opus_score(self) -> None:
        """Test opus gets score 3."""
        assert _model_tier_score("opus") == 3

    def test_case_insensitive(self) -> None:
        """Test case-insensitive matching."""
        assert _model_tier_score("HAIKU") == _model_tier_score("haiku")
        assert _model_tier_score("Sonnet") == _model_tier_score("sonnet")

    def test_unknown_model_defaults_to_sonnet(self) -> None:
        """Test that unknown model defaults to sonnet (tier 2)."""
        assert _model_tier_score("unknown") == 2


class TestParseResultsTsv:
    """Test parse_results_tsv."""

    def test_nonexistent_file(self) -> None:
        """Test handling of nonexistent results.tsv."""
        result = parse_results_tsv(Path("/nonexistent/results.tsv"))
        assert result == {}

    def test_empty_file(self) -> None:
        """Test handling of empty results.tsv."""
        with TemporaryDirectory() as tmpdir:
            tsv_path = Path(tmpdir) / "results.tsv"
            tsv_path.write_text("")
            result = parse_results_tsv(tsv_path)
            assert result == {}

    def test_valid_tsv_single_iteration(self) -> None:
        """Test parsing valid results.tsv with single iteration."""
        with TemporaryDirectory() as tmpdir:
            tsv_path = Path(tmpdir) / "results.tsv"
            tsv_content = (
                "timestamp\tspiral_iter\tstory_id\tstatus\tduration_sec\tmodel\n"
                "2026-04-01T00:00:00Z\t1\tUS-100\tpass\t120\thaniku\n"
                "2026-04-01T00:02:00Z\t1\tUS-101\tpass\t180\tsonnet\n"
            )
            tsv_path.write_text(tsv_content)
            result = parse_results_tsv(tsv_path)

            assert 1 in result
            assert len(result[1]) == 2
            assert result[1][0]["story_id"] == "US-100"
            assert result[1][1]["story_id"] == "US-101"

    def test_valid_tsv_multiple_iterations(self) -> None:
        """Test parsing results.tsv with multiple iterations."""
        with TemporaryDirectory() as tmpdir:
            tsv_path = Path(tmpdir) / "results.tsv"
            tsv_content = (
                "timestamp\tspiral_iter\tstory_id\tstatus\tduration_sec\tmodel\n"
                "2026-04-01T00:00:00Z\t1\tUS-100\tpass\t120\thaniku\n"
                "2026-04-01T01:00:00Z\t2\tUS-200\tpass\t180\tsonnet\n"
                "2026-04-01T02:00:00Z\t2\tUS-201\treject\t100\topus\n"
            )
            tsv_path.write_text(tsv_content)
            result = parse_results_tsv(tsv_path)

            assert 1 in result
            assert 2 in result
            assert len(result[1]) == 1
            assert len(result[2]) == 2

    def test_skips_rows_without_spiral_iter(self) -> None:
        """Test that rows without spiral_iter are skipped."""
        with TemporaryDirectory() as tmpdir:
            tsv_path = Path(tmpdir) / "results.tsv"
            tsv_content = (
                "timestamp\tspiral_iter\tstory_id\tstatus\tduration_sec\tmodel\n"
                "2026-04-01T00:00:00Z\t1\tUS-100\tpass\t120\thaniku\n"
                "2026-04-01T00:02:00Z\t\tUS-101\tpass\t180\tsonnet\n"
            )
            tsv_path.write_text(tsv_content)
            result = parse_results_tsv(tsv_path)

            assert len(result[1]) == 1


class TestParseSpiralEvents:
    """Test parse_spiral_events."""

    def test_nonexistent_file(self) -> None:
        """Test handling of nonexistent spiral_events.jsonl."""
        result = parse_spiral_events(Path("/nonexistent/spiral_events.jsonl"))
        assert result == {}

    def test_empty_file(self) -> None:
        """Test handling of empty spiral_events.jsonl."""
        with TemporaryDirectory() as tmpdir:
            events_path = Path(tmpdir) / "spiral_events.jsonl"
            events_path.write_text("")
            result = parse_spiral_events(events_path)
            assert result == {}

    def test_extracts_phase_g_events(self) -> None:
        """Test extraction of Phase G completion events."""
        with TemporaryDirectory() as tmpdir:
            events_path = Path(tmpdir) / "spiral_events.jsonl"
            events_content = (
                '{"event_type": "phase_complete", "phase_letter": "G", '
                '"iteration": 1, "timestamp": "2026-04-01T00:30:00Z"}\n'
                '{"event_type": "phase_complete", "phase_letter": "G", '
                '"iteration": 2, "timestamp": "2026-04-01T01:30:00Z"}\n'
            )
            events_path.write_text(events_content)
            result = parse_spiral_events(events_path)

            assert 1 in result
            assert 2 in result
            assert result[1] == "2026-04-01T00:30:00Z"
            assert result[2] == "2026-04-01T01:30:00Z"

    def test_ignores_non_phase_g_events(self) -> None:
        """Test that non-Phase G events are ignored."""
        with TemporaryDirectory() as tmpdir:
            events_path = Path(tmpdir) / "spiral_events.jsonl"
            events_content = (
                '{"event_type": "phase_complete", "phase_letter": "A", '
                '"iteration": 1, "timestamp": "2026-04-01T00:10:00Z"}\n'
                '{"event_type": "phase_complete", "phase_letter": "G", '
                '"iteration": 1, "timestamp": "2026-04-01T00:30:00Z"}\n'
            )
            events_path.write_text(events_content)
            result = parse_spiral_events(events_path)

            assert len(result) == 1
            assert result[1] == "2026-04-01T00:30:00Z"

    def test_ignores_malformed_json(self) -> None:
        """Test that malformed JSON lines are skipped."""
        with TemporaryDirectory() as tmpdir:
            events_path = Path(tmpdir) / "spiral_events.jsonl"
            events_content = (
                '{"event_type": "phase_complete", "phase_letter": "G", '
                '"iteration": 1, "timestamp": "2026-04-01T00:30:00Z"}\n'
                "not valid json\n"
                '{"event_type": "phase_complete", "phase_letter": "G", '
                '"iteration": 2, "timestamp": "2026-04-01T01:30:00Z"}\n'
            )
            events_path.write_text(events_content)
            result = parse_spiral_events(events_path)

            assert len(result) == 2


class TestAggregateTimeseries:
    """Test aggregate_timeseries."""

    def test_empty_iteration_dict(self) -> None:
        """Test aggregating empty iteration data."""
        result = aggregate_timeseries({}, {})
        assert result == []

    def test_single_iteration_single_story(self) -> None:
        """Test aggregating single iteration with single story."""
        by_iteration = {
            1: [
                {
                    "story_id": "US-100",
                    "status": "pass",
                    "duration_sec": "100",
                    "model": "haiku",
                    "timestamp": "2026-04-01T00:00:00Z",
                }
            ]
        }
        result = aggregate_timeseries(by_iteration, {})

        assert len(result) == 1
        assert result[0]["iteration"] == 1
        assert result[0]["stories_passed_delta"] == 1
        assert result[0]["cumulative_tokens"] > 0
        assert result[0]["avg_model_tier"] == 1.0
        assert result[0]["total_cost"] > 0

    def test_multiple_iterations_cumulative_tokens(self) -> None:
        """Test that tokens are cumulative across iterations."""
        by_iteration = {
            1: [
                {
                    "story_id": "US-100",
                    "status": "pass",
                    "duration_sec": "100",
                    "model": "haiku",
                    "timestamp": "2026-04-01T00:00:00Z",
                }
            ],
            2: [
                {
                    "story_id": "US-200",
                    "status": "pass",
                    "duration_sec": "100",
                    "model": "haiku",
                    "timestamp": "2026-04-01T01:00:00Z",
                }
            ],
        }
        result = aggregate_timeseries(by_iteration, {})

        assert len(result) == 2
        assert result[0]["cumulative_tokens"] > 0
        assert result[1]["cumulative_tokens"] > result[0]["cumulative_tokens"]

    def test_uses_phase_g_timestamp(self) -> None:
        """Test that Phase G timestamp is used when available."""
        by_iteration = {
            1: [
                {
                    "story_id": "US-100",
                    "status": "pass",
                    "duration_sec": "100",
                    "model": "haiku",
                    "timestamp": "2026-04-01T00:00:00Z",
                }
            ]
        }
        iter_timestamps = {1: "2026-04-01T00:30:00Z"}
        result = aggregate_timeseries(by_iteration, iter_timestamps)

        assert result[0]["timestamp"] == "2026-04-01T00:30:00Z"

    def test_average_model_tier(self) -> None:
        """Test average model tier calculation."""
        by_iteration = {
            1: [
                {
                    "story_id": "US-100",
                    "status": "pass",
                    "duration_sec": "100",
                    "model": "haiku",
                },
                {
                    "story_id": "US-101",
                    "status": "pass",
                    "duration_sec": "100",
                    "model": "sonnet",
                },
            ]
        }
        result = aggregate_timeseries(by_iteration, {})

        # Average of 1 (haiku) and 2 (sonnet) = 1.5
        assert result[0]["avg_model_tier"] == 1.5


class TestExportTimeseries:
    """Test export_timeseries."""

    def test_insufficient_records_error(self) -> None:
        """Test that error is raised when fewer than 10 records exist."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            tsv_path = tmpdir_path / "results.tsv"
            events_path = tmpdir_path / "spiral_events.jsonl"
            output_path = tmpdir_path / "output.json"

            # Create minimal TSV with only 5 records
            tsv_content = "timestamp\tspiral_iter\tstory_id\tstatus\tduration_sec\tmodel\n" + "\n".join(
                f"2026-04-01T{i:02d}:00:00Z\t1\tUS-{100 + i}\tpass\t100\thaniku" for i in range(5)
            )
            tsv_path.write_text(tsv_content)
            events_path.write_text("")

            with pytest.raises(ValueError, match="only 5 story records found"):
                export_timeseries(tsv_path, events_path, output_path)

    def test_export_timeseries_format(self) -> None:
        """Test that export produces valid JSON with required fields."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            tsv_path = tmpdir_path / "results.tsv"
            events_path = tmpdir_path / "spiral_events.jsonl"
            output_path = tmpdir_path / "output.json"

            # Create TSV with 10+ records
            tsv_lines = ["timestamp\tspiral_iter\tstory_id\tstatus\tduration_sec\tmodel"]
            for i in range(12):
                tsv_lines.append(f"2026-04-01T{i:02d}:00:00Z\t{(i // 6) + 1}\tUS-{100 + i}\tpass\t100\thaniku")
            tsv_path.write_text("\n".join(tsv_lines))

            # Create events with Phase G completions
            events_lines = [
                '{"event_type": "phase_complete", "phase_letter": "G", '
                '"iteration": 1, "timestamp": "2026-04-01T03:00:00Z"}',
                '{"event_type": "phase_complete", "phase_letter": "G", '
                '"iteration": 2, "timestamp": "2026-04-01T09:00:00Z"}',
            ]
            events_path.write_text("\n".join(events_lines))

            export_timeseries(tsv_path, events_path, output_path)

            # Verify output exists and is valid JSON
            assert output_path.exists()
            with open(output_path, encoding="utf-8") as f:
                data = json.load(f)

            assert isinstance(data, list)
            assert len(data) == 2

            # Check required fields
            for entry in data:
                assert "iteration" in entry
                assert "timestamp" in entry
                assert "cumulative_tokens" in entry
                assert "stories_passed_delta" in entry
                assert "avg_model_tier" in entry
                assert "total_cost" in entry

            # Verify data is sorted by iteration
            assert data[0]["iteration"] < data[1]["iteration"]


def test_export_timeseries_cli_usage() -> None:
    """Integration test: test metrics_export module via CLI."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        tsv_path = tmpdir_path / "results.tsv"
        events_path = tmpdir_path / "spiral_events.jsonl"
        output_path = tmpdir_path / "output.json"

        # Create valid test data (10+ records)
        tsv_lines = ["timestamp\tspiral_iter\tstory_id\tstatus\tduration_sec\tmodel"]
        for i in range(15):
            tsv_lines.append(f"2026-04-01T{i:02d}:00:00Z\t{(i // 8) + 1}\tUS-{100 + i}\tpass\t100\tsonnet")
        tsv_path.write_text("\n".join(tsv_lines))
        events_path.write_text("")

        export_timeseries(tsv_path, events_path, output_path)

        # Verify output
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        assert len(data) >= 1
        assert all("iteration" in e and "total_cost" in e for e in data)
