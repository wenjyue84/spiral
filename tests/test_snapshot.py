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
