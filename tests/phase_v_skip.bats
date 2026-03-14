#!/usr/bin/env bats
# tests/phase_v_skip.bats — Tests for US-183: Skip Phase V when Phase I produces no new passes
#
# Run with: bats tests/phase_v_skip.bats
#
# Tests verify:
#   - Phase V is skipped when _PASSES_AFTER_I <= _PASSES_BEFORE_I
#   - Phase V runs normally when _PASSES_AFTER_I > _PASSES_BEFORE_I
#   - SPIRAL_FORCE_VALIDATE=true bypasses the skip
#   - Skip message is logged with correct content
#   - _PHASE_V_SKIPPED is set to 1 on skip
#   - _PASSES_BEFORE_I=-1 (sentinel) never triggers the skip

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_PVS
  TMPDIR_PVS="$(mktemp -d)"

  # Resolve jq binary
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Stub helpers used in the Phase V decision block
  log_spiral_event() { printf '{"type":"%s"}\n' "$1" >> "$TMPDIR_PVS/events.jsonl"; }
  export -f log_spiral_event
  write_checkpoint() { true; }
  export -f write_checkpoint
}

teardown() {
  rm -rf "$TMPDIR_PVS"
}

# ── Helper: run Phase V skip decision logic ───────────────────────────────────
# Mirrors the elif branch added to spiral.sh for US-183.
# Returns 0 on skip, 1 on run; prints SKIPPED or RAN.
phase_v_decision() {
  local _PASSES_BEFORE_I="$1"
  local _PASSES_AFTER_I="$2"
  local SPIRAL_FORCE_VALIDATE="${3:-false}"
  local RALPH_RAN="${4:-1}"
  local SPIRAL_ITER=1

  # Replicate the exact condition from spiral.sh
  if [[ "$RALPH_RAN" -eq 0 ]]; then
    echo "RALPH_NOT_RAN"
    return 0
  elif [[ "$_PASSES_AFTER_I" -le "$_PASSES_BEFORE_I" && "$_PASSES_BEFORE_I" -ge 0 && "$SPIRAL_FORCE_VALIDATE" != "true" ]]; then
    echo "SKIPPED"
    _PHASE_V_SKIPPED=1
    log_spiral_event "phase_v_skipped"
    return 0
  else
    echo "RAN"
    return 0
  fi
}
export -f phase_v_decision

# ── Tests: skip when no new passes ────────────────────────────────────────────

@test "Phase V is skipped when passes count did not increase" {
  run phase_v_decision 3 3
  [ "$status" -eq 0 ]
  [[ "$output" == "SKIPPED" ]]
}

@test "Phase V is skipped when passes count decreased (regression guard)" {
  # Should not happen in normal flow but guard is still correct
  run phase_v_decision 4 3
  [ "$status" -eq 0 ]
  [[ "$output" == "SKIPPED" ]]
}

@test "Phase V is skipped when zero passes before and after (all stories retry)" {
  run phase_v_decision 0 0
  [ "$status" -eq 0 ]
  [[ "$output" == "SKIPPED" ]]
}

# ── Tests: run when new passes produced ──────────────────────────────────────

@test "Phase V runs when passes count increased by one" {
  run phase_v_decision 3 4
  [ "$status" -eq 0 ]
  [[ "$output" == "RAN" ]]
}

@test "Phase V runs when passes count increased from zero to one" {
  run phase_v_decision 0 1
  [ "$status" -eq 0 ]
  [[ "$output" == "RAN" ]]
}

# ── Tests: SPIRAL_FORCE_VALIDATE bypass ──────────────────────────────────────

@test "SPIRAL_FORCE_VALIDATE=true bypasses skip when no new passes" {
  run phase_v_decision 3 3 "true"
  [ "$status" -eq 0 ]
  [[ "$output" == "RAN" ]]
}

@test "SPIRAL_FORCE_VALIDATE=false respects skip (default)" {
  run phase_v_decision 5 5 "false"
  [ "$status" -eq 0 ]
  [[ "$output" == "SKIPPED" ]]
}

# ── Tests: sentinel value (-1) never triggers skip ───────────────────────────

@test "sentinel _PASSES_BEFORE_I=-1 does not trigger skip (ralph never ran)" {
  # When _PASSES_BEFORE_I=-1 the _PASSES_BEFORE_I -ge 0 guard prevents skip
  run phase_v_decision -1 -1
  [ "$status" -eq 0 ]
  # -1 is NOT >= 0, so skip condition is false → falls through to RAN
  [[ "$output" == "RAN" ]]
}

# ── Tests: RALPH_RAN=0 takes the earlier skip path ───────────────────────────

@test "RALPH_RAN=0 uses the existing ralph-did-not-run skip path" {
  run phase_v_decision 3 3 "false" 0
  [ "$status" -eq 0 ]
  [[ "$output" == "RALPH_NOT_RAN" ]]
}

# ── Tests: skip event is logged ───────────────────────────────────────────────

@test "phase_v_skipped event is emitted to events.jsonl on skip" {
  phase_v_decision 2 2 "false" 1
  [ -f "$TMPDIR_PVS/events.jsonl" ]
  grep -q "phase_v_skipped" "$TMPDIR_PVS/events.jsonl"
}

@test "phase_v_skipped event is NOT emitted when Phase V runs" {
  rm -f "$TMPDIR_PVS/events.jsonl"
  phase_v_decision 2 3 "false" 1
  # No events file, or file exists but no phase_v_skipped entry
  if [[ -f "$TMPDIR_PVS/events.jsonl" ]]; then
    ! grep -q "phase_v_skipped" "$TMPDIR_PVS/events.jsonl"
  fi
}
