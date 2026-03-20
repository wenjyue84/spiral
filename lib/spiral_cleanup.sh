#!/usr/bin/env bash
# lib/spiral_cleanup.sh -- Signal handlers and cleanup functions
#
# Functions: _spiral_cleanup, cleanup, write_active_status
#
# Globals read: SPIRAL_ITER, PHASE, SCRATCH_DIR, CHECKPOINT_FILE,
#   REPO_ROOT, WATCHDOG_PID, _ACTIVE_STORY_ID, _ACTIVE_STORY_TITLE,
#   JQ, CHILD_PIDS

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# Signal handler for graceful interrupt (SIGINT/SIGTERM)
_spiral_cleanup() {
  local sig="${1:-INT}"
  echo ""
  echo "  [SPIRAL] Interrupted (signal $sig) at iter $SPIRAL_ITER phase $PHASE"
  log_spiral_event "error" "\"message\":\"Interrupted by signal $sig\",\"context\":\"iter=$SPIRAL_ITER phase=$PHASE\"" 2>/dev/null || true

  # Kill tracked child processes (ralph, parallel workers, etc.)
  for pid in "${CHILD_PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done

  # Write checkpoint atomically if we're mid-iteration
  if [[ -n "$PHASE" && "$SPIRAL_ITER" -gt 0 ]]; then
    local _ckpt_tmp
    _ckpt_tmp=$(mktemp -p "$SCRATCH_DIR" 2>/dev/null || echo "$SCRATCH_DIR/.checkpoint.tmp")
    printf '{"iter":%d,"phase":"%s","ts":"%s"}\n' \
      "$SPIRAL_ITER" "$PHASE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$_ckpt_tmp" 2>/dev/null || true
    mv "$_ckpt_tmp" "$CHECKPOINT_FILE" 2>/dev/null || true
    echo "  [SPIRAL] Checkpoint saved at iter=$SPIRAL_ITER phase=$PHASE"
  fi

  echo "  [SPIRAL] Interrupted at iter $SPIRAL_ITER phase $PHASE — run again to resume"

  # Call the regular cleanup for worktrees, etc.
  cleanup
  exit 130 # Standard exit code for SIGINT
}

# Regular cleanup (EXIT)
cleanup() {
  echo ""
  echo "  [cleanup] Shutting down child processes..."
  # Kill memory watchdog
  [[ -n "$WATCHDOG_PID" ]] && kill "$WATCHDOG_PID" 2>/dev/null || true
  # Two-phase kill: SIGTERM first, wait, then SIGKILL stragglers
  local child_pids
  child_pids=$(jobs -p 2>/dev/null) || true
  if [[ -n "$child_pids" ]]; then
    echo "$child_pids" | xargs kill 2>/dev/null || true
    sleep 2
    echo "$child_pids" | xargs kill -9 2>/dev/null || true
  fi
  # Clean up orphaned git worktrees
  if [[ -d "$REPO_ROOT/.spiral-workers" ]]; then
    for wt in "$REPO_ROOT/.spiral-workers"/worker-*; do
      [[ -d "$wt" ]] && git -C "$REPO_ROOT" worktree remove "$wt" --force 2>/dev/null || true
    done
    rm -rf "$REPO_ROOT/.spiral-workers" 2>/dev/null || true
  fi
  # Prune stale worktree admin records left by crashed/interrupted workers (US-080)
  git -C "$REPO_ROOT" worktree prune 2>/dev/null || true
  # Clean up docker lock dirs
  rm -rf /tmp/spiral-docker-lock-* 2>/dev/null || true
  # Clean up memory pressure signal files
  rm -f "$SCRATCH_DIR/_memory_pressure.json" "$SCRATCH_DIR/_low_power_active" 2>/dev/null || true
  rm -f "$SCRATCH_DIR"/_worker_pause_* 2>/dev/null || true
  # US-311: Delete active status file on clean exit (crash detection: file persists if killed)
  rm -f "$SCRATCH_DIR/_active_status.json" 2>/dev/null || true
  echo "  [cleanup] Done."
}

# ── US-311: Write active status file ─────────────────────────────────────────
# Writes .spiral/_active_status.json atomically at each phase start.
# Globals read: _ACTIVE_STORY_ID, _ACTIVE_STORY_TITLE (optional story context)
write_active_status() {
  local phase="$1"
  local pct_done="${2:-0}"
  local tmp_file
  tmp_file=$(mktemp -p "$SCRATCH_DIR" _active_status_XXXXXX.json 2>/dev/null || echo "$SCRATCH_DIR/_active_status_$$.json")
  if [[ -n "${_ACTIVE_STORY_ID:-}" ]]; then
    "$JQ" -n \
      --arg phase "$phase" \
      --argjson iter "${SPIRAL_ITER:-0}" \
      --argjson ts "$(date +%s)" \
      --argjson pct "$pct_done" \
      --arg sid "$_ACTIVE_STORY_ID" \
      --arg stitle "${_ACTIVE_STORY_TITLE:-}" \
      '{phase:$phase,iteration:$iter,started_at:$ts,pct_done:$pct,story_id:$sid,story_title:$stitle}' \
      >"$tmp_file" 2>/dev/null || true
  else
    "$JQ" -n \
      --arg phase "$phase" \
      --argjson iter "${SPIRAL_ITER:-0}" \
      --argjson ts "$(date +%s)" \
      --argjson pct "$pct_done" \
      '{phase:$phase,iteration:$iter,started_at:$ts,pct_done:$pct}' \
      >"$tmp_file" 2>/dev/null || true
  fi
  mv "$tmp_file" "$SCRATCH_DIR/_active_status.json" 2>/dev/null || true
}

