#!/usr/bin/env bash
# lib/phases/phase_s_story_validate.sh — Phase S: STORY VALIDATE
#
# Runs between Research (R/T) and Merge (M).
#
# Reviews all story candidates produced by Phase R and Phase T before
# they are committed to prd.json. Acts as a lightweight automated gate:
#
#   1. Constitution check  — reject stories that violate SPIRAL_SPECKIT_CONSTITUTION
#   2. Goal alignment      — reject stories with no clear connection to prd.json goals[]
#
# Stories that fail any check are written to .spiral/_story_rejected.json
# with a rejection reason. Accepted stories pass through to Phase M via
# .spiral/_validated_stories.json.
#
# Inputs:
#   $RESEARCH_OUTPUT                   — Phase R candidates (_research_output.json)
#   $TEST_OUTPUT                       — Phase T candidates (_test_stories_output.json)
#   $PRD_FILE                          — existing prd.json (for goals[])
#   $SPIRAL_SPECKIT_CONSTITUTION       — optional constitution file path
#   $SPIRAL_STORY_VALIDATE_MIN_OVERLAP — min keyword overlap to accept (default: 1)
#
# Outputs:
#   .spiral/_validated_stories.json    — accepted story candidates (→ Phase M)
#   .spiral/_story_rejected.json       — rejected stories with reasons (log only)

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_story_validate() {
  local iter="$1"
  local research_output="${2:-$RESEARCH_OUTPUT}"
  local test_output="${3:-$TEST_OUTPUT}"
  local prd_file="${4:-$PRD_FILE}"
  local scratch_dir="${5:-$SCRATCH_DIR}"
  local spiral_python="${6:-$SPIRAL_PYTHON}"
  local spiral_home="${7:-$SPIRAL_HOME}"
  local ai_suggest_output="${8:-}"     # Phase A: Source 2 (ai-example) candidates
  local test_story_candidates="${9:-}" # Source 5 (test-story) candidates

  local validated_out="$scratch_dir/_validated_stories.json"
  local rejected_out="$scratch_dir/_story_rejected.json"

  # Build optional constitution arg
  local constitution_arg=()
  if [[ -n "${SPIRAL_SPECKIT_CONSTITUTION:-}" && -f "${SPIRAL_SPECKIT_CONSTITUTION}" ]]; then
    constitution_arg=("--constitution" "$SPIRAL_SPECKIT_CONSTITUTION")
  fi

  # Build optional Phase A and Source 5 args
  local ai_suggest_arg=()
  if [[ -n "$ai_suggest_output" && -f "$ai_suggest_output" ]]; then
    ai_suggest_arg=("--ai-suggest" "$ai_suggest_output")
  fi
  local test_story_arg=()
  if [[ -n "$test_story_candidates" && -f "$test_story_candidates" ]]; then
    test_story_arg=("--test-story-candidates" "$test_story_candidates")
  fi

  local min_overlap="${SPIRAL_STORY_VALIDATE_MIN_OVERLAP:-1}"

  # Build optional batch API args (US-390/US-406)
  # Auto-trigger when: SPIRAL_BATCH_VALIDATE=1 OR (SPIRAL_PHASE_S_BATCH_SIZE > 1 AND ANTHROPIC_API_KEY set)
  # NOTE: SPIRAL_STORY_BATCH_SIZE controls Phase I slicing only — not Phase S.
  #       Use SPIRAL_PHASE_S_BATCH_SIZE to opt-in to Phase S Anthropic Batch API.
  local batch_api_arg=()
  local _batch_size="${SPIRAL_PHASE_S_BATCH_SIZE:-0}"
  local _auto_batch=0
  if [[ "${SPIRAL_BATCH_VALIDATE:-0}" == "1" ]]; then
    _auto_batch=1
  elif [[ "$_batch_size" -gt 1 && -n "${ANTHROPIC_API_KEY:-}" ]]; then
    _auto_batch=1
  fi
  if [[ "$_auto_batch" == "1" ]]; then
    batch_api_arg=(
      "--batch-api"
      "--batch-out" "$scratch_dir/_phase_s_batch.json"
      "--batch-size" "$_batch_size"
    )
  fi

  # Run Python validation script
  if "$spiral_python" "$spiral_home/lib/prd/validate_stories.py" \
    --prd "$prd_file" \
    --research "${research_output:-/dev/null}" \
    --test-stories "${test_output:-/dev/null}" \
    --validated-out "$validated_out" \
    --rejected-out "$rejected_out" \
    "${constitution_arg[@]}" \
    "${ai_suggest_arg[@]}" \
    "${test_story_arg[@]}" \
    --min-overlap "$min_overlap" \
    "${batch_api_arg[@]}"; then
    : # success
  else
    echo "  [S] WARNING: Story validation failed — passing all stories through"
    # Fallback: copy research output as validated (accept all)
    if [[ -f "${research_output:-}" ]]; then
      cp "$research_output" "$validated_out"
    else
      echo '{"stories":[]}' >"$validated_out"
    fi
    echo '{"stories":[]}' >"$rejected_out"
  fi

  # ── US-1339: Emit DUPLICATE_CANDIDATE warnings before merge_stories ──
  if [[ -f "$validated_out" ]]; then
    while IFS= read -r line; do
      echo "  [S] $line"
    done < <(PYTHONPATH="$spiral_home${PYTHONPATH:+:$PYTHONPATH}" \
      "$spiral_python" -m lib.phase_s.duplicate_detector "$validated_out" 2>/dev/null || true)
  fi
}

# run_phase_s — Phase S orchestration wrapper
#
# Contains the full Phase S lifecycle: banner, event logging, webhook
# notifications, checkpoint handling, dry-run guard, story validation,
# acceptance-rate logging, and phase hooks.
#
# Called from the main SPIRAL loop:
#   run_phase_s || continue
#
# Returns 1 if the PRE phase hook requests an abort (so the loop can
# `continue` to the next iteration), 0 on all other paths.
run_phase_s() {
  PHASE="S"
  write_active_status "S" 30 # US-311
  print_phase_banner "S" "STORY VALIDATE — filtering candidates against project goals..."
  log_spiral_event "phase_start" "\"phase\":\"S\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "S" "start"
  _PHASE_TS_S=$(date +%s)
  run_phase_hook PRE "S" || return 1

  VALIDATED_OUTPUT="$SCRATCH_DIR/_validated_stories.json"

  if checkpoint_phase_done "S"; then
    echo "  [S] Skipping (checkpoint: already done this iter)"
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] skipping story validation"
    echo '{"stories":[]}' >"$VALIDATED_OUTPUT"
    write_checkpoint "$SPIRAL_ITER" "S"
  else
    run_phase_story_validate "$SPIRAL_ITER" \
      "$RESEARCH_OUTPUT" "$TEST_OUTPUT" \
      "$PRD_FILE" "$SCRATCH_DIR" \
      "$SPIRAL_PYTHON" "$SPIRAL_HOME" \
      "$AI_SUGGEST_OUTPUT" "$TEST_STORY_CANDIDATES"

    # Log acceptance rate to spiral_events.jsonl
    _S_ACCEPTED=$("$JQ" '.stories | length' "$VALIDATED_OUTPUT" 2>/dev/null || echo "0")
    _S_REJECTED=$("$JQ" '.stories | length' "$SCRATCH_DIR/_story_rejected.json" 2>/dev/null || echo "0")
    _S_TOTAL=$((_S_ACCEPTED + _S_REJECTED))
    log_spiral_event "phase_s_result" "\"iteration\":$SPIRAL_ITER,\"accepted\":$_S_ACCEPTED,\"rejected\":$_S_REJECTED,\"total\":$_S_TOTAL"

    # ── US-1283: Track rejection reasons in prd.json and .spiral/rejections.jsonl ──
    if [[ -f "$SCRATCH_DIR/_story_rejected.json" ]] && [[ "$_S_REJECTED" -gt 0 ]]; then
      local rejections_jsonl="$SCRATCH_DIR/rejections.jsonl"
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/track_rejections.py" \
        --prd "$PRD_FILE" \
        --rejected "$SCRATCH_DIR/_story_rejected.json" \
        --rejections-jsonl "$rejections_jsonl" || true
    fi

    # ── US-771: Record rejected pattern fingerprints for cross-iteration dedup ──
    if [[ -f "$SCRATCH_DIR/_story_rejected.json" ]] && [[ "$_S_REJECTED" -gt 0 ]]; then
      local rejected_patterns_file="$SPIRAL_HOME/.spiral/rejected_patterns.json"
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/record_rejected_patterns.py" \
        --rejected-stories "$SCRATCH_DIR/_story_rejected.json" \
        --cache-file "$rejected_patterns_file" \
        --iteration "$SPIRAL_ITER" || true
    fi

    write_checkpoint "$SPIRAL_ITER" "S"
  fi

  run_phase_hook POST "S" || true
  _PHASE_DUR_S=$(($(date +%s) - _PHASE_TS_S))
  log_spiral_event "phase_end" "\"phase\":\"S\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_S,\"model\":\"$SPIRAL_VALIDATION_MODEL\""
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-phase --phase S --duration-s "$_PHASE_DUR_S" --iteration "$SPIRAL_ITER" 2>/dev/null || true
  notify_webhook "S" "end"
}
