#!/bin/bash
# worker_heartbeat.sh — Heartbeat file management for worker health detection
#
# Functions:
#   worker_heartbeat_start()  — Launch background heartbeat loop
#   worker_heartbeat_stop()   — Stop heartbeat loop and clean up
#   check_stale_heartbeats()  — Find and report stale heartbeats
#
# Environment variables (must be set before sourcing):
#   SPIRAL_WORKER_ID        — Worker number (1, 2, 3...)
#   HEARTBEAT_DIR           — Directory for heartbeat files (default: .spiral/workers)
#   HEARTBEAT_INTERVAL      — Write interval in seconds (default: 30)
#   STALE_THRESHOLD         — Stale timeout in seconds (default: 120)

set -o pipefail

HEARTBEAT_DIR="${HEARTBEAT_DIR:-.spiral/workers}"
HEARTBEAT_INTERVAL="${HEARTBEAT_INTERVAL:-30}"
STALE_THRESHOLD="${STALE_THRESHOLD:-120}"

# Global variable to track heartbeat background job
_HEARTBEAT_PID=""
# Track worker start time for uptime calculation
_WORKER_START_TS=""

# ── Worker-side: Start periodic heartbeat writes ────────────────────────────────
worker_heartbeat_start() {
  local worker_id="${1:-$SPIRAL_WORKER_ID}"
  local interval="${2:-$HEARTBEAT_INTERVAL}"

  if [[ -z "$worker_id" ]]; then
    echo "[heartbeat] ERROR: worker_id not provided and SPIRAL_WORKER_ID not set" >&2
    return 1
  fi

  mkdir -p "$HEARTBEAT_DIR" 2>/dev/null || true
  _WORKER_START_TS=$(date +%s)

  # Start background loop that writes heartbeat every N seconds
  (
    local start_ts
    start_ts=$(date +%s)
    # US-531: Track last time worker made progress (completed count changed)
    local _last_progress_ts _prev_completed
    _last_progress_ts=$(date +%s)
    _prev_completed=0
    while true; do
      sleep "$interval"
      # Get current story ID if available (from _current_story_id file in worker root)
      local current_story_id="${SPIRAL_CURRENT_STORY:-unknown}"
      local completed="${SPIRAL_STORIES_COMPLETED:-0}"
      local phase="${SPIRAL_WORKER_PHASE:-unknown}"
      # US-531: Update _last_progress_ts when completed count changes
      if [[ "$completed" != "$_prev_completed" ]]; then
        _last_progress_ts=$(date +%s)
        _prev_completed="$completed"
      fi
      # US-481: Write .heartbeat directly in HEARTBEAT_DIR (typically .spiral-workers/worker-N)
      # This allows the GET /api/workers endpoint to read it without needing worker_id
      local hb_file="$HEARTBEAT_DIR/.heartbeat"
      local ts
      ts=$(date +%s)
      local pid=$$
      # Get memory usage in MB (cross-platform) — bash wrapper process
      local mem_mb=0
      if command -v powershell.exe &>/dev/null; then
        mem_mb=$(powershell.exe -Command "[math]::Floor((Get-Process -Id $pid -ErrorAction SilentlyContinue).WorkingSet64 / 1MB)" 2>/dev/null | tr -d '\r') || mem_mb=0
      elif [[ -f "/proc/$pid/status" ]]; then
        mem_mb=$(awk '/VmRSS/{printf "%d", $2/1024}' "/proc/$pid/status" 2>/dev/null) || mem_mb=0
      fi
      # Get actual Node.js child process RSS (the Claude CLI uses most of the memory)
      local node_mem_mb=0
      local node_pid=0
      if command -v powershell.exe &>/dev/null; then
        # Windows: find child node.exe process by parent PID
        local _node_info
        _node_info=$(powershell.exe -NoProfile -Command "
          \$p = Get-WmiObject Win32_Process -Filter \"ParentProcessId=$pid AND Name='node.exe'\" -ErrorAction SilentlyContinue | Select-Object -First 1;
          if (\$p) { \"{0} {1}\" -f \$p.ProcessId, [math]::Floor(\$p.WorkingSetSize / 1MB) }
        " 2>/dev/null | tr -d '\r') || _node_info=""
        if [[ -n "$_node_info" ]]; then
          node_pid="${_node_info%% *}"
          node_mem_mb="${_node_info##* }"
        fi
      elif [[ -d "/proc/$pid" ]]; then
        # Linux: find child node process via pgrep
        local _child_pid
        _child_pid=$(pgrep -P "$pid" -x node 2>/dev/null | head -1) || _child_pid=""
        if [[ -n "$_child_pid" && -f "/proc/$_child_pid/status" ]]; then
          node_pid="$_child_pid"
          node_mem_mb=$(awk '/VmRSS/{printf "%d", $2/1024}' "/proc/$_child_pid/status" 2>/dev/null) || node_mem_mb=0
        fi
      fi
      # Write heartbeat JSON atomically (temp + mv prevents partial reads by monitor)
      local hb_tmp="${hb_file}.tmp"
      printf '{"pid":%s,"storyId":"%s","ts":%s,"completed":%s,"phase":"%s","memMb":%s,"nodeMemMb":%s,"nodePid":%s,"last_progress_time":%s}\n' \
        "$pid" "$current_story_id" "$ts" "$completed" "$phase" "${mem_mb:-0}" "${node_mem_mb:-0}" "${node_pid:-0}" "$_last_progress_ts" >"$hb_tmp" 2>/dev/null &&
        mv "$hb_tmp" "$hb_file" 2>/dev/null || true
      # US-531: Warn if worker has made no progress for longer than SPIRAL_WORKER_TIMEOUT
      local _wt_timeout="${SPIRAL_WORKER_TIMEOUT:-300}"
      if [[ "$_wt_timeout" -gt 0 ]]; then
        local _stall_secs=$((ts - _last_progress_ts))
        if [[ "$_stall_secs" -gt "$_wt_timeout" ]]; then
          echo "[heartbeat] WARNING: Worker $worker_id: no progress for ${_stall_secs}s (timeout=${_wt_timeout}s)" >&2
        fi
      fi

      # US-527: Write per-worker queue JSON to .spiral/workers/worker_N.json
      # This allows GET /api/workers/<id>/queue to return live task state
      local uptime=$((ts - start_ts))
      local started_at
      started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")
      local wq_file="${HEARTBEAT_DIR}/worker_${worker_id}.json"
      local wq_tmp="${wq_file}.tmp"
      # Build current_task JSON (null if no story is running)
      local current_task_json="null"
      if [[ "$current_story_id" != "unknown" && -n "$current_story_id" ]]; then
        current_task_json="{\"story_id\":\"$current_story_id\",\"started_at\":\"$started_at\"}"
      fi
      # SPIRAL_QUEUED_TASKS can be set to a JSON array string by the worker coordinator
      local queue_json="${SPIRAL_QUEUED_TASKS:-[]}"
      printf '{"worker_id":"worker-%s","current_task":%s,"queue":%s,"uptime":%s,"phase":"%s"}\n' \
        "$worker_id" "$current_task_json" "$queue_json" "$uptime" "$phase" >"$wq_tmp" 2>/dev/null &&
        mv "$wq_tmp" "$wq_file" 2>/dev/null || true
    done
  ) &
  _HEARTBEAT_PID=$!

  echo "[heartbeat] Worker $worker_id: heartbeat loop started (PID: $_HEARTBEAT_PID, interval: ${interval}s)"
}

# ── Worker-side: Stop heartbeat loop and clean up ────────────────────────────────
worker_heartbeat_stop() {
  local worker_id="${1:-$SPIRAL_WORKER_ID}"

  if [[ -z "$_HEARTBEAT_PID" ]]; then
    return 0
  fi

  # Kill background loop
  kill "$_HEARTBEAT_PID" 2>/dev/null || true
  wait "$_HEARTBEAT_PID" 2>/dev/null || true

  # Clean up heartbeat file (US-481: write directly to HEARTBEAT_DIR/.heartbeat)
  local hb_file="$HEARTBEAT_DIR/.heartbeat"
  rm -f "$hb_file" 2>/dev/null || true

  # US-527: Clean up per-worker queue JSON
  local wq_file="${HEARTBEAT_DIR}/worker_${worker_id}.json"
  rm -f "$wq_file" 2>/dev/null || true

  echo "[heartbeat] Worker $worker_id: heartbeat loop stopped, cleanup done"
}

# ── Coordinator-side: Detect stale heartbeats ────────────────────────────────────
# Returns: JSON array with stale worker info, or empty array if none found
# Example output: [{"workerId": 1, "storyId": "US-001", "lastSeen": 245}]
check_stale_heartbeats() {
  local hb_dir="${1:-$HEARTBEAT_DIR}"
  local threshold="${2:-$STALE_THRESHOLD}"
  local now ts stale_workers

  now=$(date +%s)
  stale_workers="[]"

  if [[ ! -d "$hb_dir" ]]; then
    printf '%s\n' "$stale_workers"
    return 0
  fi

  # Check each heartbeat file
  shopt -s nullglob 2>/dev/null || true
  for hb_file in "$hb_dir"/worker_*.heartbeat; do
    if [[ -f "$hb_file" ]]; then
      local mtime=$(stat -c %Y "$hb_file" 2>/dev/null || stat -f %m "$hb_file" 2>/dev/null || echo "0")
      local age=$((now - mtime))

      if [[ "$age" -gt "$threshold" ]]; then
        # File is stale — extract worker info
        local hb_content story_id
        hb_content=$(cat "$hb_file" 2>/dev/null || echo '{}')
        story_id=$(printf '%s' "$hb_content" | grep -o '"storyId":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
        local worker_num=$(basename "$hb_file" .heartbeat | sed 's/worker_//')

        # Append to stale_workers JSON array (avoid leading comma on first element)
        local entry="{\"workerId\":$worker_num,\"storyId\":\"$story_id\",\"staledSinceSeconds\":$age}"
        if [[ "$stale_workers" == "[]" ]]; then
          stale_workers="[$entry]"
        else
          stale_workers="${stale_workers%]},$entry]"
        fi
      fi
    fi
  done

  printf '%s\n' "$stale_workers"
}

# ── Coordinator-side: Re-queue stale stories ────────────────────────────────────
# Marks stale stories as passes=false WITHOUT incrementing retryCount
requeue_stale_stories() {
  local prd_file="$1"
  local stale_info="$2" # JSON with storyId
  local jq_cmd="${3:-jq}"
  local story_id

  # If stale_info starts with '{', treat as JSON and extract storyId; otherwise it IS the ID
  if [[ "$stale_info" == "{"* ]]; then
    story_id=$(printf '%s' "$stale_info" | $jq_cmd -r '.storyId // empty')
  else
    story_id="$stale_info"
  fi

  if [[ -z "$story_id" || "$story_id" == "unknown" ]]; then
    return 0
  fi

  if [[ ! -f "$prd_file" ]]; then
    return 1
  fi

  # Mark story as not passed, preserve retryCount
  "$jq_cmd" \
    --arg sid "$story_id" \
    '(.userStories[] | select(.id == $sid) | .passes) = false' \
    "$prd_file" >"$prd_file.tmp" && mv "$prd_file.tmp" "$prd_file"

  return $?
}

# Export functions for subshells
export -f worker_heartbeat_start worker_heartbeat_stop check_stale_heartbeats requeue_stale_stories
