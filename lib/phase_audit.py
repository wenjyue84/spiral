#!/usr/bin/env python3
"""
lib/phase_audit.py — Phase Output Audit Trail (US-543)

Tracks story status changes between iterations by comparing phase output files.
Detects which stories were added, removed, modified, or stuck between consecutive
iterations.

Usage:
    spiral phase-audit --compare-last [--phase=PHASE] [--scratch-dir .spiral]

Output:
    JSON with keys: added[], removed[], modified[{storyId, changedFields}], stuck[{storyId, stuckSince}]
"""

import json
from pathlib import Path
from typing import Any, Literal

Phase = Literal["R", "T", "S", "M", "G", "I", "V", "C"]

# Map phase names to output files
PHASE_OUTPUT_FILES = {
    "R": "_research_output.json",
    "T": "_test_stories_output.json",
    "S": "_validated_stories.json",
    "M": "_merged_stories.json",
}


def load_phase_output(iteration: int, phase: Phase, scratch_dir: Path) -> dict[str, Any]:
    """Load phase output file for a given iteration.

    Args:
        iteration: Iteration number (e.g., 3)
        phase: Phase identifier ('R', 'T', 'S', 'M', 'G', 'I', 'V', 'C')
        scratch_dir: Path to .spiral directory

    Returns:
        Dictionary with 'stories' key containing list of story dicts.
        Returns {'stories': []} if file doesn't exist or is invalid.
    """
    if phase not in PHASE_OUTPUT_FILES:
        return {"stories": []}

    filename = PHASE_OUTPUT_FILES[phase]
    # For now, phase outputs are saved as-is in .spiral/
    # Future: could be organized by iteration like .spiral/iter-3/_validated_stories.json
    file_path = scratch_dir / filename

    if not file_path.exists():
        return {"stories": []}

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
            # Normalize: ensure we have a 'stories' key with a list
            if isinstance(data, list):
                return {"stories": data}
            elif isinstance(data, dict) and "stories" in data:
                return data
            elif isinstance(data, dict):
                # Single story or stories under different key
                return {"stories": [data] if "id" in data else []}
            else:
                return {"stories": []}
    except (json.JSONDecodeError, OSError):
        return {"stories": []}


def get_story_id(story: dict[str, Any]) -> str:
    """Extract story ID from a story dict."""
    return story.get("id") or story.get("story_id") or ""


def get_story_key_fields(story: dict[str, Any]) -> dict[str, Any]:
    """Extract fields that matter for change detection.

    Returns a dict of field_name -> value for comparison.
    """
    return {
        "title": story.get("title", story.get("story_title", "")),
        "status": story.get("status", ""),
        "scope": story.get("scope", ""),
        "estimatedComplexity": story.get("estimatedComplexity", ""),
        "priority": story.get("priority", ""),
        "passes": story.get("passes"),
    }


def compare_iterations(
    current_iter: int,
    phase: Phase,
    scratch_dir: Path,
    min_prev_iters: int = 1,
) -> dict[str, Any]:
    """Compare phase outputs across consecutive iterations.

    Args:
        current_iter: Current iteration number
        phase: Phase to audit
        scratch_dir: Path to .spiral directory
        min_prev_iters: How many previous iterations to look back (for stuck detection)

    Returns:
        {
            'added': [{'id': 'US-123', ...}],
            'removed': [{'id': 'US-456', ...}],
            'modified': [{'id': 'US-789', 'changedFields': ['status', 'scope']}],
            'stuck': [{'id': 'US-999', 'stuckSince': 3}],
            'totalCompared': <int>,
        }
    """
    # For now, assume each iteration's phase output is stored in a single location
    # (Current implementation saves to scratch_dir directly, not per-iteration)
    # This is a limitation: we would need iteration-specific paths like .spiral/iter-3/
    # For now, we'll work with the current state and compare against previous checkpoints

    current_output = load_phase_output(current_iter, phase, scratch_dir)
    current_stories = current_output.get("stories", [])
    current_ids = {get_story_id(s): s for s in current_stories if get_story_id(s)}

    # Build a history view: check if we can find previous iteration data
    # Current limitation: phase outputs are not versioned per iteration
    # Workaround: use prd.json backups from prd-backups/ if available
    prev_output = _load_previous_iteration_stories(scratch_dir, phase, current_iter)
    prev_stories = prev_output.get("stories", [])
    prev_ids = {get_story_id(s): s for s in prev_stories if get_story_id(s)}

    # Detect changes
    added = []
    removed = []
    modified = []

    # Added: in current but not in prev
    for story_id, story in current_ids.items():
        if story_id not in prev_ids:
            added.append(story)

    # Removed: in prev but not in current
    for story_id, story in prev_ids.items():
        if story_id not in current_ids:
            removed.append(story)

    # Modified: in both but fields changed
    for story_id in current_ids:
        if story_id in prev_ids:
            current_fields = get_story_key_fields(current_ids[story_id])
            prev_fields = get_story_key_fields(prev_ids[story_id])

            changed_fields = [field for field in current_fields if current_fields[field] != prev_fields[field]]

            if changed_fields:
                modified.append(
                    {
                        "id": story_id,
                        "changedFields": changed_fields,
                    }
                )

    # Detect stuck stories: check if story appears in same phase for 3+ consecutive iterations
    stuck = _detect_stuck_stories(scratch_dir, phase, current_iter, current_ids)

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "stuck": stuck,
        "totalCompared": len(current_ids),
        "phase": phase,
        "iteration": current_iter,
    }


def _load_previous_iteration_stories(scratch_dir: Path, phase: Phase, current_iter: int) -> dict[str, Any]:
    """Load previous iteration's phase output.

    Currently: Look in prd-backups/ for previous PRD state and infer stories.
    Future: Should look in iteration-specific phase output directory.
    """
    if current_iter <= 1:
        return {"stories": []}

    # Check for prd-backups/ directory
    prev_iter = current_iter - 1
    backup_dir = scratch_dir / "prd-backups"

    if backup_dir.exists():
        # Look for prd-iter-N.json or similar pattern
        for backup_file in backup_dir.iterdir():
            if f"iter-{prev_iter}" in backup_file.name or f"-{prev_iter}." in backup_file.name:
                try:
                    with open(backup_file, encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict) and "userStories" in data:
                            stories = data["userStories"]
                            # Filter to stories that match this phase's context
                            return {"stories": stories[:] if isinstance(stories, list) else []}
                except (json.JSONDecodeError, OSError):
                    pass

    return {"stories": []}


def _detect_stuck_stories(
    scratch_dir: Path,
    phase: Phase,
    current_iter: int,
    current_stories: dict[str, dict[str, Any]],
    threshold: int = 3,
) -> list[dict[str, Any]]:
    """Detect stories that appear in the same phase for N+ consecutive iterations.

    Args:
        scratch_dir: Path to .spiral directory
        phase: Phase to check
        current_iter: Current iteration
        current_stories: Current iteration's story dict {id: story}
        threshold: Minimum consecutive iterations to be considered "stuck"

    Returns:
        List of {'id': 'US-123', 'stuckSince': 3} dicts
    """
    stuck = []

    # Walk back through iterations and count how many times each story appears
    story_iteration_count: dict[str, int] = {story_id: 1 for story_id in current_stories}

    for iter_num in range(current_iter - 1, max(0, current_iter - threshold), -1):
        prev_output = _load_previous_iteration_stories(scratch_dir, phase, iter_num)
        prev_stories = prev_output.get("stories", [])
        prev_ids = {get_story_id(s) for s in prev_stories if get_story_id(s)}

        for story_id in story_iteration_count:
            if story_id in prev_ids:
                story_iteration_count[story_id] += 1

    # Mark as stuck if appeared in threshold+ iterations
    for story_id, count in story_iteration_count.items():
        if count >= threshold:
            stuck.append(
                {
                    "id": story_id,
                    "stuckSince": count,
                }
            )

    return stuck


def run_phase_audit(
    phase: Phase | None = None,
    scratch_dir: Path | None = None,
) -> int:
    """Main CLI entrypoint for phase-audit command.

    Args:
        phase: Optional phase to audit. If None, compares most recent iterations.
        scratch_dir: Path to .spiral directory

    Returns:
        Exit code (0 on success)
    """
    if scratch_dir is None:
        scratch_dir = Path.cwd() / ".spiral"

    # Default to most recent iteration
    # For now, assume current iteration is 1 (limitation: no persistent iter tracking)
    # In future, read from _checkpoint.json
    current_iter = 1
    checkpoint_file = scratch_dir / "_checkpoint.json"
    if checkpoint_file.exists():
        try:
            with open(checkpoint_file, encoding="utf-8") as f:
                checkpoint = json.load(f)
                current_iter = checkpoint.get("iteration", 1)
        except (json.JSONDecodeError, OSError):
            pass

    # Default to Phase S if not specified
    audit_phase: Phase = phase if phase is not None else "S"

    result = compare_iterations(current_iter, audit_phase, scratch_dir)
    print(json.dumps(result, indent=2))
    return 0
