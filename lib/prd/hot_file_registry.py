"""Hot File Registry — track historically conflict-prone files.

Scans spiral_events.jsonl for merge_conflict_detected events and builds a
persistent .spiral/hot_files.json registry.  Files that repeatedly cause
merge conflicts are flagged as "hot" so partition_prd.py can force stories
touching them onto the same worker, reducing future conflicts.

Usage:
    # Update registry after a parallel run
    python lib/prd/hot_file_registry.py --events .spiral/spiral_events.jsonl \
        --registry .spiral/hot_files.json --iteration 5

    # Query hot files (for partition_prd.py)
    python lib/prd/hot_file_registry.py --registry .spiral/hot_files.json \
        --query --threshold 2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def load_registry(registry_path: str) -> dict[str, Any]:
    """Load the hot file registry from disk. Returns empty structure if missing."""
    if not os.path.isfile(registry_path):
        return {"files": {}, "last_iteration": 0}
    try:
        with open(registry_path, encoding="utf-8") as f:
            data = json.load(f)
        if "files" not in data:
            data["files"] = {}
        if "last_iteration" not in data:
            data["last_iteration"] = 0
        return data
    except (json.JSONDecodeError, OSError):
        return {"files": {}, "last_iteration": 0}


def save_registry(registry: dict[str, Any], registry_path: str) -> None:
    """Atomically write the registry to disk."""
    os.makedirs(os.path.dirname(registry_path) or ".", exist_ok=True)
    tmp = registry_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, registry_path)


def scan_conflict_events(events_path: str) -> list[list[str]]:
    """Scan spiral_events.jsonl for merge_conflict_detected events.

    Returns a list of file-path lists (one per conflict event).
    """
    conflicts: list[list[str]] = []
    if not os.path.isfile(events_path):
        return conflicts
    try:
        with open(events_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if evt.get("event") == "merge_conflict_detected":
                    files = evt.get("conflictingFiles", [])
                    if isinstance(files, list) and files:
                        conflicts.append(files)
    except OSError:
        pass
    return conflicts


def apply_decay(
    registry: dict[str, Any],
    current_iteration: int,
    decay_interval: int = 5,
) -> dict[str, Any]:
    """Halve conflict weights for files not seen in recent iterations.

    Decay fires every `decay_interval` iterations since the file was last seen.
    """
    if decay_interval <= 0:
        return registry
    files = registry.get("files", {})
    to_remove: list[str] = []
    for fpath, info in files.items():
        last_seen = info.get("last_seen_iteration", 0)
        gap = current_iteration - last_seen
        if gap >= decay_interval:
            decays = gap // decay_interval
            info["weight"] = info.get("weight", info.get("count", 1)) / (2**decays)
            if info["weight"] < 0.5:
                to_remove.append(fpath)
    for fpath in to_remove:
        del files[fpath]
    return registry


def update_registry(
    events_path: str,
    registry_path: str,
    current_iteration: int,
    decay_interval: int = 5,
) -> dict[str, Any]:
    """Main entry point: scan events, update counts, apply decay, save.

    Returns the updated registry dict.
    """
    registry = load_registry(registry_path)
    conflicts = scan_conflict_events(events_path)

    files = registry.setdefault("files", {})
    for conflict_files in conflicts:
        for fpath in conflict_files:
            fpath = fpath.replace("\\", "/")
            if fpath in files:
                files[fpath]["count"] = files[fpath].get("count", 0) + 1
                files[fpath]["weight"] = files[fpath]["count"]
                files[fpath]["last_seen_iteration"] = current_iteration
            else:
                files[fpath] = {
                    "count": 1,
                    "weight": 1.0,
                    "first_seen_iteration": current_iteration,
                    "last_seen_iteration": current_iteration,
                }

    registry = apply_decay(registry, current_iteration, decay_interval)
    registry["last_iteration"] = current_iteration
    save_registry(registry, registry_path)
    return registry


def get_hot_files(
    registry_path: str,
    threshold: int = 2,
) -> set[str]:
    """Return the set of file paths whose conflict weight >= threshold.

    Used by partition_prd.py for hard co-location constraints.
    """
    registry = load_registry(registry_path)
    hot: set[str] = set()
    for fpath, info in registry.get("files", {}).items():
        weight = info.get("weight", info.get("count", 0))
        if weight >= threshold:
            hot.add(fpath)
    return hot


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Hot File Registry for SPIRAL parallel workers")
    parser.add_argument("--events", default=".spiral/spiral_events.jsonl", help="Path to spiral_events.jsonl")
    parser.add_argument("--registry", default=".spiral/hot_files.json", help="Path to hot_files.json")
    parser.add_argument("--iteration", type=int, default=0, help="Current iteration number")
    parser.add_argument("--decay-interval", type=int, default=5, help="Halve weight every N iterations")
    parser.add_argument("--query", action="store_true", help="Query mode: print hot files and exit")
    parser.add_argument("--threshold", type=int, default=2, help="Min weight to flag as hot (query mode)")
    args = parser.parse_args()

    if args.query:
        hot = get_hot_files(args.registry, args.threshold)
        if hot:
            print(f"[hot-files] {len(hot)} hot file(s) (threshold={args.threshold}):")
            for f in sorted(hot):
                print(f"  {f}")
        else:
            print("[hot-files] No hot files above threshold")
        return 0

    registry = update_registry(args.events, args.registry, args.iteration, args.decay_interval)
    n_files = len(registry.get("files", {}))
    hot_list = [f for f, info in registry.get("files", {}).items() if info.get("weight", 0) >= args.threshold]
    print(f"[hot-files] Registry updated: {n_files} tracked, {len(hot_list)} hot (threshold={args.threshold})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
