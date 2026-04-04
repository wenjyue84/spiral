#!/usr/bin/env bash
# lib/phases/phase_rt_parallel.sh — Phase R+T parallel orchestration
#
# Functions: run_phase_rt_parallel
# Manages the parallel execution of Phase R (research) and Phase T (test synthesis),
# including skip conditions, background job spawning, PID tracking, wait logic,
# checkpoint management, duration computation, post-phase hooks, quality judge,
# and research summarization.
#
# Returns 0 on success, 1 if the iteration should be skipped (continue).
#
# Globals read/modified: PHASE, _ACTIVE_STORY_ID, _ACTIVE_STORY_TITLE,
#   RESEARCH_OUTPUT, TEST_OUTPUT, _phase_r_ckpt, _phase_t_ckpt,
#   _PHASE_TS_R, _PHASE_TS_T, _PHASE_DUR_R, _PHASE_DUR_T, _PHASE_DUR_RT_WALL,
#   and many SPIRAL_* config vars

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_rt_parallel() {
  PHASE="R"
  _ACTIVE_STORY_ID=""
  _ACTIVE_STORY_TITLE="" # US-311: clear story context at phase start
  write_active_status "R" 10
  RESEARCH_OUTPUT="$SCRATCH_DIR/_research_output.json"
  if [[ "${SPIRAL_TEST_OUTPUT_FORMAT:-json}" == "yaml" ]]; then
    TEST_OUTPUT="$SCRATCH_DIR/_test_stories_output.yaml"
  else
    TEST_OUTPUT="$SCRATCH_DIR/_test_stories_output.json"
  fi
  _phase_r_ckpt="$SCRATCH_DIR/_phase_R_${SPIRAL_ITER}.ckpt"
  _phase_t_ckpt="$SCRATCH_DIR/_phase_T_${SPIRAL_ITER}.ckpt"

  log_spiral_event "phase_start" "\"phase\":\"R\",\"iteration\":$SPIRAL_ITER"
  log_spiral_event "phase_start" "\"phase\":\"T\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "R" "start"
  notify_webhook "T" "start"

  # PRE hook for Phase R (synchronous — a failing hook aborts this iteration)
  if ! run_phase_hook PRE "R"; then
    return 1
  fi

  # ── Determine skip conditions (synchronous, fast) ─────────────────────
  _R_SKIP=0
  _T_SKIP=0

  if checkpoint_phase_done "R"; then
    echo ""
    echo "  [R] Skipping Phase R (checkpoint: already done this iter)"
    _R_SKIP=1
  elif [[ "${SKIP_RT:-false}" == "true" ]]; then
    # ── US-1103: Fast-path skip R/T when no new stories merged and all pending have retries ──
    echo ""
    echo "  [R] Skipping Phase R (US-1103: no new stories merged and all pending have retries)"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    touch "$_phase_r_ckpt"
    _R_SKIP=1
    log_spiral_event "phase_skip" "\"phase\":\"R\",\"iteration\":$SPIRAL_ITER,\"reason\":\"no_new_stories_and_all_retried\""
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    echo "  [dry-run] skipping research agent — using empty output"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    touch "$_phase_r_ckpt"
    _R_SKIP=1
  elif [[ "$SKIP_RESEARCH" -eq 1 ]]; then
    echo ""
    echo "  [R] Skipping Phase R (--skip-research flag set)"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    touch "$_phase_r_ckpt"
    _R_SKIP=1
  elif [[ "$OVER_CAPACITY" -eq 1 ]]; then
    echo ""
    echo "  [R] Skipping Phase R (over-capacity: $PENDING pending > $CAPACITY_LIMIT)"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    touch "$_phase_r_ckpt"
    _R_SKIP=1
  elif [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]] && spiral_should_skip_phase "R"; then
    _P_LVL=$(spiral_pressure_level)
    echo ""
    echo "  [R] Skipping Phase R (memory pressure: level $_P_LVL)"
    spiral_log_low_power "Phase R skipped (pressure level $_P_LVL, iter $SPIRAL_ITER)"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    touch "$_phase_r_ckpt"
    _R_SKIP=1
  elif [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]] && [[ -f "$RESEARCH_OUTPUT" ]]; then
    _R_CACHE_AGE_H=$("$SPIRAL_PYTHON" -c "import os,time; m=os.path.getmtime('$RESEARCH_OUTPUT'); print((time.time()-m)/3600)" 2>/dev/null || echo "9999")
    _R_CACHE_HIT=$(
      "$SPIRAL_PYTHON" -c "exit(0 if float('$_R_CACHE_AGE_H') < $SPIRAL_RESEARCH_CACHE_TTL_HOURS else 1)" 2>/dev/null
      echo $?
    )
    if [[ "$_R_CACHE_HIT" -eq 0 ]]; then
      _R_CACHE_AGE_DISPLAY=$("$SPIRAL_PYTHON" -c "h=float('$_R_CACHE_AGE_H'); print(f'{h:.1f}h')" 2>/dev/null || echo "${_R_CACHE_AGE_H}h")
      echo ""
      echo "  [Phase R] cache hit — research is ${_R_CACHE_AGE_DISPLAY} old (TTL: ${SPIRAL_RESEARCH_CACHE_TTL_HOURS}h), skipping Phase R"
      touch "$_phase_r_ckpt"
      _R_SKIP=1
    fi
  fi

  # ── US-403: Query-embedding cache lookup ───────────────────────────────
  if [[ "$_R_SKIP" -eq 0 ]] && [[ -n "$SPIRAL_GEMINI_PROMPT" ]] && [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]]; then
    mkdir -p "$RESEARCH_CACHE_DIR"
    _Q_CACHE_RESULT=$(
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/resilience/query_embed_cache.py" lookup \
        "$RESEARCH_CACHE_DIR" "$SPIRAL_GEMINI_PROMPT" \
        --threshold "$SPIRAL_CACHE_SIM_THRESHOLD" \
        --ttl-hours "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" 2>/dev/null || true
    )
    if [[ -n "$_Q_CACHE_RESULT" ]]; then
      echo ""
      echo "  [Phase R] query-similarity cache hit (threshold: $SPIRAL_CACHE_SIM_THRESHOLD) — reusing cached research output"
      echo "$_Q_CACHE_RESULT" >"$RESEARCH_OUTPUT"
      touch "$_phase_r_ckpt"
      _R_SKIP=1
    fi
  fi

  if checkpoint_phase_done "T"; then
    echo "  [T] Skipping Phase T (checkpoint: already done this iter)"
    _T_SKIP=1
  elif [[ "${SKIP_RT:-false}" == "true" ]]; then
    # ── US-1103: Fast-path skip R/T when no new stories merged and all pending have retries ──
    echo "  [T] Skipping Phase T (US-1103: no new stories merged and all pending have retries)"
    _write_empty_test_output
    touch "$_phase_t_ckpt"
    _T_SKIP=1
    log_spiral_event "phase_skip" "\"phase\":\"T\",\"iteration\":$SPIRAL_ITER,\"reason\":\"no_new_stories_and_all_retried\""
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] skipping test synthesis"
    _write_empty_test_output
    touch "$_phase_t_ckpt"
    _T_SKIP=1
  elif [[ "${SPIRAL_SKIP_PHASES:-}" == *"T"* ]]; then
    echo ""
    echo "  [T] Skipping Phase T (SPIRAL_SKIP_PHASES)"
    _write_empty_test_output
    touch "$_phase_t_ckpt"
    _T_SKIP=1
  elif [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]] && spiral_should_skip_phase "T"; then
    _P_LVL=$(spiral_pressure_level)
    echo "  [T] Skipping Phase T (memory pressure: level $_P_LVL)"
    spiral_log_low_power "Phase T skipped (pressure level $_P_LVL, iter $SPIRAL_ITER)"
    _write_empty_test_output
    touch "$_phase_t_ckpt"
    _T_SKIP=1
  fi

  # ── Launch parallel background jobs ────────────────────────────────────
  _PHASE_TS_RT=$(date +%s)
  _PHASE_TS_R=$_PHASE_TS_RT
  _PHASE_TS_T=$_PHASE_TS_RT
  PID_R=""
  PID_T=""

  if [[ "$_R_SKIP" -eq 0 ]]; then
    print_phase_banner "R" "RESEARCH — launching in background..."
    (
      run_phase_research
    ) >"$SCRATCH_DIR/_phase_r_bg.log" 2>&1 &
    PID_R=$!
  fi

  if [[ "$_T_SKIP" -eq 0 ]]; then
    print_phase_banner "T" "TEST SYNTHESIS — launching in background..."
    (
      _T_EXIT=0
      _T_START=$(date +%s)
      if [[ -n "$SPIRAL_CORE_BIN" ]]; then
        if [[ "${SPIRAL_TEST_SYNTH_TIMEOUT:-60}" -gt 0 ]] && command -v timeout &>/dev/null; then
          timeout --kill-after=30 "${SPIRAL_TEST_SYNTH_TIMEOUT}" \
            "$SPIRAL_CORE_BIN" synthesize \
            --prd "$PRD_FILE" \
            --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
            --output "$TEST_OUTPUT" \
            --repo-root "$REPO_ROOT" \
            ${SPIRAL_TEST_OUTPUT_FORMAT:+--output-format "$SPIRAL_TEST_OUTPUT_FORMAT"} \
            ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _T_EXIT=$?
        else
          "$SPIRAL_CORE_BIN" synthesize \
            --prd "$PRD_FILE" \
            --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
            --output "$TEST_OUTPUT" \
            --repo-root "$REPO_ROOT" \
            ${SPIRAL_TEST_OUTPUT_FORMAT:+--output-format "$SPIRAL_TEST_OUTPUT_FORMAT"} \
            ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _T_EXIT=$?
        fi
      else
        if [[ "${SPIRAL_TEST_SYNTH_TIMEOUT:-60}" -gt 0 ]] && command -v timeout &>/dev/null; then
          timeout --kill-after=30 "${SPIRAL_TEST_SYNTH_TIMEOUT}" \
            "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research/synthesize_tests.py" \
            --prd "$PRD_FILE" \
            --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
            --output "$TEST_OUTPUT" \
            --repo-root "$REPO_ROOT" \
            --output-format "${SPIRAL_TEST_OUTPUT_FORMAT:-json}" \
            ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _T_EXIT=$?
        else
          "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research/synthesize_tests.py" \
            --prd "$PRD_FILE" \
            --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
            --output "$TEST_OUTPUT" \
            --repo-root "$REPO_ROOT" \
            --output-format "${SPIRAL_TEST_OUTPUT_FORMAT:-json}" \
            ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _T_EXIT=$?
        fi
      fi
      _T_ELAPSED=$(($(date +%s) - _T_START))
      if [[ "$_T_EXIT" -eq 124 ]]; then
        echo "  [Phase T] WARNING: Test synthesis timed out after ${_T_ELAPSED}s (limit: ${SPIRAL_TEST_SYNTH_TIMEOUT}s) — using empty output"
        log_spiral_event "phase_timeout" "\"phase\":\"T\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_T_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_TEST_SYNTH_TIMEOUT}"
        _write_empty_test_output
      elif [[ "$_T_EXIT" -ne 0 ]]; then
        echo "  [Phase T] WARNING: Test synthesis exited with status $_T_EXIT — continuing with partial/empty output"
      fi

      if [[ "${SPIRAL_TEST_OUTPUT_FORMAT:-json}" == "yaml" ]]; then
        TEST_COUNT=$("$SPIRAL_PYTHON" -c "
import yaml, sys
try:
    d = yaml.safe_load(open(sys.argv[1]))
    print(len(d.get('stories', [])) if isinstance(d, dict) else 0)
except Exception:
    print(0)
" "$TEST_OUTPUT" 2>/dev/null || echo "0")
      else
        TEST_COUNT=$("$JQ" '.stories | length' "$TEST_OUTPUT" 2>/dev/null || echo "0")
      fi
      echo "  [T] Test synthesis complete — $TEST_COUNT story candidates from failures"

      # Mark Phase T complete and record end time
      touch "$_phase_t_ckpt"
      date +%s >"$SCRATCH_DIR/_phase_T_${SPIRAL_ITER}.endtime"
    ) >"$SCRATCH_DIR/_phase_t_bg.log" 2>&1 &
    PID_T=$!
  fi

  # ── Await both background jobs ─────────────────────────────────────────
  RC_R=0
  RC_T=0
  [[ -n "$PID_R" ]] && {
    wait "$PID_R"
    RC_R=$?
  }
  [[ -n "$PID_T" ]] && {
    wait "$PID_T"
    RC_T=$?
  }

  # ── Print buffered output (R first, then T) ────────────────────────────
  [[ -n "$PID_R" && -f "$SCRATCH_DIR/_phase_r_bg.log" ]] && cat "$SCRATCH_DIR/_phase_r_bg.log"
  [[ -n "$PID_T" && -f "$SCRATCH_DIR/_phase_t_bg.log" ]] && cat "$SCRATCH_DIR/_phase_t_bg.log"

  # ── Handle failures: treat output as empty ────────────────────────────
  if [[ "$RC_R" -ne 0 && ! -f "$RESEARCH_OUTPUT" ]]; then
    echo "  [R] Phase R background job failed (exit $RC_R) — using empty research output"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
  fi
  if [[ "$RC_T" -ne 0 && ! -f "$TEST_OUTPUT" ]]; then
    echo "  [T] Phase T background job failed (exit $RC_T) — using empty test output"
    _write_empty_test_output
  fi

  # ── Write main checkpoint (T = last parallel phase in ordering) ───────
  write_checkpoint "$SPIRAL_ITER" "T"

  # ── Compute individual durations and combined wall time ───────────────
  _NOW=$(date +%s)
  _R_END=$(cat "$SCRATCH_DIR/_phase_R_${SPIRAL_ITER}.endtime" 2>/dev/null || echo "$_NOW")
  _T_END=$(cat "$SCRATCH_DIR/_phase_T_${SPIRAL_ITER}.endtime" 2>/dev/null || echo "$_NOW")
  _PHASE_DUR_R=$((_R_END - _PHASE_TS_RT))
  _PHASE_DUR_T=$((_T_END - _PHASE_TS_RT))
  _PHASE_DUR_RT_WALL=$((_NOW - _PHASE_TS_RT)) # actual wall time = max(R,T)

  # Clamp to non-negative (stale endtime files from prior runs could cause negative values)
  [[ "$_PHASE_DUR_R" -lt 0 ]] && _PHASE_DUR_R=0
  [[ "$_PHASE_DUR_T" -lt 0 ]] && _PHASE_DUR_T=0
  [[ "$_PHASE_DUR_RT_WALL" -lt 0 ]] && _PHASE_DUR_RT_WALL=0

  log_spiral_event "phase_end" "\"phase\":\"R\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_R,\"model\":\"$SPIRAL_RESEARCH_MODEL\""
  log_spiral_event "phase_end" "\"phase\":\"T\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_T"
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-phase --phase R --duration-s "$_PHASE_DUR_R" --iteration "$SPIRAL_ITER" 2>/dev/null || true
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-phase --phase T --duration-s "$_PHASE_DUR_T" --iteration "$SPIRAL_ITER" 2>/dev/null || true
  notify_webhook "R" "end"
  notify_webhook "T" "end"
  PHASE="T"

  # POST hook for R (runs after both phases complete)
  run_phase_hook POST "R" || true

  # ── LLM-as-Judge: score Phase R output (US-248) ──────────────────────
  if [[ -f "$RESEARCH_OUTPUT" ]]; then
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/quality/quality_judge.py" judge-phase-r \
      --research-output "$RESEARCH_OUTPUT" \
      --checkpoint "$CHECKPOINT_FILE" \
      --iteration "$SPIRAL_ITER" \
      --threshold "${SPIRAL_QUALITY_THRESHOLD:-3}" 2>&1 | grep -v "^\s*$" || true
  fi

  # ── US-254: Hierarchical summarization of oversized Phase R output ────
  if [[ -f "$RESEARCH_OUTPUT" ]] &&
    [[ "${SPIRAL_RESEARCH_SUMMARY_THRESHOLD:-4000}" -gt 0 ]] &&
    [[ "${SPIRAL_USE_FULL_RESEARCH:-0}" -ne 1 ]]; then
    _SUMM_STATUS=$(
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research/summarize_research.py" \
        --input "$RESEARCH_OUTPUT" --check-only \
        --threshold "${SPIRAL_RESEARCH_SUMMARY_THRESHOLD:-4000}" 2>/dev/null
      echo $?
    )
    if [[ "$_SUMM_STATUS" -eq 2 ]]; then
      # Over threshold — run summarization
      _RESEARCH_FULL="$SCRATCH_DIR/_research_full.json"
      cp "$RESEARCH_OUTPUT" "$_RESEARCH_FULL"
      _SUMM_ERR=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research/summarize_research.py" \
        --input "$_RESEARCH_FULL" \
        --output "$RESEARCH_OUTPUT" \
        --threshold "${SPIRAL_RESEARCH_SUMMARY_THRESHOLD:-4000}" 2>&1 >/dev/null || true)
      if [[ -n "$_SUMM_ERR" ]]; then
        # Parse reduction info from stderr JSON
        _SUMM_ORIG=$(echo "$_SUMM_ERR" | "$JQ" -r '.original_tokens // "?"' 2>/dev/null || echo "?")
        _SUMM_FINAL=$(echo "$_SUMM_ERR" | "$JQ" -r '.summary_tokens // "?"' 2>/dev/null || echo "?")
        _SUMM_PCT=$(echo "$_SUMM_ERR" | "$JQ" -r '.reduction_pct // "?"' 2>/dev/null || echo "?")
        echo "  [R] Summarized research: ${_SUMM_ORIG} → ${_SUMM_FINAL} tokens (${_SUMM_PCT}% reduction)"
        log_spiral_event "research_summarized" \
          "\"iteration\":$SPIRAL_ITER,\"original_tokens\":${_SUMM_ORIG},\"summary_tokens\":${_SUMM_FINAL},\"reduction_pct\":${_SUMM_PCT}"
      fi
      # Store both in checkpoint
      if [[ -f "$CHECKPOINT_FILE" ]] && [[ -n "$JQ" ]]; then
        _FULL_B64=$("$SPIRAL_PYTHON" -c "
import base64, sys
with open('$_RESEARCH_FULL', 'rb') as f:
    sys.stdout.write(base64.b64encode(f.read()).decode())" 2>/dev/null || true)
        _SUMM_B64=$("$SPIRAL_PYTHON" -c "
import base64, sys
with open('$RESEARCH_OUTPUT', 'rb') as f:
    sys.stdout.write(base64.b64encode(f.read()).decode())" 2>/dev/null || true)
        if [[ -n "$_FULL_B64" && -n "$_SUMM_B64" ]]; then
          _CKPT_TMP="${CHECKPOINT_FILE}.summ.$$"
          "$JQ" --arg full "$_FULL_B64" --arg summ "$_SUMM_B64" \
            '._phaseR = {"full": $full, "summary": $summ}' \
            "$CHECKPOINT_FILE" >"$_CKPT_TMP" 2>/dev/null &&
            mv "$_CKPT_TMP" "$CHECKPOINT_FILE" 2>/dev/null || true
        fi
      fi
    fi
  fi

  return 0
}
