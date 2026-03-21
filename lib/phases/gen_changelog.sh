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

  # Validate CHANGELOG schema compliance (US-688)
  _validate_changelog_schema "$spiral_home" "$output_file"
  local _validate_rc=$?
  if [[ "$_validate_rc" -ne 0 ]]; then
    echo "[phase-g] Schema validation failed — rolling back CHANGELOG.md" >&2
    rm -f "$output_file"
    return 1
  fi

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

# _validate_changelog_schema: Run lib/validate_phase_g.py to validate CHANGELOG.md
#
# Calls validate_all_outputs() via the module CLI, logging results to
# .spiral/_phase_g_validation.json. Skips silently if Python is unavailable.
#
# Returns: 0 on pass or unavailable, 1 on schema violation
_validate_changelog_schema() {
  local spiral_home="$1"
  local changelog_path="$2"
  local python_bin="${SPIRAL_PYTHON:-python3}"
  local validate_script="${spiral_home}/lib/validate_phase_g.py"
  local pdoc_dir="${spiral_home}/.spiral/docs/api"
  local scratch_dir="${spiral_home}/.spiral"

  if [[ ! -f "$validate_script" ]]; then
    echo "[phase-g] WARNING: lib/validate_phase_g.py not found — skipping validation"
    return 0
  fi

  if ! command -v "$python_bin" &>/dev/null && ! $python_bin --version &>/dev/null 2>&1; then
    echo "[phase-g] WARNING: Python not available — skipping schema validation"
    return 0
  fi

  echo "[phase-g] Validating CHANGELOG schema..."
  if $python_bin "$validate_script" \
    --changelog "$changelog_path" \
    --pdoc-dir "$pdoc_dir" \
    --scratch-dir "$scratch_dir"; then
    echo "[phase-g] CHANGELOG schema validation passed"
    return 0
  else
    return 1
  fi
}

# Export functions for use in spiral.sh
export -f phase_gen_changelog
export -f _log_orphan_commits
export -f _validate_changelog_schema
