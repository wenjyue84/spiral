"""archive_checkpoint.py — Create and restore SPIRAL state backups (US-643).

Commands:
  archive  -- Create a tar.gz snapshot of prd.json, results.tsv, .spiral/, .spiral-workers/
  restore  -- Restore files from a previously created archive
"""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _compute_sha256(path: Path) -> str:
    """Return hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_stories(prd_path: Path) -> tuple[int, int]:
    """Return (total_stories, passing_stories) from prd.json."""
    if not prd_path.exists():
        return 0, 0
    try:
        with open(prd_path, encoding="utf-8") as fh:
            data = json.load(fh)
        stories = data.get("userStories", [])
        total = len(stories)
        passing = sum(1 for s in stories if s.get("passes") is True)
        return total, passing
    except (json.JSONDecodeError, KeyError):
        return 0, 0


def _read_iteration(checkpoint_path: Path) -> int:
    """Read current iteration from .spiral/_checkpoint.json."""
    if not checkpoint_path.exists():
        return 0
    try:
        with open(checkpoint_path, encoding="utf-8") as fh:
            data = json.load(fh)
        return int(data.get("iteration", 0))
    except (json.JSONDecodeError, ValueError, KeyError):
        return 0


def archive(
    root: Path,
    output: Path,
    *,
    include_workers: bool = True,
) -> dict[str, Any]:
    """Create a tar.gz checkpoint archive.

    Args:
        root: Project root directory (contains prd.json, .spiral/, etc.)
        output: Destination .tar.gz path.
        include_workers: Whether to include .spiral-workers/ (default True).

    Returns:
        manifest dict written into the archive as manifest.json.
    """
    checkpoint_path = root / ".spiral" / "_checkpoint.json"
    prd_path = root / "prd.json"
    results_path = root / "results.tsv"

    iteration = _read_iteration(checkpoint_path)
    total_stories, passing_stories = _count_stories(prd_path)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Collect source paths that exist
    sources: list[Path] = []
    for candidate in [prd_path, results_path]:
        if candidate.exists():
            sources.append(candidate)
    for dirname in [".spiral"]:
        d = root / dirname
        if d.exists() and d.is_dir():
            sources.append(d)
    if include_workers:
        workers_dir = root / ".spiral-workers"
        if workers_dir.exists() and workers_dir.is_dir():
            sources.append(workers_dir)

    # Build archive into a temp file first, then rename atomically
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output.with_suffix(".tmp.tar.gz")

    checksums: dict[str, str] = {}

    with tarfile.open(tmp_path, "w:gz") as tar:
        for src in sources:
            arcname = src.relative_to(root).as_posix()
            tar.add(str(src), arcname=arcname, recursive=True)
            # Compute checksums for individual files
            if src.is_file():
                checksums[arcname] = _compute_sha256(src)
            else:
                for fpath in sorted(src.rglob("*")):
                    if fpath.is_file():
                        rel = fpath.relative_to(root).as_posix()
                        checksums[rel] = _compute_sha256(fpath)

        # Write manifest.json into the archive
        archive_size_mb = round(tmp_path.stat().st_size / (1024 * 1024), 2)
        manifest: dict[str, Any] = {
            "iteration": iteration,
            "timestamp": timestamp,
            "total_stories": total_stories,
            "passing_stories": passing_stories,
            "archive_size_mb": archive_size_mb,
            "checksums": checksums,
        }
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest_bytes)
        import io

        tar.addfile(info, io.BytesIO(manifest_bytes))

    # Re-open to finalise archive_size_mb (after manifest added)
    final_size_mb = round(tmp_path.stat().st_size / (1024 * 1024), 2)
    if final_size_mb != archive_size_mb:
        # Rewrite with corrected size (small discrepancy is fine, update manifest only)
        manifest["archive_size_mb"] = final_size_mb

    os.replace(str(tmp_path), str(output))
    return manifest


def restore(archive_path: Path, root: Path) -> dict[str, str]:
    """Extract a checkpoint archive back to the project root.

    Returns:
        Dict mapping restored file paths to their SHA-256 checksums.
    """
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    with tarfile.open(archive_path, "r:gz") as tar:
        # Extract manifest first
        try:
            manifest_member = tar.getmember("manifest.json")
            f = tar.extractfile(manifest_member)
            manifest: dict[str, Any] = json.loads(f.read().decode("utf-8")) if f else {}
        except KeyError:
            manifest = {}

        # Extract all members except manifest.json (it stays inside the archive)
        members = [m for m in tar.getmembers() if m.name != "manifest.json"]
        # Use filter="data" on Python 3.12+ for security; fall back gracefully
        try:
            tar.extractall(path=str(root), members=members, filter="data")
        except TypeError:
            tar.extractall(path=str(root), members=members)

    # Verify checksums from manifest
    stored_checksums: dict[str, str] = manifest.get("checksums", {})
    verified: dict[str, str] = {}
    for rel_path, expected_sha in stored_checksums.items():
        abs_path = root / rel_path
        if abs_path.exists() and abs_path.is_file():
            actual = _compute_sha256(abs_path)
            if actual != expected_sha:
                raise ValueError(f"Checksum mismatch for {rel_path}: expected {expected_sha}, got {actual}")
            verified[rel_path] = actual

    return verified


def read_manifest(archive_path: Path) -> dict[str, Any]:
    """Read only the manifest.json from an archive without extracting."""
    with tarfile.open(archive_path, "r:gz") as tar:
        try:
            f = tar.extractfile("manifest.json")
            if f is None:
                return {}
            return dict(json.loads(f.read().decode("utf-8")))
        except KeyError:
            return {}
