#!/bin/bash
# lib/workers/profiler.sh — Per-phase timing measurements
#
# Exports functions to measure wall-clock time for sub-phases:
# - decompose_secs: time spent in story decomposition
# - impl_secs: time spent in implementation (AI invocation + edits)
# - verify_secs: time spent in verification (quality checks, tests)
#
# Usage:
#   source lib/workers/profiler.sh
#   phase_start "decompose"
#   # ... do decompose work ...
#   decompose_secs=$(phase_end "decompose")
#
#   phase_start "impl"
#   # ... do implementation work ...
#   impl_secs=$(phase_end "impl")
#
#   phase_start "verify"
#   # ... do verification work ...
#   verify_secs=$(phase_end "verify")

set -euo pipefail

# ── Phase timing state ──────────────────────────────────────────────────────
declare -gA _PHASE_START_TIME=() # map: phase_name -> seconds since epoch
declare -gA _PHASE_DURATION=()   # map: phase_name -> elapsed seconds

# Start measuring a named phase
# Arguments: phase_name (e.g., "decompose", "impl", "verify")
phase_start() {
  local phase_name="${1:?phase_name required}"
  _PHASE_START_TIME["$phase_name"]=$(date +%s%3N 2>/dev/null || date +%s)
}

# End measurement for a named phase, return elapsed seconds
# Arguments: phase_name (e.g., "decompose", "impl", "verify")
# Returns: elapsed seconds (integer, rounded down)
# Exports: {phase_name}_secs=<duration> to caller's environment
phase_end() {
  local phase_name="${1:?phase_name required}"
  local end_time
  local elapsed_ms
  local elapsed_sec

  end_time=$(date +%s%3N 2>/dev/null || date +%s)

  # Handle both millisecond and second precision
  if [[ "$end_time" =~ [0-9]+[0-9]{3}$ ]]; then
    # Millisecond precision (ms)
    elapsed_ms=$((end_time - _PHASE_START_TIME["$phase_name"]))
    elapsed_sec=$((elapsed_ms / 1000))
  else
    # Second precision
    elapsed_sec=$((end_time - _PHASE_START_TIME["$phase_name"]))
  fi

  _PHASE_DURATION["$phase_name"]=$elapsed_sec
  echo "$elapsed_sec"
}

# Get all phase durations as tab-separated values
# Output format: decompose_secs<TAB>impl_secs<TAB>verify_secs<TAB>retry_escalation_count
# Handles missing phases gracefully (defaults to 0)
get_phase_durations() {
  local decompose_secs="${_PHASE_DURATION[decompose]:-0}"
  local impl_secs="${_PHASE_DURATION[impl]:-0}"
  local verify_secs="${_PHASE_DURATION[verify]:-0}"
  local escalation_count="${_PHASE_ESCALATION_COUNT:-0}"

  echo -e "${decompose_secs}\t${impl_secs}\t${verify_secs}\t${escalation_count}"
}

# Increment retry escalation counter when model escalates (haiku→sonnet, sonnet→opus, etc)
# Called by ralph.sh when EFFECTIVE_MODEL changes
increment_escalation_count() {
  _PHASE_ESCALATION_COUNT=$((${_PHASE_ESCALATION_COUNT:-0} + 1))
}

# Reset all phase timings for a new story
reset_phase_timings() {
  _PHASE_START_TIME=()
  _PHASE_DURATION=()
  _PHASE_ESCALATION_COUNT=0
}
