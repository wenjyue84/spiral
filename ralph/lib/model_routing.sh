#!/bin/bash
# ralph/lib/model_routing.sh — Model routing functions for Ralph
#
# Extracted from ralph.sh. Contains story dependency checking, model
# classification, retry/quality-based escalation, adaptive thinking
# support detection, and the top-level resolve_model() dispatcher.
#
# Depends on globals set by ralph.sh before these functions are called:
#   $JQ, $PRD_FILE, $RALPH_MODEL,
#   $SPIRAL_ESCALATION_RETRY_SONNET, $SPIRAL_ESCALATION_RETRY_OPUS

# Source-only guard — do not execute directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# Check if all dependencies of a story are complete (passes: true)
check_deps_met() {
  local story_id="$1"
  local deps
  deps=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .dependencies // [] | .[]" "$PRD_FILE" | tr -d '\r')
  if [[ -z "$deps" ]]; then
    return 0 # No dependencies
  fi
  for dep in $deps; do
    local dep_passes
    dep_passes=$($JQ -r ".userStories[] | select(.id == \"$dep\") | .passes" "$PRD_FILE" | tr -d '\r')
    if [[ "$dep_passes" != "true" ]]; then
      return 1 # Dependency not met
    fi
  done
  return 0
}

# ── Model routing functions ───────────────────────────────────────
# Score a story's complexity and return the appropriate Claude model tier.
# Score 0-1 → haiku (trivial), 2-4 → sonnet (default), 5+ → opus (complex)
classify_model() {
  local story_id="$1" score=0

  local complexity priority deps_count ac_count
  complexity=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .estimatedComplexity // \"medium\"" "$PRD_FILE" | tr -d '\r')
  priority=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .priority // \"medium\"" "$PRD_FILE" | tr -d '\r')
  deps_count=$($JQ ".userStories[] | select(.id == \"$story_id\") | .dependencies // [] | length" "$PRD_FILE" | tr -d '\r')
  ac_count=$($JQ ".userStories[] | select(.id == \"$story_id\") | .acceptanceCriteria // [] | length" "$PRD_FILE" | tr -d '\r')

  # estimatedComplexity: small=0, medium=2, large=5
  case "$complexity" in
    small) score=$((score + 0)) ;;
    large) score=$((score + 5)) ;;
    *) score=$((score + 2)) ;; # medium or missing
  esac

  # priority: low=0, medium=1, high=2, critical=3
  case "$priority" in
    low) score=$((score + 0)) ;;
    high) score=$((score + 2)) ;;
    critical) score=$((score + 3)) ;;
    *) score=$((score + 1)) ;; # medium or missing
  esac

  # dependencies: 0-1 deps=0, 2+=1
  if [[ "$deps_count" -ge 2 ]]; then
    score=$((score + 1))
  fi

  # acceptanceCriteria: ≤6=0, 7+=1
  if [[ "$ac_count" -ge 7 ]]; then
    score=$((score + 1))
  fi

  # Map score to model tier
  if [[ "$score" -le 1 ]]; then
    echo "haiku"
  elif [[ "$score" -le 4 ]]; then
    echo "sonnet"
  else
    echo "opus"
  fi
}

# Escalate model tier based on retry count for incomplete stories.
# Thresholds are configurable via SPIRAL_ESCALATION_RETRY_SONNET and SPIRAL_ESCALATION_RETRY_OPUS.
# Default: retry 0 = keep base; retry 1 = +1 tier (haiku→sonnet); retry 2+ = opus
escalate_model_by_retry() {
  local base_model="$1" retry_count="$2"
  local sonnet_threshold="${SPIRAL_ESCALATION_RETRY_SONNET:-1}"
  local opus_threshold="${SPIRAL_ESCALATION_RETRY_OPUS:-2}"

  if [[ "$retry_count" -lt "$sonnet_threshold" ]]; then
    echo "$base_model"
  elif [[ "$retry_count" -lt "$opus_threshold" ]]; then
    case "$base_model" in
      haiku) echo "sonnet" ;;
      sonnet) echo "opus" ;;
      *) echo "opus" ;;
    esac
  else
    echo "opus"
  fi
}

# Escalate model tier based on quality gate failures.
# escalation 0: keep base; escalation 1: +1 tier; escalation 2+: opus
escalate_model_by_quality_failure() {
  local base_model="$1" escalation_count="$2"
  if [[ "$escalation_count" -le 0 ]]; then
    echo "$base_model"
  elif [[ "$escalation_count" -eq 1 ]]; then
    case "$base_model" in
      haiku) echo "sonnet" ;;
      sonnet) echo "opus" ;;
      *) echo "opus" ;;
    esac
  else
    echo "opus"
  fi
}

# US-373: Check if a model supports adaptive thinking (--effort flag).
# Claude 4.6 models (opus-4-6, sonnet-4-6) use adaptive thinking.
# Older models (haiku-4-5, sonnet-4-5) use budget_tokens (no --effort flag).
# Short aliases "opus" and "sonnet" resolve to the latest (4.6) in Claude CLI.
supports_adaptive_thinking() {
  local model="$1"
  case "$model" in
    opus | sonnet) return 0 ;;             # short aliases → latest (4.6)
    *opus-4-6* | *sonnet-4-6*) return 0 ;; # full model IDs
    *) return 1 ;;                         # haiku, older models
  esac
}

# US-398: Map SPIRAL_THINKING_BUDGET_TOKENS to --effort level.
# The Claude CLI uses --effort (low/medium/high/max) instead of raw budget_tokens.
# This function maps the numeric budget to the closest effort level:
#   0          → (disabled — no --effort flag)
#   1024-4999  → low
#   5000-9999  → medium
#   10000-49999 → high
#   50000+     → max
budget_to_effort() {
  local budget="$1"
  if [[ "$budget" -le 0 ]]; then
    echo ""
  elif [[ "$budget" -lt 5000 ]]; then
    echo "low"
  elif [[ "$budget" -lt 10000 ]]; then
    echo "medium"
  elif [[ "$budget" -lt 50000 ]]; then
    echo "high"
  else
    echo "max"
  fi
}

# should_skip_escalation <failure_type>
# Returns 0 (true) if the failure type indicates that model escalation won't help.
# These are errors fixable by retrying the same model with the error message.
should_skip_escalation() {
  local failure_type="${1:-}"
  case "$failure_type" in
    syntax_error | type_error | test_assertion | missing_dependency | context_overflow)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

# Resolve the effective model: prd.json annotation > CLI override > auto-classify+escalate
# Optional 4th arg: failure_type from failure_categorizer.py. When set to a "fixable"
# category (syntax_error, type_error, etc.), model escalation is skipped — the same
# model retries with the error appended to anti-patterns.
resolve_model() {
  local story_id="$1" retry_count="$2" escalation_count="$3"
  local failure_type="${4:-}"

  # Per-story .model annotation in prd.json overrides everything (including --model flag)
  local prd_model
  prd_model=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .model // empty" "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo '')
  if [[ -n "$prd_model" ]]; then
    if [[ -n "$failure_type" ]] && should_skip_escalation "$failure_type"; then
      echo "$prd_model"
    else
      local escalated_model
      escalated_model=$(escalate_model_by_retry "$prd_model" "$retry_count")
      escalate_model_by_quality_failure "$escalated_model" "$escalation_count"
    fi
    return
  fi

  # CLI --model wins next
  if [[ -n "$RALPH_MODEL" ]]; then
    if [[ -n "$failure_type" ]] && should_skip_escalation "$failure_type"; then
      echo "$RALPH_MODEL"
    else
      local escalated
      escalated=$(escalate_model_by_retry "$RALPH_MODEL" "$retry_count")
      escalate_model_by_quality_failure "$escalated" "$escalation_count"
      echo "$escalated"
    fi
    return
  fi

  # Historical model routing: query results.tsv for pass rates by complexity band
  if [[ "${SPIRAL_HISTORY_ROUTING:-false}" == "true" && "$retry_count" -eq 0 ]]; then
    local complexity
    complexity=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .estimatedComplexity // \"medium\"" "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo 'medium')
    local hist_model
    hist_model=$(uv run python "$(dirname "${BASH_SOURCE[0]}")/../../lib/routing/complexity_scorer.py" \
        --recommend --complexity "$complexity" 2>/dev/null || echo "")
    if [[ -n "$hist_model" ]]; then
      echo "[model_routing] History recommends $hist_model for complexity=$complexity" >&2
      echo "$hist_model"
      return
    fi
  fi

  # Auto-classify from story metadata + escalate on retry
  local base_model
  base_model=$(classify_model "$story_id")
  if [[ -n "$failure_type" ]] && should_skip_escalation "$failure_type"; then
    echo "$base_model"
  else
    local escalated_model
    escalated_model=$(escalate_model_by_retry "$base_model" "$retry_count")
    escalate_model_by_quality_failure "$escalated_model" "$escalation_count"
  fi
}
