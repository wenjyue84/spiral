#!/usr/bin/env bash
# lib/phases/phase_st_self_tune.sh — Phase ST: SELF-TUNE
#
# Analyzes telemetry from recent iterations and adjusts env vars
# for the next iteration. Runs after Phase L (learning), before
# the loop-back to Phase A.
#
# Inputs:
#   $REPO_ROOT          — repo root path
#   $SCRATCH_DIR        — .spiral directory for outputs
#   $SPIRAL_ITER        — current iteration number
#   $SPIRAL_HOME        — spiral repo root
#   $SPIRAL_PYTHON      — python3 executable path
#
# Outputs:
#   Exports adjusted SPIRAL_* env vars into current shell
#   Appends adjustments to .spiral/tuning_history.jsonl

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_self_tune() {
  PHASE="ST"
  print_phase_banner "ST" "SELF-TUNE — adjusting config from telemetry..."
  log_spiral_event "phase_start" "\"phase\":\"ST\",\"iteration\":$SPIRAL_ITER"
  _PHASE_TS_ST=$(date +%s)

  local _TUNING_HISTORY="$SCRATCH_DIR/tuning_history.jsonl"
  local _RESULTS_TSV="$REPO_ROOT/results.tsv"
  local _ST_OUTPUT
  local _ST_RC

  # Skip if no results exist yet (iteration 1 with no prior data)
  if [[ ! -f "$_RESULTS_TSV" ]]; then
    echo "  [ST] No results.tsv yet — skipping self-tune"
    _PHASE_DUR_ST=$(($(date +%s) - _PHASE_TS_ST))
    log_spiral_event "phase_end" \
      "\"phase\":\"ST\",\"iteration\":$SPIRAL_ITER,\"duration_sec\":$_PHASE_DUR_ST,\"status\":\"skipped\""
    return 0
  fi

  # Run Python analysis
  _ST_OUTPUT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/self_tune.py" \
    "$_RESULTS_TSV" \
    "$_TUNING_HISTORY" \
    "$SCRATCH_DIR" \
    "$SPIRAL_ITER" 2>&1)
  _ST_RC=$?

  if [[ $_ST_RC -ne 0 ]]; then
    echo "  [ST] WARNING: self-tune analysis failed (code $_ST_RC)"
    echo "$_ST_OUTPUT" | head -5
    _PHASE_DUR_ST=$(($(date +%s) - _PHASE_TS_ST))
    log_spiral_event "phase_end" \
      "\"phase\":\"ST\",\"iteration\":$SPIRAL_ITER,\"duration_sec\":$_PHASE_DUR_ST,\"status\":\"error\""
    return 0 # non-fatal
  fi

  # Parse exports from JSON output
  local _EXPORT_COUNT=0
  local _EXPORTS_LINE

  while IFS='=' read -r key val; do
    [[ -z "$key" ]] && continue
    echo "  [ST] TUNING: $key  $( printenv "$key" 2>/dev/null || echo '(unset)' ) -> $val"
    export "$key"="$val"
    _EXPORT_COUNT=$((_EXPORT_COUNT + 1))
    log_spiral_event "self_tune_adjust" \
      "\"phase\":\"ST\",\"iteration\":$SPIRAL_ITER,\"setting\":\"$key\",\"new_value\":\"$val\""
  done < <(echo "$_ST_OUTPUT" | "$JQ" -r '.exports // {} | to_entries[] | "\(.key)=\(.value)"' 2>/dev/null)

  if [[ $_EXPORT_COUNT -eq 0 ]]; then
    echo "  [ST] No adjustments needed this iteration"
  else
    echo "  [ST] Applied $_EXPORT_COUNT adjustment(s) for next iteration"
  fi

  _PHASE_DUR_ST=$(($(date +%s) - _PHASE_TS_ST))
  log_spiral_event "phase_end" \
    "\"phase\":\"ST\",\"iteration\":$SPIRAL_ITER,\"duration_sec\":$_PHASE_DUR_ST,\"adjustments\":$_EXPORT_COUNT"
}
