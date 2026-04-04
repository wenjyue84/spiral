#!/usr/bin/env bats
# tests/checkpoint_atomic.bats — Integration tests for atomic checkpoint writes (US-1106)
#
# Run with: bats tests/checkpoint_atomic.bats
#
# Tests verify:
#   - write_checkpoint() produces valid JSON with schema_version field
#   - load_checkpoint() returns 0 for a valid checkpoint and populates CKPT_* vars
#   - Truncated checkpoint (crash simulation) triggers graceful recovery to iter 1
#   - Missing phase field triggers recovery to iter 1
#   - load_checkpoint() returns 1 when no checkpoint file exists

bats_require_minimum_version 1.7.0

setup() {
  load test_helper/common-setup
  _resolve_jq
  export SPIRAL_SCRATCH_DIR
  SPIRAL_SCRATCH_DIR="$(mktemp -d)"
  export CHECKPOINT_FILE="$SPIRAL_SCRATCH_DIR/_checkpoint.json"
  export JQ="${JQ:-jq}"
  export SPIRAL_RUN_ID="test-run-id"
  export SPIRAL_VERSION="test-1.0"
  export SPIRAL_LOG_LEVEL="INFO"
  export _PHASE_DUR_R=0 _PHASE_DUR_T=0 _PHASE_DUR_M=0
  export _PHASE_DUR_I=0 _PHASE_DUR_V=0 _PHASE_DUR_C=0

  # Source helpers
  source lib/spiral_helpers.sh
}

teardown() {
  rm -rf "$SPIRAL_SCRATCH_DIR"
}

# ── write_checkpoint tests ─────────────────────────────────────────────────────

@test "write_checkpoint: produces valid JSON" {
  run write_checkpoint 3 "M"
  assert_success
  [[ -f "$CHECKPOINT_FILE" ]]
  run "$JQ" -e '.' "$CHECKPOINT_FILE"
  assert_success
}

@test "write_checkpoint: checkpoint contains schema_version=1" {
  write_checkpoint 5 "I"
  run "$JQ" -r '.schema_version' "$CHECKPOINT_FILE"
  assert_success
  assert_output "1"
}

@test "write_checkpoint: writes to tmp file then renames (atomic)" {
  # The .tmp.$$ file must not exist after a successful write
  write_checkpoint 2 "V"
  local tmp_count
  tmp_count=$(ls "$SPIRAL_SCRATCH_DIR/_checkpoint.json.tmp."* 2>/dev/null | wc -l)
  [[ "$tmp_count" -eq 0 ]]
}

@test "write_checkpoint: checkpoint contains correct iter and phase" {
  write_checkpoint 7 "S"
  run "$JQ" -r '.iter' "$CHECKPOINT_FILE"
  assert_output "7"
  run "$JQ" -r '.phase' "$CHECKPOINT_FILE"
  assert_output "S"
}

# ── load_checkpoint tests ──────────────────────────────────────────────────────

@test "load_checkpoint: returns 1 when no checkpoint file exists" {
  rm -f "$CHECKPOINT_FILE"
  run load_checkpoint
  assert_failure 1
}

@test "load_checkpoint: returns 0 and populates CKPT_ITER for valid checkpoint" {
  write_checkpoint 4 "R"
  run load_checkpoint
  assert_success
}

@test "load_checkpoint: populates CKPT_ITER and CKPT_PHASE from valid checkpoint" {
  write_checkpoint 4 "R"
  load_checkpoint
  [[ "$CKPT_ITER" == "4" ]]
  [[ "$CKPT_PHASE" == "R" ]]
}

# ── Crash simulation (integration) ─────────────────────────────────────────────

@test "load_checkpoint: truncated checkpoint (crash simulation) triggers recovery" {
  # Simulate a crash mid-write: write truncated JSON (no closing brace)
  printf '{"schema_version":1,"iter":3,"phase":"I","ts":"2026-01-01T00:00:00Z"' \
    >"$CHECKPOINT_FILE"

  run load_checkpoint
  assert_failure 1
  assert_output --partial "Malformed JSON"
  # Corrupt file should be removed
  [[ ! -f "$CHECKPOINT_FILE" ]]
}

@test "load_checkpoint: empty file (crash simulation) triggers recovery" {
  printf '' >"$CHECKPOINT_FILE"
  run load_checkpoint
  assert_failure 1
  [[ ! -f "$CHECKPOINT_FILE" ]]
}

@test "load_checkpoint: non-numeric iter triggers recovery" {
  printf '{"schema_version":1,"iter":"bad","phase":"M","ts":"2026-01-01T00:00:00Z"}\n' \
    >"$CHECKPOINT_FILE"
  run load_checkpoint
  assert_failure 1
  assert_output --partial "invalid iter"
}

@test "load_checkpoint: missing phase triggers recovery" {
  printf '{"schema_version":1,"iter":2,"ts":"2026-01-01T00:00:00Z"}\n' \
    >"$CHECKPOINT_FILE"
  run load_checkpoint
  assert_failure 1
  assert_output --partial "empty phase"
}
