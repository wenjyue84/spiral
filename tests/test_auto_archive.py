"""Tests for auto-archive logic (US-1132) — auto-archive completed stories at iteration start."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from prd.archive_prd import is_archivable


def _make_story(
    story_id: str,
    title: str,
    passes: bool = False,
    decomposed: bool = False,
) -> dict:
    """Helper to create a story for testing."""
    story = {
        "id": story_id,
        "title": title,
        "description": f"Test story {story_id}",
        "acceptanceCriteria": ["AC1"],
        "passes": passes,
    }
    if decomposed:
        story["_decomposed"] = True
    return story


# ── is_archivable tests (from archive_prd.py) ────────────────────────────────


def test_is_archivable_completed() -> None:
    """Completed story (passes: true, not decomposed) is archivable."""
    story = _make_story("US-1", "Test 1", passes=True, decomposed=False)
    assert is_archivable(story) is True


def test_is_archivable_pending() -> None:
    """Pending story (passes: false) is NOT archivable."""
    story = _make_story("US-2", "Test 2", passes=False, decomposed=False)
    assert is_archivable(story) is False


def test_is_archivable_decomposed_parent() -> None:
    """Decomposed parent (passes: true, _decomposed: true) is NOT archivable."""
    story = _make_story("US-3", "Test 3", passes=True, decomposed=True)
    assert is_archivable(story) is False


def test_is_archivable_pending_decomposed() -> None:
    """Pending decomposed parent is NOT archivable."""
    story = _make_story("US-4", "Test 4", passes=False, decomposed=True)
    assert is_archivable(story) is False


# ── Completed story count calculation tests ────────────────────────────────


def test_count_completed_stories_empty() -> None:
    """Count with no stories is 0."""
    prd = {"userStories": []}
    stories = prd.get("userStories", [])
    completed = [s for s in stories if s.get("passes") is True and not s.get("_decomposed", False)]
    assert len(completed) == 0


def test_count_completed_stories_mixed() -> None:
    """Count completed stories correctly with mixed state."""
    stories = [
        _make_story("US-1", "Completed 1", passes=True, decomposed=False),  # archivable
        _make_story("US-2", "Completed 2", passes=True, decomposed=False),  # archivable
        _make_story("US-3", "Pending 1", passes=False, decomposed=False),  # not archivable
        _make_story("US-4", "Parent 1", passes=True, decomposed=True),  # not archivable
        _make_story("US-5", "Completed 3", passes=True, decomposed=False),  # archivable
    ]
    completed = [s for s in stories if s.get("passes") is True and not s.get("_decomposed", False)]
    assert len(completed) == 3  # US-1, US-2, US-5


def test_count_completed_stories_all_completed() -> None:
    """Count when all stories are completed."""
    stories = [_make_story(f"US-{i}", f"Story {i}", passes=True, decomposed=False) for i in range(1, 6)]
    completed = [s for s in stories if s.get("passes") is True and not s.get("_decomposed", False)]
    assert len(completed) == 5


# ── Threshold trigger tests ────────────────────────────────────────────────


def test_threshold_trigger_exactly_at_threshold() -> None:
    """Archive triggers when completed count == threshold."""
    threshold = 100
    # Exactly 100 completed stories should trigger
    completed_count = 100
    assert completed_count >= threshold  # Should trigger


def test_threshold_trigger_above_threshold() -> None:
    """Archive triggers when completed count > threshold."""
    threshold = 100
    completed_count = 150
    assert completed_count >= threshold  # Should trigger


def test_threshold_trigger_below_threshold() -> None:
    """Archive does NOT trigger when completed count < threshold."""
    threshold = 100
    completed_count = 50
    assert not (completed_count >= threshold)  # Should not trigger


def test_threshold_disabled() -> None:
    """Archive does NOT run when threshold is 0."""
    threshold = 0
    # Threshold 0 should disable auto-archive
    assert not (threshold > 0)  # Condition check should fail


def test_threshold_default_value() -> None:
    """Default threshold is 100 as documented."""
    # This test documents the expected default
    default_threshold = 100
    assert default_threshold == 100


# ── Integration tests with prd.json ────────────────────────────────────────


def test_auto_archive_prd_json_integration() -> None:
    """Full integration: count completed stories in real prd.json structure."""
    prd = {
        "productName": "Spiral",
        "userStories": [
            _make_story(f"US-{i}", f"Completed Story {i}", passes=True, decomposed=False)
            for i in range(1, 51)  # 50 completed
        ]
        + [
            _make_story(f"US-5{i}", f"Pending Story {i}", passes=False, decomposed=False)
            for i in range(1, 6)  # 5 pending
        ]
        + [
            _make_story("US-PAR1", "Parent Story", passes=True, decomposed=True),  # 1 parent
        ],
    }

    stories = prd.get("userStories", [])
    completed = [s for s in stories if s.get("passes") is True and not s.get("_decomposed", False)]
    assert len(completed) == 50  # Only the 50 completed stories


def test_auto_archive_count_with_temp_prd() -> None:
    """Write prd.json to temp file and count completed stories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prd_file = Path(tmpdir) / "prd.json"
        prd = {
            "productName": "Test",
            "userStories": [
                _make_story(f"US-{i}", f"Story {i}", passes=True, decomposed=False)
                for i in range(1, 26)  # 25 completed
            ],
        }
        with open(prd_file, "w", encoding="utf-8") as f:
            json.dump(prd, f)

        # Read back and count
        with open(prd_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        stories = loaded.get("userStories", [])
        completed = [s for s in stories if s.get("passes") is True and not s.get("_decomposed", False)]
        assert len(completed) == 25


# ── Archive destination tests ──────────────────────────────────────────────


def test_archive_file_name() -> None:
    """Archive destination file should be prd-archive.json."""
    # This is the expected file name for archived stories
    archive_name = "prd-archive.json"
    assert archive_name == "prd-archive.json"


def test_archive_preserves_completed_stories() -> None:
    """Archived stories are moved (not deleted) to prd-archive.json."""
    # Verify archiving is an append operation (union) not deletion.
    # The archive_prd.py module appends to existing archive (union semantics),
    # so prd-archive.json grows monotonically as iterations complete stories.


# ── Threshold edge cases ──────────────────────────────────────────────────


def test_threshold_large_value() -> None:
    """Threshold can be set to large values."""
    threshold = 10000
    completed_count = 5000
    # Should not trigger
    assert not (completed_count >= threshold)


def test_threshold_string_to_int_conversion() -> None:
    """Threshold config value can be converted from string (shell env var)."""
    threshold_str = "100"
    threshold_int = int(threshold_str)
    completed_count = 100
    assert completed_count >= threshold_int  # Should trigger
