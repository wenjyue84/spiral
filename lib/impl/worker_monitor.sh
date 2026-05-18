#!/bin/bash
# lib/impl/worker_monitor.sh — Background heartbeat monitor for worker stall detection
#
# Spawned once per worker during _launch_worker_i(). Monitors the worker's heartbeat
# file for staleness. If no progress for > SPIRAL_WORKER_STALL_TIMEOUT_SECONDS (default 90s),
# kills the worker and logs a recovery event to spiral_events.jsonl.
#
# Usage:
#   bash lib/impl/worker_monitor.sh <worker_num> <worker_pid> <worker_dir> <spiral_home>
#
# Arguments:
#   worker_num   — Worker ID (1, 2, 3...)
#   worker_pid   — PID of the spawned worker process to monitor
#   worker_dir   — Path to worker directory (e.g., .spiral-workers/worker-1)
#   spiral_home  — Path to SPIRAL repo root (for accessing helpers)

set -euo pipefail

WORKER_NUM="${1:?worker_num required}"
WORKER_PID="${2:?worker_pid required}"
WORKER_DIR="${3:?worker_dir required}"
SPIRAL_HOME="${4:?spiral_home required}"

# Config from environment
STALL_TIMEOUT_SECS="${SPIRAL_WORKER_STALL_TIMEOUT_SECONDS:-90}"
HEARTBEAT_CHECK_INTERVAL_SECS=30

# Helper: log to events file
spiral_event() {
  local _ef="$1" _ej="$2"
  if [[ -n "${PYTHON:-}" && -n "${SPIRAL_HOME:-}" ]]; then
    "$PYTHON" "$SPIRAL_HOME/lib/core/spiral_io.py" --append "$_ef" "$_ej" 2>/dev/null && return 0
  fi
  printf '%s\n' "$_ej" >>"$_ef" 2>/dev/null || true
}

# Main monitor loop
monitor_worker() {
  local hb_file="$WORKER_DIR/.heartbeat"
  local scratch_dir="${SPIRAL_SCRATCH_DIR:-.spiral}"

  while true; do
    sleep "$HEARTBEAT_CHECK_INTERVAL_SECS"

    # Check if heartbeat file exists
    if [[ ! -f "$hb_file" ]]; then
      # Heartbeat not yet written; skip check
      continue
    fi

    # Check if worker process still exists
    if ! kill -0 "$WORKER_PID" 2>/dev/null; then
      # Worker already exited; monitor can exit
      break
    fi

    # Read heartbeat JSON and extract last_progress_time
    local lpt stall_secs now
    lpt=$(jq -r '.last_progress_time // 0' "$hb_file" 2>/dev/null || echo "0")

    # If last_progress_time is 0 or missing, skip (heartbeat not yet stabilized)
    if [[ "$lpt" -eq 0 ]]; then
      continue
    fi

    # Calculate stall duration
    now=$(date +%s)
    stall_secs=$((now - lpt))

    # Check if stalled
    if [[ "$stall_secs" -gt "$STALL_TIMEOUT_SECS" ]]; then
      # Stall detected — kill worker and log event
      local story_id phase
      story_id=$(jq -r '.storyId // "unknown"' "$hb_file" 2>/dev/null || echo "unknown")
      phase=$(jq -r '.phase // "unknown"' "$hb_file" 2>/dev/null || echo "unknown")

      echo "[monitor] ALERT: Worker $WORKER_NUM stalled (no progress for ${stall_secs}s, threshold ${STALL_TIMEOUT_SECS}s) — killing PID $WORKER_PID" >&2

      # Kill worker process
      kill "$WORKER_PID" 2>/dev/null || true
      sleep 1
      kill -9 "$WORKER_PID" 2>/dev/null || true

      # Log event to spiral_events.jsonl
      if [[ -d "$scratch_dir" ]]; then
        spiral_event "$scratch_dir/spiral_events.jsonl" \
          "$(printf '{"ts":"%s","event":"worker_stalled_and_recovered","run_id":"%s","worker":%d,"story_id":"%s","stall_secs":%d,"phase":"%s"}' \
            "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${SPIRAL_RUN_ID:-}" "$WORKER_NUM" "$story_id" "$stall_secs" "$phase")"
      fi

      # Exit monitor — parent (run_parallel_ralph.sh) will handle restart via _restart_stalled_worker
      break
    fi
  done
}

monitor_worker "$@"
