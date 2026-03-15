#!/usr/bin/env python3
"""
lib/llm_models.py — Pydantic v2 models for all LLM JSON output shapes (US-203).

Validates LLM-returned JSON before downstream processing.  Every call site
that previously used bare ``json.loads()`` on LLM output should now pass
the result through ``Model.model_validate(data)`` to surface schema
mismatches immediately.

Four shapes are modelled:

1. DecompositionResult  — story decomposition (decompose_story.py)
2. ResearchOutput       — Phase R research candidates
3. RouteStoriesResult   — route_stories annotation output
4. TestSynthesisReport  — Phase T synthesized test stories

A helper ``log_validation_error()`` writes validation failures to
``spiral_events.jsonl`` so they are observable without grepping logs.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

__all__ = [
    "SubStory",
    "DecompositionResult",
    "StoryCandidate",
    "ResearchOutput",
    "RoutedStory",
    "RouteStoriesResult",
    "FailingTestStory",
    "TestSynthesisReport",
    "log_validation_error",
    "validate_llm_json",
]


# ---------------------------------------------------------------------------
# 1. Story Decomposition
# ---------------------------------------------------------------------------

class SubStory(BaseModel):
    """A single sub-story produced by the decomposition LLM call."""

    title: str
    description: str = ""
    acceptanceCriteria: list[str] = Field(default_factory=list)
    technicalNotes: list[str] = Field(default_factory=list)
    estimatedComplexity: str = "small"


class DecompositionResult(BaseModel):
    """Top-level shape returned by the decomposition LLM call.

    Expected: ``{"ordered": bool, "stories": [SubStory, ...]}``
    """

    ordered: bool = False
    stories: list[SubStory] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 2. Research Output (Phase R)
# ---------------------------------------------------------------------------

class StoryCandidate(BaseModel):
    """A story candidate discovered during Phase R research."""

    model_config = ConfigDict(extra="allow")

    title: str
    priority: str = "medium"
    description: str = ""
    acceptanceCriteria: list[str] = Field(default_factory=list)
    technicalNotes: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    estimatedComplexity: str = "medium"
    tags: list[str] = Field(default_factory=list)
    source: str = ""


class ResearchOutput(BaseModel):
    """Top-level shape of ``_research_output.json``.

    Expected: ``{"stories": [StoryCandidate, ...]}``
    """

    stories: list[StoryCandidate] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3. Route Stories Result
# ---------------------------------------------------------------------------

class RoutedStory(BaseModel):
    """A story annotated with a model assignment by the semantic router."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    title: str = ""
    model: str = ""


class RouteStoriesResult(BaseModel):
    """Wrapper for the full prd after route_stories annotation.

    Expected: ``{"userStories": [RoutedStory, ...]}``
    """

    model_config = ConfigDict(extra="allow")

    userStories: list[RoutedStory] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 4. Test Synthesis Report (Phase T)
# ---------------------------------------------------------------------------

class FailingTestStory(BaseModel):
    """A story candidate generated from a failing test."""

    model_config = ConfigDict(extra="allow")

    title: str
    priority: str = "medium"
    description: str = ""
    acceptanceCriteria: list[str] = Field(default_factory=list)
    technicalNotes: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    estimatedComplexity: str = "small"


class TestSynthesisReport(BaseModel):
    """Top-level shape of ``_test_stories_output.json``.

    Expected: ``{"stories": [TestFailureStory, ...]}``
    """

    stories: list[FailingTestStory] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

def log_validation_error(
    error: ValidationError,
    raw_data: Any,
    context: str,
    scratch_dir: str | None = None,
) -> None:
    """Append a validation_error event to spiral_events.jsonl.

    Parameters
    ----------
    error:
        The Pydantic ``ValidationError`` that was caught.
    raw_data:
        The raw LLM output (dict or str) that failed validation.
    context:
        Human-readable label for the call site (e.g. ``"decompose_story"``).
    scratch_dir:
        Directory containing ``spiral_events.jsonl``.  Falls back to
        ``$SCRATCH_DIR`` or ``/tmp``.
    """
    if scratch_dir is None:
        scratch_dir = os.environ.get("SCRATCH_DIR", "/tmp")

    log_path = os.path.join(scratch_dir, "spiral_events.jsonl")

    # Build structured error details including field path + received value
    error_details = []
    for e in error.errors():
        error_details.append({
            "field_path": " -> ".join(str(loc) for loc in e["loc"]),
            "message": e["msg"],
            "received_value": repr(e.get("input", ""))[:200],
            "type": e["type"],
        })

    # Truncate raw_data for logging (avoid huge payloads)
    raw_str = json.dumps(raw_data, ensure_ascii=False, default=str) if not isinstance(raw_data, str) else raw_data
    if len(raw_str) > 2000:
        raw_str = raw_str[:2000] + "...(truncated)"

    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": "validation_error",
        "context": context,
        "error_count": error.error_count(),
        "errors": error_details,
        "raw_output": raw_str,
        "level": os.environ.get("SPIRAL_LOG_LEVEL", "WARN"),
    }

    run_id = os.environ.get("SPIRAL_RUN_ID", "")
    if run_id:
        entry["run_id"] = run_id

    try:
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        # Best-effort logging — never crash the pipeline over a log write
        print(f"[llm_models] WARNING: could not write to {log_path}", file=sys.stderr)


def validate_llm_json(
    model_class: type[BaseModel],
    data: dict[str, Any],
    context: str,
    scratch_dir: str | None = None,
) -> BaseModel:
    """Validate *data* against *model_class*, logging errors on failure.

    Returns the validated model instance.  On ``ValidationError``, logs to
    ``spiral_events.jsonl`` and re-raises so the caller can decide whether
    to retry or skip.
    """
    try:
        return model_class.model_validate(data)
    except ValidationError as exc:
        log_validation_error(exc, data, context, scratch_dir)
        raise
