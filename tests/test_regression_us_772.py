"""Regression tests for US-772: Research Quality Feedback Loop.

Guards against breakage of research story scoring (calculate_research_quality_score)
and aggregation (aggregate_research_quality) in lib/research_quality.py.

Run: uv run pytest tests/ -k us_772 -v
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from research_quality import aggregate_research_quality, calculate_research_quality_score


def test_us_772_scoring_formula() -> None:
    """Core scoring: retry_count maps to fixed quality scores."""
    assert calculate_research_quality_score(0) == 100  # 1-try pass
    assert calculate_research_quality_score(1) == 70  # 2-try pass
    assert calculate_research_quality_score(2) == 50  # 3-try pass
    assert calculate_research_quality_score(3) == 30  # 3+ retries
    assert calculate_research_quality_score(10) == 30  # capped at 30


def test_us_772_aggregate_filters_research_source() -> None:
    """Only _source=research stories contribute to quality metrics."""
    prd: dict[str, Any] = {
        "userStories": [
            {"id": "US-100", "title": "Research story", "_source": "research"},
            {"id": "US-200", "title": "AI story", "_source": "ai-example"},
        ]
    }
    with TemporaryDirectory() as tmpdir:
        tsv = Path(tmpdir) / "results.tsv"
        result = aggregate_research_quality(prd, tsv)
    assert result.total_stories == 1
    assert "US-100" in result.scores_by_story
    assert "US-200" not in result.scores_by_story


def test_us_772_aggregate_uses_retry_count() -> None:
    """Aggregate quality score reflects retry_num from results.tsv."""
    prd: dict[str, Any] = {
        "userStories": [
            {"id": "US-300", "title": "Fast story", "_source": "research"},
            {"id": "US-301", "title": "Slow story", "_source": "research"},
        ]
    }
    with TemporaryDirectory() as tmpdir:
        tsv = Path(tmpdir) / "results.tsv"
        with open(tsv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["story_id", "retry_num", "status"], delimiter="\t")
            writer.writeheader()
            writer.writerow({"story_id": "US-300", "retry_num": "0", "status": "passed"})
            writer.writerow({"story_id": "US-301", "retry_num": "3", "status": "failed"})
        result = aggregate_research_quality(prd, tsv)
    assert result.scores_by_story["US-300"] == 100
    assert result.scores_by_story["US-301"] == 30
    assert result.average_score == pytest.approx(65.0)
