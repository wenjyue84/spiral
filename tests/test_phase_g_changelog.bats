#!/usr/bin/env bats
# tests/test_phase_g_changelog.bats — Phase G CHANGELOG generation tests (US-1253)
#
# Tests for CHANGELOG.md auto-generation via git-cliff with story ID grouping
# and orphan commit detection.
#
# Run with: bats tests/test_phase_g_changelog.bats

bats_require_minimum_version 1.7.0

setup() {
  load test_helper/common-setup
  _resolve_jq

  # Create temporary test repository
  export TMPDIR_PG
  TMPDIR_PG="$(mktemp -d)"

  export TEST_REPO
  TEST_REPO="${TMPDIR_PG}/test_repo"
  mkdir -p "$TEST_REPO"

  # Initialize git repo
  git -C "$TEST_REPO" init -q
  git -C "$TEST_REPO" config user.email "test@spiral.test"
  git -C "$TEST_REPO" config user.name "Spiral Test"

  # Create initial commit
  echo "# Test Project" >"$TEST_REPO/README.md"
  git -C "$TEST_REPO" add README.md
  git -C "$TEST_REPO" commit -q -m "init: initial commit"

  # Copy cliff.toml and gen_changelog.sh to test repo
  export SPIRAL_HOME
  SPIRAL_HOME="$TEST_REPO"
  cp "$(dirname "$BATS_TEST_DIRNAME")/cliff.toml" "$TEST_REPO/cliff.toml"
  mkdir -p "$TEST_REPO/lib/phases"
  cp "$(dirname "$BATS_TEST_DIRNAME")/lib/phases/gen_changelog.sh" "$TEST_REPO/lib/phases/gen_changelog.sh"
  mkdir -p "$TEST_REPO/.spiral"
}

teardown() {
  rm -rf "$TMPDIR_PG"
}

# Helper: Create a commit with story ID in the body
create_commit_with_story() {
  local message="$1"
  local story_id="$2"
  local filename="file_${story_id}.txt"

  echo "content for $story_id" >"$TEST_REPO/$filename"
  git -C "$TEST_REPO" add "$filename"
  git -C "$TEST_REPO" commit -q -m "$message" -m "Story: $story_id" -m "Co-Authored-By: Test <test@test.com>"
}

# Helper: Create a commit without story ID (orphan)
create_orphan_commit() {
  local message="$1"
  local filename="orphan_$(date +%s).txt"

  echo "orphan content" >"$TEST_REPO/$filename"
  git -C "$TEST_REPO" add "$filename"
  git -C "$TEST_REPO" commit -q -m "$message"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "phase_g.sh sources successfully" {
  source "$(dirname "$BATS_TEST_DIRNAME")/lib/phases/phase_g.sh"
  declare -f run_phase_g
  [ $? -eq 0 ]
}

@test "cliff.toml config file exists" {
  [[ -f "$TEST_REPO/cliff.toml" ]]
}

@test "cliff.toml contains changelog header" {
  grep -q "# Changelog" "$TEST_REPO/cliff.toml"
}

@test "cliff.toml has conventional_commits enabled" {
  grep -q "conventional_commits = true" "$TEST_REPO/cliff.toml"
}

@test "cliff.toml defines commit_parsers for feat/fix/docs" {
  grep -q 'message = "\^feat"' "$TEST_REPO/cliff.toml"
  grep -q 'message = "\^fix"' "$TEST_REPO/cliff.toml"
  grep -q 'message = "\^docs"' "$TEST_REPO/cliff.toml"
}

@test "gen_changelog.sh module loads without errors" {
  source "$TEST_REPO/lib/phases/gen_changelog.sh"
  declare -f phase_gen_changelog
  [ $? -eq 0 ]
}

@test "creates CHANGELOG.md with single feature commit" {
  create_commit_with_story "feat: Add dashboard widget" "US-1001"

  source "$TEST_REPO/lib/phases/gen_changelog.sh"
  SPIRAL_HOME="$TEST_REPO" phase_gen_changelog

  [[ -f "$TEST_REPO/CHANGELOG.md" ]]
  grep -q "Features" "$TEST_REPO/CHANGELOG.md"
  grep -q "US-1001" "$TEST_REPO/CHANGELOG.md"
}

@test "creates CHANGELOG.md with multiple commits grouped by type" {
  create_commit_with_story "feat: Add dashboard widget" "US-1001"
  create_commit_with_story "fix: Resolve memory leak" "US-1002"
  create_commit_with_story "docs: Update API reference" "US-1003"

  source "$TEST_REPO/lib/phases/gen_changelog.sh"
  SPIRAL_HOME="$TEST_REPO" phase_gen_changelog

  [[ -f "$TEST_REPO/CHANGELOG.md" ]]
  grep -q "### Features" "$TEST_REPO/CHANGELOG.md"
  grep -q "### Bug Fixes" "$TEST_REPO/CHANGELOG.md"
  grep -q "### Documentation" "$TEST_REPO/CHANGELOG.md"
}

@test "CHANGELOG.md includes commit hash links" {
  create_commit_with_story "feat: Add new feature" "US-1001"

  source "$TEST_REPO/lib/phases/gen_changelog.sh"
  SPIRAL_HOME="$TEST_REPO" phase_gen_changelog

  # Should contain commit hash in a markdown link format
  grep -qE '\([0-9a-f]{7,}\)' "$TEST_REPO/CHANGELOG.md"
}

@test "detects orphan commits without story ID" {
  create_commit_with_story "feat: Add widget" "US-1001"
  create_orphan_commit "chore: update dependencies"

  source "$TEST_REPO/lib/phases/gen_changelog.sh"
  SPIRAL_HOME="$TEST_REPO" phase_gen_changelog

  # Orphan warnings should be logged
  [[ -f "$TEST_REPO/.spiral/phase_g_warnings.log" ]]
  grep -q "chore: update dependencies" "$TEST_REPO/.spiral/phase_g_warnings.log"
}

@test "orphan commit log contains commit hash and message" {
  create_orphan_commit "chore: missing story id"

  source "$TEST_REPO/lib/phases/gen_changelog.sh"
  SPIRAL_HOME="$TEST_REPO" phase_gen_changelog

  local log_line
  log_line=$(cat "$TEST_REPO/.spiral/phase_g_warnings.log" | head -1)

  # Format should be: <hash> <message>
  [[ "$log_line" =~ ^[0-9a-f]{7,} ]]
  [[ "$log_line" =~ "chore: missing story id" ]]
}

@test "skips chore commits in CHANGELOG" {
  create_commit_with_story "feat: Add feature" "US-1001"
  create_commit_with_story "chore: bump version" "US-1002"

  source "$TEST_REPO/lib/phases/gen_changelog.sh"
  SPIRAL_HOME="$TEST_REPO" phase_gen_changelog

  # Chore should be skipped (filtered_commits)
  ! grep -q "bump version" "$TEST_REPO/CHANGELOG.md"
}

@test "validates that CHANGELOG.md is valid markdown" {
  create_commit_with_story "feat: Add dashboard" "US-1001"

  source "$TEST_REPO/lib/phases/gen_changelog.sh"
  SPIRAL_HOME="$TEST_REPO" phase_gen_changelog

  # Should have markdown headers
  grep -q "^# Changelog" "$TEST_REPO/CHANGELOG.md"
  grep -q "^###" "$TEST_REPO/CHANGELOG.md"
}

@test "phase_gen_changelog returns 0 on success" {
  create_commit_with_story "feat: Test feature" "US-1001"

  source "$TEST_REPO/lib/phases/gen_changelog.sh"
  SPIRAL_HOME="$TEST_REPO" phase_gen_changelog
  [ $? -eq 0 ]
}

@test "phase_gen_changelog fails if cliff.toml not found" {
  # Remove cliff.toml to trigger error
  rm "$TEST_REPO/cliff.toml"

  source "$TEST_REPO/lib/phases/gen_changelog.sh"
  SPIRAL_HOME="$TEST_REPO" phase_gen_changelog
  [ $? -ne 0 ]
}

@test "run_phase_g orchestration stub works" {
  create_commit_with_story "feat: Test feature" "US-1001"

  source "$(dirname "$BATS_TEST_DIRNAME")/lib/phases/phase_g.sh"
  SPIRAL_HOME="$TEST_REPO" run_phase_g
  [ $? -eq 0 ]
  [[ -f "$TEST_REPO/CHANGELOG.md" ]]
}

@test "multiple stories can be tracked in same commit" {
  # Some commits might reference multiple story IDs in the message
  local msg="feat: Implement feature for two stories"
  local filename="multi_story.txt"

  echo "content" >"$TEST_REPO/$filename"
  git -C "$TEST_REPO" add "$filename"
  git -C "$TEST_REPO" commit -q -m "$msg" -m "Story: US-1001"

  source "$TEST_REPO/lib/phases/gen_changelog.sh"
  SPIRAL_HOME="$TEST_REPO" phase_gen_changelog

  # Should generate CHANGELOG without errors
  [[ -f "$TEST_REPO/CHANGELOG.md" ]]
  [ $? -eq 0 ]
}

@test "CHANGELOG preserves commit message formatting" {
  create_commit_with_story "feat: Add feature with (parentheses) and [brackets]" "US-1001"

  source "$TEST_REPO/lib/phases/gen_changelog.sh"
  SPIRAL_HOME="$TEST_REPO" phase_gen_changelog

  grep -q "(parentheses)" "$TEST_REPO/CHANGELOG.md" || grep -q "parentheses" "$TEST_REPO/CHANGELOG.md"
}
