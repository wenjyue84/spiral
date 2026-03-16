#!/usr/bin/env bats
# tests/tool_param_validation.bats — Tool parameter semantic validation (US-249)
#
# Verifies that malformed tool calls are caught at the validation layer
# and that valid calls pass through without errors.

setup() {
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
  [ "$status" -eq 0 ]
}

@test "git valid subcommand 'commit' passes" {
  run validate_tool_params git commit -m "msg"
  [ "$status" -eq 0 ]
}

@test "git valid subcommand 'checkout' passes" {
  run validate_tool_params git checkout main
  [ "$status" -eq 0 ]
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
  [ "$status" -eq 0 ]
}

# ── python file extension validation ─────────────────────────────────────────

@test "python with .py file passes" {
  run validate_tool_params python main.py
  [ "$status" -eq 0 ]
}

@test "python with -m flag passes" {
  run validate_tool_params python -m pytest tests/
  [ "$status" -eq 0 ]
}

@test "python with -c flag passes" {
  run validate_tool_params python -c "print('hello')"
  [ "$status" -eq 0 ]
}

@test "python with non-.py file extension is caught" {
  run validate_tool_params python script.sh
  [ "$status" -ne 0 ]
}

# ── bats file extension validation ───────────────────────────────────────────

@test "bats with .bats file passes" {
  run validate_tool_params bats tests/my_test.bats
  [ "$status" -eq 0 ]
}

@test "bats with directory argument passes (no extension to check)" {
  run validate_tool_params bats tests/
  [ "$status" -eq 0 ]
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
  [ "$status" -eq 0 ]
}

@test "jq with --arg and filter passes" {
  run validate_tool_params jq --arg key val '.[$key]'
  [ "$status" -eq 0 ]
}

@test "jq without filter is caught" {
  run validate_tool_params jq
  [ "$status" -ne 0 ]
}

@test "jq with only flags and no filter is caught" {
  run validate_tool_params jq -r -c
  [ "$status" -ne 0 ]
}

# ── curl URL scheme validation ────────────────────────────────────────────────

@test "curl with https URL passes" {
  run validate_tool_params curl https://example.com/api
  [ "$status" -eq 0 ]
}

@test "curl with http URL passes" {
  run validate_tool_params curl -sf http://localhost:8080/health
  [ "$status" -eq 0 ]
}

@test "curl with ftp URL passes" {
  run validate_tool_params curl ftp://files.example.com/data.csv
  [ "$status" -eq 0 ]
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
  [ "$status" -ne 0 ]
}

# ── uv subcommand validation ──────────────────────────────────────────────────

@test "uv run passes" {
  run validate_tool_params uv run pytest
  [ "$status" -eq 0 ]
}

@test "uv invalid subcommand is caught" {
  run validate_tool_params uv foobar
  [ "$status" -ne 0 ]
}

# ── unknown tools pass through (no false positives) ──────────────────────────

@test "unknown tool passes through without error" {
  run validate_tool_params make build
  [ "$status" -eq 0 ]
}

@test "shell builtin passes through without error" {
  run validate_tool_params echo hello world
  [ "$status" -eq 0 ]
}

# ── tool_schema_init creates schema file ──────────────────────────────────────

@test "tool_schema_init creates .spiral/tool-schema.json" {
  local schema_file="${SPIRAL_SCRATCH_DIR}/tool-schema.json"
  [ ! -f "$schema_file" ]  # Ensure it doesn't exist yet
  run tool_schema_init
  [ "$status" -eq 0 ]
  [ -f "$schema_file" ]
}

@test "tool_schema_init output is valid JSON" {
  local schema_file
  schema_file=$(tool_schema_init)
  [ -f "$schema_file" ]
  run python3 -c "import json,sys; json.load(sys.stdin)" < "$schema_file"
  [ "$status" -eq 0 ]
}
