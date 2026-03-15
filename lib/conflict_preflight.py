#!/usr/bin/env python3
"""SPIRAL Pre-flight Cross-Story File Conflict Detection

Checks pairs of stories in a parallel batch for file-level conflicts using:
  1. filesTouch overlap — fast O(n²) check using planned file hints
  2. git merge-tree --write-tree — accurate check when story branches exist

Usage:
  python lib/conflict_preflight.py \\
    --prd prd.json \\
    --story-ids US-001 US-002 US-003 \\
    --repo-root . \\
    --conflict-log .spiral/conflict-log.jsonl \\
    --batch-number 1 \\
    [--update-prd]

Exits 0 always (results printed as JSON to stdout + appended to conflict-log.jsonl).
Output JSON: {"deferred": ["US-003"], "conflicts": [...], "elapsed_ms": N}
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

# Force UTF-8 stdout — prevents UnicodeEncodeError on Windows cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ── Helpers ────────────────────────────────────────────────────────────────────


def get_files_to_touch(story: dict) -> set[str]:
    """Extract filesTouch from story, checking both top-level and technicalHints."""
    files = set(story.get("filesTouch", []))
    if not files:
        hints = story.get("technicalHints", {})
        if isinstance(hints, dict):
            files = set(hints.get("filesTouch", []))
    return files


def priority_rank(story: dict) -> int:
    """Return numeric priority rank (lower = higher priority)."""
    return PRIORITY_RANK.get(story.get("priority", "medium"), 2)


def _branch_exists(repo_root: str, branch: str) -> bool:
    """Return True if the given branch exists in the repository."""
    try:
        r = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "--verify", f"refs/heads/{branch}"],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _merge_base(repo_root: str, ref_a: str, ref_b: str) -> str | None:
    """Return the common ancestor SHA of two refs, or None on failure."""
    try:
        r = subprocess.run(
            ["git", "-C", repo_root, "merge-base", ref_a, ref_b],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _check_merge_tree(
    repo_root: str, branch_a: str, branch_b: str
) -> list[str]:
    """
    Run git merge-tree to detect conflicts between two branches.

    Tries new-style (git 2.38+) first:
      git merge-tree --write-tree <branchA> <branchB>
    Falls back to old-style three-way:
      git merge-tree <base> <branchA> <branchB>

    Returns list of conflicting file paths (empty = no conflicts detected).
    """
    conflict_files: list[str] = []

    try:
        # New-style: exits non-zero when conflicts exist; outputs conflict details
        r = subprocess.run(
            ["git", "-C", repo_root, "merge-tree", "--write-tree", branch_a, branch_b],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            for line in (r.stdout + r.stderr).splitlines():
                if "Merge conflict in" in line:
                    path = line.split("Merge conflict in", 1)[1].strip()
                    if path:
                        conflict_files.append(path)
            if conflict_files:
                return conflict_files
            # Non-zero exit but no "Merge conflict in" lines — fall through to old-style
    except Exception:
        pass

    # Old-style fallback: git merge-tree <base> <branchA> <branchB>
    base = _merge_base(repo_root, branch_a, branch_b)
    if base is None:
        return []

    try:
        r2 = subprocess.run(
            ["git", "-C", repo_root, "merge-tree", base, branch_a, branch_b],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Old-style outputs conflict markers inline; detect files by context
        in_changed = False
        for line in r2.stdout.splitlines():
            if line.startswith("changed in both"):
                in_changed = True
            elif in_changed and line.startswith("  base   "):
                # Line like: "  base   100644 SHA\t<file>"
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    conflict_files.append(parts[1].strip())
                in_changed = False
            else:
                in_changed = False
    except Exception:
        pass

    return conflict_files


# ── Core logic ─────────────────────────────────────────────────────────────────


def check_pair(
    story_a: dict,
    story_b: dict,
    repo_root: str,
    worker_branches: dict[str, str],
) -> list[str]:
    """
    Check if two stories would produce file conflicts.

    Strategy:
      1. Compute filesTouch overlap — if empty, no conflict possible.
      2. If both stories have associated branches that exist, run git merge-tree
         for a precise answer (may override the filesTouch overlap result).
      3. Otherwise fall back to reporting the filesTouch overlap as the conflict.

    Returns list of conflicting file paths (empty = no conflict).
    """
    files_a = get_files_to_touch(story_a)
    files_b = get_files_to_touch(story_b)

    overlap = files_a & files_b
    if not overlap:
        # No filesTouch overlap — skip git check (fast path)
        return []

    branch_a = worker_branches.get(story_a["id"])
    branch_b = worker_branches.get(story_b["id"])

    if (
        branch_a
        and branch_b
        and _branch_exists(repo_root, branch_a)
        and _branch_exists(repo_root, branch_b)
    ):
        # Both branches exist — use git merge-tree for a precise answer
        mt_files = _check_merge_tree(repo_root, branch_a, branch_b)
        # Trust merge-tree result: no conflicts found even with overlap → no conflict
        return mt_files

    # No branches to check — report the filesTouch overlap
    return sorted(overlap)


def run_preflight(
    prd_file: str,
    story_ids: list[str],
    repo_root: str,
    conflict_log: str,
    batch_number: int,
    worker_branches: dict[str, str] | None = None,
) -> dict:
    """
    Run pre-flight conflict detection for the given story IDs.

    Checks all N*(N-1)/2 pairs.  For each conflicting pair the lower-priority
    story is deferred (removed from batch and marked pending).  If priorities are
    equal the second story in the pair order is deferred.

    Returns:
        {
            "deferred": [story_ids removed from batch],
            "conflicts": [{storyA, storyB, conflictingFiles, deferred, batch}],
            "elapsed_ms": int,
        }
    """
    start = time.monotonic()

    if worker_branches is None:
        worker_branches = {}

    if len(story_ids) < 2:
        return {"deferred": [], "conflicts": [], "elapsed_ms": 0}

    with open(prd_file, encoding="utf-8") as f:
        prd = json.load(f)

    story_map = {s["id"]: s for s in prd.get("userStories", [])}
    stories = [story_map[sid] for sid in story_ids if sid in story_map]

    if len(stories) < 2:
        return {"deferred": [], "conflicts": [], "elapsed_ms": 0}

    conflicts: list[dict] = []
    deferred: set[str] = set()

    for i in range(len(stories)):
        for j in range(i + 1, len(stories)):
            sa, sb = stories[i], stories[j]

            # Skip pairs where one story is already deferred
            if sa["id"] in deferred or sb["id"] in deferred:
                continue

            conflict_files = check_pair(sa, sb, repo_root, worker_branches)
            if not conflict_files:
                continue

            # Lower-priority story loses (higher rank = lower priority)
            rank_a = priority_rank(sa)
            rank_b = priority_rank(sb)
            if rank_a >= rank_b:
                loser = sa
            else:
                loser = sb

            conflicts.append(
                {
                    "storyA": sa["id"],
                    "storyB": sb["id"],
                    "conflictingFiles": conflict_files,
                    "deferred": loser["id"],
                    "batch": batch_number,
                }
            )
            deferred.add(loser["id"])

    elapsed_ms = int((time.monotonic() - start) * 1000)

    # Append conflicts to conflict-log.jsonl
    if conflicts and conflict_log:
        log_dir = os.path.dirname(os.path.abspath(conflict_log))
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with open(conflict_log, "a", encoding="utf-8") as fh:
            for c in conflicts:
                entry = {
                    "ts": ts,
                    "event": "preflight_conflict",
                    "batch": c["batch"],
                    "storyA": c["storyA"],
                    "storyB": c["storyB"],
                    "conflictingFiles": c["conflictingFiles"],
                    "deferred": c["deferred"],
                }
                fh.write(json.dumps(entry) + "\n")

    return {
        "deferred": sorted(deferred),
        "conflicts": conflicts,
        "elapsed_ms": elapsed_ms,
    }


def update_prd_defer_stories(prd_file: str, story_ids: list[str]) -> None:
    """
    Reset deferred stories in prd.json to pending state.
    Sets passes=false, removes _failureReason, adds _conflictDeferred=true.
    Uses atomic temp-file rename to prevent corruption.
    """
    if not story_ids:
        return

    with open(prd_file, encoding="utf-8") as f:
        prd = json.load(f)

    ids = set(story_ids)
    modified = False
    for story in prd.get("userStories", []):
        if story["id"] in ids:
            story["passes"] = False
            story.pop("_failureReason", None)
            story["_conflictDeferred"] = True
            modified = True

    if not modified:
        return

    tmp = prd_file + ".conflict_preflight.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prd, f, indent=2)
        f.write("\n")
    os.replace(tmp, prd_file)


# ── CLI ────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SPIRAL pre-flight cross-story conflict detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument(
        "--story-ids", nargs="+", required=True, help="Story IDs in this batch"
    )
    parser.add_argument(
        "--repo-root", default=".", help="Git repository root (default: .)"
    )
    parser.add_argument(
        "--conflict-log",
        default="",
        help="Path to conflict-log.jsonl (default: no file written)",
    )
    parser.add_argument(
        "--batch-number",
        type=int,
        default=1,
        help="Current batch / wave number (default: 1)",
    )
    parser.add_argument(
        "--update-prd",
        action="store_true",
        help="Write deferred stories back to prd.json as pending",
    )
    args = parser.parse_args()

    result = run_preflight(
        prd_file=args.prd,
        story_ids=args.story_ids,
        repo_root=args.repo_root,
        conflict_log=args.conflict_log,
        batch_number=args.batch_number,
    )

    if args.update_prd and result["deferred"]:
        update_prd_defer_stories(args.prd, result["deferred"])

    print(json.dumps(result))

    if result["deferred"]:
        print(
            f"  [conflict-preflight] Deferred {len(result['deferred'])} "
            f"story/stories: {', '.join(result['deferred'])} "
            f"(elapsed {result['elapsed_ms']}ms)",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
