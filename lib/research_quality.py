"""lib/research_quality.py — Research quality scoring and analytics (US-772).

Tracks how well research-sourced stories implement through Phase I by scoring
based on retry count. Aggregates scores to identify which research strategies
yield implementable stories.

Usage (Python API):
    from research_quality import (
        calculate_research_quality_score,
        aggregate_research_quality,
        get_research_quality_trend,
    )

    # Score a single story by retry count
    score = calculate_research_quality_score(retry_count=2)  # Returns 70

    # Aggregate all research-sourced stories
    prd = load_prd("prd.json")
    results = aggregate_research_quality(prd, Path("results.tsv"))
    # Returns: {
    #   "total_stories": 42,
    #   "average_score": 68.5,
    #   "scores_by_story": {"US-500": 100, "US-501": 30, ...}
    # }

    # Get trend across last N iterations
    trend = get_research_quality_trend(Path("results.tsv"), iterations=3)
    # Returns: [
    #   {"iteration": 5, "average_score": 72.0},
    #   {"iteration": 6, "average_score": 65.0},
    # ]

CLI usage (via main.py):
    spiral show-research-quality
    spiral show-research-quality --last-n-iterations 3 --json
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def calculate_research_quality_score(retry_count: int) -> int:
    """Calculate research quality score based on retry count.

    Scoring formula:
    - retry_count == 0 (1-try pass): 100 points
    - retry_count == 1 (2-try pass): 70 points
    - retry_count == 2 (3-try pass): 50 points
    - retry_count >= 3: 30 points

    Args:
        retry_count: Number of retries (0 = first attempt succeeded).

    Returns:
        Score (0-100).
    """
    if retry_count == 0:
        return 100
    elif retry_count == 1:
        return 70
    elif retry_count == 2:
        return 50
    else:
        return 30


@dataclass
class ResearchQualityResult:
    """Aggregated research quality metrics."""

    total_stories: int
    average_score: float
    median_score: float
    scores_by_story: dict[str, int]  # story_id -> score
    stories_by_status: dict[str, list[str]]  # "passed" -> [story_ids], "failed" -> [...]


def aggregate_research_quality(
    prd: dict[str, Any],
    results_tsv: Path,
) -> ResearchQualityResult:
    """Aggregate research quality scores from prd.json and results.tsv.

    Filters stories with _source="research", reads max retry_count per story
    from results.tsv, calculates score for each, and returns aggregated metrics.

    Args:
        prd: Parsed prd.json dict.
        results_tsv: Path to results.tsv.

    Returns:
        ResearchQualityResult with aggregated metrics.
    """
    # Find all research-sourced stories
    research_stories = {s["id"]: s for s in prd.get("userStories", []) if s.get("_source") == "research"}

    if not research_stories:
        return ResearchQualityResult(
            total_stories=0,
            average_score=0.0,
            median_score=0.0,
            scores_by_story={},
            stories_by_status={"passed": [], "failed": []},
        )

    # Load retry counts from results.tsv
    retry_counts: dict[str, int] = {}  # story_id -> max retry_count
    statuses: dict[str, str] = {}  # story_id -> status

    if results_tsv.exists():
        try:
            with open(results_tsv, encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    story_id = row.get("story_id", "")
                    if story_id not in research_stories:
                        continue

                    try:
                        retry_num = int(row.get("retry_num", 0) or 0)
                        status = row.get("status", "unknown")

                        # Track max retry count for this story
                        if story_id not in retry_counts:
                            retry_counts[story_id] = retry_num
                        else:
                            retry_counts[story_id] = max(retry_counts[story_id], retry_num)

                        # Track latest status (last row wins)
                        statuses[story_id] = status
                    except (ValueError, TypeError):
                        pass
        except (OSError, csv.Error):
            pass

    # Calculate scores
    scores_by_story: dict[str, int] = {}
    for story_id in research_stories:
        retry_count = retry_counts.get(story_id, 0)
        scores_by_story[story_id] = calculate_research_quality_score(retry_count)

    # Group by status
    stories_by_status: dict[str, list[str]] = {"passed": [], "failed": []}
    for story_id, status in statuses.items():
        if status == "passed":
            stories_by_status["passed"].append(story_id)
        elif status == "failed":
            stories_by_status["failed"].append(story_id)

    # Calculate aggregate metrics
    scores_list = list(scores_by_story.values())
    avg_score = sum(scores_list) / len(scores_list) if scores_list else 0.0
    median_score = _calculate_median(scores_list)

    return ResearchQualityResult(
        total_stories=len(research_stories),
        average_score=avg_score,
        median_score=median_score,
        scores_by_story=scores_by_story,
        stories_by_status=stories_by_status,
    )


def _calculate_median(values: list[int]) -> float:
    """Calculate median of a list of integers."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    n = len(sorted_values)
    if n % 2 == 0:
        return (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2.0
    else:
        return float(sorted_values[n // 2])


@dataclass
class ResearchQualityTrend:
    """Research quality trend for a single iteration."""

    iteration: int
    average_score: float
    story_count: int


def get_research_quality_trend(
    results_tsv: Path,
    iterations: int = 3,
) -> list[ResearchQualityTrend]:
    """Extract research quality trend from last N iterations in results.tsv.

    Args:
        results_tsv: Path to results.tsv.
        iterations: Number of recent iterations to include (default: 3).

    Returns:
        List of ResearchQualityTrend sorted by iteration (oldest first).
    """
    if not results_tsv.exists():
        return []

    # Collect scores per iteration
    scores_by_iter: dict[int, list[int]] = {}
    story_count_by_iter: dict[int, set[str]] = {}

    try:
        with open(results_tsv, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                iter_num_str = row.get("spiral_iter", "")
                story_id = row.get("story_id", "")
                source = row.get("_source", "")  # Custom column if populated

                # Skip if not research-sourced or missing iter
                if not iter_num_str or source != "research":
                    continue

                try:
                    iter_num = int(iter_num_str)
                    retry_num = int(row.get("retry_num", 0) or 0)
                    score = calculate_research_quality_score(retry_num)

                    if iter_num not in scores_by_iter:
                        scores_by_iter[iter_num] = []
                        story_count_by_iter[iter_num] = set()

                    scores_by_iter[iter_num].append(score)
                    story_count_by_iter[iter_num].add(story_id)
                except (ValueError, TypeError):
                    pass
    except (OSError, csv.Error):
        pass

    # Extract last N iterations
    all_iters = sorted(scores_by_iter.keys())
    relevant_iters = all_iters[-iterations:] if all_iters else []

    trends = []
    for iter_num in relevant_iters:
        scores = scores_by_iter[iter_num]
        avg = sum(scores) / len(scores) if scores else 0.0
        trend = ResearchQualityTrend(
            iteration=iter_num,
            average_score=avg,
            story_count=len(story_count_by_iter[iter_num]),
        )
        trends.append(trend)

    return trends


def format_research_quality_report(result: ResearchQualityResult) -> str:
    """Format research quality metrics as human-readable report.

    Args:
        result: ResearchQualityResult from aggregate_research_quality().

    Returns:
        Formatted report string.
    """
    lines = [
        "Research Quality Report",
        "=" * 40,
        f"Total research-sourced stories: {result.total_stories}",
        f"Average quality score: {result.average_score:.1f}/100",
        f"Median quality score: {result.median_score:.1f}/100",
        f"Stories passed: {len(result.stories_by_status['passed'])}",
        f"Stories failed: {len(result.stories_by_status['failed'])}",
    ]

    # Show score distribution
    distribution = _build_score_distribution(result.scores_by_story)
    lines.append("\nScore Distribution:")
    for score_range, count in sorted(distribution.items()):
        lines.append(f"  {score_range}: {count} stories")

    return "\n".join(lines)


def _build_score_distribution(scores_by_story: dict[str, int]) -> dict[str, int]:
    """Build histogram of score ranges."""
    distribution = {
        "90-100": 0,
        "70-89": 0,
        "50-69": 0,
        "30-49": 0,
    }
    for score in scores_by_story.values():
        if score >= 90:
            distribution["90-100"] += 1
        elif score >= 70:
            distribution["70-89"] += 1
        elif score >= 50:
            distribution["50-69"] += 1
        else:
            distribution["30-49"] += 1
    return distribution


# ── Research Result Source Credibility Scoring (US-1407) ──────────────────────


def score_research_result(url: str, snippet_text: str) -> int:
    """Score research result by source credibility (0-100).

    Evaluates domain authority and snippet quality:
    - .edu/.gov/.org/.ac.uk domains: 70-100 (high authority)
    - News outlets (reuters, bbc, nytimes, etc.): 65-85
    - Tech news (techcrunch, arstechnica, theverge): 60-80
    - Academic sources (nature, ieee, acm): 75-95
    - Marketing/ad domains (linkedin, medium.com personal): 20-35
    - Blog/forum spam (reddit, dev.to, pinteres...): 25-40
    - Unknown domains: 45-55 (neutral)

    Args:
        url: Source URL
        snippet_text: Snippet content from the source

    Returns:
        Score 0-100 (higher = more credible)
    """
    from urllib.parse import urlparse

    if not url:
        return 20  # No URL = low credibility

    # Parse domain
    try:
        parsed = urlparse(url.lower())
        domain = parsed.netloc.lower()
    except Exception:
        return 20

    # If URL lacks proper scheme/domain structure, score low
    if not domain or (not domain.count(".") >= 1 and domain != "localhost"):
        return 30

    # Remove common prefixes
    if domain.startswith("www."):
        domain = domain[4:]

    score = 50  # Default neutral

    # ── HIGH AUTHORITY DOMAINS (70+) ──
    if domain.endswith(".edu") or domain.endswith(".gov") or domain.endswith(".mil"):
        score = 85
    elif domain.endswith(".ac.uk") or domain.endswith(".edu.au") or domain.endswith(".org.uk"):
        score = 80
    elif domain.endswith(".org"):
        # Most .org are good, but some are spammy
        if any(x in domain for x in ["spam", "bot", "fake"]):
            score = 30
        else:
            score = 75

    # ── ACADEMIC & RESEARCH (75+) ──
    elif any(x in domain for x in ["nature.com", "sciencedirect.com", "ieee.org", "acm.org"]):
        score = 85
    elif any(x in domain for x in ["arxiv.org", "scholar.google.com", "researchgate.net"]):
        score = 80

    # ── REPUTABLE NEWS (65+) ──
    elif any(
        x in domain
        for x in [
            "reuters.com",
            "apnews.com",
            "bbc.com",
            "bbc.co.uk",
            "nytimes.com",
            "washingtonpost.com",
            "theguardian.com",
            "bloomberg.com",
            "wsj.com",
            "cnbc.com",
        ]
    ):
        score = 75

    # ── TECH MEDIA (60-75) ──
    elif any(x in domain for x in ["techcrunch.com", "arstechnica.com", "wired.com", "theverge.com"]):
        score = 70
    elif any(x in domain for x in ["medium.com", "dev.to"]):
        # Medium and Dev.to: personal blogs, moderate credibility
        score = 40

    # ── LOW CREDIBILITY SPAM (20-40) ──
    elif any(
        x in domain
        for x in [
            "reddit.com",
            "pinterest.com",
            "facebook.com",
            "instagram.com",
            "tiktok.com",
            "quora.com",
            "linkedin.com",
        ]
    ):
        score = 25

    # ── AD/MARKETING DOMAINS (<30) ──
    elif any(x in domain for x in ["ads.", ".ad.", "adserver", "doubleclick.net", "googleads"]):
        score = 15
    elif any(x in url.lower() for x in ["utm_", "clickid=", "affiliate", "promo", "sponsored"]):
        score = 20

    # ── SNIPPET QUALITY ADJUSTMENTS ──
    # Check snippet for red flags with penalty magnitude based on domain authority
    snippet_lower = snippet_text.lower() if snippet_text else ""

    # Determine penalty magnitude based on initial score
    if score >= 70:
        # High-authority sources: small penalties only for severe issues
        short_penalty = 3
        marketing_penalty = 5
    elif score >= 45:
        # Medium-credibility sources: moderate penalties
        short_penalty = 10
        marketing_penalty = 15
    else:
        # Low-credibility sources: larger penalties
        short_penalty = 15
        marketing_penalty = 20

    if len(snippet_text or "") < 20:
        # Very short snippet, probably low quality
        score = max(15, score - short_penalty)

    if any(x in snippet_lower for x in ["click here", "buy now", "limited time", "sponsored"]):
        # Marketing language
        score = max(20, score - marketing_penalty)

    # Error pages always reduce score significantly
    if any(x in snippet_lower for x in ["error", "404", "not found"]):
        score = max(15, score - 40)

    return min(100, max(0, score))


def filter_research_results_by_quality(
    results: dict[str, Any],
    min_score: int = 40,
    log_path: str = ".spiral/research_quality.jsonl",
) -> dict[str, Any]:
    """Filter research results by source credibility score.

    Evaluates each result's source, logs filtering decisions, and returns
    filtered results suitable for synthesis.

    Args:
        results: {"stories": [...]} dict from Phase R
        min_score: Minimum credibility score to keep (default 40)
        log_path: Path to write filtering log (JSONL format)

    Returns:
        Filtered results with same structure, reduced story count
    """
    import json
    from pathlib import Path

    stories = results.get("stories", [])
    filtered_stories = []
    skipped_count = 0

    # Create log entries for skipped results
    log_entries = []

    for story in stories:
        if not isinstance(story, dict):
            continue

        # Extract URL and snippet from story
        # Research results may have different field names, try several
        url = story.get("url") or story.get("source_url") or story.get("link") or ""
        snippet = story.get("snippet") or story.get("content") or story.get("summary") or ""

        score = score_research_result(url, snippet)

        if score < min_score:
            skipped_count += 1
            log_entries.append(
                {
                    "url": url,
                    "score": score,
                    "reason": "credibility_threshold",
                    "threshold": min_score,
                    "snippet_preview": (snippet[:100] + "...") if snippet else "",
                }
            )
        else:
            # Keep this story with score metadata
            story_copy = dict(story)
            story_copy["_quality_score"] = score
            filtered_stories.append(story_copy)

    # Write log entries
    log_path_obj = Path(log_path)
    log_path_obj.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_path_obj, "a", encoding="utf-8") as f:
            for entry in log_entries:
                f.write(json.dumps(entry) + "\n")
    except (OSError, TypeError):
        pass  # Graceful fallback if logging fails

    return {"stories": filtered_stories, "_skipped_count": skipped_count}
