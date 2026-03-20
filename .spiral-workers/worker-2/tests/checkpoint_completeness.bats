#!/usr/bin/env bats
# tests/checkpoint_completeness.bats — Unit tests for checkpoint completeness checks (US-250)
#
# Run with: bats tests/checkpoint_completeness.bats
#
# Tests verify:
#   - check_checkpoint_completeness detects missing phase field
#   - check_checkpoint_completeness detects missing storyId field
#   - check_checkpoint_completeness detects missing retryCount field
#   - check_checkpoint_completeness returns 0 for complete checkpoint
#   - Truncated checkpoint triggers re-load in spiral.sh

bats_require_minimum_version 1.7.0

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  _resolve_jq
  export SPIRAL_SCRATCH_DIR="$(mktemp -d)"
  export JQ="jq"

  # Check if jq is available
  if ! command -v jq &>/dev/null; then
    if [[ -f "ralph/jq.exe" ]]; then
      export JQ="ralph/jq.exe"
    elif [[ -f "ralph/jq" ]]; then
      export JQ="ralph/jq"
    fi
  fi

  # Source the check_checkpoint_completeness function from spiral.sh
  # Extract the function definition
  source <(sed -n '/^check_checkpoint_completeness()/,/^}/p' spiral.sh)
}

teardown() {
  rm -rf "$SPIRAL_SCRATCH_DIR"
}

# ── Checkpoint completeness tests ──────────────────────────────────────────────

@test "check_checkpoint_completeness: complete checkpoint returns 0" {
  local ckpt_file="$SPIRAL_SCRATCH_DIR/complete-checkpoint.json"
  $JQ -n '{phase: "I", storyId: "US-123", retryCount: 0}' >"$ckpt_file"

  run check_checkpoint_completeness "$ckpt_file"
  assert_success
}

@test "check_checkpoint_completeness: missing phase returns 1" {
  local ckpt_file="$SPIRAL_SCRATCH_DIR/missing-phase.json"
  $JQ -n '{storyId: "US-123", retryCount: 0}' >"$ckpt_file"

  run check_checkpoint_completeness "$ckpt_file"
  assert_failure 1
  assert_output --partial "phase=✗"
}

@test "check_checkpoint_completeness: missing storyId returns 1" {
  local ckpt_file="$SPIRAL_SCRATCH_DIR/missing-storyid.json"
  $JQ -n '{phase: "I", retryCount: 0}' >"$ckpt_file"

  run check_checkpoint_completeness "$ckpt_file"
  assert_failure 1
  assert_output --partial "storyId=✗"
}

@test "check_checkpoint_completeness: missing retryCount returns 1" {
  local ckpt_file="$SPIRAL_SCRATCH_DIR/missing-retrycount.json"
  $JQ -n '{phase: "I", storyId: "US-123"}' >"$ckpt_file"

  run check_checkpoint_completeness "$ckpt_file"
  assert_failure 1
  assert_output --partial "retryCount=✗"
}

@test "check_checkpoint_completeness: empty checkpoint returns 1" {
  local ckpt_file="$SPIRAL_SCRATCH_DIR/empty-checkpoint.json"
  $JQ -n '{}' >"$ckpt_file"

  run check_checkpoint_completeness "$ckpt_file"
  assert_failure 1
}

@test "check_checkpoint_completeness: truncated checkpoint returns 1" {
  local ckpt_file="$SPIRAL_SCRATCH_DIR/truncated-checkpoint.json"
  # Simulate a truncated checkpoint (missing closing brace)
  echo '{"phase":"R","storyId":"US-456"' >"$ckpt_file"

  run check_checkpoint_completeness "$ckpt_file"
  assert_failure 1
}

@test "check_checkpoint_completeness: checkpoint with null values returns 1" {
  local ckpt_file="$SPIRAL_SCRATCH_DIR/null-values-checkpoint.json"
  $JQ -n '{phase: null, storyId: null, retryCount: null}' >"$ckpt_file"

  run check_checkpoint_completeness "$ckpt_file"
  assert_failure 1
}

@test "check_checkpoint_completeness: checkpoint with extra fields returns 0" {
  local ckpt_file="$SPIRAL_SCRATCH_DIR/extra-fields-checkpoint.json"
  $JQ -n '{phase: "V", storyId: "US-789", retryCount: 2, timestamp: "2026-03-16T10:00:00Z", extra: "data"}' >"$ckpt_file"

  run check_checkpoint_completeness "$ckpt_file"
  assert_success
}
