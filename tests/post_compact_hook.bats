#!/usr/bin/env bats
# tests/post_compact_hook.bats — Tests for US-379: PostCompact SessionStart hook
#
# Run with: tests/bats-core/bin/bats tests/post_compact_hook.bats
#
# Tests verify:
#   - The hook command exits 0
#   - The hook produces non-empty stdout
#   - CONTEXT_REFRESH.md contains key conventions
#   - settings.json has the SessionStart compact hook

bats_require_minimum_version 1.7.0

# ── Setup ───────────────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
}

# ── Tests ───────────────────────────────────────────────────────────────────

@test "post-compact-hook: cat CONTEXT_REFRESH.md exits 0" {
  run bash -c "cd '$PROJECT_ROOT' && cat ralph/CONTEXT_REFRESH.md"
  assert_success
}

@test "post-compact-hook: CONTEXT_REFRESH.md produces non-empty stdout" {
  run bash -c "cd '$PROJECT_ROOT' && cat ralph/CONTEXT_REFRESH.md"
  assert_success
  [ -n "$output" ]
}

@test "post-compact-hook: CONTEXT_REFRESH.md contains uv convention" {
  run bash -c "cd '$PROJECT_ROOT' && cat ralph/CONTEXT_REFRESH.md"
  assert_success
  assert_output --partial "uv"
}

@test "post-compact-hook: CONTEXT_REFRESH.md contains validation command" {
  run bash -c "cd '$PROJECT_ROOT' && cat ralph/CONTEXT_REFRESH.md"
  assert_success
  assert_output --partial "pytest"
}

@test "post-compact-hook: CONTEXT_REFRESH.md contains diagnosis block reminder" {
  run bash -c "cd '$PROJECT_ROOT' && cat ralph/CONTEXT_REFRESH.md"
  assert_success
  assert_output --partial "Diagnosis"
}

@test "post-compact-hook: CONTEXT_REFRESH.md is under 500 tokens (approx 2000 chars)" {
  local size
  size=$(wc -c <"$PROJECT_ROOT/ralph/CONTEXT_REFRESH.md")
  [ "$size" -lt 2000 ]
}

@test "post-compact-hook: settings.json has SessionStart compact hook" {
  run bash -c "cat '$PROJECT_ROOT/.claude/settings.json'"
  assert_success
  assert_output --partial '"SessionStart"'
  assert_output --partial '"compact"'
  assert_output --partial 'CONTEXT_REFRESH.md'
}
