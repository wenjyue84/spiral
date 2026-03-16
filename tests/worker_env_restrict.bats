#!/usr/bin/env bats
# tests/worker_env_restrict.bats — Tests for US-359: Worker env allowlist restriction
#
# Run with: bats tests/worker_env_restrict.bats
#
# Tests verify:
#   - _restrict_worker_env unsets non-allowlisted env vars
#   - GITHUB_TOKEN is not accessible to a worker subprocess unless allowlisted
#   - Allowlisted vars (ANTHROPIC_API_KEY, PATH, HOME) survive restriction
#   - worker_env_audit event is logged with passed/removed key names
#   - Custom SPIRAL_WORKER_ENV_ALLOWLIST extends the default allowlist
#   - Wildcard prefix matching works (SPIRAL_* matches SPIRAL_WORKER_ID)

# ── Helpers ──────────────────────────────────────────────────────────────────

_setup_restrict_env() {
  export SCRATCH_DIR="$TEST_DIR/scratch"
  export SPIRAL_SCRATCH_DIR="$SCRATCH_DIR"
  export SPIRAL_RUN_ID="test-restrict-001"
  mkdir -p "$SCRATCH_DIR"

  # Default allowlist (matches run_parallel_ralph.sh)
  _WORKER_ENV_ALLOWLIST_CFG="${SPIRAL_WORKER_ENV_ALLOWLIST:-ANTHROPIC_API_KEY,PATH,HOME,TMPDIR,TERM,SHELL,USER,LANG,TZ,SPIRAL_*,NODE_*,CLAUDE_*,RALPH_*,HEARTBEAT_DIR,TRACEPARENT,TRACESTATE,JQ,PYTHON,PWD,SHLVL}"
  _WORKER_ENV_ALLOWLIST_RE=$(echo "$_WORKER_ENV_ALLOWLIST_CFG" | sed 's/\*/.\*/g; s/,/|/g')

  # Define _restrict_worker_env (extracted from run_parallel_ralph.sh)
  _restrict_worker_env() {
    local worker_num="$1"
    local _passed=""
    local _removed=""
    local _passed_count=0
    local _removed_count=0

    while IFS='=' read -r _vname _; do
      if [[ -z "$_vname" ]]; then
        continue
      fi
      if echo "$_vname" | grep -qE "^(${_WORKER_ENV_ALLOWLIST_RE})$"; then
        _passed="${_passed}${_vname},"
        _passed_count=$((_passed_count + 1))
      else
        _removed="${_removed}${_vname},"
        _removed_count=$((_removed_count + 1))
        unset "$_vname" 2>/dev/null || true
      fi
    done < <(env 2>/dev/null)

    local _ts
    _ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '{"ts":"%s","event":"worker_env_audit","run_id":"%s","worker":%d,"passed_count":%d,"removed_count":%d,"passed_keys":"%s","removed_keys":"%s"}\n' \
      "$_ts" "${SPIRAL_RUN_ID:-}" "$worker_num" \
      "$_passed_count" "$_removed_count" \
      "${_passed%,}" "${_removed%,}" \
      >>"$SPIRAL_SCRATCH_DIR/spiral_events.jsonl" 2>/dev/null || true
  }
}

# ── Setup / Teardown ─────────────────────────────────────────────────────────

setup() {
  TEST_DIR="$(mktemp -d)"
  _setup_restrict_env
}

teardown() {
  cd /
  rm -rf "$TEST_DIR" 2>/dev/null || true
}

# ── Test: GITHUB_TOKEN is removed by default allowlist ───────────────────────

@test "worker subprocess cannot access GITHUB_TOKEN unless allowlisted" {
  export GITHUB_TOKEN="ghp_test_secret_12345"
  [ -n "$GITHUB_TOKEN" ]

  # Run restriction in a subshell (simulating worker env)
  (
    _restrict_worker_env 1
    # After restriction, GITHUB_TOKEN should be gone
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
      echo "FAIL: GITHUB_TOKEN still set after restriction: $GITHUB_TOKEN"
      exit 1
    fi
    exit 0
  )
  [ $? -eq 0 ]
}

# ── Test: allowlisted vars survive restriction ───────────────────────────────

@test "allowlisted vars (ANTHROPIC_API_KEY, PATH, HOME) survive restriction" {
  export ANTHROPIC_API_KEY="sk-ant-test-key"
  local orig_path="$PATH"
  local orig_home="$HOME"

  (
    _restrict_worker_env 2
    [ -n "$ANTHROPIC_API_KEY" ]
    [ "$ANTHROPIC_API_KEY" = "sk-ant-test-key" ]
    [ -n "$PATH" ]
    [ -n "$HOME" ]
    exit 0
  )
  [ $? -eq 0 ]
}

# ── Test: SPIRAL_* wildcard matching preserves SPIRAL_ prefixed vars ─────────

@test "SPIRAL_* wildcard matches SPIRAL_WORKER_ID and SPIRAL_SCRATCH_DIR" {
  export SPIRAL_WORKER_ID=42
  export SPIRAL_SCRATCH_DIR="$SCRATCH_DIR"

  (
    _restrict_worker_env 3
    [ "${SPIRAL_WORKER_ID:-}" = "42" ]
    [ -n "${SPIRAL_SCRATCH_DIR:-}" ]
    exit 0
  )
  [ $? -eq 0 ]
}

# ── Test: worker_env_audit event is logged with key names ────────────────────

@test "worker_env_audit event logged with passed and removed key names" {
  export GITHUB_TOKEN="ghp_secret"
  export FIRECRAWL_API_KEY="fc_secret"

  (
    _restrict_worker_env 4
  )

  # Event should exist
  [ -f "$SCRATCH_DIR/spiral_events.jsonl" ]
  local line
  line=$(grep 'worker_env_audit' "$SCRATCH_DIR/spiral_events.jsonl" | tail -1)
  [ -n "$line" ]

  # Verify key fields exist
  echo "$line" | grep -q '"event":"worker_env_audit"'
  echo "$line" | grep -q '"worker":4'
  echo "$line" | grep -q '"run_id":"test-restrict-001"'
  echo "$line" | grep -q '"passed_count":'
  echo "$line" | grep -q '"removed_count":'

  # GITHUB_TOKEN and FIRECRAWL_API_KEY should appear in removed_keys
  echo "$line" | grep -q 'GITHUB_TOKEN'
  echo "$line" | grep -q 'FIRECRAWL_API_KEY'
}

# ── Test: custom allowlist adds GITHUB_TOKEN ─────────────────────────────────

@test "custom SPIRAL_WORKER_ENV_ALLOWLIST includes GITHUB_TOKEN when configured" {
  export GITHUB_TOKEN="ghp_test_custom"
  # Override allowlist to include GITHUB_TOKEN
  _WORKER_ENV_ALLOWLIST_CFG="ANTHROPIC_API_KEY,PATH,HOME,TMPDIR,TERM,GITHUB_TOKEN,SPIRAL_*"
  _WORKER_ENV_ALLOWLIST_RE=$(echo "$_WORKER_ENV_ALLOWLIST_CFG" | sed 's/\*/.\*/g; s/,/|/g')

  (
    _restrict_worker_env 5
    [ "${GITHUB_TOKEN:-}" = "ghp_test_custom" ]
    exit 0
  )
  [ $? -eq 0 ]
}

# ── Test: multiple non-allowed secrets are all removed ───────────────────────

@test "multiple secrets (GITHUB_TOKEN, FIRECRAWL_API_KEY, AWS_SECRET_ACCESS_KEY) all removed" {
  export GITHUB_TOKEN="ghp_secret"
  export FIRECRAWL_API_KEY="fc_secret"
  export AWS_SECRET_ACCESS_KEY="aws_secret"

  (
    _restrict_worker_env 6
    [ -z "${GITHUB_TOKEN:-}" ]
    [ -z "${FIRECRAWL_API_KEY:-}" ]
    [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]
    exit 0
  )
  [ $? -eq 0 ]
}
