#!/usr/bin/env python3
"""
snapshot.py — Save and restore SPIRAL project state snapshots.

Snapshots preserve prd.json, results.tsv, .spiral/checkpoint.json, and retry-counts.json
as timestamped tarballs (.spiral/snapshot-<ISO8601>.tar.gz).

Usage:
  python lib/snapshot.py save [--out-dir .spiral]
  python lib/snapshot.py restore <timestamp> [--out-dir .spiral]
"""

import argparse
import json
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SnapshotManager:
    """Manages SPIRAL project state snapshots."""

    # Files to include in snapshots (relative to project root)
    SNAPSHOT_FILES = [
        "prd.json",
        "results.tsv",
        ".spiral/checkpoint.json",
        "retry-counts.json",
    ]

    def __init__(self, project_root: str | None = None) -> None:
        """Initialize SnapshotManager.

        Args:
            project_root: Root directory of the project (defaults to cwd)
        """
        self.project_root = Path(project_root or ".")

    def save(self, out_dir: str = ".spiral") -> str:
        """Save a snapshot of the current project state.

        Creates a timestamped tarball containing prd.json, results.tsv,
        .spiral/checkpoint.json, and retry-counts.json.

        Args:
            out_dir: Output directory for the snapshot (defaults to .spiral)

        Returns:
            Path to the created snapshot file

        Raises:
            FileNotFoundError: If output directory does not exist
            RuntimeError: If no files could be added to the snapshot
        """
        out_path = Path(out_dir)
        if not out_path.exists():
            raise FileNotFoundError(f"Output directory does not exist: {out_dir}")

        # Create ISO8601 timestamp (format: YYYY-MM-DDTHH-mm-ssZ)
        now = datetime.now(timezone.utc)
        # isoformat() gives: 2026-04-27T12:34:56.123456+00:00
        iso_str = now.isoformat()
        # Replace time colons with dashes, remove microseconds and timezone
        time_part = iso_str.split("+")[0]  # Remove timezone offset
        if "." in time_part:
            time_part = time_part.split(".")[0]  # Remove microseconds
        timestamp = time_part.replace(":", "-") + "Z"

        snapshot_filename = f"snapshot-{timestamp}.tar.gz"
        snapshot_path = out_path / snapshot_filename

        # Create tarball with snapshots files
        files_added = 0
        with tarfile.open(snapshot_path, "w:gz") as tar:
            for file_rel in self.SNAPSHOT_FILES:
                file_abs = self.project_root / file_rel
                if file_abs.exists():
                    # Add file to tar with relative path
                    tar.add(file_abs, arcname=file_rel)
                    files_added += 1

        if files_added == 0:
            snapshot_path.unlink()  # Remove empty tarball
            raise RuntimeError(
                f"No snapshot files found. Expected to find at least one of: {', '.join(self.SNAPSHOT_FILES)}"
            )

        return str(snapshot_path)

    def restore(self, timestamp: str, out_dir: str = ".spiral") -> dict[str, Any]:
        """Restore a project snapshot.

        Extracts the snapshot tarball matching the given timestamp and overwrites
        the current prd.json and results.tsv. Also extracts checkpoint info.

        Args:
            timestamp: ISO8601 timestamp of the snapshot to restore
            out_dir: Directory where snapshots are stored (defaults to .spiral)

        Returns:
            Dictionary with checkpoint resume info (iter, phase, ts)

        Raises:
            FileNotFoundError: If no matching snapshot is found
            RuntimeError: If extraction fails
        """
        out_path = Path(out_dir)

        # Normalize timestamp (convert colons to dashes if needed, add Z suffix)
        if ":" in timestamp:
            timestamp = timestamp.replace(":", "-")
        if not timestamp.endswith("Z"):
            timestamp = f"{timestamp}Z"

        snapshot_filename = f"snapshot-{timestamp}.tar.gz"
        snapshot_path = out_path / snapshot_filename

        if not snapshot_path.exists():
            # Try to find similar snapshots for better error message
            available = sorted(out_path.glob("snapshot-*.tar.gz"))
            if available:
                raise FileNotFoundError(
                    f"Snapshot not found: {snapshot_filename}\n"
                    f"Available snapshots:\n" + "\n".join(f"  {s.name}" for s in available[-5:])
                )
            raise FileNotFoundError(f"Snapshot not found: {snapshot_filename} (no snapshots found in {out_dir})")

        # Extract tarball, overwriting existing files
        with tarfile.open(snapshot_path, "r:gz") as tar:
            # Use filter='data' to extract only file data, ignore metadata like owners/permissions
            tar.extractall(path=self.project_root, filter="data")

        # Read and return checkpoint info if available
        checkpoint_path = self.project_root / ".spiral" / "checkpoint.json"
        checkpoint_info = {}
        if checkpoint_path.exists():
            try:
                with open(checkpoint_path, encoding="utf-8") as f:
                    checkpoint_data = json.load(f)
                    checkpoint_info = {
                        "iter": checkpoint_data.get("iter", "?"),
                        "phase": checkpoint_data.get("phase", "?"),
                        "ts": checkpoint_data.get("ts", "?"),
                    }
            except (json.JSONDecodeError, OSError):
                pass

        return checkpoint_info

    def list(self, out_dir: str = ".spiral") -> list[dict[str, Any]]:
        """List all snapshots in the given directory with metadata.

        Scans the output directory for snapshot archives and returns metadata
        including timestamp, file size (human-readable), story count from prd.json,
        and creation time.

        Args:
            out_dir: Directory containing snapshots (defaults to .spiral)

        Returns:
            List of dicts with keys: timestamp, size, size_human, story_count, creation_time
        """
        out_path = Path(out_dir)
        snapshots = []

        if not out_path.exists():
            return []

        for snapshot_path in sorted(out_path.glob("snapshot-*.tar.gz")):
            try:
                # Extract timestamp from filename
                timestamp = snapshot_path.name.replace("snapshot-", "").replace(".tar.gz", "")

                # Get file size
                size_bytes = snapshot_path.stat().st_size
                size_human = self._human_readable_size(size_bytes)

                # Get creation time from file
                creation_time = datetime.fromtimestamp(snapshot_path.stat().st_mtime, tz=timezone.utc).isoformat()

                # Extract story count from prd.json inside archive
                story_count = 0
                try:
                    with tarfile.open(snapshot_path, "r:gz") as tar:
                        # Try to read prd.json from tarball
                        try:
                            prd_member = tar.getmember("prd.json")
                            f = tar.extractfile(prd_member)
                            if f:
                                prd_data = json.loads(f.read().decode("utf-8"))
                                story_count = len(prd_data.get("userStories", []))
                        except (KeyError, OSError, json.JSONDecodeError):
                            # Archive doesn't have prd.json or it's malformed
                            story_count = 0
                except (tarfile.TarError, OSError):
                    # Can't read archive, skip
                    continue

                snapshots.append(
                    {
                        "timestamp": timestamp,
                        "size": size_bytes,
                        "size_human": size_human,
                        "story_count": story_count,
                        "creation_time": creation_time,
                    }
                )
            except Exception:
                # Skip corrupted snapshots
                continue

        return snapshots

    @staticmethod
    def _human_readable_size(size_bytes: int) -> str:
        """Convert bytes to human-readable format."""
        size_float = float(size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size_float < 1024:
                return f"{size_float:.1f} {unit}"
            size_float /= 1024
        return f"{size_float:.1f} TB"


def main() -> None:
    """CLI entry point for snapshot operations."""
    parser = argparse.ArgumentParser(description="Save and restore SPIRAL project state snapshots")
    parser.add_argument("command", choices=["save", "restore"], help="save or restore")
    parser.add_argument(
        "timestamp",
        nargs="?",
        help="Timestamp for restore (ISO8601 format, e.g., 2026-04-27T12-34-56Z)",
    )
    parser.add_argument(
        "--out-dir",
        default=".spiral",
        help="Directory for snapshots (default: .spiral)",
    )
    parser.add_argument("--project-root", default=".", help="Project root directory (default: .)")

    args = parser.parse_args()
    manager = SnapshotManager(project_root=args.project_root)

    try:
        if args.command == "save":
            path = manager.save(out_dir=args.out_dir)
            print(f"[spiral] Snapshot saved: {path}")
            sys.exit(0)

        elif args.command == "restore":
            if not args.timestamp:
                print("[spiral] ERROR: restore requires timestamp argument", file=sys.stderr)
                sys.exit(1)
            info = manager.restore(timestamp=args.timestamp, out_dir=args.out_dir)
            print(f"[spiral] Snapshot restored from {args.timestamp}")
            if info:
                print(f"[spiral] Checkpoint: iteration {info['iter']}, phase {info['phase']}, ts {info['ts']}")
            sys.exit(0)

    except (FileNotFoundError, RuntimeError) as e:
        print(f"[spiral] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[spiral] FATAL: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
