"""Tests for lib/story_query.py — filter, group, and export story queries."""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from story_query import (
    format_csv,
    format_json,
    group_by_project,
    query_stories,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

_PRD = {
    "userStories": [
        {"id": "US-1", "title": "Story A", "passes": True, "estimatedComplexity": "small", "model": "haiku"},
        {"id": "US-2", "title": "Story B", "passes": False, "estimatedComplexity": "medium", "model": "sonnet"},
        {"id": "US-3", "title": "Story C", "passes": False, "estimatedComplexity": "small", "model": "haiku"},
        {"id": "UT-1", "title": "Test D", "passes": True, "estimatedComplexity": "large", "model": "opus"},
    ]
}

_TSV_ROWS = [
    "timestamp\tstory_id\tstory_title\tstatus\tmodel\tcache_read_tokens\tcache_creation_tokens\tduration_sec",
    "2026-01-01T00:00:00Z\tUS-2\tStory B\treject\tsonnet\t1000\t200\t60",
    "2026-01-02T00:00:00Z\tUS-3\tStory C\treject\thaiku\t500\t100\t30",
]


def _write_fixtures(tmp: str) -> tuple[str, str]:
    prd_path = os.path.join(tmp, "prd.json")
    tsv_path = os.path.join(tmp, "results.tsv")
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(_PRD, f)
    with open(tsv_path, "w", encoding="utf-8") as f:
        f.write("\n".join(_TSV_ROWS) + "\n")
    return prd_path, tsv_path


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestFilterByStatus:
    def test_filter_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prd, tsv = _write_fixtures(tmp)
            results = query_stories(prd, tsv, {"status": "pass"})
            ids = [r["ID"] for r in results]
            assert "US-1" in ids
            assert "UT-1" in ids
            assert "US-2" not in ids
            assert "US-3" not in ids

    def test_filter_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prd, tsv = _write_fixtures(tmp)
            results = query_stories(prd, tsv, {"status": "fail"})
            ids = [r["ID"] for r in results]
            assert "US-2" in ids
            assert "US-3" in ids
            assert "US-1" not in ids

    def test_filter_complexity_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prd, tsv = _write_fixtures(tmp)
            results = query_stories(prd, tsv, {"status": "fail", "complexity": "medium"})
            ids = [r["ID"] for r in results]
            assert ids == ["US-2"]
            assert results[0]["Last_Failure_Reason"] == "reject"


class TestFilterByProject:
    def test_group_by_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prd, tsv = _write_fixtures(tmp)
            all_stories = query_stories(prd, tsv, {})
            output = group_by_project(all_stories)
            assert "US" in output
            assert "UT" in output

    def test_group_shows_pass_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prd, tsv = _write_fixtures(tmp)
            all_stories = query_stories(prd, tsv, {})
            output = group_by_project(all_stories)
            # US has 3 stories (1 pass) → 33%; UT has 1 story (1 pass) → 100%
            assert "33%" in output
            assert "100%" in output


class TestFormatCsv:
    def test_format_csv_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prd, tsv = _write_fixtures(tmp)
            stories = query_stories(prd, tsv, {"status": "pass"})
            csv_out = format_csv(stories)
            reader = csv.DictReader(io.StringIO(csv_out))
            rows = list(reader)
            assert len(rows) == 2
            assert set(reader.fieldnames or []) >= {
                "ID",
                "Title",
                "Status",
                "Project",
                "Complexity",
                "Tokens",
                "Cost",
                "Model",
                "Last_Failure_Reason",
            }

    def test_format_csv_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prd, tsv = _write_fixtures(tmp)
            stories = query_stories(prd, tsv, {"status": "fail"})
            csv_out = format_csv(stories)
            reader = csv.DictReader(io.StringIO(csv_out))
            rows = list(reader)
            ids = [r["ID"] for r in rows]
            assert "US-2" in ids
            row_us2 = next(r for r in rows if r["ID"] == "US-2")
            assert row_us2["Status"] == "fail"


class TestFormatJson:
    def test_format_json_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prd, tsv = _write_fixtures(tmp)
            stories = query_stories(prd, tsv, {})
            json_out = format_json(stories)
            parsed = json.loads(json_out)
            assert isinstance(parsed, list)
            assert len(parsed) == 4

    def test_format_json_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prd, tsv = _write_fixtures(tmp)
            stories = query_stories(prd, tsv, {"status": "pass"})
            parsed = json.loads(format_json(stories))
            for item in parsed:
                assert "ID" in item
                assert "Title" in item
                assert "Status" in item
                assert item["Status"] == "pass"
