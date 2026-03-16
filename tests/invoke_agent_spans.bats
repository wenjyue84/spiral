#!/usr/bin/env bats
# tests/invoke_agent_spans.bats — Tests for invoke_agent OTel spans (US-318)
#
# Run with: bats tests/invoke_agent_spans.bats
#
# Tests verify:
#   - invoke-agent subcommand emits event to spiral_events.jsonl
#   - Event has gen_ai.operation.name=invoke_agent
#   - Event has gen_ai.agent.id (story ID), gen_ai.agent.name (ralph)
#   - Event has gen_ai.conversation.id (SPIRAL_RUN_ID)
#   - Span kind is CLIENT
#   - Events appear with correct status values

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_IA
  TMPDIR_IA="$(mktemp -d)"
  export SCRATCH_DIR="$TMPDIR_IA"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_IA"
  export SPIRAL_RUN_ID="test-run-318"
  export SPIRAL_VERSION="v1.2.3-test"
  export SPIRAL_LOG_LEVEL="INFO"
  PYTHON="${SPIRAL_PYTHON:-python3}"
  OTEL_SCRIPT="lib/otel_spans.py"
}

teardown() {
  rm -rf "$TMPDIR_IA"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

events_file() {
  echo "$TMPDIR_IA/spiral_events.jsonl"
}

last_event() {
  tail -1 "$(events_file)"
}

run_invoke_agent() {
  "$PYTHON" "$OTEL_SCRIPT" invoke-agent "$@"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "invoke-agent creates spiral_events.jsonl entry" {
  run_invoke_agent --story-id "US-042" --worker-id "1" \
    --duration-s 30 --status passed
  [[ -f "$(events_file)" ]]
  local count
  count=$(wc -l < "$(events_file)")
  [[ "$count" -ge 1 ]]
}

@test "event has gen_ai.operation.name=invoke_agent" {
  run_invoke_agent --story-id "US-100" --worker-id "0" \
    --duration-s 10 --status passed
  local line
  line="$(last_event)"
  echo "$line" | "$PYTHON" -c "
import json, sys
d = json.load(sys.stdin)
assert d['gen_ai.operation.name'] == 'invoke_agent', \
    f\"expected invoke_agent, got {d['gen_ai.operation.name']}\"
"
}

@test "event has gen_ai.agent.id=story_id and gen_ai.agent.name=ralph" {
  run_invoke_agent --story-id "US-318" --worker-id "2" \
    --duration-s 5 --status failed
  local line
  line="$(last_event)"
  echo "$line" | "$PYTHON" -c "
import json, sys
d = json.load(sys.stdin)
assert d['gen_ai.agent.id'] == 'US-318', \
    f\"expected US-318, got {d['gen_ai.agent.id']}\"
assert d['gen_ai.agent.name'] == 'ralph', \
    f\"expected ralph, got {d['gen_ai.agent.name']}\"
"
}

@test "event has gen_ai.conversation.id from SPIRAL_RUN_ID" {
  run_invoke_agent --story-id "US-010" --worker-id "0" \
    --duration-s 1 --status passed \
    --conversation-id "$SPIRAL_RUN_ID"
  local line
  line="$(last_event)"
  echo "$line" | "$PYTHON" -c "
import json, sys
d = json.load(sys.stdin)
assert d['gen_ai.conversation.id'] == 'test-run-318', \
    f\"expected test-run-318, got {d['gen_ai.conversation.id']}\"
"
}

@test "event has gen_ai.agent.version from SPIRAL_VERSION" {
  run_invoke_agent --story-id "US-010" --worker-id "0" \
    --duration-s 1 --status passed \
    --agent-version "$SPIRAL_VERSION"
  local line
  line="$(last_event)"
  echo "$line" | "$PYTHON" -c "
import json, sys
d = json.load(sys.stdin)
assert d['gen_ai.agent.version'] == 'v1.2.3-test', \
    f\"expected v1.2.3-test, got {d['gen_ai.agent.version']}\"
"
}

@test "event span.kind is CLIENT" {
  run_invoke_agent --story-id "US-050" --worker-id "1" \
    --duration-s 15 --status passed
  local line
  line="$(last_event)"
  echo "$line" | "$PYTHON" -c "
import json, sys
d = json.load(sys.stdin)
assert d['span.kind'] == 'CLIENT', \
    f\"expected CLIENT, got {d['span.kind']}\"
"
}

@test "event has correct event type" {
  run_invoke_agent --story-id "US-001" --worker-id "0" \
    --duration-s 20 --status passed
  local line
  line="$(last_event)"
  echo "$line" | "$PYTHON" -c "
import json, sys
d = json.load(sys.stdin)
assert d['event'] == 'invoke_agent', \
    f\"expected invoke_agent event, got {d['event']}\"
"
}

@test "event includes worker_id and duration_s" {
  run_invoke_agent --story-id "US-099" --worker-id "3" \
    --duration-s 42 --status failed
  local line
  line="$(last_event)"
  echo "$line" | "$PYTHON" -c "
import json, sys
d = json.load(sys.stdin)
assert d['worker_id'] == '3', f\"expected worker 3, got {d['worker_id']}\"
assert d['duration_s'] == 42.0, f\"expected 42.0, got {d['duration_s']}\"
assert d['status'] == 'failed', f\"expected failed, got {d['status']}\"
"
}

@test "timeout status is recorded correctly" {
  run_invoke_agent --story-id "US-200" --worker-id "1" \
    --duration-s 600 --status timeout
  local line
  line="$(last_event)"
  echo "$line" | "$PYTHON" -c "
import json, sys
d = json.load(sys.stdin)
assert d['status'] == 'timeout', f\"expected timeout, got {d['status']}\"
"
}

@test "TRACEPARENT trace_id/span_id injected when set" {
  export TRACEPARENT="00-abcdef0123456789abcdef0123456789-fedcba9876543210-01"
  run_invoke_agent --story-id "US-300" --worker-id "0" \
    --duration-s 5 --status passed
  local line
  line="$(last_event)"
  echo "$line" | "$PYTHON" -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('trace_id') == 'abcdef0123456789abcdef0123456789', \
    f\"expected trace_id, got {d.get('trace_id')}\"
assert d.get('span_id') == 'fedcba9876543210', \
    f\"expected span_id, got {d.get('span_id')}\"
"
  unset TRACEPARENT
}

@test "invoke-agent includes cache token attributes when provided" {
  run_invoke_agent --story-id "US-341" --worker-id "0" \
    --duration-s 25 --status passed \
    --cache-read-tokens 15000 --cache-creation-tokens 3000
  local line
  line="$(last_event)"
  echo "$line" | "$PYTHON" -c "
import json, sys
d = json.load(sys.stdin)
assert d['gen_ai.usage.cache_read.input_tokens'] == 15000, \
    f\"expected 15000, got {d['gen_ai.usage.cache_read.input_tokens']}\"
assert d['gen_ai.usage.cache_creation.input_tokens'] == 3000, \
    f\"expected 3000, got {d['gen_ai.usage.cache_creation.input_tokens']}\"
"
}

@test "invoke-agent cache tokens default to 0 when omitted" {
  run_invoke_agent --story-id "US-341B" --worker-id "1" \
    --duration-s 10 --status passed
  local line
  line="$(last_event)"
  echo "$line" | "$PYTHON" -c "
import json, sys
d = json.load(sys.stdin)
assert d['gen_ai.usage.cache_read.input_tokens'] == 0, \
    f\"expected 0, got {d['gen_ai.usage.cache_read.input_tokens']}\"
assert d['gen_ai.usage.cache_creation.input_tokens'] == 0, \
    f\"expected 0, got {d['gen_ai.usage.cache_creation.input_tokens']}\"
"
}

@test "multiple invoke-agent events append correctly" {
  run_invoke_agent --story-id "US-A" --worker-id "1" \
    --duration-s 10 --status passed
  run_invoke_agent --story-id "US-B" --worker-id "2" \
    --duration-s 20 --status failed
  run_invoke_agent --story-id "US-C" --worker-id "3" \
    --duration-s 30 --status timeout
  local count
  count=$(wc -l < "$(events_file)")
  [[ "$count" -eq 3 ]]
  # Verify each has a different story ID
  local ids
  ids=$("$PYTHON" -c "
import json, sys
with open(sys.argv[1]) as f:
    ids = [json.loads(l)['gen_ai.agent.id'] for l in f if l.strip()]
print(' '.join(ids))
" "$(events_file)")
  [[ "$ids" == "US-A US-B US-C" ]]
}
