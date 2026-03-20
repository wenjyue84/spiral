#!/usr/bin/env python3
"""
.claude/hooks/verify_story_acceptance.py — Stop agent hook to verify story acceptance criteria.

This agent hook fires when Claude Code's agent is about to stop. It verifies that:
1. All filesTouch files exist and were modified in the last git commit
2. Targeted pytest pass on story-related test files
3. Returns {ok: false, reason: '...'} if criteria unmet, allowing Claude to continue

Reads SPIRAL_CURRENT_STORY_ID from environment to locate the story in prd.json.
Checks stop_hook_active flag to prevent infinite re-entry loops.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def read_hook_input() -> dict[str, Any]:
    """Read agent hook input from stdin (JSON)."""
    try:
        input_data = json.loads(sys.stdin.read())
        return input_data if isinstance(input_data, dict) else {}
    except json.JSONDecodeError:
        return {}


def load_prd_json(repo_root: Path) -> dict[str, Any]:
    """Load prd.json from repo root."""
    prd_path = repo_root / "prd.json"
    if not prd_path.exists():
        return {}
    with open(prd_path) as f:
        data = json.load(f)
        return data if isinstance(data, dict) else {}


def get_current_story(repo_root: Path, story_id: str) -> dict[str, Any] | None:
    """Find story by ID in prd.json."""
    prd = load_prd_json(repo_root)
    for story_data in prd.get("userStories", []):
        if isinstance(story_data, dict) and story_data.get("id") == story_id:
            return story_data
    return None


def check_files_exist(repo_root: Path, files: list[str]) -> tuple[bool, str]:
    """Check that all files exist relative to repo root."""
    for file_path in files:
        full_path = repo_root / file_path
        if not full_path.exists():
            return False, f"File not found: {file_path}"
    return True, ""


def check_files_modified_in_last_commit(repo_root: Path, files: list[str]) -> tuple[bool, str]:
    """Check that all files were modified in the last git commit."""
    try:
        # Get list of files changed in the last commit
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            # If we can't get git diff (e.g., first commit), skip this check
            return True, ""

        changed_files = set(result.stdout.strip().split("\n"))

        # Normalize file paths for comparison
        for file_path in files:
            normalized = file_path.replace("\\", "/")
            if normalized not in changed_files:
                return (
                    False,
                    f"File not modified in last commit: {file_path}",
                )

        return True, ""

    except subprocess.TimeoutExpired:
        return False, "Git check timed out"
    except Exception as e:
        return False, f"Git check failed: {e}"


def run_targeted_pytest(repo_root: Path, files: list[str]) -> tuple[bool, str]:
    """Run pytest on story-related test files."""
    if not files:
        return True, ""

    # Extract test files: those matching tests/test_*.py or tests/**/*_test.py
    test_files = [f for f in files if "test" in f and f.endswith(".py")]
    if not test_files:
        return True, ""

    try:
        # Run pytest on those test files
        result = subprocess.run(
            ["python", "-m", "pytest"] + test_files + ["-v", "--tb=short"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0:
            return True, ""

        # Collect pytest failure info
        stderr_lines = result.stderr.strip().split("\n")
        stdout_lines = result.stdout.strip().split("\n")
        last_lines = (stderr_lines + stdout_lines)[-5:]  # Last 5 lines
        reason = " | ".join(last_lines)
        return False, f"Pytest failed: {reason}"

    except subprocess.TimeoutExpired:
        return False, "Pytest timed out (>60s)"
    except FileNotFoundError:
        return True, ""  # pytest not found, skip check
    except Exception as e:
        return False, f"Pytest check failed: {e}"


def main() -> None:
    """Main hook logic."""
    # Read hook input
    hook_input = read_hook_input()

    # Check stop_hook_active to prevent infinite re-entry
    if hook_input.get("stop_hook_active", False):
        # Already in a stop hook; exit immediately to prevent loops
        print(json.dumps({"ok": True}))
        sys.exit(0)

    # Get story ID from environment
    story_id = os.environ.get("SPIRAL_CURRENT_STORY_ID", "")
    if not story_id:
        # No story context; allow completion
        print(json.dumps({"ok": True}))
        sys.exit(0)

    # Find repo root (assume we're in .claude/hooks/)
    hook_dir = Path(__file__).parent
    repo_root = hook_dir.parent.parent

    # Load story
    story = get_current_story(repo_root, story_id)
    if not story:
        # Story not found; allow completion
        print(json.dumps({"ok": True}))
        sys.exit(0)

    acceptance_criteria = story.get("acceptanceCriteria", [])
    files_to_touch = story.get("filesTouch", [])

    # Check 1: All filesTouch files exist
    if files_to_touch:
        ok, reason = check_files_exist(repo_root, files_to_touch)
        if not ok:
            print(json.dumps({"ok": False, "reason": reason}))
            sys.exit(0)

    # Check 2: All filesTouch files were modified in last commit
    if files_to_touch:
        ok, reason = check_files_modified_in_last_commit(repo_root, files_to_touch)
        if not ok:
            print(json.dumps({"ok": False, "reason": reason}))
            sys.exit(0)

    # Check 3: Run targeted pytest on story-related tests
    ok, reason = run_targeted_pytest(repo_root, files_to_touch)
    if not ok:
        print(json.dumps({"ok": False, "reason": reason}))
        sys.exit(0)

    # All checks passed
    print(json.dumps({"ok": True}))
    sys.exit(0)


if __name__ == "__main__":
    main()
