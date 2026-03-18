#!/usr/bin/env bash
# lib/modes/mode_ops.sh — SPIRAL --benchmark, --rollback, --undo mode handlers
#
# Functions: handle_benchmark_mode, handle_rollback_mode, handle_undo_mode
# Each function returns 0 if its mode is inactive, or exits the process.

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

handle_benchmark_mode() {
  [[ -z "${BENCHMARK_STORY_ID:-}" ]] && return 0
  if [[ -z "$BENCHMARK_MODELS" ]]; then
    spiral_exit E101 "--models must be specified when using --benchmark"
  fi

  # Validate story ID exists in prd.json
  _BM_EXISTS=$("$JQ" --arg id "$BENCHMARK_STORY_ID" \
    '[.userStories[] | select(.id == $id)] | length' "$PRD_FILE" 2>/dev/null || echo "0")
  if [[ "$_BM_EXISTS" -eq 0 ]]; then
    spiral_exit E403 "$BENCHMARK_STORY_ID"
  fi

  _BM_TITLE=$("$JQ" -r --arg id "$BENCHMARK_STORY_ID" \
    '.userStories[] | select(.id == $id) | .title' "$PRD_FILE")

  BENCHMARK_RESULTS_FILE="$SCRATCH_DIR/benchmark-results.jsonl"
  BENCHMARK_DIR="$REPO_ROOT/.spiral-benchmark-${BENCHMARK_STORY_ID}"
  BENCHMARK_START_TS=$(date +%s)

  echo ""
  echo "  ╔══════════════════════════════════════════════════════╗"
  echo "  ║  [BENCHMARK] $BENCHMARK_STORY_ID"
  echo "  ║  $_BM_TITLE"
  echo "  ║  Models: $BENCHMARK_MODELS"
  echo "  ╠══════════════════════════════════════════════════════╣"
  echo "  ║  Results: $BENCHMARK_RESULTS_FILE"
  echo "  ╚══════════════════════════════════════════════════════╝"
  echo ""

  # Create benchmark directory
  mkdir -p "$BENCHMARK_DIR"

  # Convert model list to array
  IFS=',' read -ra MODELS_ARRAY <<<"$BENCHMARK_MODELS"

  # Track results for each model
  declare -A BM_RESULTS
  declare -A BM_DURATIONS

  for MODEL in "${MODELS_ARRAY[@]}"; do
    MODEL=$(echo "$MODEL" | xargs) # trim whitespace
    BM_WORKTREE="$BENCHMARK_DIR/worktree-$MODEL"
    BM_BRANCH="spiral-benchmark-${BENCHMARK_STORY_ID}-${MODEL}-$(date +%Y%m%d-%H%M%S)"
    BM_LOG="$BENCHMARK_DIR/log-${MODEL}.txt"
    BM_PRD="$BM_WORKTREE/prd.json"

    echo "  [benchmark] [$MODEL] Creating worktree..."

    # Remove existing worktree if present
    if [[ -d "$BM_WORKTREE" ]]; then
      git -C "$REPO_ROOT" worktree remove "$BM_WORKTREE" --force 2>/dev/null || rm -rf "$BM_WORKTREE"
    fi

    # Create isolated git worktree from current HEAD
    git -C "$REPO_ROOT" worktree add -b "$BM_BRANCH" "$BM_WORKTREE" HEAD 2>&1 | grep -v "Preparing worktree" || true

    # Copy prd.json and set only the target story to pending
    cp "$PRD_FILE" "$BM_PRD"
    _BM_UPDATED=$("$JQ" --arg id "$BENCHMARK_STORY_ID" \
      '(.userStories[] | select(.id == $id) | .passes) = false' "$BM_PRD") &&
      echo "$_BM_UPDATED" >"$BM_PRD"
    echo "  [benchmark] [$MODEL] Story set to pending"

    # Phase I: run ralph in the worktree with specified model
    echo "  [benchmark] [$MODEL] Phase I — running ralph..."
    BM_I_RC=0
    _BM_DRY_RUN_FLAG=""
    [[ "${DRY_RUN:-0}" -eq 1 ]] && _BM_DRY_RUN_FLAG="--dry-run"
    _BM_I_START=$(date +%s)

    # Run ralph with model override
    (cd "$BM_WORKTREE" && bash "$SPIRAL_RALPH" \
      "$RALPH_MAX_ITERS" --prd "$BM_PRD" --tool claude --model "$MODEL" $_BM_DRY_RUN_FLAG \
      2>&1) | tee "$BM_LOG" || BM_I_RC=$?

    _BM_I_ELAPSED=$(($(date +%s) - _BM_I_START))
    BM_DURATIONS[$MODEL]=$_BM_I_ELAPSED

    # Check story pass state from worktree prd.json
    _BM_STORY_PASSES=$("$JQ" -r --arg id "$BENCHMARK_STORY_ID" \
      '.userStories[] | select(.id == $id) | .passes' "$BM_PRD" 2>/dev/null || echo "false")

    BM_RESULTS[$MODEL]="$_BM_STORY_PASSES"
    echo "  [benchmark] [$MODEL] Result: $_BM_STORY_PASSES (${_BM_I_ELAPSED}s)"
  done

  # Phase J: Score with LLM judge and write results
  echo ""
  echo "  [benchmark] Phase J — scoring with LLM judge..."

  # Call benchmark judge script
  _BJ_RC=0
  if [[ -f "$SPIRAL_HOME/lib/observability/benchmark_judge.py" ]]; then
    # Build model results JSON
    _MODEL_RESULTS_JSON='{'
    _FIRST=1
    for MODEL in "${MODELS_ARRAY[@]}"; do
      MODEL=$(echo "$MODEL" | xargs)
      if [[ $_FIRST -eq 0 ]]; then
        _MODEL_RESULTS_JSON+=','
      fi
      _FIRST=0
      _PASSES="${BM_RESULTS[$MODEL]}"
      _DURATION="${BM_DURATIONS[$MODEL]}"
      _MODEL_RESULTS_JSON+="\"$MODEL\":{\"passes\":${_PASSES},\"duration_s\":${_DURATION}}"
    done
    _MODEL_RESULTS_JSON+='}'

    # Call judge with results
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/benchmark_judge.py" \
      --story-id "$BENCHMARK_STORY_ID" \
      --prd "$PRD_FILE" \
      --benchmark-dir "$BENCHMARK_DIR" \
      --results "$_MODEL_RESULTS_JSON" \
      --output "$BENCHMARK_RESULTS_FILE" 2>&1 || _BJ_RC=$?
  else
    echo "  [benchmark] WARNING: benchmark_judge.py not found; skipping scoring"
  fi

  # Write basic results if judge didn't
  if [[ ! -f "$BENCHMARK_RESULTS_FILE" ]]; then
    _BM_DURATION=$(($(date +%s) - BENCHMARK_START_TS))
    _RESULTS_LINE="{\"storyId\":\"$BENCHMARK_STORY_ID\",\"timestamp\":$(date +%s),\"models\":["
    _FIRST=1
    for MODEL in "${MODELS_ARRAY[@]}"; do
      MODEL=$(echo "$MODEL" | xargs)
      if [[ $_FIRST -eq 0 ]]; then
        _RESULTS_LINE+=','
      fi
      _FIRST=0
      _PASSES="${BM_RESULTS[$MODEL]}"
      _DURATION="${BM_DURATIONS[$MODEL]}"
      _RESULTS_LINE+="{\"name\":\"$MODEL\",\"passes\":${_PASSES},\"duration_s\":${_DURATION}}"
    done
    _RESULTS_LINE+="]}"
    echo "$_RESULTS_LINE" >>"$BENCHMARK_RESULTS_FILE"
  fi

  echo "  [benchmark] Results written to: $BENCHMARK_RESULTS_FILE"
  echo "  [benchmark] Benchmark complete"
  exit 0
}

handle_rollback_mode() {
  [[ -z "${ROLLBACK_STORY_ID:-}" ]] && return 0
  # Validate story ID exists in prd.json
  _RB_EXISTS=$("$JQ" --arg id "$ROLLBACK_STORY_ID" \
    '[.userStories[] | select(.id == $id)] | length' "$PRD_FILE" 2>/dev/null || echo "0")
  if [[ "$_RB_EXISTS" -eq 0 ]]; then
    spiral_exit E403 "$ROLLBACK_STORY_ID"
  fi

  # Guard: reject if working tree has uncommitted changes (tracked files only;
  # untracked files are excluded since they cannot conflict with a revert)
  _RB_DIRTY=$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null | grep -v '^??' || true)
  if [[ -n "$_RB_DIRTY" ]]; then
    spiral_exit E301 "Working tree has uncommitted changes. Commit or stash first."
  fi

  # Read _passedCommit from prd.json
  _RB_SHA=$("$JQ" -r --arg id "$ROLLBACK_STORY_ID" \
    '.userStories[] | select(.id == $id) | ._passedCommit // ""' "$PRD_FILE")
  if [[ -z "$_RB_SHA" || "$_RB_SHA" == "null" ]]; then
    spiral_exit E301 "Story '$ROLLBACK_STORY_ID' has no _passedCommit SHA recorded"
  fi

  _RB_TITLE=$("$JQ" -r --arg id "$ROLLBACK_STORY_ID" \
    '.userStories[] | select(.id == $id) | .title' "$PRD_FILE")

  echo ""
  echo "  ╔══════════════════════════════════════════════════════╗"
  echo "  ║  [ROLLBACK] $ROLLBACK_STORY_ID"
  echo "  ║  $_RB_TITLE"
  echo "  ╠══════════════════════════════════════════════════════╣"
  echo "  ║  Reverting commit: $_RB_SHA"
  echo "  ╚══════════════════════════════════════════════════════╝"
  echo ""

  # Run git revert (creates a new revert commit, preserves linear history)
  if ! git -C "$REPO_ROOT" revert --no-edit "$_RB_SHA"; then
    spiral_exit E301 "git revert failed for commit $_RB_SHA"
  fi

  # Reset story status in prd.json: clear passes, _passedCommit, _passedAt, _adrPath, _prUrl
  _RB_UPDATED=$("$JQ" --arg id "$ROLLBACK_STORY_ID" \
    '(.userStories[] | select(.id == $id)) |= (
      .passes = false | del(._passedCommit) | del(._passedAt) | del(._adrPath) | del(._prUrl)
    )' "$PRD_FILE")
  echo "$_RB_UPDATED" >"$PRD_FILE"

  log_spiral_event "rollback_complete" \
    "\"storyId\":\"$ROLLBACK_STORY_ID\",\"sha\":\"$_RB_SHA\""

  echo "  [rollback] Story '$ROLLBACK_STORY_ID' reset to pending"
  echo "  [rollback] Fields cleared: passes, _passedCommit, _passedAt, _adrPath, _prUrl"
  echo "  [rollback] Done. Use --replay $ROLLBACK_STORY_ID to re-implement."
  exit 0
}

handle_undo_mode() {
  [[ -z "${UNDO_STORY_ID:-}" ]] && return 0
  _UNDO_LIB="$SPIRAL_HOME/lib/spiral_undo.sh"
  if [[ ! -f "$_UNDO_LIB" ]]; then
    spiral_exit E103 "lib/spiral_undo.sh not found (SPIRAL_HOME=$SPIRAL_HOME)"
  fi
  source "$_UNDO_LIB"

  _UNDO_LOG_PATH="${SPIRAL_SCRATCH_DIR:-.spiral}/undo/${UNDO_STORY_ID}.jsonl"

  echo ""
  echo "  ╔══════════════════════════════════════════════════════╗"
  echo "  ║  [UNDO] $UNDO_STORY_ID"
  echo "  ║  Replaying undo log: $_UNDO_LOG_PATH"
  echo "  ╚══════════════════════════════════════════════════════╝"
  echo ""

  if ! undo_log_exists "$UNDO_STORY_ID"; then
    echo "[undo] No undo log found for '$UNDO_STORY_ID' at $_UNDO_LOG_PATH"
    echo "[undo] Nothing to undo — worktree is already clean, or use --rollback for committed stories."
    exit 0
  fi

  if undo_log_replay "$UNDO_STORY_ID"; then
    undo_log_cleanup "$UNDO_STORY_ID"
    echo "  [undo] Done. Story '$UNDO_STORY_ID' worktree restored."
    exit 0
  else
    spiral_exit E301 "Undo replay finished with errors for $UNDO_STORY_ID"
  fi
}
