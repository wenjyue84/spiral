"""lib/auto_release.py — Semantic version bump on SPIRAL completion.

Reads prd.json and git log, determines version bump level from conventional
commits, creates a git tag, and writes CHANGELOG.md.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Bump level constants
BUMP_NONE = 0
BUMP_PATCH = 1
BUMP_MINOR = 2
BUMP_MAJOR = 3

# Conventional commit prefixes → bump levels
_PREFIX_BUMP: dict[str, int] = {
    "feat": BUMP_MINOR,
    "fix": BUMP_PATCH,
    "perf": BUMP_PATCH,
    "refactor": BUMP_PATCH,
}


@dataclasses.dataclass
class Commit:
    sha: str
    subject: str
    body: str


def _classify_bump(commits: list[Commit]) -> int:
    """Return the highest bump level required by the commit list."""
    level = BUMP_NONE
    for commit in commits:
        subject = commit.subject
        body = commit.body
        # Breaking change: trailing ! or BREAKING CHANGE footer
        if re.match(r"^\w+[^:]*!:", subject) or "BREAKING CHANGE" in body:
            return BUMP_MAJOR
        # Parse conventional commit prefix
        m = re.match(r"^(\w+)(?:\([^)]+\))?:", subject)
        if m:
            prefix = m.group(1)
            bump = _PREFIX_BUMP.get(prefix, BUMP_NONE)
            if bump > level:
                level = bump
    return level


def _next_version(tag: str | None, bump: int) -> str:
    """Compute next semver string given the latest tag and bump level."""
    if tag is None:
        major, minor, patch = 0, 0, 0
    else:
        tag = tag.lstrip("v")
        parts = tag.split(".")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    if bump == BUMP_MAJOR:
        return f"{major + 1}.0.0"
    elif bump == BUMP_MINOR:
        return f"{major}.{minor + 1}.0"
    elif bump == BUMP_PATCH:
        return f"{major}.{minor}.{patch + 1}"
    else:
        return f"{major}.{minor}.{patch}"


def _write_changelog(
    path: Path,
    version: str,
    commits: list[Commit],
    stories: list[str],
) -> None:
    """Write (or prepend to) a CHANGELOG.md file."""
    today = datetime.date.today().isoformat()

    features: list[Commit] = []
    fixes: list[Commit] = []
    perf_commits: list[Commit] = []

    for commit in commits:
        m = re.match(r"^(\w+)(?:\([^)]+\))?!?:", commit.subject)
        if not m:
            continue
        prefix = m.group(1)
        if prefix == "feat":
            features.append(commit)
        elif prefix == "fix":
            fixes.append(commit)
        elif prefix == "perf":
            perf_commits.append(commit)

    lines: list[str] = [f"## [{version}] - {today}\n\n"]

    if features:
        lines.append("### Features\n\n")
        for c in features:
            desc = re.sub(r"^\w+(?:\([^)]+\))?!?:\s*", "", c.subject)
            lines.append(f"- {desc} ([{c.sha[:7]}])\n")
        lines.append("\n")

    if fixes:
        lines.append("### Bug Fixes\n\n")
        for c in fixes:
            desc = re.sub(r"^\w+(?:\([^)]+\))?!?:\s*", "", c.subject)
            lines.append(f"- {desc} ([{c.sha[:7]}])\n")
        lines.append("\n")

    if perf_commits:
        lines.append("### Performance\n\n")
        for c in perf_commits:
            desc = re.sub(r"^\w+(?:\([^)]+\))?!?:\s*", "", c.subject)
            lines.append(f"- {desc} ([{c.sha[:7]}])\n")
        lines.append("\n")

    if stories:
        lines.append("### Stories Completed\n\n")
        for s in stories:
            lines.append(f"- {s}\n")
        lines.append("\n")

    new_section = "".join(lines)

    if path.exists():
        existing = path.read_text(encoding="utf-8")
        path.write_text(new_section + existing, encoding="utf-8")
    else:
        path.write_text(new_section, encoding="utf-8")


def _get_latest_tag(repo: str) -> str | None:
    """Return the latest semver git tag in the repo, or None."""
    result = subprocess.run(
        ["git", "-C", repo, "tag", "-l", "v*", "--sort=-version:refname"],
        capture_output=True,
        text=True,
    )
    tags = [t.strip() for t in result.stdout.strip().splitlines() if t.strip()]
    return tags[0] if tags else None


def _get_commits_since(repo: str, tag: str | None) -> list[Commit]:
    """Return commits since tag (or all commits if tag is None)."""
    fmt = "%H%x00%s%x00%b%x01"
    if tag:
        cmd = ["git", "-C", repo, "log", f"{tag}..HEAD", f"--format={fmt}"]
    else:
        cmd = ["git", "-C", repo, "log", f"--format={fmt}"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    commits: list[Commit] = []
    for record in result.stdout.split("\x01"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x00")
        if len(parts) >= 2:
            sha = parts[0].strip()
            subject = parts[1].strip()
            body = parts[2].strip() if len(parts) > 2 else ""
            if sha:
                commits.append(Commit(sha=sha, subject=subject, body=body))
    return commits


def _get_passed_stories(prd_path: str) -> list[str]:
    """Return titles of passed stories from prd.json."""
    try:
        with open(prd_path, encoding="utf-8") as f:
            prd: dict[str, Any] = json.load(f)
        stories = prd.get("userStories", [])
        return [s.get("title", s.get("id", "")) for s in stories if s.get("passes")]
    except (OSError, json.JSONDecodeError):
        return []


def main(argv: list[str] | None = None) -> int:
    """Entry point for auto-release. Returns exit code."""
    parser = argparse.ArgumentParser(description="Auto-release on SPIRAL completion")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--repo", default=".", help="Path to git repo")
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not create tags or write files"
    )

    args = parser.parse_args(argv)

    repo = args.repo
    tag = _get_latest_tag(repo)
    commits = _get_commits_since(repo, tag)
    bump = _classify_bump(commits)

    if bump == BUMP_NONE:
        print("No releasable commits found. Skipping release.", file=sys.stderr)
        return 2

    version = _next_version(tag, bump)
    stories = _get_passed_stories(args.prd)

    if not args.dry_run:
        changelog = Path(repo) / "CHANGELOG.md"
        _write_changelog(changelog, version, commits, stories)

        subprocess.run(
            ["git", "-C", repo, "tag", "-a", f"v{version}", "-m", f"Release v{version}"],
            check=True,
            capture_output=True,
        )
        print(f"Released v{version}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
