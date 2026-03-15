#!/bin/bash
# SPIRAL Plugin System — Declarative plugin management with hook-based extension points
#
# Conventions:
#  - plugins/ directory at SPIRAL_HOME/plugins/
#  - Each plugin is a subdirectory: plugins/plugin-name/
#  - Each plugin MUST contain: plugin.toml (manifest)
#  - Hook scripts (executable bash files) named after hook points: pre-phase, post-phase, post-story, etc.
#
# plugin.toml format:
#   [plugin]
#   name = "plugin-name"
#   version = "1.0.0"
#   hooks = ["pre-phase", "post-phase"]
#   allowed_env = ["SLACK_WEBHOOK_URL"]  # optional; required env vars to validate
#
# Hook execution:
#  - Hook scripts receive story context as JSON on stdin
#  - Hook scripts run with 30-second timeout (SPIRAL_HOOK_TIMEOUT)
#  - Pre-phase hooks: non-zero exit aborts current story attempt
#  - Post-phase hooks: non-zero exit logged as warning, execution continues
#  - Plugin scripts have access to: SPIRAL_CURRENT_PHASE, SPIRAL_CURRENT_STORY_ID, etc.

set -euo pipefail

# ── Plugin discovery and validation ────────────────────────────────────────────
# Returns: 0 if valid, 1 if malformed or missing
validate_plugin_manifest() {
  local plugin_dir="$1"
  local plugin_toml="$plugin_dir/plugin.toml"

  if [[ ! -f "$plugin_toml" ]]; then
    echo "  [plugin] WARNING: $plugin_dir/plugin.toml not found — skipping" >&2
    return 1
  fi

  # Basic TOML validation: check for required fields
  if ! grep -q "^\[plugin\]" "$plugin_toml"; then
    echo "  [plugin] WARNING: $plugin_toml missing [plugin] section — skipping" >&2
    return 1
  fi

  if ! grep -q "^name = " "$plugin_toml"; then
    echo "  [plugin] WARNING: $plugin_toml missing name field — skipping" >&2
    return 1
  fi

  if ! grep -q "^version = " "$plugin_toml"; then
    echo "  [plugin] WARNING: $plugin_toml missing version field — skipping" >&2
    return 1
  fi

  if ! grep -q "^hooks = " "$plugin_toml"; then
    echo "  [plugin] WARNING: $plugin_toml missing hooks array — skipping" >&2
    return 1
  fi

  return 0
}

# ── Parse plugin.toml and extract fields ──────────────────────────────────────
# Usage: parse_plugin_manifest PLUGIN_DIR
# Sets global associative array: PLUGIN_MANIFEST[name], PLUGIN_MANIFEST[version], PLUGIN_MANIFEST[hooks]
declare -gA PLUGIN_MANIFEST
parse_plugin_manifest() {
  local plugin_dir="$1"
  local plugin_toml="$plugin_dir/plugin.toml"

  PLUGIN_MANIFEST=()

  # Extract name (quoted string)
  local name
  name=$(grep "^name = " "$plugin_toml" | sed 's/^name = "\(.*\)"$/\1/' || true)
  [[ -n "$name" ]] && PLUGIN_MANIFEST[name]="$name"

  # Extract version (quoted string)
  local version
  version=$(grep "^version = " "$plugin_toml" | sed 's/^version = "\(.*\)"$/\1/' || true)
  [[ -n "$version" ]] && PLUGIN_MANIFEST[version]="$version"

  # Extract hooks array (rough parse: hooks = ["hook1", "hook2"])
  local hooks_str
  hooks_str=$(grep "^hooks = " "$plugin_toml" | sed 's/^hooks = \[\(.*\)\]$/\1/' || true)
  # Remove quotes and split by comma
  hooks_str=$(echo "$hooks_str" | sed 's/"//g')
  PLUGIN_MANIFEST[hooks]="$hooks_str"
}

# ── Load and register all plugins ──────────────────────────────────────────────
# Usage: load_plugins SPIRAL_HOME
# Sets global associative array: PLUGINS[plugin_name]=plugin_dir, PLUGIN_HOOKS[hook_name]=plugin_dir
declare -gA PLUGINS PLUGIN_HOOKS
load_plugins() {
  local spiral_home="$1"
  local plugins_dir="$spiral_home/plugins"

  PLUGINS=()
  PLUGIN_HOOKS=()

  [[ ! -d "$plugins_dir" ]] && return 0

  # Scan plugins directory
  for plugin_dir in "$plugins_dir"/*; do
    [[ ! -d "$plugin_dir" ]] && continue
    local plugin_name
    plugin_name=$(basename "$plugin_dir")

    # Validate manifest
    if ! validate_plugin_manifest "$plugin_dir"; then
      continue
    fi

    # Parse manifest
    parse_plugin_manifest "$plugin_dir"

    # Register plugin
    PLUGINS["$plugin_name"]="$plugin_dir"

    # Register hooks
    local hooks="${PLUGIN_MANIFEST[hooks]:-}"
    if [[ -n "$hooks" ]]; then
      # Split by comma and space
      IFS=', ' read -ra hook_array <<< "$hooks"
      for hook in "${hook_array[@]}"; do
        hook=$(echo "$hook" | xargs)  # trim whitespace
        PLUGIN_HOOKS["$hook"]+="$plugin_name "
      done
    fi

    echo "  [plugin] Loaded: $plugin_name (version ${PLUGIN_MANIFEST[version]:-unknown})"
  done
}

# ── List all loaded plugins ────────────────────────────────────────────────────
# Usage: list_plugins
list_plugins() {
  if [[ ${#PLUGINS[@]} -eq 0 ]]; then
    echo "No plugins loaded."
    return 0
  fi

  echo "Loaded plugins:"
  for plugin_name in "${!PLUGINS[@]}"; do
    local plugin_dir="${PLUGINS[$plugin_name]}"
    parse_plugin_manifest "$plugin_dir"
    local hooks="${PLUGIN_MANIFEST[hooks]:-}"
    echo "  - $plugin_name (v${PLUGIN_MANIFEST[version]:-unknown})"
    echo "    hooks: ${hooks:-none}"
  done
}

# ── Build context JSON for hook scripts ────────────────────────────────────────
# Usage: build_hook_context STORY_ID
build_hook_context() {
  local story_id="${1:-}"

  # Build minimal JSON with current context
  # jq is a dependency, so we can use it here
  local context
  context="$(cat <<EOF
{
  "iteration": ${SPIRAL_ITER:-0},
  "spiral_run_id": "${SPIRAL_RUN_ID:-}",
  "phase": "${SPIRAL_CURRENT_PHASE:-}",
  "story_id": "$story_id",
  "timestamp_iso": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
)"
  echo "$context"
}

# ── Invoke plugin hooks for a specific hook point ────────────────────────────────
# Usage: run_plugin_hooks HOOK_POINT HOOK_TYPE STORY_ID
# HOOK_TYPE: PRE (abort on failure) or POST (warn on failure)
run_plugin_hooks() {
  local hook_point="$1"  # pre-phase, post-phase, post-story, etc.
  local hook_type="$2"   # PRE or POST
  local story_id="${3:-}"

  local plugins_for_hook="${PLUGIN_HOOKS[$hook_point]:-}"
  [[ -z "$plugins_for_hook" ]] && return 0

  local context
  context=$(build_hook_context "$story_id")

  local rc=0
  for plugin_name in $plugins_for_hook; do
    local plugin_dir="${PLUGINS[$plugin_name]}"
    local hook_script="$plugin_dir/$hook_point"

    if [[ ! -x "$hook_script" ]]; then
      echo "  [plugin] WARNING: Hook script $hook_script not executable — skipping" >&2
      continue
    fi

    # Execute hook with context on stdin, timeout enforced
    local hook_rc=0
    local hook_ts
    hook_ts=$(date +%s)
    if ! timeout "${SPIRAL_HOOK_TIMEOUT:-30}" bash "$hook_script" <<< "$context" 2>&1; then
      hook_rc=$?
    else
      hook_rc=0
    fi
    local hook_dur=$(( $(date +%s) - hook_ts ))

    # Log result
    log_spiral_event "plugin_hook" \
      "\"plugin\":\"$plugin_name\",\"hook\":\"$hook_point\",\"type\":\"$hook_type\",\"exit_code\":$hook_rc,\"duration_s\":$hook_dur" 2>/dev/null || true

    if [[ $hook_rc -ne 0 ]]; then
      if [[ "$hook_type" == "PRE" ]]; then
        echo "  [plugin] Pre-hook $hook_point/$plugin_name exited $hook_rc — aborting story attempt" >&2
        rc=$hook_rc
        break
      else
        echo "  [plugin] Post-hook $hook_point/$plugin_name exited $hook_rc (non-fatal)" >&2
      fi
    fi
  done

  return $rc
}

# ── Check if all required env vars are present for a plugin ──────────────────────
# Usage: validate_plugin_env PLUGIN_DIR
validate_plugin_env() {
  local plugin_dir="$1"
  local plugin_toml="$plugin_dir/plugin.toml"

  # Extract allowed_env array if present
  local allowed_env_str
  allowed_env_str=$(grep "^allowed_env = " "$plugin_toml" | sed 's/^allowed_env = \[\(.*\)\]$/\1/' || true)

  if [[ -z "$allowed_env_str" ]]; then
    return 0  # No env requirements
  fi

  # Check each required env var
  local missing=0
  IFS=', ' read -ra env_array <<< "$allowed_env_str"
  for env_var in "${env_array[@]}"; do
    env_var=$(echo "$env_var" | sed 's/"//g' | xargs)
    if [[ -z "${!env_var:-}" ]]; then
      echo "  [plugin] WARNING: Plugin requires $env_var but it's not set" >&2
      missing=1
    fi
  done

  return $missing
}
