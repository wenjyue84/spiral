#!/usr/bin/env python3
"""
SPIRAL — Auto-populate filesTouch hints from git history.

Scans git log for commits matching 'feat: US-*' patterns, extracts files
changed per story, builds a keyword → files mapping, then pre-populates
filesTouch on pending stories with matching keywords.

This is best-effort: wrong hints don't cause errors (they just affect
partitioning quality). Stories without hints work exactly as before.

Usage:
  python populate_hints.py --prd prd.json --repo-root .

Environment:
  SPIRAL_HINT_DIRS  — comma-separated directories to include (default: all)
  SPIRAL_STORY_PREFIX — story ID prefix (default: US)
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from prd_schema import validate_prd

from spiral_io import configure_utf8_stdout
configure_utf8_stdout()

# Directories to include in filesTouch (from env or all files)
_hint_dirs_env = os.environ.get("SPIRAL_HINT_DIRS", "")
INCLUDE_DIRS = set()
if _hint_dirs_env:
    for d in _hint_dirs_env.split(","):
        d = d.strip().rstrip("/") + "/"
        if d != "/":
            INCLUDE_DIRS.add(d)

# Story ID prefix from env
STORY_PREFIX = os.environ.get("SPIRAL_STORY_PREFIX", "US")

# GitNexus knowledge graph repo name — semantic fallback for populate_hints when
# keyword matching against git history finds nothing (e.g., new story areas with
# no commit history yet). Set SPIRAL_GITNEXUS_REPO to a repo name from `gitnexus list`.
# Default: empty (skip gitnexus — use keyword matching only)
GITNEXUS_REPO = os.environ.get("SPIRAL_GITNEXUS_REPO", "")

# Stop words to exclude from keyword matching
STOP_WORDS = {
    "a", "an", "the", "and", "or", "for", "in", "on", "to", "of", "is",
    "add", "fix", "update", "implement", "create", "with", "from", "that",
    "this", "are", "was", "be", "has", "had", "have", "it", "its", "as",
    "at", "by", "not", "but", "all", "can", "if", "do", "no", "so",
    "us", "new", "test", "ensure", "based", "when", "per", "via",
}


def extract_keywords(title: str) -> set[str]:
    """Extract meaningful keywords from a story title."""
    # Remove story prefix (e.g. US-NNN)
    title = re.sub(rf"^{re.escape(STORY_PREFIX)}-\d+\s*[-:–—]\s*", "", title)
    words = re.findall(r"[a-zA-Z0-9]+", title.lower())
    return {w for w in words if len(w) > 2 and w not in STOP_WORDS}


def get_completed_story_files(repo_root: str) -> dict[str, list[str]]:
    """
    Scan git log for 'feat: <PREFIX>-NNN' commits and extract files changed.
    Returns: {story_id: [file_paths]}
    """
    story_files: dict[str, list[str]] = {}

    try:
        # Get all commits matching feat: PREFIX-* pattern
        result = subprocess.run(
            ["git", "-C", repo_root, "log", "--oneline", "--all",
             f"--grep=feat: {STORY_PREFIX}-", "--format=%H %s"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30
        )
        if result.returncode != 0:
            return story_files

        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(" ", 1)
            if len(parts) < 2:
                continue
            commit_hash, message = parts

            # Extract PREFIX-NNN from message
            match = re.search(rf"{re.escape(STORY_PREFIX)}-(\d+)", message)
            if not match:
                continue
            story_id = f"{STORY_PREFIX}-{match.group(1)}"

            # Get files changed in this commit
            diff_result = subprocess.run(
                ["git", "-C", repo_root, "diff-tree", "--no-commit-id",
                 "-r", "--name-only", commit_hash],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=10
            )
            if diff_result.returncode != 0:
                continue

            files = []
            for f in diff_result.stdout.strip().split("\n"):
                f = f.strip()
                if not f:
                    continue
                # If INCLUDE_DIRS is set, filter; otherwise include all
                if INCLUDE_DIRS:
                    if any(f.startswith(d) for d in INCLUDE_DIRS):
                        files.append(f)
                else:
                    files.append(f)

            if files:
                if story_id in story_files:
                    story_files[story_id].extend(files)
                else:
                    story_files[story_id] = files

    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Deduplicate
    for sid in story_files:
        story_files[sid] = sorted(set(story_files[sid]))

    return story_files


def build_keyword_file_mapping(
    stories: list[dict], story_files: dict[str, list[str]]
) -> dict[str, set[str]]:
    """
    Build keyword → files mapping from completed stories.
    For each completed story with known files, map its title keywords to those files.
    """
    keyword_files: dict[str, set[str]] = defaultdict(set)

    for story in stories:
        if not story.get("passes"):
            continue
        sid = story["id"]
        if sid not in story_files:
            continue

        keywords = extract_keywords(story.get("title", ""))
        files = story_files[sid]

        for kw in keywords:
            keyword_files[kw].update(files)

    return dict(keyword_files)


def query_gitnexus_files(title: str, repo_root: str) -> list[str]:
    """
    Query GitNexus knowledge graph for files semantically related to a story title.
    Used as a fallback when keyword matching against git history finds nothing.
    Returns up to 5 file paths that exist on disk, or [] on any error.
    Requires: gitnexus CLI (`npm i -g gitnexus`) and SPIRAL_GITNEXUS_REPO set.
    """
    try:
        result = subprocess.run(
            ["gitnexus", "query", title, "-r", GITNEXUS_REPO, "--limit", "8"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10
        )
        if result.returncode != 0:
            return []
        # Parse file paths from definitions output
        file_pattern = re.compile(r"\b([\w][\w/._-]+\.(?:py|js|ts|java|go|rb|php))\b")
        found: list[str] = []
        seen: set[str] = set()
        for line in result.stdout.splitlines():
            for m in file_pattern.finditer(line):
                fp = m.group(1)
                if fp in seen:
                    continue
                seen.add(fp)
                if os.path.isfile(os.path.join(repo_root, fp)):
                    found.append(fp)
                    if len(found) >= 5:
                        return found
        return found
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return []


def populate_hints(prd: dict, repo_root: str) -> int:
    """
    Pre-populate filesTouch on pending stories using keyword matching.
    Returns number of stories updated.
    """
    stories = prd.get("userStories", [])
    story_files = get_completed_story_files(repo_root)

    if not story_files and not GITNEXUS_REPO:
        print("[hints] No story commit history found — skipping")
        return 0

    keyword_files = build_keyword_file_mapping(stories, story_files) if story_files else {}

    if not keyword_files and not GITNEXUS_REPO:
        print("[hints] No keyword→file mapping built — skipping")
        return 0

    updated = 0
    gitnexus_count = 0
    for story in stories:
        if story.get("passes"):
            continue

        # Skip stories that already have filesTouch
        existing = story.get("filesTouch", [])
        hints = story.get("technicalHints", {})
        if isinstance(hints, dict):
            existing = existing or hints.get("filesTouch", [])
        if existing:
            continue

        # Match title keywords against the mapping
        keywords = extract_keywords(story.get("title", ""))
        matched_files: set[str] = set()

        for kw in keywords:
            if kw in keyword_files:
                matched_files.update(keyword_files[kw])

        if not matched_files:
            if GITNEXUS_REPO:
                # Keyword matching found nothing — try gitnexus knowledge graph
                gn_files = query_gitnexus_files(story.get("title", ""), repo_root)
                if gn_files:
                    story["filesTouch"] = gn_files
                    story["_hintsSource"] = "gitnexus"
                    updated += 1
                    gitnexus_count += 1
            continue

        # Cap at 10 files to avoid noise
        files_list = sorted(matched_files)[:10]

        # Store as top-level filesTouch for easy access
        story["filesTouch"] = files_list
        updated += 1

    if gitnexus_count:
        print(f"[hints] gitnexus filled {gitnexus_count} stories (keyword matching missed them)")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auto-populate filesTouch hints from git history"
    )
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--repo-root", default=".", help="Path to git repo root")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change without modifying prd.json")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"[hints] ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    with open(args.prd, encoding="utf-8") as f:
        prd = json.load(f)

    errors = validate_prd(prd)
    if errors:
        print("[schema] PRD validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    updated = populate_hints(prd, args.repo_root)

    if updated == 0:
        print("[hints] No stories updated")
        return 0

    if args.dry_run:
        print(f"[hints] Would update {updated} stories (dry-run)")
        for s in prd.get("userStories", []):
            if s.get("filesTouch") and not s.get("passes"):
                print(f"  {s['id']}: {s['filesTouch']}")
        return 0

    # Write back
    tmp = args.prd + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prd, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, args.prd)

    print(f"[hints] Updated {updated} pending stories with filesTouch hints")
    return 0


if __name__ == "__main__":
    sys.exit(main())
