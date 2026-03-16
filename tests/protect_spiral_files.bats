#!/usr/bin/env bats
# tests/protect_spiral_files.bats — Tests for US-378: PreToolUse hook blocks
#                                    ralph workers from modifying protected files
#
# Run with: bats tests/protect_spiral_files.bats
#
# Tests verify:
#   - Protected exact-match files are blocked (exit 2)
#   - Protected prefix (.spiral/) paths are blocked (exit 2)
#   - Non-protected paths are allowed (exit 0)
#   - Empty/missing file_path is allowed (exit 0)
#   - Windows backslash paths are normalized and checked

bats_require_minimum_version 1.7.0

# ── Setup ───────────────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  HOOK_SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/.claude/hooks/protect-spiral-files.sh"
}

# ── Helper ──────────────────────────────────────────────────────────────────

_run_hook() {
  local file_path="$1"
  local input="{\"tool_input\":{\"file_path\":\"$file_path\"}}"
  run bash "$HOOK_SCRIPT" <<< "$input"
}

# ── Tests: Protected files (should block with exit 2) ───────────────────────

@test "protect-spiral-files: blocks spiral.sh" {
  _run_hook "spiral.sh"
  assert_failure 2
  assert_output --partial "BLOCKED"
  assert_output --partial "spiral.sh"
}

@test "protect-spiral-files: blocks spiral.config.sh" {
  _run_hook "spiral.config.sh"
  assert_failure 2
  assert_output --partial "BLOCKED"
}

@test "protect-spiral-files: blocks prd.json" {
  _run_hook "prd.json"
  assert_failure 2
  assert_output --partial "BLOCKED"
  assert_output --partial "prd.json"
}

@test "protect-spiral-files: blocks prd.schema.json" {
  _run_hook "prd.schema.json"
  assert_failure 2
  assert_output --partial "BLOCKED"
}

@test "protect-spiral-files: blocks ralph/ralph.sh" {
  _run_hook "ralph/ralph.sh"
  assert_failure 2
  assert_output --partial "BLOCKED"
  assert_output --partial "ralph/ralph.sh"
}

@test "protect-spiral-files: blocks .spiral/ directory paths" {
  _run_hook ".spiral/_checkpoint.json"
  assert_failure 2
  assert_output --partial "BLOCKED"
  assert_output --partial ".spiral/"
}

@test "protect-spiral-files: blocks nested .spiral/ paths" {
  _run_hook ".spiral/worktree_audit.log"
  assert_failure 2
  assert_output --partial "BLOCKED"
}

# ── Tests: Non-protected files (should allow with exit 0) ───────────────────

@test "protect-spiral-files: allows lib/merge_stories.py" {
  _run_hook "lib/merge_stories.py"
  assert_success
  refute_output --partial "BLOCKED"
}

@test "protect-spiral-files: allows tests/test_merge.py" {
  _run_hook "tests/test_merge.py"
  assert_success
}

@test "protect-spiral-files: allows ralph/CLAUDE.md (not ralph.sh)" {
  _run_hook "ralph/CLAUDE.md"
  assert_success
}

@test "protect-spiral-files: allows src/main.py" {
  _run_hook "src/main.py"
  assert_success
}

@test "protect-spiral-files: allows progress.txt" {
  _run_hook "progress.txt"
  assert_success
}

# ── Tests: Edge cases ───────────────────────────────────────────────────────

@test "protect-spiral-files: empty file_path allows" {
  run bash "$HOOK_SCRIPT" <<< '{"tool_input":{"file_path":""}}'
  assert_success
}

@test "protect-spiral-files: missing file_path allows" {
  run bash "$HOOK_SCRIPT" <<< '{"tool_input":{}}'
  assert_success
}

@test "protect-spiral-files: strips leading ./ before matching" {
  _run_hook "./prd.json"
  assert_failure 2
  assert_output --partial "BLOCKED"
}

@test "protect-spiral-files: normalizes backslashes for Windows paths" {
  local input='{"tool_input":{"file_path":".spiral\\_checkpoint.json"}}'
  run bash "$HOOK_SCRIPT" <<< "$input"
  assert_failure 2
  assert_output --partial "BLOCKED"
}
