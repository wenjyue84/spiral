#!/usr/bin/env bash
# lib/phases/gen_changelog.sh — Phase G: CHANGELOG generation via git-cliff
#
# Functions: phase_gen_changelog
# Integrates git-cliff to generate CHANGELOG.md with conventional commit sections
# (feat/fix/docs/refactor). Parses commit messages for story IDs (US-NNN, UT-NNN)
# and logs orphan commits (no story ID) to .spiral/phase_g_warnings.log.

set -euo pipefail

# phase_gen_changelog: Generate CHANGELOG.md via git-cliff and log orphan commits
#
# Uses SPIRAL_GIT_CLIFF_BIN (default: git-cliff) for the binary path.
# Validates binary existence before execution.
# Generates CHANGELOG.md in SPIRAL_HOME (project root).
# Scans git log for commits without story ID patterns and writes warnings.
#
# Returns: 0 on success, 1 on missing binary or config
phase_gen_changelog() {
  local cliff_bin="${SPIRAL_GIT_CLIFF_BIN:-git-cliff}"
  local spiral_home="${SPIRAL_HOME:-.}"
  local cliff_config="${spiral_home}/cliff.toml"
  local output_file="${spiral_home}/CHANGELOG.md"
  local warnings_file="${spiral_home}/.spiral/phase_g_warnings.log"

  # Validate git-cliff binary exists
  if ! command -v "$cliff_bin" &>/dev/null; then
    echo "[phase-g] ERROR: git-cliff binary not found at '${cliff_bin}'" >&2
    echo "[phase-g] Install with: cargo install git-cliff" >&2
    return 1
  fi

  # Validate cliff.toml config exists
  if [[ ! -f "$cliff_config" ]]; then
    echo "[phase-g] ERROR: cliff.toml not found at ${cliff_config}" >&2
    return 1
  fi

  echo "[phase-g] Generating CHANGELOG.md via ${cliff_bin}..."

  # Run git-cliff to generate CHANGELOG.md
  "$cliff_bin" --config "$cliff_config" --output "$output_file"

  if [[ ! -f "$output_file" ]]; then
    echo "[phase-g] ERROR: CHANGELOG.md was not created" >&2
    return 1
  fi

  echo "[phase-g] CHANGELOG.md generated at ${output_file}"

  # Detect orphan commits (no story ID pattern US-NNN or UT-NNN)
  _log_orphan_commits "$spiral_home" "$warnings_file"

  return 0
}

# _log_orphan_commits: Find commits without story ID patterns and log them
#
# Scans git log for commits whose full message (subject + body) does not
# contain US-NNN or UT-NNN patterns. Writes hash + subject to warnings file.
_log_orphan_commits() {
  local spiral_home="$1"
  local warnings_file="$2"

  mkdir -p "$(dirname "$warnings_file")"

  # Clear previous warnings
  : >"$warnings_file"

  local orphan_count=0

  # Read git log: short hash and full commit message
  while IFS= read -r line; do
    local hash subject
    hash="${line%% *}"
    subject="${line#* }"

    # Check if full commit message (subject + body) contains story ID
    local full_message
    full_message=$(git log -1 --format="%B" "$hash" 2>/dev/null || echo "")

    if ! echo "$full_message" | grep -qE '(US|UT)-[0-9]+'; then
      echo "${hash} ${subject}" >>"$warnings_file"
      orphan_count=$((orphan_count + 1))
    fi
  done < <(git log --oneline --no-merges 2>/dev/null || true)

  if [[ "$orphan_count" -gt 0 ]]; then
    echo "[phase-g] WARNING: ${orphan_count} orphan commits (no story ID) logged to ${warnings_file}"
  else
    echo "[phase-g] All commits have story IDs"
  fi
}

# Export functions for use in spiral.sh
export -f phase_gen_changelog
export -f _log_orphan_commits
