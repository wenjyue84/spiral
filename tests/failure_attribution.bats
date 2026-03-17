#!/usr/bin/env bats
# Tests for multi-agent failure attribution (US-233)

bats_require_minimum_version 1.7.0
setup() {
  load test_helper/common-setup
  _resolve_jq
  export TMPDIR="${TMPDIR:-/tmp}"
  CHECKPOINT_FILE="$TMPDIR/checkpoint_$RANDOM.json"
  PYTHON="${PYTHON:-python}"
}

teardown() {
  rm -f "$CHECKPOINT_FILE"
}

@test "record-failure creates failure event" {
  "$PYTHON" lib/failure_attribution.py record-failure \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --story-id "US-001" \
    --error "Build failed" 2>&1 | grep -q "US-001"

  # Verify checkpoint was written
  [[ -f "$CHECKPOINT_FILE" ]]
}

@test "record-failure with resource contention" {
  "$PYTHON" lib/failure_attribution.py record-failure \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --story-id "US-001" \
    --error "Port conflict" \
    --resource "port:8000"

  grep -q "port:8000" "$CHECKPOINT_FILE"
}

@test "register-worker stores resource allocation" {
  "$PYTHON" lib/failure_attribution.py register-worker \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --worktree "/repo/.spiral-workers/worker-1" \
    --branch "spiral-worker-1" \
    --port 8001

  [[ -f "$CHECKPOINT_FILE" ]]
}

@test "cascade detection: worker within 30s with shared resource" {
  # Register two workers sharing worktree parent path
  "$PYTHON" lib/failure_attribution.py register-worker \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --worktree "/repo/.spiral-workers/worker-1" \
    --branch "spiral-worker-1"

  "$PYTHON" lib/failure_attribution.py register-worker \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 2 \
    --worktree "/repo/.spiral-workers/worker-2" \
    --branch "spiral-worker-2"

  # Record first failure (local)
  "$PYTHON" lib/failure_attribution.py record-failure \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --story-id "US-001" \
    --error "Build failed"

  # Sleep briefly, then record second failure (should detect cascade if within window)
  sleep 1

  OUTPUT=$("$PYTHON" lib/failure_attribution.py record-failure \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 2 \
    --story-id "US-002" \
    --error "Runtime error" 2>&1)

  # Check that cascade was detected (both share worktree parent)
  echo "$OUTPUT" | grep -q '"failure_type": "cascade"'
}

@test "local failure has no root_cause_worker_id" {
  "$PYTHON" lib/failure_attribution.py record-failure \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --story-id "US-001" \
    --error "Test failed" 2>&1 | grep -q '"failure_type": "local"'
}

@test "diagnose --format text prints failure chain" {
  # Setup two workers
  "$PYTHON" lib/failure_attribution.py register-worker \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --worktree "/repo/.spiral-workers/worker-1" \
    --branch "spiral-worker-1"

  "$PYTHON" lib/failure_attribution.py register-worker \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 2 \
    --worktree "/repo/.spiral-workers/worker-2" \
    --branch "spiral-worker-2"

  # Record failures
  "$PYTHON" lib/failure_attribution.py record-failure \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --story-id "US-001" \
    --error "Worker 1 failed"

  sleep 1

  "$PYTHON" lib/failure_attribution.py record-failure \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 2 \
    --story-id "US-002" \
    --error "Worker 2 failed"

  # Diagnose
  OUTPUT=$("$PYTHON" lib/failure_attribution.py diagnose \
    --checkpoint "$CHECKPOINT_FILE" \
    --format text 2>&1)

  echo "$OUTPUT" | grep -q "Total failures"
  echo "$OUTPUT" | grep -q "LOCAL\|CASCAD"
}

@test "diagnose --format json returns structured output" {
  "$PYTHON" lib/failure_attribution.py register-worker \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --worktree "/repo/.spiral-workers/worker-1" \
    --branch "spiral-worker-1"

  "$PYTHON" lib/failure_attribution.py record-failure \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --story-id "US-001" \
    --error "Failed"

  OUTPUT=$("$PYTHON" lib/failure_attribution.py diagnose \
    --checkpoint "$CHECKPOINT_FILE" \
    --format json 2>&1)

  # Verify JSON has required fields
  echo "$OUTPUT" | grep -q '"total_failures"'
  echo "$OUTPUT" | grep -q '"cascade_failures"'
  echo "$OUTPUT" | grep -q '"chains"'
}

@test "port conflict detection" {
  # Two workers on same port
  "$PYTHON" lib/failure_attribution.py register-worker \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --worktree "/repo/.spiral-workers/worker-1" \
    --branch "spiral-worker-1" \
    --port 8001

  "$PYTHON" lib/failure_attribution.py register-worker \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 2 \
    --worktree "/repo/.spiral-workers/worker-2" \
    --branch "spiral-worker-2" \
    --port 8001

  "$PYTHON" lib/failure_attribution.py record-failure \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --story-id "US-001" \
    --error "Bind failed"

  sleep 1

  OUTPUT=$("$PYTHON" lib/failure_attribution.py record-failure \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 2 \
    --story-id "US-002" \
    --error "Port in use" 2>&1)

  # Should be cascade due to port conflict
  echo "$OUTPUT" | grep -q '"failure_type": "cascade"'
  echo "$OUTPUT" | grep -q 'port:8001'
}

@test "checkpoint preserves other fields during update" {
  # Create checkpoint with initial state
  echo '{"iter":5,"phase":"I"}' >"$CHECKPOINT_FILE"

  "$PYTHON" lib/failure_attribution.py register-worker \
    --checkpoint "$CHECKPOINT_FILE" \
    --worker-id 1 \
    --worktree "/repo/.spiral-workers/worker-1" \
    --branch "spiral-worker-1"

  # Verify original fields are preserved
  grep -q '"iter": 5' "$CHECKPOINT_FILE" || grep -q '"iter":5' "$CHECKPOINT_FILE"
  grep -q '"phase": "I"' "$CHECKPOINT_FILE" || grep -q '"phase":"I"' "$CHECKPOINT_FILE"
}
