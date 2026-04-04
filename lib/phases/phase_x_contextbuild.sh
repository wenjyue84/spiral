#!/usr/bin/env bash
# lib/phases/phase_x_contextbuild.sh — Phase X: CONTEXT BUILD (repo map + overflow guard)
#
# Builds per-story symbol maps from filesTouch entries. Parses exports,
# imports, test neighbors, callers, and dependency boundaries using Python
# stdlib (zero LLM cost). Results are written as pre-formatted markdown
# files in $SCRATCH_DIR and injected into Ralph's user prompt.
#
# Also applies context overflow guard to detect and trim stories that
# exceed SPIRAL_CONTEXT_BUDGET (default 180000 tokens).
#
# Only runs when SPIRAL_REPO_MAP=true (repo map part is optional; guard always runs).
#
# Inputs:
#   $PRD_FILE, $REPO_ROOT
#
# Outputs:
#   $SCRATCH_DIR/_repo_map.json           — full structured data
#   $SCRATCH_DIR/_repo_map_<story_id>.md  — per-story markdown for prompt injection
#   $PRD_FILE (updated)                   — stories with _context_trimmed field set

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_context_build() {
  local _x_ts
  _x_ts=$(date +%s)

  # Apply context overflow guard to all stories in PRD
  echo "  [X] Applying context overflow guard to stories..."
  local _guard_rc=0
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/context/apply_overflow_guard.py" \
    --prd "$PRD_FILE" \
    --budget "${SPIRAL_CONTEXT_BUDGET:-180000}" || _guard_rc=$?

  if [[ "$_guard_rc" -ne 0 ]]; then
    echo "  [X] WARNING: Overflow guard failed (rc=$_guard_rc) — proceeding without trimming"
  fi

  # Optional: Build repo maps (only when enabled)
  if [[ "${SPIRAL_REPO_MAP:-false}" != "true" ]]; then
    local _x_dur=$(($(date +%s) - _x_ts))
    _PHASE_DUR_X=$_x_dur
    echo "  [X] Context build complete (overflow guard only, ${_x_dur}s)"
    return 0
  fi

  local _repo_map_out="$SCRATCH_DIR/_repo_map.json"
  local _max_lines="${SPIRAL_REPO_MAP_MAX_LINES:-150}"

  print_phase_banner "X" "CONTEXT BUILD — generating symbol maps for pending stories..."

  local _x_rc=0
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/context/repo_map.py" \
    --prd "$PRD_FILE" \
    --output "$_repo_map_out" \
    --repo-root "$REPO_ROOT" \
    --max-lines "$_max_lines" || _x_rc=$?

  local _x_dur=$(($(date +%s) - _x_ts))
  _PHASE_DUR_X=$_x_dur

  if [[ "$_x_rc" -eq 0 && -f "$_repo_map_out" ]]; then
    local _x_count
    _x_count=$("$JQ" 'keys | length' "$_repo_map_out" 2>/dev/null || echo "?")
    echo "  [X] Context build complete — $_x_count story maps ready (${_x_dur}s)"
    log_spiral_event "phase_end" "\"phase\":\"X\",\"iteration\":$SPIRAL_ITER,\"stories\":$_x_count,\"duration\":$_x_dur"
  else
    echo "  [X] WARNING: Context build failed (rc=$_x_rc) — proceeding without repo map"
  fi
}
