#!/usr/bin/env bats
# tests/spiral_events.bats — Unit tests for lib/spiral_events.sh (US-117, US-130)
#
# Run with: bats tests/spiral_events.bats
# Install bats: https://github.com/bats-core/bats-core
#
# Tests verify:
#   - log_spiral_event emits valid JSON with required base fields
#   - run_id appears in every log line
#   - trace_id and span_id are injected when TRACEPARENT is set
#   - trace_id and span_id are omitted when TRACEPARENT is not set
#   - Extra JSON fields are preserved alongside trace fields
#   - Correct extraction from standard W3C traceparent format
#   - level field matches SPIRAL_LOG_LEVEL (US-130)
#   - level field defaults to INFO when SPIRAL_LOG_LEVEL is unset (US-130)

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_SE="$(mktemp -d)"
  export SCRATCH_DIR="$TMPDIR_SE"
  export SPIRAL_RUN_ID="test-run-$(date +%s)"
  export SPIRAL_EVENT_LOG_MAX_LINES=10000

  # Unset TRACEPARENT so each test starts clean
  unset TRACEPARENT
  # Reset SPIRAL_LOG_LEVEL so each test starts with the default
  unset SPIRAL_LOG_LEVEL

  source "lib/spiral_events.sh"
}

teardown() {
  rm -rf "$TMPDIR_SE"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

last_log_line() {
  tail -1 "$SCRATCH_DIR/spiral_events.jsonl"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "emits valid JSON with ts, event, and run_id fields" {
  log_spiral_event "test.event"
  local line
  line="$(last_log_line)"
  # Should parse as JSON (python3 -c will fail if invalid)
  echo "$line" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'ts' in d and 'event' in d and 'run_id' in d"
}

@test "run_id matches SPIRAL_RUN_ID in every log line" {
  log_spiral_event "run_id.check"
  local line run_id
  line="$(last_log_line)"
  run_id="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['run_id'])")"
  [[ "$run_id" == "$SPIRAL_RUN_ID" ]]
}

@test "trace_id and span_id are injected when TRACEPARENT is set" {
  export TRACEPARENT="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
  log_spiral_event "trace.inject"
  local line trace_id span_id
  line="$(last_log_line)"
  trace_id="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['trace_id'])")"
  span_id="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['span_id'])")"
  [[ "$trace_id" == "4bf92f3577b34da6a3ce929d0e0e4736" ]]
  [[ "$span_id" == "00f067aa0ba902b7" ]]
}

@test "trace_id and span_id are absent when TRACEPARENT is not set" {
  unset TRACEPARENT
  log_spiral_event "no.trace"
  local line
  line="$(last_log_line)"
  # Neither field should be present
  echo "$line" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert 'trace_id' not in d, 'trace_id should not appear without TRACEPARENT'
assert 'span_id' not in d, 'span_id should not appear without TRACEPARENT'
"
}

@test "extra JSON fields coexist with trace_id and span_id" {
  export TRACEPARENT="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
  log_spiral_event "extra.fields" '"phase":"R","iteration":3'
  local line
  line="$(last_log_line)"
  echo "$line" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('phase') == 'R', f'phase missing: {d}'
assert d.get('iteration') == 3, f'iteration missing: {d}'
assert d.get('trace_id') == '4bf92f3577b34da6a3ce929d0e0e4736', f'trace_id wrong: {d}'
assert d.get('span_id') == '00f067aa0ba902b7', f'span_id wrong: {d}'
"
}

@test "event name is recorded correctly in log line" {
  log_spiral_event "phase.R.start"
  local line event
  line="$(last_log_line)"
  event="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['event'])")"
  [[ "$event" == "phase.R.start" ]]
}

@test "multiple events each contain run_id" {
  log_spiral_event "event.one"
  log_spiral_event "event.two"
  log_spiral_event "event.three"
  local log_path="$SCRATCH_DIR/spiral_events.jsonl"
  local count
  count=$(python3 - "$log_path" <<'PYEOF'
import json, sys
count = 0
with open(sys.argv[1]) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if 'run_id' in d and d['run_id']:
            count += 1
print(count)
PYEOF
)
  [[ "$count" -eq 3 ]]
}

# ── US-130: level field in spiral_events.jsonl ───────────────────────────────

@test "level field defaults to INFO when SPIRAL_LOG_LEVEL is unset" {
  unset SPIRAL_LOG_LEVEL
  log_spiral_event "log_level.default"
  local line level
  line="$(last_log_line)"
  level="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['level'])")"
  [[ "$level" == "INFO" ]]
}

@test "level field reflects SPIRAL_LOG_LEVEL=DEBUG" {
  export SPIRAL_LOG_LEVEL="DEBUG"
  log_spiral_event "log_level.debug"
  local line level
  line="$(last_log_line)"
  level="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['level'])")"
  [[ "$level" == "DEBUG" ]]
}

@test "level field reflects SPIRAL_LOG_LEVEL=WARN" {
  export SPIRAL_LOG_LEVEL="WARN"
  log_spiral_event "log_level.warn"
  local line level
  line="$(last_log_line)"
  level="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['level'])")"
  [[ "$level" == "WARN" ]]
}

@test "level field reflects SPIRAL_LOG_LEVEL=ERROR" {
  export SPIRAL_LOG_LEVEL="ERROR"
  log_spiral_event "log_level.error"
  local line level
  line="$(last_log_line)"
  level="$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['level'])")"
  [[ "$level" == "ERROR" ]]
}

@test "level field is present alongside extra JSON fields" {
  export SPIRAL_LOG_LEVEL="INFO"
  log_spiral_event "log_level.extra" '"phase":"R","iteration":1'
  local line
  line="$(last_log_line)"
  echo "$line" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert 'level' in d, 'level field missing'
assert d['level'] == 'INFO', f\"expected INFO, got {d['level']}\"
assert d['phase'] == 'R', 'extra phase field missing'
assert d['iteration'] == 1, 'extra iteration field missing'
"
}

@test "level field is present when TRACEPARENT is also set" {
  export TRACEPARENT="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
  export SPIRAL_LOG_LEVEL="INFO"
  log_spiral_event "log_level.trace"
  local line
  line="$(last_log_line)"
  echo "$line" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert 'level' in d, 'level field missing with TRACEPARENT'
assert 'trace_id' in d, 'trace_id missing'
assert d['level'] == 'INFO'
"
}
