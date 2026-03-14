#!/usr/bin/env bats
# tests/conventional_commit.bats — Unit tests for build_commit_msg in ralph/ralph.sh
#
# Run with: bats tests/conventional_commit.bats
#
# Tests verify:
#   - Correct format: <type>(<scope>): <title> with Story + SPIRAL-Run trailers
#   - Type derived from tags; defaults to "feat" when tags absent or unrecognised
#   - Scope derived from top-level directory of first filesTouch entry
#   - No scope parentheses when filesTouch is empty
#   - Story: and SPIRAL-Run: trailers appear in the footer

setup() {
  # Source only the build_commit_msg function from ralph.sh
  # shellcheck source=ralph/ralph.sh
  source <(sed -n '/^build_commit_msg()/,/^}/p' ralph/ralph.sh)
}

# ── Subject line format ────────────────────────────────────────────────────────

@test "build_commit_msg: with tags and filesTouch — subject is type(scope): title" {
  result=$(build_commit_msg "US-042" "Add retry logic" "feat" "lib/retry.sh" "run-99" "7" "12")
  first_line=$(echo "$result" | head -1)
  [ "$first_line" = "feat(lib): Add retry logic" ]
}

@test "build_commit_msg: no tags — defaults to feat type" {
  result=$(build_commit_msg "US-001" "Wire preflight check" "" "spiral.sh" "" "1" "5")
  first_line=$(echo "$result" | head -1)
  [ "$first_line" = "feat(spiral): Wire preflight check" ]
}

@test "build_commit_msg: no filesTouch — no scope parentheses in subject" {
  result=$(build_commit_msg "US-099" "Update docs" "docs" "" "" "3" "2")
  first_line=$(echo "$result" | head -1)
  [ "$first_line" = "docs: Update docs" ]
}

@test "build_commit_msg: fix tag — type is fix" {
  result=$(build_commit_msg "US-010" "Fix null byte crash" "fix" "lib/validate.py" "" "2" "8")
  first_line=$(echo "$result" | head -1)
  [ "$first_line" = "fix(lib): Fix null byte crash" ]
}

@test "build_commit_msg: chore tag — type is chore" {
  result=$(build_commit_msg "US-020" "Remove dead code" "chore" "ralph/ralph.sh" "" "4" "3")
  first_line=$(echo "$result" | head -1)
  [ "$first_line" = "chore(ralph): Remove dead code" ]
}

@test "build_commit_msg: unrecognised tag — falls back to feat" {
  result=$(build_commit_msg "US-030" "Some story" "improvement" "lib/foo.sh" "" "5" "4")
  first_line=$(echo "$result" | head -1)
  [ "$first_line" = "feat(lib): Some story" ]
}

# ── Scope extraction ───────────────────────────────────────────────────────────

@test "build_commit_msg: nested path — scope is top-level dir only" {
  result=$(build_commit_msg "US-050" "Add cache" "feat" "lib/cache/lru.py" "" "6" "10")
  first_line=$(echo "$result" | head -1)
  [ "$first_line" = "feat(lib): Add cache" ]
}

@test "build_commit_msg: root-level file — scope is filename stem" {
  result=$(build_commit_msg "US-051" "Update shell" "feat" "spiral.sh" "" "6" "10")
  first_line=$(echo "$result" | head -1)
  [ "$first_line" = "feat(spiral): Update shell" ]
}

# ── Footer trailers ────────────────────────────────────────────────────────────

@test "build_commit_msg: Story trailer present in output" {
  result=$(build_commit_msg "US-042" "Add retry logic" "feat" "lib/retry.sh" "run-99" "7" "12")
  [[ "$result" == *"Story: US-042"* ]]
}

@test "build_commit_msg: SPIRAL-Run trailer present when run_id provided" {
  result=$(build_commit_msg "US-042" "Add retry logic" "feat" "lib/retry.sh" "run-abc" "7" "12")
  [[ "$result" == *"SPIRAL-Run: run-abc"* ]]
}

@test "build_commit_msg: SPIRAL-Run trailer absent when run_id empty" {
  result=$(build_commit_msg "US-042" "Add retry logic" "feat" "lib/retry.sh" "" "7" "12")
  [[ "$result" != *"SPIRAL-Run:"* ]]
}

# ── Multi-tag CSV ──────────────────────────────────────────────────────────────

@test "build_commit_msg: multiple tags CSV — uses first recognised type" {
  result=$(build_commit_msg "US-060" "Refactor worker" "chore,refactor" "lib/worker.sh" "" "8" "6")
  first_line=$(echo "$result" | head -1)
  # "chore" comes first and is recognised
  [ "$first_line" = "chore(lib): Refactor worker" ]
}
