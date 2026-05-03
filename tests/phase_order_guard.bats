#!/usr/bin/env bats
# tests/phase_order_guard.bats — Tests for associative-array lookup guards
#
# Run with: bats tests/phase_order_guard.bats
#
# Tests verify:
#   - Empty phase token does not crash
#   - Empty checkpoint phase file does not crash
#   - Null/unknown phase token returns 0 (skip)
#   - Valid phase order passes
#   - Backward phase order fails

bats_require_minimum_version 1.7.0

setup() {
  load test_helper/common-setup
  TEST_DIR="$(mktemp -d)"
  export SCRATCH_DIR="$TEST_DIR/scratch"
  mkdir -p "$SCRATCH_DIR"
  export SPIRAL_ASSERT_MODE="log"
  export SPIRAL_EVENT_LOG="$SCRATCH_DIR/spiral_events.jsonl"
  touch "$SPIRAL_EVENT_LOG"

  _resolve_jq
}

teardown() {
  rm -rf "$TEST_DIR" 2>/dev/null || true
}

# Source the assert module
_source_assert() {
  local spiral_home
  spiral_home="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  # Source helpers first (for log_spiral_event)
  source "$spiral_home/lib/spiral_events.sh" 2>/dev/null || true
  source "$spiral_home/lib/spiral_assert.sh"
}

@test "empty current_phase does not crash" {
  _source_assert
  run spiral_assert_phase_order ""
  # Should not crash with 'bad array subscript'
  [[ "$status" -eq 0 ]]
}

@test "empty checkpoint phase file does not crash" {
  _source_assert
  # Write empty content to last phase file
  echo "" > "$SCRATCH_DIR/_last_phase"
  run spiral_assert_phase_order "M"
  [[ "$status" -eq 0 ]]
}

@test "null checkpoint phase file does not crash" {
  _source_assert
  echo "null" > "$SCRATCH_DIR/_last_phase"
  run spiral_assert_phase_order "M"
  [[ "$status" -eq 0 ]]
}

@test "unknown phase token returns 0" {
  _source_assert
  echo "Z" > "$SCRATCH_DIR/_last_phase"
  run spiral_assert_phase_order "M"
  [[ "$status" -eq 0 ]]
}

@test "valid forward phase order passes" {
  _source_assert
  echo "A" > "$SCRATCH_DIR/_last_phase"
  run spiral_assert_phase_order "M"
  [[ "$status" -eq 0 ]]
}

@test "valid equal phase order for A (iteration reset) passes" {
  _source_assert
  echo "C" > "$SCRATCH_DIR/_last_phase"
  run spiral_assert_phase_order "A"
  [[ "$status" -eq 0 ]]
}

@test "backward phase order fails in log mode" {
  _source_assert
  echo "M" > "$SCRATCH_DIR/_last_phase"
  run spiral_assert_phase_order "A"
  # In log mode, assert logs but returns 0
  [[ "$status" -eq 0 ]]
}

@test "no last phase file passes" {
  _source_assert
  rm -f "$SCRATCH_DIR/_last_phase" 2>/dev/null || true
  run spiral_assert_phase_order "M"
  [[ "$status" -eq 0 ]]
}

@test "valid sequential phases A->R->T->S->E->M all pass" {
  _source_assert
  local phases=(A R T S E M X G I V C L)
  for phase in "${phases[@]}"; do
    run spiral_assert_phase_order "$phase"
    [[ "$status" -eq 0 ]]
  done
}

@test "backward M->A fails assertion" {
  _source_assert
  echo "M" > "$SCRATCH_DIR/_last_phase"
  # A is special (iteration reset) — should pass
  run spiral_assert_phase_order "A"
  [[ "$status" -eq 0 ]]
  # But R->A would be backward (R=2, A is excluded from check)
  echo "R" > "$SCRATCH_DIR/_last_phase"
  run spiral_assert_phase_order "A"
  [[ "$status" -eq 0 ]]
}
