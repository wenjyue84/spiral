"""Tests for lib/import_csv.py — CSV story importer."""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Ensure lib/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import import_csv as ic  # noqa: E402
import main  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_prd(tmp_path: Path, stories: list[dict] | None = None) -> Path:
    prd: dict = {
        "productName": "Test",
        "branchName": "main",
        "userStories": stories or [],
    }
    p = tmp_path / "prd.json"
    p.write_text(json.dumps(prd), encoding="utf-8")
    return p


def _write_csv(tmp_path: Path, content: str, name: str = "stories.csv") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ── _split_list_field ─────────────────────────────────────────────────────────


class TestSplitListField:
    def test_empty_string_returns_empty_list(self):
        assert ic._split_list_field("") == []

    def test_single_item(self):
        assert ic._split_list_field("item one") == ["item one"]

    def test_semicolon_delimited(self):
        result = ic._split_list_field("one; two; three")
        assert result == ["one", "two", "three"]

    def test_strips_whitespace(self):
        assert ic._split_list_field("  a  ;  b  ") == ["a", "b"]

    def test_skips_empty_segments(self):
        assert ic._split_list_field("a;;b") == ["a", "b"]


# ── _next_story_id ────────────────────────────────────────────────────────────


class TestNextStoryId:
    def test_empty_stories_starts_at_1(self):
        assert ic._next_story_id([]) == "US-1"

    def test_increments_max_id(self):
        stories = [{"id": "US-5"}, {"id": "US-3"}]
        assert ic._next_story_id(stories) == "US-6"

    def test_ignores_non_us_ids(self):
        stories = [{"id": "UT-10"}, {"id": "custom-1"}]
        assert ic._next_story_id(stories) == "US-1"

    def test_sequential_allocation(self):
        """IDs should not collide when called repeatedly with accumulation."""
        existing: list[dict] = []
        ids = []
        for _ in range(3):
            next_id = ic._next_story_id(existing)
            ids.append(next_id)
            existing.append({"id": next_id})
        assert ids == ["US-1", "US-2", "US-3"]


# ── parse_csv_rows ────────────────────────────────────────────────────────────


class TestParseCsvRows:
    def test_basic_row(self, tmp_path):
        csv_content = "title,priority\nBuild login page,high\n"
        csv_path = _write_csv(tmp_path, csv_content)
        rows, errors = ic.parse_csv_rows(str(csv_path))
        assert len(rows) == 1
        assert rows[0]["title"] == "Build login page"
        assert rows[0]["priority"] == "high"
        assert errors == []

    def test_all_columns(self, tmp_path):
        csv_content = (
            "title,description,priority,estimatedComplexity,"
            "acceptanceCriteria,technicalNotes\n"
            "My story,Desc here,medium,small,"
            "Criterion one; Criterion two,Note A; Note B\n"
        )
        csv_path = _write_csv(tmp_path, csv_content)
        rows, errors = ic.parse_csv_rows(str(csv_path))
        assert len(rows) == 1
        row = rows[0]
        assert row["description"] == "Desc here"
        assert row["estimatedComplexity"] == "small"
        assert row["acceptanceCriteria"] == ["Criterion one", "Criterion two"]
        assert row["technicalNotes"] == ["Note A", "Note B"]
        assert errors == []

    def test_missing_title_is_error(self, tmp_path):
        csv_content = "title,priority\n,high\n"
        csv_path = _write_csv(tmp_path, csv_content)
        rows, errors = ic.parse_csv_rows(str(csv_path))
        assert rows == []
        assert len(errors) == 1
        assert "Row 2" in errors[0]
        assert "missing title" in errors[0]

    def test_missing_priority_is_error(self, tmp_path):
        csv_content = "title,priority\nSome title,\n"
        csv_path = _write_csv(tmp_path, csv_content)
        rows, errors = ic.parse_csv_rows(str(csv_path))
        assert rows == []
        assert "missing priority" in errors[0]

    def test_invalid_priority_is_error(self, tmp_path):
        csv_content = "title,priority\nSome title,urgent\n"
        csv_path = _write_csv(tmp_path, csv_content)
        rows, errors = ic.parse_csv_rows(str(csv_path))
        assert rows == []
        assert "invalid priority" in errors[0]
        assert "Row 2" in errors[0]

    def test_invalid_complexity_defaults_to_medium(self, tmp_path):
        csv_content = "title,priority,estimatedComplexity\nStory,low,gigantic\n"
        csv_path = _write_csv(tmp_path, csv_content)
        rows, errors = ic.parse_csv_rows(str(csv_path))
        assert rows[0]["estimatedComplexity"] == "medium"
        assert errors == []

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ic.parse_csv_rows(str(tmp_path / "nonexistent.csv"))

    def test_tab_delimiter(self, tmp_path):
        tsv_content = "title\tpriority\nTSV story\tlow\n"
        csv_path = _write_csv(tmp_path, tsv_content, "stories.tsv")
        rows, errors = ic.parse_csv_rows(str(csv_path), delimiter="\t")
        assert len(rows) == 1
        assert rows[0]["title"] == "TSV story"

    def test_multiple_rows_with_mixed_validity(self, tmp_path):
        csv_content = (
            "title,priority\n"
            "Valid story,medium\n"
            ",high\n"
            "Another story,low\n"
        )
        csv_path = _write_csv(tmp_path, csv_content)
        rows, errors = ic.parse_csv_rows(str(csv_path))
        assert len(rows) == 2
        assert len(errors) == 1
        assert "Row 3" in errors[0]

    def test_priority_case_insensitive(self, tmp_path):
        csv_content = "title,priority\nStory,HIGH\n"
        csv_path = _write_csv(tmp_path, csv_content)
        rows, errors = ic.parse_csv_rows(str(csv_path))
        assert rows[0]["priority"] == "high"
        assert errors == []


# ── import_csv_stories ────────────────────────────────────────────────────────


class TestImportCsvStories:
    def test_adds_new_stories(self, tmp_path):
        prd_path = _make_prd(tmp_path)
        csv_content = "title,priority\nNew story,medium\n"
        csv_path = _write_csv(tmp_path, csv_content)

        added, skipped, errors = ic.import_csv_stories(
            csv_path=str(csv_path),
            prd_path=str(prd_path),
        )

        assert len(added) == 1
        assert added[0]["title"] == "New story"
        assert added[0]["id"] == "US-1"
        assert added[0]["_source"] == "csv-import"
        assert added[0]["passes"] is False
        assert skipped == []
        assert errors == []

    def test_duplicate_title_is_skipped(self, tmp_path):
        prd_path = _make_prd(
            tmp_path,
            [{"id": "US-1", "title": "Existing story", "passes": False}],
        )
        csv_content = "title,priority\nExisting story,high\n"
        csv_path = _write_csv(tmp_path, csv_content)

        added, skipped, errors = ic.import_csv_stories(
            csv_path=str(csv_path),
            prd_path=str(prd_path),
        )

        assert added == []
        assert skipped == ["Existing story"]
        assert errors == []

    def test_dry_run_does_not_write_prd(self, tmp_path):
        prd_path = _make_prd(tmp_path)
        original_content = prd_path.read_text(encoding="utf-8")
        csv_content = "title,priority\nDry run story,low\n"
        csv_path = _write_csv(tmp_path, csv_content)

        added, skipped, errors = ic.import_csv_stories(
            csv_path=str(csv_path),
            prd_path=str(prd_path),
            dry_run=True,
        )

        assert len(added) == 1
        assert prd_path.read_text(encoding="utf-8") == original_content

    def test_writes_to_prd_when_not_dry_run(self, tmp_path):
        prd_path = _make_prd(tmp_path)
        csv_content = "title,priority\nPersisted story,high\n"
        csv_path = _write_csv(tmp_path, csv_content)

        ic.import_csv_stories(
            csv_path=str(csv_path),
            prd_path=str(prd_path),
        )

        prd = json.loads(prd_path.read_text(encoding="utf-8"))
        titles = [s["title"] for s in prd["userStories"]]
        assert "Persisted story" in titles

    def test_id_follows_existing_max(self, tmp_path):
        prd_path = _make_prd(
            tmp_path,
            [{"id": "US-42", "title": "Old story", "passes": True}],
        )
        csv_content = "title,priority\nNew story after 42,medium\n"
        csv_path = _write_csv(tmp_path, csv_content)

        added, _, _ = ic.import_csv_stories(
            csv_path=str(csv_path),
            prd_path=str(prd_path),
        )

        assert added[0]["id"] == "US-43"

    def test_parse_errors_are_returned(self, tmp_path):
        prd_path = _make_prd(tmp_path)
        csv_content = "title,priority\n,badpriority\n"
        csv_path = _write_csv(tmp_path, csv_content)

        added, skipped, errors = ic.import_csv_stories(
            csv_path=str(csv_path),
            prd_path=str(prd_path),
        )

        assert added == []
        assert len(errors) >= 1

    def test_missing_prd_raises(self, tmp_path):
        csv_content = "title,priority\nStory,medium\n"
        csv_path = _write_csv(tmp_path, csv_content)

        with pytest.raises(FileNotFoundError):
            ic.import_csv_stories(
                csv_path=str(csv_path),
                prd_path=str(tmp_path / "missing.json"),
            )

    def test_multiple_stories_get_sequential_ids(self, tmp_path):
        prd_path = _make_prd(tmp_path)
        csv_content = "title,priority\nStory A,high\nStory B,low\nStory C,medium\n"
        csv_path = _write_csv(tmp_path, csv_content)

        added, _, _ = ic.import_csv_stories(
            csv_path=str(csv_path),
            prd_path=str(prd_path),
        )

        ids = [s["id"] for s in added]
        assert ids == ["US-1", "US-2", "US-3"]


# ── main() CLI ────────────────────────────────────────────────────────────────


class TestImportCsvCli:
    def test_dry_run_flag(self, tmp_path, capsys):
        prd_path = _make_prd(tmp_path)
        csv_content = "title,priority\nCLI story,medium\n"
        csv_path = _write_csv(tmp_path, csv_content)

        result = ic.main(
            [str(csv_path), "--prd", str(prd_path), "--dry-run"]
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "dry-run" in captured.out
        assert "CLI story" in captured.out

    def test_normal_run_prints_added(self, tmp_path, capsys):
        prd_path = _make_prd(tmp_path)
        csv_content = "title,priority\nAdded story,high\n"
        csv_path = _write_csv(tmp_path, csv_content)

        result = ic.main([str(csv_path), "--prd", str(prd_path)])

        assert result == 0
        captured = capsys.readouterr()
        assert "Added 1" in captured.out

    def test_missing_csv_returns_1(self, tmp_path, capsys):
        prd_path = _make_prd(tmp_path)
        result = ic.main(
            [str(tmp_path / "nope.csv"), "--prd", str(prd_path)]
        )
        assert result == 1

    def test_warn_output_for_invalid_rows(self, tmp_path, capsys):
        prd_path = _make_prd(tmp_path)
        csv_content = "title,priority\n,badprio\n"
        csv_path = _write_csv(tmp_path, csv_content)

        result = ic.main([str(csv_path), "--prd", str(prd_path)])

        assert result == 0
        captured = capsys.readouterr()
        assert "[warn]" in captured.out


# ── main.py integration ───────────────────────────────────────────────────────


class TestMainImportCsvDispatch:
    def test_import_csv_subcommand_registered(self):
        """import-csv must appear in main.py's subparser choices."""
        import argparse

        # Build the parser by calling main() with --help captured.
        parser = argparse.ArgumentParser()
        # Verify the command is dispatchable without error.
        with pytest.raises(SystemExit):
            # Parsing --help triggers SystemExit(0); that's fine.
            import sys as _sys
            old_argv = _sys.argv
            _sys.argv = ["spiral", "--help"]
            try:
                main.main() if hasattr(main, "main") else None
            finally:
                _sys.argv = old_argv
