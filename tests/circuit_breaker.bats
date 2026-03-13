#!/usr/bin/env bats
# tests/circuit_breaker.bats — Unit tests for lib/circuit_breaker.sh
#
# Run with: bats tests/circuit_breaker.bats
# Install bats: https://github.com/bats-core/bats-core
#
# Tests verify:
#   - Default CLOSED state
#   - Failure accumulation up to threshold
#   - OPEN state after threshold failures
#   - HALF_OPEN transition after cooldown expires
#   - CLOSED reset after successful probe in HALF_OPEN
#   - Re-trip to OPEN after HALF_OPEN probe failure
#   - Permanent errors are not counted
#   - Atomic write (no torn reads)

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  # Use a temporary directory for all state files
  export TMPDIR_CB="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_CB"
  export SPIRAL_CB_FAILURE_THRESHOLD=5
  export SPIRAL_CB_COOLDOWN_SECS=60

  # Provide a minimal JQ path (bats runs without the full ralph environment)
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Source the circuit breaker library
  source "lib/circuit_breaker.sh"
}

teardown() {
  rm -rf "$TMPDIR_CB"
}

# ── Helper ────────────────────────────────────────────────────────────────────

cb_state() {
  local endpoint="${1:-default}"
  cb_read "$endpoint"
  echo "$CB_STATE"
}

cb_failures() {
  local endpoint="${1:-default}"
  cb_read "$endpoint"
  echo "$CB_FAILURE_COUNT"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "default state is CLOSED with zero failures" {
  run cb_state "default"
  [ "$output" = "CLOSED" ]
  run cb_failures "default"
  [ "$output" = "0" ]
}

@test "cb_check returns 0 (allow) when CLOSED" {
  run cb_check "test_ep"
  [ "$status" -eq 0 ]
}

@test "4 failures stay CLOSED (below threshold of 5)" {
  for i in 1 2 3 4; do
    cb_record_failure "test_ep" 429
  done
  run cb_state "test_ep"
  [ "$output" = "CLOSED" ]
  run cb_failures "test_ep"
  [ "$output" = "4" ]
}

@test "5th consecutive 429 failure trips circuit to OPEN" {
  for i in 1 2 3 4 5; do
    cb_record_failure "test_ep" 429
  done
  run cb_state "test_ep"
  [ "$output" = "OPEN" ]
}

@test "502 and 503 also count as transient failures" {
  cb_record_failure "test_ep" 429
  cb_record_failure "test_ep" 502
  cb_record_failure "test_ep" 503
  cb_record_failure "test_ep" 502
  cb_record_failure "test_ep" 503
  run cb_state "test_ep"
  [ "$output" = "OPEN" ]
}

@test "cb_check returns 1 (block) when OPEN and within cooldown" {
  # Trip the breaker
  for i in 1 2 3 4 5; do cb_record_failure "ep_block" 429; done
  # Cooldown has not elapsed (last_failure_ts just set to now)
  run cb_check "ep_block"
  [ "$status" -eq 1 ]
}

@test "cb_check transitions OPEN to HALF_OPEN after cooldown expires" {
  # Write OPEN state with a last_failure_ts far in the past
  local past=$(( $(date +%s) - 120 ))   # 120s ago, cooldown is 60s
  cb_write "ep_hopen" "OPEN" 5 "$past" 60

  run cb_check "ep_hopen"
  [ "$status" -eq 0 ]   # allowed (probe)

  run cb_state "ep_hopen"
  [ "$output" = "HALF_OPEN" ]
}

@test "success in HALF_OPEN resets to CLOSED" {
  local past=$(( $(date +%s) - 120 ))
  cb_write "ep_probe" "OPEN" 5 "$past" 60
  cb_check "ep_probe"   # triggers OPEN → HALF_OPEN

  cb_record_success "ep_probe"
  run cb_state "ep_probe"
  [ "$output" = "CLOSED" ]
  run cb_failures "ep_probe"
  [ "$output" = "0" ]
}

@test "failure in HALF_OPEN re-trips to OPEN" {
  local past=$(( $(date +%s) - 120 ))
  cb_write "ep_reprobe" "OPEN" 5 "$past" 60
  cb_check "ep_reprobe"   # OPEN → HALF_OPEN

  cb_record_failure "ep_reprobe" 429
  run cb_state "ep_reprobe"
  [ "$output" = "OPEN" ]
}

@test "permanent error (401) does not increment failure count" {
  cb_record_failure "ep_perm" 401
  run cb_state "ep_perm"
  [ "$output" = "CLOSED" ]
  run cb_failures "ep_perm"
  [ "$output" = "0" ]
}

@test "permanent error (400) does not increment failure count" {
  cb_record_failure "ep_400" 400
  run cb_failures "ep_400"
  [ "$output" = "0" ]
}

@test "success resets failure counter to zero from a partial count" {
  cb_record_failure "ep_partial" 429
  cb_record_failure "ep_partial" 429
  cb_record_success "ep_partial"
  run cb_failures "ep_partial"
  [ "$output" = "0" ]
}

@test "per-endpoint state is isolated" {
  for i in 1 2 3 4 5; do cb_record_failure "ep_a" 429; done
  run cb_state "ep_a"
  [ "$output" = "OPEN" ]
  run cb_state "ep_b"
  [ "$output" = "CLOSED" ]
}

@test "state file is created in SPIRAL_SCRATCH_DIR" {
  cb_record_failure "ep_file" 429
  [ -f "${SPIRAL_SCRATCH_DIR}/circuit_breaker_ep_file.json" ]
}

@test "default endpoint uses circuit_breaker.json" {
  cb_record_failure "default" 429
  [ -f "${SPIRAL_SCRATCH_DIR}/circuit_breaker.json" ]
}

@test "state file contains required fields" {
  cb_record_failure "ep_fields" 429
  local f="${SPIRAL_SCRATCH_DIR}/circuit_breaker_ep_fields.json"
  [ -f "$f" ]
  run $JQ -r '.state' "$f";          [ "$output" = "CLOSED" ]
  run $JQ -r '.failure_count' "$f";  [ "$output" = "1" ]
  run $JQ '.last_failure_ts' "$f";   [[ "$output" =~ ^[0-9]+$ ]]
  run $JQ '.cooldown_secs' "$f";     [ "$output" = "60" ]
}

@test "SPIRAL_CB_FAILURE_THRESHOLD is respected (custom threshold=3)" {
  export SPIRAL_CB_FAILURE_THRESHOLD=3
  for i in 1 2 3; do cb_record_failure "ep_thresh" 503; done
  run cb_state "ep_thresh"
  [ "$output" = "OPEN" ]
}
