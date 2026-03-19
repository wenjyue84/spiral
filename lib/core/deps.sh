#!/usr/bin/env bash
# lib/core/deps.sh — SPIRAL dependency resolution: jq binary
#
# Functions: resolve_jq
# Globals set: JQ
# Globals used: SPIRAL_HOME, REPO_ROOT, ERR_MISSING_DEP

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# ── jq resolution ─────────────────────────────────────────────────────────────
# Checks system jq, then Windows-bundled jq.exe variants. Sets JQ global.
# Exits with ERR_MISSING_DEP if jq is not found anywhere.
resolve_jq() {
  local ralph_jq_dir="$SPIRAL_HOME/ralph"
  if command -v jq &>/dev/null; then
    JQ="jq"
  elif [[ -f "$ralph_jq_dir/jq.exe" ]]; then
    JQ="$ralph_jq_dir/jq.exe"
  elif [[ -f "$REPO_ROOT/scripts/ralph/jq.exe" ]]; then
    JQ="$REPO_ROOT/scripts/ralph/jq.exe"
  else
    echo "[spiral] ERROR: jq not found. Install with: choco install jq"
    exit $ERR_MISSING_DEP
  fi
}
