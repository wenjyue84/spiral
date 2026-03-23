"""lib/phases/phase_v.py — Phase V CHANGELOG validation helpers.

Provides three functions used by Phase V pre-commit checks:
- extract_story_ids: find US-/UT- IDs mentioned in a CHANGELOG.md
- validate_changelog_stories: check those IDs are completed in prd.json
- find_orphan_commits: find git commits referencing incomplete story IDs
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from lib.validators.changelog_schema import validate_changelog_format

# Matches US-123 or UT-456 patterns
_STORY_ID_RE = re.compile(r"\b((?:US|UT)-\d+)\b")


def extract_story_ids(changelog_path: str) -> list[str]:
    """Return unique story IDs mentioned in a CHANGELOG.md (order-preserving)."""
    p = Path(changelog_path)
    if not p.exists():
        return []
    content = p.read_text(encoding="utf-8")
    # dict.fromkeys preserves insertion order while deduplicating
    return list(dict.fromkeys(_STORY_ID_RE.findall(content)))


def validate_changelog_stories(
    changelog_path: str,
    prd_path: str,
) -> dict[str, Any]:
    """Validate that every story ID in CHANGELOG.md exists in prd.json as completed.

    Returns a dict with keys:
        ok (bool)        — True iff format is valid and all IDs are completed
        orphan_ids (list) — story IDs in CHANGELOG that are not completed
        errors (list)    — human-readable error messages
    """
    if not validate_changelog_format(changelog_path):
        return {
            "ok": False,
            "orphan_ids": [],
            "errors": ["CHANGELOG.md fails Keep-a-Changelog format check"],
        }

    changelog_ids = extract_story_ids(changelog_path)

    try:
        prd_data = json.loads(Path(prd_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "orphan_ids": [], "errors": [f"Cannot load prd.json: {exc}"]}

    completed: set[str] = {
        s["id"]
        for s in prd_data.get("userStories", [])
        if s.get("passes") is True
    }

    orphans = [sid for sid in changelog_ids if sid not in completed]
    errors = [f"Story {sid} is not completed in prd.json" for sid in orphans]
    return {"ok": len(orphans) == 0, "orphan_ids": orphans, "errors": errors}


def find_orphan_commits(prd_path: str) -> list[str]:
    """Return git commit lines (--oneline) that reference incomplete story IDs.

    An 'orphan commit' is one whose message mentions a US-/UT- ID that either
    does not exist in prd.json or has passes != True.
    """
    try:
        prd_data = json.loads(Path(prd_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    completed: set[str] = {
        s["id"]
        for s in prd_data.get("userStories", [])
        if s.get("passes") is True
    }

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--all"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if result.returncode != 0:
        return []

    orphan_lines: list[str] = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        ids_in_line = _STORY_ID_RE.findall(line)
        if any(sid not in completed for sid in ids_in_line):
            orphan_lines.append(line)

    return orphan_lines
