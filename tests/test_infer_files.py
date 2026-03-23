"""Tests for lib/prd/infer_files_to_touch.py — static analysis file inference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lib.prd.infer_files_to_touch import (
    build_symbol_to_files,
    enrich_prd,
    extract_file_refs,
    extract_symbol_refs,
    extract_text_fields,
    infer_files,
    resolve_file_refs,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Create a minimal repo layout."""
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "prd").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "lib" / "foo.py").write_text("def do_work(): pass\n", encoding="utf-8")
    (tmp_path / "lib" / "bar.sh").write_text("#!/bin/bash\necho hello\n", encoding="utf-8")
    (tmp_path / "lib" / "prd" / "merge.py").write_text("def merge(): pass\n", encoding="utf-8")
    (tmp_path / "tests" / "test_foo.py").write_text("def test_it(): pass\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# extract_text_fields
# ---------------------------------------------------------------------------


class TestExtractTextFields:
    def test_basic_fields(self) -> None:
        story: dict[str, Any] = {
            "id": "US-100",
            "title": "Add new endpoint",
            "description": "Create a REST endpoint in lib/foo.py",
            "acceptanceCriteria": ["Endpoint returns 200", "Tests pass in tests/test_foo.py"],
        }
        text = extract_text_fields(story)
        assert "Add new endpoint" in text
        assert "lib/foo.py" in text
        assert "tests/test_foo.py" in text

    def test_with_technical_hints(self) -> None:
        story: dict[str, Any] = {
            "id": "US-101",
            "title": "Fix bug",
            "technicalHints": {"approach": "Modify lib/bar.sh to fix the issue"},
        }
        text = extract_text_fields(story)
        assert "lib/bar.sh" in text

    def test_empty_story(self) -> None:
        text = extract_text_fields({"id": "US-102"})
        assert text.strip() == ""


# ---------------------------------------------------------------------------
# extract_file_refs
# ---------------------------------------------------------------------------


class TestExtractFileRefs:
    def test_python_files(self) -> None:
        refs = extract_file_refs("Modify lib/foo.py and tests/test_foo.py")
        assert "lib/foo.py" in refs
        assert "tests/test_foo.py" in refs

    def test_shell_files(self) -> None:
        refs = extract_file_refs("Update spiral.sh and lib/phases/merge.sh")
        assert "spiral.sh" in refs
        assert "lib/phases/merge.sh" in refs

    def test_ts_tsx_files(self) -> None:
        refs = extract_file_refs("Edit src/App.tsx and src/utils/api.ts")
        assert "src/App.tsx" in refs
        assert "src/utils/api.ts" in refs

    def test_json_files(self) -> None:
        refs = extract_file_refs("Schema in prd.schema.json")
        assert "prd.schema.json" in refs

    def test_no_false_positives_on_urls(self) -> None:
        # Should not match URLs or version numbers
        refs = extract_file_refs("See https://example.com for v2.3.4 details")
        # URLs and version numbers should not be extracted as file refs
        for ref in refs:
            assert not ref.startswith("http")


# ---------------------------------------------------------------------------
# extract_symbol_refs
# ---------------------------------------------------------------------------


class TestExtractSymbolRefs:
    def test_pascal_case(self) -> None:
        symbols = extract_symbol_refs("Update the StoryMap class")
        assert "StoryMap" in symbols

    def test_function_calls(self) -> None:
        symbols = extract_symbol_refs("Call do_work() and merge_stories()")
        assert "do_work" in symbols
        assert "merge_stories" in symbols


# ---------------------------------------------------------------------------
# resolve_file_refs
# ---------------------------------------------------------------------------


class TestResolveFileRefs:
    def test_exact_match(self) -> None:
        repo_files = {"lib/foo.py", "lib/bar.sh", "tests/test_foo.py"}
        resolved = resolve_file_refs({"lib/foo.py"}, repo_files)
        assert "lib/foo.py" in resolved

    def test_basename_match(self) -> None:
        repo_files = {"lib/foo.py", "lib/bar.sh"}
        resolved = resolve_file_refs({"foo.py"}, repo_files)
        assert "lib/foo.py" in resolved

    def test_ambiguous_basename_prefers_suffix(self) -> None:
        repo_files = {"lib/foo.py", "other/foo.py"}
        resolved = resolve_file_refs({"lib/foo.py"}, repo_files)
        assert "lib/foo.py" in resolved

    def test_no_match(self) -> None:
        repo_files = {"lib/foo.py"}
        resolved = resolve_file_refs({"nonexistent.py"}, repo_files)
        assert len(resolved) == 0


# ---------------------------------------------------------------------------
# build_symbol_to_files
# ---------------------------------------------------------------------------


class TestBuildSymbolToFiles:
    def test_basic_index(self) -> None:
        repo_map: dict[str, Any] = {
            "US-100": {
                "files": {
                    "lib/foo.py": {
                        "functions": ["do_work", "process"],
                        "classes": ["Worker"],
                        "exports": ["do_work", "Worker"],
                        "variables": [],
                    }
                }
            }
        }
        index = build_symbol_to_files(repo_map)
        assert "do_work" in index
        assert "lib/foo.py" in index["do_work"]
        assert "Worker" in index
        assert "lib/foo.py" in index["Worker"]


# ---------------------------------------------------------------------------
# infer_files
# ---------------------------------------------------------------------------


class TestInferFiles:
    def test_infers_from_text(self, repo: Path) -> None:
        story: dict[str, Any] = {
            "id": "US-100",
            "title": "Fix bug in lib/foo.py",
            "description": "Also update tests/test_foo.py",
        }
        result = infer_files(story, repo_root=str(repo))
        assert "lib/foo.py" in result
        assert "tests/test_foo.py" in result

    def test_infers_from_repo_map_symbols(self, repo: Path) -> None:
        repo_map: dict[str, Any] = {
            "US-100": {
                "files": {
                    "lib/foo.py": {
                        "functions": ["do_work"],
                        "classes": [],
                        "exports": ["do_work"],
                        "variables": [],
                    }
                }
            }
        }
        story: dict[str, Any] = {
            "id": "US-100",
            "title": "Refactor do_work() function",
        }
        result = infer_files(story, repo_map=repo_map, repo_root=str(repo))
        assert "lib/foo.py" in result

    def test_empty_story_returns_empty(self, repo: Path) -> None:
        result = infer_files({"id": "US-100"}, repo_root=str(repo))
        assert result == set()


# ---------------------------------------------------------------------------
# enrich_prd
# ---------------------------------------------------------------------------


class TestEnrichPrd:
    def test_enriches_pending_stories(self, repo: Path) -> None:
        prd: dict[str, Any] = {
            "goal": "Test",
            "userStories": [
                {"id": "US-100", "title": "Fix lib/foo.py bug", "passes": False, "dependencies": []},
                {"id": "US-101", "title": "Done story", "passes": True, "dependencies": []},
            ],
        }
        prd_path = str(repo / "prd.json")
        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump(prd, f)

        enriched = enrich_prd(prd_path, repo_root=str(repo))
        assert "US-100" in enriched
        assert "lib/foo.py" in enriched["US-100"]
        # Passed story should not be enriched
        assert "US-101" not in enriched

        # Verify prd.json was modified
        with open(prd_path, encoding="utf-8") as f:
            updated = json.load(f)
        us100 = next(s for s in updated["userStories"] if s["id"] == "US-100")
        assert "lib/foo.py" in us100["filesTouch"]
        assert "lib/foo.py" in us100["_inferredFiles"]

    def test_dry_run_doesnt_modify(self, repo: Path) -> None:
        prd: dict[str, Any] = {
            "goal": "Test",
            "userStories": [
                {"id": "US-100", "title": "Fix lib/foo.py bug", "passes": False, "dependencies": []},
            ],
        }
        prd_path = str(repo / "prd.json")
        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump(prd, f)

        enriched = enrich_prd(prd_path, repo_root=str(repo), dry_run=True)
        assert "US-100" in enriched

        # prd.json should NOT be modified
        with open(prd_path, encoding="utf-8") as f:
            original = json.load(f)
        us100 = next(s for s in original["userStories"] if s["id"] == "US-100")
        assert "filesTouch" not in us100 or us100.get("filesTouch") == []

    def test_no_duplicates_with_existing_files(self, repo: Path) -> None:
        prd: dict[str, Any] = {
            "goal": "Test",
            "userStories": [
                {
                    "id": "US-100",
                    "title": "Fix lib/foo.py bug",
                    "filesTouch": ["lib/foo.py"],
                    "passes": False,
                    "dependencies": [],
                },
            ],
        }
        prd_path = str(repo / "prd.json")
        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump(prd, f)

        enriched = enrich_prd(prd_path, repo_root=str(repo))
        # lib/foo.py already exists in filesTouch, so should not appear in enriched
        if "US-100" in enriched:
            assert "lib/foo.py" not in enriched["US-100"]
