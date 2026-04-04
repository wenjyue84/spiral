#!/usr/bin/env bash
# lib/impl/git_retry.sh — Retry wrapper for git operations on index.lock failures
#
# On Windows, parallel workers frequently race on shared .git/index.lock, causing
# git operations to fail. This module adds a retry wrapper with exponential backoff
# and stale lock detection.
#
# Usage:
#   source lib/impl/git_retry.sh
#   git_retry 3 1 git -C /path/to/repo commit -m "message"
#
# Arguments:
#   $1: max_retries (default 3)
#   $2: initial_backoff_seconds (default 1)
#   $3+: git command to execute (e.g., git -C /repo commit -m "msg")
#
# Returns: exit code of the git command on success, or non-zero on all retries exhausted
#
# Behavior:
#   1. Runs the git command
#   2. On success: returns 0 immediately
#   3. On index.lock error:
#      a. Checks if lock file exists and extracts PID
#      b. If PID is dead: removes lock and retries
#      c. If PID is alive: waits backoff seconds and retries
#      d. Repeats up to max_retries times with exponential backoff (1s, 2s, 4s...)
#   4. Logs each retry attempt to spiral_events.jsonl

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# _is_pid_alive <pid>
# Returns 0 if PID is alive, 1 if dead or invalid
# Cross-platform: works on Windows (Git Bash) and Unix
_is_pid_alive() {
  local pid="$1"

  # On Windows/Git Bash, ps aux is available
  # On Unix, use standard ps
  if ps -p "$pid" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

# _remove_stale_lock <git_repo>
# Detects and removes stale .git/index.lock if its PID is dead
# Returns 0 if lock was removed or doesn't exist, 1 if removal failed
_remove_stale_lock() {
  local repo_root="$1"
  local lock_file="$repo_root/.git/index.lock"

  if [[ ! -f "$lock_file" ]]; then
    return 0
  fi

  # Try to extract PID from lock file (format: "pid <number>\n")
  local lock_pid
  lock_pid=$(head -1 "$lock_file" 2>/dev/null || true)
  lock_pid="${lock_pid##*[^0-9]}" # Extract trailing digits
  lock_pid="${lock_pid%%[^0-9]*}" # Remove trailing non-digits

  if [[ -z "$lock_pid" ]] || ! [[ "$lock_pid" =~ ^[0-9]+$ ]]; then
    # Can't extract PID, assume stale and remove
    rm -f "$lock_file" 2>/dev/null && return 0
    return 1
  fi

  # Check if the PID is still alive
  if ! _is_pid_alive "$lock_pid"; then
    # PID is dead, safe to remove the lock
    rm -f "$lock_file" 2>/dev/null && return 0
    return 1
  fi

  # PID is still alive, don't remove (caller will retry with backoff)
  return 1
}

# _log_retry_event <story_id> <attempt> <backoff_seconds>
# Logs a retry event to spiral_events.jsonl
_log_retry_event() {
  local story_id="$1"
  local attempt="$2"
  local backoff_seconds="$3"

  local _ts _ev_file _ev_json
  _ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  _ev_file="${SPIRAL_SCRATCH_DIR:-./}spiral_events.jsonl"

  # shellcheck disable=SC2059
  _ev_json="$(printf '{"ts":"%s","event":"git_retry","story_id":"%s","run_id":"%s","attempt":%d,"backoff_seconds":%d}' \
    "$_ts" "${story_id:-unknown}" "${SPIRAL_RUN_ID:-}" "$attempt" "$backoff_seconds")"

  _py="${SPIRAL_PYTHON:-${PYTHON:-uv run python}}"
  _spiral_io="${SPIRAL_HOME:-${SPIRAL_ROOT:-.}}/lib/core/spiral_io.py"
  if [[ -f "$_spiral_io" ]]; then
    $_py "$_spiral_io" --append "$_ev_file" "$_ev_json" 2>/dev/null ||
      printf '%s\n' "$_ev_json" >>"$_ev_file" 2>/dev/null || true
  else
    printf '%s\n' "$_ev_json" >>"$_ev_file" 2>/dev/null || true
  fi
}

# git_retry [max_retries] [initial_backoff_seconds] <git command...>
#
# Wraps a git command with retry logic for index.lock failures.
# If fewer than 2 args provided, uses defaults (max_retries=3, backoff=1s).
#
# Examples:
#   git_retry git -C /repo commit -m "message"
#   git_retry 5 2 git -C /repo add .
git_retry() {
  local max_retries=3
  local initial_backoff=1
  local story_id="${CURRENT_STORY_ID:-}"

  # Parse optional first two arguments
  if [[ $# -ge 2 ]] && [[ "$1" =~ ^[0-9]+$ ]]; then
    max_retries="$1"
    shift
    if [[ "$1" =~ ^[0-9]+$ ]]; then
      initial_backoff="$1"
      shift
    fi
  fi

  # Remaining args are the git command
  local -a git_cmd=("$@")

  if [[ ${#git_cmd[@]} -eq 0 ]]; then
    echo "[ERROR] git_retry: no command provided" >&2
    return 1
  fi

  local attempt=0
  local backoff="$initial_backoff"
  local output
  local rc

  while [[ $attempt -le $max_retries ]]; do
    attempt=$((attempt + 1))

    # Run the git command and capture output
    output=$("${git_cmd[@]}" 2>&1)
    rc=$?

    # Success case
    if [[ $rc -eq 0 ]]; then
      echo "$output"
      return 0
    fi

    # Check if error is index.lock related
    if echo "$output" | grep -q "index.lock"; then
      # Attempt to remove stale lock if PID is dead
      # Extract repo path from git command (look for -C flag, or use current directory)
      local repo_root=""
      for i in $(seq 0 $((${#git_cmd[@]} - 1))); do
        if [[ "${git_cmd[$i]}" == "-C" ]] && [[ $((i + 1)) -lt ${#git_cmd[@]} ]]; then
          repo_root="${git_cmd[$((i + 1))]}"
          break
        fi
      done

      # If no -C flag, default to current directory
      if [[ -z "$repo_root" ]]; then
        repo_root="."
      fi

      if _remove_stale_lock "$repo_root"; then
        # Lock was stale and removed, retry immediately
        _log_retry_event "$story_id" "$attempt" 0
        continue
      fi

      # Not a stale lock, or couldn't remove it
      if [[ $attempt -le $max_retries ]]; then
        # Log this retry and wait before next attempt
        _log_retry_event "$story_id" "$attempt" "$backoff"
        sleep "$backoff"
        backoff=$((backoff * 2)) # Exponential backoff: 1s -> 2s -> 4s -> ...
        continue
      fi
    fi

    # Non-recoverable error (not index.lock), return immediately
    echo "$output" >&2
    return $rc
  done

  # All retries exhausted
  echo "$output" >&2
  return $rc
}
