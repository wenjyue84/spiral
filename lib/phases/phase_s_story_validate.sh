#!/usr/bin/env bash
# lib/phases/phase_s_story_validate.sh — Phase S: STORY VALIDATE
#
# NEW PHASE — runs between Research (R/T) and Merge (M).
#
# Reviews all story candidates produced by Phase R and Phase T before
# they are committed to prd.json. Acts as a lightweight automated gate:
#
#   1. Constitution check  — reject stories that violate .specify/memory/constitution.md
#   2. Goal alignment      — reject stories with no clear connection to prd.json goals[]
#   3. Quality check       — reject stories with vague acceptance criteria or missing fields
#   4. Dedup check         — reject stories with > 60% title overlap with existing stories
#      (dedup is also done in Phase M, but catching it here saves a merge round-trip)
#
# Stories that fail any check are written to .spiral/_story_rejected.json
# with a rejection reason. Accepted stories pass through to Phase M.
#
# This replaces the human-review component of the old Phase G (Gate), which
# has been moved to Phase 0 (Clarify) as a one-time startup step.
#
# Inputs:
#   .spiral/_research_output.json      — Phase R candidates
#   .spiral/_test_stories_output.json  — Phase T candidates
#   $PRD_FILE                          — existing prd.json (for dedup)
#   $SPIRAL_SPECKIT_CONSTITUTION       — optional constitution file
#
# Outputs:
#   .spiral/_validated_stories.json    — accepted story candidates (→ Phase M)
#   .spiral/_story_rejected.json       — rejected stories with reasons (log only)
#
# TODO: implement story validation logic using jq + optional Claude review agent.

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_story_validate() {
  local iter="$1"
  echo "[Phase S] STORY VALIDATE — iteration $iter"
  # TODO: implement
  :
}
