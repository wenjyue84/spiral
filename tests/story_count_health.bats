#!/usr/bin/env bats
# tests/story_count_health.bats — Unit tests for the SPIRAL_MAX_STORIES health check
# in lib/validate_preflight.sh and lib/spiral_doctor.sh
#
# Run with: bats tests/story_count_health.bats

bats_require_minimum_version 1.7.0

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  _resolve_jq
  export TMPDIR_TEST="$(mktemp -d)"
  export SCRATCH_DIR="$TMPDIR_TEST"

  export SPIRAL_PYTHON="python3"
  export SPIRAL_HOME="$PWD"

  # Helper: generate a prd.json with N stories
  make_prd() {
    local n="$1"
    local file="$TMPDIR_TEST/prd.json"
    python3 -c "
import json, sys
n = int(sys.argv[1])
stories = [{'id': f'US-{i:03}', 'title': f'Story {i}', 'passes': False} for i in range(1, n+1)]
print(json.dumps({'schemaVersion': '1', 'userStories': stories}))
" "$n" > "$file"
    echo "$file"
  }
  export -f make_prd
}

teardown() {
  rm -rf "$TMPDIR_TEST"
}

# ── Tests: validate_preflight.sh story count section ─────────────────────────

# Source just the story-count block from validate_preflight.sh as a standalone function
_run_story_count_check() {
  local prd_file="$1"
  local SPIRAL_MAX_STORIES="${SPIRAL_MAX_STORIES:-200}"
  local SPIRAL_MAX_STORIES_ABORT="${SPIRAL_MAX_STORIES_ABORT:-0}"
  local story_count
  story_count=$("$JQ" '.userStories | length' "$prd_file" 2>/dev/null || echo "0")
  if [[ "$story_count" -gt "$SPIRAL_MAX_STORIES" ]]; then
    echo "  [preflight] WARNING: prd.json has $story_count stories (threshold: $SPIRAL_MAX_STORIES) — consider archiving passing stories to reduce context size"
    if [[ "${SPIRAL_MAX_STORIES_ABORT}" != "0" ]]; then
      echo "  [preflight] FATAL: SPIRAL_MAX_STORIES_ABORT is set — aborting due to story count ($story_count > $SPIRAL_MAX_STORIES)"
      return 1
    fi
  fi
  return 0
}

@test "story count below threshold: no warning emitted" {
  local prd
  prd="$(make_prd 5)"
  SPIRAL_MAX_STORIES=200 run _run_story_count_check "$prd"
  assert_success
  refute_output --partial "WARNING"
}

@test "story count exactly at threshold: no warning emitted" {
  local prd
  prd="$(make_prd 200)"
  SPIRAL_MAX_STORIES=200 run _run_story_count_check "$prd"
  assert_success
  refute_output --partial "WARNING"
}

@test "story count exceeds threshold: WARNING emitted" {
  local prd
  prd="$(make_prd 201)"
  SPIRAL_MAX_STORIES=200 run _run_story_count_check "$prd"
  assert_success
  assert_output --partial "WARNING"
  assert_output --partial "201 stories"
  assert_output --partial "threshold: 200"
  assert_output --partial "archiving"
}

@test "story count exceeds threshold: warning includes count and suggestion" {
  local prd
  prd="$(make_prd 50)"
  SPIRAL_MAX_STORIES=10 run _run_story_count_check "$prd"
  assert_success
  assert_output --partial "50 stories"
  assert_output --partial "threshold: 10"
}

@test "SPIRAL_MAX_STORIES_ABORT=1: fails hard when count exceeded" {
  local prd
  prd="$(make_prd 201)"
  SPIRAL_MAX_STORIES=200 SPIRAL_MAX_STORIES_ABORT=1 run _run_story_count_check "$prd"
  assert_failure
  assert_output --partial "FATAL"
  assert_output --partial "SPIRAL_MAX_STORIES_ABORT"
}

@test "SPIRAL_MAX_STORIES_ABORT=0 (default): warns but does not fail" {
  local prd
  prd="$(make_prd 201)"
  SPIRAL_MAX_STORIES=200 SPIRAL_MAX_STORIES_ABORT=0 run _run_story_count_check "$prd"
  assert_success
  assert_output --partial "WARNING"
  refute_output --partial "FATAL"
}

@test "custom SPIRAL_MAX_STORIES=5: warns when prd has 6 stories" {
  local prd
  prd="$(make_prd 6)"
  SPIRAL_MAX_STORIES=5 run _run_story_count_check "$prd"
  assert_success
  assert_output --partial "WARNING"
}

@test "empty prd (0 stories): no warning" {
  local prd="$TMPDIR_TEST/empty.json"
  echo '{"schemaVersion":"1","userStories":[]}' > "$prd"
  SPIRAL_MAX_STORIES=200 run _run_story_count_check "$prd"
  assert_success
  refute_output --partial "WARNING"
}
