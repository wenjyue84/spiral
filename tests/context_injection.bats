#!/usr/bin/env bats
# tests/context_injection.bats — Unit tests for build_files_context() (US-280)
#
# Run with: tests/bats-core/bin/bats tests/context_injection.bats
#
# Tests verify:
#   - diff mode produces output smaller than full mode for a modified file
#   - full mode injects complete file contents
#   - empty filesTouch produces no output
#   - new file (empty diff) falls back to full content
#   - truncation at SPIRAL_MAX_DIFF_LINES adds notice
#   - SPIRAL_CONTEXT_MODE=full injects full file contents

# ── Setup / teardown ──────────────────────────────────────────────────────────

setup() {
  export TMPDIR
  TMPDIR="$(mktemp -d)"

  # Create a temporary git repo for testing
  export TEST_REPO="$TMPDIR/repo"
  mkdir -p "$TEST_REPO"
  cd "$TEST_REPO" || return 1
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"

  # Commit 1: create a file with 50 lines
  seq 1 50 > bigfile.txt
  git add bigfile.txt
  git commit -q -m "init"

  # Commit 2: modify the file (append 10 lines)
  seq 51 60 >> bigfile.txt
  git add bigfile.txt
  git commit -q -m "update bigfile"

  # Commit 3: add a newfile (no prior history)
  echo "brand new" > newfile.txt
  git add newfile.txt
  git commit -q -m "add newfile"

  # Build a minimal jq stub path
  export JQ
  if command -v jq &>/dev/null; then
    JQ="jq"
  else
    skip "jq not available"
  fi

  # Source build_files_context from ralph.sh by extracting the function
  # We isolate it by sourcing only the function definition.
  export SPIRAL_SCRATCH_DIR="$TMPDIR/scratch"
  mkdir -p "$SPIRAL_SCRATCH_DIR"

  # Extract the build_files_context function + its env var defaults from ralph.sh
  # This avoids executing the full ralph.sh startup code.
  _RALPH_SH="$(cd "$BATS_TEST_DIRNAME/.." && pwd)/ralph/ralph.sh"
  if [[ ! -f "$_RALPH_SH" ]]; then
    skip "ralph/ralph.sh not found"
  fi

  # Source env defaults that build_files_context depends on
  export SPIRAL_CONTEXT_MODE="${SPIRAL_CONTEXT_MODE:-diff}"
  export SPIRAL_DIFF_DEPTH="${SPIRAL_DIFF_DEPTH:-3}"
  export SPIRAL_MAX_DIFF_LINES="${SPIRAL_MAX_DIFF_LINES:-500}"

  # Extract and eval the build_files_context function body
  eval "$(sed -n '/^build_files_context()/,/^}/p' "$_RALPH_SH")"
}

teardown() {
  rm -rf "$TMPDIR"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

make_story_json() {
  local files="$1"  # JSON array string e.g. '["bigfile.txt"]'
  printf '{"id":"US-TEST","filesTouch":%s}' "$files"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "diff mode: produces non-empty output for a modified file" {
  cd "$TEST_REPO"
  SPIRAL_CONTEXT_MODE="diff"
  local story_json
  story_json=$(make_story_json '["bigfile.txt"]')
  run build_files_context "$story_json"
  [ "$status" -eq 0 ]
  [ -n "$output" ]
}

@test "diff mode: output contains diff header" {
  cd "$TEST_REPO"
  SPIRAL_CONTEXT_MODE="diff"
  local story_json
  story_json=$(make_story_json '["bigfile.txt"]')
  run build_files_context "$story_json"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Diff (last"* ]] || [[ "$output" == *"File (new/unchanged)"* ]]
}

@test "diff mode output is smaller than full mode for modified file" {
  cd "$TEST_REPO"
  local story_json
  story_json=$(make_story_json '["bigfile.txt"]')

  # Use depth=1 so HEAD~1 exists (HEAD~3 would be before the initial commit)
  SPIRAL_CONTEXT_MODE="diff" SPIRAL_DIFF_DEPTH=1 run build_files_context "$story_json"
  local diff_output="$output"

  SPIRAL_CONTEXT_MODE="full" SPIRAL_DIFF_DEPTH=1 run build_files_context "$story_json"
  local full_output="$output"

  local diff_len=${#diff_output}
  local full_len=${#full_output}

  # Diff context (10 changed lines + context) must be smaller than full 60-line file
  [ "$diff_len" -lt "$full_len" ]
}

@test "full mode: injects complete file contents" {
  cd "$TEST_REPO"
  SPIRAL_CONTEXT_MODE="full"
  local story_json
  story_json=$(make_story_json '["bigfile.txt"]')
  run build_files_context "$story_json"
  [ "$status" -eq 0 ]
  # Full file has 60 lines (seq 1..60); output should contain them
  [[ "$output" == *"60"* ]]
  [[ "$output" == *"### File:"* ]]
}

@test "new file (empty diff): falls back to full content" {
  cd "$TEST_REPO"
  SPIRAL_CONTEXT_MODE="diff"
  local story_json
  story_json=$(make_story_json '["newfile.txt"]')
  run build_files_context "$story_json"
  [ "$status" -eq 0 ]
  # newfile.txt has no history before HEAD~1, so diff is empty → fall back
  [[ "$output" == *"brand new"* ]] || [[ "$output" == *"new/unchanged"* ]]
}

@test "empty filesTouch: produces no output" {
  cd "$TEST_REPO"
  SPIRAL_CONTEXT_MODE="diff"
  local story_json
  story_json='{"id":"US-TEST","filesTouch":[]}'
  run build_files_context "$story_json"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "missing filesTouch key: produces no output" {
  cd "$TEST_REPO"
  SPIRAL_CONTEXT_MODE="diff"
  local story_json='{"id":"US-TEST"}'
  run build_files_context "$story_json"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "truncation: output does not exceed SPIRAL_MAX_DIFF_LINES" {
  cd "$TEST_REPO"
  SPIRAL_CONTEXT_MODE="full"
  SPIRAL_MAX_DIFF_LINES=5  # very small limit
  local story_json
  story_json=$(make_story_json '["bigfile.txt"]')
  run build_files_context "$story_json"
  [ "$status" -eq 0 ]
  [ -n "$output" ]
  # Should contain truncation notice
  [[ "$output" == *"truncated at SPIRAL_MAX_DIFF_LINES"* ]]
}

@test "truncation: line count is at most max_lines + small header overhead" {
  cd "$TEST_REPO"
  SPIRAL_CONTEXT_MODE="full"
  SPIRAL_MAX_DIFF_LINES=10
  local story_json
  story_json=$(make_story_json '["bigfile.txt"]')
  run build_files_context "$story_json"
  [ "$status" -eq 0 ]
  local line_count
  line_count=$(printf '%s\n' "$output" | wc -l)
  # Allow a few extra lines for header + truncation notice
  [ "$line_count" -le 20 ]
}

@test "context mode header appears in output" {
  cd "$TEST_REPO"
  SPIRAL_CONTEXT_MODE="diff"
  local story_json
  story_json=$(make_story_json '["bigfile.txt"]')
  run build_files_context "$story_json"
  [ "$status" -eq 0 ]
  [[ "$output" == *"SPIRAL_CONTEXT_MODE=diff"* ]]
}
