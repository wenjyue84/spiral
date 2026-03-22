#!/usr/bin/env bash
# lib/phases/phase_l_learn.sh — Phase L: LEARNING
#
# Analyzes completed stories and extracts retry patterns to inform future iterations.
# Clusters stories by retry count (0, 1, 2, 3+) and extracts common traits
# that correlate with easy vs hard stories.
#
# Inputs:
#   $PRD_FILE           — prd.json (completed stories)
#   $REPO_ROOT          — repo root path
#   $SCRATCH_DIR        — .spiral directory for outputs
#   $SPIRAL_ITER        — current iteration number
#   $SPIRAL_HOME        — spiral repo root
#   $SPIRAL_PYTHON      — python3 executable path
#
# Outputs:
#   .spiral/learned_patterns.json — timestamped pattern analysis

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_learn() {
  PHASE="L"
  print_phase_banner "L" "LEARNING — analyzing retry patterns from completed stories..."
  log_spiral_event "phase_start" "\"phase\":\"L\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "L" "start"
  _PHASE_TS_L=$(date +%s)

  _PATTERNS_FILE="$SCRATCH_DIR/learned_patterns_iter_${SPIRAL_ITER}.json"
  _RETRY_COUNTS="$REPO_ROOT/retry-counts.json"

  if [[ ! -f "$_RETRY_COUNTS" ]]; then
    echo "  [L] No retry-counts.json found — skipping pattern analysis"
    return 0
  fi

  # Run pattern analysis
  _ANALYSIS_OUTPUT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/pattern_analyzer.py" \
    "$PRD_FILE" "$_RETRY_COUNTS" "$SPIRAL_ITER" 2>&1)
  _PA_RC=$?

  if [[ $_PA_RC -eq 0 ]]; then
    # Save patterns to file
    echo "$_ANALYSIS_OUTPUT" >"$_PATTERNS_FILE"
    echo "  [L] Pattern analysis saved: $_PATTERNS_FILE"

    # Display insights
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/pattern_analyzer.py" show "$_PATTERNS_FILE" 2>/dev/null || true
  else
    echo "  [L] WARNING: pattern analysis failed (code $_PA_RC)"
    echo "$_ANALYSIS_OUTPUT"
  fi

  _PHASE_DUR_L=$(($(date +%s) - _PHASE_TS_L))
  log_spiral_event "phase_end" "\"phase\":\"L\",\"iteration\":$SPIRAL_ITER,\"duration_sec\":$_PHASE_DUR_L"
}
