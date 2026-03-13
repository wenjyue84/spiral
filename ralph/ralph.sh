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
SPIRAL_STORY_COST_WARN_USD="${SPIRAL_STORY_COST_WARN_USD:-0.50}"   # warn when story exceeds this
SPIRAL_STORY_COST_HARD_USD="${SPIRAL_STORY_COST_HARD_USD:-2.00}"   # abandon story when it exceeds this
SPIRAL_MODEL_INPUT_PRICE_PER_M="${SPIRAL_MODEL_INPUT_PRICE_PER_M:-3.00}"   # $/1M input tokens (sonnet default)
SPIRAL_MODEL_OUTPUT_PRICE_PER_M="${SPIRAL_MODEL_OUTPUT_PRICE_PER_M:-15.00}" # $/1M output tokens (sonnet default)
SPIRAL_MODEL_FALLBACK_CHAIN="${SPIRAL_MODEL_FALLBACK_CHAIN:-}"  # colon-separated fallback models (e.g. sonnet:haiku:gemini-2.0-flash)
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

# ── Helper: append a JSONL event to spiral_events.jsonl ─────────────────────
SPIRAL_SCRATCH_DIR="${SPIRAL_SCRATCH_DIR:-.spiral}"
log_ralph_event() {
  local event="$1"
  local extra="${2:-}"
  local ts log_file line
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log_file="$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"
  if [[ -n "$extra" ]]; then
    line="{\"ts\":\"$ts\",\"event\":\"$event\",$extra}"
  else
    line="{\"ts\":\"$ts\",\"event\":\"$event\"}"
  fi
  printf '%s\n' "$line" >> "$log_file" 2>/dev/null || true
}

# ── Per-story token cost accumulation ────────────────────────────────────────
# accumulate_story_cost <story_id> <tokens_input> <tokens_output>
# Writes atomically to $SPIRAL_SCRATCH_DIR/story_costs.json.
# Emits a cost_update event to spiral_events.jsonl.
# Prints the new cumulative estimated_usd for the story on stdout.
# Returns 0 always (errors are non-fatal).
accumulate_story_cost() {
  local story_id="$1" tokens_input="${2:-0}" tokens_output="${3:-0}"
  local cost_file="$SPIRAL_SCRATCH_DIR/story_costs.json"
  local input_price="$SPIRAL_MODEL_INPUT_PRICE_PER_M"
  local output_price="$SPIRAL_MODEL_OUTPUT_PRICE_PER_M"

  local cumulative_usd
  cumulative_usd=$(python3 - <<PYEOF 2>/dev/null
import json, os, sys

story_id = '$story_id'
tokens_input = int('$tokens_input') if '$tokens_input'.isdigit() else 0
tokens_output = int('$tokens_output') if '$tokens_output'.isdigit() else 0
input_price = float('$input_price')
output_price = float('$output_price')
cost_file = '$cost_file'

try:
    with open(cost_file, 'r', encoding='utf-8') as f:
        costs = json.load(f)
except (FileNotFoundError, json.JSONDecodeError, OSError):
    costs = {}

entry = costs.get(story_id, {'tokens_input': 0, 'tokens_output': 0, 'estimated_usd': 0.0})
entry['tokens_input'] = entry.get('tokens_input', 0) + tokens_input
entry['tokens_output'] = entry.get('tokens_output', 0) + tokens_output
call_cost = (tokens_input / 1_000_000) * input_price + (tokens_output / 1_000_000) * output_price
entry['estimated_usd'] = round(entry.get('estimated_usd', 0.0) + call_cost, 6)
costs[story_id] = entry

tmp = cost_file + '.tmp'
try:
    os.makedirs(os.path.dirname(cost_file) or '.', exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(costs, f, indent=2)
    os.replace(tmp, cost_file)
except OSError as e:
    sys.stderr.write(f'[cost] WARNING: could not write {cost_file}: {e}\n')

print(entry['estimated_usd'])
PYEOF
  ) || true

  cumulative_usd="${cumulative_usd:-0}"

  # Emit cost_update event
  log_ralph_event "cost_update" \
    "\"story_id\":\"$story_id\",\"tokens_input\":$tokens_input,\"tokens_output\":$tokens_output,\"estimated_usd\":$cumulative_usd" || true

  printf '%s' "$cumulative_usd"
}

# ── Source memory pressure helper (if available) ──────────────────────────────
_PRESSURE_HELPER="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)/lib/memory-pressure-check.sh"
if [[ -f "$_PRESSURE_HELPER" ]]; then
  source "$_PRESSURE_HELPER"
fi

# ── Source circuit breaker (if available) ─────────────────────────────────────
_CB_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)/lib/circuit_breaker.sh"
if [[ -f "$_CB_LIB" ]]; then
  source "$_CB_LIB"
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

# ── Event logger (writes structured JSONL to .spiral/spiral_events.jsonl) ────
log_spiral_event() {
  local event_type="$1"
  local extra_json="${2:-}"
  local events_file="${SPIRAL_SCRATCH_DIR}/spiral_events.jsonl"
  mkdir -p "${SPIRAL_SCRATCH_DIR}"
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if [[ -n "$extra_json" ]]; then
    printf '{"type":"%s","ts":"%s","story_id":"%s",%s}\n' \
      "$event_type" "$ts" "${NEXT_STORY:-}" "$extra_json" >> "$events_file"
  else
    printf '{"type":"%s","ts":"%s","story_id":"%s"}\n' \
      "$event_type" "$ts" "${NEXT_STORY:-}" >> "$events_file"
  fi
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
    # ── Focus-tags filter: skip stories that don't match any requested tag ──
    if [[ -n "${SPIRAL_FOCUS_TAGS:-}" ]]; then
      _STORY_TAGS=$($JQ -r ".userStories[] | select(.id == \"$candidate\") | .tags // [] | join(\",\")" "$PRD_FILE" | tr -d '\r')
      _TAG_MATCH=0
      IFS=',' read -ra _WANTED_TAGS <<< "$SPIRAL_FOCUS_TAGS"
      for _wt in "${_WANTED_TAGS[@]}"; do
        if [[ ",$_STORY_TAGS," == *",$_wt,"* ]]; then
          _TAG_MATCH=1
          break
        fi
      done
      if [[ "$_TAG_MATCH" -eq 0 ]]; then
        continue  # skip — no matching tag (not failed, not retry-counted)
      fi
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

  # ── Circuit breaker check with model fallback chain ─────────────────────
  _CB_ENDPOINT="${EFFECTIVE_MODEL:-${EFFECTIVE_TOOL:-default}}"
  _FALLBACK_USED=""
  _ALL_MODELS_OPEN=0
  if declare -f cb_check > /dev/null 2>&1; then
    if ! cb_check "$_CB_ENDPOINT"; then
      echo "  [cb] Circuit breaker OPEN for $_CB_ENDPOINT — checking fallback chain"
      # Try fallback models from SPIRAL_MODEL_FALLBACK_CHAIN
      if [[ -n "$SPIRAL_MODEL_FALLBACK_CHAIN" && "$EFFECTIVE_TOOL" == "claude" ]]; then
        _PRIMARY_MODEL="$_CB_ENDPOINT"
        IFS=':' read -ra _FALLBACK_MODELS <<< "$SPIRAL_MODEL_FALLBACK_CHAIN"
        _FOUND_FALLBACK=0
        for _FB_MODEL in "${_FALLBACK_MODELS[@]}"; do
          # Skip the primary model (already checked)
          [[ "$_FB_MODEL" == "$_PRIMARY_MODEL" ]] && continue
          if cb_check "$_FB_MODEL"; then
            echo "  [cb] Falling back to $_FB_MODEL (primary $_PRIMARY_MODEL OPEN)"
            log_spiral_event "model_fallback" \
              "\"primary_model\":\"$_PRIMARY_MODEL\",\"fallback_model\":\"$_FB_MODEL\",\"reason\":\"circuit_breaker_open\""
            EFFECTIVE_MODEL="$_FB_MODEL"
            _CB_ENDPOINT="$_FB_MODEL"
            _FALLBACK_USED="$_FB_MODEL"
            _FOUND_FALLBACK=1
            break
          else
            echo "  [cb] Fallback $_FB_MODEL also OPEN — trying next"
          fi
        done
        if [[ "$_FOUND_FALLBACK" -eq 0 ]]; then
          echo "  [cb] All models in fallback chain are OPEN — deferring story"
          log_spiral_event "all_models_unavailable" \
            "\"story_id\":\"$NEXT_STORY\",\"primary_model\":\"$_PRIMARY_MODEL\",\"chain\":\"$SPIRAL_MODEL_FALLBACK_CHAIN\""
          # Set _failureReason on the story
          $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason) = \"all_models_unavailable\"" \
            "$PRD_FILE" > "${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
          _ALL_MODELS_OPEN=1
        fi
      else
        echo "  [cb] Circuit breaker OPEN for $_CB_ENDPOINT — no fallback chain configured"
        log_spiral_event "circuit_breaker_blocked" \
          "\"endpoint\":\"$_CB_ENDPOINT\",\"story_id\":\"$NEXT_STORY\""
      fi
    fi
  fi

  # ── Skip to next story if all models unavailable ───────────────────────
  if [[ "$_ALL_MODELS_OPEN" -eq 1 ]]; then
    STORY_END=$(date +%s)
    append_result "deferred"
    echo "## Iteration $ITERATION - $(date)" >> "$PROGRESS_FILE"
    echo "DEFERRED: $STORY_TITLE ($NEXT_STORY) — all models in fallback chain unavailable" >> "$PROGRESS_FILE"
    echo "" >> "$PROGRESS_FILE"
    continue
  fi

  # ── Rate-limit retry loop (covers all AI tools) ────────────────────────────
  _RL_ATTEMPT=0
  _RL_MAX=5
  _RL_TMP="${SPIRAL_SCRATCH_DIR}/_rate_limit_check_$$.tmp"

  while true; do
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
    # Wrap with 529 overloaded_error retry loop (separate from 429 rate-limit handling)
    _529_ATTEMPT=0
    _529_MAX=5
    _529_BASE=2
    _529_CAP=30
    while true; do
      _CLAUDE_TMP="${SPIRAL_SCRATCH_DIR}/_claude_raw_$$.tmp"
      mkdir -p "${SPIRAL_SCRATCH_DIR}"
      (unset CLAUDECODE; claude -p "$RALPH_PROMPT_CONTENT" \
        $CLAUDE_MODEL_FLAG \
        --allowedTools "Edit,Write,Read,Glob,Grep,Bash,Skill,Task" \
        --max-turns 75 \
        --verbose \
        --output-format stream-json \
        --dangerously-skip-permissions \
        2>&1 | tee "$_CLAUDE_TMP" | node "$SCRIPT_DIR/stream-formatter.mjs") || true
      # Detect HTTP 529 overloaded_error — separate handler from 429 rate-limit
      if grep -qE 'overloaded_error|"529"' "$_CLAUDE_TMP" 2>/dev/null; then
        _529_ATTEMPT=$((_529_ATTEMPT + 1))
        rm -f "$_CLAUDE_TMP"
        if [[ "$_529_ATTEMPT" -gt "$_529_MAX" ]]; then
          echo "  [529] Max overload retries ($_529_MAX) reached — proceeding to story outcome check"
          break
        fi
        _delay=$(( _529_BASE * (2 ** (_529_ATTEMPT - 1)) ))
        [[ "$_delay" -gt "$_529_CAP" ]] && _delay="$_529_CAP"
        _jitter=$(( (_delay * 10) / 100 + 1 ))
        _sleep=$(( _delay + RANDOM % _jitter ))
        echo "  [529] API overloaded (attempt $_529_ATTEMPT/$_529_MAX) — retrying in ${_sleep}s..."
        log_spiral_event "api_overloaded" "\"retry_attempt\":${_529_ATTEMPT},\"sleep_sec\":${_sleep}"
        sleep "$_sleep"
      else
        mv "$_CLAUDE_TMP" "$_RL_TMP" 2>/dev/null || true
        break
      fi
    done
  elif [[ "$EFFECTIVE_TOOL" == "codex" ]]; then
    echo "  [ralph] Delegating to Codex (GPT-5)..."
    PROMPT_TEXT=$(cat "$PROMPT_FILE")
    codex exec --full-auto -C "$(pwd)" "$PROMPT_TEXT" 2>&1 | tee "$_RL_TMP" | tail -60
  elif [[ "$EFFECTIVE_TOOL" == "qwen" ]]; then
    echo "  [ralph] Delegating to Qwen Code (free quota)..."
    PROMPT_TEXT=$(cat "$PROMPT_FILE")
    qwen "$PROMPT_TEXT" --approval-mode yolo 2>&1 | tee "$_RL_TMP" | tail -200
  else
    amp --prompt-file "$PROMPT_FILE" 2>&1 | tee "$_RL_TMP"
  fi
  echo "  ─────── AI Output End ($EFFECTIVE_TOOL) ─────────"

  # ── Rate-limit / transient-error detection (all AI tools) ─────────────────
  _RL_ERROR_CODE=0
  if grep -qiE 'HTTP 429|"429"|rate_limit_error|Too Many Requests' "$_RL_TMP" 2>/dev/null; then
    _RL_ERROR_CODE=429
  elif grep -qiE '"502"|HTTP 502|bad.?gateway' "$_RL_TMP" 2>/dev/null; then
    _RL_ERROR_CODE=502
  elif grep -qiE '"503"|HTTP 503|service.?unavailable' "$_RL_TMP" 2>/dev/null; then
    _RL_ERROR_CODE=503
  fi
  if [[ "$_RL_ERROR_CODE" -ne 0 ]]; then
    _RL_ATTEMPT=$((_RL_ATTEMPT + 1))
    # Record failure in circuit breaker
    if declare -f cb_record_failure > /dev/null 2>&1; then
      cb_record_failure "$_CB_ENDPOINT" "$_RL_ERROR_CODE"
    fi
    rm -f "$_RL_TMP"
    if [[ "$_RL_ATTEMPT" -gt "$_RL_MAX" ]]; then
      echo "  [ralph] Rate limit max retries ($_RL_MAX) reached — proceeding to story outcome check"
      break
    fi
    echo "  [ralph] Transient error $_RL_ERROR_CODE — waiting 60s before retry (attempt $_RL_ATTEMPT/$_RL_MAX)"
    log_spiral_event "rate_limited" "\"retry_attempt\":${_RL_ATTEMPT},\"sleep_sec\":60,\"error_code\":${_RL_ERROR_CODE}"
    sleep 60
    continue
  fi
  # Successful call — reset circuit breaker
  if declare -f cb_record_success > /dev/null 2>&1; then
    cb_record_success "$_CB_ENDPOINT"
  fi

  # ── Parse token counts from LLM output (before cleanup) ─────────────────
  _CALL_TOKENS_INPUT=0
  _CALL_TOKENS_OUTPUT=0
  if [[ "$EFFECTIVE_TOOL" == "claude" && -f "$_RL_TMP" ]]; then
    _RESULT_LINE=$(grep -m1 '"type":"result"' "$_RL_TMP" 2>/dev/null || true)
    if [[ -n "$_RESULT_LINE" ]]; then
      _ti=$($JQ -r '.usage.input_tokens // 0' <<< "$_RESULT_LINE" 2>/dev/null || echo 0)
      _to=$($JQ -r '.usage.output_tokens // 0' <<< "$_RESULT_LINE" 2>/dev/null || echo 0)
      [[ "$_ti" =~ ^[0-9]+$ ]] && _CALL_TOKENS_INPUT=$_ti
      [[ "$_to" =~ ^[0-9]+$ ]] && _CALL_TOKENS_OUTPUT=$_to
    fi
  fi

  rm -f "$_RL_TMP"
  break
  done  # end rate-limit retry loop

  # ── Accumulate per-story token cost ───────────────────────────────────────
  _STORY_CUMULATIVE_USD=0
  if [[ "$_CALL_TOKENS_INPUT" -gt 0 || "$_CALL_TOKENS_OUTPUT" -gt 0 ]]; then
    _STORY_CUMULATIVE_USD=$(accumulate_story_cost "$NEXT_STORY" "$_CALL_TOKENS_INPUT" "$_CALL_TOKENS_OUTPUT" 2>/dev/null || echo 0)
    echo "  [cost] Story $NEXT_STORY: input=${_CALL_TOKENS_INPUT} output=${_CALL_TOKENS_OUTPUT} tokens | cumulative \$${_STORY_CUMULATIVE_USD}"
  fi

  # ── Per-story cost enforcement ───────────────────────────────────────────
  _STORY_COST_ABANDON=0
  if [[ -n "$_STORY_CUMULATIVE_USD" ]] && python3 -c "
import sys
try:
    cur = float('${_STORY_CUMULATIVE_USD}')
    hard = float('${SPIRAL_STORY_COST_HARD_USD}')
    sys.exit(0 if cur >= hard else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    echo "  [cost] WARNING: Story $NEXT_STORY cumulative cost \$${_STORY_CUMULATIVE_USD} exceeds hard limit \$${SPIRAL_STORY_COST_HARD_USD} — abandoning"
    log_ralph_event "story_cost_ceiling" \
      "\"story_id\":\"$NEXT_STORY\",\"cumulative_usd\":${_STORY_CUMULATIVE_USD},\"hard_limit\":${SPIRAL_STORY_COST_HARD_USD}"
    $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason) = \"story_cost_ceiling\"" "$PRD_FILE" > "${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
    _STORY_COST_ABANDON=1
  elif [[ -n "$_STORY_CUMULATIVE_USD" ]] && python3 -c "
import sys
try:
    cur = float('${_STORY_CUMULATIVE_USD}')
    warn = float('${SPIRAL_STORY_COST_WARN_USD}')
    sys.exit(0 if cur >= warn else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    echo "  [cost] WARNING: Story $NEXT_STORY cumulative cost \$${_STORY_CUMULATIVE_USD} exceeds warn threshold \$${SPIRAL_STORY_COST_WARN_USD} — continuing"
  fi

  STORY_END=$(date +%s)
  STORY_DURATION=$(( (STORY_END - STORY_START) / 60 ))
  echo "  [time] Story took ${STORY_DURATION}m"

  # ── Cost ceiling: abandon story if hard limit exceeded ────────────────────
  if [[ "$_STORY_COST_ABANDON" -eq 1 ]]; then
    $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" > "${PRD_FILE}.tmp"
    mv "${PRD_FILE}.tmp" "$PRD_FILE"
    increment_retry "$NEXT_STORY"
    RETRY_NOW=$(get_retry_count "$NEXT_STORY")
    append_result "reject"
    echo "## Iteration $ITERATION - $(date)" >> "$PROGRESS_FILE"
    echo "COST CEILING: $STORY_TITLE ($NEXT_STORY) — \$${_STORY_CUMULATIVE_USD} exceeded hard limit \$${SPIRAL_STORY_COST_HARD_USD}" >> "$PROGRESS_FILE"
    echo "" >> "$PROGRESS_FILE"
    continue
  fi

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
      append_result "reject"
      echo "## Iteration $ITERATION - $(date)" >> "$PROGRESS_FILE"
      echo "TIME BUDGET EXCEEDED: $STORY_TITLE ($NEXT_STORY) — ${STORY_DURATION_SEC}s > ${STORY_TIME_BUDGET}s budget" >> "$PROGRESS_FILE"
      if [[ "$RETRY_NOW" -ge "$MAX_RETRIES" ]]; then
        FAILURE_REASON="TIME_BUDGET_EXCEEDED (${STORY_DURATION_SEC}s > ${STORY_TIME_BUDGET}s limit)"
        $JQ --arg reason "$FAILURE_REASON" \
          '(.userStories[] | select(.id == "'"$NEXT_STORY"'") | ._failureReason) = $reason' \
          "$PRD_FILE" > "${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
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

      # Record _passedCommit SHA in prd.json for traceability
      COMMIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo '')
      if [[ -n "$COMMIT_SHA" ]]; then
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\"))._passedCommit = \"$COMMIT_SHA\"" "$PRD_FILE" > "${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
      fi

      append_result "keep" "$COMMIT_SHA"
      log_ralph_event "story_passed" "\"storyId\":\"$NEXT_STORY\",\"retryCount\":$(get_retry_count "$NEXT_STORY"),\"model\":\"${EFFECTIVE_MODEL:-sonnet}\""

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
      append_result "reject"
      log_ralph_event "story_failed" "\"storyId\":\"$NEXT_STORY\",\"retryCount\":$RETRY_NOW,\"model\":\"${EFFECTIVE_MODEL:-sonnet}\""

      echo "## Iteration $ITERATION - $(date)" >> "$PROGRESS_FILE"
      echo "FAILED quality gates: $STORY_TITLE (ID: $NEXT_STORY) — attempt $RETRY_NOW/$MAX_RETRIES" >> "$PROGRESS_FILE"
      if [[ "$RETRY_NOW" -ge "$MAX_RETRIES" ]]; then
        FAILURE_REASON="MAX_RETRIES exhausted (quality gate failed after $MAX_RETRIES attempts)"
        $JQ --arg reason "$FAILURE_REASON" \
          '(.userStories[] | select(.id == "'"$NEXT_STORY"'") | ._failureReason) = $reason' \
          "$PRD_FILE" > "${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
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
    append_result "reject"
    log_ralph_event "story_failed" "\"storyId\":\"$NEXT_STORY\",\"retryCount\":$RETRY_NOW,\"model\":\"${EFFECTIVE_MODEL:-sonnet}\""

    echo "## Iteration $ITERATION - $(date)" >> "$PROGRESS_FILE"
    echo "Incomplete: $STORY_TITLE (ID: $NEXT_STORY) — attempt $RETRY_NOW/$MAX_RETRIES" >> "$PROGRESS_FILE"
    if [[ "$RETRY_NOW" -ge "$MAX_RETRIES" ]]; then
      FAILURE_REASON="MAX_RETRIES exhausted (story incomplete after $MAX_RETRIES attempts)"
      $JQ --arg reason "$FAILURE_REASON" \
        '(.userStories[] | select(.id == "'"$NEXT_STORY"'") | ._failureReason) = $reason' \
        "$PRD_FILE" > "${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
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
