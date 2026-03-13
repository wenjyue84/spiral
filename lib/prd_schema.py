#!/usr/bin/env python3
"""
SPIRAL — PRD Schema Validator (stdlib-only)
Validates prd.json structure, types, ID uniqueness, and dependency integrity.

Usage:
  python lib/prd_schema.py prd.json           # exit 0 = valid, exit 1 = errors
  python lib/prd_schema.py prd.json --quiet   # suppress success message

As module:
  from prd_schema import validate_prd
  errors = validate_prd(prd_dict)  # [] = valid
"""
import json
import os
import re
import sys

# Force UTF-8 stdout — prevents UnicodeEncodeError on Windows cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STORY_PREFIX = os.environ.get("SPIRAL_STORY_PREFIX", "US")

VALID_PRIORITIES = {"critical", "high", "medium", "low"}
VALID_COMPLEXITIES = {"small", "medium", "large"}
STORY_ID_PATTERN = re.compile(r"^(US|UT)-\d{3,4}$")


def validate_prd(prd: dict) -> list[str]:
    """
    Validate a prd.json dict. Returns list of error strings (empty = valid).
    """
    errors: list[str] = []

    if not isinstance(prd, dict):
        return ["Root must be a JSON object"]

    # ── Top-level required keys ──────────────────────────────────────────────
    for key in ("productName", "branchName", "userStories"):
        if key not in prd:
            errors.append(f"Missing required top-level key: {key}")

    if "productName" in prd and not isinstance(prd["productName"], str):
        errors.append(f"productName must be string, got {type(prd['productName']).__name__}")

    if "branchName" in prd and not isinstance(prd["branchName"], str):
        errors.append(f"branchName must be string, got {type(prd['branchName']).__name__}")

    if "userStories" in prd and not isinstance(prd["userStories"], list):
        errors.append(f"userStories must be a list, got {type(prd['userStories']).__name__}")
        return errors  # Can't validate stories if not a list

    if "userStories" not in prd:
        return errors

    # ── Optional top-level keys ──────────────────────────────────────────────
    if "overview" in prd and not isinstance(prd["overview"], str):
        errors.append(f"overview must be string, got {type(prd['overview']).__name__}")

    if "goals" in prd:
        if not isinstance(prd["goals"], list):
            errors.append(f"goals must be a list, got {type(prd['goals']).__name__}")

    # ── Per-story validation ─────────────────────────────────────────────────
    stories = prd["userStories"]
    seen_ids: dict[str, int] = {}  # id → index for duplicate detection
    all_ids: set[str] = set()

    for i, story in enumerate(stories):
        prefix = f"userStories[{i}]"

        if not isinstance(story, dict):
            errors.append(f"{prefix}: must be an object, got {type(story).__name__}")
            continue

        # Required fields
        sid = story.get("id")
        if sid is None:
            errors.append(f"{prefix}: missing required field 'id'")
        elif not isinstance(sid, str):
            errors.append(f"{prefix}: id must be string, got {type(sid).__name__}")
        else:
            if not STORY_ID_PATTERN.match(sid):
                errors.append(f"{prefix}: id '{sid}' does not match pattern (US|UT)-NNN")
            if sid in seen_ids:
                errors.append(f"{prefix}: duplicate story ID '{sid}' (first at index {seen_ids[sid]})")
            seen_ids[sid] = i
            all_ids.add(sid)

        if "title" not in story:
            errors.append(f"{prefix}: missing required field 'title'")
        elif not isinstance(story["title"], str) or not story["title"].strip():
            errors.append(f"{prefix}: title must be a non-empty string")

        if "passes" not in story:
            errors.append(f"{prefix}: missing required field 'passes'")
        elif not isinstance(story["passes"], bool):
            errors.append(f"{prefix}: passes must be boolean, got {type(story['passes']).__name__}")

        if "priority" not in story:
            errors.append(f"{prefix}: missing required field 'priority'")
        elif story["priority"] not in VALID_PRIORITIES:
            errors.append(f"{prefix}: invalid priority '{story['priority']}' (valid: {', '.join(sorted(VALID_PRIORITIES))})")

        if "description" in story and not isinstance(story["description"], str):
            errors.append(f"{prefix}: description must be string")

        if "acceptanceCriteria" not in story:
            errors.append(f"{prefix}: missing required field 'acceptanceCriteria'")
        elif not isinstance(story["acceptanceCriteria"], list):
            errors.append(f"{prefix}: acceptanceCriteria must be a list")

        if "dependencies" not in story:
            errors.append(f"{prefix}: missing required field 'dependencies'")
        elif not isinstance(story["dependencies"], list):
            errors.append(f"{prefix}: dependencies must be a list")

        # Optional fields (validate type when present)
        if "estimatedComplexity" in story:
            if story["estimatedComplexity"] not in VALID_COMPLEXITIES:
                errors.append(f"{prefix}: invalid estimatedComplexity '{story['estimatedComplexity']}' (valid: {', '.join(sorted(VALID_COMPLEXITIES))})")

        if "technicalNotes" in story and not isinstance(story.get("technicalNotes"), list):
            errors.append(f"{prefix}: technicalNotes must be a list")

        if "_decomposed" in story and not isinstance(story["_decomposed"], bool):
            errors.append(f"{prefix}: _decomposed must be boolean")

        if "_decomposedFrom" in story and not isinstance(story["_decomposedFrom"], str):
            errors.append(f"{prefix}: _decomposedFrom must be string")

        if "_decomposedInto" in story and not isinstance(story["_decomposedInto"], list):
            errors.append(f"{prefix}: _decomposedInto must be a list")

        if "filesTouch" in story and not isinstance(story["filesTouch"], list):
            errors.append(f"{prefix}: filesTouch must be a list")

        if "isTestFix" in story and not isinstance(story["isTestFix"], bool):
            errors.append(f"{prefix}: isTestFix must be boolean")

    # ── Cross-story checks (only if IDs were valid) ──────────────────────────
    for i, story in enumerate(stories):
        if not isinstance(story, dict):
            continue
        sid = story.get("id", "")
        prefix = f"userStories[{i}] ({sid})"

        # Dependency references
        deps = story.get("dependencies", [])
        if isinstance(deps, list):
            for dep in deps:
                if dep == sid:
                    errors.append(f"{prefix}: self-referencing dependency '{dep}'")
                elif dep not in all_ids:
                    errors.append(f"{prefix}: dependency '{dep}' not found in userStories")

        # _decomposedFrom reference
        parent = story.get("_decomposedFrom")
        if isinstance(parent, str) and parent not in all_ids:
            errors.append(f"{prefix}: _decomposedFrom '{parent}' not found in userStories")

        # _decomposedInto references
        children = story.get("_decomposedInto")
        if isinstance(children, list):
            for child_id in children:
                if child_id not in all_ids:
                    errors.append(f"{prefix}: _decomposedInto '{child_id}' not found in userStories")

    return errors


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate prd.json schema")
    parser.add_argument("prd", help="Path to prd.json")
    parser.add_argument("--quiet", action="store_true", help="Suppress success message")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"[schema] ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    try:
        with open(args.prd, encoding="utf-8") as f:
            prd = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[schema] ERROR: Invalid JSON in {args.prd}: {e}", file=sys.stderr)
        return 1

    errors = validate_prd(prd)
    if errors:
        print(f"[schema] {args.prd} — {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    if not args.quiet:
        story_count = len(prd.get("userStories", []))
        print(f"[schema] {args.prd} — valid ({story_count} stories)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
