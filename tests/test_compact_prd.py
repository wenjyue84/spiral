"""Unit tests for lib/compact_prd.py — field stripping and schema safety."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from compact_prd import compact_prd, TRANSIENT_FIELDS, REQUIRED_FIELDS, _story_is_compactable


# ── _story_is_compactable ────────────────────────────────────────────────────


class TestStoryIsCompactable:
    def test_passes_true_is_eligible(self):
        assert _story_is_compactable({"passes": True}) is True

    def test_passes_false_is_not_eligible(self):
        assert _story_is_compactable({"passes": False}) is False

    def test_status_passed_is_eligible(self):
        assert _story_is_compactable({"status": "passed"}) is True

    def test_status_skipped_is_eligible(self):
        assert _story_is_compactable({"status": "skipped"}) is True

    def test_status_pending_not_eligible(self):
        assert _story_is_compactable({"status": "pending"}) is False

    def test_no_status_no_passes_not_eligible(self):
        assert _story_is_compactable({"id": "US-1", "title": "foo"}) is False


# ── compact_prd — core logic ─────────────────────────────────────────────────


def _make_prd(tmp_path, stories):
    p = tmp_path / "prd.json"
    p.write_text(json.dumps({"userStories": stories}, indent=2), encoding="utf-8")
    return str(p)


class TestCompactPrdTransientRemoval:
    def test_removes_transient_from_passed_story(self, tmp_path):
        stories = [
            {
                "id": "US-1",
                "title": "First story",
                "passes": True,
                "_lastAttempt": "2025-01-01",
                "_workerPid": 1234,
                "_researchOutput": "lots of text",
                "_routerScore": 0.9,
                "_lastResearchAttempt": "2025-01-01",
            }
        ]
        prd_path = _make_prd(tmp_path, stories)
        result = compact_prd(prd_path, backup_dir=str(tmp_path / ".spiral"))

        assert result["stories_compacted"] == 1
        assert result["fields_removed"] == 5

        with open(prd_path, encoding="utf-8") as f:
            updated = json.load(f)
        story = updated["userStories"][0]
        for field in TRANSIENT_FIELDS:
            assert field not in story, f"{field} should have been removed"

    def test_keeps_required_fields(self, tmp_path):
        stories = [
            {
                "id": "US-2",
                "title": "Story two",
                "passes": True,
                "_lastAttempt": "2025-01-01",
            }
        ]
        prd_path = _make_prd(tmp_path, stories)
        compact_prd(prd_path, backup_dir=str(tmp_path / ".spiral"))

        with open(prd_path, encoding="utf-8") as f:
            updated = json.load(f)
        story = updated["userStories"][0]
        for field in REQUIRED_FIELDS:
            assert field in story, f"Required field {field} must not be removed"

    def test_skips_incomplete_story(self, tmp_path):
        stories = [
            {
                "id": "US-3",
                "title": "Incomplete story",
                "passes": False,
                "_lastAttempt": "2025-01-01",
            }
        ]
        prd_path = _make_prd(tmp_path, stories)
        result = compact_prd(prd_path, backup_dir=str(tmp_path / ".spiral"))

        assert result["stories_compacted"] == 0
        assert result["fields_removed"] == 0

        with open(prd_path, encoding="utf-8") as f:
            updated = json.load(f)
        # Field should still be there
        assert "_lastAttempt" in updated["userStories"][0]

    def test_nothing_to_compact_returns_zeros(self, tmp_path):
        stories = [{"id": "US-4", "title": "Clean story", "passes": True}]
        prd_path = _make_prd(tmp_path, stories)
        result = compact_prd(prd_path, backup_dir=str(tmp_path / ".spiral"))

        assert result["stories_compacted"] == 0
        assert result["fields_removed"] == 0
        assert result["backup_path"] is None

    def test_backup_created_when_changes_made(self, tmp_path):
        stories = [
            {"id": "US-5", "title": "Story", "passes": True, "_lastAttempt": "x"}
        ]
        prd_path = _make_prd(tmp_path, stories)
        backup_dir = str(tmp_path / ".spiral")
        result = compact_prd(prd_path, backup_dir=backup_dir)

        assert result["backup_path"] is not None
        assert os.path.exists(result["backup_path"])
        # Backup should contain the original transient field
        with open(result["backup_path"], encoding="utf-8") as f:
            backup = json.load(f)
        assert "_lastAttempt" in backup["userStories"][0]

    def test_no_backup_when_nothing_compacted(self, tmp_path):
        stories = [{"id": "US-6", "title": "Clean", "passes": True}]
        prd_path = _make_prd(tmp_path, stories)
        result = compact_prd(prd_path, backup_dir=str(tmp_path / ".spiral"))
        assert result["backup_path"] is None

    def test_dry_run_does_not_modify_file(self, tmp_path):
        stories = [
            {"id": "US-7", "title": "Story", "passes": True, "_lastAttempt": "x"}
        ]
        prd_path = _make_prd(tmp_path, stories)
        original = open(prd_path, encoding="utf-8").read()

        result = compact_prd(prd_path, backup_dir=str(tmp_path / ".spiral"), dry_run=True)

        assert result["stories_compacted"] == 1
        assert result["fields_removed"] == 1
        assert result["backup_path"] is None
        # File unchanged
        assert open(prd_path, encoding="utf-8").read() == original

    def test_mixed_stories(self, tmp_path):
        stories = [
            {"id": "US-8", "title": "Done", "passes": True, "_lastAttempt": "x"},
            {"id": "US-9", "title": "Pending", "passes": False, "_lastAttempt": "y"},
        ]
        prd_path = _make_prd(tmp_path, stories)
        result = compact_prd(prd_path, backup_dir=str(tmp_path / ".spiral"))

        assert result["stories_compacted"] == 1
        assert result["fields_removed"] == 1

        with open(prd_path, encoding="utf-8") as f:
            updated = json.load(f)
        # US-8 should be clean
        assert "_lastAttempt" not in updated["userStories"][0]
        # US-9 should retain its transient field
        assert "_lastAttempt" in updated["userStories"][1]

    def test_status_skipped_also_compacted(self, tmp_path):
        stories = [
            {"id": "US-10", "title": "Skipped", "status": "skipped", "_routerScore": 0.5}
        ]
        prd_path = _make_prd(tmp_path, stories)
        result = compact_prd(prd_path, backup_dir=str(tmp_path / ".spiral"))
        assert result["fields_removed"] == 1
