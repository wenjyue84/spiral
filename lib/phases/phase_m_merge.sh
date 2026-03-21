#!/usr/bin/env bash
# lib/phases/phase_m_merge.sh — Phase M: MERGE
#
# Merges validated story candidates (from Phase S) into prd.json.
#
# Steps:
#   1. US-323: Goal-hijack detection (verify goals hash unchanged after Phase R)
#   2. Snapshot prd.json (backup before write)
#   3. Call lib/prd/merge_stories.py with validated candidates
#   4. Overflow: candidates that would push pending > SPIRAL_MAX_PENDING
#      are written to .spiral/_research_overflow.json for the next iteration
#   5. Post-merge assertions (IDs unique, DAG valid, story count bounded)
#
# Inputs:
#   .spiral/_validated_stories.json   — accepted candidates (from Phase S)
#   $PRD_FILE                         — prd.json to patch
#
# Outputs:
#   $PRD_FILE (patched)
#   .spiral/_research_overflow.json   — excess stories held for next iteration
#
# Config vars:
#   SPIRAL_MAX_PENDING   — max allowed pending stories (default: 50)

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_merge() {
  # ── US-323: Goal-hijack detection — verify goals hash unchanged after Phase R ──
  if [[ -f "$_GOALS_HASH_FILE" && -f "$PRD_FILE" ]]; then
    _GOALS_HASH_BEFORE=$(cat "$_GOALS_HASH_FILE")
    _GOALS_HASH_AFTER=$("$JQ" -S '.goals // []' "$PRD_FILE" 2>/dev/null | sha256sum | awk '{print $1}')
    if [[ "$_GOALS_HASH_BEFORE" != "$_GOALS_HASH_AFTER" ]]; then
      echo ""
      echo "  [SECURITY] GOAL-HIJACK DETECTED: prd.json goals changed during Phase R!"
      echo "  [SECURITY] Expected hash: $_GOALS_HASH_BEFORE"
      echo "  [SECURITY] Actual hash:   $_GOALS_HASH_AFTER"
      # Compute diff for human review using the pre-Phase-R snapshot
      _GOALS_DIFF_AFTER="$SCRATCH_DIR/_goals_after.json"
      "$JQ" -S '.goals // []' "$PRD_FILE" >"$_GOALS_DIFF_AFTER" 2>/dev/null
      _GOALS_DIFF=$(diff "$_GOALS_SNAPSHOT_FILE" "$_GOALS_DIFF_AFTER" 2>/dev/null || true)
      echo "  [SECURITY] Goals diff:"
      echo "$_GOALS_DIFF" | head -20
      # Log to security-audit.jsonl
      _SECURITY_AUDIT="$SCRATCH_DIR/security-audit.jsonl"
      _HIJACK_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      _GOALS_DIFF_ESC=$(echo "$_GOALS_DIFF" | head -20 | "$JQ" -Rs '.' 2>/dev/null || echo '""')
      printf '{"ts":"%s","event":"goal_hijack_detected","iteration":%d,"hash_before":"%s","hash_after":"%s","diff":%s}\n' \
        "$_HIJACK_TS" "$SPIRAL_ITER" "$_GOALS_HASH_BEFORE" "$_GOALS_HASH_AFTER" "$_GOALS_DIFF_ESC" \
        >>"$_SECURITY_AUDIT" 2>/dev/null || true
      log_spiral_event "goal_hijack_detected" \
        "\"iteration\":$SPIRAL_ITER,\"hash_before\":\"$_GOALS_HASH_BEFORE\",\"hash_after\":\"$_GOALS_HASH_AFTER\""
      echo "  [SECURITY] Phase M ABORTED — goals integrity compromised. Review security-audit.jsonl"
      # Skip Phase M by writing checkpoint
      write_checkpoint "$SPIRAL_ITER" "M"
      ADDED=0
      _GOALS_HIJACK_ABORT=1
    fi
  fi

  # ── Phase M: MERGE ──────────────────────────────────────────────────────────
  PHASE="M"
  write_active_status "M" 40 # US-311
  print_phase_banner "M" "MERGE — deduplicating and patching prd.json..."
  log_spiral_event "phase_start" "\"phase\":\"M\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "M" "start"
  _PHASE_TS_M=$(date +%s)
  run_phase_hook PRE "M" || return 1

  if checkpoint_phase_done "M"; then
    echo "  [M] Skipping (checkpoint: already done this iter)"
  else
    # ── Phase M backup: snapshot prd.json before merge ──────────────────────
    if [[ -f "$PRD_FILE" ]]; then
      mkdir -p "$SCRATCH_DIR/prd-backups"
      cp "$PRD_FILE" "$SCRATCH_DIR/prd-backups/prd-iter${SPIRAL_ITER}.json"
      # Keep only last 10 backups
      ls -t "$SCRATCH_DIR/prd-backups"/ | tail -n +11 | xargs -I{} rm -f "$SCRATCH_DIR/prd-backups/{}"
    fi

    # ── Phase M: use _validated_stories.json from Phase S if available ────────
    _M_RESEARCH_INPUT="$RESEARCH_OUTPUT"
    if [[ -f "$VALIDATED_OUTPUT" ]] && "$JQ" -e '.stories' "$VALIDATED_OUTPUT" >/dev/null 2>&1; then
      _M_RESEARCH_INPUT="$VALIDATED_OUTPUT"
      echo "  [M] Using Phase S validated stories: $VALIDATED_OUTPUT"
    fi

    # ── Phase M pre-check: validate research input schema ─────────────────
    if [[ ! -f "$_M_RESEARCH_INPUT" ]]; then
      echo "  [M] WARNING: $_M_RESEARCH_INPUT missing — skipping merge"
      write_checkpoint "$SPIRAL_ITER" "M"
    elif ! "$JQ" '.' "$_M_RESEARCH_INPUT" >/dev/null 2>&1; then
      echo "  [M] WARNING: $_M_RESEARCH_INPUT is not valid JSON — skipping merge"
      write_checkpoint "$SPIRAL_ITER" "M"
    elif ! "$JQ" -e '.stories' "$_M_RESEARCH_INPUT" >/dev/null 2>&1; then
      echo "  [M] WARNING: $_M_RESEARCH_INPUT missing 'stories' key — skipping merge"
      write_checkpoint "$SPIRAL_ITER" "M"
    else
      # ── Phase M validated — proceed with merge ──────────────────────────────

      OVERFLOW_FILE="$SCRATCH_DIR/_research_overflow.json"
      BEFORE_TOTAL=$("$JQ" '[.userStories | length] | .[0]' "$PRD_FILE")
      if [[ -n "$SPIRAL_CORE_BIN" ]]; then
        "$SPIRAL_CORE_BIN" merge \
          --prd "$PRD_FILE" \
          --research "$_M_RESEARCH_INPUT" \
          --test-stories "$TEST_OUTPUT" \
          --overflow-in "$OVERFLOW_FILE" \
          --overflow-out "$OVERFLOW_FILE" \
          --max-new 50 \
          --max-pending "$SPIRAL_MAX_PENDING" \
          ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || true
      else
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/merge_stories.py" \
          --prd "$PRD_FILE" \
          --research "$_M_RESEARCH_INPUT" \
          --test-stories "$TEST_OUTPUT" \
          --overflow-in "$OVERFLOW_FILE" \
          --overflow-out "$OVERFLOW_FILE" \
          --max-new 50 \
          --max-pending "$SPIRAL_MAX_PENDING" \
          ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || true
      fi
      AFTER_TOTAL=$("$JQ" '[.userStories | length] | .[0]' "$PRD_FILE")
      ADDED=$((AFTER_TOTAL - BEFORE_TOTAL))
      echo "  [M] Merge complete — $ADDED new stories added (total: $AFTER_TOTAL)"

      write_checkpoint "$SPIRAL_ITER" "M"

      # ── Tier 2: Post-merge assertions ──────────────────────────────────────
      spiral_assert_ids_unique "$PRD_FILE"
      spiral_assert_deps_dag "$PRD_FILE"
      spiral_assert_story_count_bounded "$PRD_FILE"
      spiral_assert_merge_no_story_loss "$BEFORE_TOTAL" "$AFTER_TOTAL"
      spiral_assert_pending_bounded "$PRD_FILE"
      spiral_assert_decomposition_integrity "$PRD_FILE"
      spiral_assert_dependency_completion_order "$PRD_FILE"

      # ── Phase M: Enforce pending story cap (evict to candidate_us.json) ──────
      _CANDIDATE_US="$SCRATCH_DIR/candidate_us.json"
      if [[ "${SPIRAL_PRD_PENDING_CAP:-50}" -gt 0 ]]; then
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/rebalance_pending.py" \
          --prd "$PRD_FILE" \
          --candidate-out "$_CANDIDATE_US" \
          --overflow-out "$OVERFLOW_FILE" \
          --max-pending "${SPIRAL_PRD_PENDING_CAP:-50}" || true
      fi

      # ── Phase M: Detect file conflicts between pending stories ────────────
      _CONFLICT_LOG="$SCRATCH_DIR/conflict_report.jsonl"
      echo "  [M] Detecting file conflicts between pending stories..."
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/conflict_detector.py" \
        --prd "$PRD_FILE" \
        --log-file "$_CONFLICT_LOG"
      _CONFLICT_EXIT=$?

      if [[ $_CONFLICT_EXIT -eq 1 ]]; then
        echo ""
        echo "  [CONFLICT] File collisions detected across sub-projects!"
        if [[ -f "$SCRATCH_DIR/.spiral/merge_conflicts.json" ]]; then
          "$JQ" '.[]' "$SCRATCH_DIR/.spiral/merge_conflicts.json" | while read -r conflict; do
            _FILE=$(echo "$conflict" | "$JQ" -r '.file_path')
            _PROJECTS=$(echo "$conflict" | "$JQ" -r '.sub_projects | join(", ")')
            echo "  [CONFLICT] File $_FILE modified by sub-projects: $_PROJECTS"
          done
        fi
        echo "  [CONFLICT] Phase M ABORTED — manual resolution required."
        write_checkpoint "$SPIRAL_ITER" "M"
        ADDED=0
        return 1
      fi

      # ── Phase M: Infer dependencies from filesTouch overlap ─────────────────
      _HINTS_FILE="$SCRATCH_DIR/_dependency_hints.json"
      echo "  [M] Inferring dependencies from filesTouch overlap..."
      SPIRAL_AUTO_INFER_DEPS="$SPIRAL_AUTO_INFER_DEPS" \
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/tools/infer_dependencies.py" \
        --prd "$PRD_FILE" \
        --out-hints "$_HINTS_FILE" || true

    fi # end validation else
  fi

  # ── progress.txt rotation (before Phase I) ────────────────────────────────
  if [[ "$SPIRAL_PROGRESS_MAX_LINES" -gt 0 && -f "$REPO_ROOT/progress.txt" ]]; then
    _PROGRESS_LINES=$(wc -l <"$REPO_ROOT/progress.txt" 2>/dev/null || echo 0)
    if [[ "$_PROGRESS_LINES" -gt "$SPIRAL_PROGRESS_MAX_LINES" ]]; then
      _PROGRESS_ARCHIVE="$REPO_ROOT/progress-$(date +%Y%m%d-%H%M%S).txt"
      mv "$REPO_ROOT/progress.txt" "$_PROGRESS_ARCHIVE"
      touch "$REPO_ROOT/progress.txt"
      echo "  [spiral] progress.txt rotated ($_PROGRESS_LINES lines → $(basename "$_PROGRESS_ARCHIVE"))"
    fi
  fi

  run_phase_hook POST "M" || true
  _PHASE_DUR_M=$(($(date +%s) - _PHASE_TS_M))
  log_spiral_event "phase_end" "\"phase\":\"M\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_M,\"model\":\"$SPIRAL_MERGE_MODEL\""
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-phase --phase M --duration-s "$_PHASE_DUR_M" --iteration "$SPIRAL_ITER" 2>/dev/null || true
  notify_webhook "M" "end"
}
