#!/usr/bin/env bats
# tests/idempotency_guard.bats — Tests for US-325: Phase I idempotency guard
#
# Run with: bats tests/idempotency_guard.bats
#
# Tests verify:
#   - check_idempotency_guard skips stories with existing commits
#   - Skipped stories are marked passes=true with _passedCommit SHA
#   - Revert commits are NOT treated as idempotent matches
#   - Stories without matching commits proceed normally
#   - idempotency_skip event is logged to spiral_events.jsonl

bats_require_minimum_version 1.7.0

# ── Helpers ──────────────────────────────────────────────────────────────────

# Source check_idempotency_guard from spiral.sh by extracting just the function
# and its dependencies. We set up a minimal environment to avoid running the
# full script.

_source_guard() {
  export REPO_ROOT="$TEST_DIR/repo"
  export SCRATCH_DIR="$TEST_DIR/scratch"
  export SPIRAL_RUN_ID="test-run-001"
  export SPIRAL_ITER=1
  export SPIRAL_LOG_LEVEL="INFO"
  mkdir -p "$SCRATCH_DIR"

  # Detect jq
  if command -v jq &>/dev/null; then
    JQ="jq"
  elif [[ -f "$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/ralph/jq.exe" ]]; then
    JQ="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/ralph/jq.exe"
  else
    skip "jq not available"
  fi
  export JQ

  # Source spiral_events.sh for log_spiral_event
  SPIRAL_HOME="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$SPIRAL_HOME/lib/spiral_events.sh"

  # Define check_idempotency_guard inline (mirrors spiral.sh definition)
  check_idempotency_guard() {
    local story_id="$1"
    local prd_file="$2"

    local existing_sha
    existing_sha=$(git -C "$REPO_ROOT" log --grep="$story_id" --max-count=1 --format=%H 2>/dev/null || echo "")

    if [[ -z "$existing_sha" ]]; then
      return 1
    fi

    local commit_subject
    commit_subject=$(git -C "$REPO_ROOT" log -1 --format=%s "$existing_sha" 2>/dev/null || echo "")
    if [[ "$commit_subject" == Revert* ]]; then
      return 1
    fi

    echo "  [idempotency] Story $story_id already implemented in commit ${existing_sha:0:8} — skipping"
    "$JQ" --arg id "$story_id" --arg sha "$existing_sha" \
      '(.userStories[] | select(.id == $id)) |= (.passes = true | ._passedCommit = $sha)' \
      "$prd_file" >"${prd_file}.tmp" && mv "${prd_file}.tmp" "$prd_file"

    log_spiral_event "idempotency_skip" \
      "\"story_id\":\"$story_id\",\"commit_sha\":\"$existing_sha\",\"iteration\":${SPIRAL_ITER:-0}"

    return 0
  }
}

# ── Setup / Teardown ─────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  _resolve_jq
  TEST_DIR="$(mktemp -d)"
  git init -b main "$TEST_DIR/repo" >/dev/null 2>&1
  cd "$TEST_DIR/repo"
  git config user.email "test@spiral.dev"
  git config user.name "SPIRAL Test"
  git config core.autocrlf false

  # Create initial prd.json with one pending story
  cat >prd.json <<'EOF'
{
  "userStories": [
    {
      "id": "US-999",
      "title": "Test story for idempotency",
      "passes": false,
      "priority": "high"
    }
  ]
}
EOF
  git add prd.json
  git commit -m "init: add prd.json" >/dev/null 2>&1

  _source_guard
}

teardown() {
  cd /
  rm -rf "$TEST_DIR" 2>/dev/null || true
}

# ── Test: story with existing commit is skipped ──────────────────────────────

@test "idempotency guard skips story when matching commit exists" {
  cd "$TEST_DIR/repo"

  # Create a commit that mentions the story ID
  echo "implementation" >feature.txt
  git add feature.txt
  git commit -m "feat: US-999 implement test story" >/dev/null 2>&1

  run check_idempotency_guard "US-999" "$TEST_DIR/repo/prd.json"
  assert_success
  assert_output --partial "[idempotency]"
  assert_output --partial "US-999"
  assert_output --partial "skipping"
}

# ── Test: story marked passes=true with _passedCommit ────────────────────────

@test "idempotency guard sets passes=true and _passedCommit SHA" {
  cd "$TEST_DIR/repo"

  echo "implementation" >feature.txt
  git add feature.txt
  git commit -m "feat: US-999 implement test story" >/dev/null 2>&1
  EXPECTED_SHA=$(git rev-parse HEAD)

  check_idempotency_guard "US-999" "$TEST_DIR/repo/prd.json"

  # Verify passes=true
  passes=$("$JQ" -r '.userStories[] | select(.id == "US-999") | .passes' "$TEST_DIR/repo/prd.json")
  [ "$passes" = "true" ]

  # Verify _passedCommit matches the commit SHA
  passed_commit=$("$JQ" -r '.userStories[] | select(.id == "US-999") | ._passedCommit' "$TEST_DIR/repo/prd.json")
  [ "$passed_commit" = "$EXPECTED_SHA" ]
}

# ── Test: Revert commits are not treated as matches ──────────────────────────

@test "idempotency guard ignores Revert commits" {
  cd "$TEST_DIR/repo"

  # Create a feature commit and then revert it
  echo "implementation" >feature.txt
  git add feature.txt
  git commit -m "feat: US-999 implement test story" >/dev/null 2>&1
  git revert --no-edit HEAD >/dev/null 2>&1

  # The most recent commit mentioning US-999 is the revert
  run check_idempotency_guard "US-999" "$TEST_DIR/repo/prd.json"
  assert_failure 1

  # Story should still be passes=false
  passes=$("$JQ" -r '.userStories[] | select(.id == "US-999") | .passes' "$TEST_DIR/repo/prd.json")
  [ "$passes" = "false" ]
}

# ── Test: story without matching commit proceeds normally ────────────────────

@test "idempotency guard returns 1 when no matching commit exists" {
  cd "$TEST_DIR/repo"

  # No commit mentioning US-999 beyond the init (which mentions prd.json, not the story)
  run check_idempotency_guard "US-999" "$TEST_DIR/repo/prd.json"
  assert_failure 1

  # Story should still be passes=false
  passes=$("$JQ" -r '.userStories[] | select(.id == "US-999") | .passes' "$TEST_DIR/repo/prd.json")
  [ "$passes" = "false" ]
}

# ── Test: idempotency_skip event is logged ───────────────────────────────────

@test "idempotency guard logs idempotency_skip event to spiral_events.jsonl" {
  cd "$TEST_DIR/repo"

  echo "implementation" >feature.txt
  git add feature.txt
  git commit -m "feat: US-999 implement test story" >/dev/null 2>&1

  check_idempotency_guard "US-999" "$TEST_DIR/repo/prd.json"

  # Check spiral_events.jsonl for the event
  [ -f "$SCRATCH_DIR/spiral_events.jsonl" ]
  grep -q "idempotency_skip" "$SCRATCH_DIR/spiral_events.jsonl"
  grep -q "US-999" "$SCRATCH_DIR/spiral_events.jsonl"
}
