#!/usr/bin/env bats
# tests/prd_stream.bats — Unit tests for get_pending_story_ids() in ralph/ralph.sh
#
# Run with: bats tests/prd_stream.bats
#
# Tests verify:
#   - Non-streaming path (small files) returns correct IDs sorted by priority
#   - Streaming path (jq --stream) returns identical output to non-streaming path
#   - SPIRAL_PRD_STREAM_THRESHOLD_KB=0 forces streaming path
#   - Empty pending set returns no output
#   - Decomposed stories are excluded from both paths

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export SPIRAL_SCRATCH_DIR="$(mktemp -d)"
  export PRD_FILE="$SPIRAL_SCRATCH_DIR/prd.json"
  export PROGRESS_FILE="/dev/null"

  # Resolve jq binary (same logic as other bats tests)
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Source only get_pending_story_ids from ralph.sh
  # Use sed to extract the function body plus the default variable it references
  source <(grep -E '^SPIRAL_PRD_STREAM_THRESHOLD_KB=' ralph/ralph.sh | head -1)
  source <(sed -n '/^get_pending_story_ids()/,/^}/p' ralph/ralph.sh)
}

teardown() {
  rm -rf "$SPIRAL_SCRATCH_DIR"
}

# ── Helper: write a minimal PRD JSON ──────────────────────────────────────────

_write_prd() {
  cat > "$PRD_FILE"
}

# ── Small-file (non-streaming) path ──────────────────────────────────────────

@test "non-streaming: returns pending IDs sorted by priority (critical first)" {
  _write_prd <<'EOF'
{
  "userStories": [
    {"id": "US-001", "title": "A", "priority": "low",      "passes": false},
    {"id": "US-002", "title": "B", "priority": "critical",  "passes": false},
    {"id": "US-003", "title": "C", "priority": "high",      "passes": false},
    {"id": "US-004", "title": "D", "priority": "medium",    "passes": true}
  ]
}
EOF
  export SPIRAL_PRD_STREAM_THRESHOLD_KB=9999
  run get_pending_story_ids "$PRD_FILE"
  [ "$status" -eq 0 ]
  # critical < high < low alphabetically (same order as sort_by(.priority) in jq)
  [ "${lines[0]}" = "US-002" ]
  [ "${lines[1]}" = "US-003" ]
  [ "${lines[2]}" = "US-001" ]
}

@test "non-streaming: excludes passed stories" {
  _write_prd <<'EOF'
{
  "userStories": [
    {"id": "US-001", "title": "A", "priority": "medium", "passes": true},
    {"id": "US-002", "title": "B", "priority": "medium", "passes": false}
  ]
}
EOF
  export SPIRAL_PRD_STREAM_THRESHOLD_KB=9999
  run get_pending_story_ids "$PRD_FILE"
  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [ "${lines[0]}" = "US-002" ]
}

@test "non-streaming: excludes _decomposed parent stories" {
  _write_prd <<'EOF'
{
  "userStories": [
    {"id": "US-001", "title": "A", "priority": "high", "passes": false, "_decomposed": true},
    {"id": "US-002", "title": "B", "priority": "high", "passes": false}
  ]
}
EOF
  export SPIRAL_PRD_STREAM_THRESHOLD_KB=9999
  run get_pending_story_ids "$PRD_FILE"
  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [ "${lines[0]}" = "US-002" ]
}

@test "non-streaming: empty result when all stories pass" {
  _write_prd <<'EOF'
{"userStories": [{"id": "US-001", "title": "A", "priority": "high", "passes": true}]}
EOF
  export SPIRAL_PRD_STREAM_THRESHOLD_KB=9999
  run get_pending_story_ids "$PRD_FILE"
  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 0 ]
}

# ── Streaming path (SPIRAL_PRD_STREAM_THRESHOLD_KB=0) ────────────────────────

@test "streaming: returns pending IDs sorted by priority (critical first)" {
  _write_prd <<'EOF'
{
  "userStories": [
    {"id": "US-001", "title": "A", "priority": "low",      "passes": false},
    {"id": "US-002", "title": "B", "priority": "critical",  "passes": false},
    {"id": "US-003", "title": "C", "priority": "high",      "passes": false},
    {"id": "US-004", "title": "D", "priority": "medium",    "passes": true}
  ]
}
EOF
  export SPIRAL_PRD_STREAM_THRESHOLD_KB=0
  run get_pending_story_ids "$PRD_FILE"
  [ "$status" -eq 0 ]
  [ "${lines[0]}" = "US-002" ]
  [ "${lines[1]}" = "US-003" ]
  [ "${lines[2]}" = "US-001" ]
}

@test "streaming: excludes passed stories" {
  _write_prd <<'EOF'
{
  "userStories": [
    {"id": "US-001", "title": "A", "priority": "medium", "passes": true},
    {"id": "US-002", "title": "B", "priority": "medium", "passes": false}
  ]
}
EOF
  export SPIRAL_PRD_STREAM_THRESHOLD_KB=0
  run get_pending_story_ids "$PRD_FILE"
  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [ "${lines[0]}" = "US-002" ]
}

@test "streaming: excludes _decomposed parent stories" {
  _write_prd <<'EOF'
{
  "userStories": [
    {"id": "US-001", "title": "A", "priority": "high", "passes": false, "_decomposed": true},
    {"id": "US-002", "title": "B", "priority": "high", "passes": false}
  ]
}
EOF
  export SPIRAL_PRD_STREAM_THRESHOLD_KB=0
  run get_pending_story_ids "$PRD_FILE"
  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [ "${lines[0]}" = "US-002" ]
}

@test "streaming: empty result when all stories pass" {
  _write_prd <<'EOF'
{"userStories": [{"id": "US-001", "title": "A", "priority": "high", "passes": true}]}
EOF
  export SPIRAL_PRD_STREAM_THRESHOLD_KB=0
  run get_pending_story_ids "$PRD_FILE"
  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 0 ]
}

# ── Equivalence: both paths must produce identical output ─────────────────────

@test "both paths produce identical output on a 50-story synthetic PRD" {
  # Generate a 50-story synthetic prd.json with mixed pass/fail states
  python3 - <<'PYEOF' > "$PRD_FILE"
import json, random
random.seed(42)
priorities = ["critical", "high", "medium", "low"]
stories = []
for i in range(1, 51):
    sid = f"US-{i:03d}"
    stories.append({
        "id": sid,
        "title": f"Story {i}",
        "priority": random.choice(priorities),
        "passes": random.random() < 0.4,
    })
print(json.dumps({"userStories": stories}))
PYEOF

  export SPIRAL_PRD_STREAM_THRESHOLD_KB=9999
  run get_pending_story_ids "$PRD_FILE"
  normal_output="$output"

  export SPIRAL_PRD_STREAM_THRESHOLD_KB=0
  run get_pending_story_ids "$PRD_FILE"
  stream_output="$output"

  [ "$normal_output" = "$stream_output" ]
}
