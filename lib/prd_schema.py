#!/usr/bin/env python3
"""
SPIRAL — PRD Schema Validator
Validates prd.json structure, types, ID uniqueness, and dependency integrity.

Uses formal JSON Schema (prd.schema.json) when the `jsonschema` package is
available; falls back to built-in stdlib validation otherwise.

Exit codes:
  0 = valid
  1 = file/JSON parse error
  2 = schema validation errors

Usage:
  python lib/prd_schema.py prd.json           # exit 0 = valid, exit 2 = errors
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

# Current PRD schema version — bump when schema changes
CURRENT_SCHEMA_VERSION = 1


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

    # ── schemaVersion validation ─────────────────────────────────────────────
    if "schemaVersion" not in prd:
        print(
            "[schema] WARNING: prd.json has no schemaVersion field. "
            "Run 'spiral.sh --migrate' or 'python lib/migrate_prd.py prd.json' to add it.",
            file=sys.stderr,
        )
    elif not isinstance(prd["schemaVersion"], int):
        errors.append(f"schemaVersion must be integer, got {type(prd['schemaVersion']).__name__}")
    elif prd["schemaVersion"] < 1:
        errors.append(f"schemaVersion must be >= 1, got {prd['schemaVersion']}")

    # ── Optional top-level keys ──────────────────────────────────────────────
    if "overview" in prd and not isinstance(prd["overview"], str):
        errors.append(f"overview must be string, got {type(prd['overview']).__name__}")

    if "goals" in prd:
        if not isinstance(prd["goals"], list):
            errors.append(f"goals must be a list, got {type(prd['goals']).__name__}")

    if "epics" in prd:
        if not isinstance(prd["epics"], list):
            errors.append(f"epics must be a list, got {type(prd['epics']).__name__}")
        else:
            for j, epic in enumerate(prd["epics"]):
                ep = f"epics[{j}]"
                if not isinstance(epic, dict):
                    errors.append(f"{ep}: must be an object")
                    continue
                if "id" not in epic or not isinstance(epic.get("id"), str) or not epic["id"].strip():
                    errors.append(f"{ep}: missing or empty required field 'id'")
                if "title" in epic and not isinstance(epic["title"], str):
                    errors.append(f"{ep}: title must be string")
                if "description" in epic and not isinstance(epic["description"], str):
                    errors.append(f"{ep}: description must be string")

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

        if "_passedCommit" in story:
            pc = story["_passedCommit"]
            if not isinstance(pc, str):
                errors.append(f"{prefix}: _passedCommit must be string")
            elif pc and not re.match(r'^[0-9a-f]{40}$', pc):
                errors.append(f"{prefix}: _passedCommit must be a 40-char hex SHA or empty string")

        if "filesTouch" in story and not isinstance(story["filesTouch"], list):
            errors.append(f"{prefix}: filesTouch must be a list")

        if "isTestFix" in story and not isinstance(story["isTestFix"], bool):
            errors.append(f"{prefix}: isTestFix must be boolean")

        if "tags" in story:
            if not isinstance(story["tags"], list):
                errors.append(f"{prefix}: tags must be a list")
            else:
                tag_pattern = re.compile(r"^[a-z0-9_-]+$")
                for ti, tag in enumerate(story["tags"]):
                    if not isinstance(tag, str) or not tag:
                        errors.append(f"{prefix}: tags[{ti}] must be a non-empty string")
                    elif not tag_pattern.match(tag):
                        errors.append(f"{prefix}: tags[{ti}] '{tag}' must match /^[a-z0-9_-]+$/")

        if "epicId" in story:
            if not isinstance(story["epicId"], str) or not story["epicId"].strip():
                errors.append(f"{prefix}: epicId must be a non-empty string")

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


def validate_jsonschema(prd: dict, schema_path: str) -> list[str]:
    """
    Validate prd against a formal JSON Schema file using the jsonschema package.
    Returns list of diff-style error strings (empty = valid).
    Raises ImportError if jsonschema is not installed.
    """
    import jsonschema  # noqa: F811 — intentional late import

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    validator = jsonschema.Draft202012Validator(schema)
    errors: list[str] = []
    for err in sorted(validator.iter_errors(prd), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in err.absolute_path) if err.absolute_path else "(root)"
        # Identify story id for contextual error messages
        story_ctx = ""
        parts = list(err.absolute_path)
        if len(parts) >= 2 and parts[0] == "userStories":
            idx = parts[1]
            stories = prd.get("userStories", [])
            if isinstance(idx, int) and 0 <= idx < len(stories):
                sid = stories[idx].get("id", "?")
                story_ctx = f" ({sid})"
        errors.append(f"  - {path}{story_ctx}: {err.message}")
    return errors


def has_jsonschema() -> bool:
    """Return True if the jsonschema package is importable."""
    try:
        import jsonschema  # noqa: F401
        return True
    except ImportError:
        return False


def _find_schema_file(prd_path: str) -> str | None:
    """Locate prd.schema.json relative to the PRD file or SPIRAL_HOME."""
    candidates = []
    # Next to the prd file
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(prd_path)), "prd.schema.json"))
    # SPIRAL_HOME
    spiral_home = os.environ.get("SPIRAL_HOME")
    if spiral_home:
        candidates.append(os.path.join(spiral_home, "prd.schema.json"))
    # Relative to this script (lib/ → repo root)
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prd.schema.json"))
    for c in candidates:
        if os.path.isfile(c):
            return os.path.normpath(c)
    return None


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

    # Try formal JSON Schema validation first
    schema_file = _find_schema_file(args.prd)
    if schema_file and has_jsonschema():
        js_errors = validate_jsonschema(prd, schema_file)
        if js_errors:
            print(f"[schema] {args.prd} — JSON Schema validation failed ({len(js_errors)} error(s)):", file=sys.stderr)
            for err in js_errors:
                print(err, file=sys.stderr)
            return 2

    # Always run stdlib validation for cross-story checks (duplicates, dangling deps)
    errors = validate_prd(prd)
    if errors:
        print(f"[schema] {args.prd} — {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 2

    if not args.quiet:
        story_count = len(prd.get("userStories", []))
        method = "JSON Schema + stdlib" if (schema_file and has_jsonschema()) else "stdlib"
        print(f"[schema] {args.prd} — valid ({story_count} stories, {method})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
