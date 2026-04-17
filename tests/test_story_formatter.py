"""tests/test_story_formatter.py — Tests for lib/story_formatter.py."""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.story_formatter import (
    _load_results,
    _load_story,
    format_story_explain,
)

SAMPLE_STORY: dict = {
    "id": "US-1234",
    "title": "Add spiral explain command",
    "description": "Adds spiral explain <story-id> subcommand.",
    "_source": "seed",
    "passes": False,
    "acceptanceCriteria": ["AC one", "AC two"],
    "technicalNotes": ["Note A", "Note B"],
    "filesTouch": ["lib/story_formatter.py"],
    "estimatedComplexity": "small",
}

RESEARCH_STORY: dict = {
    **SAMPLE_STORY,
    "id": "US-9999",
    "_source": "research",
    "research_summary": "Key finding from the web.",
    "research_urls": ["https://github.com/foo/bar", "https://medium.com/baz"],
}


def _write_prd(story: dict) -> str:
    """Write a minimal prd.json with one story, return path."""
    prd = {"userStories": [story]}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(prd, f)
        return f.name


def _write_tsv(story_id: str) -> str:
    """Write a minimal results.tsv with one row, return path."""
    header = "timestamp\tstory_id\tmodel\tcache_read_tokens\tcache_creation_tokens\tstatus\n"
    row = f"2026-04-17T10:00:00Z\t{story_id}\tsonnet\t1000\t500\tpass\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
        f.write(header + row)
        return f.name


class TestFormatTextBasic:
    def test_format_text_basic(self) -> None:
        out = format_story_explain(SAMPLE_STORY, None, "text")
        assert "US-1234" in out
        assert "Add spiral explain command" in out
        assert "[seed]" in out
        assert "AC one" in out
        assert "AC two" in out
        assert "Note A" in out
        assert "lib/story_formatter.py" in out

    def test_format_text_with_results(self) -> None:
        tsv = {"model": "haiku", "cache_read_tokens": "2000", "cache_creation_tokens": "300", "status": "pass"}
        out = format_story_explain(SAMPLE_STORY, tsv, "text")
        assert "haiku" in out
        assert "2,300" in out


class TestFormatMarkdownOutput:
    def test_format_markdown_output(self) -> None:
        out = format_story_explain(SAMPLE_STORY, None, "markdown")
        assert "# US-1234" in out
        assert "## Acceptance Criteria" in out
        assert "1. AC one" in out
        assert "2. AC two" in out
        assert "## Technical Notes" in out
        assert "- Note A" in out
        assert "`lib/story_formatter.py`" in out

    def test_format_markdown_badges(self) -> None:
        out = format_story_explain(SAMPLE_STORY, None, "markdown")
        assert "`[seed]`" in out
        assert "`PENDING`" in out

    def test_format_markdown_passed(self) -> None:
        story = {**SAMPLE_STORY, "passes": True}
        out = format_story_explain(story, None, "markdown")
        assert "`PASSED`" in out


class TestFormatJsonWithResults:
    def test_format_json_with_results(self) -> None:
        tsv = {"model": "sonnet", "cache_read_tokens": "100", "cache_creation_tokens": "50", "status": "pass"}
        out = format_story_explain(SAMPLE_STORY, tsv, "json")
        data = json.loads(out)
        assert data["id"] == "US-1234"
        assert data["_results"]["model"] == "sonnet"

    def test_format_json_without_results(self) -> None:
        out = format_story_explain(SAMPLE_STORY, None, "json")
        data = json.loads(out)
        assert data["id"] == "US-1234"
        assert "_results" not in data


class TestResearchContextFormatting:
    def test_research_context_text(self) -> None:
        out = format_story_explain(RESEARCH_STORY, None, "text")
        assert "Research Context" in out
        assert "Key finding from the web." in out
        assert "github.com" in out
        assert "high" in out
        assert "medium.com" in out
        assert "low" in out

    def test_research_context_markdown(self) -> None:
        out = format_story_explain(RESEARCH_STORY, None, "markdown")
        assert "## Research Context" in out
        assert "github.com" in out
        assert "credibility" in out

    def test_no_research_section_for_seed(self) -> None:
        out = format_story_explain(SAMPLE_STORY, None, "text")
        assert "Research Context" not in out


class TestLoadHelpers:
    def test_load_story_found(self) -> None:
        prd_path = _write_prd(SAMPLE_STORY)
        try:
            story = _load_story(prd_path, "US-1234")
            assert story is not None
            assert story["id"] == "US-1234"
        finally:
            os.unlink(prd_path)

    def test_load_story_not_found(self) -> None:
        prd_path = _write_prd(SAMPLE_STORY)
        try:
            story = _load_story(prd_path, "US-9999")
            assert story is None
        finally:
            os.unlink(prd_path)

    def test_load_results_latest_row(self) -> None:
        tsv_path = _write_tsv("US-1234")
        try:
            rows = _load_results(tsv_path)
            assert "US-1234" in rows
            assert rows["US-1234"]["model"] == "sonnet"
        finally:
            os.unlink(tsv_path)

    def test_load_results_missing_file(self) -> None:
        rows = _load_results("/nonexistent/path/results.tsv")
        assert rows == {}
