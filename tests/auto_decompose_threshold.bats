#!/usr/bin/env bats
# tests/auto_decompose_threshold.bats — Unit tests for maybe_auto_decompose()
#
# Run with: bats tests/auto_decompose_threshold.bats
#
# Tests verify:
#   - SPIRAL_DECOMPOSE_THRESHOLD=0 disables auto-decompose (current behaviour)
#   - retry_count below threshold does not trigger
#   - retry_count at threshold invokes decompose_story
#   - retry_count at MAX_RETRIES is NOT handled (left to existing MAX_RETRIES path)
#   - On success, parent is marked _skipped=true + _failureReason=auto_decomposed
#   - On success, an auto_decompose event is written to spiral_events.jsonl

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_AD
  TMPDIR_AD="$(mktemp -d)"

  export PRD_FILE="$TMPDIR_AD/prd.json"
  export PROGRESS_FILE="$TMPDIR_AD/progress.txt"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_AD"
  export RETRY_FILE="$TMPDIR_AD/retry-counts.json"
  export MAX_RETRIES=3

  touch "$PROGRESS_FILE"
  echo '{}' > "$RETRY_FILE"

  # Resolve jq binary
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Minimal prd.json with one story
  cat > "$PRD_FILE" <<'JSON'
{
  "productName": "Test",
  "branchName": "main",
  "userStories": [
    {
      "id": "US-001",
      "title": "Test Story",
      "priority": "medium",
      "description": "A story",
      "acceptanceCriteria": ["Works"],
      "technicalNotes": [],
      "dependencies": [],
      "estimatedComplexity": "small",
      "passes": false
    }
  ]
}
JSON

  # Stub decompose_story: succeeds and writes _decomposed/_decomposedInto on parent
  decompose_story() {
    printf 'decompose_story called\n' > "$TMPDIR_AD/decompose_called"
    "$JQ" '(.userStories[] | select(.id == "US-001") | ._decomposed) = true |
           (.userStories[] | select(.id == "US-001") | ._decomposedInto) = ["US-002","US-003"]' \
      "$PRD_FILE" > "${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE"
    return 0
  }
  export -f decompose_story

  # Stub helpers to avoid real side-effects
  log_ralph_event() {
    printf '%s %s\n' "$1" "${2:-}" >> "$TMPDIR_AD/events.log"
  }
  reset_retry() { true; }
  export -f log_ralph_event reset_retry

  # Source only maybe_auto_decompose from ralph.sh
  source <(sed -n '/^maybe_auto_decompose()/,/^}/p' ralph/ralph.sh)
}

teardown() {
  rm -rf "$TMPDIR_AD"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "threshold=0 disables auto-decompose (returns 1, no decompose called)" {
  export SPIRAL_DECOMPOSE_THRESHOLD=0
  run maybe_auto_decompose "US-001" 2 "sonnet"
  [ "$status" -eq 1 ]
  [ ! -f "$TMPDIR_AD/decompose_called" ]
}

@test "retry_count below threshold does not trigger (returns 1)" {
  export SPIRAL_DECOMPOSE_THRESHOLD=2
  run maybe_auto_decompose "US-001" 1 "sonnet"
  [ "$status" -eq 1 ]
  [ ! -f "$TMPDIR_AD/decompose_called" ]
}

@test "retry_count at threshold triggers decompose_story (returns 0)" {
  export SPIRAL_DECOMPOSE_THRESHOLD=2
  run maybe_auto_decompose "US-001" 2 "sonnet"
  [ "$status" -eq 0 ]
  [ -f "$TMPDIR_AD/decompose_called" ]
}

@test "retry_count at MAX_RETRIES does not trigger auto-decompose (returns 1)" {
  export SPIRAL_DECOMPOSE_THRESHOLD=2
  # MAX_RETRIES=3; at 3 the existing decompose-at-MAX_RETRIES path handles it
  run maybe_auto_decompose "US-001" 3 "sonnet"
  [ "$status" -eq 1 ]
  [ ! -f "$TMPDIR_AD/decompose_called" ]
}

@test "after threshold trigger, parent _skipped is set to true" {
  export SPIRAL_DECOMPOSE_THRESHOLD=2
  maybe_auto_decompose "US-001" 2 "sonnet"
  run "$JQ" -r '.userStories[] | select(.id == "US-001") | ._skipped' "$PRD_FILE"
  [ "$output" = "true" ]
}

@test "after threshold trigger, parent _failureReason is auto_decomposed" {
  export SPIRAL_DECOMPOSE_THRESHOLD=2
  maybe_auto_decompose "US-001" 2 "sonnet"
  run "$JQ" -r '.userStories[] | select(.id == "US-001") | ._failureReason' "$PRD_FILE"
  [ "$output" = "auto_decomposed" ]
}

@test "auto_decompose event is logged to events.log" {
  export SPIRAL_DECOMPOSE_THRESHOLD=2
  maybe_auto_decompose "US-001" 2 "sonnet"
  run grep "auto_decompose" "$TMPDIR_AD/events.log"
  [ "$status" -eq 0 ]
}

@test "auto_decompose event contains storyId and childIds" {
  export SPIRAL_DECOMPOSE_THRESHOLD=2
  maybe_auto_decompose "US-001" 2 "sonnet"
  run grep "auto_decompose" "$TMPDIR_AD/events.log"
  [[ "$output" == *"US-001"* ]]
  [[ "$output" == *"US-002"* ]]
}

@test "custom threshold=1 triggers on first retry" {
  export SPIRAL_DECOMPOSE_THRESHOLD=1
  run maybe_auto_decompose "US-001" 1 "sonnet"
  [ "$status" -eq 0 ]
  [ -f "$TMPDIR_AD/decompose_called" ]
}
