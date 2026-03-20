#!/usr/bin/env bats
# tests/lib/memory_pool.bats — Unit tests for lib/memory_pool.sh
#
# Run with: bats tests/lib/memory_pool.bats

bats_require_minimum_version 1.7.0
setup() {
  load ../test_helper/common-setup
  _resolve_jq
  export TMPDIR_POOL="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_POOL"

  local SPIRAL_HOME
  SPIRAL_HOME="$(cd "$(dirname "${BATS_TEST_DIRNAME}")/.." && pwd)"

  # Set tier sizes for deterministic tests
  export SPIRAL_POOL_TIER_SMALL=768
  export SPIRAL_POOL_TIER_MEDIUM=1536
  export SPIRAL_POOL_TIER_LARGE=2560
  export SPIRAL_POOL_V8_HEAP_FRACTION=65
  export SPIRAL_POOL_RESERVE_MB=1024

  # Source the library under test
  source "$SPIRAL_HOME/lib/memory_pool.sh"
}

teardown() {
  rm -rf "$TMPDIR_POOL"
}

# ── Helper: write a fake ledger ─────────────────────────────────────────────

write_ledger() {
  local total="${1:-8192}"
  local reserved="${2:-0}"
  local available="${3:-$total}"
  local workers="${4:-"{}"}"
  # Use jq to construct valid JSON (avoids heredoc shell escaping issues)
  echo "$workers" | "$JQ" \
    --argjson t "$total" --argjson r "$reserved" --argjson a "$available" \
    '{total_mb: $t, reserved_mb: $r, available_mb: $a, workers: .}' >"$_POOL_LEDGER"
}

# ── pool_init tests ─────────────────────────────────────────────────────────

@test "pool_init creates ledger file" {
  # Override _pool_free_ram_mb to return a known value
  _pool_free_ram_mb() { echo "8192"; }
  export -f _pool_free_ram_mb

  run pool_init
  assert_success
  assert [ -f "$_POOL_LEDGER" ]

  # Verify ledger content: 8192 - 1024 reserve = 7168
  local total
  total=$("$JQ" -r '.total_mb' "$_POOL_LEDGER")
  assert_equal "$total" "7168"

  local available
  available=$("$JQ" -r '.available_mb' "$_POOL_LEDGER")
  assert_equal "$available" "7168"

  local reserved
  reserved=$("$JQ" -r '.reserved_mb' "$_POOL_LEDGER")
  assert_equal "$reserved" "0"
}

@test "pool_init fails when free RAM is 0" {
  _pool_free_ram_mb() { echo "0"; }
  export -f _pool_free_ram_mb

  run pool_init
  assert_failure
}

@test "pool_init fails when pool too small after reserve" {
  _pool_free_ram_mb() { echo "1200"; }  # 1200 - 1024 = 176 < 768 (TIER_SMALL)
  export -f _pool_free_ram_mb

  run pool_init
  assert_failure
}

# ── pool_reserve tests ──────────────────────────────────────────────────────

@test "pool_reserve succeeds when enough memory" {
  write_ledger 8192 0 8192
  run pool_reserve "1" 768 "small"
  assert_success

  # Check ledger updated
  local reserved
  reserved=$("$JQ" -r '.reserved_mb' "$_POOL_LEDGER")
  assert_equal "$reserved" "768"

  local available
  available=$("$JQ" -r '.available_mb' "$_POOL_LEDGER")
  assert_equal "$available" "7424"

  # Check worker entry
  local worker_reserved
  worker_reserved=$("$JQ" -r '.workers["1"].reserved_mb' "$_POOL_LEDGER")
  assert_equal "$worker_reserved" "768"
}

@test "pool_reserve fails when not enough memory" {
  write_ledger 8192 7800 392
  run pool_reserve "1" 768 "small"
  assert_failure
}

@test "pool_reserve computes V8 heap correctly (65%)" {
  write_ledger 8192 0 8192
  run pool_reserve "1" 1536 "medium"
  assert_success

  # V8 heap = 1536 * 65 / 100 = 998
  local v8_heap
  v8_heap=$("$JQ" -r '.workers["1"].v8_heap_mb' "$_POOL_LEDGER")
  assert_equal "$v8_heap" "998"
}

@test "pool_reserve multiple workers" {
  write_ledger 8192 0 8192
  pool_reserve "1" 768 "small" >/dev/null
  pool_reserve "2" 1536 "medium" >/dev/null
  run pool_reserve "3" 2560 "large"
  assert_success

  local reserved
  reserved=$("$JQ" -r '.reserved_mb' "$_POOL_LEDGER")
  assert_equal "$reserved" "4864"

  local available
  available=$("$JQ" -r '.available_mb' "$_POOL_LEDGER")
  assert_equal "$available" "3328"
}

# ── pool_release tests ──────────────────────────────────────────────────────

@test "pool_release returns memory to pool" {
  write_ledger 8192 768 7424 '{"1":{"reserved_mb":768,"v8_heap_mb":499,"pid":'$$',"tier":"small"}}'
  run pool_release "1"
  assert_success

  local available
  available=$("$JQ" -r '.available_mb' "$_POOL_LEDGER")
  assert_equal "$available" "8192"

  local reserved
  reserved=$("$JQ" -r '.reserved_mb' "$_POOL_LEDGER")
  assert_equal "$reserved" "0"

  # Worker entry removed
  local worker_count
  worker_count=$("$JQ" -r '.workers | length' "$_POOL_LEDGER")
  assert_equal "$worker_count" "0"
}

@test "pool_release is no-op for unknown worker" {
  write_ledger 8192 768 7424 '{"1":{"reserved_mb":768,"v8_heap_mb":499,"pid":'$$',"tier":"small"}}'
  run pool_release "99"
  assert_success

  # Nothing changed
  local reserved
  reserved=$("$JQ" -r '.reserved_mb' "$_POOL_LEDGER")
  assert_equal "$reserved" "768"
}

# ── pool_available tests ────────────────────────────────────────────────────

@test "pool_available returns available MB from ledger" {
  write_ledger 8192 2304 5888
  run pool_available
  assert_output "5888"
}

@test "pool_available returns 0 when no ledger" {
  rm -f "$_POOL_LEDGER"
  run pool_available
  assert_output "0"
}

# ── pool_classify_budget tests ──────────────────────────────────────────────

@test "pool_classify_budget classifies haiku as small" {
  run pool_classify_budget '{"model":"haiku","retryCount":0,"complexityScore":1}'
  assert_output "small 768"
}

@test "pool_classify_budget classifies sonnet as medium" {
  run pool_classify_budget '{"model":"sonnet","retryCount":0,"complexityScore":3}'
  assert_output "medium 1536"
}

@test "pool_classify_budget classifies opus as large" {
  run pool_classify_budget '{"model":"opus","retryCount":0,"complexityScore":5}'
  assert_output "large 2560"
}

@test "pool_classify_budget classifies high retries as large" {
  run pool_classify_budget '{"model":"haiku","retryCount":2,"complexityScore":1}'
  assert_output "large 2560"
}

@test "pool_classify_budget classifies high complexity as large" {
  run pool_classify_budget '{"model":"haiku","retryCount":0,"complexityScore":5}'
  assert_output "large 2560"
}

@test "pool_classify_budget defaults to small for empty" {
  run pool_classify_budget '{}'
  assert_output "small 768"
}

# ── pool_compute_v8_heap tests ──────────────────────────────────────────────

@test "pool_compute_v8_heap computes 65% of 768" {
  run pool_compute_v8_heap 768
  assert_output "499"
}

@test "pool_compute_v8_heap computes 65% of 1536" {
  run pool_compute_v8_heap 1536
  assert_output "998"
}

@test "pool_compute_v8_heap computes 65% of 2560" {
  run pool_compute_v8_heap 2560
  assert_output "1664"
}

# ── pool_reclaim_stale tests ────────────────────────────────────────────────

@test "pool_reclaim_stale reclaims dead PID reservations" {
  # Use a PID that definitely doesn't exist (99999999)
  write_ledger 8192 768 7424 '{"1":{"reserved_mb":768,"v8_heap_mb":499,"pid":99999999,"tier":"small"}}'

  run pool_reclaim_stale
  assert_success

  local available
  available=$("$JQ" -r '.available_mb' "$_POOL_LEDGER")
  assert_equal "$available" "8192"

  local worker_count
  worker_count=$("$JQ" -r '.workers | length' "$_POOL_LEDGER")
  assert_equal "$worker_count" "0"
}

@test "pool_reclaim_stale leaves live PID reservations" {
  # Use our own PID (guaranteed alive)
  write_ledger 8192 768 7424 '{"1":{"reserved_mb":768,"v8_heap_mb":499,"pid":'$$',"tier":"small"}}'

  run pool_reclaim_stale
  assert_success

  # Worker still present
  local worker_count
  worker_count=$("$JQ" -r '.workers | length' "$_POOL_LEDGER")
  assert_equal "$worker_count" "1"
}

@test "pool_reclaim_stale is no-op when no ledger" {
  rm -f "$_POOL_LEDGER"
  run pool_reclaim_stale
  assert_success
}

# ── pool_cleanup tests ──────────────────────────────────────────────────────

@test "pool_cleanup removes ledger and lock" {
  write_ledger 8192 0 8192
  mkdir -p "$_POOL_LOCK" 2>/dev/null || true
  run pool_cleanup
  assert_success
  assert [ ! -f "$_POOL_LEDGER" ]
  assert [ ! -d "$_POOL_LOCK" ]
}

# ── mutex tests ─────────────────────────────────────────────────────────────

@test "_pool_lock creates lock directory" {
  run _pool_lock
  assert_success
  assert [ -d "$_POOL_LOCK" ]
  _pool_unlock
}

@test "_pool_unlock removes lock directory" {
  _pool_lock
  _pool_unlock
  assert [ ! -d "$_POOL_LOCK" ]
}
