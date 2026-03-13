#!/bin/bash
# Ralph - Autonomous AI Agent Loop
# Generic version — works with any JS/TS project
# Based on Geoffrey Huntley's Ralph pattern (snarktank/ralph)
#
# Usage:
#   bash /path/to/ralph.sh [max_iterations] [--prd prd.json] [--tool claude|amp|codex] [--dry-run]
#
# Project-specific overrides:
#   Place ralph-config.sh in CWD to define run_project_quality_checks()
#   Place scripts/ralph/CLAUDE.md in project for a custom prompt

set -e

# ── Memory guard — cap V8 heap to prevent OOM ───────────────────────────────
# --max-old-space-size caps old generation. --max-semi-space-size=4 tightens new space
# (smaller = more frequent but shorter GC, less total RSS per process).
SPIRAL_V8_FLAGS="--max-old-space-size=${SPIRAL_MEMORY_LIMIT:-1024} --max-semi-space-size=4"
export NODE_OPTIONS="$SPIRAL_V8_FLAGS"

# Default values
MAX_ITERATIONS=60
AI_TOOL="claude"
RALPH_MODEL=""
RALPH_FOCUS="${SPIRAL_FOCUS:-}"
STORY_TIME_BUDGET="${SPIRAL_STORY_TIME_BUDGET:-0}"  # 0 = disabled
PRD_FILE="prd.json"
PROGRESS_FILE="progress.txt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --tool)
      AI_TOOL="$2"
      shift 2
      ;;
    --prd)
      PRD_FILE="$2"
      shift 2
      ;;
    --model)
      RALPH_MODEL="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    *)
      MAX_ITERATIONS="$1"
      shift
      ;;
  esac
done

# Validate AI tool
if [[ "$AI_TOOL" != "amp" && "$AI_TOOL" != "claude" && "$AI_TOOL" != "codex" && "$AI_TOOL" != "qwen" && "$AI_TOOL" != "auto" ]]; then
  echo "Error: Invalid tool: $AI_TOOL (use 'amp', 'claude', 'codex', 'qwen', or 'auto')"
  exit 1
fi

# Check prerequisites
if [[ ! -f "$PRD_FILE" ]]; then
  echo "Error: $PRD_FILE not found. Create a prd.json in the project root first."
  exit 1
fi

# Use local jq if system jq not found
if command -v jq &> /dev/null; then
  JQ="jq"
elif [[ -f "$SCRIPT_DIR/jq.exe" ]]; then
  JQ="$SCRIPT_DIR/jq.exe"
elif [[ -f "$SCRIPT_DIR/jq" ]]; then
  JQ="$SCRIPT_DIR/jq"
else
  echo "Error: jq is not installed. Install it with: choco install jq"
  echo "  Or place jq.exe in $SCRIPT_DIR/"
  exit 1
fi

# ── Source memory pressure helper (if available) ──────────────────────────────
SPIRAL_SCRATCH_DIR="${SPIRAL_SCRATCH_DIR:-.spiral}"
_PRESSURE_HELPER="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)/lib/memory-pressure-check.sh"
if [[ -f "$_PRESSURE_HELPER" ]]; then
  source "$_PRESSURE_HELPER"
fi

# Source project-specific quality gates if available
if [[ -f "./ralph-config.sh" ]]; then
  echo "[config] Loading project quality gates from ./ralph-config.sh"
  source "./ralph-config.sh"
fi

# ── Progress file initialization ──────────────────────────────────
if [[ ! -f "$PROGRESS_FILE" ]]; then
  echo "## Codebase Patterns" > "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
  echo "(Patterns will be added by Ralph iterations as they discover them)" >> "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
  echo "---" >> "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
  echo "# Ralph Progress Log - $(date)" >> "$PROGRESS_FILE"
  echo "Started autonomous agent loop for PRD completion" >> "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
fi

# ── Archive previous runs ────────────────────────────────────────
BRANCH_NAME=$($JQ -r '.branchName // "ralph-auto"' "$PRD_FILE")
PRODUCT_NAME=$($JQ -r '.productName // .project // "unknown"' "$PRD_FILE")

# Count completed vs total stories
TOTAL_STORIES=$($JQ '[.userStories | length] | .[0]' "$PRD_FILE")
COMPLETE_STORIES=$($JQ '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE")
INCOMPLETE_STORIES=$((TOTAL_STORIES - COMPLETE_STORIES))

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║     Ralph Autonomous Agent Loop      ║"
echo "  ╠══════════════════════════════════════╣"
if [[ "$AI_TOOL" == "auto" ]]; then
  echo "  ║  Tool:       auto (UT-*→Codex | US-* 1st→Qwen | retry→Claude)"
else
  echo "  ║  Tool:       $AI_TOOL"
fi
echo "  ║  PRD:        $PRODUCT_NAME"
echo "  ║  Branch:     $BRANCH_NAME"
echo "  ║  Stories:    $COMPLETE_STORIES/$TOTAL_STORIES complete"
echo "  ║  Remaining:  $INCOMPLETE_STORIES stories"
echo "  ║  Max iters:  $MAX_ITERATIONS"
[[ "$STORY_TIME_BUDGET" -gt 0 ]] && \
echo "  ║  Time budget: ${STORY_TIME_BUDGET}s per story"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── Branch management ────────────────────────────────────────────
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "$BRANCH_NAME" && "$BRANCH_NAME" != "main" && "$BRANCH_NAME" != "master" ]]; then
  if git show-ref --verify --quiet "refs/heads/$BRANCH_NAME"; then
    echo "[branch] Switching to existing branch: $BRANCH_NAME"
    git checkout "$BRANCH_NAME"
  else
    echo "[branch] Creating new feature branch: $BRANCH_NAME"
    git checkout -b "$BRANCH_NAME"
  fi
fi

# ── Quality gate functions ───────────────────────────────────────

# Default generic quality gates (can be overridden by ralph-config.sh)
if ! type run_project_quality_checks &>/dev/null; then
  run_project_quality_checks() {
    local pre_story_ts_errors="${1:-0}"
    local checks_passed=true

    echo "  ┌─ Quality Gates ─────────────────────┐"

    # Gate 1: TypeScript (if tsconfig.json found in CWD)
    echo -n "  │ [1/2] TypeScript... "
    if [[ -f "tsconfig.json" ]]; then
      local ts_output ts_errors
      ts_output=$(npx tsc --noEmit --pretty false 2>&1 || true)
      ts_errors=$(echo "$ts_output" | grep -c "error TS" || true)
      if [[ "$ts_errors" -le "$pre_story_ts_errors" ]]; then
        echo "PASS ($ts_errors errors, baseline $pre_story_ts_errors)"
      else
        echo "FAIL ($ts_errors vs baseline $pre_story_ts_errors — $((ts_errors - pre_story_ts_errors)) new)"
        checks_passed=false
      fi
    else
      echo "SKIP (no tsconfig.json in CWD)"
    fi

    # Gate 2: Lint (if npm run lint script exists)
    echo -n "  │ [2/2] Lint... "
    if npm run lint --silent 2>/dev/null; then
      echo "PASS"
    else
      echo "SKIP (no lint script or lint errors ignored)"
    fi

    echo "  └─────────────────────────────────────┘"

    if [[ "$checks_passed" == "true" ]]; then
      echo "  ✓ All quality gates passed!"
      return 0
    else
      echo "  ✗ Some quality gates FAILED"
      return 1
    fi
  }
fi

capture_ts_baseline() {
  # Default: check tsconfig.json in CWD
  # Override in ralph-config.sh for projects with subdirectory code
  if [[ -f "tsconfig.json" ]]; then
    npx tsc --noEmit --pretty false 2>&1 | grep -c "error TS" || true
  else
    echo "0"
  fi
}

# ── Retry tracking ───────────────────────────────────────────────
RETRY_FILE="retry-counts.json"
if [[ ! -f "$RETRY_FILE" ]]; then
  echo '{}' > "$RETRY_FILE"
fi
MAX_RETRIES=3

get_retry_count() {
  local story_id="$1"
  $JQ -r ".\"$story_id\" // 0" "$RETRY_FILE" | tr -d '\r'
}

increment_retry() {
  local story_id="$1"
  local current
  current=$(get_retry_count "$story_id")
  $JQ ".\"$story_id\" = $((current + 1))" "$RETRY_FILE" > "${RETRY_FILE}.tmp"
  mv "${RETRY_FILE}.tmp" "$RETRY_FILE"
}

reset_retry() {
  local story_id="$1"
  $JQ "del(.\"$story_id\")" "$RETRY_FILE" > "${RETRY_FILE}.tmp"
  mv "${RETRY_FILE}.tmp" "$RETRY_FILE"
}

# ── Story decomposition ──────────────────────────────────────────
decompose_story() {
  local story_id="$1"
  local model="${2:-sonnet}"

  # Guard: sub-stories cannot be decomposed (prevent infinite recursion)
  local from_parent
  from_parent=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | ._decomposedFrom // \"\"" "$PRD_FILE" | tr -d '\r')
  if [[ -n "$from_parent" ]]; then
    echo "  [decompose] $story_id is a sub-story of $from_parent — skipping decomposition"
    return 1
  fi

  local python_cmd="${SPIRAL_PYTHON:-python3}"
  local decompose_script
  decompose_script="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)/lib/decompose_story.py"

  if [[ ! -f "$decompose_script" ]]; then
    echo "  [decompose] decompose_story.py not found — skipping"
    return 1
  fi

  echo "  [decompose] Decomposing $story_id into sub-stories..."
  if "$python_cmd" "$decompose_script" \
    --prd "$PRD_FILE" \
    --story-id "$story_id" \
    --progress "$PROGRESS_FILE" \
    --model "$model"; then
    echo "  [decompose] $story_id decomposed successfully"
    TOTAL_STORIES=$($JQ '[.userStories | length] | .[0]' "$PRD_FILE")
    return 0
  else
    echo "  [decompose] Failed to decompose $story_id — will skip instead"
    return 1
  fi
}

# ── Results ledger (autoresearch-inspired) ──────────────────────
RESULTS_FILE="results.tsv"
append_result() {
  local status="$1" commit_sha="${2:-}"
  local ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  local duration_sec=$((STORY_END - STORY_START))
  local model_col="${EFFECTIVE_MODEL:-${EFFECTIVE_TOOL:-unknown}}"
  if [[ ! -f "$RESULTS_FILE" ]]; then
    printf 'timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha\n' > "$RESULTS_FILE"
  fi
  local safe_title="${STORY_TITLE//$'\t'/ }"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$ts" "${SPIRAL_ITER:-0}" "$ITERATION" "$NEXT_STORY" "$safe_title" \
    "$status" "$duration_sec" "$model_col" "$RETRY_NOW" "$commit_sha" \
    >> "$RESULTS_FILE"
}

# Check if all dependencies of a story are complete (passes: true)
check_deps_met() {
  local story_id="$1"
  local deps
  deps=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .dependencies // [] | .[]" "$PRD_FILE" | tr -d '\r')
  if [[ -z "$deps" ]]; then
    return 0  # No dependencies
  fi
  for dep in $deps; do
    local dep_passes
    dep_passes=$($JQ -r ".userStories[] | select(.id == \"$dep\") | .passes" "$PRD_FILE" | tr -d '\r')
    if [[ "$dep_passes" != "true" ]]; then
      return 1  # Dependency not met
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
    small)  score=$((score + 0)) ;;
    large)  score=$((score + 5)) ;;
    *)      score=$((score + 2)) ;;  # medium or missing
  esac

  # priority: low=0, medium=1, high=2, critical=3
  case "$priority" in
    low)      score=$((score + 0)) ;;
    high)     score=$((score + 2)) ;;
    critical) score=$((score + 3)) ;;
    *)        score=$((score + 1)) ;;  # medium or missing
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

# Escalate model tier based on retry count.
# retry 0: keep base; retry 1: +1 tier; retry 2+: opus
escalate_model() {
  local base_model="$1" retry_count="$2"

  if [[ "$retry_count" -le 0 ]]; then
    echo "$base_model"
  elif [[ "$retry_count" -eq 1 ]]; then
    case "$base_model" in
      haiku)  echo "sonnet" ;;
      sonnet) echo "opus" ;;
      *)      echo "opus" ;;
    esac
  else
    echo "opus"
  fi
}

# Resolve the effective model: prd.json annotation > CLI override > auto-classify+escalate
resolve_model() {
  local story_id="$1" retry_count="$2"

  # Per-story .model annotation in prd.json overrides everything (including --model flag)
  local prd_model
  prd_model=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .model // empty" "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo '')
  if [[ -n "$prd_model" ]]; then
    escalate_model "$prd_model" "$retry_count"
    return
  fi

  # CLI --model wins next
  if [[ -n "$RALPH_MODEL" ]]; then
    local escalated
    escalated=$(escalate_model "$RALPH_MODEL" "$retry_count")
    echo "$escalated"
    return
  fi

  # Auto-classify from story metadata + escalate on retry
  local base_model
  base_model=$(classify_model "$story_id")
  escalate_model "$base_model" "$retry_count"
}

# ── Dry run mode ─────────────────────────────────────────────────
if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] Would process $INCOMPLETE_STORIES stories"
  echo ""
  $JQ -r '.userStories[] | select(.passes == false) | "  [\(.id)] \(.title) (priority: \(.priority))"' "$PRD_FILE"
  echo ""
  echo "[dry-run] Run without --dry-run to execute"
  exit 0
fi

# ── Progress display helper ──────────────────────────────────────
show_progress_bar() {
  local done=$1
  local total=$2
  local width=30
  local filled=$((done * width / total))
  local empty=$((width - filled))
  local pct=$((done * 100 / total))

  printf "  Progress: ["
  printf "%0.s█" $(seq 1 $filled 2>/dev/null) || true
  printf "%0.s░" $(seq 1 $empty 2>/dev/null) || true
  printf "] %d/%d (%d%%)\n" "$done" "$total" "$pct"
}

# ── Periodic status report ────────────────────────────────────────
SPIRAL_STATUS_INTERVAL="${SPIRAL_STATUS_INTERVAL:-1800}"  # default 30 min (1800s)
LAST_STATUS_TIME=$(date +%s)

periodic_status_report() {
  local now=$(date +%s)
  local elapsed=$((now - LAST_STATUS_TIME))
  if [[ "$elapsed" -lt "$SPIRAL_STATUS_INTERVAL" ]]; then
    return
  fi
  LAST_STATUS_TIME=$now

  local total_elapsed=$(( (now - START_TIME) / 60 ))
  local done=$($JQ '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE")
  local total=$($JQ '[.userStories | length] | .[0]' "$PRD_FILE")
  local pending=$((total - done))
  local skipped=0
  if [[ -f "$RETRY_FILE" ]]; then
    skipped=$($JQ "[to_entries[] | select(.value >= $MAX_RETRIES)] | length" "$RETRY_FILE")
  fi

  echo ""
  echo "  ┌─ Periodic Status (every $((SPIRAL_STATUS_INTERVAL / 60))m) ──────┐"
  echo "  │ Elapsed:    ${total_elapsed}m"
  echo "  │ Iteration:  $ITERATION/$MAX_ITERATIONS"
  echo "  │ Completed:  $done/$total"
  echo "  │ Pending:    $pending"
  echo "  │ Skipped:    $skipped"
  show_progress_bar "$done" "$total"
  echo "  └──────────────────────────────────────┘"
  echo ""
}

# ── Main loop ────────────────────────────────────────────────────
ITERATION=0
STORIES_COMPLETED=$COMPLETE_STORIES
STORIES_SKIPPED=0
START_TIME=$(date +%s)

while [[ $ITERATION -lt $MAX_ITERATIONS ]]; do
  ITERATION=$((ITERATION + 1))

  # Periodic status report (default every 30m)
  periodic_status_report

  # Show progress bar
  CURRENT_DONE=$($JQ '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE")
  echo ""
  echo "  ╔══════════════════════════════════════╗"
  echo "  ║  Iteration $ITERATION/$MAX_ITERATIONS"
  show_progress_bar "$CURRENT_DONE" "$TOTAL_STORIES"
  echo "  ╚══════════════════════════════════════╝"

  # Find next incomplete story — respecting retries and dependencies
  NEXT_STORY=""
  ALL_INCOMPLETE=$($JQ -r '[.userStories[] | select(.passes == false and (._decomposed | not))] | sort_by(.priority) | .[].id' "$PRD_FILE" | tr -d '\r')

  for candidate in $ALL_INCOMPLETE; do
    retries=$(get_retry_count "$candidate")
    if [[ "$retries" -ge "$MAX_RETRIES" ]]; then
      continue
    fi
    if check_deps_met "$candidate"; then
      NEXT_STORY="$candidate"
      break
    fi
  done

  if [[ -z "$NEXT_STORY" ]]; then
    REMAINING=$($JQ '[.userStories[] | select(.passes == false)] | length' "$PRD_FILE")
    if [[ "$REMAINING" -eq 0 ]]; then
      echo ""
      echo "  *** ALL STORIES COMPLETE! ***"
    else
      echo ""
      echo "  No actionable stories left ($REMAINING blocked or max-retried)"
      for sid in $ALL_INCOMPLETE; do
        retries=$(get_retry_count "$sid")
        stitle=$($JQ -r ".userStories[] | select(.id == \"$sid\") | .title" "$PRD_FILE")
        local is_decomposed_parent
        is_decomposed_parent=$($JQ -r ".userStories[] | select(.id == \"$sid\") | ._decomposed // false" "$PRD_FILE" | tr -d '\r')
        if [[ "$is_decomposed_parent" == "true" ]]; then
          local children
          children=$($JQ -r ".userStories[] | select(.id == \"$sid\") | ._decomposedInto // [] | join(\", \")" "$PRD_FILE" | tr -d '\r')
          echo "    DECOMPOSED:            [$sid] $stitle → [$children]"
        elif [[ "$retries" -ge "$MAX_RETRIES" ]]; then
          echo "    SKIPPED (${retries}x failed): [$sid] $stitle"
          STORIES_SKIPPED=$((STORIES_SKIPPED + 1))
          # Log skip to results ledger
          NEXT_STORY="$sid"; STORY_TITLE="$stitle"; RETRY_NOW="$retries"
          STORY_START=$(date +%s); STORY_END=$STORY_START
          append_result "skip"
        else
          echo "    BLOCKED (deps unmet):  [$sid] $stitle"
        fi
      done
    fi
    break
  fi

  STORY_TITLE=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .title" "$PRD_FILE" | tr -d '\r')
  STORY_PRIORITY=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .priority" "$PRD_FILE" | tr -d '\r')
  STORY_DEPS=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .dependencies // [] | join(\", \")" "$PRD_FILE" | tr -d '\r')
  RETRY_NOW=$(get_retry_count "$NEXT_STORY")

  # ── Tool selection: explicit tool, or auto-route per story type + retry count ──
  if [[ "$AI_TOOL" == "auto" ]]; then
    if [[ "$NEXT_STORY" == UT-* ]]; then
      EFFECTIVE_TOOL="codex"
    elif [[ "$RETRY_NOW" -ge 1 ]]; then
      EFFECTIVE_TOOL="claude"
    else
      EFFECTIVE_TOOL="qwen"
    fi
  else
    EFFECTIVE_TOOL="$AI_TOOL"
  fi

  # ── Model routing (only applies when effective tool is claude) ──
  EFFECTIVE_MODEL=""
  MODEL_REASON=""
  STORY_MODEL=""
  if [[ "$EFFECTIVE_TOOL" == "claude" ]]; then
    # Read per-story .model annotation from prd.json
    STORY_MODEL=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .model // empty" "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo '')
    EFFECTIVE_MODEL=$(resolve_model "$NEXT_STORY" "$RETRY_NOW")
    if [[ -n "$STORY_MODEL" ]]; then
      if [[ "$RETRY_NOW" -gt 0 && "$EFFECTIVE_MODEL" != "$STORY_MODEL" ]]; then
        MODEL_REASON="prd.json ($STORY_MODEL→$EFFECTIVE_MODEL, retry $RETRY_NOW)"
      else
        MODEL_REASON="prd.json annotation"
      fi
    elif [[ -n "$RALPH_MODEL" ]]; then
      if [[ "$RETRY_NOW" -gt 0 ]]; then
        MODEL_REASON="cli override + retry escalation"
      else
        MODEL_REASON="cli override"
      fi
    else
      BASE_MODEL=$(classify_model "$NEXT_STORY")
      if [[ "$RETRY_NOW" -gt 0 && "$EFFECTIVE_MODEL" != "$BASE_MODEL" ]]; then
        MODEL_REASON="auto ($BASE_MODEL→$EFFECTIVE_MODEL, retry $RETRY_NOW)"
      else
        MODEL_REASON="auto (score-based)"
      fi
    fi
    echo "  [model] $NEXT_STORY → $EFFECTIVE_MODEL ($MODEL_REASON)"
  fi

  echo ""
  echo "  ┌─ Story ─────────────────────────────┐"
  echo "  │ ID:       $NEXT_STORY"
  echo "  │ Title:    $STORY_TITLE"
  echo "  │ Priority: $STORY_PRIORITY"
  echo "  │ Deps:     ${STORY_DEPS:-none}"
  echo "  │ Attempt:  $((RETRY_NOW + 1))/$MAX_RETRIES"
  [[ -n "$EFFECTIVE_MODEL" ]] && \
  echo "  │ Model:    $EFFECTIVE_MODEL ($MODEL_REASON)"
  echo "  └─────────────────────────────────────┘"
  echo ""

  # Select prompt file — project-specific first, then global
  PROMPT_FILE="./scripts/ralph/CLAUDE.md"
  if [[ ! -f "$PROMPT_FILE" ]]; then
    PROMPT_FILE="$SCRIPT_DIR/CLAUDE.md"
  fi
  if [[ "$AI_TOOL" == "amp" ]]; then
    PROMPT_FILE="$SCRIPT_DIR/prompt.md"
  fi

  if [[ ! -f "$PROMPT_FILE" ]]; then
    echo "Error: Prompt file not found: $PROMPT_FILE"
    exit 1
  fi

  # Capture TS error baseline BEFORE Claude makes any changes
  echo -n "  [baseline] Counting pre-story TS errors... "
  PRE_STORY_TS_ERRORS=$(capture_ts_baseline)
  echo "$PRE_STORY_TS_ERRORS errors"

  # ── Memory pressure gate (cooperative) ────────────────────────────────────
  if type spiral_pressure_level &>/dev/null; then
    _P_LVL=$(spiral_pressure_level)
    # Level 3-4: wait until pressure drops below 3
    while [[ "$_P_LVL" -ge 3 ]]; do
      echo "  [memory] Pressure level $_P_LVL — waiting 15s before spawn..."
      spiral_log_low_power "ralph: waiting to spawn $NEXT_STORY (pressure level $_P_LVL)"
      sleep 15
      _P_LVL=$(spiral_pressure_level)
    done
    # Model downgrade under pressure (only downgrade, never upgrade)
    _REC_MODEL=$(spiral_recommended_model)
    if [[ -n "$_REC_MODEL" && "$EFFECTIVE_TOOL" == "claude" && -n "$EFFECTIVE_MODEL" ]]; then
      declare -A _MODEL_RANK=([haiku]=1 [sonnet]=2 [opus]=3)
      _CUR_RANK=${_MODEL_RANK[${EFFECTIVE_MODEL}]:-2}
      _REC_RANK=${_MODEL_RANK[$_REC_MODEL]:-2}
      if [[ "$_REC_RANK" -lt "$_CUR_RANK" ]]; then
        spiral_log_low_power "ralph: model downgrade $EFFECTIVE_MODEL -> $_REC_MODEL for $NEXT_STORY"
        echo "  [memory] Model downgrade: $EFFECTIVE_MODEL -> $_REC_MODEL (pressure)"
        EFFECTIVE_MODEL="$_REC_MODEL"
      fi
    fi
  fi

  # ── Cooperative pause (parallel workers only) ───────────────────────────────
  if [[ -n "${SPIRAL_WORKER_ID:-}" ]] && type spiral_pressure_level &>/dev/null; then
    _PAUSE_FILE="${SPIRAL_SCRATCH_DIR}/_worker_pause_${SPIRAL_WORKER_ID}"
    while [[ -f "$_PAUSE_FILE" ]]; do
      echo "  [memory] Worker $SPIRAL_WORKER_ID paused — waiting for resume..."
      spiral_log_low_power "ralph: worker $SPIRAL_WORKER_ID paused between stories"
      sleep 10
    done
  fi

  # Spawn fresh AI instance with real-time stream output
  STORY_START=$(date +%s)
  echo ""
  echo "  [spawn] Fresh $EFFECTIVE_TOOL instance for $NEXT_STORY..."

  # ── Gemini pre-context (paid tier, deep reasoning, saves 20+ claude turns) ──
  STORY_JSON=$($JQ -c ".userStories[] | select(.id == \"$NEXT_STORY\")" "$PRD_FILE" 2>/dev/null || echo "{}")
  if command -v gemini &>/dev/null && [[ -n "$STORY_JSON" && "$STORY_JSON" != "{}" ]]; then
    echo "  [precontext] Running Gemini 2.5 Pro pre-analysis..."
    GEMINI_PROMPT="You are preparing context for a Claude Code agent that will implement a Frappe/Python user story in the lhdn_payroll_integration app.
Analyze this story JSON and return a concise technical brief (15-20 lines) covering:
1. Which Python files to modify (most likely candidates based on the story description)
2. Which Frappe DocTypes or hooks are involved
3. The recommended implementation approach
4. Any edge cases or gotchas to watch for
Story JSON: $STORY_JSON"
    PRECONTEXT=$(gemini \
      -m gemini-2.5-pro \
      -p "$GEMINI_PROMPT" \
      --output-format text 2>/dev/null || true)
    if [[ -n "$PRECONTEXT" ]]; then
      {
        echo ""
        echo "## Pre-analysis for $NEXT_STORY (Gemini 2.5 Pro)"
        echo "$PRECONTEXT"
        echo ""
      } >> "$PROGRESS_FILE"
      echo "  [precontext] Gemini pre-analysis injected ($(echo "$PRECONTEXT" | wc -l) lines)"
    else
      echo "  [precontext] Gemini returned empty — skipping injection"
    fi
  fi

  echo "  ─────── AI Output Start ($EFFECTIVE_TOOL) ───────"
  if [[ "$EFFECTIVE_TOOL" == "claude" ]]; then
    # Build model flag (empty if no model routing)
    CLAUDE_MODEL_FLAG=""
    [[ -n "$EFFECTIVE_MODEL" ]] && CLAUDE_MODEL_FLAG="--model $EFFECTIVE_MODEL"
    # Build prompt content (base + optional spec-kit constitution)
    RALPH_PROMPT_CONTENT="$(cat "$PROMPT_FILE")"
    SPECKIT_CONST=".specify/memory/constitution.md"
    if [[ -f "$SPECKIT_CONST" ]]; then
      RALPH_PROMPT_CONTENT="$RALPH_PROMPT_CONTENT

---

## Project Constitution (Spec-Kit — non-negotiable standards)

$(cat "$SPECKIT_CONST")
"
      echo "  [speckit] Constitution loaded ($(wc -l < "$SPECKIT_CONST") lines)"
    fi
    if [[ -n "$RALPH_FOCUS" ]]; then
      RALPH_PROMPT_CONTENT="$RALPH_PROMPT_CONTENT

---

## Iteration Focus: $RALPH_FOCUS

This SPIRAL iteration is focused on **$RALPH_FOCUS**. Keep this theme in mind while implementing the assigned story. Prioritize approaches that align with this focus area."
      echo "  [focus] Focus context injected: \"$RALPH_FOCUS\""
    fi
    # Detect Chrome DevTools MCP availability
    BROWSER_TOOLS_HINT=""
    if claude --help 2>&1 | grep -q "chrome-devtools" 2>/dev/null || [[ -n "${CHROME_DEVTOOLS_MCP:-}" ]]; then
      BROWSER_TOOLS_HINT="Chrome DevTools MCP is available. Use visual verification for UI stories."
    fi
    if [[ -n "$BROWSER_TOOLS_HINT" ]]; then
      RALPH_PROMPT_CONTENT="$RALPH_PROMPT_CONTENT

---

## Browser Tools

$BROWSER_TOOLS_HINT"
      echo "  [browser] Chrome DevTools MCP detected — visual verification enabled"
    fi
    # Unset CLAUDECODE to allow nested Claude Code invocation from within an active session
    (unset CLAUDECODE; claude -p "$RALPH_PROMPT_CONTENT" \
      $CLAUDE_MODEL_FLAG \
      --allowedTools "Edit,Write,Read,Glob,Grep,Bash,Skill,Task" \
      --max-turns 75 \
      --verbose \
      --output-format stream-json \
      --dangerously-skip-permissions \
      2>&1 | node "$SCRIPT_DIR/stream-formatter.mjs") || true
  elif [[ "$EFFECTIVE_TOOL" == "codex" ]]; then
    echo "  [ralph] Delegating to Codex (GPT-5)..."
    PROMPT_TEXT=$(cat "$PROMPT_FILE")
    codex exec --full-auto -C "$(pwd)" "$PROMPT_TEXT" 2>&1 | tail -60
  elif [[ "$EFFECTIVE_TOOL" == "qwen" ]]; then
    echo "  [ralph] Delegating to Qwen Code (free quota)..."
    PROMPT_TEXT=$(cat "$PROMPT_FILE")
    qwen "$PROMPT_TEXT" --approval-mode yolo 2>&1 | tail -200
  else
    amp --prompt-file "$PROMPT_FILE"
  fi
  echo "  ─────── AI Output End ($EFFECTIVE_TOOL) ─────────"
  STORY_END=$(date +%s)
  STORY_DURATION=$(( (STORY_END - STORY_START) / 60 ))
  echo "  [time] Story took ${STORY_DURATION}m"

  # ── Time budget enforcement ──────────────────────────────────
  if [[ "$STORY_TIME_BUDGET" -gt 0 ]]; then
    STORY_DURATION_SEC=$((STORY_END - STORY_START))
    if [[ "$STORY_DURATION_SEC" -gt "$STORY_TIME_BUDGET" ]]; then
      echo "  [time] Story exceeded budget (${STORY_DURATION_SEC}s > ${STORY_TIME_BUDGET}s) — discarding"
      $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" > "${PRD_FILE}.tmp"
      mv "${PRD_FILE}.tmp" "$PRD_FILE"
      increment_retry "$NEXT_STORY"
      RETRY_NOW=$(get_retry_count "$NEXT_STORY")
      STORY_TITLE=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .title" "$PRD_FILE" | tr -d '\r')
      append_result "discard"
      echo "## Iteration $ITERATION - $(date)" >> "$PROGRESS_FILE"
      echo "TIME BUDGET EXCEEDED: $STORY_TITLE ($NEXT_STORY) — ${STORY_DURATION_SEC}s > ${STORY_TIME_BUDGET}s budget" >> "$PROGRESS_FILE"
      if [[ "$RETRY_NOW" -ge "$MAX_RETRIES" ]]; then
        if decompose_story "$NEXT_STORY" "${EFFECTIVE_MODEL:-sonnet}"; then
          echo "DECOMPOSED: $NEXT_STORY after $MAX_RETRIES failed attempts — sub-stories created" >> "$PROGRESS_FILE"
          echo "[decompose] $NEXT_STORY decomposed after $MAX_RETRIES attempts"
        else
          echo "SKIPPED: $NEXT_STORY after $MAX_RETRIES failed attempts" >> "$PROGRESS_FILE"
          echo "[skip] $NEXT_STORY skipped after $MAX_RETRIES attempts — moving on"
        fi
      fi
      echo "" >> "$PROGRESS_FILE"
      continue
    fi
  fi

  # Check if story was completed
  PASSES=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .passes" "$PRD_FILE" | tr -d '\r')

  if [[ "$PASSES" == "true" ]]; then
    STORIES_COMPLETED=$((STORIES_COMPLETED + 1))
    echo ""
    echo "  [done] Story completed: $STORY_TITLE"

    # Run quality checks
    if run_project_quality_checks "$PRE_STORY_TS_ERRORS"; then
      reset_retry "$NEXT_STORY"

      COAUTHOR_MODEL="${EFFECTIVE_MODEL:-sonnet}"
      COAUTHOR_LABEL="${COAUTHOR_MODEL^}"
      git add -A
      git commit -m "feat: $NEXT_STORY - $STORY_TITLE

Completed by Ralph iteration $ITERATION (${STORY_DURATION}m)

Co-Authored-By: Claude ${COAUTHOR_LABEL} 4.6 <noreply@anthropic.com>" || echo "[warn] No changes to commit"

      append_result "keep" "$(git rev-parse HEAD 2>/dev/null)"

      echo "## Iteration $ITERATION - $(date)" >> "$PROGRESS_FILE"
      echo "Completed: $STORY_TITLE (ID: $NEXT_STORY) in ${STORY_DURATION}m" >> "$PROGRESS_FILE"
      echo "" >> "$PROGRESS_FILE"
    else
      echo "[rollback] Quality checks failed — reverting prd.json mark"
      $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" > "${PRD_FILE}.tmp"
      mv "${PRD_FILE}.tmp" "$PRD_FILE"

      increment_retry "$NEXT_STORY"
      RETRY_NOW=$(get_retry_count "$NEXT_STORY")
      echo "[retry] $NEXT_STORY attempt $RETRY_NOW/$MAX_RETRIES"
      append_result "discard"

      echo "## Iteration $ITERATION - $(date)" >> "$PROGRESS_FILE"
      echo "FAILED quality gates: $STORY_TITLE (ID: $NEXT_STORY) — attempt $RETRY_NOW/$MAX_RETRIES" >> "$PROGRESS_FILE"
      if [[ "$RETRY_NOW" -ge "$MAX_RETRIES" ]]; then
        git checkout -- . 2>/dev/null || true
        if decompose_story "$NEXT_STORY" "${EFFECTIVE_MODEL:-sonnet}"; then
          echo "DECOMPOSED: $NEXT_STORY after $MAX_RETRIES failed attempts — sub-stories created" >> "$PROGRESS_FILE"
          echo "[decompose] $NEXT_STORY decomposed after $MAX_RETRIES attempts"
        else
          echo "SKIPPED: $NEXT_STORY after $MAX_RETRIES failed attempts" >> "$PROGRESS_FILE"
          echo "[skip] $NEXT_STORY skipped after $MAX_RETRIES attempts — moving on"
        fi
      fi
      echo "" >> "$PROGRESS_FILE"
    fi
  else
    echo ""
    echo "[warn] Story not completed by $EFFECTIVE_TOOL instance"

    increment_retry "$NEXT_STORY"
    RETRY_NOW=$(get_retry_count "$NEXT_STORY")
    echo "[retry] $NEXT_STORY attempt $RETRY_NOW/$MAX_RETRIES"
    append_result "discard"

    echo "## Iteration $ITERATION - $(date)" >> "$PROGRESS_FILE"
    echo "Incomplete: $STORY_TITLE (ID: $NEXT_STORY) — attempt $RETRY_NOW/$MAX_RETRIES" >> "$PROGRESS_FILE"
    if [[ "$RETRY_NOW" -ge "$MAX_RETRIES" ]]; then
      git checkout -- . 2>/dev/null || true
      if decompose_story "$NEXT_STORY" "${EFFECTIVE_MODEL:-sonnet}"; then
        echo "DECOMPOSED: $NEXT_STORY after $MAX_RETRIES failed attempts — sub-stories created" >> "$PROGRESS_FILE"
        echo "[decompose] $NEXT_STORY decomposed after $MAX_RETRIES attempts"
      else
        echo "SKIPPED: $NEXT_STORY after $MAX_RETRIES failed attempts" >> "$PROGRESS_FILE"
        echo "[skip] $NEXT_STORY skipped after $MAX_RETRIES attempts — moving on"
      fi
    fi
    echo "" >> "$PROGRESS_FILE"
  fi
done

# ── Summary ──────────────────────────────────────────────────────
END_TIME=$(date +%s)
TOTAL_MINUTES=$(( (END_TIME - START_TIME) / 60 ))

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║     Ralph Session Summary            ║"
echo "  ╠══════════════════════════════════════╣"
REMAINING=$($JQ '[.userStories[] | select(.passes == false)] | length' "$PRD_FILE")
TOTAL=$($JQ '[.userStories | length] | .[0]' "$PRD_FILE")
SKIPPED_COUNT=0
if [[ -f "$RETRY_FILE" ]]; then
  SKIPPED_COUNT=$($JQ "[to_entries[] | select(.value >= $MAX_RETRIES)] | length" "$RETRY_FILE")
fi

echo "  ║  Duration:        ${TOTAL_MINUTES}m"
echo "  ║  Iterations:      $ITERATION"
echo "  ║  Completed:       $STORIES_COMPLETED/$TOTAL"
echo "  ║  Skipped:         $SKIPPED_COUNT (exceeded $MAX_RETRIES retries)"
echo "  ║  Remaining:       $REMAINING"

if [[ $REMAINING -eq 0 ]]; then
  echo "  ║  Status:          ALL COMPLETE"
else
  echo "  ║  Status:          $REMAINING stories remaining"
fi
echo "  ╚══════════════════════════════════════╝"

if [[ $REMAINING -gt 0 ]]; then
  if [[ "$SKIPPED_COUNT" -gt 0 ]]; then
    echo ""
    echo "  Skipped stories (failed ${MAX_RETRIES}x):"
    for sid in $($JQ -r 'to_entries[] | select(.value >= '"$MAX_RETRIES"') | .key' "$RETRY_FILE"); do
      stitle=$($JQ -r ".userStories[] | select(.id == \"$sid\") | .title" "$PRD_FILE")
      echo "    [$sid] $stitle"
    done
  fi
  echo ""
  echo "  Remaining stories:"
  $JQ -r '.userStories[] | select(.passes == false) | "    [\(.id)] \(.title)"' "$PRD_FILE"
fi

# Cleanup retry file if all done
if [[ $REMAINING -eq 0 ]]; then
  rm -f "$RETRY_FILE"
fi
