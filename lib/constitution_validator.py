#!/usr/bin/env python3
"""
lib/constitution_validator.py — Phase S Constitution Validation Engine

Parses constitution.md rules and antiPatterns, then validates stories
against them. Provides rejection logging for audit trail and learning loop.

Functions:
  - parse_constitution_rules(filepath) → dict with 'rules', 'antipatterns'
  - validate_story(story, rules) → tuple[bool, str] (is_valid, reason)
  - match_antipattern(text, patterns) → tuple[bool, str] (matched, pattern)
"""

import json
import os
import re
from typing import Any


def _strip_parenthetical(text: str) -> str:
    """Remove parenthetical explanations from text.

    E.g., "remove or bypass gates (x, y, z)" -> "remove or bypass gates"
    """
    return re.sub(r"\s*\([^)]*\)", "", text).strip()


def parse_constitution_rules(filepath: str) -> dict[str, Any]:
    """Parse constitution.md and extract rules and antiPatterns.

    Returns:
        {
          'rules': ['Phase ordering...', ...],
          'antipatterns': ['avoid hardcoded...', ...],
          'core_invariants': ['Phase ordering', ...]
        }
    """
    rules: dict[str, Any] = {
        "rules": [],
        "antipatterns": [],
        "core_invariants": [],
        "forbidden_phrases": [],
    }

    if not filepath or not os.path.exists(filepath):
        return rules

    try:
        with open(filepath, encoding="utf-8") as fh:
            content = fh.read()

        # Extract Core Invariants section
        invariants_match = re.search(
            r"## Core Invariants.*?\n(.*?)(?=##|\Z)", content, re.DOTALL
        )
        if invariants_match:
            invariants_block = invariants_match.group(1)
            invariants = re.findall(
                r"^\d+\.\s+\*\*([^*]+)\*\*", invariants_block, re.MULTILINE
            )
            rules["core_invariants"].extend(invariants)

        # Extract What Stories Must NOT Do section
        must_not_match = re.search(
            r"## What Stories Must NOT Do\n(.*?)(?=##|\Z)", content, re.DOTALL
        )
        if must_not_match:
            must_not_block = must_not_match.group(1)
            forbidden = re.findall(
                r"^- ([^\n]+)", must_not_block, re.MULTILINE
            )
            rules["forbidden_phrases"].extend(
                _strip_parenthetical(f).lower().strip()
                for f in forbidden
                if f
            )

        # Extract Acceptable Story Scope section
        acceptable_match = re.search(
            r"## Acceptable Story Scope\n(.*?)(?=##|\Z)", content, re.DOTALL
        )
        if acceptable_match:
            acceptable_block = acceptable_match.group(1)
            acceptable = re.findall(
                r"^- ([^\n]+)", acceptable_block, re.MULTILINE
            )
            rules["rules"].extend(
                f.lower().strip() for f in acceptable if f
            )

        # Extract Anti-Patterns section
        antipatterns_match = re.search(
            r"### Anti-Patterns.*?\n(.*?)(?=###|##|\Z)",
            content,
            re.DOTALL,
        )
        if antipatterns_match:
            antipatterns_block = antipatterns_match.group(1)
            antipatterns = re.findall(
                r"^- ([^\n]+)", antipatterns_block, re.MULTILINE
            )
            rules["antipatterns"].extend(
                _strip_parenthetical(a).lower().strip()
                for a in antipatterns
                if a
            )

    except OSError:
        pass

    return rules


def match_antipattern(
    text: str, patterns: list[str]
) -> tuple[bool, str]:
    """Check if text matches any antipattern.

    Args:
        text: Story title or description to check
        patterns: List of antipattern strings to match

    Returns:
        (matched: bool, pattern: str matching if matched else '')
    """
    text_lower = text.lower()
    for pattern in patterns:
        if pattern and pattern in text_lower:
            return True, pattern
    return False, ""


def validate_story(
    story: dict[str, Any], rules: dict[str, Any]
) -> tuple[bool, str]:
    """Validate a story against constitution rules and antiPatterns.

    Args:
        story: Story dict with 'id', 'title', 'description', etc.
        rules: Output from parse_constitution_rules()

    Returns:
        (is_valid: bool, rejection_reason: str or '')
    """
    if not isinstance(story, dict):
        return False, "invalid_story_type"

    story_id = story.get("id", "unknown")
    title = story.get("title", "")
    description = story.get("description", "")
    combined_text = f"{title} {description}"

    # Check for forbidden phrases (What Stories Must NOT Do)
    forbidden = rules.get("forbidden_phrases", [])
    for phrase in forbidden:
        if phrase and phrase in combined_text.lower():
            return False, f"forbidden_phrase: {phrase}"

    # Check for antiPatterns (Anti-Patterns to Avoid)
    antipatterns = rules.get("antipatterns", [])
    matched, pattern = match_antipattern(combined_text, antipatterns)
    if matched:
        return False, f"antipattern: {pattern}"

    # Validate story has required fields
    if not title:
        return False, "missing_title"
    if not description:
        return False, "missing_description"
    if not story_id:
        return False, "missing_id"

    return True, ""


def log_rejection(
    story: dict[str, Any],
    reason: str,
    phase: str = "S",
    output_file: str = ".spiral/_rejected_stories.json",
) -> None:
    """Log a rejected story to .spiral/_rejected_stories.json.

    Args:
        story: Rejected story dict
        reason: Rejection reason (e.g., 'antipattern: hardcoded_credentials')
        phase: Phase that rejected the story (default: 'S')
        output_file: Path to rejection log
    """
    import time

    rejection_entry = {
        "story_id": story.get("id", "unknown"),
        "title": story.get("title", ""),
        "rule_violated": reason.split(":")[0] if ":" in reason else reason,
        "reason": reason,
        "phase": phase,
        "timestamp": int(time.time()),
    }

    # Ensure directory exists
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

    # Read existing rejections
    rejections = []
    if os.path.exists(output_file):
        try:
            with open(output_file, encoding="utf-8") as fh:
                data = json.load(fh)
                rejections = data.get("rejections", [])
        except (json.JSONDecodeError, OSError):
            rejections = []

    # Append new rejection
    rejections.append(rejection_entry)

    # Write back
    try:
        with open(output_file, "w", encoding="utf-8") as fh:
            json.dump(
                {"rejections": rejections, "total": len(rejections)},
                fh,
                indent=2,
            )
    except OSError:
        pass


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python constitution_validator.py <constitution_file>")
        sys.exit(1)

    rules = parse_constitution_rules(sys.argv[1])
    print(json.dumps(rules, indent=2))
