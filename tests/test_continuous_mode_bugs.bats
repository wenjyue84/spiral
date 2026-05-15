#!/usr/bin/env bats
# tests/test_continuous_mode_bugs.bats — Regression tests for continuous mode bugs
#
# Run with: bats tests/test_continuous_mode_bugs.bats
#
# Tests verify:
#   - checkpoint_phase_done handles empty $phase without crashing
#   - checkpoint_phase_done handles empty $ckpt_phase without crashing
#   - checkpoint_phase_done rejects unknown phase tokens
#   - safe_phase catches phase function errors in continuous mode
#   - SIGCHLD trap uses function-based handler (no inline action)

bats_require_minimum_version 1.7.0

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  _resolve_jq

  export SPIRAL_SCRATCH_DIR="$(mktemp -d)"
  export SCRATCH_DIR="$SPIRAL_SCRATCH_DIR"
  export CHECKPOINT_FILE="$SPIRAL_SCRATCH_DIR/_checkpoint.json"
  export SPIRAL_ITER=5
  export SPIRAL_HOME="$PWD"
  export JQ="jq"

  if ! command -v jq &>/dev/null; then
    if [[ -f "ralph/jq.exe" ]]; then
      export JQ="ralph/jq.exe"
    elif [[ -f "ralph/jq" ]]; then
      export JQ="ralph/jq"
    fi
  fi

  # Source spiral_helpers to get checkpoint_phase_done
  source lib/spiral_helpers.sh
}

teardown() {
  rm -rf "$SPIRAL_SCRATCH_DIR"
}

# ── Bug 1: checkpoint_phase_done with empty phases ───────────────────────────

@test "checkpoint_phase_done: empty \$phase returns 1, no error" {
  # Create a valid checkpoint at iter 5, phase M
  echo '{"iter":5,"phase":"M","ts":"2026-05-02T00:00:00Z"}' >"$CHECKPOINT_FILE"

  # Call with empty phase arg — should return 1 (not done), NOT crash
  run checkpoint_phase_done ""
  assert_failure # return 1 = phase not done
  # Must not contain "bad array subscript"
  refute_output --partial "bad array subscript"
}

@test "checkpoint_phase_done: empty ckpt_phase in checkpoint returns 1, no error" {
  # Create a checkpoint with empty phase field
  echo '{"iter":5,"phase":"","ts":"2026-05-02T00:00:00Z"}' >"$CHECKPOINT_FILE"

  run checkpoint_phase_done "V"
  assert_failure
  refute_output --partial "bad array subscript"
}

@test "checkpoint_phase_done: null ckpt_phase in checkpoint returns 1" {
  echo '{"iter":5,"ts":"2026-05-02T00:00:00Z"}' >"$CHECKPOINT_FILE"

  run checkpoint_phase_done "V"
  assert_failure
  refute_output --partial "bad array subscript"
}

@test "checkpoint_phase_done: unknown phase token returns 1" {
  echo '{"iter":5,"phase":"Z","ts":"2026-05-02T00:00:00Z"}' >"$CHECKPOINT_FILE"

  run checkpoint_phase_done "V"
  assert_failure
}

@test "checkpoint_phase_done: valid checkpoint phase done returns 0" {
  # Checkpoint at phase V (order 10), asking if phase M (order 6) is done → yes
  echo '{"iter":5,"phase":"V","ts":"2026-05-02T00:00:00Z"}' >"$CHECKPOINT_FILE"

  run checkpoint_phase_done "M"
  assert_success
}

@test "checkpoint_phase_done: valid checkpoint phase not yet done returns 1" {
  # Checkpoint at phase M (order 6), asking if phase V (order 10) is done → no
  echo '{"iter":5,"phase":"M","ts":"2026-05-02T00:00:00Z"}' >"$CHECKPOINT_FILE"

  run checkpoint_phase_done "V"
  assert_failure
}

# ── Bug 2: SIGCHLD trap must be function-based ───────────────────────────────

@test "SIGCHLD trap in spiral.sh uses function-based handler" {
  # Verify the SIGCHLD trap references a function, not an inline string with commands
  # This prevents trap parse errors when SIGCHLD fires during command substitution
  run grep -E "^trap _reap_zombies SIGCHLD" spiral.sh
  assert_success
  assert_output --partial "_reap_zombies"
}

@test "_reap_zombies function is defined in spiral.sh" {
  run grep -E "^_reap_zombies\(\)" spiral.sh
  assert_success
}

# ── Circuit breaker: safe_phase wrapper ──────────────────────────────────────

@test "safe_phase defined in spiral.sh" {
  run grep -E "^safe_phase\(\)" spiral.sh
  assert_success
}

@test "safe_phase wraps phase calls in main loop" {
  # All run_phase_* || continue calls should go through safe_phase
  run grep -c "safe_phase run_phase_" spiral.sh
  # Should find at least 5 wrapped phase calls
  [[ "${output}" -ge 5 ]]
}
