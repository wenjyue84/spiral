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
STORY_TIME_BUDGET="${SPIRAL_STORY_TIME_BUDGET:-0}"                          # 0 = disabled
SPIRAL_STORY_COST_WARN_USD="${SPIRAL_STORY_COST_WARN_USD:-0.50}"            # warn when story exceeds this
SPIRAL_STORY_COST_HARD_USD="${SPIRAL_STORY_COST_HARD_USD:-2.00}"            # abandon story when it exceeds this
SPIRAL_MODEL_INPUT_PRICE_PER_M="${SPIRAL_MODEL_INPUT_PRICE_PER_M:-3.00}"    # $/1M input tokens (sonnet default)
SPIRAL_MODEL_OUTPUT_PRICE_PER_M="${SPIRAL_MODEL_OUTPUT_PRICE_PER_M:-15.00}" # $/1M output tokens (sonnet default)
SPIRAL_MODEL_FALLBACK_CHAIN="${SPIRAL_MODEL_FALLBACK_CHAIN:-}"              # colon-separated fallback models (e.g. sonnet:haiku:gemini-2.0-flash)
SPIRAL_MAX_DIFF_LINES="${SPIRAL_MAX_DIFF_LINES:-500}"                       # 0 = disabled; abort commit if staged diff exceeds this many changed lines
SPIRAL_GIT_AUTHOR="${SPIRAL_GIT_AUTHOR:-}"                                  # optional: AI commit author name (e.g. "SPIRAL Agent")
SPIRAL_GIT_EMAIL="${SPIRAL_GIT_EMAIL:-}"                                    # optional: AI commit author email (e.g. "spiral@noreply.local")
SPIRAL_DECOMPOSE_THRESHOLD="${SPIRAL_DECOMPOSE_THRESHOLD:-2}"               # auto-decompose story at this retry count; 0 = disabled
SPIRAL_SECURITY_SCAN="${SPIRAL_SECURITY_SCAN:-false}"                       # true = enable Phase S security scan gate
SPIRAL_SECURITY_SCAN_TOOL="${SPIRAL_SECURITY_SCAN_TOOL:-semgrep}"           # 'semgrep' (default) or 'bandit'
SPIRAL_SECURITY_SCAN_ARGS="${SPIRAL_SECURITY_SCAN_ARGS:-}"                  # extra flags passed to the scanner binary
SPIRAL_PRD_STREAM_THRESHOLD_KB="${SPIRAL_PRD_STREAM_THRESHOLD_KB:-512}"     # switch to jq --stream when prd.json exceeds this size (KB); 0 = always stream
SPIRAL_OLLAMA_FALLBACK_MODEL="${SPIRAL_OLLAMA_FALLBACK_MODEL:-}"        # Ollama model for Claude API fallback (e.g. qwen2.5-coder:32b); empty = disabled
SPIRAL_OLLAMA_HOST="${SPIRAL_OLLAMA_HOST:-http://localhost:11434/v1}"   # Ollama OpenAI-compat base URL (default: local Ollama)
SPIRAL_SKIP_SELF_REVIEW="${SPIRAL_SKIP_SELF_REVIEW:-false}"             # true = disable Phase I.5 LLM self-review gate (US-145)
SPIRAL_SELF_REVIEW_MODEL="${SPIRAL_SELF_REVIEW_MODEL:-haiku}"           # Claude model for self-review; haiku to minimise cost (US-145)
SPIRAL_GEMINI_SKIP_SMALL="${SPIRAL_GEMINI_SKIP_SMALL:-true}"           # true = skip Gemini pre-analysis for small stories with <=2 filesTouch (US-171)
SPIRAL_SKIP_ADR="${SPIRAL_SKIP_ADR:-false}"                             # true = disable ADR generation after story passes (US-155)
SPIRAL_ADR_MODEL="${SPIRAL_ADR_MODEL:-haiku}"                           # Claude model for ADR generation; haiku to minimise cost (US-155)
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
if command -v jq &>/dev/null; then
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

# ── Source spiral_retry library for API retry with jitter ───────────────────
SPIRAL_HOME="${SPIRAL_HOME:-.}"
[[ -f "$SPIRAL_HOME/lib/spiral_retry.sh" ]] && source "$SPIRAL_HOME/lib/spiral_retry.sh"

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
  printf '%s\n' "$line" >>"$log_file" 2>/dev/null || true
}

# ── Per-story token cost accumulation ────────────────────────────────────────
# accumulate_story_cost <story_id> <tokens_input> <tokens_output> [cache_creation_tokens] [cache_read_tokens]
# Writes atomically to $SPIRAL_SCRATCH_DIR/story_costs.json.
# Emits a cost_update event to spiral_events.jsonl.
# Prints the new cumulative estimated_usd for the story on stdout.
# Returns 0 always (errors are non-fatal).
# When prompt caching is active, cache_read tokens are priced at 10% of input price
# and cache_creation tokens at 125% of input price (per Anthropic pricing).
accumulate_story_cost() {
  local story_id="$1" tokens_input="${2:-0}" tokens_output="${3:-0}"
  local cache_creation="${4:-0}" cache_read="${5:-0}"
  local cost_file="$SPIRAL_SCRATCH_DIR/story_costs.json"
  local input_price="$SPIRAL_MODEL_INPUT_PRICE_PER_M"
  local output_price="$SPIRAL_MODEL_OUTPUT_PRICE_PER_M"

  local cumulative_usd
  cumulative_usd=$(
    python3 - <<PYEOF 2>/dev/null
import json, os, sys

story_id = '$story_id'
tokens_input = int('$tokens_input') if '$tokens_input'.isdigit() else 0
tokens_output = int('$tokens_output') if '$tokens_output'.isdigit() else 0
cache_creation = int('$cache_creation') if '$cache_creation'.isdigit() else 0
cache_read = int('$cache_read') if '$cache_read'.isdigit() else 0
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
# Cost calculation: non-cached input at full price, cache creation at 1.25x, cache read at 0.1x
non_cached_input = max(0, tokens_input - cache_creation - cache_read)
call_cost = ((non_cached_input / 1_000_000) * input_price
             + (cache_creation / 1_000_000) * input_price * 1.25
             + (cache_read / 1_000_000) * input_price * 0.1
             + (tokens_output / 1_000_000) * output_price)
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
  echo "## Codebase Patterns" >"$PROGRESS_FILE"
  echo "" >>"$PROGRESS_FILE"
  echo "(Patterns will be added by Ralph iterations as they discover them)" >>"$PROGRESS_FILE"
  echo "" >>"$PROGRESS_FILE"
  echo "---" >>"$PROGRESS_FILE"
  echo "" >>"$PROGRESS_FILE"
  echo "# Ralph Progress Log - $(date)" >>"$PROGRESS_FILE"
  echo "Started autonomous agent loop for PRD completion" >>"$PROGRESS_FILE"
  echo "" >>"$PROGRESS_FILE"
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
[[ "$STORY_TIME_BUDGET" -gt 0 ]] &&
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

# ── Secret scanning gate ─────────────────────────────────────────
# run_secret_scan: Runs gitleaks on staged files before git commit.
# Returns 0 (ok to commit) or 1 (secrets detected, abort commit).
# Honors SPIRAL_SKIP_SECRET_SCAN=true to bypass for development use.
run_secret_scan() {
  if [[ "${SPIRAL_SKIP_SECRET_SCAN:-false}" == "true" ]]; then
    log_ralph_event "secret_scan_skipped" "\"storyId\":\"$NEXT_STORY\",\"reason\":\"SPIRAL_SKIP_SECRET_SCAN=true\""
    echo "  [secret-scan] SKIPPED (SPIRAL_SKIP_SECRET_SCAN=true)"
    return 0
  fi

  if ! command -v gitleaks >/dev/null 2>&1; then
    echo "  [secret-scan] gitleaks not found in PATH — skipping (install gitleaks to enable secret scanning)"
    return 0
  fi

  local report_path="${SPIRAL_SCRATCH_DIR}/gitleaks-report.json"
  mkdir -p "${SPIRAL_SCRATCH_DIR}"

  if gitleaks detect --staged --report-format json --report-path "$report_path" >/dev/null 2>&1; then
    echo "  [secret-scan] No secrets detected"
    return 0
  else
    local findings=0
    if [[ -f "$report_path" ]]; then
      findings=$($JQ 'length' "$report_path" 2>/dev/null || echo "1")
    else
      findings=1
    fi
    log_ralph_event "secret_detected" "\"storyId\":\"$NEXT_STORY\",\"findings\":$findings,\"reportPath\":\"$report_path\""
    echo "  [secret-scan] SECRETS DETECTED ($findings finding(s)) — commit aborted"
    echo "  [secret-scan] Report: $report_path"
    return 1
  fi
}

# ── Git identity helper ─────────────────────────────────────────
# do_git_commit: Wraps `git commit` with optional identity overrides.
# When SPIRAL_GIT_AUTHOR is set, passes -c user.name / user.email to avoid
# modifying the global git config and appends a Generated-By trailer.
# When unset, behaviour is identical to a plain `git commit -m <msg>`.
do_git_commit() {
  local msg="$1"
  if [[ -n "${SPIRAL_GIT_AUTHOR:-}" ]]; then
    local email="${SPIRAL_GIT_EMAIL:-spiral@noreply.local}"
    msg="${msg}
Generated-By: SPIRAL"
    git -c "user.name=${SPIRAL_GIT_AUTHOR}" -c "user.email=${email}" commit -m "$msg"
  else
    git commit -m "$msg"
  fi
}

# do_story_reset: Hard-reset working tree to the pre-story baseline SHA.
# Called on every failure path so each retry starts from a clean state.
# This is the Karpathy ratchet: failed experiments leave zero traces in git.
do_story_reset() {
  local baseline="${1:-}"
  if [[ -n "$baseline" ]]; then
    git reset --hard "$baseline" 2>/dev/null || git checkout -- . 2>/dev/null || true
  else
    git checkout -- . 2>/dev/null || true
  fi
}

# ── Conventional Commit message builder ─────────────────────────
# build_commit_msg: Generates a Conventional Commits v1.0 compliant message
# from story metadata.
#
# Args:
#   $1 - story_id       (e.g. "US-042")
#   $2 - story_title    (e.g. "Add retry logic to worker")
#   $3 - story_tags_csv (comma-separated list from prd.json .tags, or "")
#   $4 - files_touch    (first filesTouch entry, or "")
#   $5 - spiral_run_id  (value of $SPIRAL_RUN_ID, or "")
#   $6 - iteration      (Ralph iteration number, for the body line)
#   $7 - duration       (story duration in minutes)
#
# Output format:
#   <type>(<scope>): <story_title>
#
#   Completed by Ralph iteration <N> (<Dm>)
#
#   Story: <STORY_ID>
#   SPIRAL-Run: <SPIRAL_RUN_ID>
#   Co-Authored-By: Claude ...
build_commit_msg() {
  local story_id="${1:-}"
  local story_title="${2:-}"
  local story_tags_csv="${3:-}"
  local first_file="${4:-}"
  local spiral_run_id="${5:-}"
  local iteration="${6:-}"
  local duration="${7:-}"

  # Derive type from first recognised tag; default to "feat"
  local commit_type="feat"
  local tag
  IFS=',' read -ra _tags <<< "$story_tags_csv"
  for tag in "${_tags[@]}"; do
    tag="${tag// /}"   # strip whitespace
    case "$tag" in
      feat|fix|chore|refactor|test|docs|perf|ci|build|style)
        commit_type="$tag"
        break
        ;;
    esac
  done

  # Derive scope from top-level directory of first filesTouch entry
  local commit_scope=""
  if [[ -n "$first_file" ]]; then
    # Strip leading ./ if present, then take the first path component
    first_file="${first_file#./}"
    local top_dir="${first_file%%/*}"
    # If the file is at root level (no slash), use the filename stem
    if [[ "$top_dir" == "$first_file" ]]; then
      top_dir="${first_file%.*}"
    fi
    commit_scope="$top_dir"
  fi

  # Build subject line
  local subject
  if [[ -n "$commit_scope" ]]; then
    subject="${commit_type}(${commit_scope}): ${story_title}"
  else
    subject="${commit_type}: ${story_title}"
  fi

  # Build body + trailers
  local body="Completed by Ralph iteration ${iteration} (${duration}m)"
  local trailers="Story: ${story_id}"
  if [[ -n "$spiral_run_id" ]]; then
    trailers="${trailers}
SPIRAL-Run: ${spiral_run_id}"
  fi

  printf '%s\n\n%s\n\n%s\n' "$subject" "$body" "$trailers"
}

# ── Diff size guard ─────────────────────────────────────────────
# _parse_diff_lines: Extract total changed lines (insertions + deletions)
# from a `git diff --stat` summary line such as:
#   "3 files changed, 450 insertions(+), 120 deletions(-)"
# Returns the numeric total on stdout; returns 0 on empty/unrecognised input.
_parse_diff_lines() {
  local stat_line="$1"
  echo "$stat_line" | awk '
    {
      ins=0; del=0
      if (match($0, /([0-9]+) insertion/, a)) {
        ins = a[1]
      }
      if (match($0, /([0-9]+) deletion/, a)) {
        del = a[1]
      }
      print ins + del
    }'
}

# check_diff_size: Returns 0 (ok) or 1 (oversized) based on staged diff size.
# Honors SPIRAL_MAX_DIFF_LINES=0 to disable the guard.
check_diff_size() {
  if [[ "${SPIRAL_MAX_DIFF_LINES:-500}" -eq 0 ]]; then
    return 0
  fi

  local stat_summary
  stat_summary=$(git diff --cached --stat 2>/dev/null | tail -1 | tr -d '\r')
  if [[ -z "$stat_summary" ]]; then
    return 0 # No staged changes — nothing to guard
  fi

  local total_lines
  total_lines=$(_parse_diff_lines "$stat_summary")
  LAST_DIFF_STAT="$stat_summary"
  LAST_DIFF_LINES="${total_lines:-0}"

  if [[ "${total_lines:-0}" -gt "${SPIRAL_MAX_DIFF_LINES:-500}" ]]; then
    return 1
  fi
  return 0
}

# ── Security scan gate (Phase S) ────────────────────────────────
# run_security_scan: Optional Phase S gate between quality checks and git commit.
# Enabled by SPIRAL_SECURITY_SCAN=true.  Scans only staged files.
# HIGH-severity findings → returns 1 (abort commit).
# MEDIUM findings → warning only, returns 0.
# Scanner binary not found → skips with warning, returns 0.
run_security_scan() {
  if [[ "${SPIRAL_SECURITY_SCAN:-false}" != "true" ]]; then
    return 0
  fi

  local tool="${SPIRAL_SECURITY_SCAN_TOOL:-semgrep}"
  local extra_args="${SPIRAL_SECURITY_SCAN_ARGS:-}"
  local report_path="${SPIRAL_SCRATCH_DIR}/security_scan_${NEXT_STORY}.json"
  mkdir -p "${SPIRAL_SCRATCH_DIR}"

  # Collect staged files
  local staged_files
  staged_files=$(git diff --cached --name-only 2>/dev/null)
  if [[ -z "$staged_files" ]]; then
    echo "  [security-scan] No staged files — skipping"
    return 0
  fi

  if [[ "$tool" == "bandit" ]]; then
    if ! command -v bandit >/dev/null 2>&1; then
      echo "  [security-scan] bandit not found in PATH — skipping (install bandit to enable)"
      log_ralph_event "security_scan_skipped" "\"storyId\":\"$NEXT_STORY\",\"reason\":\"bandit_not_found\""
      return 0
    fi
    # bandit only handles Python files
    local py_files
    py_files=$(echo "$staged_files" | grep '\.py$' || true)
    if [[ -z "$py_files" ]]; then
      echo "  [security-scan] No Python files staged — bandit scan skipped"
      return 0
    fi
    # shellcheck disable=SC2086
    bandit -r $py_files ${extra_args:+$extra_args} -f json -o "$report_path" >/dev/null 2>&1 || true

    local high_count medium_count
    high_count=$($JQ '[.results[] | select(.issue_severity == "HIGH")] | length' "$report_path" 2>/dev/null || echo "0")
    medium_count=$($JQ '[.results[] | select(.issue_severity == "MEDIUM")] | length' "$report_path" 2>/dev/null || echo "0")

  else
    # Default: semgrep
    if ! command -v semgrep >/dev/null 2>&1; then
      echo "  [security-scan] semgrep not found in PATH — skipping (install semgrep to enable)"
      log_ralph_event "security_scan_skipped" "\"storyId\":\"$NEXT_STORY\",\"reason\":\"semgrep_not_found\""
      return 0
    fi
    # shellcheck disable=SC2086
    semgrep --config=auto --json --output="$report_path" ${extra_args:+$extra_args} $staged_files >/dev/null 2>&1 || true

    local high_count medium_count
    high_count=$($JQ '[.results[] | select(.extra.severity == "ERROR")] | length' "$report_path" 2>/dev/null || echo "0")
    medium_count=$($JQ '[.results[] | select(.extra.severity == "WARNING")] | length' "$report_path" 2>/dev/null || echo "0")
  fi

  if [[ "${medium_count:-0}" -gt 0 ]]; then
    echo "  [security-scan] WARNING: $medium_count MEDIUM-severity finding(s) — see $report_path"
  fi

  if [[ "${high_count:-0}" -gt 0 ]]; then
    log_ralph_event "security_scan_failure" "\"storyId\":\"$NEXT_STORY\",\"tool\":\"$tool\",\"highCount\":$high_count,\"mediumCount\":${medium_count:-0},\"reportPath\":\"$report_path\""
    echo "  [security-scan] FAILED: $high_count HIGH-severity finding(s) detected — commit aborted"
    echo "  [security-scan] Report: $report_path"
    return 1
  fi

  log_ralph_event "security_scan_passed" "\"storyId\":\"$NEXT_STORY\",\"tool\":\"$tool\",\"mediumCount\":${medium_count:-0},\"reportPath\":\"$report_path\""
  echo "  [security-scan] Passed ($tool: 0 HIGH findings)"
  return 0
}

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

capture_test_baseline() {
  # Returns numeric count of currently passing tests.
  # Returns -1 if test runner cannot be detected (gate will be skipped).
  # Override with SPIRAL_TEST_BASELINE_CMD for project-specific runners.
  if [[ -n "${SPIRAL_TEST_BASELINE_CMD:-}" ]]; then
    local raw
    raw=$(eval "$SPIRAL_TEST_BASELINE_CMD" 2>/dev/null) || true
    # Try to parse a bare integer first, then "N passed" patterns
    if echo "$raw" | grep -qP '^\d+$'; then
      echo "$raw" | grep -oP '^\d+'
    elif echo "$raw" | grep -qP '\d+ passed'; then
      echo "$raw" | grep -oP '\d+(?= passed)' | head -1
    else
      echo "-1"
    fi
    return
  fi
  # Auto-detect: pytest
  if command -v python3 &>/dev/null && [[ -f "pytest.ini" || -f "pyproject.toml" || -f "setup.cfg" || -d "tests" ]]; then
    local out
    out=$(python3 -m pytest --tb=no -q 2>/dev/null) || true
    local n
    n=$(echo "$out" | grep -oP '^\d+(?= passed)' | head -1)
    echo "${n:-0}"
    return
  fi
  # Auto-detect: vitest (package.json with vitest dependency)
  if command -v npx &>/dev/null && [[ -f "package.json" ]] && grep -q '"vitest"' package.json 2>/dev/null; then
    local out
    out=$(npx vitest run --reporter=verbose 2>/dev/null) || true
    local n
    n=$(echo "$out" | grep -oP '(\d+) passed' | grep -oP '\d+' | head -1)
    echo "${n:-0}"
    return
  fi
  # Auto-detect: bats
  if command -v bats &>/dev/null && ls tests/*.bats &>/dev/null 2>&1; then
    local out
    out=$(bats tests/ 2>/dev/null) || true
    local n
    n=$(echo "$out" | grep -oP '\d+(?= test)' | head -1)
    echo "${n:-0}"
    return
  fi
  echo "-1"  # -1 = unknown, gate will be skipped
}

check_test_ratchet() {
  local baseline="${1:--1}"
  if [[ "$baseline" == "-1" || "${SPIRAL_SKIP_TEST_RATCHET:-false}" == "true" ]]; then
    echo "  [test-ratchet] SKIP (baseline unknown or SPIRAL_SKIP_TEST_RATCHET=true)"
    return 0
  fi
  local after
  after=$(capture_test_baseline)
  if [[ "$after" == "-1" ]]; then
    echo "  [test-ratchet] SKIP (could not measure post-story test count)"
    return 0
  fi
  if [[ "$after" -lt "$baseline" ]]; then
    echo "  [test-ratchet] FAIL: $after passing (was $baseline) — $((baseline - after)) test(s) broken"
    return 1
  fi
  echo "  [test-ratchet] PASS: $after passing (was $baseline)"
  return 0
}

# ── Retry tracking ───────────────────────────────────────────────
RETRY_FILE="retry-counts.json"
if [[ ! -f "$RETRY_FILE" ]]; then
  echo '{}' >"$RETRY_FILE"
fi
MAX_RETRIES=3
ESCALATION_FILE="escalation-counts.json"
MAX_ESCALATIONS=2

get_retry_count() {
  local story_id="$1"
  $JQ -r ".\"$story_id\" // 0" "$RETRY_FILE" | tr -d '\r'
}

increment_retry() {
  local story_id="$1"
  local current
  current=$(get_retry_count "$story_id")
  $JQ ".\"$story_id\" = $((current + 1))" "$RETRY_FILE" >"${RETRY_FILE}.tmp"
  mv "${RETRY_FILE}.tmp" "$RETRY_FILE"
}

reset_retry() {
  local story_id="$1"
  $JQ "del(.\"$story_id\")" "$RETRY_FILE" >"${RETRY_FILE}.tmp"
  mv "${RETRY_FILE}.tmp" "$RETRY_FILE"
}

if [[ ! -f "$ESCALATION_FILE" ]]; then
  echo '{}' >"$ESCALATION_FILE"
fi

get_escalation_count() {
  local story_id="$1"
  $JQ -r ".\"$story_id\" // 0" "$ESCALATION_FILE" | tr -d '\r'
}

increment_escalation() {
  local story_id="$1"
  local current
  current=$(get_escalation_count "$story_id")
  $JQ ".\"$story_id\" = $((current + 1))" "$ESCALATION_FILE" >"${ESCALATION_FILE}.tmp"
  mv "${ESCALATION_FILE}.tmp" "$ESCALATION_FILE"
}

reset_escalation() {
  local story_id="$1"
  $JQ "del(.\"$story_id\")" "$ESCALATION_FILE" >"${ESCALATION_FILE}.tmp"
  mv "${ESCALATION_FILE}.tmp" "$ESCALATION_FILE"
}

# ── Auto-decompose at retry threshold ────────────────────────────
# Called after increment_retry. Triggers early decomposition when retry_count
# reaches SPIRAL_DECOMPOSE_THRESHOLD (default 2) — before MAX_RETRIES is hit.
# Returns 0 if auto-decomposition was triggered (caller should `continue`),
# Returns 1 if threshold not met, disabled, or decomposition failed.
maybe_auto_decompose() {
  local story_id="$1" retry_now="$2" model="${3:-sonnet}"
  local threshold="${SPIRAL_DECOMPOSE_THRESHOLD:-2}"

  # Disabled when threshold is 0
  if [[ "$threshold" -eq 0 ]]; then
    return 1
  fi

  # Only trigger at threshold but before MAX_RETRIES (MAX_RETRIES has its own decompose path)
  if [[ "$retry_now" -lt "$threshold" || "$retry_now" -ge "$MAX_RETRIES" ]]; then
    return 1
  fi

  echo "  [auto-decompose] $story_id reached threshold $threshold after $retry_now attempt(s) — decomposing early"

  if decompose_story "$story_id" "$model"; then
    # Mark parent as auto-decomposed (not just timed out or quality-gate failed)
    $JQ "(.userStories[] | select(.id == \"$story_id\") | ._failureReason) = \"auto_decomposed\"" \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
    $JQ "(.userStories[] | select(.id == \"$story_id\") | ._skipped) = true" \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true

    # Read child IDs written by decompose_story and emit structured event
    local child_ids
    child_ids=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | ._decomposedInto // [] | join(\",\")" \
      "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo "")
    log_ralph_event "auto_decompose" \
      "\"storyId\":\"$story_id\",\"retryCount\":$retry_now,\"threshold\":$threshold,\"childIds\":\"$child_ids\""

    echo "AUTO-DECOMPOSED: $story_id at retry $retry_now (threshold $threshold) → $child_ids" >>"$PROGRESS_FILE"
    reset_retry "$story_id"
    return 0
  else
    echo "  [auto-decompose] decomposition failed for $story_id — continuing with normal retry"
    return 1
  fi
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

  # Pass failure reason + git root so decomposer can enrich sub-story technicalNotes
  local _fail_reason
  _fail_reason=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | ._failureReason // \"\"" "$PRD_FILE" 2>/dev/null | tr -d '\r' || true)
  local _git_root
  _git_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

  echo "  [decompose] Decomposing $story_id (failure: ${_fail_reason:-unknown})..."
  if "$python_cmd" "$decompose_script" \
    --prd "$PRD_FILE" \
    --story-id "$story_id" \
    --progress "$PROGRESS_FILE" \
    --git-root "$_git_root" \
    --failure-reason "${_fail_reason:-}" \
    --model "$model"; then
    echo "  [decompose] $story_id decomposed successfully"
    TOTAL_STORIES=$($JQ '[.userStories | length] | .[0]' "$PRD_FILE")
    return 0
  else
    echo "  [decompose] Failed to decompose $story_id -- will skip instead"
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
    printf 'timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit\tcache_read_tokens\treview_tokens\n' >"$RESULTS_FILE"
  fi
  local safe_title="${STORY_TITLE//$'\t'/ }"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$ts" "${SPIRAL_ITER:-0}" "$ITERATION" "$NEXT_STORY" "$safe_title" \
    "$status" "$duration_sec" "$model_col" "$RETRY_NOW" "$commit_sha" "${SPIRAL_RUN_ID:-}" \
    "${_CACHE_HIT:-false}" "${_CACHE_READ_TOKENS:-0}" "${_REVIEW_TOKENS:-0}" \
    >>"$RESULTS_FILE"
}

# ── GitHub PR creation (US-143) ─────────────────────────────────────────────
# create_github_pr <story_id> <story_title> <commit_sha>
# Pushes story commit to spiral/<story_id> branch and opens a GitHub PR.
# Stores the PR URL in prd.json as _prUrl.  Errors are non-fatal: if gh CLI
# is unavailable or unauthenticated the function emits an actionable message
# and returns 0 so the story is not failed.
create_github_pr() {
  local story_id="$1" story_title="$2" commit_sha="$3"
  local pr_base="${SPIRAL_PR_BASE_BRANCH:-main}"
  local pr_branch="spiral/${story_id}"
  local draft_flag=""
  [[ "${SPIRAL_PR_DRAFT:-false}" == "true" ]] && draft_flag="--draft"

  # Guard: gh CLI must be installed
  if ! command -v gh &>/dev/null; then
    echo "  [pr] SKIP: gh CLI not found. Install from https://cli.github.com to enable PR creation."
    return 0
  fi

  # Guard: gh must be authenticated
  if ! gh auth status &>/dev/null 2>&1; then
    echo "  [pr] SKIP: gh CLI is not authenticated. Run 'gh auth login' to enable PR creation."
    return 0
  fi

  # Push the story commit to the feature branch (force-update so idempotent on retry)
  echo "  [pr] Pushing $commit_sha to branch $pr_branch..."
  if ! git push origin "${commit_sha}:refs/heads/${pr_branch}" --force 2>&1; then
    echo "  [pr] WARNING: git push failed — skipping PR creation"
    return 0
  fi

  # Build PR body from prd.json: description + acceptance criteria + run metadata
  local story_desc
  story_desc=$($JQ -r --arg id "$story_id" \
    '.userStories[] | select(.id == $id) | .description // ""' "$PRD_FILE" 2>/dev/null || echo "")

  local ac_list
  ac_list=$($JQ -r --arg id "$story_id" \
    '.userStories[] | select(.id == $id) | .acceptanceCriteria // [] | .[] | "- [ ] \(.)"' \
    "$PRD_FILE" 2>/dev/null || echo "")

  local pr_body
  pr_body="## Story: ${story_id}

${story_desc}

## Acceptance Criteria

${ac_list}

---
*SPIRAL Run ID:* \`${SPIRAL_RUN_ID:-unknown}\`
*Commit:* \`${commit_sha}\`
*Generated by [SPIRAL](https://github.com/anthropics/spiral) autonomous dev loop*"

  # Auto-create 'spiral-ai' label if missing (best-effort, non-fatal)
  gh label create "spiral-ai" --color "0075ca" --description "SPIRAL AI-generated story" 2>/dev/null || true

  # Check if a PR already exists for this branch (idempotent)
  local existing_pr_url
  existing_pr_url=$(gh pr list --head "$pr_branch" --json url --jq '.[0].url' 2>/dev/null || echo "")
  if [[ -n "$existing_pr_url" ]]; then
    echo "  [pr] PR already exists: $existing_pr_url"
    $JQ --arg id "$story_id" --arg url "$existing_pr_url" \
      '(.userStories[] | select(.id == $id)) |= . + {"_prUrl": $url}' \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
    return 0
  fi

  # Create the PR
  local pr_url
  # shellcheck disable=SC2086
  pr_url=$(gh pr create \
    --base "$pr_base" \
    --head "$pr_branch" \
    --title "$story_title" \
    --body "$pr_body" \
    --label "spiral-ai" \
    $draft_flag \
    2>&1) || {
    echo "  [pr] WARNING: gh pr create failed: $pr_url"
    return 0
  }

  # gh pr create prints the URL on stdout
  pr_url=$(echo "$pr_url" | grep -E '^https?://' | head -1 || echo "")
  if [[ -n "$pr_url" ]]; then
    echo "  [pr] Created PR: $pr_url"
    $JQ --arg id "$story_id" --arg url "$pr_url" \
      '(.userStories[] | select(.id == $id)) |= . + {"_prUrl": $url}' \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
    log_ralph_event "pr_created" "\"storyId\":\"$story_id\",\"prUrl\":\"$pr_url\",\"branch\":\"$pr_branch\""
  else
    echo "  [pr] WARNING: PR created but URL not captured"
  fi
}

# ── Ollama API fallback (US-144) ─────────────────────────────────────────────
# call_ollama_fallback <system_prompt_file> <user_prompt_file>
# Calls Ollama via OpenAI-compatible API at SPIRAL_OLLAMA_HOST.
# Prints response text to stdout.
# Returns 0 on success, 1 on connection error (curl exit 7/28) or other failure.
call_ollama_fallback() {
  local sys_file="$1"
  local usr_file="$2"
  local model="${SPIRAL_OLLAMA_FALLBACK_MODEL}"
  local host="${SPIRAL_OLLAMA_HOST:-http://localhost:11434/v1}"

  echo "  [ollama] Calling Ollama model: $model at $host"

  # Build JSON payload using python3 for safe string escaping (avoids shell quoting issues)
  local payload
  payload=$(python3 -c "
import json, sys
system = open(sys.argv[1]).read()
user = open(sys.argv[2]).read()
model = sys.argv[3]
print(json.dumps({'model': model, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], 'stream': False, 'temperature': 0.1}))
" "$sys_file" "$usr_file" "$model" 2>/dev/null) || {
    echo "  [ollama] ERROR: failed to build JSON payload"
    return 1
  }

  # POST to Ollama OpenAI-compat endpoint; suppress curl progress, capture body only
  local response
  response=$(curl -sf \
    -X POST "${host}/chat/completions" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    --connect-timeout 10 \
    --max-time 300 \
    2>/dev/null)
  local curl_rc=$?

  if [[ "$curl_rc" -eq 7 ]]; then
    echo "  [ollama] ERROR: connection refused (curl exit 7) — is Ollama running at ${host}?"
    return 1
  elif [[ "$curl_rc" -eq 28 ]]; then
    echo "  [ollama] ERROR: connection timed out (curl exit 28)"
    return 1
  elif [[ "$curl_rc" -ne 0 ]]; then
    echo "  [ollama] ERROR: curl failed (exit $curl_rc)"
    return 1
  fi

  # Extract message content from OpenAI-compatible response
  local content
  content=$(echo "$response" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(data['choices'][0]['message']['content'])
" 2>/dev/null) || content="$response"

  printf '%s\n' "$content"
}

# ── Phase I.5: LLM self-review gate (US-145) ────────────────────────────────
# run_self_review <story_id>
# Sends story spec + git diff (≤500 lines) to Claude haiku for structured review.
# Sets _REVIEW_TOKENS (input+output) for results.tsv tracking.
# Returns 0 if no critical issues found; returns 1 if any critical issue found.
# On critical find, stores issues JSON in prd.json as _selfReviewIssues and sets
# _failureReason so the retry context injection surfaces them to the next agent.
_REVIEW_TOKENS=0
run_self_review() {
  local story_id="$1"
  _REVIEW_TOKENS=0

  # Collect git diff limited to 500 lines (working tree vs HEAD)
  local _diff
  _diff=$(git diff HEAD 2>/dev/null | head -500)
  if [[ -z "$_diff" ]]; then
    # Agent may have committed — try last commit diff
    _diff=$(git diff HEAD~1 HEAD 2>/dev/null | head -500)
  fi
  if [[ -z "$_diff" ]]; then
    echo "  [review] No diff to review — Phase I.5 skipped"
    return 0
  fi

  # Collect story spec from prd.json
  local _story_title _story_desc _story_ac
  _story_title=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .title // \"\"" "$PRD_FILE" 2>/dev/null | tr -d '\r')
  _story_desc=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .description // \"\"" "$PRD_FILE" 2>/dev/null | tr -d '\r')
  _story_ac=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .acceptanceCriteria // [] | .[] | \"- \" + ." "$PRD_FILE" 2>/dev/null | tr -d '\r' | head -20)

  # Cacheable system prompt (constant across stories — prompt-caching friendly)
  local _review_system
  _review_system='You are a senior code reviewer performing a pre-validation review. Given a story specification and a git diff, identify bugs, security issues, and spec deviations. Respond with ONLY a valid JSON object — no markdown, no explanation — matching exactly: {"issues":[{"severity":"critical|major|minor","location":"<file:line or description>","description":"<concise description of the issue>"}]}. Use severity "critical" only for bugs that will definitely cause test failures, security vulnerabilities, or hard spec violations. Use "major" for significant issues and "minor" for style/quality concerns. If there are no issues, respond with: {"issues":[]}'

  local _review_user
  _review_user="## Story Specification

Title: ${_story_title}
Description: ${_story_desc}

Acceptance Criteria:
${_story_ac:-  (none listed)}

## Git Diff (truncated to 500 lines)

\`\`\`diff
${_diff}
\`\`\`

Review the diff against the story specification above. Output ONLY the JSON object."

  # Call Claude haiku (single turn, stream-json to capture tokens + text)
  local _review_model="${SPIRAL_SELF_REVIEW_MODEL:-haiku}"
  local _review_tmp="${SPIRAL_SCRATCH_DIR:-/tmp}/_review_raw_$$.tmp"
  mkdir -p "${SPIRAL_SCRATCH_DIR:-/tmp}"

  echo "  [Phase I.5] Sending ${#_diff} chars of diff to ${_review_model} for self-review..."
  (
    unset CLAUDECODE
    claude -p "$_review_user" \
      --model "$_review_model" \
      --append-system-prompt "$_review_system" \
      --betas prompt-caching-2024-07-31 \
      --max-turns 1 \
      --output-format stream-json \
      --dangerously-skip-permissions \
      2>/dev/null
  ) >"$_review_tmp" 2>/dev/null || true

  # Extract token counts from stream-json result line
  if [[ -f "$_review_tmp" ]]; then
    local _rl
    _rl=$(grep -m1 '"type":"result"' "$_review_tmp" 2>/dev/null || true)
    if [[ -n "$_rl" ]]; then
      local _ri _ro
      _ri=$($JQ -r '.usage.input_tokens // 0' <<<"$_rl" 2>/dev/null || echo 0)
      _ro=$($JQ -r '.usage.output_tokens // 0' <<<"$_rl" 2>/dev/null || echo 0)
      [[ "$_ri" =~ ^[0-9]+$ ]] && [[ "$_ro" =~ ^[0-9]+$ ]] && _REVIEW_TOKENS=$((_ri + _ro)) || _REVIEW_TOKENS=0
    fi
  fi

  # Extract assistant text: stream-json result line has a .result field with the text
  local _review_text
  _review_text=""
  if [[ -f "$_review_tmp" ]]; then
    local _rl2
    _rl2=$(grep -m1 '"type":"result"' "$_review_tmp" 2>/dev/null || true)
    if [[ -n "$_rl2" ]]; then
      _review_text=$($JQ -r '.result // ""' <<<"$_rl2" 2>/dev/null | tr -d '\r' || true)
    fi
  fi
  rm -f "$_review_tmp"

  # Strip markdown code fences if present
  _review_text=$(printf '%s' "$_review_text" | sed 's/^```json[[:space:]]*//' | sed 's/^```[[:space:]]*//' | sed 's/```[[:space:]]*$//' | tr -d '\r')

  # Validate JSON and count issues
  local _critical_count=0 _total_count=0
  if [[ -n "$_review_text" ]] && echo "$_review_text" | $JQ empty 2>/dev/null; then
    _critical_count=$(echo "$_review_text" | $JQ '[.issues[] | select(.severity == "critical")] | length' 2>/dev/null || echo 0)
    _total_count=$(echo "$_review_text" | $JQ '.issues | length' 2>/dev/null || echo 0)
    [[ "$_critical_count" =~ ^[0-9]+$ ]] || _critical_count=0
    [[ "$_total_count" =~ ^[0-9]+$ ]] || _total_count=0
  else
    echo "  [Phase I.5] WARNING: review response was not valid JSON — treating as no issues"
    echo "  [Phase I.5] Raw response (first 200 chars): ${_review_text:0:200}"
    _REVIEW_TOKENS=0
    return 0
  fi

  echo "  [Phase I.5] Review complete: ${_total_count} issue(s) (${_critical_count} critical) | tokens: ${_REVIEW_TOKENS}"
  log_spiral_event "self_review" \
    "\"story_id\":\"$story_id\",\"critical\":${_critical_count},\"total\":${_total_count},\"review_tokens\":${_REVIEW_TOKENS}"

  if [[ "$_critical_count" -gt 0 ]]; then
    echo "  [Phase I.5] Critical issues found — re-entering Phase I:"
    echo "$_review_text" | $JQ -r '.issues[] | select(.severity == "critical") | "    - [\(.severity)] \(.location): \(.description)"' 2>/dev/null || true

    # Store full issue list in prd.json as _selfReviewIssues
    local _issues_json
    _issues_json=$(echo "$_review_text" | $JQ -c '.issues // []' 2>/dev/null || echo '[]')
    $JQ --argjson issues "$_issues_json" \
      "(.userStories[] | select(.id == \"$story_id\") | ._selfReviewIssues) = \$issues" \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true

    return 1
  fi

  return 0
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
    printf '{"type":"%s","ts":"%s","story_id":"%s","run_id":"%s",%s}\n' \
      "$event_type" "$ts" "${NEXT_STORY:-}" "${SPIRAL_RUN_ID:-}" "$extra_json" >>"$events_file"
  else
    printf '{"type":"%s","ts":"%s","story_id":"%s","run_id":"%s"}\n' \
      "$event_type" "$ts" "${NEXT_STORY:-}" "${SPIRAL_RUN_ID:-}" >>"$events_file"
  fi
}

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
# retry 0: keep base; retry 1: +1 tier; retry 2+: opus
escalate_model_by_retry() {
  local base_model="$1" retry_count="$2"

  if [[ "$retry_count" -le 0 ]]; then
    echo "$base_model"
  elif [[ "$retry_count" -eq 1 ]]; then
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

# Resolve the effective model: prd.json annotation > CLI override > auto-classify+escalate
resolve_model() {
  local story_id="$1" retry_count="$2" escalation_count="$3"

  # Per-story .model annotation in prd.json overrides everything (including --model flag)
  local prd_model
  prd_model=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .model // empty" "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo '')
  if [[ -n "$prd_model" ]]; then
    local escalated_model
    escalated_model=$(escalate_model_by_retry "$prd_model" "$retry_count")
    escalate_model_by_quality_failure "$escalated_model" "$escalation_count"
    return
  fi

  # CLI --model wins next
  if [[ -n "$RALPH_MODEL" ]]; then
    local escalated
    escalated=$(escalate_model_by_retry "$RALPH_MODEL" "$retry_count")
    escalate_model_by_quality_failure "$escalated" "$escalation_count"
    echo "$escalated"
    return
  fi

  # Auto-classify from story metadata + escalate on retry
  local base_model
  base_model=$(classify_model "$story_id")
  local escalated_model
  escalated_model=$(escalate_model_by_retry "$base_model" "$retry_count")
  escalate_model_by_quality_failure "$escalated_model" "$escalation_count"
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
SPIRAL_STATUS_INTERVAL="${SPIRAL_STATUS_INTERVAL:-1800}" # default 30 min (1800s)
LAST_STATUS_TIME=$(date +%s)

periodic_status_report() {
  local now=$(date +%s)
  local elapsed=$((now - LAST_STATUS_TIME))
  if [[ "$elapsed" -lt "$SPIRAL_STATUS_INTERVAL" ]]; then
    return
  fi
  LAST_STATUS_TIME=$now

  local total_elapsed=$(((now - START_TIME) / 60))
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

# Returns incomplete (passes==false, not decomposed) story IDs sorted by priority.
# Switches to jq --stream when prd.json exceeds SPIRAL_PRD_STREAM_THRESHOLD_KB (default 512 KB)
# to avoid loading the entire document into memory for large PRDs.
# Both paths produce identical output.
get_pending_story_ids() {
  local prd_file="${1:-$PRD_FILE}"
  local threshold_kb="${SPIRAL_PRD_STREAM_THRESHOLD_KB:-512}"
  local file_kb
  file_kb=$(( $(wc -c < "$prd_file") / 1024 ))

  if [[ "$threshold_kb" -gt 0 && "$file_kb" -ge "$threshold_kb" ]]; then
    # Streaming path: reconstruct individual userStories objects using fromstream,
    # then filter and sort in a second pass to avoid full document parse.
    $JQ -rn --stream \
      'fromstream(1|truncate_stream(inputs|select(.[0][0]=="userStories")))
       | select(.passes == false and (._decomposed | not))
       | [.priority // "zzz", .id]
       | @tsv' "$prd_file" \
      | sort \
      | cut -f2 \
      | tr -d '\r'
  else
    # Normal path: full in-memory parse (default for prd.json files under threshold)
    $JQ -r '[.userStories[] | select(.passes == false and (._decomposed | not))]
             | sort_by(.priority)
             | .[].id' "$prd_file" \
      | tr -d '\r'
  fi
}

# ── Main loop ────────────────────────────────────────────────────
ITERATION=0
STORIES_COMPLETED=$COMPLETE_STORIES
STORIES_SKIPPED=0
START_TIME=$(date +%s)
# Ollama fallback: consecutive Claude API connection failure counter (US-144)
_CLAUDE_API_FAIL_STREAK=0

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
  ALL_INCOMPLETE=$(get_pending_story_ids "$PRD_FILE")

  for candidate in $ALL_INCOMPLETE; do
    # ── Manual skip filter: skip stories in SPIRAL_SKIP_STORY_IDS without penalty ──
    if [[ -n "${SPIRAL_SKIP_STORY_IDS:-}" ]]; then
      _MANUAL_SKIP=0
      IFS=',' read -ra _SKIP_IDS <<<"$SPIRAL_SKIP_STORY_IDS"
      for _sid in "${_SKIP_IDS[@]}"; do
        _sid=$(echo "$_sid" | tr -d ' \r')
        if [[ "$candidate" == "$_sid" ]]; then
          _MANUAL_SKIP=1
          break
        fi
      done
      if [[ "$_MANUAL_SKIP" -eq 1 ]]; then
        continue # manual skip — no retry increment
      fi
    fi
    retries=$(get_retry_count "$candidate")
    if [[ "$retries" -ge "$MAX_RETRIES" ]]; then
      continue
    fi
    # ── Focus-tags filter: skip stories that don't match any requested tag ──
    if [[ -n "${SPIRAL_FOCUS_TAGS:-}" ]]; then
      _STORY_TAGS=$($JQ -r ".userStories[] | select(.id == \"$candidate\") | .tags // [] | join(\",\")" "$PRD_FILE" | tr -d '\r')
      _TAG_MATCH=0
      IFS=',' read -ra _WANTED_TAGS <<<"$SPIRAL_FOCUS_TAGS"
      for _wt in "${_WANTED_TAGS[@]}"; do
        if [[ ",$_STORY_TAGS," == *",$_wt,"* ]]; then
          _TAG_MATCH=1
          break
        fi
      done
      if [[ "$_TAG_MATCH" -eq 0 ]]; then
        continue # skip — no matching tag (not failed, not retry-counted)
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
          NEXT_STORY="$sid"
          STORY_TITLE="$stitle"
          RETRY_NOW="$retries"
          STORY_START=$(date +%s)
          STORY_END=$STORY_START
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
  STORY_TAGS=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .tags // [] | join(\",\")" "$PRD_FILE" | tr -d '\r')
  STORY_FIRST_FILE=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .filesTouch // [] | first // empty" "$PRD_FILE" | tr -d '\r')
  RETRY_NOW=$(get_retry_count "$NEXT_STORY")

  # ── Stamp last_attempted timestamp on the story (US-129: stale detection) ──
  _NOW_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .last_attempted) = \"$_NOW_ISO\"" \
    "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true

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
  [[ -n "$EFFECTIVE_MODEL" ]] &&
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

  # Capture test baseline BEFORE Claude makes any changes
  echo -n "  [baseline] Counting pre-story passing tests... "
  PRE_STORY_TESTS_PASSING=$(capture_test_baseline)
  if [[ "$PRE_STORY_TESTS_PASSING" == "-1" ]]; then
    echo "unknown (no test runner detected)"
  else
    echo "$PRE_STORY_TESTS_PASSING passing"
  fi

  # Capture git baseline SHA for Karpathy ratchet (reset on failure)
  PRE_STORY_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")

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
  _OLLAMA_USED=0      # reset per-story; set to 1 if Ollama fallback fires (US-144)
  _REVIEW_TOKENS=0    # reset per-story; set by run_self_review Phase I.5 (US-145)
  echo ""
  echo "  [spawn] Fresh $EFFECTIVE_TOOL instance for $NEXT_STORY..."

  # ── Gemini pre-context (paid tier, deep reasoning, saves 20+ claude turns) ──
  STORY_JSON=$($JQ -c ".userStories[] | select(.id == \"$NEXT_STORY\")" "$PRD_FILE" 2>/dev/null || echo "{}")

  # ── Context truncation gate (US-141) ─────────────────────────────────────
  # Measure story token count before spawning AI; strip over-budget fields.
  _TRUNCATE_PY="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)/lib/truncate_context.py"
  if [[ -f "$_TRUNCATE_PY" ]] && command -v python3 &>/dev/null &&
    [[ -n "$STORY_JSON" && "$STORY_JSON" != "{}" ]]; then
    _TRUNC_WARN=$(echo "$STORY_JSON" |
      python3 "$_TRUNCATE_PY" --base-prompt-file "$PROMPT_FILE" \
        --attempt "${RETRY_NOW:-0}" \
        2>&1 1>/dev/null)
    _TRUNC_JSON=$(echo "$STORY_JSON" |
      python3 "$_TRUNCATE_PY" --base-prompt-file "$PROMPT_FILE" \
        --attempt "${RETRY_NOW:-0}" \
        2>/dev/null)
    if [[ -n "$_TRUNC_WARN" ]]; then
      echo "  [context] WARNING: $(echo "$_TRUNC_WARN" | python3 -c \
        "import sys,json; d=json.load(sys.stdin); \
         print(f\"context truncated for {d.get('story_id','?')}: \
{d.get('original_tokens','?')} → {d.get('truncated_tokens','?')} tokens \
(dropped: {', '.join(d.get('dropped_fields',[]))})\") " 2>/dev/null || echo "$_TRUNC_WARN")"
      {
        echo ""
        echo "## Context Truncation Warning — $NEXT_STORY"
        echo "$_TRUNC_WARN"
        echo ""
      } >>"$PROGRESS_FILE"
    fi
  fi

  # ── Fast-path: skip Gemini pre-analysis for small stories (US-171) ─────────
  # Saves 10-30s per story with no quality loss for trivially small stories.
  # Override: SPIRAL_GEMINI_SKIP_SMALL=false to disable; does not apply when
  # SPIRAL_GEMINI_ANNOTATE_PROMPT is set (explicit annotation requested).
  _GEMINI_FAST_SKIP=0
  if [[ "${SPIRAL_GEMINI_SKIP_SMALL:-true}" != "false" && \
        -z "${SPIRAL_GEMINI_ANNOTATE_PROMPT:-}" && \
        -n "$STORY_JSON" && "$STORY_JSON" != "{}" ]]; then
    _FP_COMPLEXITY=$($JQ -r '.estimatedComplexity // ""' <<<"$STORY_JSON" 2>/dev/null || echo "")
    _FP_FILES_COUNT=$($JQ '(.filesTouch // []) | length' <<<"$STORY_JSON" 2>/dev/null || echo "99")
    if [[ "$_FP_COMPLEXITY" == "small" && "$_FP_FILES_COUNT" -le 2 ]]; then
      echo "  [precontext] skipped -- small story with <= 2 file hints"
      _GEMINI_FAST_SKIP=1
    fi
  fi

  if [[ "$_GEMINI_FAST_SKIP" -eq 0 ]] && command -v gemini &>/dev/null && [[ -n "$STORY_JSON" && "$STORY_JSON" != "{}" ]]; then
    _GEMINI_CACHE_DIR="${SPIRAL_SCRATCH_DIR}/gemini-cache"
    _GEMINI_CACHE_FILE="$_GEMINI_CACHE_DIR/${NEXT_STORY}.json"
    PRECONTEXT=""
    _CACHE_HIT=0

    # ── Cache hit check ────────────────────────────────────────────────────
    if [[ -f "$_GEMINI_CACHE_FILE" ]]; then
      _CACHED_RUN_ID=$($JQ -r '.run_id // ""' "$_GEMINI_CACHE_FILE" 2>/dev/null || echo "")
      if [[ -n "${SPIRAL_RUN_ID:-}" && "$_CACHED_RUN_ID" == "$SPIRAL_RUN_ID" ]]; then
        PRECONTEXT=$($JQ -r '.content // ""' "$_GEMINI_CACHE_FILE" 2>/dev/null || true)
        if [[ -n "$PRECONTEXT" ]]; then
          echo "  [precontext] Gemini cache hit for $NEXT_STORY"
          _CACHE_HIT=1
        fi
      fi
    fi

    # ── Cache miss: call Gemini and write cache ────────────────────────────
    if [[ "$_CACHE_HIT" -eq 0 ]]; then
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
      if [[ -n "$PRECONTEXT" && -n "${SPIRAL_RUN_ID:-}" ]]; then
        mkdir -p "$_GEMINI_CACHE_DIR"
        $JQ -n \
          --arg run_id "$SPIRAL_RUN_ID" \
          --arg story_id "$NEXT_STORY" \
          --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
          --arg content "$PRECONTEXT" \
          '{run_id: $run_id, story_id: $story_id, timestamp: $timestamp, content: $content}' \
          >"$_GEMINI_CACHE_FILE"
      fi
    fi

    if [[ -n "$PRECONTEXT" ]]; then
      {
        echo ""
        echo "## Pre-analysis for $NEXT_STORY (Gemini 2.5 Pro)"
        echo "$PRECONTEXT"
        echo ""
      } >>"$PROGRESS_FILE"
      echo "  [precontext] Gemini pre-analysis injected ($(echo "$PRECONTEXT" | wc -l) lines)"
    else
      echo "  [precontext] Gemini returned empty — skipping injection"
    fi
  fi

  # ── Circuit breaker check with model fallback chain ─────────────────────
  _CB_ENDPOINT="${EFFECTIVE_MODEL:-${EFFECTIVE_TOOL:-default}}"
  _FALLBACK_USED=""
  _ALL_MODELS_OPEN=0
  if declare -f cb_check >/dev/null 2>&1; then
    if ! cb_check "$_CB_ENDPOINT"; then
      echo "  [cb] Circuit breaker OPEN for $_CB_ENDPOINT — checking fallback chain"
      # Try fallback models from SPIRAL_MODEL_FALLBACK_CHAIN
      if [[ -n "$SPIRAL_MODEL_FALLBACK_CHAIN" && "$EFFECTIVE_TOOL" == "claude" ]]; then
        _PRIMARY_MODEL="$_CB_ENDPOINT"
        IFS=':' read -ra _FALLBACK_MODELS <<<"$SPIRAL_MODEL_FALLBACK_CHAIN"
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
            "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
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
    echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
    echo "DEFERRED: $STORY_TITLE ($NEXT_STORY) — all models in fallback chain unavailable" >>"$PROGRESS_FILE"
    echo "" >>"$PROGRESS_FILE"
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
      # Build prompt content — split into system prompt (cacheable) and user prompt (minimal)
      # The system prompt is stable across story iterations so Anthropic prompt caching
      # (cache_control: {type: ephemeral}) can cache it, saving ~90% input token cost.
      RALPH_SYSTEM_PROMPT="$(cat "$PROMPT_FILE")"
      SPECKIT_CONST=".specify/memory/constitution.md"
      if [[ -f "$SPECKIT_CONST" ]]; then
        RALPH_SYSTEM_PROMPT="$RALPH_SYSTEM_PROMPT

---

## Project Constitution (Spec-Kit — non-negotiable standards)

$(cat "$SPECKIT_CONST")
"
        echo "  [speckit] Constitution loaded ($(wc -l <"$SPECKIT_CONST") lines)"
      fi
      if [[ -n "$RALPH_FOCUS" ]]; then
        RALPH_SYSTEM_PROMPT="$RALPH_SYSTEM_PROMPT

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
        RALPH_SYSTEM_PROMPT="$RALPH_SYSTEM_PROMPT

---

## Browser Tools

$BROWSER_TOOLS_HINT"
        echo "  [browser] Chrome DevTools MCP detected — visual verification enabled"
      fi
      # Minimal user prompt — the system prompt has all instructions
      RALPH_USER_PROMPT="Implement the next incomplete story from prd.json now. Read prd.json and progress.txt, pick the highest priority story where passes is false, and implement it."

      # ── Retry context injection ───────────────────────────────────────────────
      # On attempt 2+, prepend a concise brief so the agent doesn't need to hunt
      # through progress.txt to find what the previous attempt learned.
      if [[ "${RETRY_NOW:-0}" -ge 1 ]]; then
        _PREV_ATTEMPT=$((RETRY_NOW))
        _FAIL_REASON=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason // \"(not recorded)\"" "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo "(not recorded)")
        # Extract the last progress.txt section(s) mentioning this story
        _RETRY_NOTES=""
        if [[ -f "$PROGRESS_FILE" ]]; then
          # Grab up to 40 lines from the end of progress.txt that mention the story
          _RETRY_NOTES=$(grep -A 8 -B 2 "$NEXT_STORY" "$PROGRESS_FILE" 2>/dev/null | tail -40 || true)
        fi
        _RETRY_BRIEF="RETRY CONTEXT — ATTEMPT $((RETRY_NOW + 1)) of $MAX_RETRIES

Story $NEXT_STORY (\"$STORY_TITLE\") was attempted $RETRY_NOW time(s) and did NOT pass.
Failure reason: $_FAIL_REASON

Notes from the previous attempt (from progress.txt):
${_RETRY_NOTES:-  (none found — check progress.txt manually)}

ACTION: Do NOT repeat the same approach that failed. Read progress.txt carefully for what
was tried, then implement the story differently. You are using a more powerful model this
attempt ($EFFECTIVE_MODEL) — use it."
        RALPH_USER_PROMPT="$_RETRY_BRIEF

---

$RALPH_USER_PROMPT"
        echo "  [retry] Attempt $((RETRY_NOW + 1))/$MAX_RETRIES — injected failure context ($RETRY_NOW prior attempt(s), reason: ${_FAIL_REASON:0:60})"
      fi

      echo "  [cache] System prompt: $(echo "$RALPH_SYSTEM_PROMPT" | wc -c) bytes (cacheable via prompt-caching beta)"
      # Unset CLAUDECODE to allow nested Claude Code invocation from within an active session
      # Wrap with 529 overloaded_error retry loop (separate from 429 rate-limit handling)
      _529_ATTEMPT=0
      _529_MAX=5
      _529_BASE=2
      _529_CAP=30
      while true; do
        _CLAUDE_TMP="${SPIRAL_SCRATCH_DIR}/_claude_raw_$$.tmp"
        mkdir -p "${SPIRAL_SCRATCH_DIR}"
        (
          unset CLAUDECODE
          claude -p "$RALPH_USER_PROMPT" \
            $CLAUDE_MODEL_FLAG \
            --append-system-prompt "$RALPH_SYSTEM_PROMPT" \
            --betas prompt-caching-2024-07-31 \
            --allowedTools "Edit,Write,Read,Glob,Grep,Bash,Skill,Task" \
            --max-turns 75 \
            --verbose \
            --output-format stream-json \
            --dangerously-skip-permissions \
            2>&1 | tee "$_CLAUDE_TMP" | node "$SCRIPT_DIR/stream-formatter.mjs"
        ) || true
        # ── Connection failure detection for Ollama fallback (US-144) ──────────────
        # Detect curl exit 7 (ECONNREFUSED) / exit 28 (ETIMEDOUT) patterns in output.
        # Empty output or connection-refused messages indicate Claude API is unreachable.
        # After _CLAUDE_API_FAIL_STREAK >= 3, switch to Ollama for the current story.
        if [[ -n "${SPIRAL_OLLAMA_FALLBACK_MODEL:-}" ]]; then
          _TMP_SIZE=0
          [[ -f "$_CLAUDE_TMP" ]] && _TMP_SIZE=$(wc -c < "$_CLAUDE_TMP" 2>/dev/null || echo 0)
          _IS_CONN_FAIL=0
          if [[ "${_TMP_SIZE:-0}" -eq 0 ]]; then
            _IS_CONN_FAIL=1
          elif grep -qiE 'ECONNREFUSED|ETIMEDOUT|connection refused|failed to connect|could not resolve host' \
              "$_CLAUDE_TMP" 2>/dev/null; then
            _IS_CONN_FAIL=1
          fi
          if [[ "$_IS_CONN_FAIL" -eq 1 ]]; then
            _CLAUDE_API_FAIL_STREAK=$((_CLAUDE_API_FAIL_STREAK + 1))
            rm -f "$_CLAUDE_TMP"
            echo "  [ollama] Claude API unreachable (streak: $_CLAUDE_API_FAIL_STREAK/3)"
            log_spiral_event "claude_api_unreachable" \
              "\"story_id\":\"${NEXT_STORY:-}\",\"streak\":${_CLAUDE_API_FAIL_STREAK}"
            if [[ "$_CLAUDE_API_FAIL_STREAK" -ge 3 ]]; then
              echo "  [ollama] Streak >= 3 — switching to Ollama for ${NEXT_STORY:-}"
              mkdir -p "${SPIRAL_SCRATCH_DIR}"
              _OLLAMA_SYS_TMP="${SPIRAL_SCRATCH_DIR}/_ollama_sys_$$.tmp"
              _OLLAMA_USR_TMP="${SPIRAL_SCRATCH_DIR}/_ollama_usr_$$.tmp"
              printf '%s' "$RALPH_SYSTEM_PROMPT" > "$_OLLAMA_SYS_TMP"
              printf '%s' "$RALPH_USER_PROMPT" > "$_OLLAMA_USR_TMP"
              echo "  ─────── Ollama Output Start ───────"
              if call_ollama_fallback "$_OLLAMA_SYS_TMP" "$_OLLAMA_USR_TMP" | tee "$_RL_TMP"; then
                _OLLAMA_USED=1
                _CLAUDE_API_FAIL_STREAK=0
                echo "  [ollama] Ollama fallback succeeded"
              else
                _OLLAMA_USED=0
                > "$_RL_TMP"
                echo "  [ollama] Ollama fallback also failed — story will be retried later"
              fi
              echo "  ─────── Ollama Output End ─────────"
              rm -f "$_OLLAMA_SYS_TMP" "$_OLLAMA_USR_TMP"
            fi
            break  # exit _529_ATTEMPT loop — no benefit retrying a connection failure
          else
            # Successful connection — reset fail streak
            _CLAUDE_API_FAIL_STREAK=0
          fi
        fi
        # Detect HTTP 529 overloaded_error — separate handler from 429 rate-limit
        # Also detect streaming errors returned with HTTP 200: Claude CLI may emit
        # {"type":"error","error":{"type":"overloaded_error","message":"..."}} as the
        # first NDJSON chunk while the HTTP status is 200, so exit code does not signal failure.
        _FIRST_LINE=$(head -1 "$_CLAUDE_TMP" 2>/dev/null || true)
        if grep -qE 'overloaded_error|"529"' "$_CLAUDE_TMP" 2>/dev/null ||
          echo "$_FIRST_LINE" | grep -qF '"type":"error"' 2>/dev/null; then
          _529_ATTEMPT=$((_529_ATTEMPT + 1))
          rm -f "$_CLAUDE_TMP"
          if [[ "$_529_ATTEMPT" -gt "$_529_MAX" ]]; then
            echo "  [529] Max overload retries ($_529_MAX) reached — proceeding to story outcome check"
            break
          fi
          _delay=$((_529_BASE * (2 ** (_529_ATTEMPT - 1))))
          [[ "$_delay" -gt "$_529_CAP" ]] && _delay="$_529_CAP"
          _jitter=$(((_delay * 10) / 100 + 1))
          _sleep=$((_delay + RANDOM % _jitter))
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
      if declare -f cb_record_failure >/dev/null 2>&1; then
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
    if declare -f cb_record_success >/dev/null 2>&1; then
      cb_record_success "$_CB_ENDPOINT"
    fi

    # ── Parse token counts from LLM output (before cleanup) ─────────────────
    _CALL_TOKENS_INPUT=0
    _CALL_TOKENS_OUTPUT=0
    _CACHE_CREATION_TOKENS=0
    _CACHE_READ_TOKENS=0
    _CACHE_HIT=false
    if [[ "$EFFECTIVE_TOOL" == "claude" && -f "$_RL_TMP" ]]; then
      _RESULT_LINE=$(grep -m1 '"type":"result"' "$_RL_TMP" 2>/dev/null || true)
      if [[ -n "$_RESULT_LINE" ]]; then
        _ti=$($JQ -r '.usage.input_tokens // 0' <<<"$_RESULT_LINE" 2>/dev/null || echo 0)
        _to=$($JQ -r '.usage.output_tokens // 0' <<<"$_RESULT_LINE" 2>/dev/null || echo 0)
        [[ "$_ti" =~ ^[0-9]+$ ]] && _CALL_TOKENS_INPUT=$_ti
        [[ "$_to" =~ ^[0-9]+$ ]] && _CALL_TOKENS_OUTPUT=$_to
        # Extract prompt caching fields from usage (present when prompt-caching beta is active)
        _cc=$($JQ -r '.usage.cache_creation_input_tokens // 0' <<<"$_RESULT_LINE" 2>/dev/null || echo 0)
        _cr=$($JQ -r '.usage.cache_read_input_tokens // 0' <<<"$_RESULT_LINE" 2>/dev/null || echo 0)
        [[ "$_cc" =~ ^[0-9]+$ ]] && _CACHE_CREATION_TOKENS=$_cc
        [[ "$_cr" =~ ^[0-9]+$ ]] && _CACHE_READ_TOKENS=$_cr
        [[ "$_CACHE_READ_TOKENS" -gt 0 ]] && _CACHE_HIT=true
        if [[ "$_CACHE_CREATION_TOKENS" -gt 0 || "$_CACHE_READ_TOKENS" -gt 0 ]]; then
          echo "  [cache] creation=${_CACHE_CREATION_TOKENS} read=${_CACHE_READ_TOKENS} hit=${_CACHE_HIT}"
          log_spiral_event "prompt_cache" \
            "\"cache_creation_tokens\":${_CACHE_CREATION_TOKENS},\"cache_read_tokens\":${_CACHE_READ_TOKENS},\"cache_hit\":${_CACHE_HIT}"
        fi
      fi
    fi

    rm -f "$_RL_TMP"
    break
  done # end rate-limit retry loop

  # ── Accumulate per-story token cost ───────────────────────────────────────
  _STORY_CUMULATIVE_USD=0
  if [[ "$_CALL_TOKENS_INPUT" -gt 0 || "$_CALL_TOKENS_OUTPUT" -gt 0 ]]; then
    _STORY_CUMULATIVE_USD=$(accumulate_story_cost "$NEXT_STORY" "$_CALL_TOKENS_INPUT" "$_CALL_TOKENS_OUTPUT" "$_CACHE_CREATION_TOKENS" "$_CACHE_READ_TOKENS" 2>/dev/null || echo 0)
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
    $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason) = \"story_cost_ceiling\"" "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
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
  STORY_DURATION=$(((STORY_END - STORY_START) / 60))
  echo "  [time] Story took ${STORY_DURATION}m"

  # ── Cost ceiling: abandon story if hard limit exceeded ────────────────────
  if [[ "$_STORY_COST_ABANDON" -eq 1 ]]; then
    $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" >"${PRD_FILE}.tmp"
    mv "${PRD_FILE}.tmp" "$PRD_FILE"
    increment_retry "$NEXT_STORY"
    RETRY_NOW=$(get_retry_count "$NEXT_STORY")
    append_result "reject"
    echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
    echo "COST CEILING: $STORY_TITLE ($NEXT_STORY) — \$${_STORY_CUMULATIVE_USD} exceeded hard limit \$${SPIRAL_STORY_COST_HARD_USD}" >>"$PROGRESS_FILE"
    echo "" >>"$PROGRESS_FILE"
    continue
  fi

  # ── Time budget enforcement ──────────────────────────────────
  # If a story exceeds its time budget it is treated as "too large" and decomposed
  # immediately on the FIRST timeout rather than wasting 3 × budget retrying it.
  # Override behaviour: set SPIRAL_DECOMPOSE_ON_TIMEOUT=0 to use old retry-first logic.
  SPIRAL_DECOMPOSE_ON_TIMEOUT="${SPIRAL_DECOMPOSE_ON_TIMEOUT:-1}"
  if [[ "$STORY_TIME_BUDGET" -gt 0 ]]; then
    STORY_DURATION_SEC=$((STORY_END - STORY_START))
    if [[ "$STORY_DURATION_SEC" -gt "$STORY_TIME_BUDGET" ]]; then
      BUDGET_MIN=$((STORY_TIME_BUDGET / 60))
      DURATION_MIN=$((STORY_DURATION_SEC / 60))
      echo "  [time] Story exceeded ${BUDGET_MIN}min budget (took ${DURATION_MIN}min) — story is too large"
      $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" >"${PRD_FILE}.tmp"
      mv "${PRD_FILE}.tmp" "$PRD_FILE"
      increment_retry "$NEXT_STORY"
      RETRY_NOW=$(get_retry_count "$NEXT_STORY")
      STORY_TITLE=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .title" "$PRD_FILE" | tr -d '\r')
      append_result "reject"
      echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
      echo "TIME BUDGET EXCEEDED: $STORY_TITLE ($NEXT_STORY) — ${STORY_DURATION_SEC}s > ${STORY_TIME_BUDGET}s budget" >>"$PROGRESS_FILE"
      FAILURE_REASON="TIME_BUDGET_EXCEEDED (${STORY_DURATION_SEC}s > ${STORY_TIME_BUDGET}s limit)"
      $JQ --arg reason "$FAILURE_REASON" \
        '(.userStories[] | select(.id == "'"$NEXT_STORY"'") | ._failureReason) = $reason' \
        "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
      # Decompose on first timeout (SPIRAL_DECOMPOSE_ON_TIMEOUT=1, the default):
      # A story that blows the time budget once is a signal it is too large — trying
      # it 3 more times just wastes 3× budget.  Decompose immediately; only fall
      # back to retrying if decomposition itself fails.
      if [[ "$SPIRAL_DECOMPOSE_ON_TIMEOUT" != "0" ]]; then
        if decompose_story "$NEXT_STORY" "${EFFECTIVE_MODEL:-sonnet}"; then
          echo "DECOMPOSED: $NEXT_STORY (exceeded ${BUDGET_MIN}min budget) — sub-stories created" >>"$PROGRESS_FILE"
          echo "  [decompose] $NEXT_STORY decomposed on first timeout (${DURATION_MIN}min > ${BUDGET_MIN}min)"
          reset_retry "$NEXT_STORY"
        else
          # Decomposition failed — keep retrying until MAX_RETRIES then skip
          if [[ "$RETRY_NOW" -ge "$MAX_RETRIES" ]]; then
            echo "SKIPPED: $NEXT_STORY — decomposition failed and exhausted $MAX_RETRIES retries" >>"$PROGRESS_FILE"
            echo "  [skip] $NEXT_STORY skipped after $MAX_RETRIES attempts (decompose unavailable)"
          else
            echo "  [decompose] decompose_story unavailable — will retry ($RETRY_NOW/$MAX_RETRIES)"
          fi
        fi
      else
        # Old behaviour: decompose only after MAX_RETRIES failures
        if [[ "$RETRY_NOW" -ge "$MAX_RETRIES" ]]; then
          if decompose_story "$NEXT_STORY" "${EFFECTIVE_MODEL:-sonnet}"; then
            echo "DECOMPOSED: $NEXT_STORY after $MAX_RETRIES failed attempts — sub-stories created" >>"$PROGRESS_FILE"
          else
            echo "SKIPPED: $NEXT_STORY after $MAX_RETRIES failed attempts" >>"$PROGRESS_FILE"
            echo "  [skip] $NEXT_STORY skipped after $MAX_RETRIES attempts — moving on"
          fi
        fi
      fi
      echo "" >>"$PROGRESS_FILE"
      continue
    fi
  fi

  # Check if story was completed
  PASSES=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .passes" "$PRD_FILE" | tr -d '\r')

  if [[ "$PASSES" == "true" ]]; then
    STORIES_COMPLETED=$((STORIES_COMPLETED + 1))
    echo ""
    echo "  [done] Story completed: $STORY_TITLE"

    # ── Phase I.5 (REVIEW): LLM self-review gate (US-145) ──────────────────
    # Send story spec + git diff to Claude haiku for structured code review.
    # Skip when SPIRAL_SKIP_SELF_REVIEW=true or when retries exceed MAX_RETRIES/2
    # (to avoid burning tokens on stories already deep in retry chain).
    if [[ "${SPIRAL_SKIP_SELF_REVIEW:-false}" != "true" ]]; then
      _REVIEW_SKIP_THRESHOLD=$(( MAX_RETRIES / 2 ))
      if [[ "$RETRY_NOW" -le "$_REVIEW_SKIP_THRESHOLD" ]]; then
        if ! run_self_review "$NEXT_STORY"; then
          # Critical issues found — re-queue for Phase I with issue list injected
          $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" \
            "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
          # Build human-readable failure reason for retry context injection
          _REVIEW_CRITICAL_TEXT=$($JQ -r \
            ".userStories[] | select(.id == \"$NEXT_STORY\") | ._selfReviewIssues // [] | .[] | select(.severity == \"critical\") | \"  - [\" + .severity + \"] \" + .location + \": \" + .description" \
            "$PRD_FILE" 2>/dev/null || echo "  (see Phase I.5 output above)")
          _REVIEW_FAIL_REASON="SELF_REVIEW_CRITICAL: Phase I.5 found critical issue(s) that must be fixed:
${_REVIEW_CRITICAL_TEXT}
ACTION: Fix the critical issues listed above before marking passes=true."
          $JQ --arg reason "$_REVIEW_FAIL_REASON" \
            "(.userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason) = \$reason" \
            "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
          increment_retry "$NEXT_STORY"
          RETRY_NOW=$(get_retry_count "$NEXT_STORY")
          echo "  [Phase I.5] Re-entering Phase I (retry $RETRY_NOW/$MAX_RETRIES)"
          log_ralph_event "self_review_rejected" \
            "\"storyId\":\"$NEXT_STORY\",\"retryCount\":$RETRY_NOW,\"reviewTokens\":${_REVIEW_TOKENS}"
          append_result "reject"
          echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
          echo "FAILED Phase I.5 self-review: $STORY_TITLE (ID: $NEXT_STORY) — critical issues found — attempt $RETRY_NOW/$MAX_RETRIES" >>"$PROGRESS_FILE"
          echo "" >>"$PROGRESS_FILE"
          continue
        fi
      else
        echo "  [Phase I.5] Skipped (retry $RETRY_NOW > threshold ${_REVIEW_SKIP_THRESHOLD})"
      fi
    fi
    # ── End Phase I.5 ────────────────────────────────────────────────────────

    # Run quality checks
    if run_project_quality_checks "$PRE_STORY_TS_ERRORS"; then
      reset_retry "$NEXT_STORY"

      COAUTHOR_MODEL="${EFFECTIVE_MODEL:-sonnet}"
      COAUTHOR_LABEL="${COAUTHOR_MODEL^}"
      git add -A
      if ! run_secret_scan; then
        echo "  [secret-scan] Unstaging changes and aborting story"
        do_story_reset "$PRE_STORY_SHA"
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason) = \"secret_detected\"" "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
        increment_retry "$NEXT_STORY"
        RETRY_NOW=$(get_retry_count "$NEXT_STORY")
        echo "[retry] $NEXT_STORY attempt $RETRY_NOW/$MAX_RETRIES (secret scan gate failed)"
        append_result "reject"
        echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
        echo "FAILED secret scan: $STORY_TITLE (ID: $NEXT_STORY) — attempt $RETRY_NOW/$MAX_RETRIES" >>"$PROGRESS_FILE"
        echo "" >>"$PROGRESS_FILE"
        continue
      fi
      if ! check_diff_size; then
        echo "  [diff-guard] Staged diff exceeds SPIRAL_MAX_DIFF_LINES=${SPIRAL_MAX_DIFF_LINES} (${LAST_DIFF_LINES} lines changed) — aborting commit"
        log_ralph_event "oversized_diff" "\"storyId\":\"$NEXT_STORY\",\"diffLines\":${LAST_DIFF_LINES},\"maxLines\":${SPIRAL_MAX_DIFF_LINES},\"diffStat\":\"${LAST_DIFF_STAT}\""
        do_story_reset "$PRE_STORY_SHA"
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason) = \"oversized_diff\"" "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
        increment_retry "$NEXT_STORY"
        RETRY_NOW=$(get_retry_count "$NEXT_STORY")
        echo "[retry] $NEXT_STORY attempt $RETRY_NOW/$MAX_RETRIES (diff size gate failed: ${LAST_DIFF_LINES} lines)"
        append_result "reject"
        echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
        echo "FAILED diff-guard: $STORY_TITLE (ID: $NEXT_STORY) — ${LAST_DIFF_LINES} lines > ${SPIRAL_MAX_DIFF_LINES} limit — attempt $RETRY_NOW/$MAX_RETRIES" >>"$PROGRESS_FILE"
        echo "" >>"$PROGRESS_FILE"
        continue
      fi
      if ! run_security_scan; then
        echo "  [security-scan] Unstaging changes and aborting story"
        do_story_reset "$PRE_STORY_SHA"
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason) = \"security_scan_failure\"" "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
        increment_retry "$NEXT_STORY"
        RETRY_NOW=$(get_retry_count "$NEXT_STORY")
        echo "[retry] $NEXT_STORY attempt $RETRY_NOW/$MAX_RETRIES (security scan gate failed)"
        append_result "reject"
        echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
        echo "FAILED security scan: $STORY_TITLE (ID: $NEXT_STORY) — attempt $RETRY_NOW/$MAX_RETRIES" >>"$PROGRESS_FILE"
        echo "" >>"$PROGRESS_FILE"
        continue
      fi
      if ! check_test_ratchet "$PRE_STORY_TESTS_PASSING"; then
        echo "  [test-ratchet] Reverting story — test count regressed"
        do_story_reset "$PRE_STORY_SHA"
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason) = \"test_ratchet_regression\"" "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
        increment_retry "$NEXT_STORY"
        RETRY_NOW=$(get_retry_count "$NEXT_STORY")
        echo "[retry] $NEXT_STORY attempt $RETRY_NOW/$MAX_RETRIES (test ratchet gate failed)"
        append_result "reject"
        echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
        echo "FAILED test-ratchet: $STORY_TITLE (ID: $NEXT_STORY) — tests regressed — attempt $RETRY_NOW/$MAX_RETRIES" >>"$PROGRESS_FILE"
        echo "" >>"$PROGRESS_FILE"
        continue
      fi
      # ── ADR Generation (US-155) ────────────────────────────────────────────
      # Generate a MADR-format Architecture Decision Record and stage it
      # so it is included in the story commit.  Non-blocking: a failure only
      # logs a warning and does not prevent the commit from proceeding.
      if [[ "${SPIRAL_SKIP_ADR:-false}" != "true" ]]; then
        local _adr_script
        _adr_script="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)/lib/generate_adr.py"
        local _python_cmd="${SPIRAL_PYTHON:-python3}"
        if [[ -f "$_adr_script" ]] && command -v "$_python_cmd" &>/dev/null; then
          echo "  [adr] Generating ADR for $NEXT_STORY..."
          local _adr_out
          _adr_out=$("$_python_cmd" "$_adr_script" \
            --story-id "$NEXT_STORY" \
            --prd "$PRD_FILE" \
            --output-dir "docs/decisions" \
            --model "${SPIRAL_ADR_MODEL:-haiku}" \
            2>&1) || true
          # _adr_out last line is the file path when exit 0; warn on empty
          local _adr_path
          _adr_path=$(echo "$_adr_out" | tail -1 | tr -d '\r\n' || true)
          if [[ -n "$_adr_path" && -f "$_adr_path" ]]; then
            git add "$_adr_path" 2>/dev/null || true
            echo "  [adr] ADR written and staged: $_adr_path"
          else
            echo "  [adr] WARNING: ADR generation failed — continuing without ADR"
            echo "  [adr] Output: ${_adr_out:-<empty>}"
          fi
        else
          echo "  [adr] SKIP: generate_adr.py or python3 not found"
        fi
      else
        echo "  [adr] SKIPPED (SPIRAL_SKIP_ADR=true)"
      fi

      _CONV_MSG=$(build_commit_msg \
        "$NEXT_STORY" "$STORY_TITLE" "${STORY_TAGS:-}" \
        "${STORY_FIRST_FILE:-}" "${SPIRAL_RUN_ID:-}" \
        "$ITERATION" "${STORY_DURATION:-0}")
      _CONV_MSG="${_CONV_MSG}
Co-Authored-By: Claude ${COAUTHOR_LABEL} 4.6 <noreply@anthropic.com>"
      do_git_commit "$_CONV_MSG" || echo "[warn] No changes to commit"

      # Record _passedCommit SHA in prd.json for traceability
      COMMIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo '')
      if [[ -n "$COMMIT_SHA" ]]; then
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\"))._passedCommit = \"$COMMIT_SHA\"" "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
      fi

      # Tag story with Ollama model when fallback was used (US-144)
      if [[ "${_OLLAMA_USED:-0}" -eq 1 && -n "${SPIRAL_OLLAMA_FALLBACK_MODEL:-}" ]]; then
        _OLLAMA_MODEL_TAG="ollama/${SPIRAL_OLLAMA_FALLBACK_MODEL}"
        $JQ --arg m "$_OLLAMA_MODEL_TAG" \
          '(.userStories[] | select(.id == "'"$NEXT_STORY"'"))._model = $m' \
          "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
        echo "  [ollama] Tagged story $NEXT_STORY with _model: $_OLLAMA_MODEL_TAG"
        log_spiral_event "ollama_story_tagged" \
          "\"story_id\":\"$NEXT_STORY\",\"model\":\"$_OLLAMA_MODEL_TAG\""
      fi

      # GitHub PR creation (US-143): push to feature branch + open PR when enabled
      if [[ "${SPIRAL_CREATE_PRS:-false}" == "true" && -n "$COMMIT_SHA" ]]; then
        create_github_pr "$NEXT_STORY" "$STORY_TITLE" "$COMMIT_SHA"
      fi

      append_result "keep" "$COMMIT_SHA"
      log_ralph_event "story_passed" "\"storyId\":\"$NEXT_STORY\",\"retryCount\":$(get_retry_count "$NEXT_STORY"),\"model\":\"${EFFECTIVE_MODEL:-sonnet}\""

      echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
      echo "Completed: $STORY_TITLE (ID: $NEXT_STORY) in ${STORY_DURATION}m" >>"$PROGRESS_FILE"
      echo "" >>"$PROGRESS_FILE"
    else
      echo "[rollback] Quality checks failed — reverting prd.json mark"
      $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" >"${PRD_FILE}.tmp"
      mv "${PRD_FILE}.tmp" "$PRD_FILE"

      increment_retry "$NEXT_STORY"
      RETRY_NOW=$(get_retry_count "$NEXT_STORY")
      echo "[retry] $NEXT_STORY attempt $RETRY_NOW/$MAX_RETRIES"
      append_result "reject"
      log_ralph_event "story_failed" "\"storyId\":\"$NEXT_STORY\",\"retryCount\":$RETRY_NOW,\"model\":\"${EFFECTIVE_MODEL:-sonnet}\""

      echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
      echo "FAILED quality gates: $STORY_TITLE (ID: $NEXT_STORY) — attempt $RETRY_NOW/$MAX_RETRIES" >>"$PROGRESS_FILE"
      if maybe_auto_decompose "$NEXT_STORY" "$RETRY_NOW" "${EFFECTIVE_MODEL:-sonnet}"; then
        echo "" >>"$PROGRESS_FILE"
        continue
      fi
      if [[ "$RETRY_NOW" -ge "$MAX_RETRIES" ]]; then
        FAILURE_REASON="MAX_RETRIES exhausted (quality gate failed after $MAX_RETRIES attempts)"
        $JQ --arg reason "$FAILURE_REASON" \
          '(.userStories[] | select(.id == "'"$NEXT_STORY"'") | ._failureReason) = $reason' \
          "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
        do_story_reset "$PRE_STORY_SHA"
        if decompose_story "$NEXT_STORY" "${EFFECTIVE_MODEL:-sonnet}"; then
          echo "DECOMPOSED: $NEXT_STORY after $MAX_RETRIES failed attempts — sub-stories created" >>"$PROGRESS_FILE"
          echo "[decompose] $NEXT_STORY decomposed after $MAX_RETRIES attempts"
        else
          echo "SKIPPED: $NEXT_STORY after $MAX_RETRIES failed attempts" >>"$PROGRESS_FILE"
          echo "[skip] $NEXT_STORY skipped after $MAX_RETRIES attempts — moving on"
        fi
      fi
      echo "" >>"$PROGRESS_FILE"
    fi
  else
    echo ""
    echo "[warn] Story not completed by $EFFECTIVE_TOOL instance"

    increment_retry "$NEXT_STORY"
    RETRY_NOW=$(get_retry_count "$NEXT_STORY")
    echo "[retry] $NEXT_STORY attempt $RETRY_NOW/$MAX_RETRIES"
    append_result "reject"
    log_ralph_event "story_failed" "\"storyId\":\"$NEXT_STORY\",\"retryCount\":$RETRY_NOW,\"model\":\"${EFFECTIVE_MODEL:-sonnet}\""

    echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
    echo "Incomplete: $STORY_TITLE (ID: $NEXT_STORY) — attempt $RETRY_NOW/$MAX_RETRIES" >>"$PROGRESS_FILE"
    if maybe_auto_decompose "$NEXT_STORY" "$RETRY_NOW" "${EFFECTIVE_MODEL:-sonnet}"; then
      echo "" >>"$PROGRESS_FILE"
      continue
    fi
    # Ratchet: reset working tree before next retry so it starts clean
    do_story_reset "$PRE_STORY_SHA"
    if [[ "$RETRY_NOW" -ge "$MAX_RETRIES" ]]; then
      FAILURE_REASON="MAX_RETRIES exhausted (story incomplete after $MAX_RETRIES attempts)"
      $JQ --arg reason "$FAILURE_REASON" \
        '(.userStories[] | select(.id == "'"$NEXT_STORY"'") | ._failureReason) = $reason' \
        "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
      do_story_reset "$PRE_STORY_SHA"
      if decompose_story "$NEXT_STORY" "${EFFECTIVE_MODEL:-sonnet}"; then
        echo "DECOMPOSED: $NEXT_STORY after $MAX_RETRIES failed attempts — sub-stories created" >>"$PROGRESS_FILE"
        echo "[decompose] $NEXT_STORY decomposed after $MAX_RETRIES attempts"
      else
        echo "SKIPPED: $NEXT_STORY after $MAX_RETRIES failed attempts" >>"$PROGRESS_FILE"
        echo "[skip] $NEXT_STORY skipped after $MAX_RETRIES attempts — moving on"
      fi
    fi
    echo "" >>"$PROGRESS_FILE"
  fi
done

# ── Summary ──────────────────────────────────────────────────────
END_TIME=$(date +%s)
TOTAL_MINUTES=$(((END_TIME - START_TIME) / 60))

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
