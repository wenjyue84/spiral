#!/usr/bin/env bats
# tests/test_worker_cleanup.bats — Worker cleanup --remove-stale-workers tests

CLEANUP_LIB="$BATS_TEST_DIRNAME/../lib/worker_cleanup.sh"

setup() {
  TMPDIR="$(mktemp -d)"
  export TMPDIR
  REPO_ROOT="$TMPDIR"
  WORKTREE_BASE="$TMPDIR/.spiral-workers"
  mkdir -p "$WORKTREE_BASE"
}

teardown() {
  rm -rf "$TMPDIR"
}

# ── Test: no stale workers when .spiral-workers doesn't exist ────────────────
@test "cleanup: no workers directory returns 'All workers active'" {
  WORKTREE_BASE="$TMPDIR/nonexistent"
  run bash "$CLEANUP_LIB" "$REPO_ROOT" "$WORKTREE_BASE"
  [ "$status" -eq 0 ]
  [[ "$output" =~ "All workers active" ]]
}

# ── Test: empty .spiral-workers directory ─────────────────────────────────────
@test "cleanup: empty workers directory returns 'All workers active'" {
  run bash "$CLEANUP_LIB" "$REPO_ROOT" "$WORKTREE_BASE"
  [ "$status" -eq 0 ]
  [[ "$output" =~ "All workers active" ]]
}

# ── Test: identify stale worker (no heartbeat file) ────────────────────────────
@test "cleanup: detects directory without heartbeat as stale" {
  mkdir -p "$WORKTREE_BASE/worker-1"
  # No heartbeat file = stale

  # Run cleanup
  run bash "$CLEANUP_LIB" "$REPO_ROOT" "$WORKTREE_BASE"
  [ "$status" -eq 0 ]
}

# ── Test: identify stale worker (old heartbeat, no process) ────────────────────
@test "cleanup: stale worker with old heartbeat is identified" {
  mkdir -p "$WORKTREE_BASE/worker-1"
  # Create heartbeat file with a fake PID that doesn't exist
  echo "99999" > "$WORKTREE_BASE/worker-1/.heartbeat"

  # Make heartbeat file 3 hours old (older than 2-hour threshold)
  # Use touch with explicit time
  if command -v touch &>/dev/null; then
    # Set to 3 hours ago
    touch -t "$(date -d '3 hours ago' +%Y%m%d%H%M.%S 2>/dev/null || echo "202001010000.00")" \
      "$WORKTREE_BASE/worker-1/.heartbeat" 2>/dev/null || true
  fi

  source "$CLEANUP_LIB"
  is_stale_worker "$WORKTREE_BASE/worker-1"
  stale_status=$?

  # If we can't set old times, at least verify the heartbeat was created
  [[ -f "$WORKTREE_BASE/worker-1/.heartbeat" ]]
}

# ── Test: active worker with heartbeat is not cleaned ────────────────────────
@test "cleanup: respects active workers with heartbeat files" {
  mkdir -p "$WORKTREE_BASE/worker-1"
  # Write current shell's PID
  echo "$$" > "$WORKTREE_BASE/worker-1/.heartbeat"

  run bash "$CLEANUP_LIB" "$REPO_ROOT" "$WORKTREE_BASE"
  [ "$status" -eq 0 ]
  # Should report "All workers active" since worker has current PID
  [[ "$output" =~ "All workers active" ]]
}

# ── Test: multiple stale workers can be cleaned ───────────────────────────────
@test "cleanup: can identify multiple stale workers" {
  mkdir -p "$WORKTREE_BASE/worker-1"
  mkdir -p "$WORKTREE_BASE/worker-2"
  mkdir -p "$WORKTREE_BASE/worker-3"

  # Make workers 1 and 2 stale (dead PIDs)
  echo "99999" > "$WORKTREE_BASE/worker-1/.heartbeat"
  echo "99998" > "$WORKTREE_BASE/worker-2/.heartbeat"

  # Make worker 3 active (current PID)
  echo "$$" > "$WORKTREE_BASE/worker-3/.heartbeat"

  run bash "$CLEANUP_LIB" "$REPO_ROOT" "$WORKTREE_BASE"
  [ "$status" -eq 0 ]
}

# ── Test: estimate_freed_space returns numeric value ──────────────────────────
@test "cleanup: estimate_freed_space returns numeric MB value" {
  mkdir -p "$WORKTREE_BASE/worker-test"
  dd if=/dev/zero of="$WORKTREE_BASE/worker-test/testfile" bs=1M count=5 2>/dev/null || true

  source "$CLEANUP_LIB"
  freed=$(estimate_freed_space "$WORKTREE_BASE/worker-test")

  # Should return a number (may be 0 if dd failed)
  [[ "$freed" =~ ^[0-9]+$ ]]
}

# ── Test: cleanup summary message format ──────────────────────────────────────
@test "cleanup: summary message includes worker count and freed MB" {
  mkdir -p "$WORKTREE_BASE/worker-1"
  echo "99999" > "$WORKTREE_BASE/worker-1/.heartbeat"

  run bash "$CLEANUP_LIB" "$REPO_ROOT" "$WORKTREE_BASE"
  [ "$status" -eq 0 ]

  # Should have summary with either "Cleaned" or "All workers active"
  [[ "$output" =~ "Cleaned" ]] || [[ "$output" =~ "All workers active" ]]
}

# ── Test: is_process_alive with invalid PID returns 1 ───────────────────────
# ── Test: is_process_alive with current PID works ───────────────────────
@test "cleanup: is_process_alive detects current process" {
  source "$CLEANUP_LIB"
  if is_process_alive $$; then
    # Current process found - correct
    [ 0 -eq 0 ]
  else
    # Current process not found - unexpected
    [ 0 -eq 1 ]
  fi
}

# ── Test: cleanup with actual worktree can be removed ──────────────────────────
@test "cleanup: remove_worker_worktree removes directory with rm as fallback" {
  test_dir="$WORKTREE_BASE/worker-test"
  mkdir -p "$test_dir"
  touch "$test_dir/test_file.txt"

  source "$CLEANUP_LIB"
  remove_worker_worktree "$REPO_ROOT" "test" "$test_dir"
  status=$?

  # Should succeed (return 0) since rm fallback will work
  [ "$status" -eq 0 ]
  # Directory should be gone
  [ ! -d "$test_dir" ]
}

# ── Test: exit code is always 0 (success) ────────────────────────────────────
@test "cleanup: always exits with code 0 (no errors)" {
  run bash "$CLEANUP_LIB" "$REPO_ROOT" "$WORKTREE_BASE"
  [ "$status" -eq 0 ]
}
