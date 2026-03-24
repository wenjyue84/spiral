"""lib/gen_changelog.py — Phase G: CHANGELOG generation via git-cliff.

Integrates git-cliff to generate CHANGELOG.md with conventional commit sections
(feat/fix/docs/refactor). Parses commit messages for story IDs (US-NNN, UT-NNN)
and logs orphan commits (no story ID) to .spiral/phase_g_warnings.log.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Regex pattern matching story ID prefixes US-NNN or UT-NNN (case-insensitive)
STORY_ID_PATTERN = re.compile(r"(US|UT)-\d+", re.IGNORECASE)

# Regex for GitHub issue/PR references: "closes #123", "fixes #456", bare "#789"
# Group 1: keyword-prefixed number; Group 2: bare #NNN (not preceded by "[")
GITHUB_REF_PATTERN = re.compile(
    r"(?:closes?|fixed?|fixes?|resolves?)\s+#(\d+)|(?<!\[)#(\d+)",
    re.IGNORECASE,
)


# Regex matching commit SHA lines in append-mode CHANGELOG sections ("- abc1234 message")
_SHA_LINE_PATTERN = re.compile(r"^- ([0-9a-f]{7,40})\b", re.MULTILINE)


def _extract_shas_from_changelog(changelog_path: str | Path) -> set[str]:
    """Read an existing CHANGELOG.md and return all 7-char commit SHAs found in it.

    Only matches lines written by append_iteration_section() (format: "- <sha7> message").
    Returns empty set if the file does not exist.
    """
    path = Path(changelog_path)
    if not path.exists():
        return set()
    content = path.read_text(encoding="utf-8")
    return {m.group(1)[:7] for m in _SHA_LINE_PATTERN.finditer(content)}


def append_iteration_section(
    commits: list[dict[str, str]],
    iteration: int,
    changelog_path: str | Path,
    timestamp: str | None = None,
    append_mode: bool = True,
) -> None:
    """Append (or write) an iteration section to CHANGELOG.md.

    Section format::

        ## [Iteration N] - YYYY-MM-DD HH:MM UTC

        - abc1234 feat: US-1001 add feature
        - def5678 fix: US-1002 fix bug

    In append mode (default), existing content is preserved and commits already
    present (matched by their 7-char SHA) are skipped to prevent duplicates.

    Args:
        commits: List of dicts with at least ``commit`` (7-char SHA) and
            ``message`` keys.
        iteration: Iteration number used in the section header.
        changelog_path: Path to CHANGELOG.md to create or update.
        timestamp: Header timestamp string. Defaults to current UTC time in
            ``YYYY-MM-DD HH:MM UTC`` format.
        append_mode: If True, append to existing content and deduplicate by SHA.
            If False, overwrite the file.
    """
    if timestamp is None:
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    path = Path(changelog_path)
    existing_content = ""
    seen_shas: set[str] = set()

    if append_mode and path.exists():
        existing_content = path.read_text(encoding="utf-8")
        seen_shas = _extract_shas_from_changelog(changelog_path)

    new_commits = [c for c in commits if c.get("commit", "")[:7] not in seen_shas]

    if not new_commits and append_mode:
        return  # Nothing new to add

    lines = "".join(f"- {c['commit'][:7]} {c.get('message', '')}\n" for c in new_commits)
    new_section = f"## [Iteration {iteration}] - {timestamp}\n\n{lines}\n"

    content = (existing_content + new_section) if (append_mode and existing_content) else new_section
    path.write_text(content, encoding="utf-8")


def extract_github_refs(message: str) -> list[int]:
    """Parse GitHub issue/PR references from a commit message.

    Matches patterns:
    - closes/close/fixed/fixes/resolves #NNN  (keyword-prefixed)
    - bare #NNN  (not already inside a markdown link like [#NNN])

    Returns:
        Sorted, deduplicated list of integer issue/PR numbers found.
    """
    refs: set[int] = set()
    for m in GITHUB_REF_PATTERN.finditer(message):
        num_str = m.group(1) or m.group(2)
        refs.add(int(num_str))
    return sorted(refs)


def format_github_links(message: str, repo_url: str) -> str:
    """Replace bare #NNN references in text with markdown links.

    e.g. "#123" -> "[#123](https://github.com/org/repo/issues/123)"

    Already-formatted links ([#123](...)) are not double-replaced because
    the lookbehind in GITHUB_REF_PATTERN skips # preceded by "[".

    Args:
        message: Text containing GitHub issue/PR references.
        repo_url: Base GitHub repo URL, e.g. "https://github.com/org/repo".

    Returns:
        Text with bare #NNN references replaced by markdown links.
    """
    base = repo_url.rstrip("/")

    def _replace(m: re.Match[str]) -> str:
        num = m.group(1)
        return f"[#{num}]({base}/issues/{num})"

    return re.sub(r"(?<!\[)#(\d+)", _replace, message)


def validate_git_cliff(cliff_bin: str) -> bool:
    """Check that the git-cliff binary exists and is callable.

    Returns True if the binary responds to --version, False otherwise.
    """
    try:
        result = subprocess.run(
            [cliff_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, OSError):
        return False
    except subprocess.TimeoutExpired:
        return False


def generate_changelog(cliff_bin: str, cliff_config: str, output_file: str) -> bool:
    """Run git-cliff to produce CHANGELOG.md.

    Returns True if the output file was created, False otherwise.
    """
    try:
        result = subprocess.run(
            [cliff_bin, "--config", cliff_config, "--output", output_file],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(
                f"[phase-g] ERROR: git-cliff exited with code {result.returncode}",
                file=sys.stderr,
            )
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return False
        return Path(output_file).exists()
    except (FileNotFoundError, OSError) as exc:
        print(f"[phase-g] ERROR: git-cliff failed: {exc}", file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print("[phase-g] ERROR: git-cliff timed out", file=sys.stderr)
        return False


def find_orphan_commits(commits: list[dict[str, str]]) -> list[dict[str, str]]:
    """Filter commits to return only those without a story ID (US-NNN or UT-NNN).

    Args:
        commits: List of commit dicts with keys: commit, message, date.

    Returns:
        List of dicts with keys: commit, message, date, reason='no-story-id'
        for commits lacking a story ID tag.
    """
    orphans: list[dict[str, str]] = []
    for commit_dict in commits:
        message = commit_dict.get("message", "")
        if not STORY_ID_PATTERN.search(message):
            # Include all original keys plus reason
            orphan: dict[str, str] = dict(commit_dict)
            orphan["reason"] = "no-story-id"
            orphans.append(orphan)
    return orphans


def write_orphan_warnings(orphans: list[dict[str, str]], warnings_file: str) -> None:
    """Write orphan commit warnings to the specified log file."""
    path = Path(warnings_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for orphan in orphans:
            commit_hash = orphan.get("commit", "")
            message = orphan.get("message", "")
            f.write(f"{commit_hash} {message}\n")


def run(
    spiral_home: str,
    cliff_bin: str | None = None,
) -> int:
    """Generate CHANGELOG.md via git-cliff and log orphan commits.

    Returns 0 on success, 1 on failure.
    """
    if cliff_bin is None:
        cliff_bin = os.environ.get("SPIRAL_GIT_CLIFF_BIN", "git-cliff")

    cliff_config = os.path.join(spiral_home, "cliff.toml")
    output_file = os.path.join(spiral_home, "CHANGELOG.md")
    warnings_file = os.path.join(spiral_home, ".spiral", "phase_g_warnings.log")

    # Validate git-cliff binary
    if not validate_git_cliff(cliff_bin):
        print(
            f"[phase-g] ERROR: git-cliff binary not found at '{cliff_bin}'",
            file=sys.stderr,
        )
        return 1

    # Validate cliff.toml config
    if not Path(cliff_config).exists():
        print(
            f"[phase-g] ERROR: cliff.toml not found at {cliff_config}",
            file=sys.stderr,
        )
        return 1

    print(f"[phase-g] Generating CHANGELOG.md via {cliff_bin}...")

    # Run git-cliff
    if not generate_changelog(cliff_bin, cliff_config, output_file):
        print("[phase-g] ERROR: CHANGELOG.md was not created", file=sys.stderr)
        return 1

    print(f"[phase-g] CHANGELOG.md generated at {output_file}")

    # Detect orphan commits by querying git log
    try:
        log_result = subprocess.run(
            ["git", "log", "--format=%H%n%s%n%ai", "--no-merges"],
            cwd=spiral_home,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if log_result.returncode != 0:
            print("[phase-g] WARNING: Could not query git log", file=sys.stderr)
            return 0

        # Parse git log output into commit dicts
        commits: list[dict[str, str]] = []
        lines = log_result.stdout.strip().split("\n")
        i = 0
        while i < len(lines):
            if i + 2 < len(lines):
                commit_hash = lines[i].strip()
                message = lines[i + 1].strip()
                date = lines[i + 2].strip()
                if commit_hash and message:
                    commits.append(
                        {
                            "commit": commit_hash[:7],
                            "message": message,
                            "date": date,
                        }
                    )
                i += 3
            else:
                break

        # Filter to find orphans
        orphans = find_orphan_commits(commits)

        if orphans:
            write_orphan_warnings(orphans, warnings_file)
            print(f"[phase-g] WARNING: {len(orphans)} orphan commits (no story ID) logged to {warnings_file}")
        else:
            print("[phase-g] All commits have story IDs")

    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"[phase-g] ERROR: Could not query git log: {exc}", file=sys.stderr)

    return 0
