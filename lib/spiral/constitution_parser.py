#!/usr/bin/env python3
"""lib/spiral/constitution_parser.py — Parse and validate stories against constitution.

Extracts forbidden phrases from constitution.md and provides validation
functions to check if stories violate constitutional rules.
"""

from __future__ import annotations

from typing import Any


def parse_constitution_rules(constitution_path: str) -> dict[str, Any]:
    """Parse constitution.md and extract validation rules.

    Looks for lines starting with FORBIDDEN:, NOT:, NEVER:, AVOID:
    (case-insensitive) and extracts the phrases as forbidden keywords.

    Args:
        constitution_path: Path to constitution.md file.

    Returns:
        Dict with 'forbidden_phrases' list and 'parsed' boolean flag.
    """
    forbidden_phrases: list[str] = []

    if not constitution_path:
        return {"forbidden_phrases": [], "parsed": False}

    try:
        with open(constitution_path, encoding="utf-8") as fh:
            for line in fh:
                line_stripped = line.strip()
                # Check for forbidden phrase markers (case-insensitive)
                for prefix in ("FORBIDDEN:", "NOT:", "NEVER:", "AVOID:"):
                    if line_stripped.upper().startswith(prefix):
                        phrase = line_stripped[len(prefix) :].strip().lower()
                        if phrase:
                            forbidden_phrases.append(phrase)
                        break
    except OSError:
        return {"forbidden_phrases": [], "parsed": False}

    return {"forbidden_phrases": forbidden_phrases, "parsed": True}


def validate_story_against_constitution(story: dict[str, Any], forbidden_phrases: list[str]) -> tuple[bool, str]:
    """Validate story against constitution rules.

    Checks if story title/description contains any forbidden phrases.

    Args:
        story: Story dict with 'title' and 'description' fields.
        forbidden_phrases: List of forbidden phrases from constitution.

    Returns:
        Tuple of (is_valid, error_message).
        If valid: (True, "")
        If invalid: (False, "constitution violation: <details>")
    """
    if not forbidden_phrases:
        return True, ""

    story_text = (story.get("title", "") + " " + story.get("description", "")).lower()

    for phrase in forbidden_phrases:
        if phrase in story_text:
            return False, f"constitution violation: contains forbidden phrase '{phrase}'"

    return True, ""


def validate_antipatterns(story: dict[str, Any]) -> tuple[bool, str]:
    """Validate _decomposed.antiPatterns field structure.

    Checks that antiPatterns (if present) is a list with no duplicates.

    Args:
        story: Story dict potentially containing _decomposed field.

    Returns:
        Tuple of (is_valid, error_message).
        If valid: (True, "")
        If invalid: (False, "error message")
    """
    if "_decomposed" not in story:
        return True, ""

    decomposed = story.get("_decomposed")
    if not isinstance(decomposed, dict):
        return True, ""

    anti_patterns = decomposed.get("antiPatterns", [])
    if not anti_patterns:
        return True, ""

    if not isinstance(anti_patterns, list):
        return False, f"antiPatterns must be a list, got {type(anti_patterns).__name__}"

    # Check for duplicates
    seen: set[str] = set()
    for pattern in anti_patterns:
        if pattern in seen:
            raise ValueError(f"duplicate antiPattern: {pattern}")
        seen.add(pattern)

    return True, ""
