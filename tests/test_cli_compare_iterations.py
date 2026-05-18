#!/usr/bin/env python3
"""Tests for lib/cli_compare_iterations.py -- iteration delta analysis."""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from lib.cli_compare_iterations import (
    IterationData,
    calculate_token_delta,
    compute_story_deltas,
    format_delta_report,
    format_detailed_report,
    format_json_report,
    load_iteration_data,
)


@pytest.fixture
def sample_results_tsv() -> Path:
    """Create a temporary results.tsv with test data."""
    content = """timestamp	spiral_iter	ralph_iter	story_id	story_title	status	duration_sec	model	retry_num	commit_sha	run_id	cache_hit	cache_read_tokens	cache_creation_tokens	review_tokens	wall_seconds	user_cpu_s	sys_cpu_s	peak_rss_kb	batch_id
2026-05-18T01:00:00Z	5	1	US-100	Feature A	pass	10	haiku	0	abc123	run1	true	1000	2000	0	0	0	0	0
2026-05-18T01:10:00Z	5	1	US-101	Feature B	reject	15	haiku	0	abc123	run1	false	0	0	0	0	0	0	0
2026-05-18T01:20:00Z	5	1	US-102	Feature C	pass	12	sonnet	0	abc123	run1	false	500	1500	0	0	0	0	0
2026-05-18T02:00:00Z	10	1	US-100	Feature A	pass	11	haiku	0	def456	run2	true	1000	2000	0	0	0	0	0
2026-05-18T02:10:00Z	10	1	US-101	Feature B	pass	14	sonnet	1	def456	run2	false	1500	3500	0	0	0	0	0
2026-05-18T02:20:00Z	10	1	US-103	Feature D	pass	9	haiku	0	def456	run2	false	200	800	0	0	0	0	0
2026-05-18T02:30:00Z	10	1	US-104	Feature E	reject	20	sonnet	0	def456	run2	false	0	0	0	0	0	0	0
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tsv", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        temp_path = Path(f.name)
    yield temp_path
    temp_path.unlink()


def test_load_iteration_data_iter_5(sample_results_tsv: Path) -> None:
    """Test loading iteration 5 data."""
    data = load_iteration_data(sample_results_tsv, 5)

    assert data.iteration == 5
    assert len(data.stories) == 3
    assert "US-100" in data.stories
    assert "US-101" in data.stories
    assert "US-102" in data.stories
    assert data.stories["US-100"]["status"] == "pass"
    assert data.stories["US-101"]["status"] == "reject"
    assert data.total_tokens == 5000


def test_load_iteration_data_iter_10(sample_results_tsv: Path) -> None:
    """Test loading iteration 10 data."""
    data = load_iteration_data(sample_results_tsv, 10)

    assert data.iteration == 10
    assert len(data.stories) == 4
    assert "US-100" in data.stories
    assert "US-101" in data.stories
    assert "US-103" in data.stories
    assert "US-104" in data.stories
    assert data.stories["US-101"]["status"] == "pass"
    assert data.stories["US-104"]["status"] == "reject"
    assert data.total_tokens == 9000


def test_load_iteration_data_nonexistent_iteration(sample_results_tsv: Path) -> None:
    """Test loading a nonexistent iteration."""
    data = load_iteration_data(sample_results_tsv, 999)

    assert data.iteration == 999
    assert len(data.stories) == 0
    assert data.total_tokens == 0


def test_load_iteration_data_missing_file() -> None:
    """Test loading from missing file."""
    data = load_iteration_data(Path("nonexistent.tsv"), 5)

    assert data.iteration == 5
    assert len(data.stories) == 0
    assert data.total_tokens == 0


def test_compute_story_deltas(sample_results_tsv: Path) -> None:
    """Test computing deltas between iterations 5 and 10."""
    iter_5 = load_iteration_data(sample_results_tsv, 5)
    iter_10 = load_iteration_data(sample_results_tsv, 10)

    deltas = compute_story_deltas(iter_5, iter_10)

    # US-103, US-104 are new in iter 10
    assert set(deltas["new_stories"]) == {"US-103", "US-104"}

    # US-101 recovered from reject to pass
    assert deltas["recovered_stories"] == ["US-101"]

    # Nothing still failing
    assert deltas["still_failing"] == []

    # Nothing regressed
    assert deltas["regressed"] == []


def test_compute_story_deltas_both_iterations_missing(sample_results_tsv: Path) -> None:
    """Test deltas when both iterations are missing same stories."""
    iter_5 = load_iteration_data(sample_results_tsv, 5)
    iter_10 = load_iteration_data(sample_results_tsv, 10)

    deltas = compute_story_deltas(iter_5, iter_10)

    # US-102 is in iter_5 but not in iter_10 (should not be in any delta)
    assert "US-102" not in deltas["new_stories"]
    assert "US-102" not in deltas["recovered_stories"]
    assert "US-102" not in deltas["still_failing"]


def test_calculate_token_delta(sample_results_tsv: Path) -> None:
    """Test token and cost delta calculation."""
    iter_5 = load_iteration_data(sample_results_tsv, 5)
    iter_10 = load_iteration_data(sample_results_tsv, 10)

    token_info = calculate_token_delta(iter_5, iter_10)

    assert token_info["iter_a_tokens"] == 5000
    assert token_info["iter_b_tokens"] == 9000
    assert token_info["token_delta"] == 4000
    assert token_info["cost_delta"] == round(4000 * 0.000003, 4)


def test_format_delta_report_plain_text(sample_results_tsv: Path) -> None:
    """Test plain text delta report formatting."""
    iter_5 = load_iteration_data(sample_results_tsv, 5)
    iter_10 = load_iteration_data(sample_results_tsv, 10)

    deltas = compute_story_deltas(iter_5, iter_10)
    token_info = calculate_token_delta(iter_5, iter_10)

    report = format_delta_report(5, 10, deltas, token_info)

    assert "Iteration 5 → 10" in report
    assert "New stories: 2" in report
    assert "US-103, US-104" in report
    assert "Failed→Recovered: 1" in report
    assert "US-101" in report
    assert "Still Failing: 0" in report
    assert "Token delta: +4,000" in report


def test_format_json_report(sample_results_tsv: Path) -> None:
    """Test JSON delta report formatting."""
    iter_5 = load_iteration_data(sample_results_tsv, 5)
    iter_10 = load_iteration_data(sample_results_tsv, 10)

    deltas = compute_story_deltas(iter_5, iter_10)
    token_info = calculate_token_delta(iter_5, iter_10)

    report_json = format_json_report(5, 10, deltas, token_info)
    report = json.loads(report_json)

    assert report["iteration_a"] == 5
    assert report["iteration_b"] == 10
    assert set(report["new_stories"]) == {"US-103", "US-104"}
    assert report["recovered_stories"] == ["US-101"]
    assert report["still_failing"] == []
    assert report["token_delta"] == 4000


def test_format_detailed_report(sample_results_tsv: Path) -> None:
    """Test detailed plain text report formatting."""
    iter_5 = load_iteration_data(sample_results_tsv, 5)
    iter_10 = load_iteration_data(sample_results_tsv, 10)

    deltas = compute_story_deltas(iter_5, iter_10)
    token_info = calculate_token_delta(iter_5, iter_10)

    report = format_detailed_report(5, 10, iter_5, iter_10, deltas, token_info)

    assert "Detailed Status" in report
    assert "NEW STORIES:" in report
    assert "US-103" in report
    assert "US-104" in report
    assert "RECOVERED" in report
    assert "US-101" in report


def test_iteration_data_dataclass() -> None:
    """Test IterationData dataclass creation."""
    stories: dict[str, dict[str, Any]] = {
        "US-1": {"status": "pass", "model": "haiku", "duration": "10", "tokens": 1000, "cost": 0.003}
    }
    data = IterationData(iteration=5, stories=stories, total_tokens=1000, total_cost=0.003)

    assert data.iteration == 5
    assert len(data.stories) == 1
    assert data.total_tokens == 1000
    assert data.total_cost == 0.003


def test_edge_case_empty_iterations() -> None:
    """Test deltas with empty iterations."""
    empty = IterationData(iteration=1, stories={}, total_tokens=0, total_cost=0.0)
    non_empty = IterationData(
        iteration=2,
        stories={"US-1": {"status": "pass", "model": "haiku", "duration": "10", "tokens": 1000, "cost": 0.003}},
        total_tokens=1000,
        total_cost=0.003,
    )

    deltas = compute_story_deltas(empty, non_empty)

    assert deltas["new_stories"] == ["US-1"]
    assert deltas["recovered_stories"] == []
    assert deltas["still_failing"] == []
