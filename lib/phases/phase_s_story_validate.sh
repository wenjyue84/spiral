#!/usr/bin/env bash
# lib/phases/phase_s_story_validate.sh — Phase S: STORY VALIDATE
#
# Runs between Research (R/T) and Merge (M).
#
# Reviews all story candidates produced by Phase R and Phase T before
# they are committed to prd.json. Acts as a lightweight automated gate:
#
#   1. Constitution check  — reject stories that violate SPIRAL_SPECKIT_CONSTITUTION
#   2. Goal alignment      — reject stories with no clear connection to prd.json goals[]
#
# Stories that fail any check are written to .spiral/_story_rejected.json
# with a rejection reason. Accepted stories pass through to Phase M via
# .spiral/_validated_stories.json.
#
# Inputs:
#   $RESEARCH_OUTPUT                   — Phase R candidates (_research_output.json)
#   $TEST_OUTPUT                       — Phase T candidates (_test_stories_output.json)
#   $PRD_FILE                          — existing prd.json (for goals[])
#   $SPIRAL_SPECKIT_CONSTITUTION       — optional constitution file path
#   $SPIRAL_STORY_VALIDATE_MIN_OVERLAP — min keyword overlap to accept (default: 1)
#
# Outputs:
#   .spiral/_validated_stories.json    — accepted story candidates (→ Phase M)
#   .spiral/_story_rejected.json       — rejected stories with reasons (log only)

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_story_validate() {
  local iter="$1"
  local research_output="${2:-$RESEARCH_OUTPUT}"
  local test_output="${3:-$TEST_OUTPUT}"
  local prd_file="${4:-$PRD_FILE}"
  local scratch_dir="${5:-$SCRATCH_DIR}"
  local spiral_python="${6:-$SPIRAL_PYTHON}"
  local spiral_home="${7:-$SPIRAL_HOME}"
  local ai_suggest_output="${8:-}"          # Phase A: Source 2 (ai-example) candidates
  local test_story_candidates="${9:-}"      # Source 5 (test-story) candidates

  local validated_out="$scratch_dir/_validated_stories.json"
  local rejected_out="$scratch_dir/_story_rejected.json"

  # Build optional constitution arg
  local constitution_arg=()
  if [[ -n "${SPIRAL_SPECKIT_CONSTITUTION:-}" && -f "${SPIRAL_SPECKIT_CONSTITUTION}" ]]; then
    constitution_arg=("--constitution" "$SPIRAL_SPECKIT_CONSTITUTION")
  fi

  # Build optional Phase A and Source 5 args
  local ai_suggest_arg=()
  if [[ -n "$ai_suggest_output" && -f "$ai_suggest_output" ]]; then
    ai_suggest_arg=("--ai-suggest" "$ai_suggest_output")
  fi
  local test_story_arg=()
  if [[ -n "$test_story_candidates" && -f "$test_story_candidates" ]]; then
    test_story_arg=("--test-story-candidates" "$test_story_candidates")
  fi

  local min_overlap="${SPIRAL_STORY_VALIDATE_MIN_OVERLAP:-1}"

  # Run Python validation script
  if "$spiral_python" "$spiral_home/lib/validate_stories.py" \
    --prd "$prd_file" \
    --research "${research_output:-/dev/null}" \
    --test-stories "${test_output:-/dev/null}" \
    --validated-out "$validated_out" \
    --rejected-out "$rejected_out" \
    "${constitution_arg[@]}" \
    "${ai_suggest_arg[@]}" \
    "${test_story_arg[@]}" \
    --min-overlap "$min_overlap"; then
    : # success
  else
    echo "  [S] WARNING: Story validation failed — passing all stories through"
    # Fallback: copy research output as validated (accept all)
    if [[ -f "${research_output:-}" ]]; then
      cp "$research_output" "$validated_out"
    else
      echo '{"stories":[]}' >"$validated_out"
    fi
    echo '{"stories":[]}' >"$rejected_out"
  fi
}
