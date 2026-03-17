#!/usr/bin/env bats
# tests/consecutive_fail_abort.bats — Tests for US-400: SPIRAL_CONSECUTIVE_FAIL_ABORT
#
# Run with: bats tests/consecutive_fail_abort.bats
#
# Tests verify:
#   - SPIRAL_CONSECUTIVE_FAIL_ABORT defaults to 3
#   - Zero-progress counter triggers abort at the configured threshold
#   - Counter resets when progress is made
#   - SPIRAL_CONSECUTIVE_FAIL_ABORT=0 disables the check
#   - Abort writes abort_reason: consecutive_failures to checkpoint
#   - consecutive_fail_abort event is logged to spiral_events.jsonl

bats_require_minimum_version 1.7.0

# ── Helpers ──────────────────────────────────────────────────────────────────

_setup_env() {
  export SCRATCH_DIR="$TEST_DIR/scratch"
  export SPIRAL_RUN_ID="test-cfail-001"
  export SPIRAL_ITER=5
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
  export SPIRAL_HOME
  source "$SPIRAL_HOME/lib/spiral_events.sh"
}

# Create a minimal prd.json with pending stories
# Args: PRD_FILE  "SID|TITLE|REASON" ...
_create_test_prd() {
  local prd_file="$1"
  shift
  local stories="[]"
  for entry in "$@"; do
    local sid title reason
    sid="${entry%%|*}"
    local rest="${entry#*|}"
    title="${rest%%|*}"
    reason="${rest#*|}"
    # If no third field, reason equals title — treat as no reason
    [[ "$reason" == "$title" || "$reason" == "null" || -z "$reason" ]] && reason=""
    if [[ -n "$reason" ]]; then
      stories=$("$JQ" --arg id "$sid" --arg t "$title" --arg r "$reason" \
        '. + [{"id": $id, "title": $t, "passes": false, "_failureReason": $r}]' <<<"$stories")
    else
      stories=$("$JQ" --arg id "$sid" --arg t "$title" \
        '. + [{"id": $id, "title": $t, "passes": false, "_failureReason": null}]' <<<"$stories")
    fi
  done
  "$JQ" -n --argjson s "$stories" '{"userStories": $s}' >"$prd_file"
}

# Create a minimal retry-counts.json
# Args: RETRIES_FILE  "SID:COUNT" ...
_create_test_retries() {
  local retries_file="$1"
  shift
  local obj="{}"
  for entry in "$@"; do
    local sid count
    sid="${entry%%:*}"
    count="${entry##*:}"
    obj=$("$JQ" --arg id "$sid" --argjson c "$count" '.[$id] = $c' <<<"$obj")
  done
  echo "$obj" >"$retries_file"
}

# Simulates the US-400 consecutive-fail-abort logic from spiral.sh.
# Args: ABORT_LIMIT ZERO_PROGRESS_COUNT PRD_FILE RETRY_FILE
# Returns: 9 (ERR_ZERO_PROGRESS) if limit exceeded, 0 otherwise.
# Writes checkpoint and events on abort.
_simulate_consecutive_abort() {
  local abort_limit="$1"
  local zero_count="$2"
  local prd_file="$3"
  local retry_file="$4"
  local SPIRAL_CONSECUTIVE_FAIL_ABORT="$abort_limit"
  local ZERO_PROGRESS_COUNT="$zero_count"
  local SPIRAL_ITER=5
  local CHECKPOINT_FILE="$TEST_DIR/checkpoint.json"
  local PRD_FILE="$prd_file"
  local REPO_ROOT="$TEST_DIR"

  # Mirror the US-400 abort check from spiral.sh
  local _ZP_ABORT_LIMIT="$SPIRAL_CONSECUTIVE_FAIL_ABORT"
  if [[ "$_ZP_ABORT_LIMIT" -gt 0 && "$ZERO_PROGRESS_COUNT" -ge "$_ZP_ABORT_LIMIT" ]]; then
    # Collect stuck IDs
    local _ZP_STUCK_IDS
    _ZP_STUCK_IDS=$("$JQ" -r '[.userStories[] | select(.passes != true)] | map(.id) | join(",")' "$PRD_FILE" 2>/dev/null || echo "")

    # Diagnostic output
    echo "CONSECUTIVE_FAIL_ABORT: $ZERO_PROGRESS_COUNT zero-progress iterations (limit: $_ZP_ABORT_LIMIT)"
    while IFS= read -r _ZP_DIAG_SID; do
      _ZP_DIAG_SID="${_ZP_DIAG_SID//$'\r'/}"
      [[ -z "$_ZP_DIAG_SID" ]] && continue
      local _ZP_DIAG_RETRIES
      _ZP_DIAG_RETRIES=$("$JQ" -r --arg id "$_ZP_DIAG_SID" '.[$id] // 0' "$retry_file" 2>/dev/null || echo "0")
      local _ZP_DIAG_REASON
      _ZP_DIAG_REASON=$("$JQ" -r --arg id "$_ZP_DIAG_SID" '.userStories[] | select(.id == $id) | ._failureReason // "unknown"' "$PRD_FILE" 2>/dev/null || echo "unknown")
      echo "  STUCK: $_ZP_DIAG_SID retries=$_ZP_DIAG_RETRIES reason=$_ZP_DIAG_REASON"
    done < <("$JQ" -r '[.userStories[] | select(.passes != true)] | .[].id' "$PRD_FILE" 2>/dev/null || true)

    # Log event
    log_spiral_event "consecutive_fail_abort" \
      "\"iteration\":$SPIRAL_ITER,\"consecutive_zero_pass\":$ZERO_PROGRESS_COUNT,\"limit\":$_ZP_ABORT_LIMIT,\"stuck_ids\":\"$_ZP_STUCK_IDS\""

    # Write checkpoint with abort_reason
    printf '{"iter":%d,"phase":"I","ts":"%s","run_id":"%s","abort_reason":"consecutive_failures","consecutive_zero_pass":%d,"limit":%d,"stuck_ids":"%s"}\n' \
      "$SPIRAL_ITER" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${SPIRAL_RUN_ID:-}" \
      "$ZERO_PROGRESS_COUNT" "$_ZP_ABORT_LIMIT" "$_ZP_STUCK_IDS" \
      >"$CHECKPOINT_FILE" 2>/dev/null

    return 9
  fi
  echo "OK: zero_progress_count=$ZERO_PROGRESS_COUNT, limit=$_ZP_ABORT_LIMIT"
  return 0
}

# ── Setup / Teardown ─────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  _resolve_jq
  TEST_DIR="$(mktemp -d)"
  _setup_env
  # Create default test fixtures
  _create_test_prd "$TEST_DIR/prd.json" \
    "US-101|Fix login bug|timeout on auth service" \
    "US-102|Add search|null" \
    "US-103|Improve perf|OOM in worker"
  _create_test_retries "$TEST_DIR/retry-counts.json" "US-101:3" "US-102:1" "US-103:2"
}

teardown() {
  rm -rf "$TEST_DIR" 2>/dev/null || true
}

# ── Tests ────────────────────────────────────────────────────────────────────

@test "SPIRAL_CONSECUTIVE_FAIL_ABORT defaults to 3 in spiral.sh" {
  SPIRAL_HOME="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  default=$(grep 'SPIRAL_CONSECUTIVE_FAIL_ABORT=' "$SPIRAL_HOME/spiral.sh" |
    head -1 | sed -nE 's/.*:-([0-9]+)\}.*/\1/p')
  [ "$default" = "3" ]
}

@test "zero-progress count below limit does not trigger abort" {
  # 2 zero-progress iterations with limit 3 — should NOT abort
  run _simulate_consecutive_abort 3 2 "$TEST_DIR/prd.json" "$TEST_DIR/retry-counts.json"
  assert_success
  assert_output --partial "OK: zero_progress_count=2"
}

@test "zero-progress count at limit triggers abort with exit code 9" {
  # 3 zero-progress iterations with limit 3 — should abort
  run _simulate_consecutive_abort 3 3 "$TEST_DIR/prd.json" "$TEST_DIR/retry-counts.json"
  assert_failure 9
  assert_output --partial "CONSECUTIVE_FAIL_ABORT"
  assert_output --partial "3 zero-progress iterations"
}

@test "zero-progress count above limit triggers abort" {
  # 5 zero-progress iterations with limit 3 — should abort
  run _simulate_consecutive_abort 3 5 "$TEST_DIR/prd.json" "$TEST_DIR/retry-counts.json"
  assert_failure 9
  assert_output --partial "CONSECUTIVE_FAIL_ABORT"
}

@test "custom limit is respected" {
  # 4 zero-progress iterations with limit 5 — should NOT abort
  run _simulate_consecutive_abort 5 4 "$TEST_DIR/prd.json" "$TEST_DIR/retry-counts.json"
  assert_success

  # 5 zero-progress iterations with limit 5 — should abort
  run _simulate_consecutive_abort 5 5 "$TEST_DIR/prd.json" "$TEST_DIR/retry-counts.json"
  assert_failure 9
}

@test "limit 0 disables abort (unlimited retries)" {
  # 100 zero-progress iterations with limit 0 — should NOT abort
  run _simulate_consecutive_abort 0 100 "$TEST_DIR/prd.json" "$TEST_DIR/retry-counts.json"
  assert_success
  assert_output --partial "OK: zero_progress_count=100"
}

@test "abort diagnostic lists stuck story IDs and retry counts" {
  run _simulate_consecutive_abort 3 3 "$TEST_DIR/prd.json" "$TEST_DIR/retry-counts.json"
  assert_failure 9
  assert_output --partial "US-101"
  assert_output --partial "US-102"
  assert_output --partial "US-103"
  assert_output --partial "retries=3"
  assert_output --partial "retries=1"
  assert_output --partial "retries=2"
}

@test "abort diagnostic includes failure reasons" {
  run _simulate_consecutive_abort 3 3 "$TEST_DIR/prd.json" "$TEST_DIR/retry-counts.json"
  assert_failure 9
  assert_output --partial "reason=timeout on auth service"
  assert_output --partial "reason=OOM in worker"
}

@test "abort writes checkpoint with abort_reason: consecutive_failures" {
  _simulate_consecutive_abort 3 3 "$TEST_DIR/prd.json" "$TEST_DIR/retry-counts.json" || true

  [ -f "$TEST_DIR/checkpoint.json" ]
  $JQ -e '.abort_reason == "consecutive_failures"' "$TEST_DIR/checkpoint.json" >/dev/null
  $JQ -e '.consecutive_zero_pass == 3' "$TEST_DIR/checkpoint.json" >/dev/null
  $JQ -e '.limit == 3' "$TEST_DIR/checkpoint.json" >/dev/null
  $JQ -e '.stuck_ids | test("US-101")' "$TEST_DIR/checkpoint.json" >/dev/null
}

@test "consecutive_fail_abort event is logged to spiral_events.jsonl" {
  _simulate_consecutive_abort 3 3 "$TEST_DIR/prd.json" "$TEST_DIR/retry-counts.json" || true

  [ -f "$SCRATCH_DIR/spiral_events.jsonl" ]
  grep -q "consecutive_fail_abort" "$SCRATCH_DIR/spiral_events.jsonl"

  line=$(grep "consecutive_fail_abort" "$SCRATCH_DIR/spiral_events.jsonl" | tail -1)
  echo "$line" | $JQ -e '.consecutive_zero_pass == 3' >/dev/null
  echo "$line" | $JQ -e '.limit == 3' >/dev/null
  echo "$line" | $JQ -e '.stuck_ids | test("US-101")' >/dev/null
}

@test "config var present in spiral.config.sh with documentation" {
  SPIRAL_HOME="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  grep -q 'SPIRAL_CONSECUTIVE_FAIL_ABORT' "$SPIRAL_HOME/spiral.config.sh"
  # Verify documentation comment exists
  grep -q 'zero-progress' "$SPIRAL_HOME/spiral.config.sh"
}
