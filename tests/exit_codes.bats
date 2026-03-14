#!/usr/bin/env bats
# tests/exit_codes.bats — Verify spiral.sh named exit-code constants (US-121)
#
# Run with: bats tests/exit_codes.bats
#
# Two categories of tests:
#   1. Static (grep-based): verify every readonly constant is defined with the
#      correct value — no shell execution required, no external deps.
#   2. Runtime: actually invoke spiral.sh and check $? against the constant
#      values.  Only tests error paths that fire *before* any API call or
#      long-running operation (argument validation, missing deps, etc.).

SPIRAL_SH="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/spiral.sh"

# ── Helpers ────────────────────────────────────────────────────────────────

# Extract the numeric value of a named constant from spiral.sh
constant_value() {
  local name="$1"
  grep -oP "(?<=readonly ${name}=)\d+" "$SPIRAL_SH"
}

# ── Static: constant definitions ──────────────────────────────────────────

@test "ERR_BAD_USAGE is defined as 2" {
  grep -qE 'readonly ERR_BAD_USAGE=2' "$SPIRAL_SH"
}

@test "ERR_CONFIG is defined as 3" {
  grep -qE 'readonly ERR_CONFIG=3' "$SPIRAL_SH"
}

@test "ERR_MISSING_DEP is defined as 4" {
  grep -qE 'readonly ERR_MISSING_DEP=4' "$SPIRAL_SH"
}

@test "ERR_PRD_NOT_FOUND is defined as 5" {
  grep -qE 'readonly ERR_PRD_NOT_FOUND=5' "$SPIRAL_SH"
}

@test "ERR_PRD_CORRUPT is defined as 6" {
  grep -qE 'readonly ERR_PRD_CORRUPT=6' "$SPIRAL_SH"
}

@test "ERR_SCHEMA_VERSION is defined as 7" {
  grep -qE 'readonly ERR_SCHEMA_VERSION=7' "$SPIRAL_SH"
}

@test "ERR_COST_CEILING is defined as 8" {
  grep -qE 'readonly ERR_COST_CEILING=8' "$SPIRAL_SH"
}

@test "ERR_ZERO_PROGRESS is defined as 9" {
  grep -qE 'readonly ERR_ZERO_PROGRESS=9' "$SPIRAL_SH"
}

@test "ERR_REPLAY_FAILED is defined as 10" {
  grep -qE 'readonly ERR_REPLAY_FAILED=10' "$SPIRAL_SH"
}

@test "ERR_STORY_NOT_FOUND is defined as 11" {
  grep -qE 'readonly ERR_STORY_NOT_FOUND=11' "$SPIRAL_SH"
}

@test "at least 8 ERR_ constants are defined" {
  local count
  count=$(grep -cE '^\s*readonly ERR_[A-Z_]+=[0-9]+' "$SPIRAL_SH")
  [ "$count" -ge 8 ]
}

@test "no bare 'exit 1' remains in spiral.sh" {
  # Intentional exit 1 would be a regression — all exits should use named codes.
  # Allow commented lines (reference table, bash comments).
  ! grep -E '^\s*exit 1\b' "$SPIRAL_SH"
}

@test "no bare 'exit 2' remains in spiral.sh" {
  # exit 2 (ERR_BAD_USAGE) must always be referenced via the constant name.
  ! grep -E '^\s*exit 2\b' "$SPIRAL_SH"
}

@test "exit code table comment block is present in spiral.sh" {
  grep -q 'ERR_BAD_USAGE' "$SPIRAL_SH"
  grep -q 'ERR_SCHEMA_VERSION' "$SPIRAL_SH"
}

# ── Runtime: error-path exit codes ────────────────────────────────────────

@test "unknown flag produces ERR_BAD_USAGE (exit 2)" {
  local expected
  expected=$(constant_value ERR_BAD_USAGE)
  run bash "$SPIRAL_SH" --unknown-flag-xyz-test-121
  [ "$status" -eq "$expected" ]
}

@test "non-integer max_iters produces ERR_BAD_USAGE (exit 2)" {
  local expected
  expected=$(constant_value ERR_BAD_USAGE)
  # "notanumber" hits _validate_pos_int before any config/file checks
  run bash "$SPIRAL_SH" notanumber
  [ "$status" -eq "$expected" ]
}

setup() {
  # Create a minimal project directory so we can reach checks that fire
  # after argument parsing and config loading.
  SPIRAL_TEST_DIR="$(mktemp -d)"
  export SPIRAL_TEST_DIR

  # Minimal spiral.config.sh required by validate_config
  cat >"$SPIRAL_TEST_DIR/spiral.config.sh" <<'EOF'
SPIRAL_PYTHON="${SPIRAL_PYTHON:-python3}"
SPIRAL_VALIDATE_CMD="true"
EOF
}

teardown() {
  rm -rf "$SPIRAL_TEST_DIR"
}

@test "--prd pointing to non-existent directory produces ERR_PRD_NOT_FOUND (exit 5)" {
  local expected
  expected=$(constant_value ERR_PRD_NOT_FOUND)
  # /nonexistent/path/prd.json — directory does not exist
  run bash "$SPIRAL_SH" --config "$SPIRAL_TEST_DIR/spiral.config.sh" \
    --prd /nonexistent/path/that/does/not/exist/prd.json
  [ "$status" -eq "$expected" ]
}

@test "prd.json with schemaVersion > 1 produces ERR_SCHEMA_VERSION (exit 7)" {
  local expected
  expected=$(constant_value ERR_SCHEMA_VERSION)
  # Write a prd.json with schemaVersion=99 to the test dir
  printf '{"schemaVersion":99,"userStories":[]}\n' >"$SPIRAL_TEST_DIR/prd.json"
  run bash "$SPIRAL_SH" --config "$SPIRAL_TEST_DIR/spiral.config.sh" \
    --prd "$SPIRAL_TEST_DIR/prd.json"
  [ "$status" -eq "$expected" ]
}
