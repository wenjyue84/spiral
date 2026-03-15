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
  git config core.autocrlf false   # prevent CRLF conversion on Windows

  # Commit 1: create a large file (200 lines) to ensure diff < full
  seq 1 200 > bigfile.txt
  git add bigfile.txt
  git commit -q -m "init"

  # Commit 2: small modification — change only last 3 lines
  # The unified diff (~25 lines with context) will be much smaller than the full 200-line file
  printf '198_modified\n199_modified\n200_modified\n' >> bigfile.txt
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

  export SPIRAL_SCRATCH_DIR="$TMPDIR/scratch"
  mkdir -p "$SPIRAL_SCRATCH_DIR"

  # Source env defaults that build_files_context depends on
  export SPIRAL_CONTEXT_MODE="${SPIRAL_CONTEXT_MODE:-diff}"
  export SPIRAL_DIFF_DEPTH="${SPIRAL_DIFF_DEPTH:-3}"
  export SPIRAL_MAX_DIFF_LINES="${SPIRAL_MAX_DIFF_LINES:-500}"

  # Source the context injection library directly (US-280: lib/context_injection.sh)
  _LIB="$(cd "$BATS_TEST_DIRNAME/.." && pwd)/lib/context_injection.sh"
  if [[ ! -f "$_LIB" ]]; then
    skip "lib/context_injection.sh not found"
  fi
  source "$_LIB"
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

  # bigfile.txt has 200 lines; only 3 lines were added in commit 2 (HEAD~1).
  # git diff HEAD~2 -- bigfile.txt shows +3 lines + context (~20 lines total),
  # which is much smaller than the full 203-line file.
  # Note: VAR=value prefix does not propagate into bats run for shell functions;
  # set variables explicitly before each run call.
  SPIRAL_CONTEXT_MODE="diff"
  SPIRAL_DIFF_DEPTH=2
  run build_files_context "$story_json"
  local diff_output="$output"

  SPIRAL_CONTEXT_MODE="full"
  SPIRAL_DIFF_DEPTH=2
  run build_files_context "$story_json"
  local full_output="$output"

  local diff_len=${#diff_output}
  local full_len=${#full_output}

  # Diff context (~20 lines with headers) must be smaller than full 203-line file
  [ "$diff_len" -lt "$full_len" ]
}

@test "full mode: injects complete file contents" {
  cd "$TEST_REPO"
  SPIRAL_CONTEXT_MODE="full"
  local story_json
  story_json=$(make_story_json '["bigfile.txt"]')
  run build_files_context "$story_json"
  [ "$status" -eq 0 ]
  # Full file has 200+ lines; output should contain line 200
  [[ "$output" == *"200"* ]]
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
