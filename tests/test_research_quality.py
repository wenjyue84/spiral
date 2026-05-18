"""Tests for lib/research_quality.py — Research quality feedback loop (US-772).

Tests scoring formula, aggregation, and trend analysis.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from research_quality import (
    ResearchQualityResult,
    aggregate_research_quality,
    calculate_research_quality_score,
    filter_research_results_by_quality,
    format_research_quality_report,
    get_research_quality_trend,
    score_research_result,
)

# ── Scoring Formula Tests ──────────────────────────────────────────────────────


class TestScoringFormula:
    """Unit tests for calculate_research_quality_score()."""

    def test_1_try_pass_scores_100(self) -> None:
        """AC4: 1-try pass (retry_count=0) scores 100."""
        score = calculate_research_quality_score(retry_count=0)
        assert score == 100

    def test_2_try_pass_scores_70(self) -> None:
        """2-try pass (retry_count=1) scores 70."""
        score = calculate_research_quality_score(retry_count=1)
        assert score == 70

    def test_3_try_pass_scores_50(self) -> None:
        """3-try pass (retry_count=2) scores 50."""
        score = calculate_research_quality_score(retry_count=2)
        assert score == 50

    def test_3_plus_retries_score_30(self) -> None:
        """AC4: 3+ retries (retry_count >= 3) scores 30."""
        assert calculate_research_quality_score(retry_count=3) == 30
        assert calculate_research_quality_score(retry_count=4) == 30
        assert calculate_research_quality_score(retry_count=10) == 30

    def test_boundary_at_retry_2(self) -> None:
        """Verify boundary between 50 and 30 point ranges."""
        assert calculate_research_quality_score(retry_count=2) == 50
        assert calculate_research_quality_score(retry_count=3) == 30


# ── Aggregation Tests ──────────────────────────────────────────────────────────


class TestAggregation:
    """Unit tests for aggregate_research_quality()."""

    def test_returns_zero_for_no_research_stories(self) -> None:
        """Empty PRD with no research stories returns zero metrics."""
        prd: dict[str, Any] = {"userStories": []}
        with TemporaryDirectory() as tmpdir:
            tsv = Path(tmpdir) / "results.tsv"
            result = aggregate_research_quality(prd, tsv)
            assert result.total_stories == 0
            assert result.average_score == 0.0

    def test_returns_zero_for_missing_results_tsv(self) -> None:
        """Missing results.tsv returns zero metrics (graceful fallback)."""
        prd: dict[str, Any] = {"userStories": [{"id": "US-500", "title": "Test", "_source": "research"}]}
        with TemporaryDirectory() as tmpdir:
            tsv = Path(tmpdir) / "nonexistent.tsv"
            result = aggregate_research_quality(prd, tsv)
            assert result.total_stories == 1
            # Story not in results.tsv, so retry_count defaults to 0 (score 100)
            assert result.average_score == 100.0

    def test_aggregates_scores_from_results_tsv(self) -> None:
        """AC1: Stories with _source=research gain score from results.tsv retry_num."""
        prd: dict[str, Any] = {
            "userStories": [
                {"id": "US-500", "title": "Story 1", "_source": "research"},
                {"id": "US-501", "title": "Story 2", "_source": "research"},
                {"id": "US-600", "title": "Non-research", "_source": "ai-example"},
            ]
        }
        with TemporaryDirectory() as tmpdir:
            tsv = Path(tmpdir) / "results.tsv"
            with open(tsv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["story_id", "retry_num", "status"],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerow({"story_id": "US-500", "retry_num": "0", "status": "passed"})
                writer.writerow({"story_id": "US-501", "retry_num": "3", "status": "failed"})
                writer.writerow({"story_id": "US-600", "retry_num": "1", "status": "passed"})

            result = aggregate_research_quality(prd, tsv)
            assert result.total_stories == 2  # Only research stories
            assert result.scores_by_story["US-500"] == 100  # 1-try pass
            assert result.scores_by_story["US-501"] == 30  # 3+ retries
            assert result.average_score == 65.0  # (100 + 30) / 2

    def test_tracks_max_retry_for_multiple_rows(self) -> None:
        """If story appears multiple times, use max retry_num."""
        prd: dict[str, Any] = {"userStories": [{"id": "US-500", "title": "Story", "_source": "research"}]}
        with TemporaryDirectory() as tmpdir:
            tsv = Path(tmpdir) / "results.tsv"
            with open(tsv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["story_id", "retry_num", "status"],
                    delimiter="\t",
                )
                writer.writeheader()
                # Story attempted multiple times
                writer.writerow({"story_id": "US-500", "retry_num": "0", "status": "failed"})
                writer.writerow({"story_id": "US-500", "retry_num": "1", "status": "failed"})
                writer.writerow({"story_id": "US-500", "retry_num": "2", "status": "passed"})

            result = aggregate_research_quality(prd, tsv)
            assert result.scores_by_story["US-500"] == 50  # max retry_num = 2

    def test_skips_stories_not_in_research_sourced_list(self) -> None:
        """Non-research stories in results.tsv are ignored."""
        prd: dict[str, Any] = {"userStories": [{"id": "US-500", "title": "Research", "_source": "research"}]}
        with TemporaryDirectory() as tmpdir:
            tsv = Path(tmpdir) / "results.tsv"
            with open(tsv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["story_id", "retry_num", "status"],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerow({"story_id": "US-600", "retry_num": "5", "status": "failed"})
                writer.writerow({"story_id": "US-500", "retry_num": "0", "status": "passed"})

            result = aggregate_research_quality(prd, tsv)
            assert len(result.scores_by_story) == 1
            assert "US-600" not in result.scores_by_story

    def test_median_calculation(self) -> None:
        """Median is correctly calculated for score distribution."""
        prd: dict[str, Any] = {
            "userStories": [{"id": f"US-{500 + i}", "title": f"Story {i}", "_source": "research"} for i in range(3)]
        }
        with TemporaryDirectory() as tmpdir:
            tsv = Path(tmpdir) / "results.tsv"
            with open(tsv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["story_id", "retry_num", "status"],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerow({"story_id": "US-500", "retry_num": "0", "status": "passed"})  # score 100
                writer.writerow({"story_id": "US-501", "retry_num": "1", "status": "passed"})  # score 70
                writer.writerow({"story_id": "US-502", "retry_num": "3", "status": "failed"})  # score 30

            result = aggregate_research_quality(prd, tsv)
            assert result.median_score == 70.0  # Median of [30, 70, 100]

    def test_groups_stories_by_status(self) -> None:
        """Stories grouped by pass/fail status in results_by_status."""
        prd: dict[str, Any] = {
            "userStories": [
                {"id": "US-500", "title": "Story 1", "_source": "research"},
                {"id": "US-501", "title": "Story 2", "_source": "research"},
            ]
        }
        with TemporaryDirectory() as tmpdir:
            tsv = Path(tmpdir) / "results.tsv"
            with open(tsv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["story_id", "retry_num", "status"],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerow({"story_id": "US-500", "retry_num": "0", "status": "passed"})
                writer.writerow({"story_id": "US-501", "retry_num": "2", "status": "failed"})

            result = aggregate_research_quality(prd, tsv)
            assert "US-500" in result.stories_by_status["passed"]
            assert "US-501" in result.stories_by_status["failed"]


# ── Trend Analysis Tests ───────────────────────────────────────────────────────


class TestTrendAnalysis:
    """Unit tests for get_research_quality_trend()."""

    def test_returns_empty_for_missing_tsv(self) -> None:
        """Missing results.tsv returns empty trend list."""
        with TemporaryDirectory() as tmpdir:
            tsv = Path(tmpdir) / "nonexistent.tsv"
            trend = get_research_quality_trend(tsv, iterations=3)
            assert trend == []

    def test_extracts_trend_from_last_n_iterations(self) -> None:
        """AC2: Phase R logs average research quality from last 3 iterations."""
        with TemporaryDirectory() as tmpdir:
            tsv = Path(tmpdir) / "results.tsv"
            with open(tsv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "story_id",
                        "spiral_iter",
                        "retry_num",
                        "_source",
                        "status",
                    ],
                    delimiter="\t",
                )
                writer.writeheader()
                # Iteration 1: 2 research stories, avg score 85 (100 + 70)/2
                writer.writerow(
                    {
                        "story_id": "US-500",
                        "spiral_iter": "1",
                        "retry_num": "0",
                        "_source": "research",
                        "status": "passed",
                    }
                )
                writer.writerow(
                    {
                        "story_id": "US-501",
                        "spiral_iter": "1",
                        "retry_num": "1",
                        "_source": "research",
                        "status": "passed",
                    }
                )
                # Iteration 2: 1 research story, avg score 30
                writer.writerow(
                    {
                        "story_id": "US-502",
                        "spiral_iter": "2",
                        "retry_num": "3",
                        "_source": "research",
                        "status": "failed",
                    }
                )
                # Iteration 3: 1 research story, avg score 100
                writer.writerow(
                    {
                        "story_id": "US-503",
                        "spiral_iter": "3",
                        "retry_num": "0",
                        "_source": "research",
                        "status": "passed",
                    }
                )

            trends = get_research_quality_trend(tsv, iterations=3)
            assert len(trends) == 3
            assert trends[0].iteration == 1
            assert trends[0].average_score == 85.0
            assert trends[0].story_count == 2
            assert trends[1].iteration == 2
            assert trends[1].average_score == 30.0
            assert trends[1].story_count == 1
            assert trends[2].iteration == 3
            assert trends[2].average_score == 100.0
            assert trends[2].story_count == 1

    def test_filters_to_last_n_iterations(self) -> None:
        """Returns only last N iterations when N < total iterations."""
        with TemporaryDirectory() as tmpdir:
            tsv = Path(tmpdir) / "results.tsv"
            with open(tsv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "story_id",
                        "spiral_iter",
                        "retry_num",
                        "_source",
                        "status",
                    ],
                    delimiter="\t",
                )
                writer.writeheader()
                for iter_num in range(1, 6):
                    writer.writerow(
                        {
                            "story_id": f"US-{500 + iter_num}",
                            "spiral_iter": str(iter_num),
                            "retry_num": "0",
                            "_source": "research",
                            "status": "passed",
                        }
                    )

            trends = get_research_quality_trend(tsv, iterations=2)
            assert len(trends) == 2
            assert trends[0].iteration == 4
            assert trends[1].iteration == 5


# ── Source Credibility Scoring Tests (US-1407) ────────────────────────────────


class TestSourceCredibilityScoring:
    """Unit tests for score_research_result() — Source credibility scoring."""

    def test_score_academic_sources(self) -> None:
        """AC1: .edu/.gov/.org domains score >60, ad/spam <40."""
        # Educational domains
        assert score_research_result("https://example.edu", "Academic content") >= 70
        assert score_research_result("https://university.ac.uk", "Research paper") >= 70
        assert score_research_result("https://research.gov", "Government data") >= 70
        assert score_research_result("https://org.edu.au", "Australian education") >= 70

        # Organizational domains
        score_org = score_research_result("https://nonprofit.org", "Nonprofit content")
        assert score_org >= 70, f"Expected .org >= 70, got {score_org}"

        # Ad/marketing/spam domains should score <40
        assert score_research_result("https://ads.example.com", "Click here!") < 40
        assert score_research_result("https://example.com/path?utm_campaign=x", "Buy now!") < 40
        assert score_research_result("https://linkedin.com/posts", "Content") < 40
        assert score_research_result("https://reddit.com/r/x", "Discussion") < 40

    def test_reputable_news_sources(self) -> None:
        """AC2: Known news outlets (reuters, bbc, nyt, etc) score 65+."""
        news_sources = [
            "https://reuters.com/article",
            "https://bbc.com/news",
            "https://nytimes.com/story",
            "https://bloomberg.com/article",
            "https://wsj.com/article",
        ]
        for url in news_sources:
            score = score_research_result(url, "News content")
            assert score >= 65, f"News source {url} should score >= 65, got {score}"

    def test_tech_media_sources(self) -> None:
        """AC3: Tech media (techcrunch, arstechnica, theverge) score 60+."""
        tech_sources = [
            ("https://techcrunch.com/article", 60),
            ("https://arstechnica.com/article", 60),
            ("https://theverge.com/article", 60),
        ]
        for url, min_score in tech_sources:
            score = score_research_result(url, "Tech news")
            assert score >= min_score, f"{url} should score >= {min_score}, got {score}"

    def test_blog_forum_low_score(self) -> None:
        """AC4: Blogs and forums (medium, dev.to, reddit) score <50."""
        blog_sources = [
            "https://medium.com/@author/article",
            "https://dev.to/author/article",
        ]
        for url in blog_sources:
            score = score_research_result(url, "Blog post")
            assert score < 50, f"Blog source {url} should score < 50, got {score}"

    def test_snippet_quality_affects_score(self) -> None:
        """AC5: Short/error/marketing snippets reduce credibility score."""
        # Short snippet should reduce score
        score_short = score_research_result("https://example.edu", "Hi")
        score_normal = score_research_result(
            "https://example.edu", "This is a longer academic snippet with substantial content"
        )
        assert score_short < score_normal, "Short snippets should score lower"

        # Error pages reduce score
        score_error = score_research_result("https://example.edu", "404 error not found")
        assert score_error < 50, f"Error pages should score low, got {score_error}"

        # Marketing language reduces score
        score_marketing = score_research_result("https://example.edu", "Limited time offer! Click here now!")
        assert score_marketing < score_normal, "Marketing snippets should score lower"

    def test_empty_url_scores_low(self) -> None:
        """AC6: Missing URL scores very low."""
        score = score_research_result("", "Some content")
        assert score < 30, f"Empty URL should score < 30, got {score}"

    def test_invalid_url_scores_low(self) -> None:
        """AC7: Invalid URLs score low."""
        score = score_research_result("not a valid url", "Content")
        assert score < 40, f"Invalid URL should score < 40, got {score}"

    def test_score_in_valid_range(self) -> None:
        """AC8: All scores returned are in [0, 100] range."""
        test_cases = [
            ("https://example.edu", "Content"),
            ("https://reddit.com", "Post"),
            ("", "Content"),
            ("https://ads.com", "Buy now!"),
            ("https://nature.com", "Research"),
        ]
        for url, snippet in test_cases:
            score = score_research_result(url, snippet)
            assert 0 <= score <= 100, f"Score out of range: {score}"


class TestFilteringByQuality:
    """Unit tests for filter_research_results_by_quality()."""

    def test_filters_low_score_results(self) -> None:
        """Low-score results are removed from output."""
        results = {
            "stories": [
                {"url": "https://example.edu", "snippet": "Academic content", "title": "Good source"},
                {"url": "https://ads.com", "snippet": "Click here!", "title": "Bad source"},
                {"url": "https://reddit.com", "snippet": "Discussion", "title": "Forum"},
            ]
        }
        filtered = filter_research_results_by_quality(results, min_score=40)
        assert filtered["_skipped_count"] >= 1, "Should skip low-score results"

    def test_adds_quality_score_metadata(self) -> None:
        """Kept results include _quality_score field."""
        results = {
            "stories": [
                {"url": "https://example.edu", "snippet": "Academic content", "title": "Good"},
            ]
        }
        filtered = filter_research_results_by_quality(results, min_score=40)
        filtered_stories = filtered.get("stories", [])
        assert len(filtered_stories) > 0, "Should keep high-score results"
        assert "_quality_score" in filtered_stories[0], "Should add _quality_score field"
        assert filtered_stories[0]["_quality_score"] >= 40, "Score should meet minimum"

    def test_logs_filtering_decisions(self) -> None:
        """Filtering decisions are logged to JSONL."""
        with TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "quality.jsonl"
            results = {
                "stories": [
                    {"url": "https://ads.com", "snippet": "Buy now!", "title": "Ad"},
                ]
            }
            filter_research_results_by_quality(results, min_score=40, log_path=str(log_path))
            assert log_path.exists(), "Log file should be created"
            # Read and verify log entries
            with open(log_path, encoding="utf-8") as f:
                lines = f.readlines()
                assert len(lines) > 0, "Should have log entries"

    def test_empty_results(self) -> None:
        """Empty results don't cause errors."""
        results: dict[str, Any] = {"stories": []}
        filtered = filter_research_results_by_quality(results, min_score=40)
        assert filtered["stories"] == []
        assert filtered["_skipped_count"] == 0


# ── Formatting Tests ───────────────────────────────────────────────────────────


class TestFormatting:
    """Unit tests for human-readable report formatting."""

    def test_formats_research_quality_report(self) -> None:
        """Report includes metrics, score distribution, and status breakdown."""
        result = ResearchQualityResult(
            total_stories=5,
            average_score=72.0,
            median_score=70.0,
            scores_by_story={"US-500": 100, "US-501": 70, "US-502": 50, "US-503": 30},
            stories_by_status={"passed": ["US-500", "US-501"], "failed": ["US-502"]},
        )
        report = format_research_quality_report(result)
        assert "Research Quality Report" in report
        assert "Total research-sourced stories: 5" in report
        assert "Average quality score: 72.0/100" in report
        assert "Stories passed: 2" in report
        assert "Stories failed: 1" in report
        assert "Score Distribution:" in report
        assert "90-100: 1 stories" in report
        assert "70-89: 1 stories" in report
