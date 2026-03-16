#!/usr/bin/env bats
# tests/cascade_fan_out.bats — Tests for US-322: Cascading-failure fan-out cap
#
# Run with: bats tests/cascade_fan_out.bats
#
# Tests verify:
#   - SPIRAL_CASCADE_FAN_OUT_LIMIT defaults to 5
#   - Consecutive failures increment the counter
#   - Counter resets on success
#   - Fan-out limit triggers cascade_abort exit
#   - cascade_abort event is logged to spiral_events.jsonl

bats_require_minimum_version 1.7.0

# ── Helpers ──────────────────────────────────────────────────────────────────

_setup_env() {
  export SCRATCH_DIR="$TEST_DIR/scratch"
  export SPIRAL_RUN_ID="test-cascade-001"
  export SPIRAL_ITER=1
  export SPIRAL_LOG_LEVEL="INFO"
  mkdir -p "$SCRATCH_DIR"

  # Detect jq
  if command -v jq &>/dev/null; then
    JQ="jq"
  elif [[ -f "$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/ralph/jq.exe" ]]; then
    JQ="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/ralph/jq.exe"
  else
    skip "jq not available"
  fi
  export JQ

  # Source spiral_events.sh for log_spiral_event
  SPIRAL_HOME="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$SPIRAL_HOME/lib/spiral_events.sh"
}

# Simulates the cascade fan-out logic from spiral.sh Phase I.
# Args: LIMIT RESULTS...  (each result is "STORY_ID:pass" or "STORY_ID:fail")
# Returns: 15 (ERR_CASCADE_ABORT) if limit exceeded, 0 otherwise.
# Writes cascade_abort event to SCRATCH_DIR/spiral_events.jsonl on abort.
_simulate_cascade() {
  local limit="$1"; shift
  local _CASCADE_FAIL_COUNT=0
  local _CASCADE_FAIL_IDS=""
  local SPIRAL_CASCADE_FAN_OUT_LIMIT="$limit"
  local SPIRAL_ITER=1
  local CHECKPOINT_FILE="$TEST_DIR/checkpoint.json"

  for entry in "$@"; do
    local sid="${entry%%:*}"
    local result="${entry##*:}"

    if [[ "$result" == "pass" ]]; then
      _CASCADE_FAIL_COUNT=0
      _CASCADE_FAIL_IDS=""
    else
      _CASCADE_FAIL_COUNT=$((_CASCADE_FAIL_COUNT + 1))
      _CASCADE_FAIL_IDS="${_CASCADE_FAIL_IDS:+$_CASCADE_FAIL_IDS,}$sid"
      if [[ "$SPIRAL_CASCADE_FAN_OUT_LIMIT" -gt 0 && "$_CASCADE_FAIL_COUNT" -ge "$SPIRAL_CASCADE_FAN_OUT_LIMIT" ]]; then
        log_spiral_event "cascade_abort" \
          "\"iteration\":$SPIRAL_ITER,\"consecutive_failures\":$_CASCADE_FAIL_COUNT,\"failing_ids\":\"$_CASCADE_FAIL_IDS\",\"limit\":$SPIRAL_CASCADE_FAN_OUT_LIMIT"
        echo "CASCADE_ABORT: $_CASCADE_FAIL_COUNT consecutive failures: $_CASCADE_FAIL_IDS"
        return 15
      fi
    fi
  done
  echo "OK: cascade_fail_count=$_CASCADE_FAIL_COUNT"
  return 0
}

# ── Setup / Teardown ─────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  _resolve_jq
  TEST_DIR="$(mktemp -d)"
  _setup_env
}

teardown() {
  rm -rf "$TEST_DIR" 2>/dev/null || true
}

# ── Tests ────────────────────────────────────────────────────────────────────

@test "SPIRAL_CASCADE_FAN_OUT_LIMIT defaults to 5 in spiral.sh" {
  SPIRAL_HOME="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  # Extract the default value from the variable declaration
  default=$(grep 'SPIRAL_CASCADE_FAN_OUT_LIMIT=' "$SPIRAL_HOME/spiral.sh" \
    | head -1 | sed -nE 's/.*:-([0-9]+)\}.*/\1/p')
  [ "$default" = "5" ]
}

@test "consecutive failures below limit do not trigger abort" {
  # 4 failures with limit 5 — should NOT abort
  run _simulate_cascade 5 "US-001:fail" "US-002:fail" "US-003:fail" "US-004:fail"
  assert_success
  assert_output --partial "cascade_fail_count=4"
}

@test "consecutive failures at limit trigger cascade abort" {
  # 5 failures with limit 5 — should abort
  run _simulate_cascade 5 "US-001:fail" "US-002:fail" "US-003:fail" "US-004:fail" "US-005:fail"
  assert_failure 15
  assert_output --partial "CASCADE_ABORT"
  assert_output --partial "5 consecutive failures"
  assert_output --partial "US-001"
  assert_output --partial "US-005"
}

@test "success resets consecutive failure counter" {
  # 3 fails, then 1 pass, then 3 more fails — counter resets at pass
  run _simulate_cascade 5 "US-001:fail" "US-002:fail" "US-003:fail" \
    "US-004:pass" \
    "US-005:fail" "US-006:fail" "US-007:fail"
  assert_success
  assert_output --partial "cascade_fail_count=3"
}

@test "cascade_abort event is logged to spiral_events.jsonl" {
  _simulate_cascade 3 "US-A:fail" "US-B:fail" "US-C:fail" || true

  [ -f "$SCRATCH_DIR/spiral_events.jsonl" ]
  grep -q "cascade_abort" "$SCRATCH_DIR/spiral_events.jsonl"
  grep -q "US-A" "$SCRATCH_DIR/spiral_events.jsonl"
  grep -q "US-C" "$SCRATCH_DIR/spiral_events.jsonl"

  # Verify event JSON fields
  line=$(grep "cascade_abort" "$SCRATCH_DIR/spiral_events.jsonl" | tail -1)
  echo "$line" | $JQ -e '.consecutive_failures == 3' >/dev/null
  echo "$line" | $JQ -e '.limit == 3' >/dev/null
  echo "$line" | $JQ -e '.failing_ids == "US-A,US-B,US-C"' >/dev/null
}

@test "limit 0 disables cascade abort (unlimited failures allowed)" {
  # 10 failures with limit 0 — should NOT abort
  run _simulate_cascade 0 \
    "US-01:fail" "US-02:fail" "US-03:fail" "US-04:fail" "US-05:fail" \
    "US-06:fail" "US-07:fail" "US-08:fail" "US-09:fail" "US-10:fail"
  assert_success
  assert_output --partial "cascade_fail_count=10"
}
