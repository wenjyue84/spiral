"""Unit tests for lib/invocation_snapshot.py — Per-story invocation snapshots (US-362)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from invocation_snapshot import (
    compress_snapshot,
    finish_snapshot,
    list_snapshots,
    prune_snapshots,
    read_snapshot,
    write_snapshot,
)


def _sample_story(story_id: str = "US-100") -> dict:
    return {
        "id": story_id,
        "title": "Add search endpoint",
        "priority": "medium",
        "passes": False,
        "acceptanceCriteria": ["Search returns results"],
    }


class TestWriteSnapshot:
    def test_creates_file(self, tmp_path):
        path = write_snapshot(str(tmp_path), "US-100", _sample_story())
        assert os.path.isfile(path)
        assert path.endswith("US-100.json")

    def test_snapshot_contents(self, tmp_path):
        write_snapshot(
            str(tmp_path),
            "US-100",
            _sample_story(),
            iteration=3,
            phase="I",
            model="sonnet",
            ralph_flags="20 --prd prd.json --tool claude",
        )
        snap = read_snapshot(str(tmp_path), "US-100")
        assert snap is not None
        assert snap["story_id"] == "US-100"
        assert snap["iteration"] == 3
        assert snap["phase"] == "I"
        assert snap["model"] == "sonnet"
        assert snap["ralph_flags"] == "20 --prd prd.json --tool claude"
        assert snap["story_json"]["title"] == "Add search endpoint"
        assert snap["ts_start"] is not None
        assert snap["ts_end"] is None
        assert snap["rc"] is None
        assert snap["stdout_head"] is None

    def test_creates_invocations_dir(self, tmp_path):
        base = str(tmp_path / "scratch")
        write_snapshot(base, "US-101", _sample_story("US-101"))
        assert os.path.isdir(os.path.join(base, "invocations"))

    def test_overwrites_existing(self, tmp_path):
        write_snapshot(str(tmp_path), "US-100", _sample_story(), iteration=1)
        write_snapshot(str(tmp_path), "US-100", _sample_story(), iteration=2)
        snap = read_snapshot(str(tmp_path), "US-100")
        assert snap is not None
        assert snap["iteration"] == 2


class TestFinishSnapshot:
    def test_appends_completion_data(self, tmp_path):
        write_snapshot(str(tmp_path), "US-100", _sample_story())
        path = finish_snapshot(str(tmp_path), "US-100", returncode=0, stdout_head="All tests passed")
        assert path is not None
        snap = read_snapshot(str(tmp_path), "US-100")
        assert snap is not None
        assert snap["rc"] == 0
        assert snap["stdout_head"] == "All tests passed"
        assert snap["ts_end"] is not None

    def test_truncates_stdout_at_2000(self, tmp_path):
        write_snapshot(str(tmp_path), "US-100", _sample_story())
        long_output = "x" * 5000
        finish_snapshot(str(tmp_path), "US-100", returncode=1, stdout_head=long_output)
        snap = read_snapshot(str(tmp_path), "US-100")
        assert snap is not None
        assert len(snap["stdout_head"]) == 2000

    def test_returns_none_for_missing(self, tmp_path):
        result = finish_snapshot(str(tmp_path), "US-999", returncode=1)
        assert result is None


class TestReadSnapshot:
    def test_returns_none_for_missing(self, tmp_path):
        assert read_snapshot(str(tmp_path), "US-999") is None

    def test_reads_written_snapshot(self, tmp_path):
        write_snapshot(str(tmp_path), "US-200", _sample_story("US-200"))
        snap = read_snapshot(str(tmp_path), "US-200")
        assert snap is not None
        assert snap["story_id"] == "US-200"


class TestListSnapshots:
    def test_empty_dir(self, tmp_path):
        assert list_snapshots(str(tmp_path)) == []

    def test_lists_multiple(self, tmp_path):
        write_snapshot(str(tmp_path), "US-100", _sample_story("US-100"), iteration=1)
        write_snapshot(str(tmp_path), "US-101", _sample_story("US-101"), iteration=2)
        snaps = list_snapshots(str(tmp_path))
        assert len(snaps) == 2
        ids = [s["story_id"] for s in snaps]
        assert "US-100" in ids
        assert "US-101" in ids


class TestPruneSnapshots:
    def test_prunes_old_snapshots(self, tmp_path):
        write_snapshot(str(tmp_path), "US-100", _sample_story("US-100"), iteration=1)
        write_snapshot(str(tmp_path), "US-101", _sample_story("US-101"), iteration=5)
        write_snapshot(str(tmp_path), "US-102", _sample_story("US-102"), iteration=10)
        removed = prune_snapshots(str(tmp_path), current_iteration=10, retention=7)
        assert removed == 1  # US-100 at iter 1, cutoff = 10-7 = 3
        assert read_snapshot(str(tmp_path), "US-100") is None
        assert read_snapshot(str(tmp_path), "US-101") is not None
        assert read_snapshot(str(tmp_path), "US-102") is not None

    def test_no_pruning_when_all_recent(self, tmp_path):
        write_snapshot(str(tmp_path), "US-100", _sample_story("US-100"), iteration=8)
        removed = prune_snapshots(str(tmp_path), current_iteration=10, retention=7)
        assert removed == 0

    def test_empty_dir(self, tmp_path):
        removed = prune_snapshots(str(tmp_path), current_iteration=10, retention=7)
        assert removed == 0


class TestCompressSnapshot:
    def test_compresses_to_gzip(self, tmp_path):
        write_snapshot(str(tmp_path), "US-100", _sample_story())
        gz_path = compress_snapshot(str(tmp_path), "US-100")
        assert gz_path is not None
        assert gz_path.endswith(".json.gz")
        assert os.path.isfile(gz_path)
        # Original should be removed
        json_path = os.path.join(str(tmp_path), "invocations", "US-100.json")
        assert not os.path.isfile(json_path)

    def test_returns_none_for_missing(self, tmp_path):
        assert compress_snapshot(str(tmp_path), "US-999") is None
