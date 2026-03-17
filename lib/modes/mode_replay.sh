#!/usr/bin/env bash
# lib/modes/mode_replay.sh — SPIRAL --replay mode handler
#
# Re-runs a single story in an isolated worktree.
# Usage: source this file, then call handle_replay_mode
#
# Depends on globals: REPLAY_STORY_ID, REPLAY_FROM_PHASE, REPLAY_HINT,
#   PRD_FILE, SPIRAL_RALPH, RALPH_MAX_ITERS, SPIRAL_VALIDATE_CMD,
#   SCRATCH_DIR, REPO_ROOT, JQ, SPIRAL_PYTHON, SPIRAL_HOME, DRY_RUN,
#   SPIRAL_IMPL_TIMEOUT

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

handle_replay_mode() {
  [[ -z "${REPLAY_STORY_ID:-}" ]] && return 0

  # Validate story ID exists in prd.json
  _REPLAY_EXISTS=$("$JQ" --arg id "$REPLAY_STORY_ID" \
    '[.userStories[] | select(.id == $id)] | length' "$PRD_FILE" 2>/dev/null || echo "0")
  if [[ "$_REPLAY_EXISTS" -eq 0 ]]; then
    spiral_exit E403 "$REPLAY_STORY_ID"
  fi

  # Validate --from-phase letter (only I and V are valid for replay mode)
  if [[ -n "$REPLAY_FROM_PHASE" ]]; then
    case "$REPLAY_FROM_PHASE" in
      I | V) ;; # valid
      *)
        echo "[replay] ERROR: --from-phase '$REPLAY_FROM_PHASE' is invalid for replay mode."
        echo "[replay]   Valid phase letters: I (Phase I: Implement), V (Phase V: Validate)"
        exit $ERR_BAD_USAGE
        ;;
    esac
    echo "  [replay] --from-phase $REPLAY_FROM_PHASE: reusing existing worktree, skipping phases before $REPLAY_FROM_PHASE"
  fi

  _REPLAY_TITLE=$("$JQ" -r --arg id "$REPLAY_STORY_ID" \
    '.userStories[] | select(.id == $id) | .title' "$PRD_FILE")

  REPLAY_WORKTREE="$REPO_ROOT/.spiral-replay-${REPLAY_STORY_ID}"
  REPLAY_BRANCH="spiral-replay-${REPLAY_STORY_ID}-$(date +%Y%m%d-%H%M%S)"
  REPLAY_LOG="$SCRATCH_DIR/replay-${REPLAY_STORY_ID}.log"
  REPLAY_START_TS=$(date +%s)

  echo ""
  echo "  ╔══════════════════════════════════════════════════════╗"
  echo "  ║  [REPLAY] $REPLAY_STORY_ID"
  echo "  ║  $_REPLAY_TITLE"
  echo "  ╠══════════════════════════════════════════════════════╣"
  echo "  ║  Worktree: $REPLAY_WORKTREE"
  echo "  ║  Log:      $REPLAY_LOG"
  [[ -n "$REPLAY_FROM_PHASE" ]] && echo "  ║  From phase: $REPLAY_FROM_PHASE"
  [[ -n "$REPLAY_HINT" ]] && echo "  ║  Hint:       ${REPLAY_HINT:0:60}..."
  # US-362: Show previous invocation snapshot context if available
  _SNAP_JSON=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/invocation_snapshot.py" read "$SCRATCH_DIR" \
    --story-id "$REPLAY_STORY_ID" 2>/dev/null || true)
  if [[ -n "$_SNAP_JSON" && "$_SNAP_JSON" != "null" ]]; then
    _SNAP_MODEL=$(echo "$_SNAP_JSON" | "$JQ" -r '.model // "unknown"' 2>/dev/null || echo "unknown")
    _SNAP_RC=$(echo "$_SNAP_JSON" | "$JQ" -r '.rc // "N/A"' 2>/dev/null || echo "N/A")
    _SNAP_ITER=$(echo "$_SNAP_JSON" | "$JQ" -r '.iteration // 0' 2>/dev/null || echo "0")
    _SNAP_TS=$(echo "$_SNAP_JSON" | "$JQ" -r '.ts_start // "unknown"' 2>/dev/null || echo "unknown")
    echo "  ╠──────────────────────────────────────────────────────╣"
    echo "  ║  Previous snapshot:"
    echo "  ║    Model: $_SNAP_MODEL  RC: $_SNAP_RC  Iter: $_SNAP_ITER"
    echo "  ║    Started: $_SNAP_TS"
  fi
  echo "  ╚══════════════════════════════════════════════════════╝"
  echo ""

  # Worktree management: reuse on --from-phase, recreate otherwise
  REPLAY_PRD="$REPLAY_WORKTREE/prd.json"
  if [[ -n "$REPLAY_FROM_PHASE" && -d "$REPLAY_WORKTREE" ]]; then
    # Reuse the existing worktree; determine branch from git
    REPLAY_BRANCH=$(git -C "$REPLAY_WORKTREE" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "$REPLAY_BRANCH")
    echo "  [replay] Reusing existing worktree (--from-phase $REPLAY_FROM_PHASE): $REPLAY_WORKTREE"
    echo "  [replay] Branch: $REPLAY_BRANCH"
  else
    # Remove existing replay worktree if present (leftover from previous failed replay)
    if [[ -d "$REPLAY_WORKTREE" ]]; then
      echo "  [replay] Removing existing replay worktree: $REPLAY_WORKTREE"
      git -C "$REPO_ROOT" worktree remove "$REPLAY_WORKTREE" --force 2>/dev/null || rm -rf "$REPLAY_WORKTREE"
    fi

    # Create isolated git worktree from current HEAD
    echo "  [replay] Creating worktree from HEAD..."
    git -C "$REPO_ROOT" worktree add -b "$REPLAY_BRANCH" "$REPLAY_WORKTREE" HEAD

    # Copy prd.json to worktree; set only the target story to pending
    cp "$PRD_FILE" "$REPLAY_PRD"
    _UPDATED=$("$JQ" --arg id "$REPLAY_STORY_ID" \
      '(.userStories[] | select(.id == $id) | .passes) = false' "$REPLAY_PRD") &&
      echo "$_UPDATED" >"$REPLAY_PRD"
    echo "  [replay] Story $REPLAY_STORY_ID set to pending; all others preserved"
  fi

  # ── US-251: Track this replay attempt in _checkpoint.json _replayHistory ──
  if [[ -f "$CHECKPOINT_FILE" ]]; then
    _CKPT_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    _REPLAY_ENTRY="{\"timestamp\":\"$_CKPT_TS\",\"storyId\":\"$REPLAY_STORY_ID\",\"fromPhase\":\"${REPLAY_FROM_PHASE:-I}\",\"hint\":\"${REPLAY_HINT}\"}"
    _UPDATED_CKPT=$("$JQ" --argjson entry "$_REPLAY_ENTRY" \
      'if .["_replayHistory"] then .["_replayHistory"] += [$entry] else .["_replayHistory"] = [$entry] end' \
      "$CHECKPOINT_FILE" 2>/dev/null)
    if [[ -n "$_UPDATED_CKPT" ]]; then
      _CKPT_TMP=$(mktemp -p "$SCRATCH_DIR" 2>/dev/null || echo "$SCRATCH_DIR/.replay_ckpt.tmp")
      echo "$_UPDATED_CKPT" >"$_CKPT_TMP" && mv "$_CKPT_TMP" "$CHECKPOINT_FILE" 2>/dev/null || true
      echo "  [replay] Checkpoint updated with _replayHistory entry (fromPhase=${REPLAY_FROM_PHASE:-I})"
    fi
  fi

  # Phase I: run ralph in the worktree (skip if --from-phase V)
  REPLAY_I_RC=0
  if [[ "${REPLAY_FROM_PHASE:-I}" == "I" ]]; then
    echo ""
    echo "  [replay] Phase I — running ralph on $REPLAY_STORY_ID..."
    _REPLAY_DRY_RUN_FLAG=""
    [[ "${DRY_RUN:-0}" -eq 1 ]] && _REPLAY_DRY_RUN_FLAG="--dry-run"
    # Export hint so ralph.sh can inject it into the system prompt (US-251)
    export SPIRAL_REPLAY_HINT="${REPLAY_HINT:-}"
    _REPLAY_I_START=$(date +%s)
    if [[ "${SPIRAL_IMPL_TIMEOUT:-600}" -gt 0 ]] && command -v timeout &>/dev/null; then
      (cd "$REPLAY_WORKTREE" && timeout --kill-after=30 "${SPIRAL_IMPL_TIMEOUT}" bash "$SPIRAL_RALPH" \
        "$RALPH_MAX_ITERS" --prd "$REPLAY_PRD" --tool claude $_REPLAY_DRY_RUN_FLAG \
        2>&1) | tee "$REPLAY_LOG" || REPLAY_I_RC=$?
    else
      (cd "$REPLAY_WORKTREE" && bash "$SPIRAL_RALPH" \
        "$RALPH_MAX_ITERS" --prd "$REPLAY_PRD" --tool claude $_REPLAY_DRY_RUN_FLAG \
        2>&1) | tee "$REPLAY_LOG" || REPLAY_I_RC=$?
    fi
    unset SPIRAL_REPLAY_HINT
    _REPLAY_I_ELAPSED=$(($(date +%s) - _REPLAY_I_START))
    if [[ "$REPLAY_I_RC" -eq 124 ]]; then
      echo "  [replay] WARNING: Ralph timed out after ${_REPLAY_I_ELAPSED}s (limit: ${SPIRAL_IMPL_TIMEOUT}s)"
      log_spiral_event "phase_timeout" "\"phase\":\"I\",\"story_id\":\"$REPLAY_STORY_ID\",\"iteration\":0,\"duration_ms\":$((_REPLAY_I_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_IMPL_TIMEOUT}"
    fi
  else
    echo "  [replay] Phase I — SKIPPED (--from-phase $REPLAY_FROM_PHASE)"
  fi

  # Check story pass state from worktree prd.json
  _REPLAY_STORY_PASSES=$("$JQ" -r --arg id "$REPLAY_STORY_ID" \
    '.userStories[] | select(.id == $id) | .passes' "$REPLAY_PRD" 2>/dev/null || echo "false")

  # Phase V: validate in worktree
  echo ""
  echo "  [replay] Phase V — running validation in worktree..."
  REPLAY_V_RC=0
  (cd "$REPLAY_WORKTREE" && eval "$SPIRAL_VALIDATE_CMD" 2>&1) |
    tee -a "$REPLAY_LOG" || REPLAY_V_RC=$?

  # Determine overall result
  REPLAY_RESULT="fail"
  if [[ "$_REPLAY_STORY_PASSES" == "true" && "$REPLAY_V_RC" -eq 0 ]]; then
    REPLAY_RESULT="pass"
  fi

  REPLAY_END_TS=$(date +%s)
  REPLAY_DURATION=$((REPLAY_END_TS - REPLAY_START_TS))

  # Log event to spiral_events.jsonl
  log_spiral_event "replay_complete" \
    "\"storyId\":\"$REPLAY_STORY_ID\",\"result\":\"$REPLAY_RESULT\",\"duration_s\":$REPLAY_DURATION,\"fromPhase\":\"${REPLAY_FROM_PHASE:-I}\",\"log\":\"$REPLAY_LOG\""

  echo ""
  if [[ "$REPLAY_RESULT" == "pass" ]]; then
    echo "  ╔══════════════════════════════════════════════════════╗"
    echo "  ║  [REPLAY] PASSED: $REPLAY_STORY_ID"
    echo "  ║  Duration: ${REPLAY_DURATION}s | Log: $REPLAY_LOG"
    echo "  ╚══════════════════════════════════════════════════════╝"
    git -C "$REPO_ROOT" worktree remove "$REPLAY_WORKTREE" --force 2>/dev/null || true
    git -C "$REPO_ROOT" branch -D "$REPLAY_BRANCH" 2>/dev/null || true
    echo "  [replay] Worktree cleaned up (pass)"
    exit 0
  else
    echo "  ╔══════════════════════════════════════════════════════╗"
    echo "  ║  [REPLAY] FAILED: $REPLAY_STORY_ID"
    echo "  ║  Duration: ${REPLAY_DURATION}s | Log: $REPLAY_LOG"
    echo "  ║  Worktree: $REPLAY_WORKTREE (preserved for inspection)"
    echo "  ╚══════════════════════════════════════════════════════╝"
    echo "  [replay] Worktree preserved for inspection"
    spiral_exit E402 "$REPLAY_STORY_ID"
  fi
}
