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
from pathlib import Path

# Regex pattern matching story ID prefixes US-NNN or UT-NNN
STORY_ID_PATTERN = re.compile(r"(US|UT)-\d+")


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


def find_orphan_commits(repo_path: str) -> list[dict[str, str]]:
    """Scan git log for commits without a story ID (US-NNN or UT-NNN).

    Returns a list of dicts with 'hash' and 'subject' keys for each orphan.
    """
    orphans: list[dict[str, str]] = []
    try:
        log_result = subprocess.run(
            ["git", "log", "--format=%H %s", "--no-merges"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if log_result.returncode != 0:
            return orphans

        for line in log_result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(" ", 1)
            if len(parts) < 2:
                continue
            commit_hash, subject = parts[0], parts[1]

            # Get full commit message (subject + body)
            body_result = subprocess.run(
                ["git", "log", "-1", "--format=%B", commit_hash],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            full_message = body_result.stdout if body_result.returncode == 0 else ""

            if not STORY_ID_PATTERN.search(full_message):
                # Truncate hash to short form for display
                short_hash = commit_hash[:7]
                orphans.append({"hash": short_hash, "subject": subject})

    except (subprocess.TimeoutExpired, OSError):
        pass

    return orphans


def write_orphan_warnings(orphans: list[dict[str, str]], warnings_file: str) -> None:
    """Write orphan commit warnings to the specified log file."""
    path = Path(warnings_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for orphan in orphans:
            f.write(f"{orphan['hash']} {orphan['subject']}\n")


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

    # Detect orphan commits
    orphans = find_orphan_commits(spiral_home)

    if orphans:
        write_orphan_warnings(orphans, warnings_file)
        print(f"[phase-g] WARNING: {len(orphans)} orphan commits (no story ID) logged to {warnings_file}")
    else:
        print("[phase-g] All commits have story IDs")

    return 0
