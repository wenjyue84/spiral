#!/usr/bin/env python3
"""lib/research_source_scorer.py — Score research URLs by domain authority (US-548).

Parses _research_output.json from .spiral/ and scores each research URL by
domain credibility. Returns a sorted list of source entries with credibility
scores (0-100) and mention counts.

Usage (standalone):
    python lib/research_source_scorer.py --input .spiral/_research_output.json

Usage (library):
    from research_source_scorer import extract_sources, score_domain
    sources = extract_sources(research_data)
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Domain credibility tiers
# ---------------------------------------------------------------------------

# High-authority government and education domains
_GOV_EDU_SUFFIXES = (".gov", ".edu", ".mil", ".gov.uk", ".edu.au", ".ac.uk")

# Recognized news/media organizations (partial domain matches)
_NEWS_DOMAINS = frozenset(
    {
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
        "techcrunch.com",
        "arstechnica.com",
        "wired.com",
        "theverge.com",
        "nature.com",
        "sciencedirect.com",
        "ieee.org",
        "acm.org",
    }
)

# Low-credibility blog/forum patterns
_BLOG_FORUM_PATTERNS = (
    "medium.com",
    "dev.to",
    "reddit.com",
    "stackoverflow.com",
    "quora.com",
    "wordpress.com",
    "blogspot.com",
    "tumblr.com",
    "forum",
    "hacker-news",
    "hackernews",
    "producthunt.com",
)


def score_domain(domain: str) -> int:
    """Return a credibility score (0-100) for a given domain.

    Scoring tiers:
      - .gov / .edu / .mil domains: 90-95
      - Recognized news/media: 75-85
      - Known blogs/forums: 50-60
      - Everything else: 65 (neutral default)
    """
    domain = domain.lower().strip()
    if not domain:
        return 0

    # Check gov/edu suffixes
    for suffix in _GOV_EDU_SUFFIXES:
        if domain.endswith(suffix):
            return 95

    # Check recognized news/media
    for news_domain in _NEWS_DOMAINS:
        if domain == news_domain or domain.endswith("." + news_domain):
            return 80

    # Check blog/forum patterns
    for pattern in _BLOG_FORUM_PATTERNS:
        if pattern in domain:
            return 55

    # Neutral default
    return 65


def _extract_domain(url: str) -> str:
    """Extract the domain from a URL string, stripping www. prefix."""
    if not url:
        return ""
    # Ensure URL has a scheme for urlparse
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        domain = parsed.hostname or ""
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def _extract_urls_from_text(text: str) -> list[str]:
    """Find all http/https URLs in a text string."""
    return re.findall(r"https?://[^\s\"'<>\]]+", text)


def extract_sources(research_output: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse research output and extract scored source entries.

    Accepts the full _research_output.json content. Looks for URLs in:
      - story.source fields
      - top-level "sources" list
      - story descriptions and technicalNotes (URL extraction)

    Returns a list sorted by credibility_score descending:
        [{"url": str, "domain": str, "credibility_score": int, "mention_count": int}, ...]
    """
    url_counts: dict[str, int] = {}

    stories = research_output.get("stories", [])
    if isinstance(stories, list):
        for story in stories:
            if not isinstance(story, dict):
                continue

            # source field (often a URL)
            source = story.get("source", "")
            if isinstance(source, str) and source.startswith("http"):
                url_counts[source] = url_counts.get(source, 0) + 1

            # Extract URLs from description
            desc = story.get("description", "")
            if isinstance(desc, str):
                for url in _extract_urls_from_text(desc):
                    url_counts[url] = url_counts.get(url, 0) + 1

            # Extract URLs from technicalNotes
            notes = story.get("technicalNotes", [])
            if isinstance(notes, list):
                for note in notes:
                    if isinstance(note, str):
                        for url in _extract_urls_from_text(note):
                            url_counts[url] = url_counts.get(url, 0) + 1

    # Top-level sources array (Gemini raw format)
    top_sources = research_output.get("sources", [])
    if isinstance(top_sources, list):
        for src in top_sources:
            if isinstance(src, str) and src.startswith("http"):
                url_counts[src] = url_counts.get(src, 0) + 1

    # Build result list
    results: list[dict[str, Any]] = []
    for url, count in url_counts.items():
        domain = _extract_domain(url)
        results.append(
            {
                "url": url,
                "domain": domain,
                "credibility_score": score_domain(domain),
                "mention_count": count,
            }
        )

    # Sort by credibility descending, then by mention count descending
    results.sort(key=lambda r: (-r["credibility_score"], -r["mention_count"]))
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Load _research_output.json and print scored sources."""
    import argparse

    parser = argparse.ArgumentParser(description="Score research source URLs by domain authority")
    parser.add_argument(
        "--input",
        default=os.path.join(".spiral", "_research_output.json"),
        help="Path to _research_output.json",
    )
    args = parser.parse_args()

    try:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error reading {args.input}: {exc}", file=sys.stderr)
        return 1

    sources = extract_sources(data)
    print(json.dumps(sources, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
