#!/usr/bin/env bats
# tests/diff_size_guard.bats — Unit tests for the _parse_diff_lines helper
# and the check_diff_size gate in ralph/ralph.sh
#
# Run with: bats tests/diff_size_guard.bats
#
# Tests verify:
#   - Correct extraction of insertions+deletions from git diff --stat summary lines
#   - Edge cases: insertions only, deletions only, zero changes, garbage input
#   - check_diff_size guard behaviour when disabled (SPIRAL_MAX_DIFF_LINES=0)

bats_require_minimum_version 1.7.0

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  _resolve_jq
  # Provide a minimal environment so ralph.sh can be sourced up to the
  # function definitions without executing the main loop.
  export SPIRAL_SCRATCH_DIR="$(mktemp -d)"
  export SPIRAL_MAX_DIFF_LINES=500
  export PRD_FILE="/dev/null"   # won't be read — just needs to be set
  export PROGRESS_FILE="/dev/null"

  # Source only the relevant functions from ralph.sh by extracting and evaling
  # them. We use a grep/sed approach so we don't execute the main loop.
  source <(sed -n '/^_parse_diff_lines()/,/^}/p' ralph/ralph.sh)
  source <(sed -n '/^check_diff_size()/,/^}/p' ralph/ralph.sh)
}

teardown() {
  rm -rf "$SPIRAL_SCRATCH_DIR"
}

# ── _parse_diff_lines tests ───────────────────────────────────────────────────

@test "_parse_diff_lines: typical insertions and deletions" {
  run _parse_diff_lines "3 files changed, 450 insertions(+), 120 deletions(-)"
  assert_success
  [ "$output" -eq 570 ]
}

@test "_parse_diff_lines: insertions only" {
  run _parse_diff_lines "1 file changed, 25 insertions(+)"
  assert_success
  [ "$output" -eq 25 ]
}

@test "_parse_diff_lines: deletions only" {
  run _parse_diff_lines "2 files changed, 80 deletions(-)"
  assert_success
  [ "$output" -eq 80 ]
}

@test "_parse_diff_lines: single file single line" {
  run _parse_diff_lines "1 file changed, 1 insertion(+), 1 deletion(-)"
  assert_success
  [ "$output" -eq 2 ]
}

@test "_parse_diff_lines: large diff (>500)" {
  run _parse_diff_lines "10 files changed, 800 insertions(+), 300 deletions(-)"
  assert_success
  [ "$output" -eq 1100 ]
}

@test "_parse_diff_lines: empty string returns 0" {
  run _parse_diff_lines ""
  assert_success
  [ "$output" -eq 0 ]
}

@test "_parse_diff_lines: unrecognised input returns 0" {
  run _parse_diff_lines "nothing to commit, working tree clean"
  assert_success
  [ "$output" -eq 0 ]
}

# ── check_diff_size behaviour when disabled ───────────────────────────────────

@test "check_diff_size returns 0 (ok) when SPIRAL_MAX_DIFF_LINES=0" {
  export SPIRAL_MAX_DIFF_LINES=0
  # Even if there would be a large diff, guard is disabled
  run check_diff_size
  assert_success
}
