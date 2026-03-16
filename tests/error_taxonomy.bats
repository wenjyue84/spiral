#!/usr/bin/env bats
# tests/error_taxonomy.bats — Verify structured error taxonomy (US-273)
#
# Run with: bats tests/error_taxonomy.bats
#
# Tests verify that the 5 most common error codes:
#   1. Exit with the correct exit code from the catalog
#   2. Print the [SPIRAL-E-<code>] message format to stderr
#   3. Include a "Fix:" remediation line
#   4. Include a "Docs:" documentation URL line
#   5. Log structured JSON to spiral_events.jsonl
#
# Approach: source the error constants + catalog directly, then invoke
# spiral_exit in subshells. This avoids the complexity of running full
# spiral.sh for each test while thoroughly validating the taxonomy.

SPIRAL_SH="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/spiral.sh"
SPIRAL_HOME="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"

# ── Helpers ────────────────────────────────────────────────────────────────

# Assert output contains the standard SPIRAL error message format:
#   [SPIRAL-E-<code>] <message>
#   Fix: <remediation>
#   Docs: <url>
assert_error_format() {
  local code="$1"
  local output="$2"
  echo "$output" | grep -q "\[SPIRAL-E-${code}\]" || {
    echo "FAIL: missing [SPIRAL-E-${code}] prefix in output" >&2
    echo "Output was: $output" >&2
    return 1
  }
  echo "$output" | grep -q "^Fix:" || {
    echo "FAIL: missing 'Fix:' remediation line in output" >&2
    return 1
  }
  echo "$output" | grep -q "^Docs:" || {
    echo "FAIL: missing 'Docs:' documentation line in output" >&2
    return 1
  }
}

# ── Test setup ─────────────────────────────────────────────────────────────

setup() {
  TEST_DIR="$(mktemp -d)"
  export SCRATCH_DIR="$TEST_DIR/.spiral"
  mkdir -p "$SCRATCH_DIR"
}

teardown() {
  rm -rf "$TEST_DIR"
}

# Helper: source the error catalog in a subshell and call spiral_exit.
# Captures combined stdout+stderr and the exit code.
# Usage: run_spiral_exit ERROR_CODE [DETAILS]
run_spiral_exit() {
  local code="$1"
  local details="${2:-}"
  run bash -c "
    # Define exit code constants (same as spiral.sh lines 58-71)
    readonly ERR_BAD_USAGE=2
    readonly ERR_CONFIG=3
    readonly ERR_MISSING_DEP=4
    readonly ERR_PRD_NOT_FOUND=5
    readonly ERR_PRD_CORRUPT=6
    readonly ERR_SCHEMA_VERSION=7
    readonly ERR_COST_CEILING=8
    readonly ERR_ZERO_PROGRESS=9
    readonly ERR_REPLAY_FAILED=10
    readonly ERR_STORY_NOT_FOUND=11
    readonly ERR_ROLLBACK_FAILED=12
    readonly ERR_MAX_ITERS=13
    readonly ERR_API_DOWN=14
    readonly ERR_CASCADE_ABORT=15

    export SCRATCH_DIR=\"$SCRATCH_DIR\"
    export SPIRAL_RUN_ID=\"test-run\"

    # jq resolution
    if command -v jq &>/dev/null; then
      JQ=jq
    elif [[ -f \"$SPIRAL_HOME/ralph/jq.exe\" ]]; then
      JQ=\"$SPIRAL_HOME/ralph/jq.exe\"
    else
      JQ=jq
    fi

    source \"$SPIRAL_HOME/lib/spiral_errors.sh\"
    spiral_exit \"$code\" \"$details\"
  " 2>&1
}

# ── Test: E501 — prd.json not found (Schema category) ─────────────────────

@test "E501: spiral_exit produces correct exit code and [SPIRAL-E-E501] format" {
  run_spiral_exit E501 "/path/to/missing/prd.json"
  [ "$status" -eq 5 ]
  assert_error_format "E501" "$output"
  echo "$output" | grep -q "/path/to/missing/prd.json"
}

# ── Test: E503 — prd.json schema version too new (Schema category) ────────

@test "E503: spiral_exit produces correct exit code and [SPIRAL-E-E503] format" {
  run_spiral_exit E503 "99"
  [ "$status" -eq 7 ]
  assert_error_format "E503" "$output"
  echo "$output" | grep -q "99"
}

# ── Test: E103 — Required tool not found (Config category) ────────────────

@test "E103: spiral_exit produces correct exit code and [SPIRAL-E-E103] format" {
  run_spiral_exit E103 "ralph.sh not found at /nonexistent/ralph.sh"
  [ "$status" -eq 4 ]
  assert_error_format "E103" "$output"
  echo "$output" | grep -q "ralph.sh"
}

# ── Test: E401 — Zero-progress stall (Worker category) ────────────────────

@test "E401: spiral_exit produces correct exit code and [SPIRAL-E-E401] format" {
  run_spiral_exit E401
  [ "$status" -eq 9 ]
  assert_error_format "E401" "$output"
  echo "$output" | grep -q "Zero-progress"
}

# ── Test: E201 — API unreachable (API category) ───────────────────────────

@test "E201: spiral_exit produces correct exit code and [SPIRAL-E-E201] format" {
  run_spiral_exit E201 "connection timeout"
  [ "$status" -eq 14 ]
  assert_error_format "E201" "$output"
  echo "$output" | grep -q "connection timeout"
}

# ── Test: spiral_exit writes structured JSON to spiral_events.jsonl ───────

@test "spiral_exit writes structured JSON event with required fields" {
  run_spiral_exit E501 "/test/prd.json"
  local events_file="$SCRATCH_DIR/spiral_events.jsonl"
  [ -f "$events_file" ]
  local last_line
  last_line=$(tail -1 "$events_file")
  # Verify required JSON fields
  echo "$last_line" | jq -e '.event == "spiral_error"'
  echo "$last_line" | jq -e '.error_code == "E501"'
  echo "$last_line" | jq -e '.category == "Schema"'
  echo "$last_line" | jq -e '.exit_code == 5'
  echo "$last_line" | jq -e '.ts != null'
  echo "$last_line" | jq -e '.message != null'
  echo "$last_line" | jq -e '.remediation != null'
}

# ── Test: spiral_exit writes _last_error.json for status display ──────────

@test "spiral_exit writes _last_error.json with error code and category" {
  run_spiral_exit E103 "git-cliff"
  local last_error_file="$SCRATCH_DIR/_last_error.json"
  [ -f "$last_error_file" ]
  jq -e '.error_code == "E103"' "$last_error_file"
  jq -e '.category == "Config"' "$last_error_file"
  jq -e '.exit_code == 4' "$last_error_file"
}

# ── Test: all 5 categories are represented in the catalog ─────────────────

@test "error catalog covers all 5 categories: Config, API, Git, Worker, Schema" {
  local categories
  categories=$(grep -oP "SPIRAL_ERROR_CAT\[\w+\]=\"\K[^\"]+\"" \
    "$SPIRAL_HOME/lib/spiral_errors.sh" | tr -d '"' | sort -u)
  echo "$categories" | grep -q "Config"
  echo "$categories" | grep -q "API"
  echo "$categories" | grep -q "Git"
  echo "$categories" | grep -q "Worker"
  echo "$categories" | grep -q "Schema"
}

# ── Test: Python error_catalog.py has entries for all bash catalog codes ──

@test "Python error_catalog.py has entries for all bash catalog codes" {
  # Extract all error codes from spiral_errors.sh (only literal E+3digits, skip $var refs)
  local bash_codes
  bash_codes=$(grep -oP 'SPIRAL_ERROR_EXIT\[\KE[0-9]{3}(?=\])' \
    "$SPIRAL_HOME/lib/spiral_errors.sh" | sort -u)
  # Extract all error codes from error_catalog.py
  local py_codes
  py_codes=$(grep -oP '^\s+"(E[0-9]{3})":' \
    "$SPIRAL_HOME/lib/error_catalog.py" | grep -oP 'E[0-9]{3}' | sort -u)
  # Every bash code must exist in Python catalog
  for code in $bash_codes; do
    echo "$py_codes" | grep -q "^${code}$" || {
      echo "FAIL: $code exists in spiral_errors.sh but not in error_catalog.py" >&2
      return 1
    }
  done
}

# ── Test: E501 fires via real spiral.sh when prd.json missing ─────────────

@test "E501: real spiral.sh exits 5 and prints [SPIRAL-E-E501] when prd.json not found" {
  # Create test prd path where directory exists but file doesn't
  mkdir -p "$TEST_DIR/project"
  cat >"$TEST_DIR/spiral.config.sh" <<'CONF'
SPIRAL_PYTHON="${SPIRAL_PYTHON:-python3}"
SPIRAL_VALIDATE_CMD="true"
CONF
  run bash "$SPIRAL_SH" \
    --config "$TEST_DIR/spiral.config.sh" \
    --prd "$TEST_DIR/project/prd.json" 2>&1
  [ "$status" -eq 5 ]
  echo "$output" | grep -q "\[SPIRAL-E-E501\]"
}

# ── Test: E503 fires via real spiral.sh when schema version too new ───────

@test "E503: real spiral.sh exits 7 and prints [SPIRAL-E-E503] when schemaVersion=99" {
  mkdir -p "$TEST_DIR/project"
  printf '{"schemaVersion":99,"userStories":[]}\n' >"$TEST_DIR/project/prd.json"
  cat >"$TEST_DIR/spiral.config.sh" <<'CONF'
SPIRAL_PYTHON="${SPIRAL_PYTHON:-python3}"
SPIRAL_VALIDATE_CMD="true"
CONF
  run bash "$SPIRAL_SH" \
    --config "$TEST_DIR/spiral.config.sh" \
    --prd "$TEST_DIR/project/prd.json" 2>&1
  [ "$status" -eq 7 ]
  echo "$output" | grep -q "\[SPIRAL-E-E503\]"
}
