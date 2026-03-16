"""invocation_snapshot.py -- Per-story invocation snapshots for post-mortem replay (US-362).

Stores forensic records in .spiral/invocations/{story_id}.json containing the exact
story JSON, Ralph invocation flags, model selected, timestamps, and outcome.
Enables debugging failed stories without re-running the full loop.

Usage (CLI):
    python invocation_snapshot.py write DIR --story-id ID --story-json FILE [--model MODEL] [--ralph-flags FLAGS] [--iteration N]
    python invocation_snapshot.py finish DIR --story-id ID --returncode RC [--stdout-head TEXT]
    python invocation_snapshot.py read DIR --story-id ID
    python invocation_snapshot.py prune DIR [--retention N]
    python invocation_snapshot.py list DIR
"""

import argparse
import gzip
import json
import os
import sys
import time
from typing import Any


def _invocations_dir(base_dir: str) -> str:
    """Return the invocations subdirectory, creating it if needed."""
    d = os.path.join(base_dir, "invocations")
    os.makedirs(d, exist_ok=True)
    return d


def _snapshot_path(base_dir: str, story_id: str) -> str:
    return os.path.join(_invocations_dir(base_dir), f"{story_id}.json")


def write_snapshot(
    base_dir: str,
    story_id: str,
    story_json: dict[str, Any],
    iteration: int = 0,
    phase: str = "I",
    model: str = "",
    ralph_flags: str = "",
) -> str:
    """Write a pre-invocation snapshot. Returns the snapshot file path."""
    snapshot: dict[str, Any] = {
        "story_id": story_id,
        "iteration": iteration,
        "phase": phase,
        "model": model,
        "ralph_flags": ralph_flags,
        "story_json": story_json,
        "ts_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ts_end": None,
        "rc": None,
        "stdout_head": None,
    }
    path = _snapshot_path(base_dir, story_id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def finish_snapshot(
    base_dir: str,
    story_id: str,
    returncode: int,
    stdout_head: str = "",
) -> str | None:
    """Append completion data to an existing snapshot. Returns path or None."""
    path = _snapshot_path(base_dir, story_id)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        snapshot = json.load(f)
    snapshot["ts_end"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    snapshot["rc"] = returncode
    snapshot["stdout_head"] = stdout_head[:2000] if stdout_head else ""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def read_snapshot(base_dir: str, story_id: str) -> dict[str, Any] | None:
    """Read a snapshot, returning None if it doesn't exist."""
    path = _snapshot_path(base_dir, story_id)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def list_snapshots(base_dir: str) -> list[dict[str, Any]]:
    """List all snapshots as summary dicts."""
    inv_dir = os.path.join(base_dir, "invocations")
    if not os.path.isdir(inv_dir):
        return []
    results: list[dict[str, Any]] = []
    for fname in sorted(os.listdir(inv_dir)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(inv_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            results.append({
                "story_id": snap.get("story_id", fname.replace(".json", "")),
                "iteration": snap.get("iteration", 0),
                "model": snap.get("model", ""),
                "rc": snap.get("rc"),
                "ts_start": snap.get("ts_start", ""),
                "ts_end": snap.get("ts_end", ""),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return results


def prune_snapshots(base_dir: str, current_iteration: int, retention: int = 7) -> int:
    """Remove snapshots older than `retention` iterations. Returns count removed."""
    inv_dir = os.path.join(base_dir, "invocations")
    if not os.path.isdir(inv_dir):
        return 0
    cutoff = current_iteration - retention
    removed = 0
    for fname in os.listdir(inv_dir):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(inv_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            if snap.get("iteration", 0) < cutoff:
                os.remove(path)
                removed += 1
        except (json.JSONDecodeError, OSError):
            continue
    return removed


def compress_snapshot(base_dir: str, story_id: str) -> str | None:
    """Gzip-compress a snapshot file. Returns .json.gz path or None."""
    path = _snapshot_path(base_dir, story_id)
    if not os.path.isfile(path):
        return None
    gz_path = path + ".gz"
    with open(path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
        f_out.write(f_in.read())
    os.remove(path)
    return gz_path


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SPIRAL invocation snapshot manager")
    sub = parser.add_subparsers(dest="command", required=True)

    # write
    p_write = sub.add_parser("write", help="Write pre-invocation snapshot")
    p_write.add_argument("dir", help="Scratch directory (.spiral)")
    p_write.add_argument("--story-id", required=True)
    p_write.add_argument("--story-json", required=True, help="Path to story JSON file")
    p_write.add_argument("--model", default="")
    p_write.add_argument("--ralph-flags", default="")
    p_write.add_argument("--iteration", type=int, default=0)
    p_write.add_argument("--phase", default="I")

    # finish
    p_finish = sub.add_parser("finish", help="Append completion data")
    p_finish.add_argument("dir", help="Scratch directory (.spiral)")
    p_finish.add_argument("--story-id", required=True)
    p_finish.add_argument("--returncode", type=int, required=True)
    p_finish.add_argument("--stdout-head", default="")

    # read
    p_read = sub.add_parser("read", help="Read a snapshot")
    p_read.add_argument("dir", help="Scratch directory (.spiral)")
    p_read.add_argument("--story-id", required=True)

    # prune
    p_prune = sub.add_parser("prune", help="Prune old snapshots")
    p_prune.add_argument("dir", help="Scratch directory (.spiral)")
    p_prune.add_argument("--iteration", type=int, required=True, help="Current iteration")
    p_prune.add_argument("--retention", type=int, default=7)

    # list
    p_list = sub.add_parser("list", help="List all snapshots")
    p_list.add_argument("dir", help="Scratch directory (.spiral)")

    args = parser.parse_args(argv)

    if args.command == "write":
        with open(args.story_json, "r", encoding="utf-8") as f:
            story = json.load(f)
        path = write_snapshot(
            args.dir,
            args.story_id,
            story,
            iteration=args.iteration,
            phase=args.phase,
            model=args.model,
            ralph_flags=args.ralph_flags,
        )
        print(path)

    elif args.command == "finish":
        finish_path = finish_snapshot(
            args.dir,
            args.story_id,
            args.returncode,
            stdout_head=args.stdout_head,
        )
        if finish_path:
            print(finish_path)
        else:
            print(f"No snapshot found for {args.story_id}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "read":
        snap = read_snapshot(args.dir, args.story_id)
        if snap:
            json.dump(snap, sys.stdout, indent=2, ensure_ascii=False)
            print()
        else:
            print(f"No snapshot found for {args.story_id}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "prune":
        removed = prune_snapshots(args.dir, args.iteration, args.retention)
        print(f"Pruned {removed} snapshot(s)")

    elif args.command == "list":
        snaps = list_snapshots(args.dir)
        if snaps:
            json.dump(snaps, sys.stdout, indent=2, ensure_ascii=False)
            print()
        else:
            print("[]")


if __name__ == "__main__":
    main()
