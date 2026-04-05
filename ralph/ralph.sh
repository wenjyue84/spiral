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

# ── Windows encoding guard — prevent cp1252 UnicodeEncodeError on emoji ─────
# Claude output often contains emoji (✅ ✓ etc.) which crashes inline Python
# scripts when stdout defaults to cp1252 on Windows.
export PYTHONIOENCODING=utf-8

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
SPIRAL_STORY_COST_WARN_USD="${SPIRAL_STORY_COST_WARN_USD:-9999.00}"         # warn when story exceeds this
SPIRAL_STORY_COST_HARD_USD="${SPIRAL_STORY_COST_HARD_USD:-9999.00}"         # abandon story when it exceeds this
SPIRAL_MODEL_INPUT_PRICE_PER_M="${SPIRAL_MODEL_INPUT_PRICE_PER_M:-3.00}"    # $/1M input tokens (sonnet default)
SPIRAL_MODEL_OUTPUT_PRICE_PER_M="${SPIRAL_MODEL_OUTPUT_PRICE_PER_M:-15.00}" # $/1M output tokens (sonnet default)
SPIRAL_MODEL_FALLBACK_CHAIN="${SPIRAL_MODEL_FALLBACK_CHAIN:-}"              # colon-separated fallback models (e.g. sonnet:haiku:gemini-2.0-flash)
SPIRAL_MAX_DIFF_LINES="${SPIRAL_MAX_DIFF_LINES:-500}"                       # 0 = disabled; abort commit if staged diff exceeds this many changed lines
SPIRAL_CONTEXT_MODE="${SPIRAL_CONTEXT_MODE:-diff}"                          # US-280: diff|full — inject git diff (default) or full file contents as story context
SPIRAL_DIFF_DEPTH="${SPIRAL_DIFF_DEPTH:-3}"                                 # US-280: number of commits to diff against (git diff HEAD~N)
SPIRAL_GIT_AUTHOR="${SPIRAL_GIT_AUTHOR:-}"                                  # optional: AI commit author name (e.g. "SPIRAL Agent")
SPIRAL_GIT_EMAIL="${SPIRAL_GIT_EMAIL:-}"                                    # optional: AI commit author email (e.g. "spiral@noreply.local")
SPIRAL_DECOMPOSE_THRESHOLD="${SPIRAL_DECOMPOSE_THRESHOLD:-2}"               # auto-decompose story at this retry count; 0 = disabled
SPIRAL_ESCALATION_RETRY_SONNET="${SPIRAL_ESCALATION_RETRY_SONNET:-1}"       # retry count at which haiku escalates to sonnet (US-296)
SPIRAL_ESCALATION_RETRY_OPUS="${SPIRAL_ESCALATION_RETRY_OPUS:-2}"           # retry count at which sonnet escalates to opus (US-296)
SPIRAL_SECURITY_SCAN="${SPIRAL_SECURITY_SCAN:-false}"                       # true = enable Phase S security scan gate
SPIRAL_SECURITY_SCAN_TOOL="${SPIRAL_SECURITY_SCAN_TOOL:-semgrep}"           # 'semgrep' (default) or 'bandit'
SPIRAL_SECURITY_SCAN_ARGS="${SPIRAL_SECURITY_SCAN_ARGS:-}"                  # extra flags passed to the scanner binary
SPIRAL_PRD_STREAM_THRESHOLD_KB="${SPIRAL_PRD_STREAM_THRESHOLD_KB:-512}"     # switch to jq --stream when prd.json exceeds this size (KB); 0 = always stream
SPIRAL_OLLAMA_FALLBACK_MODEL="${SPIRAL_OLLAMA_FALLBACK_MODEL:-}"            # Ollama model for Claude API fallback (e.g. qwen2.5-coder:32b); empty = disabled
SPIRAL_OLLAMA_HOST="${SPIRAL_OLLAMA_HOST:-http://localhost:11434/v1}"       # Ollama OpenAI-compat base URL (default: local Ollama)
SPIRAL_LOCAL_FALLBACK_POLICY="${SPIRAL_LOCAL_FALLBACK_POLICY:-}"            # US-261: allow|deny|local-only; empty = disabled
SPIRAL_OLLAMA_BASE_URL="${SPIRAL_OLLAMA_BASE_URL:-http://localhost:11434}"  # US-261: Ollama native base URL (no /v1 suffix)
SPIRAL_OLLAMA_MODEL="${SPIRAL_OLLAMA_MODEL:-llama3.2}"                      # US-261: local model for policy-based fallback
SPIRAL_CACHE_TTL="${SPIRAL_CACHE_TTL:-}"                                    # US-336: prompt cache TTL (e.g. "1h") — extends cache lifetime at 2x cost
SPIRAL_DEFERRED_TOOLS="${SPIRAL_DEFERRED_TOOLS:-true}"                      # US-337: true = use --tools flag with core tools only; deferred tools via ToolSearch
SPIRAL_SKIP_SELF_REVIEW="${SPIRAL_SKIP_SELF_REVIEW:-false}"                 # true = disable Phase I.5 LLM self-review gate (US-145)
SPIRAL_SELF_REVIEW_MODEL="${SPIRAL_SELF_REVIEW_MODEL:-haiku}"               # Claude model for self-review; haiku to minimise cost (US-145)
SPIRAL_GEMINI_SKIP_SMALL="${SPIRAL_GEMINI_SKIP_SMALL:-true}"                # true = skip Gemini pre-analysis for small stories with <=2 filesTouch (US-171)
SPIRAL_SKIP_ADR="${SPIRAL_SKIP_ADR:-false}"                                 # true = disable ADR generation via generate_adr.py after story passes (US-155)
SPIRAL_ADR_MODEL="${SPIRAL_ADR_MODEL:-haiku}"                               # Claude model for ADR generation; haiku to minimise cost (US-155)
SPIRAL_WORKER_MEMORY_LIMIT="${SPIRAL_WORKER_MEMORY_LIMIT:-0}"               # 0 = disabled; KB — peak RSS after story triggers OOM guard (US-158)
SPIRAL_CONTEXT_WINDOW="${SPIRAL_CONTEXT_WINDOW:-10}"                        # rolling window depth for observation masking (US-241)
SPIRAL_CONTEXT_MODE="${SPIRAL_CONTEXT_MODE:-diff}"                          # diff|full — context injection mode for filesTouch files (US-280)
SPIRAL_DIFF_DEPTH="${SPIRAL_DIFF_DEPTH:-3}"                                 # number of commits to look back for git diff context injection (US-280)
SPIRAL_WORKER_NETWORK_ISOLATION="${SPIRAL_WORKER_NETWORK_ISOLATION:-false}" # true = wrap worker in Linux network namespace via unshare --net (US-278)
SPIRAL_STRICT_SCOPE_GUARD="${SPIRAL_STRICT_SCOPE_GUARD:-false}"             # true = abort commit when changed files exceed story filesTouch scope (US-356)
SPIRAL_THINKING_EFFORT="${SPIRAL_THINKING_EFFORT:-high}"                    # US-373: adaptive thinking effort for 4.6 models (low/medium/high/max)
SPIRAL_THINKING_BUDGET_TOKENS="${SPIRAL_THINKING_BUDGET_TOKENS:-10000}"     # US-398: max thinking tokens per story (0=disable thinking, min 1024)
SPIRAL_PROGRAMMATIC_TOOLS="${SPIRAL_PROGRAMMATIC_TOOLS:-auto}"              # US-339: enable code_execution_20250825 tool (auto/true/false)
SPIRAL_INTERLEAVED_THINKING="${SPIRAL_INTERLEAVED_THINKING:-false}"         # US-392: enable interleaved-thinking-2025-05-14 beta for claude-4 models
PRD_FILE="prd.json"
PROGRESS_FILE="progress.txt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Save original args before parsing (needed for re-exec under unshare)
_RALPH_ORIG_ARGS=("$@")

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
    --cache-ttl)
      SPIRAL_CACHE_TTL="$2"
      shift 2
      ;;
    --files-only)
      RALPH_FILES_ONLY="$2"
      shift 2
      ;;
    --memory-inject)
      RALPH_MEMORY_INJECT=true
      shift
      ;;
    *)
      MAX_ITERATIONS="$1"
      shift
      ;;
  esac
done

# Default files-only to empty (disabled)
RALPH_FILES_ONLY="${RALPH_FILES_ONLY:-}"
# Default memory inject to false (opt-in via --memory-inject flag)
RALPH_MEMORY_INJECT="${RALPH_MEMORY_INJECT:-false}"

# Validate AI tool
if [[ "$AI_TOOL" != "amp" && "$AI_TOOL" != "claude" && "$AI_TOOL" != "codex" && "$AI_TOOL" != "qwen" && "$AI_TOOL" != "auto" ]]; then
  echo "Error: Invalid tool: $AI_TOOL (use 'amp', 'claude', 'codex', 'qwen', or 'auto')"
  exit 1
fi

# ── Network namespace isolation (US-278) ──────────────────────────────────────
# When SPIRAL_WORKER_NETWORK_ISOLATION=true, re-exec this script under
# 'unshare --net' on Linux to block all outbound connections.
# On Windows/macOS the flag is silently accepted but isolation is skipped with
# a structured warning written to spiral_events.jsonl.
if [[ "${SPIRAL_WORKER_NETWORK_ISOLATION:-false}" == "true" && -z "${SPIRAL_NETWORK_ISOLATION_APPLIED:-}" ]]; then
  _OS_TYPE=$(uname -s 2>/dev/null || echo "Unknown")
  # Normalise MSYS/Cygwin/MinGW identifiers to "Windows"
  case "$_OS_TYPE" in
    CYGWIN* | MINGW* | MSYS*) _OS_TYPE="Windows" ;;
  esac
  if [[ "$_OS_TYPE" == "Linux" ]]; then
    if command -v unshare &>/dev/null; then
      echo "  [network-isolation] Entering network namespace via unshare --net"
      export SPIRAL_NETWORK_ISOLATION_APPLIED=1
      exec unshare --net -- bash "$0" "${_RALPH_ORIG_ARGS[@]}"
    else
      echo "  [network-isolation] WARNING: unshare not found — network isolation skipped"
      _ni_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo '1970-01-01T00:00:00Z')"
      _ni_log="${SPIRAL_SCRATCH_DIR:-.spiral}/spiral_events.jsonl"
      printf '{"ts":"%s","event":"network_isolation_skipped","reason":"unshare_not_found","os":"%s"}\n' \
        "$_ni_ts" "$_OS_TYPE" >>"$_ni_log" 2>/dev/null || true
    fi
  else
    echo "  [network-isolation] WARN: SPIRAL_WORKER_NETWORK_ISOLATION=true but OS is '$_OS_TYPE' — isolation skipped"
    _ni_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo '1970-01-01T00:00:00Z')"
    _ni_log="${SPIRAL_SCRATCH_DIR:-.spiral}/spiral_events.jsonl"
    printf '{"ts":"%s","event":"network_isolation_skipped","reason":"unsupported_os","os":"%s"}\n' \
      "$_ni_ts" "$_OS_TYPE" >>"$_ni_log" 2>/dev/null || true
  fi
fi

# Source profiling utilities
_PROFILER_PATH="${SCRIPT_DIR}/../lib/workers/profiler.sh"
if [[ -f "$_PROFILER_PATH" ]]; then
  source "$_PROFILER_PATH"
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

# ── Validate SPIRAL_ESCALATION_RETRY_* config (US-296) ─────────────────────
if [[ "${SPIRAL_ESCALATION_RETRY_OPUS:-2}" -lt "${SPIRAL_ESCALATION_RETRY_SONNET:-1}" ]]; then
  echo "ERROR: SPIRAL_ESCALATION_RETRY_OPUS (${SPIRAL_ESCALATION_RETRY_OPUS}) must be >= SPIRAL_ESCALATION_RETRY_SONNET (${SPIRAL_ESCALATION_RETRY_SONNET})."
  echo "Fix: set SPIRAL_ESCALATION_RETRY_OPUS to a value >= SPIRAL_ESCALATION_RETRY_SONNET in spiral.config.sh."
  exit 1
fi

# ── Source spiral_retry library for API retry with jitter ───────────────────
SPIRAL_HOME="${SPIRAL_HOME:-.}"
[[ -f "$SPIRAL_HOME/lib/spiral_retry.sh" ]] && source "$SPIRAL_HOME/lib/spiral_retry.sh"

# ── Source spiral_undo library for per-story undo stack (US-239) ─────────────
[[ -f "$SPIRAL_HOME/lib/spiral_undo.sh" ]] && source "$SPIRAL_HOME/lib/spiral_undo.sh"

# ── Source policy_check library for pre-action policy gate (US-242) ──────────
[[ -f "$SPIRAL_HOME/lib/policy_check.sh" ]] && source "$SPIRAL_HOME/lib/policy_check.sh"

# ── Source command_allowlist library for phase-scoped command gate (US-243) ──
[[ -f "$SPIRAL_HOME/lib/command_allowlist.sh" ]] && source "$SPIRAL_HOME/lib/command_allowlist.sh"

# ── Source context injection library (US-280) ────────────────────────────────
[[ -f "$SPIRAL_HOME/lib/context_injection.sh" ]] && source "$SPIRAL_HOME/lib/context_injection.sh"

# ── Source tool parameter validator (US-249) ──────────────────────────────────
[[ -f "$SPIRAL_HOME/lib/tool_param_validator.sh" ]] && source "$SPIRAL_HOME/lib/tool_param_validator.sh"

# ── Source agent telemetry library (US-253) ──────────────────────────────────
[[ -f "$SPIRAL_HOME/lib/agent_telemetry.sh" ]] && source "$SPIRAL_HOME/lib/agent_telemetry.sh"

# ── Source model routing functions (check_deps_met, classify_model, etc.) ────
source "$SCRIPT_DIR/lib/model_routing.sh"

# ── Source quality gate functions (secret scan, diff guard, scope guard, etc.) ─
source "$SCRIPT_DIR/lib/quality_gates.sh"

# ── Source prompt builder (system + user prompt assembly) ─────────────────────
source "$SCRIPT_DIR/lib/prompt_builder.sh"

# ── Source ralph helpers (stream text, anti-patterns, gate reject, event log, cost) ─
source "$SCRIPT_DIR/lib/ralph_helpers.sh"

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

# ── Tool schema init (US-249) ────────────────────────────────────
if declare -f tool_schema_init >/dev/null 2>&1; then
  tool_schema_init >/dev/null 2>&1 || true
fi

# ── Branch management ────────────────────────────────────────────
CURRENT_BRANCH=$(git branch --show-current)
# Capture base branch once at startup for per-story feature branching (US-157)
SPIRAL_BASE_BRANCH="${SPIRAL_BASE_BRANCH:-$CURRENT_BRANCH}"
STORY_BRANCH="" # tracks current story feature branch; set by create_story_branch
if [[ "$CURRENT_BRANCH" != "$BRANCH_NAME" && "$BRANCH_NAME" != "main" && "$BRANCH_NAME" != "master" ]]; then
  if git show-ref --verify --quiet "refs/heads/$BRANCH_NAME"; then
    echo "[branch] Switching to existing branch: $BRANCH_NAME"
    git checkout "$BRANCH_NAME"
  else
    echo "[branch] Creating new feature branch: $BRANCH_NAME"
    git checkout -b "$BRANCH_NAME"
  fi
fi

# ── Source git operations (commit, reset, conventional commit message) ────────
source "$SCRIPT_DIR/lib/git_operations.sh"

# ── filesTouch diff context injection (US-280) ──────────────────────────────
# build_filestouch_context <story_json>
# Computes a unified git diff of the filesTouch paths (last SPIRAL_DIFF_DEPTH commits)
# and returns the context block via stdout.  Falls back to full file contents when:
#   - diff is empty (new/untracked files)
#   - filesTouch is absent or empty
# Diff is truncated at SPIRAL_MAX_DIFF_LINES (default: 500) with a notice.
# Returns 0 always; outputs empty string when SPIRAL_CONTEXT_MODE=full or no filesTouch.
build_filestouch_context() {
  local story_json="${1:-}"
  if [[ "${SPIRAL_CONTEXT_MODE:-diff}" != "diff" ]]; then
    return 0
  fi
  if [[ -z "$story_json" || "$story_json" == "{}" ]]; then
    return 0
  fi

  local _jq_bin="${JQ:-jq}"
  local _ft_files=()
  while IFS= read -r _f; do
    [[ -n "$_f" ]] && _ft_files+=("$_f")
  done < <("$_jq_bin" -r '.filesTouch // [] | .[]' <<<"$story_json" 2>/dev/null)

  if [[ "${#_ft_files[@]}" -eq 0 ]]; then
    return 0
  fi

  local _depth="${SPIRAL_DIFF_DEPTH:-3}"
  local _max_lines="${SPIRAL_MAX_DIFF_LINES:-500}"
  local _diff_out
  _diff_out=$(git diff --unified=5 "HEAD~${_depth}" -- "${_ft_files[@]}" 2>/dev/null || true)

  if [[ -z "$_diff_out" ]]; then
    # Diff is empty — inject semantically relevant chunks as fallback.
    local _semantic_content=""
    local _ff
    local _story_desc
    _story_desc=$("$_jq_bin" -r '.title + ": " + .description' <<<"$story_json" 2>/dev/null)
    local _chunker_py
    _chunker_py="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)/lib/resilience/semantic_chunker.py"

    echo "  [context] filesTouch: diff empty — using semantic chunker for ${#_ft_files[@]} file(s)" >&2

    for _ff in "${_ft_files[@]}"; do
      if [[ -f "$_ff" ]]; then
        local _chunks
        _chunks=$(python3 "$_chunker_py" --file "$_ff" --task "$_story_desc" 2>/dev/null)
        if [[ -n "$_chunks" ]]; then
          _semantic_content="${_semantic_content}
### File: ${_ff} (semantically relevant chunks)
\`\`\`
${_chunks}
\`\`\`
"
        fi
      fi
    done

    if [[ -n "$_semantic_content" ]]; then
      echo "## filesTouch File Contents (Semantically Relevant Chunks)"
      echo "${_semantic_content}"
    fi
    return 0
  fi

  # Truncate diff if it exceeds SPIRAL_MAX_DIFF_LINES
  local _diff_lines
  _diff_lines=$(echo "$_diff_out" | wc -l | tr -d ' \r')
  local _truncated=0
  if [[ "${_max_lines:-500}" -gt 0 && "${_diff_lines:-0}" -gt "${_max_lines:-500}" ]]; then
    _diff_out=$(echo "$_diff_out" | head -"${_max_lines}")
    _truncated=1
  fi

  echo "## filesTouch Unified Diff (HEAD~${_depth} → HEAD)"
  echo "\`\`\`diff"
  echo "${_diff_out}"
  if [[ "$_truncated" -eq 1 ]]; then
    echo "[Diff truncated at ${_max_lines} lines — ${_diff_lines} total lines]"
  fi
  echo "\`\`\`"
  echo "  [context] filesTouch: injected unified diff (${_diff_lines} lines${_truncated:+, truncated at ${_max_lines}})" >&2
}

# ── Source story lifecycle (retry, decompose, classify, experience capture) ───
source "$SCRIPT_DIR/lib/story_lifecycle.sh"

# ── Source branch management (PR creation, story branches) ────────────────────
source "$SCRIPT_DIR/lib/branch_management.sh"

# ── Source Ollama fallback (API call, pre-warm, policy-based local fallback) ──
source "$SCRIPT_DIR/lib/ollama_fallback.sh"

# ── Ollama pre-warm at worker startup (US-261) ──────────────────────────────
ollama_prewarm

# ── Source Phase I.5: LLM self-review gate (US-145) ──────────────────────────
source "$SCRIPT_DIR/lib/self_review.sh"

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

# generate_ac_report() — Generate AC evaluation report for partial victory (US-787)
# Creates .spiral/ac_reports/STORY_ID.json with AC evaluation based on story ACs
# Used by Phase I to check for partial victory opportunities
generate_ac_report() {
  local story_id="$1"
  local prd_file="$2"
  local scratch_dir="${SPIRAL_SCRATCH_DIR:-.spiral}"

  # Extract ACs from story
  local ac_json
  ac_json=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .acceptanceCriteria // []" "$prd_file" 2>/dev/null || echo "[]")

  # Build AC evaluation report (all initially marked as failed)
  # Phase I or external logic can override this with actual AC status
  mkdir -p "$scratch_dir/ac_reports"
  local report_file="$scratch_dir/ac_reports/${story_id}.json"

  local ac_eval="[]"
  local ac_count
  ac_count=$(echo "$ac_json" | $JQ 'length' 2>/dev/null || echo "0")

  if [[ "$ac_count" -gt 0 ]]; then
    # Build AC evaluation array with all ACs initially failed
    ac_eval=$(echo "$ac_json" | $JQ -c '[to_entries | .[] | {index: .key, text: .value, passed: false}]' 2>/dev/null || echo "[]")
  fi

  # Write report
  printf '{"story_id":"%s","ac_evaluation":%s}\n' "$story_id" "$ac_eval" >"$report_file" 2>/dev/null || true
}

# ── Model routing functions sourced from $SCRIPT_DIR/lib/model_routing.sh ─────
# Functions: check_deps_met, classify_model, escalate_model_by_retry,
#            escalate_model_by_quality_failure, supports_adaptive_thinking,
#            budget_to_effort, resolve_model

# ── Dry run mode ─────────────────────────────────────────────────
if [[ "${DRY_RUN:-false}" == "true" ]]; then
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
  file_kb=$(($(wc -c <"$prd_file") / 1024))

  if [[ "$threshold_kb" -gt 0 && "$file_kb" -ge "$threshold_kb" ]]; then
    # Streaming path: reconstruct individual userStories objects using fromstream,
    # then filter and sort in a second pass to avoid full document parse.
    $JQ -rn --stream \
      'fromstream(2|truncate_stream(inputs|select(.[0][:1]==["userStories"])))
       | select(.passes == false and (._decomposed | not))
       | [.priority // "zzz", .id]
       | @tsv' "$prd_file" |
      sort |
      cut -f2 |
      tr -d '\r'
  else
    # Normal path: full in-memory parse (default for prd.json files under threshold)
    $JQ -r '[.userStories[] | select(.passes == false and (._decomposed | not))]
             | sort_by(.priority)
             | .[].id' "$prd_file" |
      tr -d '\r'
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
        is_decomposed_parent=$($JQ -r ".userStories[] | select(.id == \"$sid\") | ._decomposed // false" "$PRD_FILE" | tr -d '\r')
        if [[ "$is_decomposed_parent" == "true" ]]; then
          children=$($JQ -r ".userStories[] | select(.id == \"$sid\") | ._decomposedInto // [] | join(\", \")" "$PRD_FILE" | tr -d '\r')
          echo "    DECOMPOSED:            [$sid] $stitle → [$children]"
        elif [[ "$retries" -ge "$MAX_RETRIES" ]]; then
          echo "    SKIPPED (${retries}x failed): [$sid] $stitle"
          save_candidate_experience "$sid"
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
  STORY_BATCH_ID=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | ._batch_id // empty" "$PRD_FILE" 2>/dev/null | tr -d '\r' || true)
  RETRY_NOW=$(get_retry_count "$NEXT_STORY")

  # ── Retrieval completeness check (US-250) ────────────────────────
  # Verify story context is complete before Phase I. Retry up to 3 times.
  _completeness_attempts=0
  while [[ $_completeness_attempts -lt 3 ]]; do
    _completeness_attempts=$((_completeness_attempts + 1))
    if check_story_completeness "$NEXT_STORY" "$PRD_FILE"; then
      echo "  [completeness] ✓ Story context complete"
      break
    else
      if [[ $_completeness_attempts -lt 3 ]]; then
        echo "  [completeness] Retry $_completeness_attempts/3: Re-reading prd.json..."
        sleep 1
      else
        echo "  [completeness] BLOCKED after 3 failed checks"
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason) = \"incomplete_context\"" "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
        echo "BLOCKED incomplete_context: $NEXT_STORY (ID: $NEXT_STORY) — context incomplete after 3 checks" >>"$PROGRESS_FILE"
        continue 2 # Skip to next story in outer loop
      fi
    fi
  done

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
    EFFECTIVE_MODEL=$(resolve_model "$NEXT_STORY" "$RETRY_NOW" "$(get_escalation_count "$NEXT_STORY")")
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

  # ── Undo log: detect stale log from a prior failed attempt (US-239) ──────
  if type undo_log_exists &>/dev/null && undo_log_exists "$NEXT_STORY"; then
    echo "  [undo] Prior undo log detected for $NEXT_STORY — previous attempt left partial state"
    echo "  [undo] Worktree reset to $PRE_STORY_SHA (idempotent retry)"
    log_ralph_event "undo_log_stale_detected" "\"storyId\":\"$NEXT_STORY\",\"sha\":\"$PRE_STORY_SHA\""
  fi

  # Record checkpoint: enables clean rollback to pre-story HEAD on failure
  if type undo_log_record &>/dev/null && [[ -n "$PRE_STORY_SHA" ]]; then
    undo_log_record "$NEXT_STORY" "checkpoint" "HEAD:$PRE_STORY_SHA" \
      "git reset --hard $PRE_STORY_SHA"
  fi

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
  _TELEM_R_START_MS=$(date +%s%3N 2>/dev/null || echo 0) # US-253: Phase R start timestamp (ms)
  _TELEM_I_START_MS=0                                    # set right before AI invocation
  _TELEM_V_START_MS=0                                    # set right after AI invocation
  _OLLAMA_USED=0                                         # reset per-story; set to 1 if Ollama fallback fires (US-144)
  _REVIEW_TOKENS=0                                       # reset per-story; set by run_self_review Phase I.5 (US-145)
  _WALL_SEC=0
  _USER_CPU_S=0
  _SYS_CPU_S=0
  _PEAK_RSS_KB=0            # reset per-story resource stats (US-158)
  _DECOMPOSE_SECS=0         # reset per-story; set by decompose_story (US-521)
  _IMPL_SECS=0              # reset per-story; set by AI invocation phase (US-521)
  _VERIFY_SECS=0            # reset per-story; set by verification phase (US-521)
  _RETRY_ESCALATION_COUNT=0 # reset per-story; increment when model escalates (US-521)
  _FAILED_FILES=""          # reset per-story; JSON array of files that failed (US-597)
  if declare -f reset_phase_timings >/dev/null 2>&1; then
    reset_phase_timings
  fi

  # ── Per-story feature branch (US-157): create branch before Phase I ──────────
  create_story_branch "$NEXT_STORY"

  echo ""
  echo "  [spawn] Fresh $EFFECTIVE_TOOL instance for $NEXT_STORY..."

  # ── Gemini pre-context (paid tier, deep reasoning, saves 20+ claude turns) ──
  STORY_JSON=$($JQ -c ".userStories[] | select(.id == \"$NEXT_STORY\")" "$PRD_FILE" 2>/dev/null || echo "{}")

  # ── Token guard (US-408): Anthropic API token count + auto-trim ──────────
  # Uses count_tokens API (free, no quota) for accurate pre-flight check.
  # Falls back to tiktoken/approx when API key is absent or SDK not installed.
  # Emits token_budget_exceeded event to spiral_events.jsonl if over budget.
  _TOKEN_GUARD_PY="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)/lib/resilience/token_guard.py"
  if [[ -f "$_TOKEN_GUARD_PY" ]] && command -v python3 &>/dev/null &&
    [[ -n "$STORY_JSON" && "$STORY_JSON" != "{}" ]]; then
    _TG_WARN=$(echo "$STORY_JSON" |
      python3 "$_TOKEN_GUARD_PY" \
        --model "${SPIRAL_MODEL:-sonnet}" \
        --base-prompt-file "$PROMPT_FILE" \
        --scratch-dir "${SPIRAL_SCRATCH_DIR:-.spiral}" \
        2>&1 1>/dev/null)
    _TG_JSON=$(echo "$STORY_JSON" |
      python3 "$_TOKEN_GUARD_PY" \
        --model "${SPIRAL_MODEL:-sonnet}" \
        --base-prompt-file "$PROMPT_FILE" \
        --scratch-dir "${SPIRAL_SCRATCH_DIR:-.spiral}" \
        2>/dev/null)
    if [[ -n "$_TG_JSON" && "$_TG_JSON" != "{}" ]]; then
      STORY_JSON="$_TG_JSON"
    fi
    if [[ -n "$_TG_WARN" ]]; then
      echo "  [token_guard] WARNING: $(echo "$_TG_WARN" | python3 -c \
        "import sys,json; d=json.load(sys.stdin); \
         print(f\"token budget exceeded for {d.get('story_id','?')}: \
{d.get('token_count','?')} tokens > budget {d.get('budget','?')} — context trimmed\")" 2>/dev/null || echo "$_TG_WARN")"
      {
        echo ""
        echo "## Token Guard Warning — $NEXT_STORY"
        echo "$_TG_WARN"
        echo ""
      } >>"$PROGRESS_FILE"
    fi
  fi

  # ── Context truncation gate (US-141) ─────────────────────────────────────
  # Measure story token count before spawning AI; strip over-budget fields.
  _TRUNCATE_PY="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)/lib/resilience/truncate_context.py"
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
  if [[ "${SPIRAL_GEMINI_SKIP_SMALL:-true}" != "false" &&
    -z "${SPIRAL_GEMINI_ANNOTATE_PROMPT:-}" &&
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

  # ── Resource accounting setup (US-158) ─────────────────────────────────────
  # Use GNU time on Linux to capture wall/user/sys/RSS; else timing defaults to 0.
  _RESOURCE_TMP="${SPIRAL_SCRATCH_DIR}/_res_$$.tmp"
  _GNU_TIME_CMD=()
  if [[ "$(uname -s 2>/dev/null)" == "Linux" ]] && /usr/bin/time -f '%e' -o /dev/null true 2>/dev/null; then
    _GNU_TIME_CMD=(/usr/bin/time -f '%e %U %S %M' -o "$_RESOURCE_TMP")
  fi

  # ── AI tool invocation ──────────────────────────────────────────────────────
  _RL_TMP="${SPIRAL_SCRATCH_DIR}/_rate_limit_check_$$.tmp"
  _PHASE_I_DIAGNOSIS_BLOCK="" # US-244: populated if worker outputs a diagnosis block
  _OBS_HISTORY=()             # US-241: rolling observation buffer (one entry per retry attempt)
  _OBS_TOKENS_BEFORE=0        # US-241: cumulative raw context chars/4 estimate (all retries)
  _OBS_TOKENS_AFTER=0         # US-241: cumulative masked context chars/4 estimate (all retries)

  echo "  ─────── AI Output Start ($EFFECTIVE_TOOL) ───────"
  if [[ "$EFFECTIVE_TOOL" == "claude" ]]; then
    # Build model flag (empty if no model routing)
    CLAUDE_MODEL_FLAG=""
    [[ -n "$EFFECTIVE_MODEL" ]] && CLAUDE_MODEL_FLAG="--model $EFFECTIVE_MODEL"
    # US-373 + US-398: Build effort flag for adaptive thinking on 4.6 models.
    # When SPIRAL_THINKING_BUDGET_TOKENS is set, it overrides SPIRAL_THINKING_EFFORT
    # by mapping the budget to an effort level. When =0, thinking is disabled entirely.
    CLAUDE_EFFORT_FLAG=""
    if [[ -n "$EFFECTIVE_MODEL" ]] && supports_adaptive_thinking "$EFFECTIVE_MODEL"; then
      if [[ "${SPIRAL_THINKING_BUDGET_TOKENS:-10000}" -eq 0 ]]; then
        echo "  [thinking] Disabled: SPIRAL_THINKING_BUDGET_TOKENS=0 (model=$EFFECTIVE_MODEL)"
      else
        _BUDGET_EFFORT=$(budget_to_effort "${SPIRAL_THINKING_BUDGET_TOKENS:-10000}")
        if [[ -n "$_BUDGET_EFFORT" ]]; then
          CLAUDE_EFFORT_FLAG="--effort $_BUDGET_EFFORT"
          echo "  [thinking] Adaptive thinking: effort=$_BUDGET_EFFORT (budget=${SPIRAL_THINKING_BUDGET_TOKENS:-10000} tokens, model=$EFFECTIVE_MODEL)"
        fi
      fi
    fi
    # ── Build system + user prompts (extracted to lib/prompt_builder.sh) ────
    build_ralph_prompts

    _CACHE_BETAS=""
    # ── US-337: Deferred tool loading — reduce tool definition tokens ──────
    # When enabled, use --tools with only core tools from tool_manifest.json.
    # Deferred tools are discoverable via ToolSearch at runtime.
    _DEFERRED_TOOLS_FLAG=""
    if [[ "${SPIRAL_DEFERRED_TOOLS:-true}" == "true" ]]; then
      _TOOL_MANIFEST="${SCRIPT_DIR}/tool_manifest.json"
      if [[ -f "$_TOOL_MANIFEST" ]]; then
        _CORE_TOOLS=$("$JQ" -r '.core | join(",")' "$_TOOL_MANIFEST" 2>/dev/null || echo "")
        if [[ -n "$_CORE_TOOLS" ]]; then
          _DEFERRED_TOOLS_FLAG="--tools $_CORE_TOOLS"
          echo "  [tools] Deferred loading: core=${_CORE_TOOLS} (ToolSearch for others)"
        fi
      fi
    fi
    # ── US-339: Programmatic tool calling (code_execution_20250825) ──────────
    # Check if model supports programmatic tool calling and user enabled it.
    # Sonnet 4.6+ and Opus 4.6+ support code_execution. Haiku does not.
    _PROG_TOOLS_ENABLED=false
    if [[ "${SPIRAL_PROGRAMMATIC_TOOLS:-auto}" != "false" ]]; then
      _supports_code_exec=false
      if [[ -n "$EFFECTIVE_MODEL" ]]; then
        # Check if model is Sonnet 4.6+, Opus 4.6+, or claude-4-6
        if [[ "$EFFECTIVE_MODEL" =~ (sonnet-4\.6|opus-4\.6|claude-4\.6|claude-4-6) ]]; then
          _supports_code_exec=true
        fi
      fi
      if [[ "$_supports_code_exec" == "true" ]]; then
        _PROG_TOOLS_ENABLED=true
        echo "  [prog-tools] Enabled: code_execution_20250825 (model=$EFFECTIVE_MODEL supports programmatic tool calling)"
        log_ralph_event "programmatic_tools_enabled" "\"story_id\":\"$NEXT_STORY\",\"model\":\"$EFFECTIVE_MODEL\""
      elif [[ "${SPIRAL_PROGRAMMATIC_TOOLS:-auto}" == "true" ]]; then
        echo "  [prog-tools] WARN: Requested but model=$EFFECTIVE_MODEL does not support code_execution (requires Sonnet/Opus 4.6+)"
        log_ralph_event "programmatic_tools_unsupported" "\"story_id\":\"$NEXT_STORY\",\"model\":\"$EFFECTIVE_MODEL\",\"reason\":\"model_not_compatible\""
      fi
    fi
    # ── US-392: Interleaved thinking beta header for claude-4 models ─────────
    # When enabled, add anthropic-beta: interleaved-thinking-2025-05-14 header.
    # This enables iterative reasoning throughout the implementation workflow.
    # Supported on claude-opus-4-6 and claude-sonnet-4-6 only.
    if [[ "${SPIRAL_INTERLEAVED_THINKING:-false}" == "true" ]]; then
      _supports_interleaved=false
      if [[ -n "$EFFECTIVE_MODEL" ]]; then
        # Check if model is Sonnet 4.6+ or Opus 4.6+
        if [[ "$EFFECTIVE_MODEL" =~ (sonnet-4\.6|opus-4\.6) ]]; then
          _supports_interleaved=true
        fi
      fi
      if [[ "$_supports_interleaved" == "true" ]]; then
        _CACHE_BETAS="interleaved-thinking-2025-05-14"
        echo "  [thinking] Interleaved thinking enabled (model=$EFFECTIVE_MODEL, budget=${SPIRAL_THINKING_BUDGET_TOKENS} tokens)"
        log_ralph_event "interleaved_thinking_enabled" "\"story_id\":\"$NEXT_STORY\",\"model\":\"$EFFECTIVE_MODEL\",\"budget_tokens\":${SPIRAL_THINKING_BUDGET_TOKENS}"
      else
        echo "  [thinking] WARN: Interleaved thinking requested but model=$EFFECTIVE_MODEL does not support it (requires Sonnet/Opus 4.6+)"
        log_ralph_event "interleaved_thinking_unsupported" "\"story_id\":\"$NEXT_STORY\",\"model\":\"$EFFECTIVE_MODEL\",\"reason\":\"model_not_compatible\""
      fi
    fi
    # ── US-253: emit R→I phase transition telemetry ─────────────────────────
    _TELEM_I_START_MS=$(date +%s%3N 2>/dev/null || echo 0)
    _TELEM_R_DUR=0
    [[ "$_TELEM_I_START_MS" -gt 0 && "$_TELEM_R_START_MS" -gt 0 ]] &&
      _TELEM_R_DUR=$((_TELEM_I_START_MS - _TELEM_R_START_MS))
    declare -f emit_agent_telemetry >/dev/null 2>&1 &&
      emit_agent_telemetry "R" "I" "$_TELEM_R_DUR" 0
    # Unset CLAUDECODE to allow nested Claude Code invocation from within an active session
    _CLAUDE_TMP="${SPIRAL_SCRATCH_DIR}/_claude_raw_$$.tmp"
    mkdir -p "${SPIRAL_SCRATCH_DIR}"
    # ── US-261: local-only policy — skip cloud entirely, use Ollama directly ─────
    if [[ "${SPIRAL_LOCAL_FALLBACK_POLICY:-}" == "local-only" ]]; then
      apply_local_fallback_policy "local-only policy: bypassing cloud" "$_RL_TMP" && _OLLAMA_USED=1 || true
    else
      # ── US-397: Emit OTel gen_ai.content.prompt Event before API call ────────────
      # Wrapped in fire-and-forget block — observability must never kill the story
      if [[ "${SPIRAL_OTEL_ENABLED:-false}" == "true" ]]; then
        {
          "${SPIRAL_PYTHON:-python3}" lib/observability/otel_content_events.py emit-prompt \
            --system-prompt "$RALPH_SYSTEM_PROMPT" \
            --user-prompt "$RALPH_USER_PROMPT" \
            --model "${EFFECTIVE_MODEL:-unknown}" \
            --scratch-dir "$SPIRAL_SCRATCH_DIR" 2>/dev/null
        } || true
      fi
      # Write prompts to temp files via printf builtin — avoids ARG_MAX on Windows when
      # file context is large (printf is a bash builtin, no exec() call, no arg length limit).
      _USER_PROMPT_FILE="${SPIRAL_SCRATCH_DIR}/_user_prompt_$$.txt"
      _SYS_PROMPT_FILE="${SPIRAL_SCRATCH_DIR}/_sys_prompt_$$.txt"
      printf '%s' "$RALPH_USER_PROMPT" > "$_USER_PROMPT_FILE"
      printf '%s' "$RALPH_SYSTEM_PROMPT" > "$_SYS_PROMPT_FILE"
      (
        unset CLAUDECODE
        export SPIRAL_WORKER_ACTIVE=1 # Tell PreToolUse hook this is a Ralph worker
        "${_GNU_TIME_CMD[@]+"${_GNU_TIME_CMD[@]}"}" claude -p \
          $CLAUDE_MODEL_FLAG \
          $CLAUDE_EFFORT_FLAG \
          --append-system-prompt-file "$_SYS_PROMPT_FILE" \
          ${_CACHE_BETAS:+--betas "$_CACHE_BETAS"} \
          $_DEFERRED_TOOLS_FLAG \
          --allowedTools "Edit,Write,Read,Glob,Grep,Bash,Skill,Task,ToolSearch" \
          --max-turns 75 \
          --verbose \
          --output-format stream-json \
          --dangerously-skip-permissions \
          < "$_USER_PROMPT_FILE" 2>&1 | tee "$_CLAUDE_TMP" | node "$SCRIPT_DIR/stream-formatter.mjs"
      ) || true
      rm -f "$_USER_PROMPT_FILE" "$_SYS_PROMPT_FILE" 2>/dev/null || true
      # ── Connection failure detection for Ollama fallback (US-144) ──────────────
      # Detect ECONNREFUSED / ETIMEDOUT patterns — claude CLI unreachable.
      # After _CLAUDE_API_FAIL_STREAK >= 3, switch to Ollama for the current story.
      _CONN_HANDLED=0
      if [[ -n "${SPIRAL_OLLAMA_FALLBACK_MODEL:-}" ]]; then
        _TMP_SIZE=0
        [[ -f "$_CLAUDE_TMP" ]] && _TMP_SIZE=$(wc -c <"$_CLAUDE_TMP" 2>/dev/null || echo 0)
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
          echo "  [ollama] Claude unreachable (streak: $_CLAUDE_API_FAIL_STREAK/3)"
          log_spiral_event "claude_api_unreachable" \
            "\"story_id\":\"${NEXT_STORY:-}\",\"streak\":${_CLAUDE_API_FAIL_STREAK}"
          if [[ "$_CLAUDE_API_FAIL_STREAK" -ge 3 ]]; then
            echo "  [ollama] Streak >= 3 — switching to Ollama for ${NEXT_STORY:-}"
            mkdir -p "${SPIRAL_SCRATCH_DIR}"
            _OLLAMA_SYS_TMP="${SPIRAL_SCRATCH_DIR}/_ollama_sys_$$.tmp"
            _OLLAMA_USR_TMP="${SPIRAL_SCRATCH_DIR}/_ollama_usr_$$.tmp"
            printf '%s' "$RALPH_SYSTEM_PROMPT" >"$_OLLAMA_SYS_TMP"
            printf '%s' "$RALPH_USER_PROMPT" >"$_OLLAMA_USR_TMP"
            echo "  ─────── Ollama Output Start ───────"
            if call_ollama_fallback "$_OLLAMA_SYS_TMP" "$_OLLAMA_USR_TMP" | tee "$_RL_TMP"; then
              _OLLAMA_USED=1
              _CLAUDE_API_FAIL_STREAK=0
              echo "  [ollama] Ollama fallback succeeded"
            else
              _OLLAMA_USED=0
              >"$_RL_TMP"
              echo "  [ollama] Ollama fallback also failed — story will be retried later"
            fi
            echo "  ─────── Ollama Output End ─────────"
            rm -f "$_OLLAMA_SYS_TMP" "$_OLLAMA_USR_TMP"
          fi
          _CONN_HANDLED=1
        else
          # Successful connection — reset fail streak
          _CLAUDE_API_FAIL_STREAK=0
        fi
      fi
      # ── US-261: SPIRAL_LOCAL_FALLBACK_POLICY enforcement on cloud failure ─────────
      if [[ "$_CONN_HANDLED" -eq 0 && -n "${SPIRAL_LOCAL_FALLBACK_POLICY:-}" ]]; then
        _261_TMP_SIZE=0
        [[ -f "$_CLAUDE_TMP" ]] && _261_TMP_SIZE=$(wc -c <"$_CLAUDE_TMP" 2>/dev/null || echo 0)
        _261_CONN_FAIL=0
        if [[ "${_261_TMP_SIZE:-0}" -eq 0 ]]; then
          _261_CONN_FAIL=1
        elif grep -qiE 'ECONNREFUSED|ETIMEDOUT|connection refused|failed to connect|could not resolve host' \
          "$_CLAUDE_TMP" 2>/dev/null; then
          _261_CONN_FAIL=1
        fi
        if [[ "$_261_CONN_FAIL" -eq 1 ]]; then
          _261_ORIG_ERR="Claude unreachable (empty or connection-refused response)"
          rm -f "$_CLAUDE_TMP"
          apply_local_fallback_policy "${_261_ORIG_ERR}" "$_RL_TMP"
          _CONN_HANDLED=1
        fi
      fi
      # Move result to _RL_TMP (no-op if connection handler already removed _CLAUDE_TMP)
      mv "$_CLAUDE_TMP" "$_RL_TMP" 2>/dev/null || true
    fi
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
    fi
  fi

  # ── Record OTel metrics for token usage (US-232) ──────────────────────────
  # Record gen_ai.client.token.usage and gen_ai.client.operation.duration metrics
  # Includes model as an attribute for per-model analytics
  # Wrapped in fire-and-forget block — observability must never kill the story
  if [[ "$EFFECTIVE_TOOL" == "claude" && ("$_CALL_TOKENS_INPUT" -gt 0 || "$_CALL_TOKENS_OUTPUT" -gt 0) ]]; then
    _DURATION_MS=$(printf "%.0f" "$(echo "$_WALL_SEC * 1000" | bc 2>/dev/null || echo 0)")
    _OTEL_MODEL="${EFFECTIVE_MODEL:-unknown}"
    {
      "${SPIRAL_PYTHON:-python3}" lib/observability/otel_metrics.py record-tokens \
        --story-id "$NEXT_STORY" \
        --phase I \
        --input-tokens "$_CALL_TOKENS_INPUT" \
        --output-tokens "$_CALL_TOKENS_OUTPUT" \
        --duration-ms "$_DURATION_MS" \
        --model "$_OTEL_MODEL" \
        --scratch-dir "$SPIRAL_SCRATCH_DIR" 2>/dev/null
    } || true
  fi

  # ── US-397: Emit OTel gen_ai.content.completion Event after API call ────────────
  # Extract completion text from stream and emit it
  if [[ "$EFFECTIVE_TOOL" == "claude" && -f "$_RL_TMP" && "${SPIRAL_OTEL_ENABLED:-false}" == "true" ]]; then
    _COMPLETION_TEXT=$(
      python3 - "$_RL_TMP" <<'COMPLETION_EXTRACTOR_EOF'
import sys, json
parts = []
try:
    with open(sys.argv[1], encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get('type') == 'assistant':
                    msg = obj.get('message', obj)
                    for block in msg.get('content', []):
                        if block.get('type') == 'text':
                            parts.append(block.get('text', ''))
            except Exception:
                pass
except Exception:
    pass
print('\n'.join(parts))
COMPLETION_EXTRACTOR_EOF
      2>/dev/null || true
    )
    if [[ -n "$_COMPLETION_TEXT" ]]; then
      # Fire-and-forget — observability must never kill the story
      {
        "${SPIRAL_PYTHON:-python3}" lib/observability/otel_content_events.py emit-completion \
          --completion "$_COMPLETION_TEXT" \
          --model "${EFFECTIVE_MODEL:-unknown}" \
          --scratch-dir "$SPIRAL_SCRATCH_DIR" 2>/dev/null
      } || true
    fi
  fi

  # ── Extract Phase I diagnosis block (US-244) ─────────────────────────────
  # Parse assistant text messages from stream-json; look for the required
  # ## Current State / ## Problem Identified / ## Planned Changes headers.
  if [[ "$EFFECTIVE_TOOL" == "claude" && -f "$_RL_TMP" ]]; then
    _DIAG_TEXT=$(
      python3 - "$_RL_TMP" <<'DIAG_EXTRACTOR_EOF'
import sys, json
parts = []
try:
    with open(sys.argv[1], encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get('type') == 'assistant':
                    msg = obj.get('message', obj)
                    for block in msg.get('content', []):
                        if block.get('type') == 'text':
                            parts.append(block.get('text', ''))
            except Exception:
                pass
except Exception:
    pass
print('\n'.join(parts))
DIAG_EXTRACTOR_EOF
      2>/dev/null || true
    )
    if echo "$_DIAG_TEXT" | grep -q "## Current State" &&
      echo "$_DIAG_TEXT" | grep -qiE "## Problem( Identified)?$|## Problem Identified" &&
      echo "$_DIAG_TEXT" | grep -q "## Planned Changes"; then
      # Capture the diagnosis block (from ## Current State through ## Planned Changes section)
      _PHASE_I_DIAGNOSIS_BLOCK=$(echo "$_DIAG_TEXT" |
        awk '/## Current State/{found=1} found{print} /## Planned Changes/{p=1} p && /^##/ && !/## Planned Changes/{exit}' |
        head -80)
      echo "  [diagnosis] Diagnosis block found ($(echo "$_PHASE_I_DIAGNOSIS_BLOCK" | wc -l) lines)"
    else
      echo "  [diagnosis] No diagnosis block in Phase I output"
    fi

    # ── Allowlist scan: check LLM bash tool_use for violations (US-243) ─────
    # Scan stream-json for Bash tool_use commands matching the deny list.
    # Violations are logged to .spiral/security-events.log (non-blocking audit).
    if declare -f allowlist_scan_stream_json >/dev/null 2>&1; then
      _AL_VIOLATIONS=$(allowlist_scan_stream_json "$_RL_TMP" "I" "${NEXT_STORY:-}" 2>/dev/null || echo 0)
      if [[ "${_AL_VIOLATIONS:-0}" -gt 0 ]]; then
        echo "  [allowlist] ${_AL_VIOLATIONS} policy violation(s) logged for phase I (see .spiral/security-events.log)"
        log_ralph_event "allowlist_violation" \
          "\"story_id\":\"${NEXT_STORY:-}\",\"phase\":\"I\",\"count\":${_AL_VIOLATIONS}"
      fi
    fi

    # ── Tool param validation: semantic check of LLM bash tool_use args (US-249) ─
    # Validates parameters for git/python/bats/jq/curl against .spiral/tool-schema.json.
    # Invalid parameters are logged to checkpoint _toolErrors (non-blocking audit).
    if declare -f scan_stream_json_tool_params >/dev/null 2>&1; then
      _TP_ERRORS=$(scan_stream_json_tool_params "$_RL_TMP" "${NEXT_STORY:-}" 2>/dev/null || echo 0)
      if [[ "${_TP_ERRORS:-0}" -gt 0 ]]; then
        echo "  [tool-validate] ${_TP_ERRORS} tool parameter error(s) logged for phase I (see checkpoint _toolErrors)"
        log_ralph_event "tool_param_errors" \
          "\"storyId\":\"${NEXT_STORY:-}\",\"phase\":\"I\",\"count\":${_TP_ERRORS}"
      fi
    fi
  fi

  rm -f "$_RL_TMP"
  # ── US-253: emit I→V phase transition telemetry ─────────────────────────
  _TELEM_V_START_MS=$(date +%s%3N 2>/dev/null || echo 0)
  _TELEM_I_DUR=0
  [[ "$_TELEM_V_START_MS" -gt 0 && "$_TELEM_I_START_MS" -gt 0 ]] &&
    _TELEM_I_DUR=$((_TELEM_V_START_MS - _TELEM_I_START_MS))
  declare -f emit_agent_telemetry >/dev/null 2>&1 &&
    emit_agent_telemetry "I" "V" "$_TELEM_I_DUR" 0

  # ── Store diagnosis block in prd.json (US-244) ──────────────────────────────
  if [[ -n "$_PHASE_I_DIAGNOSIS_BLOCK" ]]; then
    $JQ --arg block "$_PHASE_I_DIAGNOSIS_BLOCK" \
      '(.userStories[] | select(.id == "'"$NEXT_STORY"'") | ._phaseI.diagnosisBlock) = $block' \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
    echo "  [diagnosis] Block stored in checkpoint for $NEXT_STORY"
  fi

  # ── Store context masking stats in prd.json (US-241) ─────────────────────
  # _OBS_TOKENS_BEFORE/AFTER are cumulative token estimates across all retries.
  # Only write when masking was active (i.e., at least one retry occurred).
  if [[ "${_OBS_TOKENS_BEFORE:-0}" -gt 0 ]]; then
    _ctx_reduction_pct=$(((_OBS_TOKENS_BEFORE - _OBS_TOKENS_AFTER) * 100 / (_OBS_TOKENS_BEFORE + 1)))
    $JQ --argjson ctxstats \
      "{\"tokensBeforeMasking\":${_OBS_TOKENS_BEFORE},\"tokensAfterMasking\":${_OBS_TOKENS_AFTER},\"reductionPct\":${_ctx_reduction_pct},\"contextWindow\":${SPIRAL_CONTEXT_WINDOW:-10}}" \
      '(.userStories[] | select(.id == "'"$NEXT_STORY"'") | ._contextStats) = $ctxstats' \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
    echo "  [context] Stats stored: before=${_OBS_TOKENS_BEFORE}T after=${_OBS_TOKENS_AFTER}T (${_ctx_reduction_pct}% saved)"
  fi

  # ── Parse resource accounting output (US-158) ──────────────────────────────
  if [[ -s "$_RESOURCE_TMP" ]]; then
    read _WALL_SEC _USER_CPU_S _SYS_CPU_S _PEAK_RSS_KB 2>/dev/null <"$_RESOURCE_TMP" || true
    rm -f "$_RESOURCE_TMP"
  fi
  _WALL_SEC="${_WALL_SEC:-0}"
  _USER_CPU_S="${_USER_CPU_S:-0}"
  _SYS_CPU_S="${_SYS_CPU_S:-0}"
  _PEAK_RSS_KB="${_PEAK_RSS_KB:-0}"

  # ── Post-story OOM guard (US-158) ───────────────────────────────────────────
  if [[ "${SPIRAL_WORKER_MEMORY_LIMIT:-0}" -gt 0 &&
    "${_PEAK_RSS_KB:-0}" -gt 0 ]] 2>/dev/null; then
    if [[ "${_PEAK_RSS_KB}" -gt "${SPIRAL_WORKER_MEMORY_LIMIT}" ]] 2>/dev/null; then
      echo "  [memory] WARNING: Story $NEXT_STORY peak RSS ${_PEAK_RSS_KB} KB exceeded limit ${SPIRAL_WORKER_MEMORY_LIMIT} KB"
      log_spiral_event "oom_threshold_exceeded" \
        "\"story_id\":\"${NEXT_STORY}\",\"peak_rss_kb\":${_PEAK_RSS_KB},\"limit_kb\":${SPIRAL_WORKER_MEMORY_LIMIT}" 2>/dev/null || true
      type spiral_log_low_power &>/dev/null &&
        spiral_log_low_power "ralph: OOM threshold exceeded for $NEXT_STORY (${_PEAK_RSS_KB}KB > ${SPIRAL_WORKER_MEMORY_LIMIT}KB)"
    fi
  fi

  # ── Accumulate per-story token cost ───────────────────────────────────────
  _STORY_CUMULATIVE_USD=0
  if [[ "$_CALL_TOKENS_INPUT" -gt 0 || "$_CALL_TOKENS_OUTPUT" -gt 0 ]]; then
    _STORY_CUMULATIVE_USD=$(accumulate_story_cost "$NEXT_STORY" "$_CALL_TOKENS_INPUT" "$_CALL_TOKENS_OUTPUT" 0 0 2>/dev/null || echo 0)
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
    # ── US-253: emit V→C phase transition telemetry ─────────────────────────
    if declare -f emit_agent_telemetry >/dev/null 2>&1; then
      _TELEM_C_MS=$(date +%s%3N 2>/dev/null || echo 0)
      _TELEM_V_DUR=0
      [[ "$_TELEM_C_MS" -gt 0 && "$_TELEM_V_START_MS" -gt 0 ]] &&
        _TELEM_V_DUR=$((_TELEM_C_MS - _TELEM_V_START_MS))
      emit_agent_telemetry "V" "C" "$_TELEM_V_DUR" 1
    fi
    echo ""
    echo "  [done] Story completed: $STORY_TITLE"

    # ── Diagnosis block gate (US-244) ─────────────────────────────────────────
    # Require workers to output ## Current State / ## Problem Identified /
    # ## Planned Changes before making file edits.  Skip when env var is set
    # (useful for pure-research stories that produce no file changes).
    if [[ -z "$_PHASE_I_DIAGNOSIS_BLOCK" && "${SPIRAL_SKIP_DIAGNOSIS_CHECK:-false}" != "true" ]]; then
      echo "  [diagnosis] WARNING: Story passed but no diagnosis block found — re-prompting"
      $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" \
        "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
      $JQ --arg reason 'DIAGNOSIS_BLOCK_MISSING: Diagnosis block required before making changes. Please output your diagnosis first.

Before making ANY file edits, output a diagnosis block with these exact headers:

## Current State
[describe the relevant current state of the code]

## Problem Identified
[what you are solving for this story]

## Planned Changes
[bullet list of specific files and changes you will make]

Output this block as plain text BEFORE calling Edit, Write, or any Bash command that modifies files.' \
        '(.userStories[] | select(.id == "'"$NEXT_STORY"'") | ._failureReason) = $reason' \
        "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
      increment_retry "$NEXT_STORY"
      RETRY_NOW=$(get_retry_count "$NEXT_STORY")
      log_ralph_event "diagnosis_block_missing" \
        "\"storyId\":\"$NEXT_STORY\",\"retryCount\":$RETRY_NOW"
      append_result "reject"
      echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
      echo "FAILED diagnosis-block gate: $STORY_TITLE (ID: $NEXT_STORY) — no diagnosis block found — attempt $RETRY_NOW/$MAX_RETRIES" >>"$PROGRESS_FILE"
      echo "" >>"$PROGRESS_FILE"
      STORIES_COMPLETED=$((STORIES_COMPLETED - 1)) # undo the increment above
      continue
    fi
    # ── End diagnosis block gate ───────────────────────────────────────────────

    # ── Phase I.5 (REVIEW): LLM self-review gate (US-145) ──────────────────
    # Send story spec + git diff to Claude haiku for structured code review.
    # Skip when SPIRAL_SKIP_SELF_REVIEW=true or when retries exceed MAX_RETRIES/2
    # (to avoid burning tokens on stories already deep in retry chain).
    if [[ "${SPIRAL_SKIP_SELF_REVIEW:-false}" != "true" ]]; then
      _REVIEW_SKIP_THRESHOLD=$((MAX_RETRIES / 2))
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
        $JQ --arg sid "$NEXT_STORY" --arg reason "oversized_diff: produced ${LAST_DIFF_LINES} lines but limit is ${SPIRAL_MAX_DIFF_LINES}. Keep total insertions+deletions under ${SPIRAL_MAX_DIFF_LINES} lines." \
          '(.userStories[] | select(.id == $sid) | ._failureReason) = $reason' "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
        accumulate_anti_pattern "oversized_diff"
        increment_retry "$NEXT_STORY"
        RETRY_NOW=$(get_retry_count "$NEXT_STORY")
        echo "[retry] $NEXT_STORY attempt $RETRY_NOW/$MAX_RETRIES (diff size gate failed: ${LAST_DIFF_LINES} lines)"
        append_result "reject"
        echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
        echo "FAILED diff-guard: $STORY_TITLE (ID: $NEXT_STORY) — ${LAST_DIFF_LINES} lines > ${SPIRAL_MAX_DIFF_LINES} limit — attempt $RETRY_NOW/$MAX_RETRIES" >>"$PROGRESS_FILE"
        echo "" >>"$PROGRESS_FILE"
        continue
      fi
      if ! check_scope_guard "$NEXT_STORY"; then
        echo "  [scope-guard] Unstaging changes and aborting story"
        do_story_reset "$PRE_STORY_SHA"
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
        $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason) = \"scope_guard_violation\"" "$PRD_FILE" >"${PRD_FILE}.tmp"
        mv "${PRD_FILE}.tmp" "$PRD_FILE"
        increment_retry "$NEXT_STORY"
        RETRY_NOW=$(get_retry_count "$NEXT_STORY")
        echo "[retry] $NEXT_STORY attempt $RETRY_NOW/$MAX_RETRIES (scope guard failed)"
        append_result "reject"
        echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
        echo "FAILED scope-guard: $STORY_TITLE (ID: $NEXT_STORY) — out-of-scope files detected — attempt $RETRY_NOW/$MAX_RETRIES" >>"$PROGRESS_FILE"
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
        _adr_script="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)/lib/observability/generate_adr.py"
        _python_cmd="${SPIRAL_PYTHON:-python3}"
        if [[ -f "$_adr_script" ]] && command -v "$_python_cmd" &>/dev/null; then
          echo "  [adr] Generating ADR for $NEXT_STORY..."
          _adr_out=$("$_python_cmd" "$_adr_script" \
            --story-id "$NEXT_STORY" \
            --prd "$PRD_FILE" \
            --output-dir "docs/decisions" \
            --model "${SPIRAL_ADR_MODEL:-haiku}" \
            2>&1) || true
          # _adr_out last line is the file path when exit 0; warn on empty
          _adr_path
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
      # Record pre-commit SHA in undo log before committing (US-239)
      if type undo_log_record &>/dev/null; then
        _PRE_COMMIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
        [[ -n "$_PRE_COMMIT_SHA" ]] && undo_log_record "$NEXT_STORY" "git_commit" \
          "pre-commit:$_PRE_COMMIT_SHA" "git reset --hard $_PRE_COMMIT_SHA"
      fi
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

      # Finalize story branch: merge to base or push for PR (US-157)
      finalize_story_branch "$NEXT_STORY" "$COMMIT_SHA"

      # When no branch prefix is configured, finalize_story_branch is a no-op,
      # so clean up the undo log here instead (US-239)
      if [[ -z "${SPIRAL_BRANCH_PREFIX:-}" ]]; then
        type undo_log_cleanup &>/dev/null && undo_log_cleanup "$NEXT_STORY"
      fi

      append_result "keep" "$COMMIT_SHA"
      log_ralph_event "story_passed" "\"storyId\":\"$NEXT_STORY\",\"retryCount\":$(get_retry_count "$NEXT_STORY"),\"model\":\"${EFFECTIVE_MODEL:-sonnet}\""

      echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
      echo "Completed: $STORY_TITLE (ID: $NEXT_STORY) in ${STORY_DURATION}m" >>"$PROGRESS_FILE"
      echo "" >>"$PROGRESS_FILE"
    else
      echo "[rollback] Quality checks failed — reverting prd.json mark"

      # Generate AC evaluation report for Phase I partial victory handling (US-787)
      generate_ac_report "$NEXT_STORY" "$PRD_FILE"

      $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" >"${PRD_FILE}.tmp"
      mv "${PRD_FILE}.tmp" "$PRD_FILE"

      # Strategy 1: Accumulate failure approach as anti-pattern for next retry
      if [[ "${SPIRAL_ANTI_PATTERN_INJECT:-true}" == "true" ]]; then
        _AP_FAIL_REASON=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason // \"quality_gate_failed\"" \
          "$PRD_FILE" 2>/dev/null | tr -d '\r"\\' | head -c 200 || echo "quality_gate_failed")
        if [[ -n "$_AP_FAIL_REASON" ]]; then
          $JQ --arg sid "$NEXT_STORY" --arg note "$_AP_FAIL_REASON" \
            '(.userStories[] | select(.id == $sid) | ._antiPatterns) |= (. // []) + [$note]' \
            "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
        fi
      fi

      increment_retry "$NEXT_STORY"
      RETRY_NOW=$(get_retry_count "$NEXT_STORY")
      classify_failure_root_cause "${_AP_FAIL_REASON:-quality_gate_failed}"
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

    # Strategy 1: Accumulate "story not completed" as anti-pattern for next retry
    if [[ "${SPIRAL_ANTI_PATTERN_INJECT:-true}" == "true" ]]; then
      _AP_FAIL_REASON=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason // \"story_incomplete\"" \
        "$PRD_FILE" 2>/dev/null | tr -d '\r"\\' | head -c 200 || echo "story_incomplete")
      if [[ -n "$_AP_FAIL_REASON" ]]; then
        $JQ --arg sid "$NEXT_STORY" --arg note "$_AP_FAIL_REASON" \
          '(.userStories[] | select(.id == $sid) | ._antiPatterns) |= (. // []) + [$note]' \
          "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
      fi
    fi

    increment_retry "$NEXT_STORY"
    RETRY_NOW=$(get_retry_count "$NEXT_STORY")
    classify_failure_root_cause "${_AP_FAIL_REASON:-story_incomplete}"
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
