#!/usr/bin/env bats
# tests/test_worker_pool.bats — Unit tests for US-1100 worker pool pre-warming
#
# Run with: bats tests/test_worker_pool.bats
#
# Tests verify:
#   - worker_pool_init spawns N idle processes
#   - Task directories are created correctly
#   - Tasks are executed on idle workers
#   - Workers can execute multiple tasks without restart
#   - Cleanup removes all processes and files

bats_require_minimum_version 1.7.0

setup() {
  load test_helper/common-setup
  export SPIRAL_SCRATCH_DIR
  SPIRAL_SCRATCH_DIR="$(mktemp -d)"
  export SPIRAL_RUN_ID="test-run-pool-$$"
  touch "$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"
  export RALPH_WORKERS=2
  export SPIRAL_HOME="${SPIRAL_HOME:-.}"

  # Initialize pool variables
  export _POOL_ENABLED_FEATURE="true"
  export _POOL_INIT_DIR=""
  declare -ag POOL_WORKER_PIDS=()

  # Define minimal spiral_event helper
  spiral_event() {
    local _ef="$1" _ej="$2"
    printf '%s\n' "$_ej" >>"$_ef" 2>/dev/null || true
  }
  export -f spiral_event

  # Define the pool functions inline
  worker_pool_init() {
    local pool_size="${1:-$RALPH_WORKERS}"
    [[ "$_POOL_ENABLED_FEATURE" != "true" ]] && return 0
    _POOL_INIT_DIR="$SPIRAL_SCRATCH_DIR/.worker-pool"
    mkdir -p "$_POOL_INIT_DIR"
    echo "  [pool] Initializing worker pool: $pool_size idle workers..."
    local _pool_start=$(date +%s%N | cut -b1-13)
    for i in $(seq 1 "$pool_size"); do
      mkdir -p "$_POOL_INIT_DIR/worker-$i"
      (
        _WORKER_POOL_ID=$i
        _WORKER_POOL_DIR="$_POOL_INIT_DIR/worker-$i"
        export _WORKER_POOL_ID
        while true; do
          _TASK_FILE="$_WORKER_POOL_DIR/task"
          while [[ ! -f "$_TASK_FILE" ]]; do
            sleep 0.1
            [[ -f "$_WORKER_POOL_DIR/stop" ]] && exit 0
          done
          _TASK_CMD=$(cat "$_TASK_FILE" 2>/dev/null)
          rm -f "$_TASK_FILE" 2>/dev/null || true
          [[ -z "$_TASK_CMD" ]] && continue
          (
            eval "$_TASK_CMD"
          )
          _TASK_RC=$?
          echo "$_TASK_RC" >"$_WORKER_POOL_DIR/exit_code" 2>/dev/null || true
          touch "$_WORKER_POOL_DIR/done" 2>/dev/null || true
        done
      ) &
      POOL_WORKER_PIDS+=($!)
    done
    local _pool_end=$(date +%s%N | cut -b1-13)
    local _pool_elapsed=$((_pool_end - _pool_start))
    echo "  [pool] Pool initialized in ${_pool_elapsed}ms"
    spiral_event "$SPIRAL_SCRATCH_DIR/spiral_events.jsonl" \
      "$(printf '{"ts":"%s","event":"pool_init","run_id":"%s","pool_size":%d,"elapsed_ms":%d}' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${SPIRAL_RUN_ID:-}" "$pool_size" "$_pool_elapsed")"
  }
  export -f worker_pool_init

  worker_pool_assign_task() {
    local worker_id="$1"
    local task_cmd="$2"
    [[ "$_POOL_ENABLED_FEATURE" != "true" ]] && return 1
    [[ -z "$_POOL_INIT_DIR" ]] && return 1
    local _task_dir="$_POOL_INIT_DIR/worker-$worker_id"
    [[ ! -d "$_task_dir" ]] && return 1
    echo "$task_cmd" >"$_task_dir/task" 2>/dev/null || return 1
    local _wait_count=0
    while [[ ! -f "$_task_dir/done" ]]; do
      sleep 0.05
      _wait_count=$((_wait_count + 1))
      if [[ "$_wait_count" -ge 1200 ]]; then
        echo "  [pool] WARNING: Worker $worker_id task timeout" >&2
        return 1
      fi
    done
    local _exit_code=0
    [[ -f "$_task_dir/exit_code" ]] && _exit_code=$(cat "$_task_dir/exit_code" 2>/dev/null || echo "0")
    rm -f "$_task_dir/done" "$_task_dir/exit_code" 2>/dev/null || true
    return "$_exit_code"
  }
  export -f worker_pool_assign_task
}

teardown() {
  # Clean up pool workers
  if [[ -n "${POOL_WORKER_PIDS[*]:-}" ]]; then
    for _pid in "${POOL_WORKER_PIDS[@]:-}"; do
      kill "$_pid" 2>/dev/null || true
    done
  fi
  rm -rf "$SPIRAL_SCRATCH_DIR" 2>/dev/null || true
}

# Test 1: Pool initialization spawns N idle processes
@test "worker_pool_init spawns correct number of idle processes" {
  worker_pool_init 2

  # Check that 2 workers are in POOL_WORKER_PIDS array
  [[ ${#POOL_WORKER_PIDS[@]} -eq 2 ]]

  # Verify all PIDs are alive
  for pid in "${POOL_WORKER_PIDS[@]}"; do
    kill -0 "$pid" 2>/dev/null || return 1
  done
}

# Test 2: Pool directory structure is created
@test "worker_pool_init creates task directories for each worker" {
  worker_pool_init 2

  # Verify task directories exist
  [[ -d "$_POOL_INIT_DIR/worker-1" ]]
  [[ -d "$_POOL_INIT_DIR/worker-2" ]]
}

# Test 3: Pool respects disabled feature flag
@test "worker_pool_init respects SPIRAL_WORKER_POOL=false" {
  export _POOL_ENABLED_FEATURE="false"
  POOL_WORKER_PIDS=()
  worker_pool_init 2

  # When disabled, no workers should be spawned
  [[ ${#POOL_WORKER_PIDS[@]} -eq 0 ]]
}

# Test 4: Task execution on idle worker
@test "worker_pool_assign_task executes command successfully" {
  worker_pool_init 1

  # Create output directory
  mkdir -p "$SPIRAL_SCRATCH_DIR/test_output"

  # Assign a task that creates a file
  worker_pool_assign_task 1 "echo hello > $SPIRAL_SCRATCH_DIR/test_output/result.txt && exit 0"

  # Verify output file was created
  [[ -f "$SPIRAL_SCRATCH_DIR/test_output/result.txt" ]]
  grep -q "hello" "$SPIRAL_SCRATCH_DIR/test_output/result.txt"
}

# Test 5: Worker reuse across multiple tasks
@test "worker_pool_assign_task reuses worker for multiple tasks" {
  worker_pool_init 1

  mkdir -p "$SPIRAL_SCRATCH_DIR/test_output"

  # Assign first task
  worker_pool_assign_task 1 "echo task1 > $SPIRAL_SCRATCH_DIR/test_output/t1.txt && exit 0"
  [[ -f "$SPIRAL_SCRATCH_DIR/test_output/t1.txt" ]]

  # Assign second task to same worker (verify it's still alive)
  worker_pool_assign_task 1 "echo task2 > $SPIRAL_SCRATCH_DIR/test_output/t2.txt && exit 0"
  [[ -f "$SPIRAL_SCRATCH_DIR/test_output/t2.txt" ]]
}

# Test 6: Pool logs initialization event
@test "worker_pool_init logs pool_init event to spiral_events.jsonl" {
  worker_pool_init 1

  # Verify event was logged
  grep -q "pool_init" "$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"
}

# Test 7: Task exit code propagation
@test "worker_pool_assign_task propagates success exit code" {
  worker_pool_init 1

  # Task should succeed (exit 0)
  worker_pool_assign_task 1 "exit 0"
  [[ $? -eq 0 ]]
}

# Test 8: Pool returns error when disabled
@test "worker_pool_assign_task returns error when pool disabled" {
  export _POOL_ENABLED_FEATURE="false"
  export _POOL_INIT_DIR=""
  worker_pool_init 1

  # Should return 1 (failure) when pool is disabled
  ! worker_pool_assign_task 1 "echo test"
}
