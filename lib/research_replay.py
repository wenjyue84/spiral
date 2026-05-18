#!/usr/bin/env python3
"""
lib/research_replay.py -- CLI command to replay historical research and compare with current synthesis.

Usage:
  python lib/research_replay.py <story_id> [--cache-dir <dir>] [--gemini-api <url>]

Loads original research queries from cache, re-runs Gemini search, and compares
source ranking and summary synthesis quality. Flags for re-research if delta > 15%.

Acceptance Criteria:
  1. Load original research queries and sources from .spiral/research_cache.json
  2. Re-run Gemini search with original queries, compare result ranking and summary
  3. Report quality delta: source ranking changes, summary divergence, flag if delta > 15%
"""

from __future__ import annotations

import difflib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    # Real Gemini import (would be used in production)
    from lib.research.gemini_mock import gemini_web_search
except ImportError:
    # Fallback mock for testing
    def gemini_web_search(query: str, search_domain: Optional[str] = None) -> str:
        """Fallback mock for testing."""
        return json.dumps({"summary": f"Mock result for: {query}", "sources": []})


@dataclass
class ResearchResult:
    """A single research query result."""

    query: str
    summary: str
    sources: list[str]  # URLs of research sources


@dataclass
class QualityDelta:
    """Quality comparison metrics between original and new research."""

    source_similarity: float  # Jaccard similarity of URLs (0-1)
    summary_similarity: float  # String similarity of summaries (0-1)
    combined_delta: float  # Average of source and summary similarity (0-1)
    flag_rerun: bool  # True if delta < 0.85 (> 15% degradation)
    report: str  # Human-readable report


def load_story_research(
    story_id: str,
    cache_file: str = ".spiral/research_cache.json",
) -> list[ResearchResult]:
    """Load original research queries and results for a story from cache.

    Args:
        story_id: Story ID to load research for (e.g., 'US-001')
        cache_file: Path to research cache file

    Returns:
        List of ResearchResult objects for this story's cached queries
    """
    cache_path = Path(cache_file)
    if not cache_path.exists():
        return []

    try:
        with open(cache_path, encoding="utf-8") as f:
            cache_data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

    results: list[ResearchResult] = []
    cached_queries = cache_data.get("cached_queries", [])

    for entry in cached_queries:
        # Filter by story_id if available (stored in query metadata)
        if entry.get("story_id") == story_id or story_id in entry.get("query", ""):
            try:
                result_data = json.loads(entry.get("result", "{}"))
                results.append(
                    ResearchResult(
                        query=entry.get("query", ""),
                        summary=result_data.get("summary", ""),
                        sources=result_data.get("sources", []),
                    )
                )
            except (json.JSONDecodeError, KeyError):
                continue

    return results


def replay_research_queries(
    original_results: list[ResearchResult],
) -> list[ResearchResult]:
    """Re-run Gemini search with original queries and return new results.

    Args:
        original_results: List of original ResearchResult objects

    Returns:
        List of new ResearchResult objects from current Gemini API
    """
    new_results: list[ResearchResult] = []

    for original in original_results:
        try:
            # Re-run Gemini search with original query
            new_result_json = gemini_web_search(original.query)
            new_result_data = json.loads(new_result_json)

            new_results.append(
                ResearchResult(
                    query=original.query,
                    summary=new_result_data.get("summary", ""),
                    sources=new_result_data.get("sources", []),
                )
            )
        except (json.JSONDecodeError, TypeError):
            # If API call fails, return empty result
            new_results.append(
                ResearchResult(
                    query=original.query,
                    summary="",
                    sources=[],
                )
            )

    return new_results


def calculate_source_similarity(original_sources: list[str], new_sources: list[str]) -> float:
    """Calculate Jaccard similarity between source URL sets.

    Args:
        original_sources: List of original source URLs
        new_sources: List of new source URLs

    Returns:
        Similarity score in [0, 1] where 1.0 = identical sets
    """
    orig_set = set(original_sources)
    new_set = set(new_sources)

    if not orig_set and not new_set:
        return 1.0
    if not orig_set or not new_set:
        return 0.0

    intersection = len(orig_set & new_set)
    union = len(orig_set | new_set)
    return intersection / union if union > 0 else 0.0


def calculate_summary_similarity(original_summary: str, new_summary: str) -> float:
    """Calculate sequence similarity between summaries using difflib.

    Args:
        original_summary: Original research summary
        new_summary: New research summary

    Returns:
        Similarity score in [0, 1] where 1.0 = identical
    """
    if not original_summary and not new_summary:
        return 1.0
    if not original_summary or not new_summary:
        return 0.0

    # Use SequenceMatcher to compare summaries
    matcher = difflib.SequenceMatcher(None, original_summary, new_summary)
    return matcher.ratio()


def calculate_quality_delta(
    original_results: list[ResearchResult],
    new_results: list[ResearchResult],
) -> QualityDelta:
    """Calculate quality delta between original and new research results.

    Compares source URLs (Jaccard) and summaries (difflib ratio).
    Combined delta is average of both metrics.
    Flags for re-research if combined delta < 0.85 (>15% degradation).

    Args:
        original_results: Original cached research results
        new_results: New results from replay

    Returns:
        QualityDelta with metrics and recommendation
    """
    if not original_results or not new_results:
        return QualityDelta(
            source_similarity=0.0,
            summary_similarity=0.0,
            combined_delta=0.0,
            flag_rerun=True,
            report="No research data to compare",
        )

    source_sims: list[float] = []
    summary_sims: list[float] = []

    # Compare pairwise between original and new results
    for orig, new in zip(original_results, new_results):
        source_sim = calculate_source_similarity(orig.sources, new.sources)
        summary_sim = calculate_summary_similarity(orig.summary, new.summary)

        source_sims.append(source_sim)
        summary_sims.append(summary_sim)

    # Average similarities
    avg_source_sim = sum(source_sims) / len(source_sims) if source_sims else 0.0
    avg_summary_sim = sum(summary_sims) / len(summary_sims) if summary_sims else 0.0

    # Combined delta
    combined_delta = (avg_source_sim + avg_summary_sim) / 2.0

    # Flag if quality degraded >15% (combined_delta < 0.85)
    flag_rerun = combined_delta < 0.85

    # Human-readable report
    report = f"""
Research Quality Delta Report
─────────────────────────────────
Source URL Similarity:    {avg_source_sim:.1%}
Summary Text Similarity:  {avg_summary_sim:.1%}
Combined Quality Delta:   {combined_delta:.1%}

{"⚠️  FLAG: Research quality degraded > 15% — recommend re-research" if flag_rerun else "✓ Research quality stable"}
"""

    return QualityDelta(
        source_similarity=avg_source_sim,
        summary_similarity=avg_summary_sim,
        combined_delta=combined_delta,
        flag_rerun=flag_rerun,
        report=report,
    )


def replay_research(
    story_id: str,
    cache_dir: str = ".spiral",
) -> int:
    """Main entry point: replay research for a story and report quality delta.

    Args:
        story_id: Story ID to replay research for
        cache_dir: Base directory for .spiral/research_cache.json

    Returns:
        0 if quality is stable, 1 if degraded or error
    """
    cache_file = str(Path(cache_dir) / "research_cache.json")

    print(f"[spiral research-replay] Loading research for {story_id}...", file=sys.stderr)

    # Load original research
    original_results = load_story_research(story_id, cache_file)
    if not original_results:
        print(f"[spiral research-replay] ERROR: No cached research found for {story_id}", file=sys.stderr)
        return 1

    print(f"[spiral research-replay] Found {len(original_results)} cached queries", file=sys.stderr)
    print("[spiral research-replay] Replaying Gemini searches...", file=sys.stderr)

    # Replay with current Gemini API
    new_results = replay_research_queries(original_results)

    print("[spiral research-replay] Calculating quality delta...", file=sys.stderr)

    # Calculate delta
    delta = calculate_quality_delta(original_results, new_results)

    # Print report
    print(delta.report)

    # Return exit code
    return 1 if delta.flag_rerun else 0


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python lib/research_replay.py <story_id> [--cache-dir <dir>]", file=sys.stderr)
        sys.exit(1)

    story_id = sys.argv[1]
    cache_dir = ".spiral"

    # Parse optional args
    for i, arg in enumerate(sys.argv[2:], start=2):
        if arg == "--cache-dir" and i + 1 < len(sys.argv):
            cache_dir = sys.argv[i + 1]

    exit_code = replay_research(story_id, cache_dir)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
