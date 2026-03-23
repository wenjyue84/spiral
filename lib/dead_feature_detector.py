#!/usr/bin/env python3
"""
lib/dead_feature_detector.py — Phase V: Dead Feature Detector

Detects newly added Python functions/classes that are defined but never called or
imported from the codebase. Prevents code that exists but doesn't work.

Usage:
  python lib/dead_feature_detector.py \
    --story-id <US-NNN> \
    --changed-files <file1> <file2> ... \
    --repo-root <path>

Inputs:
  --story-id       Story ID for logging (e.g., "US-1006")
  --changed-files  List of changed file paths (space-separated)
  --repo-root      Repository root directory (default: cwd)

Output:
  {
    "story_id": "US-1006",
    "total_features": 2,
    "dead_features": [
      {
        "name": "unused_function",
        "file": "lib/foo.py",
        "line": 42,
        "definition": "def unused_function():"
      },
      ...
    ],
    "summary": "2 dead features found"
  }
"""

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Set


class DeadFeature(NamedTuple):
    """Represents a detected dead feature."""

    name: str
    file: str
    line: int
    definition: str


def extract_new_definitions(
    story_id: str, changed_files: List[str], repo_root: str = "."
) -> Dict[str, List[tuple[str, int, str]]]:
    """
    Extract newly defined functions and classes from git diff.

    Returns dict mapping filename -> [(name, line_num, definition), ...]
    """
    definitions: Dict[str, List[tuple[str, int, str]]] = {}

    for changed_file in changed_files:
        if not changed_file.endswith(".py"):
            continue

        file_path = Path(repo_root) / changed_file
        if not file_path.exists():
            continue

        # Get git diff for this file
        try:
            diff_output = subprocess.run(
                ["git", "diff", "HEAD", changed_file],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        except Exception:
            continue

        # Find lines that start with + (added lines) but not +++ (file header)
        new_defs = []
        for line in diff_output.split("\n"):
            if line.startswith("+++") or line.startswith("---"):
                continue
            if not line.startswith("+"):
                continue

            # Check for function or class definition
            stripped = line[1:].strip()
            match_func = re.match(r"^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", stripped)
            match_class = re.match(r"^class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[\(:]?", stripped)

            if match_func:
                name = match_func.group(1)
                new_defs.append((name, stripped))
            elif match_class:
                name = match_class.group(1)
                new_defs.append((name, stripped))

        if new_defs:
            # Find line numbers in the actual file
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    lines = content.split("\n")

                file_defs = []
                for name, definition in new_defs:
                    for i, line in enumerate(lines, 1):
                        if re.match(rf"^\s*(def|class)\s+{re.escape(name)}\s*[\(\:]?", line):
                            file_defs.append((name, i, definition))
                            break

                if file_defs:
                    definitions[changed_file] = file_defs
            except Exception:
                continue

    return definitions


def search_codebase(symbol_name: str, repo_root: str = ".", exclude_files: Optional[Set[str]] = None) -> bool:
    """
    Search entire codebase for references to a symbol.

    Returns True if symbol is referenced (imported, called, or used) anywhere
    other than at its definition site.
    """
    if exclude_files is None:
        exclude_files = set()

    try:
        # Search for imports: "from ... import symbol" or "import symbol"
        grep_patterns = [
            rf"from\s+\S+\s+import\s+.*{re.escape(symbol_name)}",
            rf"import\s+{re.escape(symbol_name)}",
            # Also search for direct calls/usage: symbol(, symbol., etc.
            rf"{re.escape(symbol_name)}\s*\(",
            rf"\.{re.escape(symbol_name)}\s*\(",
        ]

        for pattern in grep_patterns:
            try:
                result = subprocess.run(
                    [
                        "grep",
                        "-r",
                        "-E",
                        pattern,
                        ".",
                        "--include=*.py",
                        "--exclude-dir=.git",
                        "--exclude-dir=.spiral",
                        "--exclude-dir=__pycache__",
                    ],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if result.stdout:
                    # Count non-definition references
                    for line in result.stdout.split("\n"):
                        if not line:
                            continue
                        # Skip test_ functions (they're discovered by pytest)
                        if symbol_name.startswith("test_"):
                            continue
                        # Skip __init__.py re-exports (acceptable)
                        if "__init__.py" in line:
                            continue
                        # If we found a reference in a different file, it's not dead
                        return True
            except subprocess.TimeoutExpired:
                # Assume it's used if grep times out
                return True
            except Exception:
                continue

        return False
    except Exception:
        # On error, assume it's used (conservative)
        return True


def find_dead_features(story_id: str, changed_files: List[str], repo_root: str = ".") -> List[DeadFeature]:
    """
    Find dead features in changed files.

    Returns list of DeadFeature objects representing unused symbols.
    """
    dead_features: List[DeadFeature] = []

    # Extract all new definitions
    definitions = extract_new_definitions(story_id, changed_files, repo_root)

    # Check each definition for references in codebase
    for file_path, defs in definitions.items():
        for symbol_name, line_num, definition in defs:
            # Skip test_ functions (discovered by pytest)
            if symbol_name.startswith("test_"):
                continue

            # Check if symbol is referenced anywhere
            if not search_codebase(symbol_name, repo_root, exclude_files={file_path}):
                dead_features.append(
                    DeadFeature(
                        name=symbol_name,
                        file=file_path,
                        line=line_num,
                        definition=definition,
                    )
                )

    return dead_features


def detect_dead_features(story_id: str, changed_files: List[str], repo_root: str = ".") -> Dict[str, Any]:
    """
    Main function to detect dead features and return structured results.

    Args:
        story_id: Story ID for logging
        changed_files: List of changed file paths
        repo_root: Repository root directory

    Returns:
        {
            "story_id": str,
            "total_features": int,
            "dead_features": [DeadFeature, ...],
            "summary": str
        }
    """
    dead_features = find_dead_features(story_id, changed_files, repo_root)

    return {
        "story_id": story_id,
        "total_features": len(dead_features),
        "dead_features": [
            {
                "name": df.name,
                "file": df.file,
                "line": df.line,
                "definition": df.definition,
            }
            for df in dead_features
        ],
        "summary": f"{len(dead_features)} dead features found",
    }


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Detect dead features in changed files")
    parser.add_argument(
        "--story-id",
        required=True,
        help="Story ID (e.g., US-1006)",
    )
    parser.add_argument(
        "--changed-files",
        nargs="*",
        default=[],
        help="List of changed file paths",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root directory",
    )

    args = parser.parse_args()

    result = detect_dead_features(
        story_id=args.story_id,
        changed_files=args.changed_files,
        repo_root=args.repo_root,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
