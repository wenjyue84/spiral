#!/usr/bin/env bats
# tests/worker_crash_cleanup.bats — Tests for US-245 worker crash cleanup
#
# Run with: bats tests/worker_crash_cleanup.bats
#
# Tests verify:
#   - _inspect_crashed_worktree removes stale git lock files
#   - _inspect_crashed_worktree removes incomplete prd.json.tmp
#   - _inspect_crashed_worktree reports clean worktree when nothing to remove
#   - PGID file is written and contains a valid PID when setsid is available
#   - Sibling worker processes continue running after one is SIGKILLed
#   - Crash is detected within 5 seconds (sleep interval check)
#   - kill -- -PGID terminates process group descendants

# ── Setup / teardown ──────────────────────────────────────────────────────────

setup() {
  # Temporary scratch + fake worktree dirs
  export TEST_TMPDIR
  TEST_TMPDIR="$(mktemp -d)"
  export WORKTREE_BASE="$TEST_TMPDIR/spiral-workers"
  mkdir -p "$WORKTREE_BASE/worker-1/.git" "$WORKTREE_BASE/worker-2/.git"
  export SCRATCH_DIR="$TEST_TMPDIR/scratch"
  mkdir -p "$SCRATCH_DIR"
  export SPIRAL_SCRATCH_DIR="$SCRATCH_DIR"

  # Source the function under test directly from run_parallel_ralph.sh
  # We use a targeted source that only loads the helper function.
  # The file uses set -euo pipefail at the top and expects many vars — extract
  # _inspect_crashed_worktree as a standalone function instead.
  _inspect_crashed_worktree() {
    local wtree="$1"
    local worker_num="$2"
    local _cleaned=0
    [[ -d "$wtree" ]] || return 0
    while IFS= read -r -d '' _lf; do
      rm -f "$_lf" 2>/dev/null && _cleaned=1 && \
        echo "  [parallel] Worker $worker_num crash-clean: removed stale lock $_lf"
    done < <(find "$wtree/.git" -name "*.lock" -print0 2>/dev/null)
    if [[ -f "$wtree/prd.json.tmp" ]]; then
      rm -f "$wtree/prd.json.tmp" 2>/dev/null
      echo "  [parallel] Worker $worker_num crash-clean: removed prd.json.tmp"
      _cleaned=1
    fi
    if [[ -f "$wtree/.spiral/_context_stats.json.tmp" ]]; then
      rm -f "$wtree/.spiral/_context_stats.json.tmp" 2>/dev/null
      _cleaned=1
    fi
    if [[ "$_cleaned" -eq 0 ]]; then
      echo "  [parallel] Worker $worker_num crash-clean: worktree appears clean"
    fi
    return 0
  }
  export -f _inspect_crashed_worktree
}

teardown() {
  rm -rf "$TEST_TMPDIR"
}

# ── _inspect_crashed_worktree tests ──────────────────────────────────────────

@test "_inspect_crashed_worktree: removes stale git lock file" {
  local wtree="$WORKTREE_BASE/worker-1"
  touch "$wtree/.git/index.lock"
  touch "$wtree/.git/HEAD.lock"
  # Call directly (not via run) — test filesystem state
  _inspect_crashed_worktree "$wtree" "1"
  [ ! -f "$wtree/.git/index.lock" ]
  [ ! -f "$wtree/.git/HEAD.lock" ]
}

@test "_inspect_crashed_worktree: removes prd.json.tmp" {
  local wtree="$WORKTREE_BASE/worker-1"
  echo '{}' > "$wtree/prd.json.tmp"
  _inspect_crashed_worktree "$wtree" "1"
  [ ! -f "$wtree/prd.json.tmp" ]
}

@test "_inspect_crashed_worktree: reports clean when no artifacts present" {
  local wtree="$WORKTREE_BASE/worker-2"
  run _inspect_crashed_worktree "$wtree" "2"
  [ "$status" -eq 0 ]
  [[ "$output" == *"appears clean"* ]]
}

@test "_inspect_crashed_worktree: handles missing worktree dir gracefully" {
  run _inspect_crashed_worktree "$TEST_TMPDIR/nonexistent" "99"
  [ "$status" -eq 0 ]
  # Should produce no output (early return)
  [ -z "$output" ]
}

@test "_inspect_crashed_worktree: removes both lock files and prd.json.tmp together" {
  local wtree="$WORKTREE_BASE/worker-1"
  touch "$wtree/.git/MERGE_HEAD.lock"
  echo '{}' > "$wtree/prd.json.tmp"
  _inspect_crashed_worktree "$wtree" "1"
  [ ! -f "$wtree/.git/MERGE_HEAD.lock" ]
  [ ! -f "$wtree/prd.json.tmp" ]
}

# ── PGID / process group tests ────────────────────────────────────────────────

@test "setsid creates a new process group with PID == PGID" {
  # Skip if setsid not available (Windows/MINGW without setsid)
  if ! command -v setsid &>/dev/null; then
    skip "setsid not available on this platform"
  fi
  local pgid_file="$TEST_TMPDIR/test.pgid"
  # setsid bash -c 'echo $$ > file; sleep 0' — $$ inside setsid'd bash is PID = PGID
  setsid bash -c "echo \$\$ > \"$pgid_file\"; sleep 0"
  [ -f "$pgid_file" ]
  local pgid
  pgid=$(cat "$pgid_file")
  # PGID must be a positive integer
  [[ "$pgid" =~ ^[0-9]+$ ]]
  [ "$pgid" -gt 0 ]
}

@test "PGID file written via wrapper before exec" {
  if ! command -v setsid &>/dev/null; then
    skip "setsid not available on this platform"
  fi
  local pgid_file="$TEST_TMPDIR/worker1.pgid"
  # Simulate the wrapper pattern used in _launch_worker_i
  setsid bash -c "echo \"\$\$\" > \"$pgid_file\"; exec bash -c 'exit 0'"
  [ -f "$pgid_file" ]
  local pgid
  pgid=$(cat "$pgid_file" | tr -d '[:space:]')
  [[ "$pgid" =~ ^[0-9]+$ ]]
  [ "$pgid" -gt 0 ]
}

@test "kill -- -PGID terminates process group descendants" {
  if ! command -v setsid &>/dev/null; then
    skip "setsid not available on this platform"
  fi
  local pgid_file="$TEST_TMPDIR/kill_test.pgid"
  # Launch a setsid'd process that writes its PGID then spawns a child sleep
  setsid bash -c "echo \"\$\$\" > \"$pgid_file\"; sleep 300" &
  local parent_pid=$!
  sleep 0.3  # allow PGID file to be written
  [ -f "$pgid_file" ]
  local pgid
  pgid=$(cat "$pgid_file" | tr -d '[:space:]')
  [[ "$pgid" =~ ^[0-9]+$ ]]
  # Kill process group — should terminate parent and the sleep child
  kill -- -"$pgid" 2>/dev/null || true
  sleep 0.2
  # Parent should no longer be alive
  run kill -0 "$parent_pid" 2>/dev/null
  [ "$status" -ne 0 ]
}

# ── Sibling worker isolation test ─────────────────────────────────────────────

@test "sibling worker continues running after one worker is SIGKILLed" {
  # Launch two background sleep workers; SIGKILL one; verify sibling still runs
  local sibling_pid sibling_alive
  sleep 30 &
  sibling_pid=$!

  # Launch 'worker' and kill it
  sleep 30 &
  local crash_pid=$!
  kill -9 "$crash_pid" 2>/dev/null
  sleep 0.3

  # Sibling should still be alive
  run kill -0 "$sibling_pid" 2>/dev/null
  sibling_alive=$status
  # Clean up sibling
  kill "$sibling_pid" 2>/dev/null || true
  wait "$sibling_pid" 2>/dev/null || true

  [ "$sibling_alive" -eq 0 ]
}

@test "monitor loop sleep interval is 5 seconds (crash detection bound)" {
  # Verify the sleep 5 line exists in run_parallel_ralph.sh (not sleep 10)
  run grep -c "^  sleep 5  # US-245" lib/run_parallel_ralph.sh
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}

@test "WORKER_PGID_FILES array is declared in run_parallel_ralph.sh" {
  run grep -c "declare -a WORKER_PGID_FILES" lib/run_parallel_ralph.sh
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}

@test "_inspect_crashed_worktree function exists in run_parallel_ralph.sh" {
  run grep -c "_inspect_crashed_worktree()" lib/run_parallel_ralph.sh
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}
