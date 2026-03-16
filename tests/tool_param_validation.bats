#!/usr/bin/env bats
# tests/tool_param_validation.bats — Tool parameter semantic validation (US-249)
#
# Verifies that malformed tool calls are caught at the validation layer
# and that valid calls pass through without errors.

bats_require_minimum_version 1.7.0
setup() {
  load test_helper/common-setup
  _resolve_jq
  # Source the validator library
  source "${BATS_TEST_DIRNAME}/../lib/tool_param_validator.sh"
  # Point SPIRAL_SCRATCH_DIR to a temp dir so schema init doesn't pollute real .spiral/
  export SPIRAL_SCRATCH_DIR="${BATS_TMPDIR}/spiral_$$"
  mkdir -p "$SPIRAL_SCRATCH_DIR"
}

teardown() {
  rm -rf "$SPIRAL_SCRATCH_DIR"
}

# ── git subcommand validation ─────────────────────────────────────────────────

@test "git valid subcommand 'add' passes" {
  run validate_tool_params git add -A
  assert_success
}

@test "git valid subcommand 'commit' passes" {
  run validate_tool_params git commit -m "msg"
  assert_success
}

@test "git valid subcommand 'checkout' passes" {
  run validate_tool_params git checkout main
  assert_success
}

@test "git invalid subcommand is caught and NOT executed" {
  # Key acceptance criterion: malformed call caught, not executed.
  # Use || to prevent set -e from triggering on the expected non-zero return.
  local rc=0
  validate_tool_params git foobar --some-flag || rc=$?
  [ "$rc" -ne 0 ]
  [[ "${_tool_param_last_error}" == *"foobar"* ]]
}

@test "git with only flags (no subcommand) passes" {
  run validate_tool_params git --version
  assert_success
}

# ── python file extension validation ─────────────────────────────────────────

@test "python with .py file passes" {
  run validate_tool_params python main.py
  assert_success
}

@test "python with -m flag passes" {
  run validate_tool_params python -m pytest tests/
  assert_success
}

@test "python with -c flag passes" {
  run validate_tool_params python -c "print('hello')"
  assert_success
}

@test "python with non-.py file extension is caught" {
  run validate_tool_params python script.sh
  assert_failure
}

# ── bats file extension validation ───────────────────────────────────────────

@test "bats with .bats file passes" {
  run validate_tool_params bats tests/my_test.bats
  assert_success
}

@test "bats with directory argument passes (no extension to check)" {
  run validate_tool_params bats tests/
  assert_success
}

@test "bats with wrong extension is caught and NOT executed" {
  # Malformed: wrong file extension — caught at validation layer.
  local rc=0
  validate_tool_params bats tests/my_test.txt || rc=$?
  [ "$rc" -ne 0 ]
  [[ "${_tool_param_last_error}" == *"txt"* ]] || [[ "${_tool_param_last_error}" == *"bats"* ]]
}

# ── jq filter validation ──────────────────────────────────────────────────────

@test "jq with filter passes" {
  run validate_tool_params jq '.foo'
  assert_success
}

@test "jq with --arg and filter passes" {
  run validate_tool_params jq --arg key val '.[$key]'
  assert_success
}

@test "jq without filter is caught" {
  run validate_tool_params jq
  assert_failure
}

@test "jq with only flags and no filter is caught" {
  run validate_tool_params jq -r -c
  assert_failure
}

# ── curl URL scheme validation ────────────────────────────────────────────────

@test "curl with https URL passes" {
  run validate_tool_params curl https://example.com/api
  assert_success
}

@test "curl with http URL passes" {
  run validate_tool_params curl -sf http://localhost:8080/health
  assert_success
}

@test "curl with ftp URL passes" {
  run validate_tool_params curl ftp://files.example.com/data.csv
  assert_success
}

@test "curl with invalid scheme is caught and NOT executed" {
  # ssh:// is not a valid curl scheme — caught at validation layer.
  local rc=0
  validate_tool_params curl ssh://internal-host/path || rc=$?
  [ "$rc" -ne 0 ]
  [[ "${_tool_param_last_error}" == *"ssh"* ]]
}

@test "curl with file:// scheme is caught" {
  run validate_tool_params curl file:///etc/passwd
  assert_failure
}

# ── uv subcommand validation ──────────────────────────────────────────────────

@test "uv run passes" {
  run validate_tool_params uv run pytest
  assert_success
}

@test "uv invalid subcommand is caught" {
  run validate_tool_params uv foobar
  assert_failure
}

# ── unknown tools pass through (no false positives) ──────────────────────────

@test "unknown tool passes through without error" {
  run validate_tool_params make build
  assert_success
}

@test "shell builtin passes through without error" {
  run validate_tool_params echo hello world
  assert_success
}

# ── tool_schema_init creates schema file ──────────────────────────────────────

@test "tool_schema_init creates .spiral/tool-schema.json" {
  local schema_file="${SPIRAL_SCRATCH_DIR}/tool-schema.json"
  [ ! -f "$schema_file" ]  # Ensure it doesn't exist yet
  run tool_schema_init
  assert_success
  [ -f "$schema_file" ]
}

@test "tool_schema_init output is valid JSON" {
  local schema_file
  schema_file=$(tool_schema_init)
  [ -f "$schema_file" ]
  run python3 -c "import json,sys; json.load(sys.stdin)" < "$schema_file"
  assert_success
}
