#!/usr/bin/env bash
# lib/phases/phase_t_test_synth.sh — Phase T: TEST SYNTHESIS
#
# Converts existing test suite failures into regression user stories.
# Reads test-reports/ to find failing tests not already covered by a story,
# then produces story candidates targeting those specific failures.
#
# Runs AFTER Phase R so test-failure stories can be merged alongside
# research stories in Phase M.
#
# Inputs:
#   $SPIRAL_REPORTS_DIR    — test reports directory (default: test-reports/)
#
# Outputs:
#   .spiral/_test_stories_output.json   — test-derived story candidates
#
# Config vars:
#   SPIRAL_TEST_SYNTH_TIMEOUT  — seconds before timeout (default: 60)
#
# TODO: extract Phase T block from spiral.sh (lines 1722–1797) into this file.

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_test_synth() {
  local iter="$1"
  # TODO: migrated from spiral.sh Phase T background subshell block (run_phase_research_and_test).
  # This is a synchronous equivalent — no background job, no PID_T, no wait.

  # ── Skip conditions ────────────────────────────────────────────────────────
  if checkpoint_phase_done "T"; then
    echo "  [T] Skipping Phase T (checkpoint: already done this iter)"
    return 0
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] skipping test synthesis"
    _write_empty_test_output
    touch "$_phase_t_ckpt"
    return 0
  elif [[ "${SPIRAL_SKIP_PHASES:-}" == *"T"* ]]; then
    echo ""
    echo "  [T] Skipping Phase T (SPIRAL_SKIP_PHASES)"
    _write_empty_test_output
    touch "$_phase_t_ckpt"
    return 0
  elif [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]] && spiral_should_skip_phase "T"; then
    local _p_lvl
    _p_lvl=$(spiral_pressure_level)
    echo "  [T] Skipping Phase T (memory pressure: level $_p_lvl)"
    spiral_log_low_power "Phase T skipped (pressure level $_p_lvl, iter $iter)"
    _write_empty_test_output
    touch "$_phase_t_ckpt"
    return 0
  fi

  print_phase_banner "T" "TEST SYNTHESIS — scanning test failures..."

  # ── Run synthesize_tests (synchronous) ────────────────────────────────────
  local _t_exit=0
  local _t_start
  _t_start=$(date +%s)

  if [[ -n "$SPIRAL_CORE_BIN" ]]; then
    if [[ "${SPIRAL_TEST_SYNTH_TIMEOUT:-60}" -gt 0 ]] && command -v timeout &>/dev/null; then
      timeout --kill-after=30 "${SPIRAL_TEST_SYNTH_TIMEOUT}" \
        "$SPIRAL_CORE_BIN" synthesize \
        --prd "$PRD_FILE" \
        --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
        --output "$TEST_OUTPUT" \
        --repo-root "$REPO_ROOT" \
        ${SPIRAL_TEST_OUTPUT_FORMAT:+--output-format "$SPIRAL_TEST_OUTPUT_FORMAT"} \
        ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _t_exit=$?
    else
      "$SPIRAL_CORE_BIN" synthesize \
        --prd "$PRD_FILE" \
        --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
        --output "$TEST_OUTPUT" \
        --repo-root "$REPO_ROOT" \
        ${SPIRAL_TEST_OUTPUT_FORMAT:+--output-format "$SPIRAL_TEST_OUTPUT_FORMAT"} \
        ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _t_exit=$?
    fi
  else
    if [[ "${SPIRAL_TEST_SYNTH_TIMEOUT:-60}" -gt 0 ]] && command -v timeout &>/dev/null; then
      timeout --kill-after=30 "${SPIRAL_TEST_SYNTH_TIMEOUT}" \
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/synthesize_tests.py" \
        --prd "$PRD_FILE" \
        --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
        --output "$TEST_OUTPUT" \
        --repo-root "$REPO_ROOT" \
        --output-format "${SPIRAL_TEST_OUTPUT_FORMAT:-json}" \
        ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _t_exit=$?
    else
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/synthesize_tests.py" \
        --prd "$PRD_FILE" \
        --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
        --output "$TEST_OUTPUT" \
        --repo-root "$REPO_ROOT" \
        --output-format "${SPIRAL_TEST_OUTPUT_FORMAT:-json}" \
        ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _t_exit=$?
    fi
  fi

  local _t_elapsed
  _t_elapsed=$(($(date +%s) - _t_start))

  # ── Handle timeout / error ─────────────────────────────────────────────────
  if [[ "$_t_exit" -eq 124 ]]; then
    echo "  [Phase T] WARNING: Test synthesis timed out after ${_t_elapsed}s (limit: ${SPIRAL_TEST_SYNTH_TIMEOUT}s) — using empty output"
    log_spiral_event "phase_timeout" "\"phase\":\"T\",\"iteration\":$iter,\"duration_ms\":$((_t_elapsed * 1000)),\"timeout_s\":${SPIRAL_TEST_SYNTH_TIMEOUT}"
    _write_empty_test_output
  elif [[ "$_t_exit" -ne 0 ]]; then
    echo "  [Phase T] WARNING: Test synthesis exited with status $_t_exit — continuing with partial/empty output"
  fi

  # ── Count story candidates ─────────────────────────────────────────────────
  local _test_count
  if [[ "${SPIRAL_TEST_OUTPUT_FORMAT:-json}" == "yaml" ]]; then
    _test_count=$("$SPIRAL_PYTHON" -c "
import yaml, sys
try:
    d = yaml.safe_load(open(sys.argv[1]))
    print(len(d.get('stories', [])) if isinstance(d, dict) else 0)
except Exception:
    print(0)
" "$TEST_OUTPUT" 2>/dev/null || echo "0")
  else
    _test_count=$("$JQ" '.stories | length' "$TEST_OUTPUT" 2>/dev/null || echo "0")
  fi
  echo "  [T] Test synthesis complete — $_test_count story candidates from failures"

  # ── Mark Phase T complete ──────────────────────────────────────────────────
  touch "$_phase_t_ckpt"
  date +%s >"$SCRATCH_DIR/_phase_T_${iter}.endtime"
}
