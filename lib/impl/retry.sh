#!/usr/bin/env bash
# lib/impl/retry.sh — Phase I sub-stage: RETRY LOGIC
#
# Manages the per-story attempt counter and enforces the 3-retry-skip rule.
# Called by phase_i_implement.sh after each ralph worker invocation.
#
# Rules:
#   - Each story starts with retries: 0 in prd.json
#   - On failure: increment retries field in prd.json
#   - At retries >= 3: mark story _skipped: true, log reason to progress.txt
#   - Skipped stories are excluded from future worker dispatch
#   - On the 2nd failure: flag story for decomposition (calls decompose.sh)
#
# Retry escalation (SPIRAL_MODEL_ROUTING=auto):
#   - Attempt 1: assigned model (haiku/sonnet based on complexity)
#   - Attempt 2: escalate to sonnet
#   - Attempt 3: escalate to opus
#   - Attempt 4+: skip
#
# Inputs:
#   story_id        — story that just failed
#   $PRD_FILE       — prd.json (read + write retries field)
#
# Outputs:
#   $PRD_FILE (retries incremented; _skipped added at threshold)
#   progress.txt (skip reason appended)
#
# Used by: phase_i_implement.sh after each worker returns passes: false

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# handle_story_failure <story_id> <current_retries>
# Returns 0 if story should be retried, 1 if it should be skipped.
handle_story_failure() {
  local story_id="$1"
  local retries="$2"
  echo "[Phase I / retry] Story $story_id failed (attempt $((retries + 1)))"
  # TODO: implement retry counter logic + model escalation
  :
}
