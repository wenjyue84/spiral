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

# invoke_exhaustion_analyzer <story_id> <attempts_json_file>
# Runs lib/impl/exhaustion_analyzer.py and writes the JSON report to
# .spiral/exhausted_stories/<story_id>_analysis.json.
# Silently skips if Python or the analyzer script is unavailable.
invoke_exhaustion_analyzer() {
  local story_id="$1"
  local attempts_file="${2:-}"
  local analyzer_script
  analyzer_script="$(dirname "${BASH_SOURCE[0]}")/exhaustion_analyzer.py"
  local output_dir=".spiral/exhausted_stories"
  local output_file="${output_dir}/${story_id}_analysis.json"

  if [[ ! -f "$analyzer_script" ]]; then
    echo "[Phase I / retry] exhaustion_analyzer.py not found, skipping report" >&2
    return 0
  fi
  if [[ -z "$attempts_file" || ! -f "$attempts_file" ]]; then
    echo "[Phase I / retry] No attempts file provided for $story_id, skipping exhaustion report" >&2
    return 0
  fi

  mkdir -p "$output_dir"
  if uv run python "$analyzer_script" \
    --story-id "$story_id" \
    --attempts "$attempts_file" \
    --output "$output_file" 2>&1; then
    echo "[Phase I / retry] Exhaustion report written: $output_file"
  else
    echo "[Phase I / retry] Exhaustion analyzer failed for $story_id (non-fatal)" >&2
  fi
  return 0
}

# handle_story_failure <story_id> <current_retries> [failure_reason]
# Records the failure reason as an anti-pattern on the story (Strategy 1).
# Returns 0 always (non-fatal — caller decides skip vs retry).
#
# When SPIRAL_ANTI_PATTERN_INJECT=true (default), appends failure_reason to
# _antiPatterns[] in prd.json so the next retry prompt shows a "FORBIDDEN
# APPROACHES" list and the agent tries a different implementation.
handle_story_failure() {
  local story_id="$1"
  local retries="$2"
  local failure_reason="${3:-}"
  local prd_file="${PRD_FILE:-prd.json}"
  local jq_bin="${JQ:-jq}"

  echo "[Phase I / retry] Story $story_id failed (attempt $((retries + 1)))"

  # Strategy 1: anti-pattern accumulation
  if [[ "${SPIRAL_ANTI_PATTERN_INJECT:-true}" == "true" && -n "$failure_reason" && -f "$prd_file" ]]; then
    # Truncate to 200 chars and strip characters unsafe for jq --arg
    local truncated
    truncated=$(printf '%s' "$failure_reason" | head -c 200 | tr -d '\n\r"\\')
    if [[ -n "$truncated" ]]; then
      "$jq_bin" --arg sid "$story_id" --arg note "$truncated" \
        '(.userStories[] | select(.id == $sid) | ._antiPatterns) |= (. // []) + [$note]' \
        "$prd_file" >"${prd_file}.tmp" && mv "${prd_file}.tmp" "$prd_file" || true
      echo "[Phase I / retry] Anti-pattern recorded for $story_id: ${truncated:0:60}..."
    fi
  fi
  return 0
}
