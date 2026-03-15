#!/usr/bin/env bats
# tests/stale_lock_cleanup.bats — Tests for US-225 stale git lock-file cleanup
#
# Run with: bats tests/stale_lock_cleanup.bats
#
# Tests verify:
#   - No lock files: function returns 0 with no output
#   - Fresh lock (< timeout): skipped, not removed
#   - Stale lock (>= timeout, no live git): removed + event logged
#   - Stale lock with live git PID: skipped (conservative guard)

# ── Setup / teardown ──────────────────────────────────────────────────────────

setup() {
  export TEST_TMPDIR
  TEST_TMPDIR="$(mktemp -d)"
  export WORKTREE_BASE="$TEST_TMPDIR/spiral-workers"
  export SCRATCH_DIR="$TEST_TMPDIR/scratch"
  mkdir -p "$SCRATCH_DIR"
  mkdir -p "$WORKTREE_BASE/worker-1/.git"
  mkdir -p "$WORKTREE_BASE/worker-2/.git"

  # Define _check_stale_worktree_locks inline so we can override ps/python
  # for unit testing without sourcing the full validate_preflight.sh.
  _check_stale_worktree_locks() {
    local worktree_base="${1}"
    local scratch_dir="${2}"
    local lock_timeout="${3:-5}"
    local _locks_removed=0

    [[ -d "$worktree_base" ]] || return 0

    for wt in "$worktree_base"/worker-*; do
      [[ -d "$wt" ]] || continue
      local wt_git_dir="$wt/.git"

      if [[ -f "$wt/.git" ]]; then
        wt_git_dir=$(sed 's/^gitdir: //' "$wt/.git" 2>/dev/null || true)
        [[ -n "$wt_git_dir" ]] || continue
      fi

      [[ -d "$wt_git_dir" ]] || continue

      while IFS= read -r -d '' lock_file; do
        local age_mins _lf_win
        _lf_win="$(cygpath -w "$lock_file" 2>/dev/null || echo "$lock_file")"
        age_mins=$(python3 -c "
import os, time
try:
    s = os.stat(r'''${_lf_win}''')
    print(int((time.time() - s.st_mtime) / 60))
except Exception:
    print(-1)
" 2>/dev/null || echo "-1")

        if [[ "$age_mins" -lt 0 ]]; then
          continue
        fi

        if [[ "$age_mins" -lt "$lock_timeout" ]]; then
          continue
        fi

        # Use TEST_LIVE_GIT_COUNT override for unit testing
        local live_git_count="${TEST_LIVE_GIT_COUNT:-0}"

        if [[ "$live_git_count" -gt 0 ]]; then
          echo "  [preflight] Stale lock detected (${age_mins}m old) but live git process found — skipping: $lock_file"
          continue
        fi

        if rm -f "$lock_file" 2>/dev/null; then
          echo "  [preflight] Removed stale git lock (${age_mins}m old): $lock_file"
          printf '{"ts":"%s","event":"stale_lock_removed","file":"%s","age_minutes":%d}\n' \
            "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$lock_file" "$age_mins" \
            >> "${scratch_dir}/spiral_events.jsonl" 2>/dev/null || true
          _locks_removed=$((_locks_removed + 1))
        fi
      done < <(find "$wt_git_dir" -maxdepth 2 -name "*.lock" -print0 2>/dev/null)
    done

    if [[ "$_locks_removed" -gt 0 ]]; then
      echo "  [preflight] Stale lock cleanup: removed $_locks_removed lock file(s)"
    fi
  }
  export -f _check_stale_worktree_locks
}

teardown() {
  rm -rf "$TEST_TMPDIR"
}

# ── Helper: create a lock file with a given age in minutes ───────────────────

_make_lock_aged() {
  local path="$1"
  local age_minutes="$2"
  touch "$path"
  # Convert MSYS path to Windows path for Python on win32
  local _win_path
  _win_path="$(cygpath -w "$path" 2>/dev/null || echo "$path")"
  # Set mtime to (now - age_minutes * 60) seconds using Python
  python3 -c "
import os, time
age = $age_minutes * 60
mtime = time.time() - age
os.utime(r'''${_win_path}''', (mtime, mtime))
"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "no lock files: returns 0 with no removal output" {
  run _check_stale_worktree_locks "$WORKTREE_BASE" "$SCRATCH_DIR" 5
  [ "$status" -eq 0 ]
  [[ "$output" != *"Removed"* ]]
}

@test "fresh lock (< timeout): not removed" {
  local lock="$WORKTREE_BASE/worker-1/.git/index.lock"
  _make_lock_aged "$lock" 2   # 2 minutes old, timeout is 5
  run _check_stale_worktree_locks "$WORKTREE_BASE" "$SCRATCH_DIR" 5
  [ "$status" -eq 0 ]
  [ -f "$lock" ]              # file still exists
  [[ "$output" != *"Removed"* ]]
}

@test "stale lock (>= timeout, no live git): removed" {
  local lock="$WORKTREE_BASE/worker-1/.git/index.lock"
  _make_lock_aged "$lock" 10  # 10 minutes old, timeout is 5
  export TEST_LIVE_GIT_COUNT=0
  run _check_stale_worktree_locks "$WORKTREE_BASE" "$SCRATCH_DIR" 5
  [ "$status" -eq 0 ]
  [ ! -f "$lock" ]            # file removed
  [[ "$output" == *"Removed stale git lock"* ]]
}

@test "stale lock removal emits event to spiral_events.jsonl" {
  local lock="$WORKTREE_BASE/worker-1/.git/packed-refs.lock"
  _make_lock_aged "$lock" 10
  export TEST_LIVE_GIT_COUNT=0
  _check_stale_worktree_locks "$WORKTREE_BASE" "$SCRATCH_DIR" 5
  [ -f "$SCRATCH_DIR/spiral_events.jsonl" ]
  run grep "stale_lock_removed" "$SCRATCH_DIR/spiral_events.jsonl"
  [ "$status" -eq 0 ]
}

@test "stale lock with live git PID: skipped (not removed)" {
  local lock="$WORKTREE_BASE/worker-2/.git/index.lock"
  _make_lock_aged "$lock" 10  # 10 minutes old
  export TEST_LIVE_GIT_COUNT=1  # simulate live git process
  run _check_stale_worktree_locks "$WORKTREE_BASE" "$SCRATCH_DIR" 5
  [ "$status" -eq 0 ]
  [ -f "$lock" ]              # file NOT removed
  [[ "$output" == *"live git process found"* ]]
}

@test "multiple stale locks across workers: all removed" {
  local lock1="$WORKTREE_BASE/worker-1/.git/index.lock"
  local lock2="$WORKTREE_BASE/worker-2/.git/MERGE_HEAD.lock"
  _make_lock_aged "$lock1" 10
  _make_lock_aged "$lock2" 15
  export TEST_LIVE_GIT_COUNT=0
  run _check_stale_worktree_locks "$WORKTREE_BASE" "$SCRATCH_DIR" 5
  [ "$status" -eq 0 ]
  [ ! -f "$lock1" ]
  [ ! -f "$lock2" ]
  [[ "$output" == *"removed 2 lock file(s)"* ]]
}

@test "missing worktree base dir: returns 0 silently" {
  run _check_stale_worktree_locks "$TEST_TMPDIR/nonexistent" "$SCRATCH_DIR" 5
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "_check_stale_worktree_locks function exists in validate_preflight.sh" {
  local script
  script="$(git -C "$(dirname "$BATS_TEST_FILENAME")" rev-parse --show-toplevel 2>/dev/null)/lib/validate_preflight.sh"
  run grep -c "_check_stale_worktree_locks" "$script"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}

@test "SPIRAL_LOCK_TIMEOUT_MINUTES is defined in spiral.config.sh" {
  local cfg
  cfg="$(git -C "$(dirname "$BATS_TEST_FILENAME")" rev-parse --show-toplevel 2>/dev/null)/spiral.config.sh"
  run grep -c "SPIRAL_LOCK_TIMEOUT_MINUTES" "$cfg"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}
