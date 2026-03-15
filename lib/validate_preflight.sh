#!/bin/bash
# SPIRAL — Pre-flight Validation
# Source this file in spiral.sh, then call spiral_preflight_check.
# Validates prd.json schema, checkpoint integrity, and config sanity before main loop.

spiral_preflight_check() {
  local prd_file="${1:-$PRD_FILE}"
  local scratch_dir="${2:-$SCRATCH_DIR}"
  local exit_on_fail=1

  echo "  [preflight] Validating prd.json schema..."
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd_file" --quiet
  local schema_rc=$?
  if [[ "$schema_rc" -ne 0 ]]; then
    echo "  [preflight] FATAL: prd.json schema validation failed — aborting (exit $schema_rc)"
    exit "$schema_rc"
  fi
  echo "  [preflight] prd.json schema: OK"

  # ── UTF-8 / control-character encoding check ────────────────────────────────
  local sanitize_flag=""
  if [[ "${SPIRAL_SANITIZE_PRD:-}" == "true" ]]; then
    sanitize_flag="--sanitize"
  fi
  local enc_out enc_rc
  enc_out=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/check_prd_encoding.py" "$prd_file" --quiet ${sanitize_flag} 2>&1)
  enc_rc=$?
  if [[ -n "$enc_out" ]]; then
    echo "$enc_out"
  fi
  if [[ "$enc_rc" -ne 0 ]]; then
    echo "  [preflight] FATAL: prd.json encoding check failed — aborting (exit $enc_rc)"
    exit "$enc_rc"
  fi

  # ── Checkpoint validation ──────────────────────────────────────────────────
  local ckpt="$scratch_dir/_checkpoint.json"
  if [[ -f "$ckpt" ]]; then
    echo "  [preflight] Validating checkpoint..."
    # Check it's valid JSON with required fields
    if ! "$JQ" -e '.iter and .phase and .ts' "$ckpt" >/dev/null 2>&1; then
      echo "  [preflight] WARNING: Corrupt checkpoint — removing $ckpt"
      rm -f "$ckpt"
    else
      local ckpt_phase
      ckpt_phase=$("$JQ" -r '.phase' "$ckpt")
      case "$ckpt_phase" in
        R | T | M | G | I | V | C) ;;
        *)
          echo "  [preflight] WARNING: Invalid checkpoint phase '$ckpt_phase' — removing"
          rm -f "$ckpt"
          ;;
      esac
    fi
  fi

  # ── Config validation (if spiral.config.sh vars are already sourced) ───────
  if [[ -n "${SPIRAL_MODEL_ROUTING:-}" ]]; then
    case "$SPIRAL_MODEL_ROUTING" in
      auto | haiku | sonnet | opus) ;;
      *)
        echo "  [preflight] WARNING: Unknown SPIRAL_MODEL_ROUTING='$SPIRAL_MODEL_ROUTING' (expected: auto|haiku|sonnet|opus)"
        ;;
    esac
  fi

  if [[ -n "${MAX_RETRIES:-}" ]]; then
    if ! [[ "$MAX_RETRIES" =~ ^[1-9][0-9]*$ ]]; then
      echo "  [preflight] WARNING: MAX_RETRIES='$MAX_RETRIES' is not a positive integer"
    fi
  fi

  if [[ -n "${SPIRAL_MAX_PENDING:-}" ]] && [[ "$SPIRAL_MAX_PENDING" != "0" ]]; then
    if ! [[ "$SPIRAL_MAX_PENDING" =~ ^[0-9]+$ ]]; then
      echo "  [preflight] WARNING: SPIRAL_MAX_PENDING='$SPIRAL_MAX_PENDING' is not a non-negative integer"
    fi
  fi

  # ── Story count health check ────────────────────────────────────────────────
  local max_stories="${SPIRAL_MAX_STORIES:-100}"
  local abort_on_excess="${SPIRAL_MAX_STORIES_ABORT:-0}"
  local story_count
  story_count=$("$JQ" '.userStories | length' "$prd_file" 2>/dev/null || echo "0")
  if [[ "$story_count" -gt "$max_stories" ]]; then
    echo "  [preflight] WARNING: prd.json has $story_count stories (threshold: $max_stories)."
    echo "  [preflight]   Run: bash spiral.sh --archive-done"
    echo "  [preflight]   This moves completed stories to prd-archive.json, keeping prd.json lean."
    if [[ "${abort_on_excess}" != "0" ]]; then
      echo "  [preflight] FATAL: SPIRAL_MAX_STORIES_ABORT is set — aborting due to story count ($story_count > $max_stories)"
      exit 1
    fi
  fi

  # ── Duplicate story ID check (US-180) ──────────────────────────────────────
  local dedup_mode="${SPIRAL_DEDUP_IDS:-strict}"
  local dup_ids
  dup_ids=$("$JQ" -r '[.userStories | group_by(.id)[] | select(length > 1) | .[0].id] | join(" ")' "$prd_file" 2>/dev/null || echo "")
  if [[ -n "$dup_ids" ]]; then
    if [[ "$dedup_mode" == "lenient" ]]; then
      echo "  [preflight] WARNING: Duplicate story IDs found: $dup_ids"
      echo "  [preflight]   Lenient mode: keeping passes:true entry, dropping duplicates..."
      local _dup_tmp
      _dup_tmp=$(mktemp)
      "$JQ" '.userStories |= (group_by(.id) | map((map(select(.passes == true)) | first) // first))' \
        "$prd_file" > "$_dup_tmp" && mv "$_dup_tmp" "$prd_file"
      printf '{"ts":"%s","event":"duplicate_ids_deduped","ids":"%s","mode":"lenient"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$dup_ids" \
        >> "${scratch_dir}/spiral_events.jsonl" 2>/dev/null || true
      echo "  [preflight] Duplicate IDs resolved (lenient)."
    else
      echo "  [preflight] FATAL: Duplicate story IDs detected — aborting."
      echo "  [preflight]   Duplicates: $dup_ids"
      echo "  [preflight]   Run with SPIRAL_DEDUP_IDS=lenient to auto-deduplicate."
      printf '{"ts":"%s","event":"duplicate_ids_fatal","ids":"%s","mode":"strict"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$dup_ids" \
        >> "${scratch_dir}/spiral_events.jsonl" 2>/dev/null || true
      exit 1
    fi
  fi

  # ── ShellCheck (informational only) ────────────────────────────────────────
  if command -v shellcheck >/dev/null 2>&1; then
    local sc_errors=0
    for script in "$SPIRAL_HOME/spiral.sh" "$SPIRAL_HOME/ralph/ralph.sh"; do
      if [[ -f "$script" ]]; then
        local count
        count=$(shellcheck -S error "$script" 2>&1 | grep -c "^In " || true)
        if [[ "$count" -gt 0 ]]; then
          echo "  [preflight] ShellCheck: $count error-level issue(s) in $(basename "$script") (non-blocking)"
          sc_errors=$((sc_errors + count))
        fi
      fi
    done
    if [[ "$sc_errors" -eq 0 ]]; then
      echo "  [preflight] ShellCheck: clean"
    fi
  fi

  # ── Claude API reachability probe (US-179) ─────────────────────────────────
  if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
    echo "  [preflight] Skipping Claude API check (--dry-run mode)"
  elif [[ "${SPIRAL_SKIP_API_CHECK:-}" == "true" ]]; then
    echo "  [preflight] Skipping Claude API check (SPIRAL_SKIP_API_CHECK=true)"
  elif [[ -z "${ANTHROPIC_API_KEY:-}" ]] && command -v claude &>/dev/null; then
    # Claude Code users: the claude CLI handles auth — no API key needed
    echo "  [preflight] Claude API check: using claude CLI auth (Claude Code mode)"
  else
    if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
      echo "  [preflight] FATAL: ANTHROPIC_API_KEY is not set and claude CLI not found"
      echo "  [preflight]   → If using Claude Code: install claude CLI and log in"
      echo "  [preflight]   → If using API directly: export ANTHROPIC_API_KEY=<your-key>"
      echo "  [preflight]   → Skip this check: export SPIRAL_SKIP_API_CHECK=true"
      exit "${ERR_API_DOWN:-14}"
    fi
    local _api_probe_ok=0
    if curl -sf --connect-timeout 5 --max-time 5 \
        -H "x-api-key: ${ANTHROPIC_API_KEY}" \
        -H "anthropic-version: 2023-06-01" \
        "https://api.anthropic.com/v1/models" >/dev/null 2>&1; then
      _api_probe_ok=1
    fi
    if [[ "$_api_probe_ok" -eq 1 ]]; then
      echo "  [preflight] Claude API reachable: OK"
    else
      echo "  [preflight] FATAL: Claude API not reachable (5-second probe failed)"
      echo "  [preflight]   Set SPIRAL_SKIP_API_CHECK=true to skip this check"
      exit "${ERR_API_DOWN:-14}"
    fi
  fi

  echo "  [preflight] All checks passed"
}
