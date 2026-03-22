#!/usr/bin/env bash
# lib/phases/phase_c_check_done.sh — Phase P+C: PUSH + CHECK DONE
#
# Phase P: pushes commits to origin/main
# Phase C: evaluates whether all stories have passed and the test suite is green.
# Decides whether to exit successfully or loop back to Phase R.
#
# Steps:
#   1. Phase P: push to origin/main (best-effort)
#   2. Phase C: Call lib/prd/check_done.py — returns 0 if all stories pass, 1 otherwise
#   3. If done: print velocity summary, run SPIRAL_ON_COMPLETE hook, exit 0
#   4. If not done: print remaining story count + velocity estimate, loop
#
# Inputs:
#   $PRD_FILE        — prd.json (reads passes fields)
#   $SPIRAL_ITER     — current iteration number
#   $MAX_SPIRAL_ITERS — max allowed iterations
#
# Outputs:
#   exit 0           — all done (calls exit directly)
#   returns normally — pending stories remain (caller loops back to Phase R)
#
# Config vars:
#   SPIRAL_ON_COMPLETE   — shell command to run on successful completion

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_check_done() {
  # ── Phase P: PUSH ──────────────────────────────────────────────────────────
  echo ""
  if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
    echo "  [Phase P] PUSH — skipped (--dry-run)"
  else
    echo "  [Phase P] PUSH — pushing commits to origin/main..."
    if git -C "$REPO_ROOT" push origin main 2>&1; then
      echo "  [P] Pushed to origin/main successfully"
    else
      echo "  [P] WARNING: Push to origin/main failed (check remote/connectivity)"
    fi
  fi

  # ── Phase C: CHECK DONE ─────────────────────────────────────────────────────
  PHASE="C"
  write_active_status "C" 95 # US-311
  print_phase_banner "C" "CHECK DONE..."
  log_spiral_event "phase_start" "\"phase\":\"C\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "C" "start"
  _PHASE_TS_C=$(date +%s)

  # ── US-227: Promote exhausted stories to DLQ state ────────────────────────
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/main.py" dlq promote 2>/dev/null || true

  _CHECK_DONE_RC=0
  if [[ -n "$SPIRAL_CORE_BIN" ]]; then
    "$SPIRAL_CORE_BIN" check-done \
      --prd "$PRD_FILE" \
      --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" || _CHECK_DONE_RC=$?
  else
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/check_done.py" \
      --prd "$PRD_FILE" \
      --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
      --skip-ids "${SPIRAL_SKIP_STORY_IDS:-}" || _CHECK_DONE_RC=$?
  fi
  if [[ "$_CHECK_DONE_RC" -eq 0 ]]; then
    rm -f "$CHECKPOINT_FILE"
    # ── US-313: Colored complete banner ────────────────────────────────────
    echo ""
    if [[ "$_USE_COLOR" -eq 1 ]]; then
      printf "  ${_C_GREEN}╔══════════════════════════════════════════════════════╗${_C_RESET}\n"
      printf "  ${_C_GREEN}║   *** SPIRAL COMPLETE! ***                           ║${_C_RESET}\n"
      printf "  ${_C_GREEN}║   All stories implemented and tests passing.         ║${_C_RESET}\n"
      printf "  ${_C_GREEN}║   Iterations: %s / %s${_C_RESET}\n" "$SPIRAL_ITER" "$MAX_SPIRAL_ITERS"
      printf "  ${_C_GREEN}╚══════════════════════════════════════════════════════╝${_C_RESET}\n"
    else
      echo "  ╔══════════════════════════════════════════════════════╗"
      echo "  ║   *** SPIRAL COMPLETE! ***                           ║"
      echo "  ║   All stories implemented and tests passing.         ║"
      echo "  ║   Iterations: $SPIRAL_ITER / $MAX_SPIRAL_ITERS"
      echo "  ╚══════════════════════════════════════════════════════╝"
    fi
    # Print the iteration summary banner for the completed run (US-313)
    print_iter_summary_banner "$SPIRAL_ITER" "$DONE" "0" "$TOTAL" "0" "0"

    if [[ -f "$REPO_ROOT/results.tsv" ]]; then
      echo ""
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/spiral_report.py" --results "$REPO_ROOT/results.tsv" 2>/dev/null || true
      if [[ "${SPIRAL_DASHBOARD_HTML:-false}" == "true" ]]; then
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/ui/spiral_dashboard.py" \
          --prd "$PRD_FILE" --results "$REPO_ROOT/results.tsv" \
          --retries "$REPO_ROOT/retry-counts.json" --progress "$REPO_ROOT/progress.txt" \
          --output "$SCRATCH_DIR/dashboard.html" --open 2>/dev/null || true
      fi
    fi

    # ── US-192: Print calibration summary if calibration data exists ──────────
    if [[ -f "calibration.jsonl" ]]; then
      echo ""
      echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
      echo "  📊 CALIBRATION SUMMARY (Actual vs Estimated Complexity)"
      echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/routing/calibration_tracker.py" report --calibration-file "calibration.jsonl" 2>/dev/null || true
    fi

    SESSION_END=$(date +%s)
    SESSION_MINUTES=$(((SESSION_END - SESSION_START) / 60))
    echo "  Session: ${SESSION_MINUTES}m total, $SPIRAL_ITER iterations"

    # ── Write iteration summary (US-039) ──────────────────────────────────
    write_iter_summary

    # ── Create annotated run-complete git tag (US-137) ────────────────────
    create_run_tag

    # ── Cleanup transient workspace artifacts (US-136) ────────────────────
    cleanup_workspace

    # ── Run SPIRAL_ON_COMPLETE hook (US-049) ──────────────────────────────
    if [[ -n "${SPIRAL_ON_COMPLETE:-}" ]]; then
      _HOOK_PREVIEW="${SPIRAL_ON_COMPLETE:0:80}"
      echo "  [hook] Running SPIRAL_ON_COMPLETE: ${_HOOK_PREVIEW}..."
      if eval "$SPIRAL_ON_COMPLETE"; then
        echo "  [hook] SPIRAL_ON_COMPLETE succeeded"
      else
        echo "  [hook] WARNING: SPIRAL_ON_COMPLETE exited with code $? (ignored)"
      fi
    fi

    # ── Emit OTel root span for completed run (US-184) ─────────────────────
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-run \
      --passes "$DONE" --story-count "$TOTAL" 2>/dev/null || true

    # ── Auto SemVer release from conventional commits (US-190) ───────────
    if [[ "${SPIRAL_AUTO_RELEASE:-false}" == "true" ]]; then
      echo ""
      echo "  [auto-release] Calculating SemVer bump from conventional commits..."
      _RELEASE_FLAGS=""
      [[ "${SPIRAL_GIT_PUSH:-false}" == "true" ]] && _RELEASE_FLAGS="--push"
      _RELEASE_RC=0
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/auto_release.py" \
        --prd "$PRD_FILE" \
        --repo "$REPO_ROOT" \
        ${_RELEASE_FLAGS} || _RELEASE_RC=$?
      if [[ "$_RELEASE_RC" -eq 2 ]]; then
        echo "  [auto-release] No releasable commits — skipping tag creation"
      elif [[ "$_RELEASE_RC" -ne 0 ]]; then
        echo "  [auto-release] WARNING: auto-release exited with code $_RELEASE_RC (ignored)"
      fi
    fi

    # ── Invoke run-completion plugin hook (US-194) ─────────────────────────
    if [[ -n "${PLUGIN_HOOKS[run-completion]:-}" ]]; then
      _FAILED=$((TOTAL - DONE))
      _SKIPPED=0
      if [[ -f "$REPO_ROOT/retry-counts.json" ]]; then
        _SKIPPED=$("$JQ" "[to_entries[] | select(.value >= ${SPIRAL_MAX_RETRIES:-3})] | length" "$REPO_ROOT/retry-counts.json" 2>/dev/null || echo "0")
      fi
      _RUN_DURATION=$((SESSION_END - SESSION_START))
      # Pass run stats as extra JSON context so hook scripts can read from stdin
      run_plugin_hooks "run-completion" "POST" "" \
        "\"total_stories\":$TOTAL,\"passed_stories\":$DONE,\"failed_stories\":$_FAILED,\"skipped_stories\":${_SKIPPED:-0},\"duration_seconds\":$_RUN_DURATION" 2>/dev/null || true
    fi

    exit 0
  fi

  # Clear checkpoint before next iteration (crash in next iter starts that iter fresh)
  rm -f "$CHECKPOINT_FILE"
  prd_stats
  echo "  [C] Not done yet — $PENDING stories remaining"
  if [[ "${RALPH_PROGRESS:-0}" -gt 0 ]]; then
    ITERS_LEFT=$(((PENDING + RALPH_PROGRESS - 1) / RALPH_PROGRESS))
    echo "  [C] Velocity: ~${RALPH_PROGRESS} stories/iter | ~${ITERS_LEFT} more iters to completion"
  fi

  # ── Tier 2: Full re-validation between iterations ──────────────────────
  spiral_assert_prd_valid "$PRD_FILE"
  spiral_assert_no_orphan_tmpfiles
  spiral_assert_iteration_progress "${ZERO_PROGRESS_COUNT:-0}" "${SPIRAL_CONSECUTIVE_FAIL_ABORT:-3}"
  spiral_assert_checkpoint_coherent "$SPIRAL_ITER"
  spiral_assert_pending_bounded "$PRD_FILE"

  # Reset phase order tracker for next iteration
  rm -f "${SCRATCH_DIR:-/tmp}/_last_phase"

  # ── Write iteration summary (US-039) ──────────────────────────────────
  write_iter_summary

  # ── US-602: Record iteration metrics to SQLite time-series store ──────
  "$SPIRAL_PYTHON" - <<PYEOF 2>/dev/null || true
import sys
sys.path.insert(0, "$SPIRAL_HOME")
from lib.dashboard.timeseries_store import record_iteration_from_results_tsv
from pathlib import Path
record_iteration_from_results_tsv(
    iteration_n=$SPIRAL_ITER,
    results_tsv=Path("$REPO_ROOT/.spiral/results.tsv"),
    db_path=Path("$REPO_ROOT/.spiral/dashboard.db"),
)
PYEOF

  # ── Write UI progress snapshot ────────────────────────────────────────
  _SNAP_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  _SNAP_DONE=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE" 2>/dev/null || echo "$DONE")
  _SNAP_PENDING=$("$JQ" '[.userStories[] | select(.passes != true)] | length' "$PRD_FILE" 2>/dev/null || echo "$PENDING")
  _SNAP_TOTAL=$("$JQ" '.userStories | length' "$PRD_FILE" 2>/dev/null || echo "$TOTAL")
  printf '{"ts":"%s","iter":%d,"done":%s,"pending":%s,"total":%s,"added":%d}\n' \
    "$_SNAP_TS" "$SPIRAL_ITER" "$_SNAP_DONE" "$_SNAP_PENDING" "$_SNAP_TOTAL" "${ADDED:-0}" \
    >>"$SCRATCH_DIR/ui-progress-history.jsonl" 2>/dev/null || true

  # Also re-register with UI (keeps lastSeen fresh and handles UI restart)
  if command -v curl &>/dev/null && [[ -n "${_UI_PROJECT_NAME:-}" ]]; then
    curl -sf -X POST "${_UI_BASE:-http://localhost:5299}/api/register-project" \
      -H "Content-Type: application/json" \
      -d "{\"name\":\"${_UI_PROJECT_NAME}\",\"root\":\"${REPO_ROOT}\"}" \
      >/dev/null 2>&1 || true
  fi

  # ── Self-versioning: bump SKILL.md patch version after each iteration ──────
  # Activates only when SPIRAL is running on its own project directory.
  if [[ "$REPO_ROOT" == "$SPIRAL_HOME" || "$SPIRAL_HOME" == "$REPO_ROOT" ]]; then
    _SKILL_MD="$SPIRAL_HOME/SKILL.md"
    if [[ -f "$_SKILL_MD" ]]; then
      _PREV_VER=$(grep '^version:' "$_SKILL_MD" | head -1 | awk '{print $2}')
      "$SPIRAL_PYTHON" -c "
import re, sys
path = sys.argv[1]
text = open(path, encoding='utf-8').read()
def bump(m):
    v = m.group(1).split('.')
    v[-1] = str(int(v[-1]) + 1)
    return 'version: ' + '.'.join(v)
text = re.sub(r'^version: (\S+)', bump, text, flags=re.MULTILINE)
open(path, 'w', encoding='utf-8').write(text)
" "$_SKILL_MD" 2>/dev/null || true
      _NEW_VER=$(grep '^version:' "$_SKILL_MD" | head -1 | awk '{print $2}')
      if [[ -n "$_NEW_VER" && "$_NEW_VER" != "$_PREV_VER" ]]; then
        echo "  [skill] SPIRAL skill version bumped: ${_PREV_VER} → ${_NEW_VER}"
        # Sync to .claude/skills/ copy
        _CLAUDE_SKILL="$HOME/.claude/skills/spiral/SKILL.md"
        if [[ -f "$_CLAUDE_SKILL" ]]; then
          cp "$_SKILL_MD" "$_CLAUDE_SKILL"
          echo "  [skill] Synced to $(basename "$(dirname "$_CLAUDE_SKILL")")/SKILL.md"
        fi
      fi
    fi
  fi

  # ── Iteration summary banner (US-313) ───────────────────────────────────
  ITER_END=$(date +%s)
  ITER_DURATION=$((ITER_END - ITER_START))
  ITER_MINUTES=$((ITER_DURATION / 60))
  # Print velocity line before main banner (supplementary phase timing info)
  if [[ "${RALPH_PROGRESS:-0}" -gt 0 && "$ITER_DURATION" -gt 0 ]]; then
    VEL=$(awk "BEGIN {printf \"%.1f\", ${RALPH_PROGRESS} / ($ITER_DURATION / 3600.0)}")
    echo "  [C] Velocity: ${VEL} stories/hour | Phases: R=${_PHASE_DUR_R}s T=${_PHASE_DUR_T}s M=${_PHASE_DUR_M}s I=${_PHASE_DUR_I}s V=${_PHASE_DUR_V}s C=${_PHASE_DUR_C}s"
  fi
  print_iter_summary_banner "$SPIRAL_ITER" "$DONE" "$PENDING" "$TOTAL" "$ITER_MINUTES" "$ITER_DURATION"

  # ── Generate & open iteration dashboard ─────────────────────────────────────
  if [[ -f "$REPO_ROOT/results.tsv" ]] && [[ "${SPIRAL_DASHBOARD_HTML:-false}" == "true" ]]; then
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/ui/spiral_dashboard.py" \
      --prd "$PRD_FILE" --results "$REPO_ROOT/results.tsv" \
      --retries "$REPO_ROOT/retry-counts.json" --progress "$REPO_ROOT/progress.txt" \
      --output "$SCRATCH_DIR/dashboard.html" --open 2>/dev/null || true
  fi

  # ── Adaptive cooldown under memory pressure ─────────────────────────────────
  if [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]]; then
    _PRESSURE_LVL=$(spiral_pressure_level)
    if [[ "$_PRESSURE_LVL" -ge 2 ]]; then
      _COOLDOWN=$((_PRESSURE_LVL * 15))
      echo "  [memory] Pressure cooldown: ${_COOLDOWN}s (level $_PRESSURE_LVL)"
      spiral_log_low_power "Inter-iteration cooldown: ${_COOLDOWN}s (level $_PRESSURE_LVL, iter $SPIRAL_ITER)"
      sleep "$_COOLDOWN"
    fi
  fi

  # ── Time limit check — stop cleanly after completing this iteration ────────
  if [[ "$SESSION_DEADLINE" -gt 0 ]]; then
    _NOW_TS=$(date +%s)
    _REMAINING_SECS=$((SESSION_DEADLINE - _NOW_TS))
    if [[ "$_REMAINING_SECS" -le 0 ]]; then
      echo "  [time] Time limit of ${TIME_LIMIT_MINS}m reached — stopping after iteration $SPIRAL_ITER"
      echo ""
      prd_stats
      SESSION_END=$(date +%s)
      SESSION_MINUTES=$(((SESSION_END - SESSION_START) / 60))
      echo ""
      echo "  ╔══════════════════════════════════════════════════════╗"
      echo "  ║  SPIRAL stopped: time limit reached (${TIME_LIMIT_MINS}m)         ║"
      echo "  ║  Stories: $DONE/$TOTAL complete ($PENDING pending)   ║"
      echo "  ║  Session: ${SESSION_MINUTES}m, $SPIRAL_ITER iterations              ║"
      echo "  ╚══════════════════════════════════════════════════════╝"
      if [[ -f "$REPO_ROOT/results.tsv" ]]; then
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/spiral_report.py" --results "$REPO_ROOT/results.tsv" 2>/dev/null || true
        if [[ "${SPIRAL_DASHBOARD_HTML:-false}" == "true" ]]; then
          "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/ui/spiral_dashboard.py" \
            --prd "$PRD_FILE" --results "$REPO_ROOT/results.tsv" \
            --retries "$REPO_ROOT/retry-counts.json" --progress "$REPO_ROOT/progress.txt" \
            --output "$SCRATCH_DIR/dashboard.html" --open 2>/dev/null || true
        fi
      fi
      exit 0
    else
      _REM_MINS=$(((_REMAINING_SECS + 59) / 60))
      echo "  [time] ~${_REM_MINS}m remaining"
    fi
  fi

  _PHASE_DUR_C=$(($(date +%s) - _PHASE_TS_C))
  log_spiral_event "phase_end" "\"phase\":\"C\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_C"
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-phase --phase C --duration-s "$_PHASE_DUR_C" --iteration "$SPIRAL_ITER" 2>/dev/null || true
  notify_webhook "C" "end"
}
