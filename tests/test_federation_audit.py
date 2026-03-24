"""tests/test_federation_audit.py — Federation Audit Trail Tests (US-1077)."""

from __future__ import annotations

import json
import os

# Add lib to path for imports
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from federation_audit import parse_audit_log, write_audit_entry


def test_write_audit_entry_creates_jsonl() -> None:
    """Test that write_audit_entry creates JSONL file with correct format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / ".spiral" / "federation_audit.jsonl"

        write_audit_entry(
            action="merge",
            story_id="US-123",
            sub_project="frontend",
            reason="test reason",
            tokens_spent=1000,
            audit_path=str(audit_path),
        )

        assert audit_path.exists()

        # Read and verify JSON format
        with open(audit_path) as f:
            line = f.readline()
            entry = json.loads(line)

        assert entry["action"] == "merge"
        assert entry["story_id"] == "US-123"
        assert entry["sub_project"] == "frontend"
        assert entry["reason"] == "test reason"
        assert entry["tokens_spent"] == 1000
        assert "timestamp" in entry


def test_write_multiple_entries() -> None:
    """Test appending multiple entries to JSONL file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"

        write_audit_entry(
            action="merge",
            story_id="US-1",
            sub_project="app",
            reason="first",
            tokens_spent=0,
            audit_path=str(audit_path),
        )
        write_audit_entry(
            action="reject",
            story_id="US-2",
            sub_project="api",
            reason="duplicate",
            tokens_spent=0,
            audit_path=str(audit_path),
        )

        entries = parse_audit_log(str(audit_path))
        assert len(entries) == 2
        assert entries[0]["story_id"] == "US-1"
        assert entries[1]["story_id"] == "US-2"


def test_parse_audit_log_empty_file() -> None:
    """Test parsing empty audit file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        audit_path.touch()

        entries = parse_audit_log(str(audit_path))
        assert entries == []


def test_parse_audit_log_nonexistent_file() -> None:
    """Test parsing nonexistent audit file returns empty list."""
    entries = parse_audit_log("/nonexistent/path/audit.jsonl")
    assert entries == []


def test_parse_audit_log_skips_malformed_lines() -> None:
    """Test that parse_audit_log skips malformed JSON lines."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"

        # Write mixed valid and invalid lines
        with open(audit_path, "w") as f:
            f.write('{"valid": "entry"}\n')
            f.write('this is not json\n')
            f.write('{"another": "valid"}\n')

        entries = parse_audit_log(str(audit_path))
        assert len(entries) == 2
        assert entries[0]["valid"] == "entry"
        assert entries[1]["another"] == "valid"


def test_write_audit_entry_all_actions() -> None:
    """Test write_audit_entry with all three action types."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"

        actions = ["merge", "reject", "quota_violation"]
        for i, action in enumerate(actions):
            write_audit_entry(
                action=action,
                story_id=f"US-{i}",
                sub_project="test",
                reason=f"test {action}",
                tokens_spent=100 * i,
                audit_path=str(audit_path),
            )

        entries = parse_audit_log(str(audit_path))
        assert len(entries) == 3
        assert entries[0]["action"] == "merge"
        assert entries[1]["action"] == "reject"
        assert entries[2]["action"] == "quota_violation"


def test_parse_audit_log_preserves_order() -> None:
    """Test that parse_audit_log preserves entry order."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"

        for i in range(5):
            write_audit_entry(
                action="merge",
                story_id=f"US-{i}",
                sub_project="test",
                reason=f"entry {i}",
                tokens_spent=i,
                audit_path=str(audit_path),
            )

        entries = parse_audit_log(str(audit_path))
        assert [e["story_id"] for e in entries] == [f"US-{i}" for i in range(5)]


def test_audit_entry_timestamp_format() -> None:
    """Test that timestamp is in ISO format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"

        write_audit_entry(
            action="merge",
            story_id="US-123",
            sub_project="test",
            reason="test",
            tokens_spent=0,
            audit_path=str(audit_path),
        )

        entries = parse_audit_log(str(audit_path))
        ts = entries[0]["timestamp"]

        # ISO format: YYYY-MM-DDTHH:MM:SS.ffffff+00:00
        assert "T" in ts
        assert ":" in ts


def test_write_creates_nested_directories() -> None:
    """Test that write_audit_entry creates nested directories as needed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "a" / "b" / "c" / "audit.jsonl"

        write_audit_entry(
            action="merge",
            story_id="US-1",
            sub_project="test",
            reason="test",
            tokens_spent=0,
            audit_path=str(audit_path),
        )

        assert audit_path.exists()


def test_quota_violation_action() -> None:
    """Test quota_violation action type for AC1."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"

        write_audit_entry(
            action="quota_violation",
            story_id="US-100",
            sub_project="frontend",
            reason="Quota exceeded for frontend: 31/30",
            tokens_spent=0,
            audit_path=str(audit_path),
        )

        entries = parse_audit_log(str(audit_path))
        assert len(entries) == 1
        assert entries[0]["action"] == "quota_violation"
        assert "Quota exceeded" in entries[0]["reason"]
