#!/usr/bin/env bash
# lib/phases/phase_l.sh — Phase L: LEARNING
#
# Extracts successful patterns from results.tsv and appends to learning.md
# This closes the learning loop so future Phase E decomposition prompts can
# benefit from accumulated successes.
#
# Inputs:
#   $RESULTS_FILE       — results.tsv (completed stories)
#   $SPIRAL_HOME        — spiral repo root
#
# Outputs:
#   .spiral/learning.md — accumulated patterns from successful stories

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_learn() {
  PHASE="L"
  print_phase_banner "L" "LEARNING — extracting patterns from successful stories..."
  log_spiral_event "phase_start" "\"phase\":\"L\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "L" "start"
  _PHASE_TS_L=$(date +%s)

  _RESULTS_FILE="${RESULTS_FILE:-.spiral/results.tsv}"
  _LEARNING_MD="${SCRATCH_DIR:-.spiral}/learning.md"

  # Run learning extractor
  _LE_OUTPUT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/learning_extractor.py" "$_RESULTS_FILE" "$_LEARNING_MD" 2>&1)
  _LE_RC=$?

  if [[ $_LE_RC -eq 0 ]]; then
    echo "  [L] Learning extraction complete: $_LEARNING_MD"
    # Show first line of output (pattern count)
    echo "$_LE_OUTPUT" | head -1 | sed 's/^/  [L] /'
  else
    echo "  [L] WARNING: learning extraction failed (code $_LE_RC)"
    echo "$_LE_OUTPUT" | sed 's/^/  [L] /'
  fi

  _PHASE_DUR_L=$(($(date +%s) - _PHASE_TS_L))
  log_spiral_event "phase_end" "\"phase\":\"L\",\"iteration\":$SPIRAL_ITER,\"duration_sec\":$_PHASE_DUR_L"
}
