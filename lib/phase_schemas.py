"""lib/phase_schemas.py — Phase output schema definitions and validators.

Each SPIRAL phase produces a JSON file. This module defines the required
structure for each phase's output and validates it, reporting violations
with file:function:line context for actionable debugging.

Phases covered:
  R  → _research_output.json
  T  → _test_stories_output.json
  S  → _validated_stories.json
  M  → prd.json patch (story schema)
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Required fields per phase output (story-level)
# ---------------------------------------------------------------------------

PHASE_R_STORY_REQUIRED: list[str] = ["title", "description"]
PHASE_T_STORY_REQUIRED: list[str] = ["title", "_source"]
PHASE_S_STORY_REQUIRED: list[str] = ["title", "_source"]
PHASE_M_STORY_REQUIRED: list[str] = ["id", "title", "passes"]

# Top-level wrapper required key for all phase outputs
STORIES_WRAPPER_KEY = "stories"


# ---------------------------------------------------------------------------
# Error class
# ---------------------------------------------------------------------------


class SchemaError(Exception):
    """Raised when a phase output fails schema validation.

    The message includes ``file:function():line: <description>`` so callers
    can pinpoint exactly where the violation was detected.
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _caller_location(extra_depth: int = 0) -> str:
    """Return 'file:function():line' string for the public validator caller."""
    # Stack: _caller_location -> _validate_story_fields -> validate_phase_* -> caller
    depth = 2 + extra_depth
    try:
        frame = inspect.stack()[depth]
        fname = Path(frame.filename).name
        return f"{fname}:{frame.function}():{frame.lineno}"
    except IndexError:
        return "unknown:unknown():0"


def _validate_wrapper(data: Any, phase: str) -> list[dict[str, Any]]:
    """Assert top-level structure is ``{stories: [...]}`` and return the list."""
    if not isinstance(data, dict):
        raise SchemaError(
            f"phase_{phase.lower()}.py:validate_{phase.lower()}_output():"
            f" root must be a JSON object, got {type(data).__name__}"
        )
    if STORIES_WRAPPER_KEY not in data:
        raise SchemaError(
            f"phase_{phase.lower()}.py:validate_{phase.lower()}_output():"
            f" missing required top-level key '{STORIES_WRAPPER_KEY}'"
        )
    stories = data[STORIES_WRAPPER_KEY]
    if not isinstance(stories, list):
        raise SchemaError(
            f"phase_{phase.lower()}.py:validate_{phase.lower()}_output():"
            f" '{STORIES_WRAPPER_KEY}' must be a list, got {type(stories).__name__}"
        )
    return stories


def _validate_story_fields(
    story: dict[str, Any],
    required: list[str],
    phase: str,
    index: int,
) -> None:
    """Raise SchemaError if any required field is missing from a story dict."""
    for field in required:
        if field not in story:
            location = _caller_location(extra_depth=1)
            raise SchemaError(f"{location}: story[{index}] missing required field '{field}' (phase {phase} output)")
        if not isinstance(story[field], str) and not isinstance(story[field], bool):
            # Accept str and bool; id/passes/title are str or bool
            pass  # type flexibility — only check presence


# ---------------------------------------------------------------------------
# Public validators
# ---------------------------------------------------------------------------


def validate_phase_r_output(data: Any) -> None:
    """Validate Phase R (_research_output.json) schema.

    Required top-level: ``{"stories": [...]}``
    Required per story: title, description

    Raises:
        SchemaError: with file:function():line context on first violation.
    """
    stories = _validate_wrapper(data, "R")
    for i, story in enumerate(stories):
        if not isinstance(story, dict):
            raise SchemaError(
                f"phase_r.py:validate_r_output():{inspect.currentframe().f_lineno}: "
                f"story[{i}] must be a dict, got {type(story).__name__}"
            )
        _validate_story_fields(story, PHASE_R_STORY_REQUIRED, "R", i)


def validate_phase_t_output(data: Any) -> None:
    """Validate Phase T (_test_stories_output.json) schema.

    Required top-level: ``{"stories": [...]}``
    Required per story: title, _source

    Raises:
        SchemaError: with file:function():line context on first violation.
    """
    stories = _validate_wrapper(data, "T")
    for i, story in enumerate(stories):
        if not isinstance(story, dict):
            raise SchemaError(
                f"phase_t.py:validate_t_output():{inspect.currentframe().f_lineno}: "
                f"story[{i}] must be a dict, got {type(story).__name__}"
            )
        _validate_story_fields(story, PHASE_T_STORY_REQUIRED, "T", i)


def validate_phase_s_output(data: Any) -> None:
    """Validate Phase S (_validated_stories.json) schema.

    Required top-level: ``{"stories": [...]}``
    Required per story: title, _source

    Raises:
        SchemaError: with file:function():line context on first violation.
    """
    stories = _validate_wrapper(data, "S")
    for i, story in enumerate(stories):
        if not isinstance(story, dict):
            raise SchemaError(
                f"phase_s.py:validate_s_output():{inspect.currentframe().f_lineno}: "
                f"story[{i}] must be a dict, got {type(story).__name__}"
            )
        _validate_story_fields(story, PHASE_S_STORY_REQUIRED, "S", i)


def validate_phase_m_output(data: Any) -> None:
    """Validate Phase M (prd.json patch) story schema.

    Required top-level: ``{"userStories": [...]}``
    Required per story: id, title, passes

    Raises:
        SchemaError: with file:function():line context on first violation.
    """
    if not isinstance(data, dict):
        raise SchemaError(f"phase_m.py:validate_m_output(): root must be a JSON object, got {type(data).__name__}")
    if "userStories" not in data:
        raise SchemaError("phase_m.py:validate_m_output(): missing required top-level key 'userStories'")
    stories = data["userStories"]
    if not isinstance(stories, list):
        raise SchemaError(f"phase_m.py:validate_m_output(): 'userStories' must be a list, got {type(stories).__name__}")
    for i, story in enumerate(stories):
        if not isinstance(story, dict):
            raise SchemaError(f"phase_m.py:validate_m_output(): story[{i}] must be a dict")
        for field in PHASE_M_STORY_REQUIRED:
            if field not in story:
                location = _caller_location()
                raise SchemaError(f"{location}: story[{i}] missing required field '{field}' (phase M prd.json output)")


def validate_phase_output(phase: str, data: Any) -> None:
    """Dispatch to the appropriate phase validator.

    Args:
        phase: One of 'R', 'T', 'S', 'M' (case-insensitive).
        data:  The parsed JSON object for that phase's output file.

    Raises:
        SchemaError: on first schema violation found.
        ValueError:  If phase is not recognised.
    """
    phase_upper = phase.upper()
    dispatch = {
        "R": validate_phase_r_output,
        "T": validate_phase_t_output,
        "S": validate_phase_s_output,
        "M": validate_phase_m_output,
    }
    if phase_upper not in dispatch:
        raise ValueError(f"Unknown phase '{phase}'. Expected one of {list(dispatch)}")
    dispatch[phase_upper](data)


def load_and_validate(path: str | Path, phase: str) -> Any:
    """Load a JSON file and validate it for the given phase.

    Args:
        path:  Path to the phase output JSON file.
        phase: One of 'R', 'T', 'S', 'M'.

    Returns:
        The parsed JSON data.

    Raises:
        SchemaError: if the file cannot be parsed or fails schema validation.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaError(f"phase_schemas.py:load_and_validate(): cannot load {path}: {exc}") from exc
    validate_phase_output(phase, data)
    return data
