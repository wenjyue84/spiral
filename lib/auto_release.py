#!/usr/bin/env python3
"""
auto_release.py — Semantic version bump on SPIRAL completion.

Parses conventional commits since the last vX.Y.Z tag to determine the
next SemVer version, creates a git tag, and updates CHANGELOG.md.
No Node.js runtime required (pure Python + git).

Usage:
    python lib/auto_release.py \
        --prd <prd.json> \
        --repo <repo_root> \
        [--push] \
        [--dry-run]

Exit codes:
    0  Tag created (or dry-run would have created one)
    2  No releasable commits — no tag created (warning emitted)
    1  Error
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple


# ── Conventional commit parsing ───────────────────────────────────────────────

_BREAKING_RE = re.compile(r"^BREAKING[- ]CHANGE:", re.MULTILINE)
_TYPE_RE = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]+\))?(?P<breaking>!)?: .+")

BUMP_NONE = 0
BUMP_PATCH = 1
BUMP_MINOR = 2
BUMP_MAJOR = 3

RELEASABLE_TYPES = {"feat", "fix", "perf", "refactor", "revert"}
MINOR_TYPES = {"feat"}
PATCH_TYPES = {"fix", "perf", "refactor", "revert"}


class Commit(NamedTuple):
    sha: str
    subject: str
    body: str


def _run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _last_version_tag(repo: Path) -> str | None:
    """Return the most recent vX.Y.Z tag, or None if none exist."""
    try:
        raw = _run_git(
            ["tag", "--sort=-version:refname", "--list", "v[0-9]*.[0-9]*.[0-9]*"],
            repo,
        )
    except RuntimeError:
        return None
    tags = [t.strip() for t in raw.splitlines() if t.strip()]
    return tags[0] if tags else None


def _commits_since(repo: Path, since_tag: str | None) -> list[Commit]:
    """Return list of Commit since since_tag (exclusive), newest first."""
    sep = "\x1f"
    if since_tag:
        rev_range = f"{since_tag}..HEAD"
    else:
        rev_range = "HEAD"

    try:
        raw = _run_git(
            [
                "log",
                rev_range,
                f"--format=%H{sep}%s{sep}%b{sep}---END---",
            ],
            repo,
        )
    except RuntimeError:
        return []

    commits: list[Commit] = []
    for block in raw.split("---END---"):
        block = block.strip()
        if not block:
            continue
        parts = block.split(sep, 2)
        sha = parts[0].strip() if len(parts) > 0 else ""
        subject = parts[1].strip() if len(parts) > 1 else ""
        body = parts[2].strip() if len(parts) > 2 else ""
        if sha:
            commits.append(Commit(sha=sha[:12], subject=subject, body=body))
    return commits


def _classify_bump(commits: list[Commit]) -> int:
    """Return BUMP_MAJOR/MINOR/PATCH/NONE based on conventional commits."""
    level = BUMP_NONE
    for c in commits:
        m = _TYPE_RE.match(c.subject)
        if not m:
            continue
        ctype = m.group("type")
        breaking_marker = m.group("breaking")
        # BREAKING CHANGE in footer or '!' in header → major
        if breaking_marker == "!" or _BREAKING_RE.search(c.body):
            return BUMP_MAJOR
        if ctype in MINOR_TYPES:
            level = max(level, BUMP_MINOR)
        elif ctype in PATCH_TYPES:
            level = max(level, BUMP_PATCH)
    return level


def _next_version(current: str | None, bump: int) -> str:
    """Calculate the next version string."""
    if current is None:
        defaults = {BUMP_MAJOR: "1.0.0", BUMP_MINOR: "0.1.0", BUMP_PATCH: "0.0.1"}
        return defaults.get(bump, "0.1.0")
    # Strip leading 'v'
    raw = current.lstrip("v")
    parts = raw.split(".")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    if bump == BUMP_MAJOR:
        return f"{major + 1}.0.0"
    elif bump == BUMP_MINOR:
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


# ── CHANGELOG writer ──────────────────────────────────────────────────────────

def _story_titles(prd_path: Path) -> list[str]:
    """Return titles of all passed stories."""
    try:
        prd = json.loads(prd_path.read_text(encoding="utf-8"))
        return [
            s["title"]
            for s in prd.get("userStories", [])
            if s.get("passes") is True
        ]
    except Exception:
        return []


def _write_changelog(
    changelog_path: Path,
    version: str,
    commits: list[Commit],
    story_titles: list[str],
) -> None:
    """Prepend a new release section to CHANGELOG.md."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = [
        f"## [{version}] - {date_str}\n",
        "\n",
    ]

    if story_titles:
        lines.append("### Stories\n\n")
        for title in story_titles:
            lines.append(f"- {title}\n")
        lines.append("\n")

    # Group releasable commits by type
    by_type: dict[str, list[Commit]] = {}
    for c in commits:
        m = _TYPE_RE.match(c.subject)
        if m and m.group("type") in RELEASABLE_TYPES:
            ctype = m.group("type")
            by_type.setdefault(ctype, []).append(c)

    section_names = {
        "feat": "Features",
        "fix": "Bug Fixes",
        "perf": "Performance",
        "refactor": "Refactoring",
        "revert": "Reverts",
    }
    for ctype, section in section_names.items():
        bucket = by_type.get(ctype, [])
        if bucket:
            lines.append(f"### {section}\n\n")
            for c in bucket:
                lines.append(f"- {c.subject} ({c.sha})\n")
            lines.append("\n")

    new_section = "".join(lines)

    existing = ""
    if changelog_path.exists():
        existing = changelog_path.read_text(encoding="utf-8")

    if existing.startswith("# Changelog"):
        # Insert after the first heading
        header_end = existing.index("\n") + 1
        updated = existing[:header_end] + "\n" + new_section + existing[header_end:]
    else:
        header = "# Changelog\n\nAll notable changes are documented here.\n\n"
        updated = header + new_section + existing

    changelog_path.write_text(updated, encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Semantic version bump on SPIRAL completion"
    )
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--repo", required=True, help="Repository root")
    parser.add_argument(
        "--push", action="store_true", help="Push tag to origin after creation"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate version but do not create tag or modify files",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    prd_path = Path(args.prd).resolve()
    changelog_path = repo / "CHANGELOG.md"

    # 1. Find last vX.Y.Z tag
    last_tag = _last_version_tag(repo)
    print(
        f"[auto-release] Last version tag: {last_tag or '(none — first release)'}",
        flush=True,
    )

    # 2. Collect commits since last tag
    commits = _commits_since(repo, last_tag)
    print(f"[auto-release] Commits since last tag: {len(commits)}", flush=True)

    # 3. Classify bump level
    bump = _classify_bump(commits)
    if bump == BUMP_NONE:
        print(
            "[auto-release] WARNING: No releasable conventional commits found "
            "(feat/fix/perf/refactor/revert). No tag created.",
            flush=True,
        )
        return 2

    bump_names = {BUMP_MAJOR: "major", BUMP_MINOR: "minor", BUMP_PATCH: "patch"}
    print(f"[auto-release] Bump level: {bump_names[bump]}", flush=True)

    # 4. Calculate next version
    new_version = _next_version(last_tag, bump)
    tag_name = f"v{new_version}"
    print(f"[auto-release] Next version: {tag_name}", flush=True)

    if args.dry_run:
        print(f"[auto-release] Dry-run — would create tag {tag_name}", flush=True)
        return 0

    # 5. Update CHANGELOG.md
    story_titles = _story_titles(prd_path)
    _write_changelog(changelog_path, new_version, commits, story_titles)
    print(f"[auto-release] CHANGELOG.md updated with section for {tag_name}", flush=True)

    # 6. Create annotated git tag
    releasable = [
        c for c in commits
        if _TYPE_RE.match(c.subject) and _TYPE_RE.match(c.subject).group("type") in RELEASABLE_TYPES  # type: ignore[union-attr]
    ]
    summary_lines = [f"Release {tag_name}"]
    if story_titles:
        summary_lines.append("")
        summary_lines.append("Stories:")
        for title in story_titles[:20]:
            summary_lines.append(f"  - {title}")
    if releasable:
        summary_lines.append("")
        summary_lines.append("Commits:")
        for c in releasable[:30]:
            summary_lines.append(f"  {c.sha} {c.subject}")
    annotation = "\n".join(summary_lines)

    try:
        _run_git(["tag", "-a", tag_name, "-m", annotation], repo)
        print(f"[auto-release] Tag created: {tag_name}", flush=True)
    except RuntimeError as exc:
        print(f"[auto-release] ERROR creating tag: {exc}", flush=True)
        return 1

    # 7. Push tag if requested
    if args.push:
        try:
            _run_git(["push", "origin", tag_name], repo)
            print(f"[auto-release] Tag {tag_name} pushed to origin", flush=True)
        except RuntimeError as exc:
            print(f"[auto-release] WARNING: Push failed: {exc}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
