#!/usr/bin/env bats
# tests/flaky_tests.bats — Unit tests for lib/flaky_tests.sh (US-240)
#
# Run with: bats tests/flaky_tests.bats
#
# Tests verify:
#   - flaky_record_result writes a valid JSON registry
#   - flaky_is_quarantined returns false for healthy tests
#   - flaky_is_quarantined returns true after threshold failures
#   - History is capped at SPIRAL_FLAKY_WINDOW entries
#   - Quarantine is lifted after SPIRAL_FLAKY_CONSEC consecutive passes
#   - flaky_gate_exit_code returns 0 for quarantined failures
#   - flaky_gate_exit_code preserves exit code for non-quarantined tests
#   - flaky_report prints a summary without error
#   - flaky_list_quarantined outputs quarantined names only
#   - Registry persists across source calls (file-based)
#   - Tests need at least 5 samples before quarantining

# ── Setup / teardown ──────────────────────────────────────────────────────────

setup() {
  export SPIRAL_SCRATCH_DIR
  SPIRAL_SCRATCH_DIR="$(mktemp -d)"
  export SPIRAL_FLAKY_THRESHOLD="0.3"
  export SPIRAL_FLAKY_WINDOW="20"
  export SPIRAL_FLAKY_CONSEC="10"

  # Resolve jq (mirrors circuit_breaker.bats pattern)
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  else
    export JQ="jq"
  fi

  # Source the library under test (from project root)
  source "lib/flaky_tests.sh"
}

# Read a field from the registry using jq (works on Windows — path via arg, not -c string)
reg_get() {
  local field="$1"     # jq filter, e.g. '.my_test.passes'
  local reg_path="${SPIRAL_SCRATCH_DIR}/flaky-tests.json"
  "$JQ" -r "$field" "$reg_path"
}

teardown() {
  rm -rf "$SPIRAL_SCRATCH_DIR"
}

# ── Helper ────────────────────────────────────────────────────────────────────

# Record N pass results for a test
record_passes() {
  local name="$1"
  local count="$2"
  for _ in $(seq 1 "$count"); do
    flaky_record_result "$name" "pass"
  done
}

# Record N fail results for a test
record_fails() {
  local name="$1"
  local count="$2"
  for _ in $(seq 1 "$count"); do
    flaky_record_result "$name" "fail"
  done
}

# ── Tests: flaky_record_result ────────────────────────────────────────────────

@test "flaky_record_result creates registry file" {
  flaky_record_result "my_test" "pass"
  local reg_path="${SPIRAL_SCRATCH_DIR}/flaky-tests.json"
  [ -f "$reg_path" ]
}

@test "flaky_record_result stores valid JSON" {
  flaky_record_result "my_test" "pass"
  local reg_path="${SPIRAL_SCRATCH_DIR}/flaky-tests.json"
  # Use jq to validate JSON (path passed as CLI arg — Git Bash translates it)
  "$JQ" empty "$reg_path"
}

@test "flaky_record_result increments passes count" {
  flaky_record_result "my_test" "pass"
  flaky_record_result "my_test" "pass"
  local passes
  passes=$(reg_get '.my_test.passes')
  [ "$passes" -eq 2 ]
}

@test "flaky_record_result increments failures count" {
  flaky_record_result "my_test" "fail"
  flaky_record_result "my_test" "fail"
  local failures
  failures=$(reg_get '.my_test.failures')
  [ "$failures" -eq 2 ]
}

@test "flaky_record_result caps history at SPIRAL_FLAKY_WINDOW" {
  export SPIRAL_FLAKY_WINDOW=5
  source "lib/flaky_tests.sh"
  record_passes "my_test" 10
  local hist_len
  hist_len=$(reg_get '.my_test.history | length')
  [ "$hist_len" -eq 5 ]
}

# ── Tests: flaky_is_quarantined ───────────────────────────────────────────────

@test "flaky_is_quarantined returns false for unknown test" {
  run flaky_is_quarantined "unknown_test"
  [ "$status" -eq 1 ]
}

@test "flaky_is_quarantined returns false for healthy test" {
  record_passes "healthy_test" 10
  run flaky_is_quarantined "healthy_test"
  [ "$status" -eq 1 ]
}

@test "flaky_is_quarantined requires at least 5 samples before quarantining" {
  # 3 fails out of 4 would be 75% > threshold, but < 5 samples
  record_fails "early_test" 3
  record_passes "early_test" 1
  run flaky_is_quarantined "early_test"
  [ "$status" -eq 1 ]
}

@test "flaky_is_quarantined returns true after threshold failures (5+ samples)" {
  # 5 fails out of 10 = 50% > 0.3 threshold, 10 samples >= 5
  record_fails "flaky_test" 5
  record_passes "flaky_test" 5
  run flaky_is_quarantined "flaky_test"
  [ "$status" -eq 0 ]
}

@test "flaky_is_quarantined returns false when failure rate is at or below threshold" {
  # 3 fails out of 10 = 30% — equal to threshold (not strictly above)
  record_passes "borderline_test" 7
  record_fails "borderline_test" 3
  run flaky_is_quarantined "borderline_test"
  # 30% is NOT above 0.3 (strict greater-than), so should not quarantine
  [ "$status" -eq 1 ]
}

# ── Tests: quarantine lifting ─────────────────────────────────────────────────

@test "quarantine is lifted after consecutive passes" {
  export SPIRAL_FLAKY_CONSEC=3
  source "lib/flaky_tests.sh"

  # Quarantine the test: alternate fail/pass to accumulate failures
  # without building consecutive pass streak (5 fails, 2 passes = 5/7 = 71% > 0.3)
  record_fails "recover_test" 5
  record_passes "recover_test" 2
  # Reset consecutive counter with a final fail
  record_fails "recover_test" 1

  # Should be quarantined now (6/8 = 75% > 0.3)
  run flaky_is_quarantined "recover_test"
  [ "$status" -eq 0 ]

  # Now add exactly CONSEC=3 consecutive passes — should lift quarantine
  record_passes "recover_test" 3

  run flaky_is_quarantined "recover_test"
  [ "$status" -eq 1 ]
}

@test "consecutive pass counter resets on failure" {
  export SPIRAL_FLAKY_CONSEC=3
  source "lib/flaky_tests.sh"

  # Quarantine it
  record_fails "reset_test" 5
  record_passes "reset_test" 5

  # Add 2 passes then a fail — consec should reset
  record_passes "reset_test" 2
  record_fails "reset_test" 1

  local consec
  consec=$(reg_get '.reset_test.consecutivePasses')
  [ "$consec" -eq 0 ]
}

# ── Tests: flaky_gate_exit_code ───────────────────────────────────────────────

@test "flaky_gate_exit_code returns 0 for quarantined test failure" {
  # Quarantine a test
  record_fails "gate_test" 5
  record_passes "gate_test" 5

  run flaky_is_quarantined "gate_test"
  [ "$status" -eq 0 ]

  result=$(flaky_gate_exit_code "gate_test" 1)
  [ "$result" -eq 0 ]
}

@test "flaky_gate_exit_code preserves exit code for non-quarantined failure" {
  record_passes "clean_test" 5

  result=$(flaky_gate_exit_code "clean_test" 1)
  [ "$result" -eq 1 ]
}

@test "flaky_gate_exit_code passes through zero exit code unchanged" {
  result=$(flaky_gate_exit_code "any_test" 0)
  [ "$result" -eq 0 ]
}

@test "flaky_gate_exit_code passes through non-zero for unknown test" {
  result=$(flaky_gate_exit_code "never_seen_test" 2)
  [ "$result" -eq 2 ]
}

# ── Tests: flaky_report ───────────────────────────────────────────────────────

@test "flaky_report prints without error on empty registry" {
  run flaky_report
  [ "$status" -eq 0 ]
  echo "$output" | grep -q "Flaky Test Registry"
}

@test "flaky_report shows quarantined test in output" {
  record_fails "noisy_test" 5
  record_passes "noisy_test" 5

  run flaky_report
  [ "$status" -eq 0 ]
  echo "$output" | grep -q "noisy_test"
}

@test "flaky_report shows failure rate for quarantined tests" {
  record_fails "rate_test" 5
  record_passes "rate_test" 5

  run flaky_report
  [ "$status" -eq 0 ]
  # Should include a percentage
  echo "$output" | grep -q "%"
}

# ── Tests: flaky_list_quarantined ─────────────────────────────────────────────

@test "flaky_list_quarantined outputs empty when no tests quarantined" {
  record_passes "clean1" 10
  run flaky_list_quarantined
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "flaky_list_quarantined outputs quarantined test names" {
  record_fails "noisy1" 5
  record_passes "noisy1" 5
  record_passes "clean1" 10

  run flaky_list_quarantined
  [ "$status" -eq 0 ]
  echo "$output" | grep -q "noisy1"
  ! echo "$output" | grep -q "clean1"
}

# ── Tests: persistence ────────────────────────────────────────────────────────

@test "registry persists across source calls" {
  flaky_record_result "persist_test" "fail"
  flaky_record_result "persist_test" "fail"

  # Re-source to simulate a fresh shell invocation
  source "lib/flaky_tests.sh"

  local failures
  failures=$(reg_get '.persist_test.failures')
  [ "$failures" -eq 2 ]
}
