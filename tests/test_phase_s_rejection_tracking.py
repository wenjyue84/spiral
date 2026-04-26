"""tests/test_phase_s_rejection_tracking.py — Test rejection tracking in Phase S.

Tests for:
- lib/track_rejections.py: track rejection reasons in prd.json and .spiral/rejections.jsonl
- lib/cli_explain_rejection.py: query and display rejection reasons
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def test_track_rejections_updates_prd_json() -> None:
    """Test that track_rejections adds _rejectionLog to prd.json."""
    from lib.track_rejections import track_rejections

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create prd.json with a story
        prd = {
            "userStories": [
                {
                    "id": "US-100",
                    "title": "Test story",
                    "description": "A test story",
                }
            ]
        }
        prd_file = tmpdir_path / "prd.json"
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        # Create rejected.json
        rejected = {
            "stories": [
                {
                    "id": "US-100",
                    "title": "Test story",
                    "_rejection_reason": "goal_misaligned: no matching keywords",
                    "_source": "research",
                }
            ]
        }
        rejected_file = tmpdir_path / "rejected.json"
        rejected_file.write_text(json.dumps(rejected), encoding="utf-8")

        # Track rejections
        result = track_rejections(str(prd_file), str(rejected_file))
        assert result == 0

        # Verify prd.json was updated
        updated_prd = json.loads(prd_file.read_text(encoding="utf-8"))
        story = updated_prd["userStories"][0]
        assert "_rejectionLog" in story
        assert len(story["_rejectionLog"]) == 1
        entry = story["_rejectionLog"][0]
        assert entry["reason"] == "goal_misaligned"
        assert "goal_misaligned" in entry["details"]


def test_track_rejections_writes_jsonl() -> None:
    """Test that track_rejections writes .spiral/rejections.jsonl."""
    from lib.track_rejections import track_rejections

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create prd.json
        prd = {"userStories": [{"id": "US-101", "title": "Story 1", "description": "desc"}]}
        prd_file = tmpdir_path / "prd.json"
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        # Create rejected.json
        rejected = {
            "stories": [
                {
                    "id": "US-101",
                    "title": "Story 1",
                    "_rejection_reason": "acceptance_criteria_incomplete: too vague",
                    "_source": "research",
                }
            ]
        }
        rejected_file = tmpdir_path / "rejected.json"
        rejected_file.write_text(json.dumps(rejected), encoding="utf-8")

        # Track rejections with jsonl output
        rejections_jsonl = tmpdir_path / "rejections.jsonl"
        result = track_rejections(str(prd_file), str(rejected_file), str(rejections_jsonl))
        assert result == 0

        # Verify rejections.jsonl was created
        assert rejections_jsonl.exists()
        lines = rejections_jsonl.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["story_id"] == "US-101"
        assert entry["reason"] == "acceptance_criteria_incomplete"


def test_track_rejections_no_rejections() -> None:
    """Test that track_rejections handles empty rejections gracefully."""
    from lib.track_rejections import track_rejections

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create prd.json
        prd = {"userStories": [{"id": "US-102", "title": "Story 2", "description": "desc"}]}
        prd_file = tmpdir_path / "prd.json"
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        # Create empty rejected.json
        rejected = {"stories": []}
        rejected_file = tmpdir_path / "rejected.json"
        rejected_file.write_text(json.dumps(rejected), encoding="utf-8")

        # Track rejections (should be no-op)
        result = track_rejections(str(prd_file), str(rejected_file))
        assert result == 0

        # Verify prd.json unchanged (no _rejectionLog)
        updated_prd = json.loads(prd_file.read_text(encoding="utf-8"))
        story = updated_prd["userStories"][0]
        assert "_rejectionLog" not in story


def test_explain_rejection_text_format() -> None:
    """Test that explain-rejection displays text format with hints."""
    from lib.cli_explain_rejection import _format_text

    story = {
        "id": "US-200",
        "title": "Example story",
        "_rejectionLog": [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": "goal_misaligned",
                "details": "goal_misaligned: no matching keywords with project goals",
            }
        ],
    }

    output = _format_text(story)
    assert "US-200" in output
    assert "Example story" in output
    assert "goal_misaligned" in output
    assert "Review prd.json goals[]" in output  # remediation hint


def test_explain_rejection_json_format() -> None:
    """Test that explain-rejection displays JSON format."""
    from lib.cli_explain_rejection import _format_json

    story = {
        "id": "US-201",
        "title": "Another story",
        "_rejectionLog": [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": "acceptance_criteria_incomplete",
                "details": "only 1 measurable AC",
            }
        ],
    }

    output = _format_json(story)
    data = json.loads(output)
    assert data["id"] == "US-201"
    assert data["title"] == "Another story"
    assert len(data["rejectionLog"]) == 1
    assert data["rejectionLog"][0]["reason"] == "acceptance_criteria_incomplete"


def test_remediation_hints_constitution() -> None:
    """Test remediation hints for constitution_mismatch."""
    from lib.cli_explain_rejection import _remediation_hints

    hints = _remediation_hints("constitution_mismatch: matches forbidden phrase")
    assert any("constitution" in h.lower() for h in hints)


def test_remediation_hints_acceptance_criteria() -> None:
    """Test remediation hints for acceptance_criteria_incomplete."""
    from lib.cli_explain_rejection import _remediation_hints

    hints = _remediation_hints("measurable acceptance criteria are required")
    assert any("measurable" in h.lower() or "backticks" in h.lower() for h in hints)


def test_normalize_reason() -> None:
    """Test that rejection reasons are normalized to standard forms."""
    from lib.track_rejections import _normalize_reason

    assert _normalize_reason("constitution mismatch detected") == "constitution_mismatch"
    assert _normalize_reason("goal alignment failed") == "goal_misaligned"
    assert _normalize_reason("duplicate_detected") == "duplicate_detected"
    assert _normalize_reason("too many vague acceptance criteria") == "acceptance_criteria_incomplete"
    assert _normalize_reason("quality score below threshold") == "quality_score_too_low"
    assert _normalize_reason("some other reason") == "validation_failed"
