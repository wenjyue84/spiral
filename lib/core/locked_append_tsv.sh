#!/bin/bash
# lib/core/locked_append_tsv.sh — Append to TSV files with exclusive file locking
#
# Usage: locked_append_tsv <tsv_file> <row_data>
#
# Acquires an exclusive file lock before appending and releases it after.
# Delegates to lib/core/locked_append_tsv.py for cross-platform file locking.
#
# Exit codes:
#   0 — append succeeded
#   1 — append failed
#   2 — helper not available (fallback to raw append)

set -euo pipefail

locked_append_tsv() {
  local tsv_file="$1"
  local row_data="$2"
  local lock_dir
  lock_dir=$(dirname "$tsv_file")
  mkdir -p "$lock_dir" 2>/dev/null || true

  # Use mkdir-based atomic lock (faster than Python on most systems)
  # mkdir is atomic on POSIX/Windows and can't race
  local lock_path="${lock_dir}/.${tsv_file##*/}.lock"
  local timeout=100 # 1 second total (100 × 10ms)
  local attempt=0

  # Spin-wait for lock with backoff
  while [[ $attempt -lt $timeout ]]; do
    if mkdir "$lock_path" 2>/dev/null; then
      # Lock acquired
      {
        printf '%s\n' "$row_data" >>"$tsv_file" || return 1
      }
      # Release lock (rmdir is atomic)
      rmdir "$lock_path" 2>/dev/null || true
      return 0
    fi
    attempt=$((attempt + 1))
    # Use /dev/null as no-op sleep alternative for speed
    # 10ms sleep per attempt × 100 = 1 second max wait
    sleep 0.01 2>/dev/null || true
  done

  # Lock timeout: log warning and fall back to raw append (graceful degradation)
  echo "  [locked_append] WARNING: Lock timeout on $tsv_file (waited 1s) — fallback to raw append" >&2
  printf '%s\n' "$row_data" >>"$tsv_file" 2>/dev/null || return 1
  return 0
}

# Main entry point when called as a script (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  locked_append_tsv "$@"
  exit $?
fi
