"""Tests for snapshot.py — SPIRAL project state snapshots."""

import json
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.snapshot import SnapshotManager


class TestSnapshotSave:
    """Test SnapshotManager.save()."""

    def test_snapshot_save_creates_tarball(self) -> None:
        """Test that save() creates a .tar.gz file."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            # Create test files
            prd_file = project_root / "prd.json"
            prd_file.write_text('{"userStories": []}', encoding="utf-8")
            results_file = project_root / "results.tsv"
            results_file.write_text("story_id\tpasses\n", encoding="utf-8")

            manager = SnapshotManager(project_root=str(project_root))
            snapshot_path = manager.save(out_dir=str(snapshot_dir))

            assert Path(snapshot_path).exists()
            assert snapshot_path.endswith(".tar.gz")

    def test_snapshot_save_contains_files(self) -> None:
        """Test that saved snapshot contains the expected files."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            # Create test files
            prd_file = project_root / "prd.json"
            prd_file.write_text('{"schemaVersion": 1}', encoding="utf-8")
            results_file = project_root / "results.tsv"
            results_file.write_text("story_id\tstatus\n", encoding="utf-8")

            manager = SnapshotManager(project_root=str(project_root))
            snapshot_path = manager.save(out_dir=str(snapshot_dir))

            # Verify tarball contents
            with tarfile.open(snapshot_path, "r:gz") as tar:
                names = tar.getnames()
                assert "prd.json" in names
                assert "results.tsv" in names

    def test_snapshot_save_timestamp_in_filename(self) -> None:
        """Test that snapshot filename contains ISO8601 timestamp."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            prd_file = project_root / "prd.json"
            prd_file.write_text("{}", encoding="utf-8")

            manager = SnapshotManager(project_root=str(project_root))
            snapshot_path = manager.save(out_dir=str(snapshot_dir))

            filename = Path(snapshot_path).name
            assert filename.startswith("snapshot-")
            assert filename.endswith(".tar.gz")
            # Verify timestamp format (should have dashes instead of colons)
            assert "-" in filename
            assert "Z" in filename

    def test_snapshot_save_missing_files(self) -> None:
        """Test that save() handles missing optional files gracefully."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            # Only create prd.json (results.tsv not required initially)
            prd_file = project_root / "prd.json"
            prd_file.write_text("{}", encoding="utf-8")

            manager = SnapshotManager(project_root=str(project_root))
            snapshot_path = manager.save(out_dir=str(snapshot_dir))

            # Should succeed and create a tarball
            assert Path(snapshot_path).exists()

    def test_snapshot_save_no_files_raises_error(self) -> None:
        """Test that save() raises error when no snapshot files exist."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            # Create no files
            manager = SnapshotManager(project_root=str(project_root))

            with pytest.raises(RuntimeError, match="No snapshot files found"):
                manager.save(out_dir=str(snapshot_dir))

    def test_snapshot_save_missing_output_dir_raises_error(self) -> None:
        """Test that save() raises error if output directory doesn't exist."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            prd_file = project_root / "prd.json"
            prd_file.write_text("{}", encoding="utf-8")

            manager = SnapshotManager(project_root=str(project_root))

            with pytest.raises(FileNotFoundError):
                manager.save(out_dir=str(project_root / "nonexistent"))


class TestSnapshotRestore:
    """Test SnapshotManager.restore()."""

    def test_snapshot_restore_overwrites_prd(self) -> None:
        """Test that restore() overwrites prd.json from snapshot."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            # Create initial prd.json
            prd_file = project_root / "prd.json"
            prd_file.write_text('{"version": 1}', encoding="utf-8")

            # Save snapshot
            manager = SnapshotManager(project_root=str(project_root))
            snapshot_path = manager.save(out_dir=str(snapshot_dir))
            snapshot_name = Path(snapshot_path).name

            # Modify prd.json
            prd_file.write_text('{"version": 2}', encoding="utf-8")

            # Extract timestamp from filename (format: snapshot-YYYY-MM-DDTHH-mm-ssZ.tar.gz)
            timestamp = snapshot_name.replace("snapshot-", "").replace(".tar.gz", "")

            # Restore from snapshot
            manager.restore(timestamp=timestamp, out_dir=str(snapshot_dir))

            # Verify prd.json was restored
            restored_prd = json.loads(prd_file.read_text(encoding="utf-8"))
            assert restored_prd == {"version": 1}

    def test_snapshot_restore_checkpoint_info(self) -> None:
        """Test that restore() returns checkpoint info."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            # Create test files including checkpoint
            prd_file = project_root / "prd.json"
            prd_file.write_text("{}", encoding="utf-8")
            checkpoint_file = snapshot_dir / "checkpoint.json"
            checkpoint_file.write_text(
                '{"iter": 5, "phase": "G", "ts": "2026-04-27T12:00:00Z"}',
                encoding="utf-8",
            )

            # Save snapshot
            manager = SnapshotManager(project_root=str(project_root))
            snapshot_path = manager.save(out_dir=str(snapshot_dir))
            timestamp = Path(snapshot_path).name.replace("snapshot-", "").replace(".tar.gz", "")

            # Restore and check checkpoint info
            info = manager.restore(timestamp=timestamp, out_dir=str(snapshot_dir))
            assert info["iter"] == 5
            assert info["phase"] == "G"
            assert "2026-04-27" in info["ts"]

    def test_snapshot_restore_timestamp_not_found(self) -> None:
        """Test that restore() raises error for non-existent timestamp."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            manager = SnapshotManager(project_root=str(project_root))

            with pytest.raises(FileNotFoundError, match="Snapshot not found"):
                manager.restore(timestamp="2026-04-27T00-00-00Z", out_dir=str(snapshot_dir))

    def test_snapshot_restore_with_colon_timestamp(self) -> None:
        """Test that restore() handles timestamp with colons (pre-normalized)."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            # Create and save snapshot
            prd_file = project_root / "prd.json"
            prd_file.write_text('{"test": true}', encoding="utf-8")

            manager = SnapshotManager(project_root=str(project_root))
            snapshot_path = manager.save(out_dir=str(snapshot_dir))
            snapshot_name = Path(snapshot_path).name

            # Extract timestamp and convert back to ISO format with colons
            timestamp_normalized = snapshot_name.replace("snapshot-", "").replace(".tar.gz", "")
            timestamp_iso = timestamp_normalized.replace("-", ":", 2)  # Restore colons in time

            # Restore using ISO format (should be normalized internally)
            info = manager.restore(timestamp=timestamp_iso, out_dir=str(snapshot_dir))
            assert info is not None

    def test_snapshot_restore_empty_checkpoint(self) -> None:
        """Test that restore() handles missing checkpoint gracefully."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            prd_file = project_root / "prd.json"
            prd_file.write_text("{}", encoding="utf-8")

            manager = SnapshotManager(project_root=str(project_root))
            snapshot_path = manager.save(out_dir=str(snapshot_dir))
            timestamp = Path(snapshot_path).name.replace("snapshot-", "").replace(".tar.gz", "")

            # Restore (checkpoint file doesn't exist after extraction if not in original)
            info = manager.restore(timestamp=timestamp, out_dir=str(snapshot_dir))
            assert isinstance(info, dict)


class TestSnapshotIntegration:
    """Integration tests for snapshot save and restore."""

    def test_snapshot_roundtrip(self) -> None:
        """Test full save and restore cycle."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            # Create initial state
            prd_file = project_root / "prd.json"
            prd_data = {"userStories": [{"id": "US-001", "title": "Test"}]}
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

            results_file = project_root / "results.tsv"
            results_file.write_text("story_id\tmodel\tstatus\nUS-001\thaiku\tpassed\n", encoding="utf-8")

            # Save snapshot
            manager = SnapshotManager(project_root=str(project_root))
            snapshot_path = manager.save(out_dir=str(snapshot_dir))
            timestamp = Path(snapshot_path).name.replace("snapshot-", "").replace(".tar.gz", "")

            # Modify files
            prd_file.write_text(json.dumps({"userStories": []}), encoding="utf-8")
            results_file.write_text("story_id\tmodel\tstatus\n", encoding="utf-8")

            # Restore
            manager.restore(timestamp=timestamp, out_dir=str(snapshot_dir))

            # Verify restored state
            restored_prd = json.loads(prd_file.read_text(encoding="utf-8"))
            assert restored_prd == prd_data

            restored_results = results_file.read_text(encoding="utf-8")
            assert "US-001" in restored_results
            assert "haiku" in restored_results


class TestSnapshotList:
    """Tests for SnapshotManager.list() method."""

    def test_snapshot_list_empty_directory(self) -> None:
        """Test list() returns empty list when no snapshots exist."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            manager = SnapshotManager(project_root=str(project_root))
            snapshots = manager.list(out_dir=str(snapshot_dir))

            assert snapshots == []

    def test_snapshot_list_ascii(self) -> None:
        """Test list() returns snapshots with correct metadata for ASCII formatting."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            # Create test files
            prd_file = project_root / "prd.json"
            prd_data = {"userStories": [{"id": "US-001"}, {"id": "US-002"}]}
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

            results_file = project_root / "results.tsv"
            results_file.write_text("story_id\tstatus\n", encoding="utf-8")

            # Save snapshot
            manager = SnapshotManager(project_root=str(project_root))
            manager.save(out_dir=str(snapshot_dir))

            # List snapshots
            snapshots = manager.list(out_dir=str(snapshot_dir))

            assert len(snapshots) == 1
            snapshot = snapshots[0]

            # Verify metadata
            assert "timestamp" in snapshot
            assert "size" in snapshot
            assert "size_human" in snapshot
            assert "story_count" in snapshot
            assert "creation_time" in snapshot

            # Verify story count
            assert snapshot["story_count"] == 2

            # Verify size is reasonable (> 0 and < 10MB)
            assert 0 < snapshot["size"] < 10_000_000

            # Verify size_human contains unit
            assert any(unit in snapshot["size_human"] for unit in ("B", "KB", "MB", "GB"))

    def test_snapshot_list_json(self) -> None:
        """Test list() returns valid JSON-serializable data."""
        import time

        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            # Create multiple snapshots
            prd_file = project_root / "prd.json"
            prd_data = {"userStories": [{"id": "US-001"}]}
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

            manager = SnapshotManager(project_root=str(project_root))
            manager.save(out_dir=str(snapshot_dir))

            # Wait to ensure different timestamp
            time.sleep(0.1)

            # Modify and save again
            prd_data["userStories"].append({"id": "US-002"})
            prd_file.write_text(json.dumps(prd_data), encoding="utf-8")
            manager.save(out_dir=str(snapshot_dir))

            # List snapshots
            snapshots = manager.list(out_dir=str(snapshot_dir))

            # Should have at least 1 snapshot (timestamp might be same if very fast)
            assert len(snapshots) >= 1

            # Verify all snapshots are JSON-serializable
            json_str = json.dumps(snapshots)
            parsed = json.loads(json_str)

            assert len(parsed) >= 1
            assert all("timestamp" in s for s in parsed)
            assert all("size" in s for s in parsed)
            assert all("story_count" in s for s in parsed)

    def test_snapshot_list_nonexistent_directory(self) -> None:
        """Test list() returns empty list for nonexistent directory."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            nonexistent_dir = project_root / ".spiral"

            manager = SnapshotManager(project_root=str(project_root))
            snapshots = manager.list(out_dir=str(nonexistent_dir))

            assert snapshots == []

    def test_snapshot_list_corrupted_archive(self) -> None:
        """Test list() skips corrupted archives gracefully."""
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            # Create a valid snapshot
            prd_file = project_root / "prd.json"
            prd_file.write_text('{"userStories": []}', encoding="utf-8")

            manager = SnapshotManager(project_root=str(project_root))
            manager.save(out_dir=str(snapshot_dir))

            # Create a corrupted .tar.gz file
            bad_snapshot = snapshot_dir / "snapshot-2026-01-01T00-00-00Z.tar.gz"
            bad_snapshot.write_text("this is not a valid tarball", encoding="utf-8")

            # List should skip the corrupted archive and return only valid one
            snapshots = manager.list(out_dir=str(snapshot_dir))

            assert len(snapshots) == 1
            assert "T" in snapshots[0]["timestamp"]  # ISO format timestamp

    def test_snapshot_list_timestamp_order(self) -> None:
        """Test list() returns snapshots in chronological order."""
        import time

        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            snapshot_dir = project_root / ".spiral"
            snapshot_dir.mkdir()

            prd_file = project_root / "prd.json"
            prd_file.write_text('{"userStories": []}', encoding="utf-8")

            manager = SnapshotManager(project_root=str(project_root))
            timestamps = []

            # Save multiple snapshots with delay to ensure different timestamps
            for i in range(2):
                path = manager.save(out_dir=str(snapshot_dir))
                timestamps.append(Path(path).name.replace("snapshot-", "").replace(".tar.gz", ""))
                if i < 1:  # Don't sleep after the last save
                    time.sleep(1.1)  # Sleep > 1 second to ensure different timestamps

            # List snapshots
            snapshots = manager.list(out_dir=str(snapshot_dir))

            assert len(snapshots) >= 1

            # Verify timestamps are in order (if multiple snapshots)
            if len(snapshots) > 1:
                for i in range(len(snapshots) - 1):
                    assert snapshots[i]["timestamp"] <= snapshots[i + 1]["timestamp"]
