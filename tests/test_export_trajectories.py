"""Tests for lib/export_trajectories.py — JSONL trajectory export."""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from export_trajectories import (
    build_trajectory,
    export_trajectories,
    load_results_tsv,
    validate_trajectory,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_TSV_HEADER = [
    "timestamp",
    "spiral_iter",
    "ralph_iter",
    "story_id",
    "story_title",
    "status",
    "duration_sec",
    "model",
    "retry_num",
    "commit_sha",
    "run_id",
    "cache_hit",
    "cache_read_tokens",
    "cache_creation_tokens",
    "review_tokens",
    "wall_seconds",
    "user_cpu_s",
    "sys_cpu_s",
    "peak_rss_kb",
    "batch_id",
]


def _make_tsv(rows: list[dict[str, str]]) -> str:
    """Write rows to a temp TSV file; return path."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_TSV_HEADER, delimiter="\t", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        full = {k: row.get(k, "") for k in _TSV_HEADER}
        writer.writerow(full)
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8")
    tmp.write(buf.getvalue())
    tmp.close()
    return tmp.name


def _sample_row(story_id: str = "US-1", status: str = "keep") -> dict[str, str]:
    return {
        "timestamp": "2026-04-01T00:00:00Z",
        "spiral_iter": "1",
        "ralph_iter": "1",
        "story_id": story_id,
        "story_title": f"Test story {story_id}",
        "status": status,
        "duration_sec": "45.5",
        "model": "sonnet",
        "retry_num": "0",
        "cache_read_tokens": "1000",
        "cache_creation_tokens": "500",
    }


# ── Tests: reward mapping ─────────────────────────────────────────────────────


def test_passed_story_gets_positive_reward() -> None:
    row = _sample_row("US-1", "keep")
    traj = build_trajectory(row)
    assert traj["reward"] > 0, f"Expected reward > 0, got {traj['reward']}"


def test_failed_story_gets_non_positive_reward() -> None:
    row = _sample_row("US-2", "reject")
    traj = build_trajectory(row)
    assert traj["reward"] <= 0, f"Expected reward <= 0, got {traj['reward']}"


def test_reward_within_bounds() -> None:
    for status in ("keep", "reject", "skip", "pass", "fail"):
        row = _sample_row("US-3", status)
        traj = build_trajectory(row)
        assert -1.0 <= traj["reward"] <= 1.0, f"Reward out of bounds for status={status}"


# ── Tests: schema validation ──────────────────────────────────────────────────


def test_trajectory_schema_valid() -> None:
    row = _sample_row("US-10", "keep")
    traj = build_trajectory(row)
    assert validate_trajectory(traj), "Expected trajectory to be valid"


def test_messages_is_list_of_role_content() -> None:
    row = _sample_row("US-11", "keep")
    traj = build_trajectory(row)
    msgs = traj["messages"]
    assert isinstance(msgs, list)
    assert len(msgs) >= 1
    for msg in msgs:
        assert "role" in msg and isinstance(msg["role"], str)
        assert "content" in msg and isinstance(msg["content"], str)


def test_meta_contains_required_fields() -> None:
    row = _sample_row("US-12", "reject")
    traj = build_trajectory(row)
    meta = traj["meta"]
    assert meta["story_id"] == "US-12"
    assert isinstance(meta["model"], str)
    assert isinstance(meta["tokens"], int)
    assert isinstance(meta["duration"], float)


def test_invalid_trajectory_missing_messages() -> None:
    assert not validate_trajectory({"reward": 1.0, "meta": {}})


def test_invalid_trajectory_reward_out_of_range() -> None:
    assert not validate_trajectory({"messages": [{"role": "user", "content": "x"}], "reward": 2.5, "meta": {}})


# ── Tests: export_trajectories ────────────────────────────────────────────────


def test_export_produces_valid_jsonl() -> None:
    rows = [_sample_row("US-1", "keep"), _sample_row("US-2", "reject")]
    tsv_path = _make_tsv(rows)
    try:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as out:
            out_path = out.name
        n = export_trajectories(tsv_path=tsv_path, out_path=out_path)
        assert n == 2
        with open(out_path, encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]
        assert len(lines) == 2
        for obj in lines:
            assert validate_trajectory(obj)
    finally:
        os.unlink(tsv_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


def test_export_empty_tsv_writes_zero_records() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
        f.write("\t".join(_TSV_HEADER) + "\n")
        tsv_path = f.name
    try:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as out:
            out_path = out.name
        n = export_trajectories(tsv_path=tsv_path, out_path=out_path)
        assert n == 0
    finally:
        os.unlink(tsv_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


def test_load_results_tsv_missing_file_returns_empty() -> None:
    result = load_results_tsv("/nonexistent/path/results.tsv")
    assert result == []
