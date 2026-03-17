#!/usr/bin/env bats
# tests/story_completeness.bats — Unit tests for story completeness checks (US-250)
#
# Run with: bats tests/story_completeness.bats
#
# Tests verify:
#   - check_story_completeness detects missing title
#   - check_story_completeness detects missing description
#   - check_story_completeness detects missing acceptanceCriteria
#   - check_story_completeness returns 0 for complete story

bats_require_minimum_version 1.7.0

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  _resolve_jq
  export SPIRAL_SCRATCH_DIR="$(mktemp -d)"
  export JQ="jq"

  # Check if jq is available
  if ! command -v jq &>/dev/null; then
    if [[ -f "ralph/jq.exe" ]]; then
      export JQ="ralph/jq.exe"
    elif [[ -f "ralph/jq" ]]; then
      export JQ="ralph/jq"
    fi
  fi

  # Source the check_story_completeness function from ralph.sh
  source <(sed -n '/^check_story_completeness()/,/^}/p' ralph/ralph.sh)
}

teardown() {
  rm -rf "$SPIRAL_SCRATCH_DIR"
}

# ── Story completeness tests ───────────────────────────────────────────────────

@test "check_story_completeness: complete story returns 0" {
  local prd_file="$SPIRAL_SCRATCH_DIR/prd.json"
  $JQ -n '{
    userStories: [
      {
        id: "US-100",
        title: "Test Story",
        description: "A test story description",
        acceptanceCriteria: ["Criterion 1", "Criterion 2"]
      }
    ]
  }' >"$prd_file"

  run check_story_completeness "US-100" "$prd_file"
  assert_success
}

@test "check_story_completeness: missing title returns 1" {
  local prd_file="$SPIRAL_SCRATCH_DIR/prd.json"
  $JQ -n '{
    userStories: [
      {
        id: "US-101",
        description: "A test story description",
        acceptanceCriteria: ["Criterion 1"]
      }
    ]
  }' >"$prd_file"

  run check_story_completeness "US-101" "$prd_file"
  assert_failure 1
  assert_output --partial "title=✗"
}

@test "check_story_completeness: missing description returns 1" {
  local prd_file="$SPIRAL_SCRATCH_DIR/prd.json"
  $JQ -n '{
    userStories: [
      {
        id: "US-102",
        title: "Test Story",
        acceptanceCriteria: ["Criterion 1"]
      }
    ]
  }' >"$prd_file"

  run check_story_completeness "US-102" "$prd_file"
  assert_failure 1
  assert_output --partial "description=✗"
}

@test "check_story_completeness: missing acceptanceCriteria returns 1" {
  local prd_file="$SPIRAL_SCRATCH_DIR/prd.json"
  $JQ -n '{
    userStories: [
      {
        id: "US-103",
        title: "Test Story",
        description: "A test story description"
      }
    ]
  }' >"$prd_file"

  run check_story_completeness "US-103" "$prd_file"
  assert_failure 1
  assert_output --partial "acceptanceCriteria=✗"
}

@test "check_story_completeness: empty acceptanceCriteria array returns 1" {
  local prd_file="$SPIRAL_SCRATCH_DIR/prd.json"
  $JQ -n '{
    userStories: [
      {
        id: "US-104",
        title: "Test Story",
        description: "A test story description",
        acceptanceCriteria: []
      }
    ]
  }' >"$prd_file"

  run check_story_completeness "US-104" "$prd_file"
  assert_failure 1
  assert_output --partial "acceptanceCriteria=✗"
}

@test "check_story_completeness: story with multiple acceptance criteria returns 0" {
  local prd_file="$SPIRAL_SCRATCH_DIR/prd.json"
  $JQ -n '{
    userStories: [
      {
        id: "US-105",
        title: "Complex Story",
        description: "A complex test story with many requirements",
        acceptanceCriteria: [
          "Criterion 1",
          "Criterion 2",
          "Criterion 3",
          "Criterion 4",
          "Criterion 5"
        ]
      }
    ]
  }' >"$prd_file"

  run check_story_completeness "US-105" "$prd_file"
  assert_success
}

@test "check_story_completeness: nonexistent story returns 1" {
  local prd_file="$SPIRAL_SCRATCH_DIR/prd.json"
  $JQ -n '{userStories: []}' >"$prd_file"

  run check_story_completeness "US-999" "$prd_file"
  assert_failure 1
}
