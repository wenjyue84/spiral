"""tests/test_archive_checkpoint.py — Integration tests for archive-checkpoint (US-643)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

# Add lib/commands to path for direct imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "commands"))
from archive_checkpoint import archive, read_manifest, restore  # type: ignore[import-untyped]

# ── helpers ──────────────────────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal SPIRAL project layout."""
    root = tmp_path / "project"
    root.mkdir()

    # prd.json with 3 stories, 2 passing
    prd = {
        "userStories": [
            {"id": "US-001", "title": "Story A", "passes": True},
            {"id": "US-002", "title": "Story B", "passes": True},
            {"id": "US-003", "title": "Story C", "passes": False},
        ]
    }
    (root / "prd.json").write_text(json.dumps(prd, indent=2), encoding="utf-8")

    # results.tsv
    (root / "results.tsv").write_text(
        "story_id\tmodel\tstatus\nUS-001\tsonnet\tpass\nUS-002\tsonnet\tpass\n",
        encoding="utf-8",
    )

    # .spiral/ directory with checkpoint
    spiral_dir = root / ".spiral"
    spiral_dir.mkdir()
    checkpoint = {"iteration": 5, "phase": "I", "timestamp": "2026-03-21T10:00:00Z"}
    (spiral_dir / "_checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    (spiral_dir / "audit.log").write_text("some log content", encoding="utf-8")

    return root


# ── AC1: archive creates valid tar.gz with manifest ──────────────────────────


def test_archive_creates_tarball(tmp_path: Path) -> None:
    """AC1: archive command creates compressed archive with required files."""
    root = _make_project(tmp_path)
    output = tmp_path / "backup-iter-5.tar.gz"

    manifest = archive(root, output)

    assert output.exists(), "Archive file was not created"
    assert output.stat().st_size > 0, "Archive is empty"
    assert manifest["total_stories"] == 3
    assert manifest["passing_stories"] == 2
    assert manifest["iteration"] == 5
    assert "timestamp" in manifest
    assert "archive_size_mb" in manifest
    assert isinstance(manifest["archive_size_mb"], float)


def test_archive_contains_required_members(tmp_path: Path) -> None:
    """AC1: archive includes prd.json, results.tsv, .spiral/, manifest.json."""
    import tarfile

    root = _make_project(tmp_path)
    output = tmp_path / "backup.tar.gz"
    archive(root, output)

    with tarfile.open(output, "r:gz") as tar:
        names = tar.getnames()

    assert "prd.json" in names, f"prd.json missing from archive. Found: {names}"
    assert "results.tsv" in names, f"results.tsv missing from archive. Found: {names}"
    assert "manifest.json" in names, f"manifest.json missing from archive. Found: {names}"
    # .spiral/_checkpoint.json should be present
    assert any(n.startswith(".spiral/") for n in names), ".spiral/ directory not archived"


# ── AC2: manifest.json has required fields ────────────────────────────────────


def test_manifest_fields(tmp_path: Path) -> None:
    """AC2: manifest.json includes iteration, timestamp, total_stories, passing_stories, archive_size_mb."""
    root = _make_project(tmp_path)
    output = tmp_path / "backup.tar.gz"
    archive(root, output)

    manifest = read_manifest(output)

    required_fields = ["iteration", "timestamp", "total_stories", "passing_stories", "archive_size_mb"]
    for field in required_fields:
        assert field in manifest, f"manifest.json missing field: {field}"

    assert manifest["iteration"] == 5
    assert manifest["total_stories"] == 3
    assert manifest["passing_stories"] == 2
    assert isinstance(manifest["archive_size_mb"], (int, float))
    # Timestamp should be ISO 8601
    assert "T" in manifest["timestamp"] and "Z" in manifest["timestamp"]


def test_manifest_checksums_present(tmp_path: Path) -> None:
    """AC2: manifest.json includes checksums dict."""
    root = _make_project(tmp_path)
    output = tmp_path / "backup.tar.gz"
    archive(root, output)

    manifest = read_manifest(output)
    assert "checksums" in manifest
    checksums = manifest["checksums"]
    assert "prd.json" in checksums
    assert "results.tsv" in checksums
    # Each checksum should be a 64-char hex string (SHA-256)
    for path_key, sha in checksums.items():
        assert len(sha) == 64, f"Checksum for {path_key} is not SHA-256: {sha}"


# ── AC3: archive → corrupt → restore → checksum verification ─────────────────


def test_restore_recovers_all_files(tmp_path: Path) -> None:
    """AC3: restore from archive recovers files with identical checksums."""
    root = _make_project(tmp_path)
    output = tmp_path / "backup.tar.gz"

    # Capture original checksums
    original_prd_sha = _sha256(root / "prd.json")
    original_tsv_sha = _sha256(root / "results.tsv")

    archive(root, output)

    # Corrupt prd.json
    (root / "prd.json").write_text('{"userStories": []}', encoding="utf-8")
    assert _sha256(root / "prd.json") != original_prd_sha, "Corruption did not change checksum"

    # Restore from archive
    verified = restore(output, root)

    # prd.json should be restored with original checksum
    restored_prd_sha = _sha256(root / "prd.json")
    assert restored_prd_sha == original_prd_sha, (
        f"prd.json checksum mismatch after restore: {restored_prd_sha} != {original_prd_sha}"
    )
    assert _sha256(root / "results.tsv") == original_tsv_sha

    # verify dict should include prd.json
    assert "prd.json" in verified


def test_restore_raises_on_missing_archive(tmp_path: Path) -> None:
    """AC3: restore raises FileNotFoundError if archive does not exist."""
    with pytest.raises(FileNotFoundError):
        restore(tmp_path / "nonexistent.tar.gz", tmp_path)


def test_restore_detects_checksum_mismatch(tmp_path: Path) -> None:
    """AC3: restore raises ValueError if a restored file has wrong checksum (tampered archive)."""
    import io
    import tarfile

    root = _make_project(tmp_path)
    output = tmp_path / "backup.tar.gz"
    archive(root, output)

    # Tamper with the archive: replace prd.json with different content but keep old checksum in manifest
    tampered = tmp_path / "tampered.tar.gz"
    import shutil

    shutil.copy(output, tampered)

    # Read current manifest
    read_manifest(tampered)

    # Re-pack with tampered prd.json but original manifest checksums
    with tarfile.open(tampered, "w:gz") as out_tar:
        with tarfile.open(output, "r:gz") as in_tar:
            for member in in_tar.getmembers():
                if member.name == "prd.json":
                    # Write different content
                    bad_content = b'{"userStories": []}'
                    info = tarfile.TarInfo(name="prd.json")
                    info.size = len(bad_content)
                    out_tar.addfile(info, io.BytesIO(bad_content))
                elif member.name == "manifest.json":
                    # Keep original manifest (with old checksum) so mismatch is detected
                    f = in_tar.extractfile(member)
                    if f:
                        data = f.read()
                        info = tarfile.TarInfo(name="manifest.json")
                        info.size = len(data)
                        out_tar.addfile(info, io.BytesIO(data))
                else:
                    f = in_tar.extractfile(member)
                    if f:
                        out_tar.addfile(member, f)
                    else:
                        out_tar.addfile(member)

    with pytest.raises(ValueError, match="Checksum mismatch"):
        restore(tampered, root)


def test_no_workers_excludes_workers_dir(tmp_path: Path) -> None:
    """archive --no-workers excludes .spiral-workers/ from the archive."""
    import tarfile

    root = _make_project(tmp_path)
    workers_dir = root / ".spiral-workers"
    workers_dir.mkdir()
    (workers_dir / "worker-1.log").write_text("log content", encoding="utf-8")

    output = tmp_path / "backup.tar.gz"
    archive(root, output, include_workers=False)

    with tarfile.open(output, "r:gz") as tar:
        names = tar.getnames()

    assert not any(n.startswith(".spiral-workers") for n in names), (
        ".spiral-workers should be excluded when include_workers=False"
    )


def test_archive_workers_included_by_default(tmp_path: Path) -> None:
    """archive includes .spiral-workers/ by default when it exists."""
    import tarfile

    root = _make_project(tmp_path)
    workers_dir = root / ".spiral-workers"
    workers_dir.mkdir()
    (workers_dir / "worker-1.log").write_text("log content", encoding="utf-8")

    output = tmp_path / "backup.tar.gz"
    archive(root, output, include_workers=True)

    with tarfile.open(output, "r:gz") as tar:
        names = tar.getnames()

    assert any(n.startswith(".spiral-workers") for n in names), ".spiral-workers should be included by default"
