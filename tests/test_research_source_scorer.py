"""Tests for lib/research_source_scorer.py — US-548 research source authority tracking."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from research_source_scorer import extract_sources, score_domain

# ── score_domain tests ────────────────────────────────────────────────────────


class TestScoreDomain:
    def test_gov_domain_scores_high(self) -> None:
        assert score_domain("data.gov") >= 90
        assert score_domain("whitehouse.gov") >= 90
        assert score_domain("privacy.example.gov") >= 90

    def test_edu_domain_scores_high(self) -> None:
        assert score_domain("mit.edu") >= 90
        assert score_domain("stanford.edu") >= 90
        assert score_domain("cs.stanford.edu") >= 90

    def test_mil_domain_scores_high(self) -> None:
        assert score_domain("army.mil") >= 90

    def test_gov_uk_domain_scores_high(self) -> None:
        assert score_domain("service.gov.uk") >= 90

    def test_news_domain_scores_medium_high(self) -> None:
        score = score_domain("reuters.com")
        assert 75 <= score <= 85

    def test_techcrunch_scores_as_news(self) -> None:
        score = score_domain("techcrunch.com")
        assert 75 <= score <= 85

    def test_blog_domain_scores_low(self) -> None:
        score = score_domain("medium.com")
        assert 50 <= score <= 60

    def test_reddit_scores_low(self) -> None:
        score = score_domain("reddit.com")
        assert 50 <= score <= 60

    def test_stackoverflow_scores_low(self) -> None:
        score = score_domain("stackoverflow.com")
        assert 50 <= score <= 60

    def test_unknown_domain_scores_neutral(self) -> None:
        score = score_domain("randomsite.io")
        assert 60 <= score <= 70

    def test_empty_domain_scores_zero(self) -> None:
        assert score_domain("") == 0

    def test_case_insensitive(self) -> None:
        assert score_domain("MIT.EDU") >= 90
        assert score_domain("Reuters.COM") >= 75


# ── extract_sources tests ─────────────────────────────────────────────────────


class TestExtractSources:
    def test_extract_sources_from_sample_output(self) -> None:
        """Extract sources from a research output with story source fields."""
        data = {
            "stories": [
                {
                    "title": "Story A",
                    "source": "https://docs.python.org/3/tutorial/",
                    "description": "A Python tutorial reference",
                },
                {
                    "title": "Story B",
                    "source": "https://nist.gov/cybersecurity",
                    "description": "NIST security guidelines",
                },
            ]
        }
        sources = extract_sources(data)
        assert len(sources) == 2
        # All entries have required fields
        for s in sources:
            assert "url" in s
            assert "domain" in s
            assert "credibility_score" in s
            assert "mention_count" in s
        # .gov should sort first (higher score)
        assert sources[0]["domain"] == "nist.gov"

    def test_extract_sources_from_gemini_format(self) -> None:
        """Extract sources from top-level 'sources' array (Gemini raw)."""
        data = {
            "stories": [],
            "sources": [
                "https://reuters.com/article/123",
                "https://medium.com/blog/post",
            ],
        }
        sources = extract_sources(data)
        assert len(sources) == 2
        domains = {s["domain"] for s in sources}
        assert "reuters.com" in domains
        assert "medium.com" in domains

    def test_extract_urls_from_description(self) -> None:
        """URLs embedded in story descriptions are extracted."""
        data = {
            "stories": [
                {
                    "title": "Story",
                    "source": "",
                    "description": "See https://example.gov/report for details",
                }
            ]
        }
        sources = extract_sources(data)
        assert len(sources) == 1
        assert sources[0]["domain"] == "example.gov"
        assert sources[0]["credibility_score"] >= 90

    def test_extract_urls_from_technical_notes(self) -> None:
        """URLs in technicalNotes are extracted."""
        data = {
            "stories": [
                {
                    "title": "Story",
                    "technicalNotes": ["Refer to https://ieee.org/spec/42"],
                }
            ]
        }
        sources = extract_sources(data)
        assert len(sources) == 1
        assert sources[0]["domain"] == "ieee.org"

    def test_mention_count_aggregation(self) -> None:
        """Same URL in multiple places is aggregated into one entry with correct count."""
        url = "https://docs.python.org/tutorial"
        data = {
            "stories": [
                {"title": "A", "source": url, "description": f"See {url} for more"},
                {"title": "B", "source": url},
            ]
        }
        sources = extract_sources(data)
        # Should be a single entry (same URL)
        assert len(sources) == 1
        # Mentioned as source in 2 stories + once in description = 3
        assert sources[0]["mention_count"] == 3

    def test_empty_research_output(self) -> None:
        """Empty or missing stories returns empty list."""
        assert extract_sources({}) == []
        assert extract_sources({"stories": []}) == []

    def test_sorted_by_credibility_descending(self) -> None:
        """Results are sorted by credibility score descending."""
        data = {
            "stories": [
                {"title": "A", "source": "https://medium.com/post"},
                {"title": "B", "source": "https://nist.gov/report"},
                {"title": "C", "source": "https://reuters.com/article"},
            ]
        }
        sources = extract_sources(data)
        scores = [s["credibility_score"] for s in sources]
        assert scores == sorted(scores, reverse=True)

    def test_non_http_source_ignored(self) -> None:
        """Non-URL source strings are not treated as URLs."""
        data = {
            "stories": [
                {"title": "A", "source": "manual-input"},
            ]
        }
        sources = extract_sources(data)
        assert len(sources) == 0
