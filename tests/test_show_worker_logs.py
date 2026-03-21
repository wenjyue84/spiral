"""tests/test_show_worker_logs.py — Integration tests for US-607.

Tests the show-worker-logs CLI command:
- AC1: Tab-separated output format with correct columns; --worker-id and --phase filters
- AC2: Logs from 2 workers merge without duplicates in time order;
       --worker-id=worker-1 returns only that worker's logs
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from commands.show_worker_logs import (  # noqa: E402
    LogEntry,
    find_worker_logs,
    format_output,
    parse_worker_logs,
    show_worker_logs,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _write_log(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


WORKER_1_LINES = [
    "2026-03-21T10:00:01 [Phase I] INFO Starting worker 1 implementation",
    "2026-03-21T10:00:05 [Phase I] WARN Retry needed for US-101",
    "2026-03-21T10:00:10 [Phase I] INFO Worker 1 completed US-101",
]

WORKER_2_LINES = [
    "2026-03-21T10:00:02 [Phase I] INFO Starting worker 2 implementation",
    "2026-03-21T10:00:07 [Phase R] INFO Worker 2 research fallback",
    "2026-03-21T10:00:12 [Phase I] ERROR Worker 2 failed US-202",
]


# ── AC1: Output format ──────────────────────────────────────────────────────


def test_output_format_tab_separated(tmp_path: Path) -> None:
    """AC1: Output is tab-separated with correct columns."""
    workers_dir = tmp_path / "workers"
    _write_log(workers_dir / "worker_1.log", WORKER_1_LINES)

    logs = find_worker_logs([workers_dir])
    entries = parse_worker_logs(logs)
    output = format_output(entries)

    lines = output.strip().split("\n")
    # Header
    assert lines[0] == "worker_id\ttimestamp\tphase\tlog_level\tmessage"

    # All data lines have 5 tab-separated fields
    for line in lines[1:]:
        fields = line.split("\t")
        assert len(fields) == 5, f"Expected 5 fields, got {len(fields)}: {line}"


def test_worker_id_filter(tmp_path: Path) -> None:
    """AC1: --worker-id filter returns only that worker's logs."""
    workers_dir = tmp_path / "workers"
    _write_log(workers_dir / "worker_1.log", WORKER_1_LINES)
    _write_log(workers_dir / "worker_2.log", WORKER_2_LINES)

    logs = find_worker_logs([workers_dir])

    # Filter to worker-1 only
    entries = parse_worker_logs(logs, worker_id_filter="worker-1")
    assert len(entries) == 3, f"Expected 3 entries for worker-1, got {len(entries)}"
    assert all(e.worker_id == "worker-1" for e in entries)

    # Filter to worker-2 only
    entries2 = parse_worker_logs(logs, worker_id_filter="worker-2")
    assert len(entries2) == 3, f"Expected 3 entries for worker-2, got {len(entries2)}"
    assert all(e.worker_id == "worker-2" for e in entries2)


def test_phase_filter(tmp_path: Path) -> None:
    """AC1: --phase filter returns only matching phase entries."""
    workers_dir = tmp_path / "workers"
    _write_log(workers_dir / "worker_1.log", WORKER_1_LINES)
    _write_log(workers_dir / "worker_2.log", WORKER_2_LINES)

    logs = find_worker_logs([workers_dir])

    # Filter to Phase R only — should get 1 entry from worker-2
    entries = parse_worker_logs(logs, phase_filter="R")
    assert len(entries) == 1
    assert entries[0].phase == "R"
    assert entries[0].worker_id == "worker-2"


def test_output_to_file(tmp_path: Path) -> None:
    """AC1: --output writes to file."""
    workers_dir = tmp_path / "workers"
    _write_log(workers_dir / "worker_1.log", WORKER_1_LINES)

    output_file = tmp_path / "output.log"
    result = show_worker_logs(
        search_dirs=[workers_dir],
        output_path=str(output_file),
    )

    assert output_file.exists()
    file_content = output_file.read_text(encoding="utf-8")
    assert "worker_id\ttimestamp\tphase\tlog_level\tmessage" in file_content
    assert result == file_content


# ── AC2: Multi-worker merge ─────────────────────────────────────────────────


def test_two_workers_merge_in_time_order(tmp_path: Path) -> None:
    """AC2: Logs from 2 workers merge in time order without duplicates."""
    workers_dir = tmp_path / "workers"
    _write_log(workers_dir / "worker_1.log", WORKER_1_LINES)
    _write_log(workers_dir / "worker_2.log", WORKER_2_LINES)

    logs = find_worker_logs([workers_dir])
    entries = parse_worker_logs(logs)

    # All 6 unique lines are present
    assert len(entries) == 6, f"Expected 6 entries, got {len(entries)}"

    # Verify time ordering: timestamps should be non-decreasing
    timestamps = [e.timestamp for e in entries]
    assert timestamps == sorted(timestamps), (
        f"Entries not in time order: {timestamps}"
    )

    # Verify interleaving: worker-1 and worker-2 entries are mixed
    worker_ids = [e.worker_id for e in entries]
    assert "worker-1" in worker_ids
    assert "worker-2" in worker_ids

    # Verify expected time order:
    # 10:00:01 w1, 10:00:02 w2, 10:00:05 w1, 10:00:07 w2, 10:00:10 w1, 10:00:12 w2
    assert entries[0].worker_id == "worker-1"  # 10:00:01
    assert entries[1].worker_id == "worker-2"  # 10:00:02
    assert entries[2].worker_id == "worker-1"  # 10:00:05
    assert entries[3].worker_id == "worker-2"  # 10:00:07


def test_no_duplicate_lines(tmp_path: Path) -> None:
    """AC2: Duplicate log lines are removed."""
    workers_dir = tmp_path / "workers"
    # Write same content to both files
    _write_log(workers_dir / "worker_1.log", WORKER_1_LINES)
    _write_log(
        workers_dir / "worker_1_copy.log",
        WORKER_1_LINES,  # exact duplicate
    )

    logs = find_worker_logs([workers_dir])
    entries = parse_worker_logs(logs)

    # Should deduplicate — same worker_id + timestamp + message
    assert len(entries) == 3, (
        f"Expected 3 deduplicated entries, got {len(entries)}"
    )


def test_log_level_extraction(tmp_path: Path) -> None:
    """Verify ERROR, WARN, INFO log levels are extracted correctly."""
    workers_dir = tmp_path / "workers"
    _write_log(workers_dir / "worker_1.log", WORKER_1_LINES)
    _write_log(workers_dir / "worker_2.log", WORKER_2_LINES)

    logs = find_worker_logs([workers_dir])
    entries = parse_worker_logs(logs)

    levels = {e.log_level for e in entries}
    assert "INFO" in levels
    assert "WARN" in levels
    assert "ERROR" in levels


def test_empty_logs_directory(tmp_path: Path) -> None:
    """Handle empty or missing log directories gracefully."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    logs = find_worker_logs([empty_dir])
    assert logs == []

    entries = parse_worker_logs(logs)
    assert entries == []


def test_find_logs_in_spiral_workers_subdirs(tmp_path: Path) -> None:
    """Find logs in worker-N subdirectory structure (worktree layout)."""
    base = tmp_path / ".spiral-workers"
    _write_log(
        base / "worker-1" / "ralph.log",
        ["2026-03-21T10:00:01 [Phase I] INFO Ralph log entry"],
    )
    _write_log(
        base / "worker-2" / "ralph.log",
        ["2026-03-21T10:00:02 [Phase I] INFO Another Ralph entry"],
    )

    logs = find_worker_logs([base])
    assert len(logs) == 2

    entries = parse_worker_logs(logs)
    assert len(entries) == 2
    worker_ids = {e.worker_id for e in entries}
    assert "worker-1" in worker_ids
    assert "worker-2" in worker_ids
