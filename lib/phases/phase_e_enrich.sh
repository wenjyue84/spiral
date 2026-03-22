#!/usr/bin/env bash
# lib/phases/phase_e_enrich.sh — Phase E: STORY ENRICHMENT (US-443)
#
# Optional pass between Phase S (STORY VALIDATE) and Phase M (MERGE).
# For medium-complexity or sparse stories, calls Claude to:
#   - Rewrite vague acceptance criteria
#   - Add exact file paths and test commands
#   - Split stories that touch 3+ files
#
# Only runs when SPIRAL_STORY_ENRICHMENT=true.
#
# Inputs:
#   $VALIDATED_OUTPUT              — Phase S output (_validated_stories.json)
#
# Outputs:
#   .spiral/_enriched_stories.json — enriched stories (-> Phase M)
#   $VALIDATED_OUTPUT updated to point at enriched output on success
#
# Config vars:
#   SPIRAL_STORY_ENRICHMENT        — "true" to enable (default: false)
#   SPIRAL_STORY_ENRICHMENT_MODEL  — Claude model (default: sonnet)
#   SPIRAL_STORY_ENRICHMENT_MAX    — Max stories to enrich per iter (default: 10)

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# run_phase_enrichment — Phase E orchestration wrapper
#
# Runs story enrichment when SPIRAL_STORY_ENRICHMENT=true. On success,
# updates VALIDATED_OUTPUT to point at the enriched file so Phase M
# picks up the richer stories. On failure, leaves VALIDATED_OUTPUT
# unchanged and prints a warning.
#
# Called from the main SPIRAL loop immediately after run_phase_s:
#   run_phase_s || continue
#   run_phase_enrichment
run_phase_enrichment() {
  ENRICHED_OUTPUT="$SCRATCH_DIR/_enriched_stories.json"
  if [[ "${SPIRAL_STORY_ENRICHMENT:-false}" != "true" ]] || [[ ! -f "$VALIDATED_OUTPUT" ]]; then
    return 0
  fi

  # ── Phase E: STORY ENRICHMENT (US-443) ──────────────────────────────────────
  PHASE="E"
  write_active_status "E" 35
  print_phase_banner "E" "STORY ENRICHMENT — refining medium/sparse stories..."
  log_spiral_event "phase_start" "\"phase\":\"E\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "E" "start"
  local _PHASE_TS_E
  _PHASE_TS_E=$(date +%s)

  local _ENRICH_MODEL="${SPIRAL_STORY_ENRICHMENT_MODEL:-sonnet}"
  local _ENRICH_MAX="${SPIRAL_STORY_ENRICHMENT_MAX:-10}"
  local _ENRICH_RC=0

  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research/enrich_stories.py" \
    --validated-in "$VALIDATED_OUTPUT" \
    --enriched-out "$ENRICHED_OUTPUT" \
    --model "$_ENRICH_MODEL" \
    --max "$_ENRICH_MAX" || _ENRICH_RC=$?

  local _PHASE_DUR_E
  _PHASE_DUR_E=$(($(date +%s) - _PHASE_TS_E))

  if [[ "$_ENRICH_RC" -eq 0 && -f "$ENRICHED_OUTPUT" ]]; then
    local _ENRICH_TOTAL
    _ENRICH_TOTAL=$("$JQ" '.stories | length' "$ENRICHED_OUTPUT" 2>/dev/null || echo "?")
    echo "  [E] Enrichment complete — $_ENRICH_TOTAL stories ready for merge (${_PHASE_DUR_E}s)"
    VALIDATED_OUTPUT="$ENRICHED_OUTPUT"
  else
    echo "  [E] WARNING: Enrichment failed (rc=$_ENRICH_RC) — using Phase S output unchanged"
  fi

  log_spiral_event "phase_end" "\"phase\":\"E\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_E,\"model\":\"$_ENRICH_MODEL\""
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-phase \
    --phase E --duration-s "$_PHASE_DUR_E" --iteration "$SPIRAL_ITER" 2>/dev/null || true
  notify_webhook "E" "end"
}
