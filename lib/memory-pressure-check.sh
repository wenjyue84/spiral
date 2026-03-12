#!/bin/bash
# memory-pressure-check.sh — Shared helper library for adaptive memory management
#
# Sourced by spiral.sh, ralph.sh, and run_parallel_ralph.sh.
# Reads the pressure signal file written by memory-watchdog.ps1.
#
# Usage: source lib/memory-pressure-check.sh
#        spiral_pressure_level          # → 0..4
#        spiral_recommended_workers     # → integer or empty
#        spiral_recommended_model       # → haiku|sonnet|opus or empty
#        spiral_should_skip_phase "R"   # → returns 0 (skip) or 1 (don't skip)
#        spiral_log_low_power "msg"     # → appends to _low_power.log
#        spiral_pressure_free_mb        # → free MB or empty

# Signal file path — set by the sourcing script via SPIRAL_SCRATCH_DIR
_SPIRAL_PRESSURE_FILE="${SPIRAL_SCRATCH_DIR:-.spiral}/_memory_pressure.json"
_SPIRAL_LOW_POWER_LOG="${SPIRAL_SCRATCH_DIR:-.spiral}/_low_power.log"
_SPIRAL_LOW_POWER_FLAG="${SPIRAL_SCRATCH_DIR:-.spiral}/_low_power_active"

# Max age (seconds) for the pressure file to be considered valid
_SPIRAL_PRESSURE_MAX_AGE=120

# JQ binary — inherits from the caller or finds it
_PRESSURE_JQ="${JQ:-jq}"

# ── Internal: check if pressure file exists and is fresh ──────────────────────
_spiral_pressure_file_fresh() {
  [[ -f "$_SPIRAL_PRESSURE_FILE" ]] || return 1

  # Check file age using file modification time (portable across GNU/macOS)
  local now_ts file_ts age
  now_ts=$(date +%s)
  file_ts=$(stat -c %Y "$_SPIRAL_PRESSURE_FILE" 2>/dev/null || \
            stat -f %m "$_SPIRAL_PRESSURE_FILE" 2>/dev/null || echo "0")
  age=$(( now_ts - file_ts ))
  [[ "$age" -le "$_SPIRAL_PRESSURE_MAX_AGE" ]]
}

# ── spiral_pressure_level — returns current pressure level (0-4) ──────────────
# Returns 0 if no pressure file or file is stale.
spiral_pressure_level() {
  if ! _spiral_pressure_file_fresh; then
    echo "0"
    return
  fi
  "$_PRESSURE_JQ" -r '.level // 0' "$_SPIRAL_PRESSURE_FILE" 2>/dev/null || echo "0"
}

# ── spiral_recommended_workers — returns recommended worker count ─────────────
# Returns empty string if no valid data.
spiral_recommended_workers() {
  if ! _spiral_pressure_file_fresh; then
    echo ""
    return
  fi
  local val
  val=$("$_PRESSURE_JQ" -r '.recommended_workers // ""' "$_SPIRAL_PRESSURE_FILE" 2>/dev/null || echo "")
  # Return empty for 0 or non-numeric
  [[ "$val" =~ ^[0-9]+$ && "$val" -gt 0 ]] && echo "$val" || echo ""
}

# ── spiral_recommended_model — returns model cap (or empty if no cap) ─────────
spiral_recommended_model() {
  if ! _spiral_pressure_file_fresh; then
    echo ""
    return
  fi
  local val
  val=$("$_PRESSURE_JQ" -r '.recommended_model // ""' "$_SPIRAL_PRESSURE_FILE" 2>/dev/null || echo "")
  echo "$val"
}

# ── spiral_should_skip_phase — returns 0 (true=skip) or 1 (false=don't skip) ─
# Usage: spiral_should_skip_phase "R" && echo "skipping R"
spiral_should_skip_phase() {
  local phase="$1"
  if ! _spiral_pressure_file_fresh; then
    return 1  # don't skip
  fi
  local skip_list
  skip_list=$("$_PRESSURE_JQ" -r '.skip_phases // [] | .[]' "$_SPIRAL_PRESSURE_FILE" 2>/dev/null)
  local p
  for p in $skip_list; do
    if [[ "$p" == "$phase" ]]; then
      return 0  # yes, skip this phase
    fi
  done
  return 1  # don't skip
}

# ── spiral_log_low_power — appends a timestamped entry to the low-power log ───
spiral_log_low_power() {
  local msg="$1"
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "[$ts] $msg" >> "$_SPIRAL_LOW_POWER_LOG" 2>/dev/null || true
}

# ── spiral_pressure_free_mb — returns free MB from signal file ────────────────
spiral_pressure_free_mb() {
  if ! _spiral_pressure_file_fresh; then
    echo ""
    return
  fi
  "$_PRESSURE_JQ" -r '.free_mb // ""' "$_SPIRAL_PRESSURE_FILE" 2>/dev/null || echo ""
}
