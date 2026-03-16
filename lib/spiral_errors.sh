#!/usr/bin/env bash
# lib/spiral_errors.sh — Structured error taxonomy for SPIRAL (US-273)
#
# Provides spiral_exit() which prints a formatted error message with
# remediation hint and logs the error to spiral_events.jsonl before exiting.
#
# Usage:
#   source "lib/spiral_errors.sh"
#   spiral_exit E101 "unknown flag --foo"
#   spiral_exit E501 "/path/to/prd.json"
#
# Error catalog codes:
#   E1xx  Config   — configuration and usage errors
#   E2xx  API      — external API / network errors
#   E3xx  Git      — git and worktree errors
#   E4xx  Worker   — worker lifecycle and progress errors
#   E5xx  Schema   — PRD schema and validation errors

# ── Error catalog: associative arrays ──────────────────────────────────────
# Each error code maps to: exit_code|category|message_template|remediation
# Message templates use %s for the details string.

declare -A SPIRAL_ERROR_EXIT SPIRAL_ERROR_CAT SPIRAL_ERROR_MSG SPIRAL_ERROR_FIX SPIRAL_ERROR_DOCS

# Config (E1xx)
SPIRAL_ERROR_EXIT[E101]=$ERR_BAD_USAGE
SPIRAL_ERROR_CAT[E101]="Config"
SPIRAL_ERROR_MSG[E101]="Invalid CLI arguments: %s"
SPIRAL_ERROR_FIX[E101]="Run: bash spiral.sh --help"
SPIRAL_ERROR_DOCS[E101]="https://github.com/user/spiral#usage"

SPIRAL_ERROR_EXIT[E102]=$ERR_CONFIG
SPIRAL_ERROR_CAT[E102]="Config"
SPIRAL_ERROR_MSG[E102]="Missing or invalid spiral.config.sh value: %s"
SPIRAL_ERROR_FIX[E102]="Run: bash spiral.sh --doctor"
SPIRAL_ERROR_DOCS[E102]="https://github.com/user/spiral#configuration"

SPIRAL_ERROR_EXIT[E103]=$ERR_MISSING_DEP
SPIRAL_ERROR_CAT[E103]="Config"
SPIRAL_ERROR_MSG[E103]="Required tool not found: %s"
SPIRAL_ERROR_FIX[E103]="Run: bash spiral.sh --doctor"
SPIRAL_ERROR_DOCS[E103]="https://github.com/user/spiral#prerequisites"

SPIRAL_ERROR_EXIT[E104]=$ERR_COST_CEILING
SPIRAL_ERROR_CAT[E104]="Config"
SPIRAL_ERROR_MSG[E104]="Cost ceiling reached: spent \$%s exceeds SPIRAL_COST_CEILING"
SPIRAL_ERROR_FIX[E104]="Increase SPIRAL_COST_CEILING in spiral.config.sh or set SPIRAL_COST_CEILING=0 to disable"
SPIRAL_ERROR_DOCS[E104]="https://github.com/user/spiral#cost-controls"

# API (E2xx)
SPIRAL_ERROR_EXIT[E201]=$ERR_API_DOWN
SPIRAL_ERROR_CAT[E201]="API"
SPIRAL_ERROR_MSG[E201]="Claude API unreachable at startup: %s"
SPIRAL_ERROR_FIX[E201]="Check your API key: echo \$ANTHROPIC_API_KEY | head -c8 ; check https://status.anthropic.com"
SPIRAL_ERROR_DOCS[E201]="https://github.com/user/spiral#api-setup"

# Git (E3xx)
SPIRAL_ERROR_EXIT[E301]=$ERR_ROLLBACK_FAILED
SPIRAL_ERROR_CAT[E301]="Git"
SPIRAL_ERROR_MSG[E301]="Rollback failed for story %s"
SPIRAL_ERROR_FIX[E301]="Run: git log --oneline -5   # inspect recent commits, then manually revert"
SPIRAL_ERROR_DOCS[E301]="https://github.com/user/spiral#rollback"

# Worker (E4xx)
SPIRAL_ERROR_EXIT[E401]=$ERR_ZERO_PROGRESS
SPIRAL_ERROR_CAT[E401]="Worker"
SPIRAL_ERROR_MSG[E401]="Zero-progress stall: all pending stories are blocked"
SPIRAL_ERROR_FIX[E401]="Run: python main.py status   # check blocked stories; consider --skip-story or splitting"
SPIRAL_ERROR_DOCS[E401]="https://github.com/user/spiral#stall-detection"

SPIRAL_ERROR_EXIT[E402]=$ERR_REPLAY_FAILED
SPIRAL_ERROR_CAT[E402]="Worker"
SPIRAL_ERROR_MSG[E402]="Replay failed for story %s"
SPIRAL_ERROR_FIX[E402]="Run: python main.py status   # check story state; re-run with --replay STORY_ID"
SPIRAL_ERROR_DOCS[E402]="https://github.com/user/spiral#replay"

SPIRAL_ERROR_EXIT[E403]=$ERR_STORY_NOT_FOUND
SPIRAL_ERROR_CAT[E403]="Worker"
SPIRAL_ERROR_MSG[E403]="Story not found in prd.json: %s"
SPIRAL_ERROR_FIX[E403]="Run: cat prd.json | jq '.userStories[].id'   # list available story IDs"
SPIRAL_ERROR_DOCS[E403]="https://github.com/user/spiral#prd-management"

SPIRAL_ERROR_EXIT[E404]=$ERR_MAX_ITERS
SPIRAL_ERROR_CAT[E404]="Worker"
SPIRAL_ERROR_MSG[E404]="Max spiral iterations (%s) reached with stories still pending"
SPIRAL_ERROR_FIX[E404]="Increase max iterations: bash spiral.sh 50 --gate proceed"
SPIRAL_ERROR_DOCS[E404]="https://github.com/user/spiral#iteration-limits"

SPIRAL_ERROR_EXIT[E405]=$ERR_CASCADE_ABORT
SPIRAL_ERROR_CAT[E405]="Worker"
SPIRAL_ERROR_MSG[E405]="Cascade abort: consecutive failures exceeded threshold (%s)"
SPIRAL_ERROR_FIX[E405]="Run: python main.py diagnose   # inspect failure chain; fix blocking stories first"
SPIRAL_ERROR_DOCS[E405]="https://github.com/user/spiral#cascade-abort"

# Schema (E5xx)
SPIRAL_ERROR_EXIT[E501]=$ERR_PRD_NOT_FOUND
SPIRAL_ERROR_CAT[E501]="Schema"
SPIRAL_ERROR_MSG[E501]="prd.json not found at %s"
SPIRAL_ERROR_FIX[E501]="Run: cp templates/prd.example.json prd.json"
SPIRAL_ERROR_DOCS[E501]="https://github.com/user/spiral#prd-setup"

SPIRAL_ERROR_EXIT[E502]=$ERR_PRD_CORRUPT
SPIRAL_ERROR_CAT[E502]="Schema"
SPIRAL_ERROR_MSG[E502]="prd.json is corrupt and unrecoverable: %s"
SPIRAL_ERROR_FIX[E502]="Run: python -m json.tool prd.json ; git checkout HEAD -- prd.json"
SPIRAL_ERROR_DOCS[E502]="https://github.com/user/spiral#prd-recovery"

SPIRAL_ERROR_EXIT[E503]=$ERR_SCHEMA_VERSION
SPIRAL_ERROR_CAT[E503]="Schema"
SPIRAL_ERROR_MSG[E503]="prd.json schemaVersion (%s) is newer than SPIRAL supports"
SPIRAL_ERROR_FIX[E503]="Update SPIRAL: git pull origin main   # or downgrade prd.json schemaVersion to 1"
SPIRAL_ERROR_DOCS[E503]="https://github.com/user/spiral#schema-versioning"

# ── spiral_exit: print formatted error + log to events + exit ──────────────
# Usage: spiral_exit ERROR_CODE [DETAILS]
# Example: spiral_exit E101 "unknown flag --foo"
spiral_exit() {
  local error_code="$1"
  local details="${2:-}"

  # Look up catalog entry
  local exit_val="${SPIRAL_ERROR_EXIT[$error_code]:-1}"
  local category="${SPIRAL_ERROR_CAT[$error_code]:-unknown}"
  local msg_template="${SPIRAL_ERROR_MSG[$error_code]:-Unknown error: %s}"
  local fix="${SPIRAL_ERROR_FIX[$error_code]:-}"
  local docs="${SPIRAL_ERROR_DOCS[$error_code]:-}"

  # Format message (substitute %s with details)
  local message
  # shellcheck disable=SC2059
  message=$(printf "$msg_template" "$details")

  # Print to stderr
  echo "[SPIRAL-E-${error_code}] ${message}" >&2
  if [[ -n "$fix" ]]; then
    echo "Fix: ${fix}" >&2
  fi
  if [[ -n "$docs" ]]; then
    echo "Docs: ${docs}" >&2
  fi

  # Log structured event to spiral_events.jsonl
  local log_file="${SCRATCH_DIR:-.spiral}/spiral_events.jsonl"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local json_line
  json_line=$("$JQ" -n \
    --arg ts "$ts" \
    --arg event "spiral_error" \
    --arg error_code "$error_code" \
    --arg category "$category" \
    --argjson exit_code "$exit_val" \
    --arg message "$message" \
    --arg remediation "$fix" \
    --arg docs_url "$docs" \
    --arg details "$details" \
    --arg run_id "${SPIRAL_RUN_ID:-}" \
    '{ts: $ts, event: $event, error_code: $error_code, category: $category,
      exit_code: $exit_code, message: $message, remediation: $remediation,
      docs_url: $docs_url, context: {details: $details}, run_id: $run_id}' \
    2>/dev/null) || true
  if [[ -n "$json_line" ]]; then
    printf '%s\n' "$json_line" >>"$log_file" 2>/dev/null || true
  fi

  # Write last error to _last_error.json for status display
  local last_error_file="${SCRATCH_DIR:-.spiral}/_last_error.json"
  "$JQ" -n \
    --arg ts "$ts" \
    --arg error_code "$error_code" \
    --arg category "$category" \
    --argjson exit_code "$exit_val" \
    --arg message "$message" \
    --arg remediation "$fix" \
    '{ts: $ts, error_code: $error_code, category: $category,
      exit_code: $exit_code, message: $message, remediation: $remediation}' \
    >"$last_error_file" 2>/dev/null || true

  exit "$exit_val"
}
