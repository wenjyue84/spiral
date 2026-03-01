#!/usr/bin/env python3
"""
SPIRAL Parallel Phase — Partition PRD
Splits pending stories into N worker prd.json files using:
  1. Priority-aware ordering: critical → high → medium → low
  2. Dependency-grouped assignment: stories with pending deps go to the same worker
  3. File-overlap co-location: stories touching the same files go to the same worker

Completed stories are included in every worker file (ralph needs them for dep checks).

Query modes (exit after printing):
  --wave-count N   Print number of pending stories at topological level N
  --list-waves     Print total number of topological levels
  --wave-level N   Only partition stories at topological level N
"""
import argparse
import json
import os
import sys

# Force UTF-8 stdout — prevents UnicodeEncodeError on Windows cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def priority_key(story: dict) -> int:
    return PRIORITY_RANK.get(story.get("priority", "medium"), 2)


def compute_levels(pending: list[dict]) -> dict[str, int]:
    """
    Compute topological levels for pending stories based on dependencies.
    Level 0 = stories with no pending dependencies (ready to run).
    Level N = stories whose pending deps are all at level < N.
    Returns: {story_id: level}
    """
    pending_ids = {s["id"] for s in pending}

    # Build adjacency: story_id → set of pending deps
    deps: dict[str, set[str]] = {}
    for s in pending:
        deps[s["id"]] = {d for d in s.get("dependencies", []) if d in pending_ids}

    levels: dict[str, int] = {}
    assigned: set[str] = set()
    level = 0

    while len(assigned) < len(pending):
        # Stories whose unassigned deps are all already assigned
        batch = [sid for sid in pending_ids - assigned if deps[sid] <= assigned]

        if not batch:
            # Circular dependency — assign remaining at current level
            for sid in pending_ids - assigned:
                levels[sid] = level
            break

        for sid in batch:
            levels[sid] = level
            assigned.add(sid)

        level += 1

    return levels


def get_files_to_touch(story: dict) -> set[str]:
    """Extract filesTouch from story, checking both top-level and technicalHints."""
    files = set(story.get("filesTouch", []))
    if not files:
        hints = story.get("technicalHints", {})
        if isinstance(hints, dict):
            files = set(hints.get("filesTouch", []))
    return files


def assign_stories(pending: list[dict], n_workers: int) -> list[list[dict]]:
    """
    Assign pending stories to n worker buckets:
    1. Sort all pending stories by priority (critical first).
    2. Co-locate a story with its already-assigned pending dependency's worker.
    3. Co-locate a story with a worker that already touches the same files.
    4. Otherwise assign to the least-loaded worker.
    """
    if not pending:
        return [[] for _ in range(n_workers)]

    pending_ids = {s["id"] for s in pending}

    # Sort by priority so high-priority stories get bucket assignment before low-priority
    pending_sorted = sorted(pending, key=priority_key)

    buckets: list[list[dict]] = [[] for _ in range(n_workers)]
    assignments: dict[str, int] = {}   # story_id → bucket index
    file_to_worker: dict[str, int] = {}  # file_path → bucket index

    for story in pending_sorted:
        sid = story["id"]

        # 1. Dependency co-location: co-locate with an already-assigned pending dep
        deps_pending = [d for d in story.get("dependencies", []) if d in pending_ids]
        assigned_worker: int | None = None
        for dep_id in deps_pending:
            if dep_id in assignments:
                assigned_worker = assignments[dep_id]
                break

        # 2. File-overlap co-location: co-locate with a worker touching the same files
        files_hint = get_files_to_touch(story)
        if assigned_worker is None:
            for f in files_hint:
                if f in file_to_worker:
                    assigned_worker = file_to_worker[f]
                    break

        # 3. Least-loaded fallback
        if assigned_worker is None:
            assigned_worker = min(range(n_workers), key=lambda i: len(buckets[i]))

        buckets[assigned_worker].append(story)
        assignments[sid] = assigned_worker

        # Register all files for this story with the assigned worker
        for f in files_hint:
            file_to_worker.setdefault(f, assigned_worker)

    return buckets


def main() -> int:
    parser = argparse.ArgumentParser(description="Partition prd.json for parallel ralph workers")
    parser.add_argument("--prd", required=True, help="Path to main prd.json")
    parser.add_argument("--workers", type=int, default=0, help="Number of workers")
    parser.add_argument("--outdir", default="", help="Output directory for worker prd files")

    # Query modes
    parser.add_argument("--wave-count", type=int, default=None, metavar="N",
                        help="Print number of pending stories at topological level N, then exit")
    parser.add_argument("--list-waves", action="store_true",
                        help="Print total number of topological levels, then exit")
    parser.add_argument("--wave-level", type=int, default=None, metavar="N",
                        help="Only partition stories at topological level N")

    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"[partition] ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    with open(args.prd, encoding="utf-8") as f:
        prd = json.load(f)

    stories = prd.get("userStories", [])
    completed = [s for s in stories if s.get("passes")]
    pending = [s for s in stories if not s.get("passes")]

    # ── Query mode: --list-waves ──────────────────────────────────────────────
    if args.list_waves:
        if not pending:
            print("0")
            return 0
        levels = compute_levels(pending)
        max_level = max(levels.values()) + 1 if levels else 0
        print(str(max_level))
        return 0

    # ── Query mode: --wave-count N ────────────────────────────────────────────
    if args.wave_count is not None:
        if not pending:
            print("0")
            return 0
        levels = compute_levels(pending)
        count = sum(1 for lvl in levels.values() if lvl == args.wave_count)
        print(str(count))
        return 0

    # ── Partition mode ────────────────────────────────────────────────────────
    if args.workers < 2:
        print("[partition] ERROR: --workers must be >= 2", file=sys.stderr)
        return 1

    if not args.outdir:
        print("[partition] ERROR: --outdir is required for partition mode", file=sys.stderr)
        return 1

    # Filter to specific wave level if requested
    if args.wave_level is not None:
        if not pending:
            print("[partition] No pending stories — nothing to partition")
            return 0
        levels = compute_levels(pending)
        pending = [s for s in pending if levels.get(s["id"]) == args.wave_level]
        print(f"[partition] Filtered to wave level {args.wave_level}: {len(pending)} stories")

    print(f"[partition] {len(completed)} completed, {len(pending)} pending → {args.workers} workers")

    if not pending:
        print("[partition] No pending stories — nothing to partition")
        return 0

    buckets = assign_stories(pending, args.workers)

    os.makedirs(args.outdir, exist_ok=True)

    for i, bucket in enumerate(buckets):
        worker_num = i + 1
        worker_prd = dict(prd)
        # All completed stories (for dependency resolution) + this worker's pending stories
        worker_prd["userStories"] = completed + bucket
        out_path = os.path.join(args.outdir, f"worker_{worker_num}.json")
        tmp = out_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(worker_prd, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, out_path)
        story_ids = [s["id"] for s in bucket]
        id_list = ", ".join(story_ids[:5]) + ("..." if len(story_ids) > 5 else "")
        priority_counts: dict[str, int] = {}
        for s in bucket:
            p = s.get("priority", "medium")
            priority_counts[p] = priority_counts.get(p, 0) + 1
        pcount_str = " ".join(
            f"{p}:{c}"
            for p, c in sorted(
                priority_counts.items(), key=lambda kv: PRIORITY_RANK.get(kv[0], 2)
            )
        )
        print(
            f"[partition] Worker {worker_num}: {len(bucket)} stories "
            f"[{id_list}] ({pcount_str}) → {out_path}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
