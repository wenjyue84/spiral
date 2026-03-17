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
  # ── Phase E: STORY ENRICHMENT (US-443) ──────────────────────────────────────
  # Optional pass: for medium-complexity or sparse stories, calls Claude to
  # rewrite vague ACs, add exact file paths + test commands, and split stories
  # touching 3+ files. Gated by SPIRAL_STORY_ENRICHMENT=true.
  ENRICHED_OUTPUT="$SCRATCH_DIR/_enriched_stories.json"
  if [[ "${SPIRAL_STORY_ENRICHMENT:-false}" == "true" ]] && [[ -f "$VALIDATED_OUTPUT" ]]; then
    _ENRICH_MODEL="${SPIRAL_STORY_ENRICHMENT_MODEL:-sonnet}"
    _ENRICH_TS=$(date +%s)
    echo ""
    echo "  [E] STORY ENRICHMENT — refining medium/sparse stories (model: $_ENRICH_MODEL)..."
    _ENRICH_RC=0
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/enrich_stories.py" \
      --validated-in "$VALIDATED_OUTPUT" \
      --enriched-out "$ENRICHED_OUTPUT" \
      --model "$_ENRICH_MODEL" || _ENRICH_RC=$?
    _ENRICH_DUR=$(($(date +%s) - _ENRICH_TS))
    if [[ "$_ENRICH_RC" -eq 0 && -f "$ENRICHED_OUTPUT" ]]; then
      _ENRICH_TOTAL=$("$JQ" '.stories | length' "$ENRICHED_OUTPUT" 2>/dev/null || echo "?")
      echo "  [E] Enrichment complete — $_ENRICH_TOTAL stories ready for merge (${_ENRICH_DUR}s)"
      VALIDATED_OUTPUT="$ENRICHED_OUTPUT"
    else
      echo "  [E] WARNING: Enrichment failed (rc=$_ENRICH_RC) — using Phase S output unchanged"
    fi
  fi
}
