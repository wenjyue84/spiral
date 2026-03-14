#!/usr/bin/env bash
# lib/phases/phase_m_merge.sh — Phase M: MERGE
#
# Merges validated story candidates (from Phase S) into prd.json.
#
# Steps:
#   1. Snapshot prd.json (backup before write)
#   2. Call lib/merge_stories.py with validated candidates
#   3. Overflow: candidates that would push pending > SPIRAL_MAX_PENDING
#      are written to .spiral/_research_overflow.json for the next iteration
#   4. Schema validate patched prd.json (lib/prd_schema.py)
#
# Inputs:
#   .spiral/_validated_stories.json   — accepted candidates (from Phase S)
#   $PRD_FILE                         — prd.json to patch
#
# Outputs:
#   $PRD_FILE (patched)
#   .spiral/_research_overflow.json   — excess stories held for next iteration
#
# Config vars:
#   SPIRAL_MAX_PENDING   — max allowed pending stories (default: 50)
#
# TODO: extract Phase M block from spiral.sh (lines 1799–1870) into this file.
#       Update to read from _validated_stories.json instead of raw research output.

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_merge() {
  local iter="$1"
  echo "[Phase M] MERGE — iteration $iter"
  # TODO: implement (migrated from spiral.sh lines 1799–1870)
  :
}
