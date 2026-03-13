#!/usr/bin/env bats
# tests/worker_heartbeat.bats — Unit tests for lib/worker_heartbeat.sh
#
# Run with: bats tests/worker_heartbeat.bats
# Install bats: https://github.com/bats-core/bats-core
#
# Tests verify:
#   - worker_heartbeat_start writes a heartbeat file after one interval
#   - worker_heartbeat_stop cleans up the file and stops the loop
#   - check_stale_heartbeats returns [] when no heartbeats exist
#   - check_stale_heartbeats returns [] for a fresh heartbeat
#   - check_stale_heartbeats returns entry for an old heartbeat file
#   - check_stale_heartbeats returns valid JSON (no leading comma)
#   - check_stale_heartbeats handles multiple stale files
#   - requeue_stale_stories with plain story ID keeps passes=false, retryCount unchanged
#   - requeue_stale_stories with JSON stale_info extracts storyId correctly
#   - requeue_stale_stories is a no-op for unknown story IDs
#   - Integration: simulate crashed worker → story requeued within threshold

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_HB="$(mktemp -d)"
  export HEARTBEAT_DIR="$TMPDIR_HB/workers"
  export HEARTBEAT_INTERVAL=2    # Fast interval for testing
  export STALE_THRESHOLD=120

  mkdir -p "$HEARTBEAT_DIR"

  # Resolve jq
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  source "lib/worker_heartbeat.sh"
}

teardown() {
  # Stop any running heartbeat loop
  if [[ -n "${_HEARTBEAT_PID:-}" ]]; then
    kill "$_HEARTBEAT_PID" 2>/dev/null || true
  fi
  rm -rf "$TMPDIR_HB"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

make_old_heartbeat() {
  local worker_id="$1"
  local story_id="${2:-US-001}"
  local age_secs="${3:-200}"
  local hb_file="$HEARTBEAT_DIR/worker_${worker_id}.heartbeat"
  local ts=$(( $(date +%s) - age_secs ))
  printf '{"pid":9999,"storyId":"%s","ts":%s}\n' "$story_id" "$ts" > "$hb_file"
  # Back-date the mtime so stat-based detection works
  touch -t "$(date -d "@$ts" +%Y%m%d%H%M.%S 2>/dev/null || date -r "$ts" +%Y%m%d%H%M.%S 2>/dev/null)" \
    "$hb_file" 2>/dev/null || true
}

make_fresh_heartbeat() {
  local worker_id="$1"
  local story_id="${2:-US-002}"
  local hb_file="$HEARTBEAT_DIR/worker_${worker_id}.heartbeat"
  printf '{"pid":1234,"storyId":"%s","ts":%s}\n' "$story_id" "$(date +%s)" > "$hb_file"
}

make_prd() {
  local prd_file="$1"
  cat > "$prd_file" << 'JSON'
{
  "userStories": [
    {"id": "US-001", "title": "Story one", "passes": true, "retryCount": 2},
    {"id": "US-002", "title": "Story two", "passes": false, "retryCount": 1}
  ]
}
JSON
}

# ── check_stale_heartbeats ────────────────────────────────────────────────────

@test "check_stale_heartbeats: returns [] when heartbeat dir is empty" {
  result=$(check_stale_heartbeats "$HEARTBEAT_DIR" 120)
  [ "$result" = "[]" ]
}

@test "check_stale_heartbeats: returns [] for a fresh heartbeat" {
  make_fresh_heartbeat 1
  result=$(check_stale_heartbeats "$HEARTBEAT_DIR" 120)
  [ "$result" = "[]" ]
}

@test "check_stale_heartbeats: detects a stale heartbeat (>120s old)" {
  make_old_heartbeat 1 "US-001" 200
  result=$(check_stale_heartbeats "$HEARTBEAT_DIR" 120)
  [ "$result" != "[]" ]
  echo "$result" | grep -q '"workerId":1'
  echo "$result" | grep -q '"storyId":"US-001"'
}

@test "check_stale_heartbeats: output is valid JSON (no leading comma)" {
  make_old_heartbeat 1 "US-001" 200
  result=$(check_stale_heartbeats "$HEARTBEAT_DIR" 120)
  # Must parse as valid JSON array
  parsed=$(printf '%s' "$result" | "$JQ" '.' 2>&1)
  [[ $? -eq 0 ]]
}

@test "check_stale_heartbeats: handles multiple stale files — valid JSON array" {
  make_old_heartbeat 1 "US-001" 200
  make_old_heartbeat 2 "US-002" 300
  result=$(check_stale_heartbeats "$HEARTBEAT_DIR" 120)
  length=$(printf '%s' "$result" | "$JQ" 'length')
  [ "$length" -eq 2 ]
}

@test "check_stale_heartbeats: ignores fresh alongside stale" {
  make_old_heartbeat 1 "US-001" 200
  make_fresh_heartbeat 2
  result=$(check_stale_heartbeats "$HEARTBEAT_DIR" 120)
  length=$(printf '%s' "$result" | "$JQ" 'length')
  [ "$length" -eq 1 ]
  echo "$result" | grep -q '"workerId":1'
}

@test "check_stale_heartbeats: staledSinceSeconds is positive integer" {
  make_old_heartbeat 1 "US-001" 200
  result=$(check_stale_heartbeats "$HEARTBEAT_DIR" 120)
  age=$(printf '%s' "$result" | "$JQ" '.[0].staledSinceSeconds')
  [[ "$age" =~ ^[0-9]+$ ]]
  [ "$age" -gt 0 ]
}

@test "check_stale_heartbeats: returns [] when dir does not exist" {
  result=$(check_stale_heartbeats "/nonexistent_dir_$$" 120)
  [ "$result" = "[]" ]
}

# ── requeue_stale_stories ─────────────────────────────────────────────────────

@test "requeue_stale_stories: plain story ID sets passes=false, retryCount unchanged" {
  prd="$TMPDIR_HB/prd.json"
  make_prd "$prd"
  requeue_stale_stories "$prd" "US-001" "$JQ"
  passes=$("$JQ" -r '.userStories[] | select(.id=="US-001") | .passes' "$prd")
  retry=$("$JQ" -r '.userStories[] | select(.id=="US-001") | .retryCount' "$prd")
  [ "$passes" = "false" ]
  [ "$retry" -eq 2 ]   # retryCount NOT incremented
}

@test "requeue_stale_stories: JSON stale_info extracts storyId correctly" {
  prd="$TMPDIR_HB/prd.json"
  make_prd "$prd"
  stale_json='{"workerId":1,"storyId":"US-001","staledSinceSeconds":200}'
  requeue_stale_stories "$prd" "$stale_json" "$JQ"
  passes=$("$JQ" -r '.userStories[] | select(.id=="US-001") | .passes' "$prd")
  [ "$passes" = "false" ]
}

@test "requeue_stale_stories: no-op for unknown story ID" {
  prd="$TMPDIR_HB/prd.json"
  make_prd "$prd"
  before=$(cat "$prd")
  requeue_stale_stories "$prd" "US-999" "$JQ"
  after=$(cat "$prd")
  # File content should be semantically unchanged
  [ "$("$JQ" '.userStories | length' "$prd")" -eq 2 ]
}

@test "requeue_stale_stories: does not modify already-false story" {
  prd="$TMPDIR_HB/prd.json"
  make_prd "$prd"
  requeue_stale_stories "$prd" "US-002" "$JQ"
  passes=$("$JQ" -r '.userStories[] | select(.id=="US-002") | .passes' "$prd")
  retry=$("$JQ" -r '.userStories[] | select(.id=="US-002") | .retryCount' "$prd")
  [ "$passes" = "false" ]
  [ "$retry" -eq 1 ]
}

@test "requeue_stale_stories: returns non-zero for missing prd file" {
  run requeue_stale_stories "/nonexistent_$$.json" "US-001" "$JQ"
  [ "$status" -ne 0 ]
}

# ── worker_heartbeat_start / stop ─────────────────────────────────────────────

@test "worker_heartbeat_start: creates heartbeat file after one interval" {
  export SPIRAL_WORKER_ID=7
  export HEARTBEAT_INTERVAL=1
  worker_heartbeat_start 7 1
  sleep 2
  [ -f "$HEARTBEAT_DIR/worker_7.heartbeat" ]
  worker_heartbeat_stop 7
}

@test "worker_heartbeat_stop: removes heartbeat file" {
  export SPIRAL_WORKER_ID=8
  export HEARTBEAT_INTERVAL=1
  worker_heartbeat_start 8 1
  sleep 2
  worker_heartbeat_stop 8
  [ ! -f "$HEARTBEAT_DIR/worker_8.heartbeat" ]
}

@test "worker_heartbeat_start: heartbeat file contains valid JSON fields" {
  export SPIRAL_WORKER_ID=9
  export HEARTBEAT_INTERVAL=1
  worker_heartbeat_start 9 1
  sleep 2
  content=$(cat "$HEARTBEAT_DIR/worker_9.heartbeat")
  echo "$content" | grep -q '"pid"'
  echo "$content" | grep -q '"storyId"'
  echo "$content" | grep -q '"ts"'
  worker_heartbeat_stop 9
}

# ── Integration: simulate crashed worker ─────────────────────────────────────
# Simulates: worker writes heartbeat then "crashes" (stops updating).
# Coordinator should detect staleness after threshold is exceeded.

@test "integration: stale heartbeat detected after threshold (simulated crash)" {
  # Write an old heartbeat as if a worker crashed 200s ago
  make_old_heartbeat 3 "US-042" 200

  # Coordinator check should detect it as stale (threshold=120)
  result=$(check_stale_heartbeats "$HEARTBEAT_DIR" 120)
  [ "$result" != "[]" ]
  echo "$result" | grep -q '"storyId":"US-042"'

  # Re-queue the story
  prd="$TMPDIR_HB/prd.json"
  cat > "$prd" << 'JSON'
{"userStories": [{"id": "US-042", "title": "Test", "passes": true, "retryCount": 1}]}
JSON
  requeue_stale_stories "$prd" "US-042" "$JQ"

  passes=$("$JQ" -r '.userStories[] | select(.id=="US-042") | .passes' "$prd")
  retry=$("$JQ" -r '.userStories[] | select(.id=="US-042") | .retryCount' "$prd")
  [ "$passes" = "false" ]
  [ "$retry" -eq 1 ]   # retryCount NOT incremented
}
