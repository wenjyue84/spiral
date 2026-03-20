#!/bin/bash
# circuit_breaker.sh — Three-state circuit breaker for LLM API calls
#
# States: CLOSED (normal) → OPEN (blocked) → HALF_OPEN (probe) → CLOSED
#
# Usage (source this file, then call cb_* functions):
#   source lib/circuit_breaker.sh
#   if cb_check "$endpoint"; then
#     make_api_call && cb_record_success "$endpoint" || cb_record_failure "$endpoint" "$error_code"
#   else
#     echo "Circuit breaker OPEN — skipping call"
#   fi
#
# Environment variables:
#   SPIRAL_CB_FAILURE_THRESHOLD  — consecutive failures before tripping (default: 5)
#   SPIRAL_CB_COOLDOWN_SECS      — seconds to wait in OPEN before HALF_OPEN (default: 60)
#   SPIRAL_SCRATCH_DIR           — directory for state files (default: .spiral)

# ── Internal helpers ──────────────────────────────────────────────────────────

# Resolve path to state file for a given endpoint
_cb_state_file() {
  local endpoint="${1:-default}"
  local scratch_dir="${SPIRAL_SCRATCH_DIR:-.spiral}"
  if [[ "$endpoint" == "default" ]]; then
    echo "${scratch_dir}/circuit_breaker.json"
  else
    # Sanitize endpoint name to a safe filename
    local safe
    safe=$(printf '%s' "$endpoint" | tr '/:.' '_' | tr -cd '[:alnum:]_-')
    echo "${scratch_dir}/circuit_breaker_${safe}.json"
  fi
}

# Determine if an error code is transient (should count toward threshold)
# Transient: 429 (rate limit), 5xx (server errors), 529 (overloaded)
# Permanent: 400 (bad request), 401 (auth), 403 (forbidden), 404 (not found)
_cb_is_transient() {
  local code="${1:-0}"
  case "$code" in
    429 | 500 | 502 | 503 | 504 | 529) return 0 ;; # transient — count it
    *) return 1 ;;                                 # permanent or unknown — skip
  esac
}

# Emit a circuit breaker event to spiral_events.jsonl (if log_spiral_event available)
_cb_log() {
  local event_type="$1"
  local extra="${2:-}"
  if declare -f log_spiral_event >/dev/null 2>&1; then
    log_spiral_event "$event_type" "$extra"
  elif declare -f log_ralph_event >/dev/null 2>&1; then
    log_ralph_event "$event_type" "$extra"
  fi
}

# ── Public API ────────────────────────────────────────────────────────────────

# Read state file into CB_STATE, CB_FAILURE_COUNT, CB_LAST_FAILURE_TS, CB_COOLDOWN
# All values are set even if the file does not yet exist (defaults to CLOSED).
cb_read() {
  local endpoint="${1:-default}"
  local state_file
  state_file=$(_cb_state_file "$endpoint")
  local _jq="${JQ:-jq}"

  if [[ -f "$state_file" ]]; then
    CB_STATE=$($_jq -r '.state // "CLOSED"' "$state_file" 2>/dev/null || echo "CLOSED")
    CB_FAILURE_COUNT=$($_jq -r '.failure_count // 0' "$state_file" 2>/dev/null || echo "0")
    CB_LAST_FAILURE_TS=$($_jq -r '.last_failure_ts // 0' "$state_file" 2>/dev/null || echo "0")
    CB_COOLDOWN=$($_jq -r '.cooldown_secs // 60' "$state_file" 2>/dev/null || echo "60")
  else
    CB_STATE="CLOSED"
    CB_FAILURE_COUNT=0
    CB_LAST_FAILURE_TS=0
    CB_COOLDOWN="${SPIRAL_CB_COOLDOWN_SECS:-60}"
  fi
}

# Write circuit breaker state atomically (write-to-tmp then mv).
# Arguments: endpoint state failure_count last_failure_ts cooldown_secs
cb_write() {
  local endpoint="${1:-default}"
  local state="$2"
  local failure_count="${3:-0}"
  local last_failure_ts="${4:-0}"
  local cooldown_secs="${5:-${SPIRAL_CB_COOLDOWN_SECS:-60}}"
  local state_file
  state_file=$(_cb_state_file "$endpoint")
  local tmp_file="${state_file}.tmp.$$"
  mkdir -p "$(dirname "$state_file")"
  printf '{"state":"%s","failure_count":%s,"last_failure_ts":%s,"cooldown_secs":%s}\n' \
    "$state" "$failure_count" "$last_failure_ts" "$cooldown_secs" >"$tmp_file"
  mv "$tmp_file" "$state_file"
}

# Check whether a call to the given endpoint should be allowed.
# Returns 0 (allow the call) or 1 (circuit is OPEN — block the call).
# Side-effect: transitions OPEN → HALF_OPEN when the cooldown has elapsed.
cb_check() {
  local endpoint="${1:-default}"
  cb_read "$endpoint"
  local now
  now=$(date +%s)

  case "$CB_STATE" in
    CLOSED)
      return 0 # Normal — allow
      ;;
    OPEN)
      local elapsed=$((now - CB_LAST_FAILURE_TS))
      if [[ "$elapsed" -ge "$CB_COOLDOWN" ]]; then
        # Cooldown expired → transition to HALF_OPEN for a probe call
        cb_write "$endpoint" "HALF_OPEN" "$CB_FAILURE_COUNT" "$CB_LAST_FAILURE_TS" "$CB_COOLDOWN"
        _cb_log "circuit_breaker_half_open" \
          "\"endpoint\":\"$endpoint\",\"elapsed_secs\":$elapsed,\"failure_count\":$CB_FAILURE_COUNT"
        echo "  [cb] Circuit breaker HALF_OPEN for $endpoint (cooldown ${CB_COOLDOWN}s elapsed)" >&2
        return 0 # Allow the single probe call
      else
        local remaining=$((CB_COOLDOWN - elapsed))
        echo "  [cb] Circuit breaker OPEN for $endpoint — ${remaining}s remaining in cooldown" >&2
        return 1 # Block
      fi
      ;;
    HALF_OPEN)
      return 0 # Allow the probe call (only one at a time in single-worker mode)
      ;;
    *)
      return 0 # Unknown state — allow (fail open)
      ;;
  esac
}

# Record a successful call.  Resets the circuit breaker to CLOSED and clears
# the failure counter.  No-op if already CLOSED with zero failures.
cb_record_success() {
  local endpoint="${1:-default}"
  cb_read "$endpoint"

  if [[ "$CB_STATE" != "CLOSED" || "$CB_FAILURE_COUNT" -gt 0 ]]; then
    local prev_state="$CB_STATE"
    cb_write "$endpoint" "CLOSED" 0 0 "${SPIRAL_CB_COOLDOWN_SECS:-60}"
    _cb_log "circuit_breaker_closed" \
      "\"endpoint\":\"$endpoint\",\"prev_state\":\"$prev_state\",\"failure_count_reset\":$CB_FAILURE_COUNT"
    echo "  [cb] Circuit breaker CLOSED for $endpoint (was $prev_state)" >&2
  fi
}

# Record a failed call.  Only transient error codes (429, 5xx, 529) increment
# the failure counter.  Permanent errors (4xx) are ignored.
# When the failure count reaches SPIRAL_CB_FAILURE_THRESHOLD, trips to OPEN.
# When already HALF_OPEN, any failure immediately re-trips to OPEN and restarts
# the cooldown.
# Arguments: endpoint [error_code]
cb_record_failure() {
  local endpoint="${1:-default}"
  local error_code="${2:-0}"
  local threshold="${SPIRAL_CB_FAILURE_THRESHOLD:-5}"

  # Only transient errors increment the counter
  if ! _cb_is_transient "$error_code"; then
    echo "  [cb] Permanent error ($error_code) — not counting toward circuit breaker" >&2
    return 0
  fi

  cb_read "$endpoint"
  local now
  now=$(date +%s)
  local new_count=$((CB_FAILURE_COUNT + 1))

  if [[ "$CB_STATE" == "HALF_OPEN" || "$new_count" -ge "$threshold" ]]; then
    # Trip (or re-trip) to OPEN
    cb_write "$endpoint" "OPEN" "$new_count" "$now" "${SPIRAL_CB_COOLDOWN_SECS:-60}"
    _cb_log "circuit_breaker_open" \
      "\"endpoint\":\"$endpoint\",\"failure_count\":$new_count,\"threshold\":$threshold,\"error_code\":$error_code"
    echo "  [cb] Circuit breaker OPEN for $endpoint (${new_count}/${threshold} failures, error $error_code)" >&2
  else
    # Stay CLOSED — increment counter
    cb_write "$endpoint" "CLOSED" "$new_count" "$now" "${SPIRAL_CB_COOLDOWN_SECS:-60}"
    echo "  [cb] Failure recorded for $endpoint (${new_count}/${threshold}, error $error_code)" >&2
  fi
}
