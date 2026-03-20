"""Tests for lib/observability/merge_events.py — per-worker event merge."""

import json
import os

import pytest

from lib.observability.merge_events import merge_events


@pytest.fixture
def events_setup(tmp_path):
    """Create a test events directory structure."""
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    main_file = str(tmp_path / "spiral_events.jsonl")
    return str(tmp_path), main_file, str(events_dir)


def test_merge_worker_events(events_setup):
    _, main_file, events_dir = events_setup

    # Main file with existing events
    with open(main_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-03-18T10:00:00Z", "event": "phase_start"}) + "\n")
        f.write(json.dumps({"ts": "2026-03-18T10:05:00Z", "event": "phase_end"}) + "\n")

    # Worker 1 events
    with open(os.path.join(events_dir, "worker-1.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-03-18T10:02:00Z", "event": "story_started", "worker_id": 1}) + "\n")
        f.write(json.dumps({"ts": "2026-03-18T10:04:00Z", "event": "story_passed", "worker_id": 1}) + "\n")

    # Worker 2 events
    with open(os.path.join(events_dir, "worker-2.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-03-18T10:03:00Z", "event": "story_started", "worker_id": 2}) + "\n")

    result = merge_events(main_file, events_dir)
    assert result == 0

    # Verify merged file
    with open(main_file, encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    assert len(lines) == 5  # 2 main + 2 worker1 + 1 worker2

    # Verify chronological order
    timestamps = [line["ts"] for line in lines]
    assert timestamps == sorted(timestamps)

    # Verify worker files were cleaned up
    assert not os.path.exists(os.path.join(events_dir, "worker-1.jsonl"))
    assert not os.path.exists(os.path.join(events_dir, "worker-2.jsonl"))


def test_merge_no_workers(events_setup):
    _, main_file, events_dir = events_setup

    with open(main_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-03-18T10:00:00Z", "event": "test"}) + "\n")

    result = merge_events(main_file, events_dir)
    assert result == 0

    # Main file unchanged
    with open(main_file, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1


def test_merge_no_main_file(events_setup):
    _, main_file, events_dir = events_setup

    # Only worker events, no main file
    with open(os.path.join(events_dir, "worker-1.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-03-18T10:00:00Z", "event": "test"}) + "\n")

    result = merge_events(main_file, events_dir)
    assert result == 0

    with open(main_file, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1


def test_merge_empty_events_dir(events_setup):
    _, main_file, events_dir = events_setup
    result = merge_events(main_file, events_dir)
    assert result == 0


def test_merge_nonexistent_events_dir(events_setup):
    _, main_file, _ = events_setup
    result = merge_events(main_file, "/nonexistent/path")
    assert result == 0


def test_merge_ignores_non_worker_files(events_setup):
    _, main_file, events_dir = events_setup

    # Create a non-worker file that should be ignored
    with open(os.path.join(events_dir, "other.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-03-18T10:00:00Z", "event": "ignore_me"}) + "\n")

    # Create a worker file
    with open(os.path.join(events_dir, "worker-1.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-03-18T10:01:00Z", "event": "include_me"}) + "\n")

    result = merge_events(main_file, events_dir)
    assert result == 0

    with open(main_file, encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    # Only worker-1 event, not the other.jsonl
    assert len(lines) == 1
    assert lines[0]["event"] == "include_me"

    # other.jsonl should still exist
    assert os.path.exists(os.path.join(events_dir, "other.jsonl"))
