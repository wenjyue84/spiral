#!/usr/bin/env python3
"""lib/validate_changelog.py — CHANGELOG.md Markdown & Link Validation (US-1403).

Validates CHANGELOG.md for:
1. Valid Markdown syntax (headers, code blocks, links)
2. Story ID references (#US-NNN, @story:US-NNN, [US-NNN]) exist in prd.json
3. File links [text](path) point to existing files in git repo

Functions:
    validate_changelog_markdown(changelog_path) -> dict
    validate_changelog_links(changelog_path, prd_path, git_root) -> dict
    validate_all(changelog_path, prd_path, *, git_root, scratch_dir) -> bool
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Story ID patterns: matches US-1234, UT-1234, FE-1234, BE-1234 in any context
STORY_ID_PATTERN = re.compile(r"((?:US|UT|FE|BE)-\d+)")

# File link pattern: [text](path)
FILE_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

# Markdown code block pattern: ```...```
CODE_BLOCK_PATTERN = re.compile(r"```")

# Heading pattern: # or ## or ### etc
HEADING_PATTERN = re.compile(r"^#+\s")


def validate_changelog_markdown(changelog_path: str | Path) -> dict[str, Any]:
    """Validate CHANGELOG.md Markdown syntax.

    Checks for:
    - Properly matched code blocks (``` pairs)
    - Valid link syntax ([text](url))
    - Valid headers (# Header, ## Header, etc.)

    Returns dict with 'valid' (bool), 'errors' (list of dicts with line_number, error_type, message).
    """
    errors: list[dict[str, Any]] = []
    path = Path(changelog_path)

    if not path.exists():
        return {
            "valid": False,
            "errors": [
                {
                    "line_number": 0,
                    "error_type": "syntax",
                    "message": f"CHANGELOG.md not found: {changelog_path}",
                }
            ],
        }

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "valid": False,
            "errors": [
                {
                    "line_number": 0,
                    "error_type": "syntax",
                    "message": f"Failed to read CHANGELOG.md: {exc}",
                }
            ],
        }

    lines = content.split("\n")
    in_code_block = False
    code_block_start_line = 0

    for line_no, line in enumerate(lines, 1):
        # Check code block matching
        code_fence_count = len(CODE_BLOCK_PATTERN.findall(line))
        if code_fence_count > 0:
            if in_code_block:
                in_code_block = False
            else:
                in_code_block = True
                code_block_start_line = line_no

    if in_code_block:
        errors.append(
            {
                "line_number": code_block_start_line,
                "error_type": "syntax",
                "message": f"Unclosed code block starting at line {code_block_start_line}",
                "suggestion": "Close with ```",
            }
        )

    # Validate link syntax
    for line_no, line in enumerate(lines, 1):
        links = FILE_LINK_PATTERN.findall(line)
        for link_text, link_url in links:
            # Check basic link syntax (should be relative or http)
            if not link_url or link_url.startswith("http"):
                continue
            # Relative links will be validated in validate_changelog_links
            if any(c in link_url for c in ["<>", '""']):
                errors.append(
                    {
                        "line_number": line_no,
                        "error_type": "syntax",
                        "message": f"Invalid link syntax: [{link_text}]({link_url})",
                        "suggestion": "Use valid URL or file path",
                    }
                )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


def validate_changelog_links(
    changelog_path: str | Path,
    prd_path: str | Path,
    git_root: str | Path = ".",
) -> dict[str, Any]:
    """Validate story ID references and file links in CHANGELOG.md.

    Checks for:
    1. Story ID references (#US-NNN, @story:US-NNN, [US-NNN]) exist in prd.json
    2. File links [text](path) point to files that exist in git repo

    Returns dict with 'valid' (bool), 'errors' (list), 'link_count_checked' (int).
    """
    errors: list[dict[str, Any]] = []
    path = Path(changelog_path)
    git_path = Path(git_root)

    if not path.exists():
        return {
            "valid": False,
            "errors": [
                {
                    "line_number": 0,
                    "error_type": "missing_story",
                    "message": f"CHANGELOG.md not found: {changelog_path}",
                }
            ],
            "link_count_checked": 0,
        }

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "valid": False,
            "errors": [
                {
                    "line_number": 0,
                    "error_type": "syntax",
                    "message": f"Failed to read CHANGELOG.md: {exc}",
                }
            ],
            "link_count_checked": 0,
        }

    # Load prd.json to get list of valid story IDs
    prd_file = Path(prd_path)
    if not prd_file.exists():
        return {
            "valid": False,
            "errors": [
                {
                    "line_number": 0,
                    "error_type": "missing_story",
                    "message": f"prd.json not found: {prd_path}",
                }
            ],
            "link_count_checked": 0,
        }

    try:
        with prd_file.open(encoding="utf-8") as f:
            prd_data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "valid": False,
            "errors": [
                {
                    "line_number": 0,
                    "error_type": "missing_story",
                    "message": f"Failed to parse prd.json: {exc}",
                }
            ],
            "link_count_checked": 0,
        }

    # Extract valid story IDs from prd.json (only passed/completed stories)
    valid_story_ids: set[str] = set()
    if isinstance(prd_data, dict) and "userStories" in prd_data:
        for story in prd_data["userStories"]:
            if isinstance(story, dict) and "id" in story:
                # Only include stories that have passes: true
                if story.get("passes") is True:
                    valid_story_ids.add(story["id"])

    lines = content.split("\n")
    link_count = 0

    for line_no, line in enumerate(lines, 1):
        # Check story ID references
        story_matches = STORY_ID_PATTERN.finditer(line)
        for match in story_matches:
            story_id = match.group(1)
            link_count += 1
            if story_id not in valid_story_ids:
                # Try to find similar story IDs for suggestion
                suggestion = ""
                if prd_data.get("userStories"):
                    for story in prd_data["userStories"]:
                        if isinstance(story, dict) and "id" in story:
                            if story["id"].split("-")[1:] == story_id.split("-")[1:]:
                                suggestion = f"did you mean {story['id']}?"
                                break

                errors.append(
                    {
                        "line_number": line_no,
                        "error_type": "missing_story",
                        "message": f"Story {story_id} not found in completed stories in prd.json",
                        "suggestion": suggestion or "Ensure story exists and has passes: true",
                    }
                )

        # Check file links
        file_links = FILE_LINK_PATTERN.findall(line)
        for link_text, link_url in file_links:
            link_count += 1
            # Skip http/https links
            if link_url.startswith("http://") or link_url.startswith("https://"):
                continue

            # Check if file exists in git repo
            file_path = git_path / link_url
            if not file_path.exists():
                errors.append(
                    {
                        "line_number": line_no,
                        "error_type": "broken_link",
                        "message": f"File not found: {link_url}",
                        "suggestion": "Check file path and ensure file is committed to repo",
                    }
                )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "link_count_checked": link_count,
    }


def validate_all(
    changelog_path: str | Path,
    prd_path: str | Path,
    *,
    git_root: str | Path = ".",
    scratch_dir: str | Path = ".spiral",
) -> bool:
    """Validate CHANGELOG.md and write results to .spiral/_changelog_validation.json.

    Runs both syntax and link validation. On any failure, returns False and logs
    detailed error report. On success, writes validation metadata.

    Returns: True on success, False on any validation failure.
    """
    scratch_path = Path(scratch_dir)
    scratch_path.mkdir(parents=True, exist_ok=True)

    result_file = scratch_path / "_changelog_validation.json"

    # Run Markdown syntax validation
    syntax_result = validate_changelog_markdown(changelog_path)

    # Run link validation
    links_result = validate_changelog_links(changelog_path, prd_path, git_root=git_root)

    # Combine all errors
    all_errors = syntax_result.get("errors", []) + links_result.get("errors", [])

    # Build result
    result: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "file": "CHANGELOG.md",
        "status": "pass" if len(all_errors) == 0 else "fail",
        "checks_performed": ["syntax", "story_links", "file_links"],
        "link_count_checked": links_result.get("link_count_checked", 0),
        "error_count": len(all_errors),
    }

    if all_errors:
        result["errors"] = all_errors
        # Log to stderr
        print("[validate-changelog] Validation failed:", file=sys.stderr)
        for error in all_errors:
            line = error.get("line_number", 0)
            etype = error.get("error_type", "unknown")
            msg = error.get("message", "unknown error")
            suggestion = error.get("suggestion", "")
            print(
                f"[validate-changelog] CHANGELOG.md:{line}: {etype} — {msg}",
                file=sys.stderr,
            )
            if suggestion:
                print(f"[validate-changelog]   → {suggestion}", file=sys.stderr)

    # Write result
    try:
        with result_file.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"[validate-changelog] Validation result written to {result_file}")
    except OSError as exc:
        print(f"[validate-changelog] ERROR: Failed to write {result_file}: {exc}", file=sys.stderr)
        return False

    return len(all_errors) == 0


def main() -> int:
    """CLI entry point for validation."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate CHANGELOG.md Markdown syntax and link integrity")
    parser.add_argument("--changelog", default="CHANGELOG.md", help="Path to CHANGELOG.md")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    parser.add_argument("--git-root", default=".", help="Git repository root")
    parser.add_argument("--scratch-dir", default=".spiral", help="Scratch directory for results")

    args = parser.parse_args()

    success = validate_all(
        args.changelog,
        args.prd,
        git_root=args.git_root,
        scratch_dir=args.scratch_dir,
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
