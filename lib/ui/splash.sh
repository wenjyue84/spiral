#!/usr/bin/env bash
# lib/ui/splash.sh — SPIRAL startup splash banner and UI dashboard registration
#
# Functions: print_spiral_splash, register_spiral_ui
# Globals used: PRD_FILE, REPO_ROOT, SPIRAL_HOME, MAX_SPIRAL_ITERS, RALPH_MAX_ITERS,
#               SPIRAL_CLI_MODEL, SPIRAL_MODEL_ROUTING, SPIRAL_RESEARCH_MODEL,
#               SPIRAL_VALIDATION_MODEL, SPIRAL_MERGE_MODEL, SPIRAL_FIRECRAWL_ENABLED,
#               RALPH_WORKERS, SKIP_RESEARCH, DRY_RUN, MONITOR_TERMINALS,
#               SPIRAL_SPECKIT_CONSTITUTION, SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE,
#               SPIRAL_FOCUS, SPIRAL_FOCUS_TAGS, SPIRAL_MAX_PENDING,
#               SPIRAL_MAX_RESEARCH_STORIES, SPIRAL_STORY_BATCH_SIZE, SPIRAL_COST_CEILING,
#               SPIRAL_LOW_POWER_MODE, TIME_LIMIT_MINS, SESSION_DEADLINE,
#               SPIRAL_RESEARCH_CACHE_TTL_HOURS, CAPACITY_LIMIT, SCRATCH_DIR,
#               DONE, TOTAL, PENDING, JQ, SPIRAL_UI_PORT

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# ── Print SPIRAL startup banner (ASCII box with run configuration) ────────────
print_spiral_splash() {
  prd_stats
  echo ""
  echo "  ╔══════════════════════════════════════════════╗"
  echo "  ║   SPIRAL — Self-iterating PRD Loop            ║"
  echo "  ╠══════════════════════════════════════════════╣"
  echo "  ║  PRD:         $PRD_FILE"
  echo "  ║  Stories:     $DONE/$TOTAL complete ($PENDING pending)"
  echo "  ║  Max iters:   $MAX_SPIRAL_ITERS"
  echo "  ║  Ralph iters: $RALPH_MAX_ITERS per phase"
  if [[ -n "$SPIRAL_CLI_MODEL" ]]; then
    echo "  ║  Model:       $SPIRAL_CLI_MODEL (cli override)"
  elif [[ "$SPIRAL_MODEL_ROUTING" == "auto" ]]; then
    echo "  ║  Model:       auto (haiku/sonnet/opus by complexity)"
  else
    echo "  ║  Model:       $SPIRAL_MODEL_ROUTING (config fixed)"
  fi
  echo "  ║  Phase models: R=$SPIRAL_RESEARCH_MODEL  S=$SPIRAL_VALIDATION_MODEL  M=$SPIRAL_MERGE_MODEL"
  if [[ "$SPIRAL_FIRECRAWL_ENABLED" -eq 1 ]]; then
    echo "  ║  Research:    $SPIRAL_RESEARCH_MODEL model + Firecrawl MCP"
  else
    echo "  ║  Research:    $SPIRAL_RESEARCH_MODEL model (WebFetch fallback)"
  fi
  [[ "$RALPH_WORKERS" -gt 1 ]] && echo "  ║  Workers:     $RALPH_WORKERS parallel (git worktrees)"
  [[ "$SKIP_RESEARCH" -eq 1 ]] && echo "  ║  Mode:        --skip-research (Phase R skipped)"
  [[ "$DRY_RUN" -eq 1 ]] && echo "  ║  Mode:        --dry-run (no API calls)"
  [[ "$MONITOR_TERMINALS" -eq 1 ]] && echo "  ║  Monitor:     terminal per worker (--monitor)"
  [[ -n "$SPIRAL_SPECKIT_CONSTITUTION" && -f "$REPO_ROOT/$SPIRAL_SPECKIT_CONSTITUTION" ]] &&
    echo "  ║  Spec-Kit:    constitution loaded"
  [[ "${SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE:-true}" == "false" ]] &&
    echo "  ║  Cache inv.:  disabled (SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE=false)"
  [[ -n "$SPIRAL_FOCUS" ]] && echo "  ║  Focus:       $SPIRAL_FOCUS"
  [[ -n "$SPIRAL_FOCUS_TAGS" ]] && echo "  ║  Focus tags:  $SPIRAL_FOCUS_TAGS"
  [[ "$SPIRAL_MAX_PENDING" -gt 0 ]] && echo "  ║  Max pending: $SPIRAL_MAX_PENDING incomplete stories"
  [[ "$SPIRAL_MAX_RESEARCH_STORIES" -gt 0 ]] && echo "  ║  Max research: $SPIRAL_MAX_RESEARCH_STORIES stories per iteration"
  [[ "$SPIRAL_STORY_BATCH_SIZE" -gt 0 ]] && echo "  ║  Batch size:  $SPIRAL_STORY_BATCH_SIZE stories per iteration"
  [[ -n "$SPIRAL_COST_CEILING" ]] && echo "  ║  Cost cap:    \$${SPIRAL_COST_CEILING} USD"
  [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]] && echo "  ║  Low power:   adaptive memory management enabled"
  if [[ "$TIME_LIMIT_MINS" -gt 0 ]]; then
    _DEADLINE_DISPLAY=$(date -d "@$SESSION_DEADLINE" +"%H:%M" 2>/dev/null ||
      date -r "$SESSION_DEADLINE" +"%H:%M" 2>/dev/null ||
      echo "~${TIME_LIMIT_MINS}m from now")
    echo "  ║  Time limit:  ${TIME_LIMIT_MINS}m (stops ~${_DEADLINE_DISPLAY})"
  fi
  [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]] && echo "  ║  Cache TTL:   ${SPIRAL_RESEARCH_CACHE_TTL_HOURS}h (research URL responses + Phase R output reuse)"
  echo "  ║  Capacity:    Phase R skipped when pending > $CAPACITY_LIMIT"
  echo "  ║  Scratch:     $SCRATCH_DIR"
  echo "  ╚══════════════════════════════════════════════╝"
  echo ""
}

# ── Register project with SPIRAL UI server and open dashboard ─────────────────
register_spiral_ui() {
  local _spiral_ui_port="${SPIRAL_UI_PORT:-5299}"
  local _ui_project_name
  _ui_project_name=$("$JQ" -r '.productName // empty' "$PRD_FILE" 2>/dev/null || true)
  if [[ -z "$_ui_project_name" ]]; then
    _ui_project_name=$(basename "$REPO_ROOT" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
  fi
  local _ui_base="http://localhost:${_spiral_ui_port}"
  local _ui_dash="${_ui_base}/${_ui_project_name}"

  # Register project with UI server (non-blocking; UI may not be running — ignore errors)
  if command -v curl &>/dev/null; then
    curl -sf -X POST "${_ui_base}/api/register-project" \
      -H "Content-Type: application/json" \
      -d "{\"name\":\"${_ui_project_name}\",\"root\":\"${REPO_ROOT}\"}" \
      >/dev/null 2>&1 || true
  fi

  # Open browser to project dashboard
  echo "  [UI] Dashboard: ${_ui_dash}"
  if command -v cmd.exe &>/dev/null; then
    cmd.exe /c start "" "${_ui_dash}" 2>/dev/null || true
  elif command -v xdg-open &>/dev/null; then
    xdg-open "${_ui_dash}" 2>/dev/null &
  elif command -v open &>/dev/null; then
    open "${_ui_dash}" 2>/dev/null || true
  fi
}
