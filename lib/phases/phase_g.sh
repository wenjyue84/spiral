#!/usr/bin/env bash
# lib/phases/phase_g.sh — Phase G: CHANGELOG.md generation via git-cliff
#
# Orchestration stub for Phase G that generates CHANGELOG.md from story commits.
# Invokes git-cliff with .cliff.toml configuration to produce a structured changelog
# grouped by story ID, with commit messages and story titles from prd.json.
#
# Functions: run_phase_g
#
# Environment:
#   SPIRAL_HOME        — Project root (default: .)
#   SPIRAL_GIT_CLIFF_BIN — Path to git-cliff binary (default: git-cliff)
#   SPIRAL_PYTHON      — Python interpreter (default: python3)

set -euo pipefail

# run_phase_g: Main Phase G orchestration
#
# Coordinates CHANGELOG.md generation via git-cliff and logs any orphan commits.
# Returns 0 on success, 1 on failure.
run_phase_g() {
  local spiral_home="${SPIRAL_HOME:-.}"

  # Source the underlying changelog generation module
  if [[ ! -f "${spiral_home}/lib/phases/gen_changelog.sh" ]]; then
    echo "[phase-g] ERROR: gen_changelog.sh not found at ${spiral_home}/lib/phases/gen_changelog.sh" >&2
    return 1
  fi

  source "${spiral_home}/lib/phases/gen_changelog.sh"

  echo "[phase-g] Starting Phase G: CHANGELOG generation"

  # Invoke the changelog generation function
  if phase_gen_changelog; then
    echo "[phase-g] Phase G completed successfully"
    return 0
  else
    echo "[phase-g] Phase G failed" >&2
    return 1
  fi
}

# Export function for use in spiral.sh
export -f run_phase_g
