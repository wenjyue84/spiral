#!/usr/bin/env bash
# lib/impl/decompose.sh — Phase I sub-stage: STORY DECOMPOSITION
#
# Breaks oversized stories into smaller sub-stories before ralph attempts them.
# Called by phase_i_implement.sh before spawning workers.
#
# When a story fails 2+ times and is flagged as "too large", this module:
#   1. Calls lib/workers/decompose_story.py to split it into sub-stories
#   2. Marks the parent story with _decomposed: true (skipped by ralph)
#   3. Injects sub-stories into prd.json with _decomposedFrom: parent_id
#   4. Sub-stories are picked up automatically in the next worker dispatch
#
# Sub-stories follow the parent's priority and inherit its dependencies.
# Ralph ignores parent stories marked _decomposed: true (see ralph/CLAUDE.md rule 12).
#
# Inputs:
#   $PRD_FILE       — prd.json (read + write)
#   story_id        — ID of story to decompose (passed as argument)
#
# Outputs:
#   $PRD_FILE (patched: parent marked _decomposed, sub-stories added)
#
# Reference: lib/workers/decompose_story.py (existing implementation)

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# decompose_story <story_id> [model]
# Calls lib/workers/decompose_story.py and patches prd.json with sub-stories.
# Returns 0 on success, 1 on failure.
#
# Environment:
#   PRD_FILE       — path to prd.json (default: prd.json)
#   PROGRESS_FILE  — path to progress.txt (default: progress.txt)
#   SPIRAL_HOME    — repo root (default: .)
#   SPIRAL_PYTHON  — Python interpreter (default: python3)
decompose_story() {
  local story_id="$1"
  local model="${2:-sonnet}"
  local prd_file="${PRD_FILE:-prd.json}"
  local progress_file="${PROGRESS_FILE:-progress.txt}"
  local spiral_home="${SPIRAL_HOME:-.}"
  local python="${SPIRAL_PYTHON:-python3}"
  local decompose_script="$spiral_home/lib/workers/decompose_story.py"

  echo "[Phase I / decompose] Decomposing $story_id into sub-stories (model=$model)"

  if [[ ! -f "$prd_file" ]]; then
    echo "[Phase I / decompose] ERROR: $prd_file not found" >&2
    return 1
  fi

  if [[ ! -f "$decompose_script" ]]; then
    echo "[Phase I / decompose] ERROR: $decompose_script not found" >&2
    return 1
  fi

  "$python" "$decompose_script" \
    --story-id "$story_id" \
    --prd "$prd_file" \
    --model "$model" \
    --progress "$progress_file"
}
