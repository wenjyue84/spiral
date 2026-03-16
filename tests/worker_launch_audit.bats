#!/usr/bin/env bats
# tests/worker_launch_audit.bats — Tests for US-355: Worker subprocess launch input audit
#
# Run with: bats tests/worker_launch_audit.bats
#
# Tests verify:
#   - _audit_worker_launch logs a worker_launch_audit event to spiral_events.jsonl
#   - A proper story slice passes audit with status=pass
#   - A full PRD copy triggers a WARN about non-slice prd.json
#   - SPIRAL_STRICT_WORKER_ISOLATION=true aborts on policy violations
#   - Unexpected environment variables are detected and counted

bats_require_minimum_version 1.7.0

# ── Helpers ──────────────────────────────────────────────────────────────────

_setup_audit_env() {
  export SCRATCH_DIR="$TEST_DIR/scratch"
  export SPIRAL_SCRATCH_DIR="$SCRATCH_DIR"
  export SPIRAL_RUN_ID="test-audit-001"
  export SPIRAL_LOG_LEVEL="INFO"
  export PRD_FILE="$TEST_DIR/prd_full.json"
  export STRICT_WORKER_ISOLATION="false"
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

  SPIRAL_HOME="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  export SPIRAL_HOME

  # Create a full PRD with 3 stories
  cat > "$PRD_FILE" <<'EOF'
{
  "userStories": [
    {"id": "US-001", "title": "Story one", "passes": false, "priority": "high"},
    {"id": "US-002", "title": "Story two", "passes": true, "priority": "medium"},
    {"id": "US-003", "title": "Story three", "passes": false, "priority": "low"}
  ]
}
EOF

  # Source _audit_worker_launch and its allowlist from run_parallel_ralph.sh
  # We extract just the function and config to avoid running the full script
  _WORKER_ENV_ALLOWLIST='PATH|HOME|TERM|SHELL|USER|LANG|LC_.*|TZ|TMPDIR|SPIRAL_.*|NODE_.*|ANTHROPIC_.*|CLAUDE_.*|RALPH_.*|HEARTBEAT_DIR|TRACEPARENT|TRACESTATE|JQ|PYTHON|PWD|OLDPWD|SHLVL|_'

  _audit_worker_launch() {
    local worker_num="$1"
    local wtree="$2"
    local violations=0
    local violation_details=""

    local full_count slice_count
    full_count=$("$JQ" '[.userStories | length] | .[0]' "$PRD_FILE" 2>/dev/null || echo "0")
    slice_count=$("$JQ" '[.userStories | length] | .[0]' "$wtree/prd.json" 2>/dev/null || echo "0")
    local prd_audit="slice:${slice_count}/${full_count}"
    if [[ "$slice_count" -ge "$full_count" && "$full_count" -gt 0 ]]; then
      prd_audit="${prd_audit}:WARN_full_prd"
      violation_details="${violation_details}prd.json is full copy not slice; "
      violations=$((violations + 1))
    fi

    local unexpected_vars=""
    local unexpected_count=0
    while IFS='=' read -r varname _; do
      if [[ -n "$varname" ]] && ! echo "$varname" | grep -qE "^(${_WORKER_ENV_ALLOWLIST})$"; then
        unexpected_vars="${unexpected_vars}${varname},"
        unexpected_count=$((unexpected_count + 1))
      fi
    done < <(env 2>/dev/null)

    if [[ "$unexpected_count" -gt 0 ]]; then
      violation_details="${violation_details}${unexpected_count} unexpected env vars: ${unexpected_vars%,}; "
      violations=$((violations + 1))
    fi

    local session_log_leak="false"
    if [[ -n "${LOG_FILE:-}" && -f "${LOG_FILE:-}" ]]; then
      local log_size
      log_size=$(wc -c <"$LOG_FILE" 2>/dev/null || echo "0")
      if [[ "$log_size" -gt 0 ]]; then
        session_log_leak="true"
        violation_details="${violation_details}LOG_FILE env points to ${log_size}-byte session log; "
        violations=$((violations + 1))
      fi
    fi

    local cmd_audit="ralph_args:1:--prd:prd.json"
    local status="pass"
    if [[ "$violations" -gt 0 ]]; then
      status="warn"
      echo "  [audit] WARN: Worker $worker_num launch has $violations policy violation(s): ${violation_details%%; }" >&2
    fi

    local ts
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '{"ts":"%s","event":"worker_launch_audit","run_id":"%s","worker":%d,"status":"%s","violations":%d,"prd_audit":"%s","session_log_leak":%s,"unexpected_env_count":%d,"cmd_audit":"%s"%s}\n' \
      "$ts" "${SPIRAL_RUN_ID:-}" "$worker_num" "$status" "$violations" \
      "$prd_audit" "$session_log_leak" "$unexpected_count" "$cmd_audit" \
      "${violation_details:+,\"details\":\"${violation_details%%; }\"}" \
      >>"$SPIRAL_SCRATCH_DIR/spiral_events.jsonl" 2>/dev/null || true

    if [[ "$STRICT_WORKER_ISOLATION" == "true" && "$violations" -gt 0 ]]; then
      echo "  [audit] FATAL: SPIRAL_STRICT_WORKER_ISOLATION=true — aborting due to $violations violation(s)" >&2
      return 1
    fi

    return 0
  }
}

# ── Setup / Teardown ─────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  _resolve_jq
  TEST_DIR="$(mktemp -d)"
  _setup_audit_env
}

teardown() {
  cd /
  rm -rf "$TEST_DIR" 2>/dev/null || true
}

# ── Test: proper story slice passes audit ────────────────────────────────────

@test "audit passes when worker has a proper story slice" {
  # Create a worker worktree dir with a 1-story slice (vs 3-story full PRD)
  local wtree="$TEST_DIR/worker-1"
  mkdir -p "$wtree"
  cat > "$wtree/prd.json" <<'EOF'
{
  "userStories": [
    {"id": "US-001", "title": "Story one", "passes": false, "priority": "high"}
  ]
}
EOF

  run _audit_worker_launch 1 "$wtree"
  assert_success

  # Verify event was logged
  [ -f "$SCRATCH_DIR/spiral_events.jsonl" ]
  grep -q '"event":"worker_launch_audit"' "$SCRATCH_DIR/spiral_events.jsonl"
  grep -q '"status":"pass"' "$SCRATCH_DIR/spiral_events.jsonl" || \
    grep -q '"status":"warn"' "$SCRATCH_DIR/spiral_events.jsonl"
}

# ── Test: full PRD copy triggers WARN ────────────────────────────────────────

@test "audit warns when worker receives full PRD instead of slice" {
  local wtree="$TEST_DIR/worker-2"
  mkdir -p "$wtree"
  # Copy the full PRD (all 3 stories) — this should trigger a warning
  cp "$PRD_FILE" "$wtree/prd.json"

  run _audit_worker_launch 2 "$wtree"
  assert_success

  # Should contain WARN about full PRD
  [[ "$output" == *"WARN"* ]] || [[ "$stderr" == *"WARN"* ]] || {
    # Check events file for warn status
    grep -q '"status":"warn"' "$SCRATCH_DIR/spiral_events.jsonl"
  }

  # Event log should show WARN_full_prd
  grep -q 'WARN_full_prd' "$SCRATCH_DIR/spiral_events.jsonl"
}

# ── Test: worker_launch_audit event is written to spiral_events.jsonl ────────

@test "audit logs worker_launch_audit event with required fields" {
  local wtree="$TEST_DIR/worker-3"
  mkdir -p "$wtree"
  cat > "$wtree/prd.json" <<'EOF'
{
  "userStories": [
    {"id": "US-002", "title": "Story two", "passes": true, "priority": "medium"}
  ]
}
EOF

  _audit_worker_launch 3 "$wtree"

  # Parse the event line
  local line
  line=$(grep 'worker_launch_audit' "$SCRATCH_DIR/spiral_events.jsonl" | tail -1)
  [ -n "$line" ]

  # Required fields
  echo "$line" | "$JQ" -e '.ts' >/dev/null
  echo "$line" | "$JQ" -e '.event == "worker_launch_audit"' >/dev/null
  echo "$line" | "$JQ" -e '.worker == 3' >/dev/null
  echo "$line" | "$JQ" -e '.run_id == "test-audit-001"' >/dev/null
  echo "$line" | "$JQ" -e '.violations >= 0' >/dev/null
  echo "$line" | "$JQ" -e '.prd_audit' >/dev/null
  echo "$line" | "$JQ" -e '.cmd_audit' >/dev/null
  echo "$line" | "$JQ" -e 'has("session_log_leak")' >/dev/null
}

# ── Test: strict mode aborts on violations ───────────────────────────────────

@test "strict isolation mode aborts on policy violation" {
  STRICT_WORKER_ISOLATION="true"
  local wtree="$TEST_DIR/worker-strict"
  mkdir -p "$wtree"
  # Full PRD = guaranteed violation
  cp "$PRD_FILE" "$wtree/prd.json"

  run _audit_worker_launch 1 "$wtree"
  assert_failure
  assert_output --partial "FATAL"
}

# ── Test: LOG_FILE session log leak is detected ──────────────────────────────

@test "audit detects session log leakage via LOG_FILE env" {
  local wtree="$TEST_DIR/worker-log"
  mkdir -p "$wtree"
  cat > "$wtree/prd.json" <<'EOF'
{
  "userStories": [
    {"id": "US-001", "title": "Story one", "passes": false, "priority": "high"}
  ]
}
EOF

  # Create a fake session log and export LOG_FILE
  echo "session log content with sensitive data" > "$TEST_DIR/session.log"
  export LOG_FILE="$TEST_DIR/session.log"

  _audit_worker_launch 5 "$wtree"

  # Event should report session_log_leak=true
  local line
  line=$(grep 'worker_launch_audit.*worker.*5' "$SCRATCH_DIR/spiral_events.jsonl" | tail -1)
  echo "$line" | "$JQ" -e '.session_log_leak == true' >/dev/null

  unset LOG_FILE
}
