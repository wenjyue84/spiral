#!/usr/bin/env bash
# lib/phases/phase_0_clarify.sh — Phase 0: CLARIFY
#
# One-time interactive session that runs BEFORE the main loop begins.
# Purpose: align Claude and the user on goals, constraints, and an initial
# story backlog before any autonomous research or implementation starts.
#
# Called once from spiral.sh after config is loaded.
# Skipped if --gate proceed or --gate skip is passed (non-interactive mode).
#
# Sub-steps:
#   1. Focus area         — read SPIRAL_FOCUS or ask the user to set one
#   2. Clarifying Qs      — ask follow-up questions about goals/constraints
#   3. Story elaboration  — expand user-supplied seeds into full story objects
#   4. Constitution check — ensure elaborated stories comply with .specify/memory/constitution.md
#
# Outputs:
#   .spiral/_clarify_output.json   — initial stories added to prd.json
#   .spiral/_checkpoint.json       — checkpoint phase=0 (crash recovery)
#
# TODO: extract Phase 0 code from spiral.sh interactive gate block (lines 1897–1975)
#       and implement clarifying-questions + story-elaboration sub-steps here.

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_clarify() {
  echo "[Phase 0] CLARIFY — interactive setup"
  # Implementation migrated from spiral.sh Phase G block
  # TODO: implement
  :
}
