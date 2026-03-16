#!/usr/bin/env bash
# tests/test_helper/common-setup.bash — Shared setup for all SPIRAL bats tests
#
# Loads bats-support and bats-assert from the sibling submodule directories.
# Source this in your setup() or at the top of each .bats file:
#   load test_helper/common-setup
#
# Provides:
#   - bats-support (output formatting helpers)
#   - bats-assert  (assert_success, assert_failure, assert_output, assert_line, etc.)
#   - _resolve_jq  (common JQ resolution helper)

_COMMON_SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_TESTS_DIR="$(cd "$_COMMON_SETUP_DIR/.." && pwd)"

# Load bats-support first (required by bats-assert)
load "${_TESTS_DIR}/bats-support/load.bash"

# Load bats-assert
load "${_TESTS_DIR}/bats-assert/load.bash"

# Common helper: resolve jq path
_resolve_jq() {
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi
}
