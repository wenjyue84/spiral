#!/bin/bash
# lib/worker_cleanup.sh — Safe cleanup of stale worker processes
#
# Functions to identify and safely remove orphaned git worktrees from
# parallel worker execution. A worker is considered stale if:
# 1. No active process (checked via ps/tasklist)
# 2. Last modified > 2 hours old
#
# Usage: cleanup_stale_workers "$REPO_ROOT" "$WORKTREE_BASE"

set -euo pipefail

# ── estimate_freed_space: calculate total disk usage of a worktree ────────────
# Args: $1 = worktree path
# Returns: size in MB
estimate_freed_space() {
  local worktree_path="$1"
  if [[ ! -d "$worktree_path" ]]; then
    echo "0"
    return
  fi

  # Use du to estimate size; fallback to 0 if du fails
  if command -v du &>/dev/null; then
    du -sm "$worktree_path" 2>/dev/null | awk '{print $1}' || echo "0"
  else
    echo "0"
  fi
}

# ── is_process_alive: check if a PID is still running ────────────────────────
# Args: $1 = PID
# Returns: 0 if alive, 1 if dead
is_process_alive() {
  local pid="$1"
  [[ -z "$pid" ]] && return 1

  # Try ps first (works in Git Bash on Windows and Unix)
  if command -v ps &>/dev/null; then
    if ps -p "$pid" >/dev/null 2>&1; then
      return 0
    else
      return 1
    fi
  fi

  # Windows fallback: use tasklist
  if command -v tasklist &>/dev/null; then
    if tasklist 2>/dev/null | grep -q "^[^ ]*\s*$pid\s"; then
      return 0
    else
      return 1
    fi
  fi

  # If no tools available, assume dead
  return 1
}

# ── is_stale_worker: check if a worker is stale (no process + age > 2h) ───────
# Args: $1 = worktree path
# Returns: 0 if stale, 1 if active
is_stale_worker() {
  local worktree_path="$1"
  local heartbeat_file="${worktree_path}/.heartbeat"

  if [[ ! -f "$heartbeat_file" ]]; then
    # No heartbeat file = stale
    return 0
  fi

  # Read PID from heartbeat
  local pid=""
  pid=$(head -1 "$heartbeat_file" 2>/dev/null || echo "")

  # Check if process is alive
  if [[ -n "$pid" ]]; then
    if is_process_alive "$pid"; then
      # Process is active = not stale
      return 1
    fi
  fi

  # Check last modified time
  local now
  local mtime
  local age_seconds

  if command -v stat &>/dev/null; then
    # Try GNU stat first (Linux)
    if stat --help 2>/dev/null | grep -q "format"; then
      mtime=$(stat -c "%Y" "$heartbeat_file" 2>/dev/null || echo "0")
    else
      # BSD stat (macOS)
      mtime=$(stat -f "%m" "$heartbeat_file" 2>/dev/null || echo "0")
    fi
  else
    # Fallback: use date -r (works on most systems)
    mtime=$(date -r "$heartbeat_file" +%s 2>/dev/null || echo "0")
  fi

  now=$(date +%s)
  age_seconds=$((now - mtime))

  # 2 hours = 7200 seconds
  if [[ $age_seconds -gt 7200 ]]; then
    # Worker is stale
    return 0
  fi

  # Worker is active
  return 1
}

# ── remove_worker_worktree: safely remove a worker worktree ──────────────────
# Args: $1 = repo root, $2 = worker ID, $3 = worktree path
# Returns: 0 on success, 1 on failure
remove_worker_worktree() {
  local repo_root="$1"
  local worker_id="$2"
  local worktree_path="$3"

  if [[ ! -d "$worktree_path" ]]; then
    return 1
  fi

  # Attempt git worktree remove
  if git -C "$repo_root" worktree remove --force "$worktree_path" 2>/dev/null; then
    return 0
  fi

  # Fallback: manual removal if git worktree remove fails
  if rm -rf "$worktree_path" 2>/dev/null; then
    return 0
  fi

  return 1
}

# ── find_stale_workers: identify all stale workers in .spiral-workers ────────
# Args: $1 = worktree base directory
# Outputs: list of worker IDs (one per line)
find_stale_workers() {
  local worktree_base="$1"

  if [[ ! -d "$worktree_base" ]]; then
    return
  fi

  for worktree_dir in "$worktree_base"/worker-*; do
    [[ ! -d "$worktree_dir" ]] && continue
    worker_id=$(basename "$worktree_dir" | sed 's/^worker-//')

    if is_stale_worker "$worktree_dir"; then
      echo "$worker_id"
    fi
  done
}

# ── cleanup_stale_workers: main cleanup orchestrator ──────────────────────────
# Args: $1 = repo root, $2 = worktree base directory
# Outputs: summary message
cleanup_stale_workers() {
  local repo_root="$1"
  local worktree_base="$2"

  if [[ ! -d "$worktree_base" ]]; then
    echo "[spiral] No stale workers found. All workers active."
    return 0
  fi

  local stale_workers=()
  local total_freed_mb=0
  local removed_count=0

  # Find all stale workers
  local stale_output
  stale_output=$(find_stale_workers "$worktree_base" 2>/dev/null || echo "")

  while IFS= read -r worker_id; do
    [[ -z "$worker_id" ]] && continue
    stale_workers+=("$worker_id")
  done <<<"$stale_output"

  if [[ ${#stale_workers[@]} -eq 0 ]]; then
    echo "[spiral] No stale workers found. All workers active."
    return 0
  fi

  # Remove each stale worker
  for worker_id in "${stale_workers[@]}"; do
    local worktree_path="${worktree_base}/worker-${worker_id}"

    if [[ ! -d "$worktree_path" ]]; then
      continue
    fi

    # Estimate disk space before removal
    local freed_mb
    freed_mb=$(estimate_freed_space "$worktree_path")

    # Remove worktree
    if remove_worker_worktree "$repo_root" "$worker_id" "$worktree_path"; then
      ((removed_count++))
      total_freed_mb=$((total_freed_mb + freed_mb))
    fi
  done

  # Print summary
  if [[ $removed_count -gt 0 ]]; then
    echo "[spiral] Cleaned $removed_count stale worker(s), freed ~${total_freed_mb} MB"
    return 0
  else
    echo "[spiral] No stale workers found. All workers active."
    return 0
  fi
}

# ── Main entry point ────────────────────────────────────────────────────────
# If sourced, nothing happens. If executed directly, run cleanup.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <repo-root> <worktree-base>" >&2
    exit 1
  fi
  cleanup_stale_workers "$1" "$2" || true
  exit 0
fi
