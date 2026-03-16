#!/usr/bin/env bats
# tests/agent_telemetry.bats — Unit tests for emit_agent_telemetry (US-253)
#
# Run with: bats tests/agent_telemetry.bats
#
# Tests verify:
#   - emit_agent_telemetry writes valid JSON with all required fields
#   - Completing Phase R emits a correctly structured telemetry event
#   - Fields: ts, workerId, storyId, fromPhase, toPhase, durationMs, qualityScore, retryCount
#   - Telemetry is queryable by storyId
#   - Log file is created in SPIRAL_SCRATCH_DIR

bats_require_minimum_version 1.7.0

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  _resolve_jq
  export TMPDIR_AT
  TMPDIR_AT="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_AT"
  export NEXT_STORY="US-253"
  export RETRY_NOW=0
  export SPIRAL_WORKER_ID="worker-1"

  source "lib/agent_telemetry.sh"
}

teardown() {
  rm -rf "$TMPDIR_AT"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

telem_file() {
  echo "$TMPDIR_AT/agent-telemetry.jsonl"
}

last_telem_line() {
  tail -1 "$(telem_file)"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "emit_agent_telemetry creates agent-telemetry.jsonl" {
  emit_agent_telemetry "R" "I" 1234 0
  [[ -f "$(telem_file)" ]]
}

@test "emits valid JSON with all required fields" {
  emit_agent_telemetry "R" "I" 1234 0
  local line
  line="$(last_telem_line)"
  echo "$line" | python3 -c "
import json, sys
d = json.load(sys.stdin)
required = ['ts', 'workerId', 'storyId', 'fromPhase', 'toPhase', 'durationMs', 'qualityScore', 'retryCount']
for f in required:
    assert f in d, f'missing field: {f}'
"
}

@test "completing Phase R emits fromPhase=R toPhase=I event" {
  emit_agent_telemetry "R" "I" 500 0
  local line
  line="$(last_telem_line)"
  echo "$line" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['fromPhase'] == 'R', f\"expected fromPhase=R, got {d['fromPhase']}\"
assert d['toPhase']   == 'I', f\"expected toPhase=I, got {d['toPhase']}\"
"
}

@test "storyId matches NEXT_STORY" {
  emit_agent_telemetry "R" "I" 1000 0
  local line
  line="$(last_telem_line)"
  local sid
  sid="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['storyId'])")"
  [[ "$sid" == "$NEXT_STORY" ]]
}

@test "workerId matches SPIRAL_WORKER_ID" {
  emit_agent_telemetry "I" "V" 5000 0
  local line
  line="$(last_telem_line)"
  local wid
  wid="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['workerId'])")"
  [[ "$wid" == "$SPIRAL_WORKER_ID" ]]
}

@test "durationMs is the integer value passed in" {
  emit_agent_telemetry "I" "V" 9876 0
  local line
  line="$(last_telem_line)"
  local dur
  dur="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['durationMs'])")"
  [[ "$dur" == "9876" ]]
}

@test "qualityScore is 1 for V→C (pass) transition" {
  emit_agent_telemetry "V" "C" 100 1
  local line
  line="$(last_telem_line)"
  local qs
  qs="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['qualityScore'])")"
  [[ "$qs" == "1" ]]
}

@test "retryCount matches RETRY_NOW" {
  export RETRY_NOW=2
  emit_agent_telemetry "R" "I" 300 0
  local line
  line="$(last_telem_line)"
  local rc
  rc="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['retryCount'])")"
  [[ "$rc" == "2" ]]
}

@test "telemetry is queryable by storyId" {
  export NEXT_STORY="US-001"
  emit_agent_telemetry "R" "I" 100 0
  export NEXT_STORY="US-002"
  emit_agent_telemetry "R" "I" 200 0
  export NEXT_STORY="US-001"
  emit_agent_telemetry "I" "V" 300 0

  local count
  count=$(python3 - "$(telem_file)" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    rows = [json.loads(l) for l in f if l.strip()]
us001 = [r for r in rows if r['storyId'] == 'US-001']
print(len(us001))
PYEOF
)
  [[ "$count" -eq 2 ]]
}

@test "multiple events are append-only (line count grows)" {
  emit_agent_telemetry "R" "I" 100 0
  emit_agent_telemetry "I" "V" 200 0
  emit_agent_telemetry "V" "C" 50  1
  local count
  count=$(wc -l < "$(telem_file)")
  [[ "$count" -eq 3 ]]
}

@test "ts field is a non-empty ISO-8601 timestamp" {
  emit_agent_telemetry "R" "I" 111 0
  local line ts
  line="$(last_telem_line)"
  ts="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['ts'])")"
  # Must match YYYY-MM-DDTHH:MM:SSZ
  [[ "$ts" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]
}
