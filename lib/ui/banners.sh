#!/usr/bin/env bash
# lib/ui/banners.sh — SPIRAL UI: phase banners, iteration summary, and structured logging
#
# Functions: print_phase_banner, print_iter_summary_banner, log_msg
# Globals used: _USE_COLOR, _C_*, JQ, REPO_ROOT, SPIRAL_HOME, SPIRAL_PYTHON,
#               SPIRAL_MAX_RETRIES, SPIRAL_LOG_LEVEL
#
# Source order: after lib/core/config.sh (colors already set via setup_color_output)

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# Helper: print a colored phase banner to stdout
# Usage: print_phase_banner "R" "RESEARCH"
print_phase_banner() {
  local phase="$1" label="$2"
  local color=""
  case "$phase" in
    R | T) color="$_C_BLUE" ;;
    I) color="$_C_YELLOW" ;;
    V) color="$_C_GREEN" ;;
    S | M | C | A | G) color="$_C_CYAN" ;;
    *) color="" ;;
  esac
  if [[ "$_USE_COLOR" -eq 1 ]]; then
    printf "\n  ${color}▓▓ Phase %s: %s ▓▓${_C_RESET}\n" "$phase" "$label"
  else
    echo ""
    echo "  [Phase $phase] $label"
  fi
}

# ── US-313: Print iteration summary banner after Phase C ────────────────────
# Usage: print_iter_summary_banner <iter> <done> <pending> <total> <iter_minutes> <iter_duration>
# Prints a bordered ASCII box with story stats, cost, and next action.
print_iter_summary_banner() {
  local iter="$1" done="$2" pending="$3" total="$4"
  local iter_minutes="${5:-0}" iter_duration="${6:-0}"
  local failed=0 actual_pending="$pending"
  # Count exhausted stories (retry count >= max retries)
  if [[ -f "$REPO_ROOT/retry-counts.json" ]]; then
    failed=$("$JQ" "[to_entries[] | select(.value >= ${SPIRAL_MAX_RETRIES:-3})] | length" \
      "$REPO_ROOT/retry-counts.json" 2>/dev/null || echo "0")
    actual_pending=$((pending > failed ? pending - failed : 0))
  fi
  # Extract cumulative cost from results.tsv
  local cost_str=""
  if [[ -f "$REPO_ROOT/results.tsv" ]]; then
    local _raw_cost
    _raw_cost=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/routing/cost_check.py" \
      --results "$REPO_ROOT/results.tsv" 2>/dev/null | head -1) || true
    cost_str=$(echo "$_raw_cost" | sed -nE 's/.*(\$[0-9]+\.[0-9]+).*/\1/p') || true
  fi
  echo ""
  if [[ "$_USE_COLOR" -eq 1 ]]; then
    printf "  ${_C_CYAN}┌─── Iteration %d complete ─────────────────────────────${_C_RESET}\n" "$iter"
    printf "  ${_C_CYAN}│${_C_RESET}  Stories: ${_C_GREEN}✓ %d passed${_C_RESET}  ${_C_RED}✗ %d failed${_C_RESET}  ${_C_YELLOW}⏳ %d pending${_C_RESET}\n" \
      "$done" "$failed" "$actual_pending"
    [[ -n "$cost_str" ]] && printf "  ${_C_CYAN}│${_C_RESET}  Est. cost: %s\n" "$cost_str"
    printf "  ${_C_CYAN}│${_C_RESET}  Duration:  %dm (%ds)\n" "$iter_minutes" "$iter_duration"
    if [[ "$pending" -eq 0 ]]; then
      printf "  ${_C_CYAN}│${_C_RESET}  ${_C_GREEN}COMPLETE: All stories passed${_C_RESET}\n"
    else
      printf "  ${_C_CYAN}│${_C_RESET}  Next: %d stories remain → starting iteration %d\n" \
        "$pending" "$((iter + 1))"
    fi
    printf "  ${_C_CYAN}└───────────────────────────────────────────────────────${_C_RESET}\n"
  else
    echo "  ┌─── Iteration $iter complete ─────────────────────────────"
    echo "  │  Stories: ✓ $done passed  ✗ $failed failed  ⏳ $actual_pending pending"
    [[ -n "$cost_str" ]] && echo "  │  Est. cost: $cost_str"
    echo "  │  Duration:  ${iter_minutes}m (${iter_duration}s)"
    if [[ "$pending" -eq 0 ]]; then
      echo "  │  COMPLETE: All stories passed"
    else
      echo "  │  Next: $pending stories remain → starting iteration $((iter + 1))"
    fi
    echo "  └───────────────────────────────────────────────────────"
  fi
  echo ""
}

# ── Structured logging: SPIRAL_LOG_LEVEL filtering (US-130) ──────────────────
# Accepts DEBUG / INFO / WARN / ERROR (case-insensitive; normalised to upper on read).
# Requires bash 4.0+ for associative arrays (already required by spiral.sh).
declare -A LOG_LEVELS=([DEBUG]=0 [INFO]=1 [WARN]=2 [ERROR]=3)

# Normalise SPIRAL_LOG_LEVEL to upper-case and validate.
SPIRAL_LOG_LEVEL="${SPIRAL_LOG_LEVEL^^}"
if [[ -z "${LOG_LEVELS[$SPIRAL_LOG_LEVEL]+x}" ]]; then
  echo "[spiral] WARNING: Unknown SPIRAL_LOG_LEVEL='$SPIRAL_LOG_LEVEL', defaulting to INFO" >&2
  SPIRAL_LOG_LEVEL="INFO"
fi
export SPIRAL_LOG_LEVEL

# log_msg LEVEL MESSAGE...
# Emits the message to stderr only when LEVEL >= SPIRAL_LOG_LEVEL.
# DEBUG messages include caller context (file:line) for traceability.
log_msg() {
  local lvl="${1^^}"
  shift
  # Default to INFO if level is unrecognised
  local lvl_num="${LOG_LEVELS[$lvl]:-1}"
  local threshold="${LOG_LEVELS[$SPIRAL_LOG_LEVEL]:-1}"
  if [[ "$lvl_num" -ge "$threshold" ]]; then
    if [[ "$lvl" == "DEBUG" ]]; then
      local caller_ctx="${BASH_SOURCE[1]:-spiral.sh}:${BASH_LINENO[0]:-0}"
      echo "[DEBUG] ($caller_ctx) $*" >&2
    elif [[ "$lvl" == "ERROR" && "$_USE_COLOR" -eq 1 ]]; then
      printf "${_C_RED}[ERROR]${_C_RESET} %s\n" "$*" >&2
    else
      echo "[$lvl] $*" >&2
    fi
  fi
}
