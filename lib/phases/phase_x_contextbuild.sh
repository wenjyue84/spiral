#!/usr/bin/env bash
# lib/phases/phase_x_contextbuild.sh — Phase X: CONTEXT BUILD (repo map)
#
# Builds per-story symbol maps from filesTouch entries. Parses exports,
# imports, test neighbors, callers, and dependency boundaries using Python
# stdlib (zero LLM cost). Results are written as pre-formatted markdown
# files in $SCRATCH_DIR and injected into Ralph's user prompt.
#
# Only runs when SPIRAL_REPO_MAP=true.
#
# Inputs:
#   $PRD_FILE, $REPO_ROOT
#
# Outputs:
#   $SCRATCH_DIR/_repo_map.json           — full structured data
#   $SCRATCH_DIR/_repo_map_<story_id>.md  — per-story markdown for prompt injection

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_context_build() {
  if [[ "${SPIRAL_REPO_MAP:-false}" != "true" ]]; then
    return 0
  fi

  local _repo_map_out="$SCRATCH_DIR/_repo_map.json"
  local _max_lines="${SPIRAL_REPO_MAP_MAX_LINES:-150}"
  local _x_ts
  _x_ts=$(date +%s)

  print_phase_banner "X" "CONTEXT BUILD — generating symbol maps for pending stories..."

  local _x_rc=0
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/context/repo_map.py" \
    --prd "$PRD_FILE" \
    --output "$_repo_map_out" \
    --repo-root "$REPO_ROOT" \
    --max-lines "$_max_lines" || _x_rc=$?

  local _x_dur=$(( $(date +%s) - _x_ts ))
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
