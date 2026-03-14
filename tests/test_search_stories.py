"""Tests for lib/search_stories.py — spiral search subcommand."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import main  # noqa: E402
from search_stories import search_stories, format_table  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_STORIES = [
    {
        "id": "US-001",
        "title": "Wire validate_preflight into spiral.sh",
        "description": "Validate environment before running the loop.",
        "acceptanceCriteria": ["spiral exits on missing jq"],
        "passes": True,
    },
    {
        "id": "US-010",
        "title": "Add rate-limit retry with exponential backoff",
        "description": "Retry API calls when rate limited.",
        "acceptanceCriteria": ["Retries up to 5 times", "Uses exponential backoff"],
        "passes": False,
    },
    {
        "id": "US-020",
        "title": "Emit SARIF 2.1.0 report from static analysis",
        "description": "Generate a SARIF report after linting passes.",
        "acceptanceCriteria": ["SARIF file written to .spiral/sarif.json"],
        "passes": True,
    },
    {
        "id": "US-030",
        "title": "Add dashboard API cost widget",
        "description": "Show cumulative API costs in the spiral dashboard.",
        "acceptanceCriteria": ["Widget shows total USD spent"],
        "passes": False,
    },
    {
        "id": "US-040",
        "title": "Memory pressure watchdog for OOM prevention",
        "description": "Kill workers when memory exceeds threshold.",
        "acceptanceCriteria": ["Workers killed at 90% RAM"],
        "passes": False,
    },
    {
        "id": "US-050",
        "title": "Git tag on successful run completion",
        "description": "Create an annotated tag after all stories pass.",
        "acceptanceCriteria": ["Tag follows spiral/run-<id>-complete pattern"],
        "passes": True,
    },
]


def _make_prd(tmp_path: Path, stories=None) -> Path:
    prd = {"productName": "Test", "branchName": "main", "userStories": stories if stories is not None else SAMPLE_STORIES}
    p = tmp_path / "prd.json"
    p.write_text(json.dumps(prd, indent=2), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Unit tests — search_stories()
# ---------------------------------------------------------------------------


class TestSearchStoriesFuzzy:
    def test_returns_top5_by_default(self, tmp_path):
        prd = _make_prd(tmp_path)
        results = search_stories(prd, "rate limit retry", force_fuzzy=True)
        assert len(results) <= 5
        assert len(results) > 0

    def test_most_relevant_first(self, tmp_path):
        prd = _make_prd(tmp_path)
        results = search_stories(prd, "rate limit retry", force_fuzzy=True)
        # US-010 should score highest
        assert results[0]["id"] == "US-010"

    def test_search_covers_acceptance_criteria(self, tmp_path):
        prd = _make_prd(tmp_path)
        results = search_stories(prd, "exponential backoff", force_fuzzy=True)
        ids = [r["id"] for r in results]
        assert "US-010" in ids

    def test_result_keys_present(self, tmp_path):
        prd = _make_prd(tmp_path)
        results = search_stories(prd, "dashboard", force_fuzzy=True)
        for r in results:
            assert "id" in r
            assert "title" in r
            assert "status" in r
            assert "score" in r
            assert "engine" in r

    def test_status_reflects_passes_flag(self, tmp_path):
        prd = _make_prd(tmp_path)
        results = search_stories(prd, "preflight validation", force_fuzzy=True)
        by_id = {r["id"]: r for r in results}
        if "US-001" in by_id:
            assert by_id["US-001"]["status"] == "passed"

    def test_top_k_respected(self, tmp_path):
        prd = _make_prd(tmp_path)
        results = search_stories(prd, "spiral", top_k=2, force_fuzzy=True)
        assert len(results) <= 2

    def test_engine_is_fuzzy(self, tmp_path):
        prd = _make_prd(tmp_path)
        results = search_stories(prd, "memory", force_fuzzy=True)
        for r in results:
            assert r["engine"] == "fuzzy"

    def test_missing_prd_returns_empty(self, tmp_path):
        results = search_stories(tmp_path / "nonexistent.json", "anything", force_fuzzy=True)
        assert results == []

    def test_empty_stories_returns_empty(self, tmp_path):
        prd = _make_prd(tmp_path, stories=[])
        results = search_stories(prd, "anything", force_fuzzy=True)
        assert results == []

    def test_no_results_does_not_raise(self, tmp_path):
        prd = _make_prd(tmp_path)
        # Highly unusual query — should return top matches (not crash)
        results = search_stories(prd, "xyzzy frobnicate quux", force_fuzzy=True)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Unit tests — format_table()
# ---------------------------------------------------------------------------


class TestFormatTable:
    def test_no_results_message(self):
        output = format_table([])
        assert "No matching stories found" in output

    def test_table_contains_id(self):
        rows = [{"id": "US-010", "title": "Rate limit retry", "status": "pending", "score": 0.95, "engine": "fuzzy"}]
        output = format_table(rows)
        assert "US-010" in output

    def test_table_contains_status(self):
        rows = [{"id": "US-001", "title": "Preflight", "status": "passed", "score": 0.80, "engine": "fuzzy"}]
        output = format_table(rows)
        assert "passed" in output

    def test_long_title_truncated(self):
        long_title = "A" * 80
        rows = [{"id": "US-999", "title": long_title, "status": "pending", "score": 0.5, "engine": "fuzzy"}]
        output = format_table(rows)
        assert "..." in output


# ---------------------------------------------------------------------------
# Integration tests — cmd_search() via main.py
# ---------------------------------------------------------------------------


class TestCmdSearchCli:
    def _run_search(self, tmp_path, query, extra_args=None, stories=None):
        """Call cmd_search with patched PRD_FILE and capture stdout."""
        prd_path = _make_prd(tmp_path, stories)
        scratch = tmp_path / ".spiral"
        scratch.mkdir(exist_ok=True)

        ns = SimpleNamespace(
            query=query,
            top=5,
            json=False,
            fuzzy=True,
        )
        if extra_args:
            for k, v in extra_args.items():
                setattr(ns, k, v)

        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "SCRATCH_DIR", scratch):
            with pytest.raises(SystemExit) as exc_info:
                main.cmd_search(ns)
        return exc_info.value.code

    def test_exits_zero_on_results(self, tmp_path, capsys):
        rc = self._run_search(tmp_path, "rate limit retry")
        assert rc == 0

    def test_exits_zero_on_no_results(self, tmp_path, capsys):
        rc = self._run_search(tmp_path, "xyzzy frobnicate", stories=[])
        assert rc == 0

    def test_json_flag_outputs_valid_json(self, tmp_path, capsys):
        prd_path = _make_prd(tmp_path)
        scratch = tmp_path / ".spiral"
        scratch.mkdir(exist_ok=True)

        ns = SimpleNamespace(query="rate limit", top=5, json=True, fuzzy=True)
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "SCRATCH_DIR", scratch):
            with pytest.raises(SystemExit):
                main.cmd_search(ns)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)

    def test_top5_results_contain_id_title_status_score(self, tmp_path, capsys):
        prd_path = _make_prd(tmp_path)
        scratch = tmp_path / ".spiral"
        scratch.mkdir(exist_ok=True)

        ns = SimpleNamespace(query="rate limit retry", top=5, json=True, fuzzy=True)
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "SCRATCH_DIR", scratch):
            with pytest.raises(SystemExit):
                main.cmd_search(ns)
        captured = capsys.readouterr()
        results = json.loads(captured.out)
        assert len(results) >= 1
        for r in results:
            assert "id" in r
            assert "title" in r
            assert "status" in r
            assert "score" in r
