#!/bin/bash
# lib/core/prd_lock.sh — Atomic read-modify-write for prd.json in worker worktrees
#
# Usage: atomic_patch_prd <wtree> <jq-filter> [extra-jq-args...]
#
# Acquires a per-worktree mkdir-based exclusive lock, applies the jq filter to
# <wtree>/prd.json atomically (tmp+mv), then releases the lock.
#
# Lock behaviour:
#   - Lock dir: <wtree>/prd.json.lock  (mkdir is atomic on POSIX + Windows NTFS)
#   - Stale lock cleanup: if the lock dir is older than 60s it is removed once
#     before the spin loop starts (checked via directory mtime — no separate file
#     needed, so there is no window between mkdir and file write)
#   - Acquisition timeout: 30s (300 × 100ms polls), then error + non-zero exit
#
# Exit codes:
#   0 — patch applied successfully
#   1 — lock timeout (30s) or jq/mv failure

# _dir_mtime <path> — portable directory mtime in epoch seconds
# Returns 0 on macOS (BSD stat) or Linux (GNU stat), 1 if unavailable.
_dir_mtime() {
  stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0
}

# atomic_patch_prd <wtree> <jq-filter> [extra-jq-args...]
# extra-jq-args: --arg, --argjson, etc. passed directly to jq before the filter
atomic_patch_prd() {
  local wtree="$1"
  local jq_filter="$2"
  shift 2
  # "$@" are extra jq args (--arg name val, --argjson name val, etc.)

  local prd_file="$wtree/prd.json"
  local lock_dir="$wtree/prd.json.lock"
  local tmp_file="$wtree/prd.json.tmp.$$"
  local jq_bin="${JQ:-jq}"
  local timeout_iters=300 # 300 × 0.1s = 30s
  local attempt=0

  # ── One-time stale lock cleanup before spin loop ───────────────────────────
  # Check is done BEFORE entering the spin loop so we never read the pid/created
  # file while another process is in the middle of writing it (no race window).
  if [[ -d "$lock_dir" ]]; then
    local lock_ts now lock_age
    lock_ts=$(_dir_mtime "$lock_dir")
    now=$(date +%s)
    lock_age=$((now - lock_ts))
    if [[ $lock_age -ge 60 ]]; then
      local holder_pid=""
      [[ -f "$lock_dir/pid" ]] && holder_pid=$(cat "$lock_dir/pid" 2>/dev/null || true)
      echo "  [prd_lock] Removing stale lock (${lock_age}s old, pid=${holder_pid:-?}): $lock_dir" >&2
      rm -rf "$lock_dir" 2>/dev/null || true
    fi
  fi

  # ── Spin-wait for lock ────────────────────────────────────────────────────
  while [[ $attempt -lt $timeout_iters ]]; do
    if mkdir "$lock_dir" 2>/dev/null; then
      # Record PID for debugging (best-effort; not used for stale detection)
      echo "$$" >"$lock_dir/pid" 2>/dev/null || true
      break
    fi
    attempt=$((attempt + 1))
    sleep 0.1 2>/dev/null || true
  done

  if [[ $attempt -ge $timeout_iters ]]; then
    local holder_pid=""
    [[ -f "$lock_dir/pid" ]] && holder_pid=$(cat "$lock_dir/pid" 2>/dev/null || true)
    echo "  [prd_lock] ERROR: lock acquisition timeout (30s) for $prd_file" >&2
    echo "  [prd_lock]   Lock: $lock_dir  Held by PID: ${holder_pid:-unknown}" >&2
    return 1
  fi

  # ── Apply jq transform and write atomically ───────────────────────────────
  local rc=0
  if "$jq_bin" "$@" "$jq_filter" "$prd_file" >"$tmp_file" 2>/dev/null &&
    mv "$tmp_file" "$prd_file" 2>/dev/null; then
    rc=0
  else
    rc=1
    rm -f "$tmp_file" 2>/dev/null || true
  fi

  # ── Release lock ──────────────────────────────────────────────────────────
  rm -rf "$lock_dir" 2>/dev/null || true
  return $rc
}

# Main entry point when called as a script (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  atomic_patch_prd "$@"
  exit $?
fi
