"""Unit tests for lib/handle_patch_rollback.py (US-1139)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from lib.handle_patch_rollback import (
    log_patch_rollback_event,
    reset_stories_to_pending,
)


@pytest.fixture
def temp_prd() -> tuple[Path, dict]:
    """Create a temporary prd.json with test stories."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        prd = {
            "schemaVersion": 1,
            "projectName": "Test",
            "userStories": [
                {
                    "id": "US-101",
                    "title": "Story 1",
                    "passes": True,
                    "_passedCommit": "abc123",
                },
                {
                    "id": "US-102",
                    "title": "Story 2",
                    "passes": True,
                    "_passedCommit": "def456",
                },
                {
                    "id": "US-103",
                    "title": "Story 3",
                    "passes": True,
                    "_passedCommit": "ghi789",
                },
            ],
        }
        json.dump(prd, f)
        prd_path = Path(f.name)
    return prd_path, prd


@pytest.fixture
def temp_events() -> Path:
    """Create a temporary spiral_events.jsonl file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        return Path(f.name)


def test_reset_stories_to_pending(temp_prd: tuple[Path, dict]) -> None:
    """Test that reset_stories_to_pending resets passed stories to pending."""
    prd_path, original_prd = temp_prd

    # Reset US-101 and US-102
    reset_stories_to_pending(str(prd_path), ["US-101", "US-102"])

    # Read the updated prd.json
    with open(prd_path, encoding="utf-8") as f:
        updated_prd = json.load(f)

    # Verify US-101 is now pending
    us101 = next(s for s in updated_prd["userStories"] if s["id"] == "US-101")
    assert us101["passes"] is False
    assert "_passedCommit" not in us101

    # Verify US-102 is now pending
    us102 = next(s for s in updated_prd["userStories"] if s["id"] == "US-102")
    assert us102["passes"] is False
    assert "_passedCommit" not in us102

    # Verify US-103 is still passed
    us103 = next(s for s in updated_prd["userStories"] if s["id"] == "US-103")
    assert us103["passes"] is True
    assert us103["_passedCommit"] == "ghi789"


def test_reset_stories_with_missing_story(
    temp_prd: tuple[Path, dict], capsys
) -> None:
    """Test that reset_stories_to_pending handles missing stories gracefully."""
    prd_path, _ = temp_prd

    # Try to reset US-101 and non-existent US-999
    reset_stories_to_pending(str(prd_path), ["US-101", "US-999"])

    # Should still succeed (with a warning)
    captured = capsys.readouterr()
    assert "US-999" in captured.err

    # US-101 should be reset
    with open(prd_path, encoding="utf-8") as f:
        updated_prd = json.load(f)
    us101 = next(s for s in updated_prd["userStories"] if s["id"] == "US-101")
    assert us101["passes"] is False


def test_log_patch_rollback_event(temp_events: Path) -> None:
    """Test that patch_rollback event is logged with correct structure."""
    story_ids = ["US-101", "US-102"]
    sha = "deadbeef1234567890abcdef"
    reason = "git apply failed for worker 2"

    log_patch_rollback_event(str(temp_events), story_ids, sha, reason)

    # Read the logged event
    with open(temp_events, encoding="utf-8") as f:
        event_line = f.read().strip()

    event = json.loads(event_line)

    # Verify event structure
    assert event["event"] == "patch_rollback"
    assert event["story_ids"] == story_ids
    assert event["sha"] == sha
    assert event["reason"] == reason
    assert "ts" in event
    assert event["ts"].endswith("Z")  # ISO format with Z suffix


def test_log_multiple_events(temp_events: Path) -> None:
    """Test that multiple events are logged correctly (JSONL format)."""
    log_patch_rollback_event(
        str(temp_events), ["US-101"], "sha1", "reason1"
    )
    log_patch_rollback_event(
        str(temp_events), ["US-102"], "sha2", "reason2"
    )

    # Read all events
    with open(temp_events, encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 2

    event1 = json.loads(lines[0])
    assert event1["story_ids"] == ["US-101"]
    assert event1["sha"] == "sha1"

    event2 = json.loads(lines[1])
    assert event2["story_ids"] == ["US-102"]
    assert event2["sha"] == "sha2"


def test_reset_and_log_atomically(
    temp_prd: tuple[Path, dict], temp_events: Path
) -> None:
    """Test that reset and logging work together correctly."""
    prd_path, _ = temp_prd

    story_ids = ["US-101", "US-102"]
    sha = "savepoint123"
    reason = "rollback test"

    # Reset stories
    reset_stories_to_pending(str(prd_path), story_ids)

    # Log event
    log_patch_rollback_event(str(temp_events), story_ids, sha, reason)

    # Verify prd.json was updated
    with open(prd_path, encoding="utf-8") as f:
        prd = json.load(f)
    us101 = next(s for s in prd["userStories"] if s["id"] == "US-101")
    assert us101["passes"] is False

    # Verify event was logged
    with open(temp_events, encoding="utf-8") as f:
        event = json.loads(f.read().strip())
    assert event["story_ids"] == story_ids
