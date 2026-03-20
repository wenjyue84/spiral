#!/usr/bin/env python3
"""
lib/validate_commits.py — Detect Orphan Stories and Squash-Commit Patterns (US-554).

Scans git log for story ID patterns (US-NNN, UT-NNN) and cross-references
against prd.json to find:
  1. Orphan stories — stories in prd.json (passes=true) with no matching commit
  2. Squash-commit patterns — single commits that reference multiple story IDs

Usage:
    from lib.validate_commits import validate_commits
    result = validate_commits("prd.json", repo_path=".")
    # {"orphans": ["US-123"], "squash_patterns": [{"commit": "abc123", "stories": ["US-1", "US-2"]}]}
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Pattern to match story IDs: US-NNN or UT-NNN
STORY_ID_RE = re.compile(r"\b(U[ST]-\d+)\b")


def _get_git_log(repo_path: str = ".") -> list[dict[str, str]]:
    """Return list of {hash, message} dicts from git log."""
    result = subprocess.run(
        ["git", "log", "--format=%H %s"],
        capture_output=True,
        text=True,
        cwd=repo_path,
    )
    if result.returncode != 0:
        return []

    commits: list[dict[str, str]] = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2:
            commits.append({"hash": parts[0], "message": parts[1]})
        elif len(parts) == 1:
            commits.append({"hash": parts[0], "message": ""})
    return commits


def _load_prd_stories(prd_path: str | Path) -> list[dict[str, Any]]:
    """Load user stories from prd.json."""
    path = Path(prd_path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("userStories", [])


def _extract_story_ids(text: str) -> list[str]:
    """Extract all story IDs (US-NNN, UT-NNN) from text."""
    return STORY_ID_RE.findall(text)


def validate_commits(
    prd_path: str | Path = "prd.json",
    repo_path: str = ".",
    *,
    git_log: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Detect orphan stories and squash-commit patterns.

    Args:
        prd_path: Path to prd.json.
        repo_path: Path to the git repository root.
        git_log: Optional pre-parsed git log (for testing). Each entry must
                 have 'hash' and 'message' keys.

    Returns:
        {
            "orphans": ["US-123", ...],
            "squash_patterns": [{"commit": "abc123", "stories": ["US-1", "US-2"]}, ...],
            "stories_with_commits": {"US-456": ["def789", ...], ...},
            "total_stories": N,
            "total_commits_scanned": N,
        }
    """
    stories = _load_prd_stories(prd_path)
    commits = git_log if git_log is not None else _get_git_log(repo_path)

    # Only consider stories that have passed (implemented)
    passed_ids: set[str] = set()
    for s in stories:
        if s.get("passes") is True:
            story_id = s.get("id", "")
            if story_id:
                passed_ids.add(story_id)

    # Map: story_id -> list of commit hashes that reference it
    stories_with_commits: dict[str, list[str]] = {sid: [] for sid in passed_ids}

    # Detect squash patterns: commits referencing multiple stories
    squash_patterns: list[dict[str, Any]] = []

    for commit in commits:
        msg = commit.get("message", "")
        commit_hash = commit.get("hash", "")
        referenced_ids = _extract_story_ids(msg)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_ids: list[str] = []
        for sid in referenced_ids:
            if sid not in seen:
                seen.add(sid)
                unique_ids.append(sid)

        # Track which stories have commits
        for sid in unique_ids:
            if sid in stories_with_commits:
                stories_with_commits[sid].append(commit_hash)

        # Flag squash-commit patterns (2+ distinct stories in one commit)
        if len(unique_ids) >= 2:
            squash_patterns.append({
                "commit": commit_hash,
                "stories": unique_ids,
            })

    # Orphans: passed stories with zero matching commits
    orphans = sorted(
        sid for sid, commits_list in stories_with_commits.items()
        if len(commits_list) == 0
    )

    return {
        "orphans": orphans,
        "squash_patterns": squash_patterns,
        "stories_with_commits": {
            sid: hashes for sid, hashes in stories_with_commits.items() if hashes
        },
        "total_stories": len(passed_ids),
        "total_commits_scanned": len(commits),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for standalone usage."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect orphan stories and squash-commit patterns (US-554)",
    )
    parser.add_argument(
        "--prd",
        default="prd.json",
        metavar="FILE",
        help="Path to prd.json (default: prd.json)",
    )
    parser.add_argument(
        "--repo",
        default=".",
        metavar="PATH",
        help="Path to git repository root (default: .)",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json)",
    )
    args = parser.parse_args(argv)

    result = validate_commits(prd_path=args.prd, repo_path=args.repo)

    if args.output_format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Total passed stories: {result['total_stories']}")
        print(f"Commits scanned: {result['total_commits_scanned']}")
        print(f"Orphan stories ({len(result['orphans'])}): {', '.join(result['orphans']) or 'none'}")
        if result["squash_patterns"]:
            print(f"Squash-commit patterns ({len(result['squash_patterns'])}):")
            for sp in result["squash_patterns"]:
                print(f"  {sp['commit'][:12]}: {', '.join(sp['stories'])}")
        else:
            print("Squash-commit patterns: none")

    # Exit 1 if orphans detected
    return 1 if result["orphans"] else 0


if __name__ == "__main__":
    sys.exit(main())
