"""lib/prd/extract_story_commits.py — Story-to-commit mapping from git log (US-640)."""

import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)
_STORY_RE = re.compile(r"\b(?:US|UT)-\d{3}\b")


def story_commits_from_git(
    repo_path: str | Path,
    known_ids: set[str] | None = None,
) -> dict[str, list[str]]:
    """Parse git log; return {story_id: [sha, ...]} (newest-first per story).

    Args:
        repo_path: Path to the git repository root.
        known_ids: Optional set of known story IDs from prd.json.
                   Commits referencing absent IDs are logged as orphan warnings.

    Returns:
        Mapping of story_id to list of commit SHAs in git log order.
    """
    proc = subprocess.run(
        ["git", "log", "--format=%H %s"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=False,
    )
    mapping: dict[str, list[str]] = {}
    for line in proc.stdout.splitlines():
        sha, _, message = line.partition(" ")
        if not sha:
            continue
        for sid in _STORY_RE.findall(message):
            mapping.setdefault(sid, []).append(sha)
            if known_ids is not None and sid not in known_ids:
                log.warning("Orphaned commit %s references unknown story %s", sha[:8], sid)
    return mapping
