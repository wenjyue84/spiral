#!/usr/bin/env python3
"""Map changed files to affected tests for incremental Phase V validation (US-1102)."""

import argparse
import json
import subprocess
from pathlib import Path


def detect_changed_files(git_ref: str = "HEAD~1", repo_root: str = ".") -> list[str]:
    """Detect changed files using git diff.

    Args:
      git_ref: Git reference to compare against (default: HEAD~1)
      repo_root: Repository root directory

    Returns:
      List of changed file paths (relative to repo_root)
    """
    try:
        result = subprocess.run(
            ["git", "diff", git_ref, "--name-only"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.split("\n") if line.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def is_python_file(path: str) -> bool:
    """Check if path is a Python source file."""
    return path.endswith(".py") and not path.startswith(".")


def get_test_file_by_convention(py_file: str) -> str:
    """Map source file to test file by naming convention.

    Examples:
      lib/foo.py -> tests/test_foo.py
      src/bar.py -> tests/test_bar.py
    """
    if py_file.startswith("test"):
        return py_file  # Already a test file
    filename = Path(py_file).name  # basename
    basename = filename[:-3]  # remove .py
    return f"tests/test_{basename}.py"


def find_tests_importing_module(py_file: str, repo_root: str = ".") -> list[str]:
    """Find test files that import the changed module.

    Uses grep to find import statements in test files that reference the module.
    """
    module_path = Path(py_file)
    module_name = module_path.stem  # basename without .py

    # Skip if not a .py file
    if not py_file.endswith(".py"):
        return []

    # Skip if already a test file
    if "test" in py_file:
        return []

    tests_dir = Path(repo_root) / "tests"
    if not tests_dir.exists():
        return []

    importing_tests = []
    try:
        # Search for "from <module>" in test files
        result = subprocess.run(
            ["grep", "-r", "-l", f"from {module_name}", "tests/"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.split("\n"):
            if line.strip() and line.endswith(".py"):
                importing_tests.append(line.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Also search for direct imports
    try:
        result = subprocess.run(
            ["grep", "-r", "-l", f"import {module_name}", "tests/"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.split("\n"):
            if line.strip() and line.endswith(".py"):
                if line.strip() not in importing_tests:
                    importing_tests.append(line.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return importing_tests


def map_changed_to_tests(changed_files: list[str], repo_root: str = ".") -> dict[str, list[str]]:
    """Map changed files to affected test files.

    Returns dict with:
      "by_convention": List of test files mapped by naming (foo.py -> test_foo.py)
      "by_import": List of test files that import the changed module
      "all": Deduplicated union of both
    """
    result: dict[str, list[str]] = {"by_convention": [], "by_import": [], "all": []}

    seen: set[str] = set()
    for changed_file in changed_files:
        if not is_python_file(changed_file):
            continue

        # Convention mapping
        test_by_conv = get_test_file_by_convention(changed_file)
        test_path = Path(repo_root) / test_by_conv
        if test_path.exists() and test_by_conv not in seen:
            result["by_convention"].append(test_by_conv)
            seen.add(test_by_conv)

        # Import graph tracing
        tests_importing = find_tests_importing_module(changed_file, repo_root)
        for test_file in tests_importing:
            if test_file not in seen:
                result["by_import"].append(test_file)
                seen.add(test_file)

    result["all"] = sorted(list(seen))
    return result


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Map changed files to affected tests")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--changed-files",
        nargs="+",
        help="List of changed file paths (space-separated)",
    )
    group.add_argument(
        "--git-diff",
        default=None,
        help="Git reference to detect changes from (default: HEAD~1)",
    )
    parser.add_argument("--repo-root", default=".", help="Repository root directory (default: .)")

    args = parser.parse_args()

    if args.changed_files:
        changed = args.changed_files
    else:
        changed = detect_changed_files(args.git_diff or "HEAD~1", args.repo_root)

    mapping = map_changed_to_tests(changed, args.repo_root)

    # Output as JSON
    output = {
        "changed_files": changed,
        "mapping": mapping,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
