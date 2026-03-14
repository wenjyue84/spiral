#!/bin/bash
# SPIRAL — API Retry with Jitter Library
# Prevents thundering herd when multiple workers hit rate limits simultaneously
# Source this file in spiral.sh and ralph.sh, then call spiral_api_retry <cmd>
#
# Each worker's RANDOM seed is unique (based on PID), so retry delays are staggered:
#   spiral_api_retry claude --help
#   spiral_api_retry curl https://api.anthropic.com/health
#
# Configuration:
#   SPIRAL_RETRY_JITTER_S — max random jitter in seconds (default: 5)
#   SPIRAL_RETRY_MAX_ATTEMPTS — max retries (default: 3)
#   SPIRAL_RETRY_BASE_DELAY — initial backoff in seconds (default: 1)

SPIRAL_RETRY_JITTER_S="${SPIRAL_RETRY_JITTER_S:-5}"
SPIRAL_RETRY_MAX_ATTEMPTS="${SPIRAL_RETRY_MAX_ATTEMPTS:-3}"
SPIRAL_RETRY_BASE_DELAY="${SPIRAL_RETRY_BASE_DELAY:-1}"

# Seed RANDOM with PID for per-worker uniqueness
RANDOM=$$

# ── Main Retry Wrapper ───────────────────────────────────────────────────────
# Usage: spiral_api_retry <cmd> [arg1 arg2 ...]
# Returns: exit code of the command on success, or non-zero on exhausted retries
spiral_api_retry() {
  local cmd=("$@")
  local attempt=0
  local max_attempts="$SPIRAL_RETRY_MAX_ATTEMPTS"
  local base_delay="$SPIRAL_RETRY_BASE_DELAY"
  local jitter_range="$SPIRAL_RETRY_JITTER_S"

  while true; do
    attempt=$((attempt + 1))

    # Execute the command
    "${cmd[@]}"
    local exit_code=$?

    # Success — return immediately
    if [[ $exit_code -eq 0 ]]; then
      return 0
    fi

    # Failed — check if we should retry
    if [[ $attempt -ge $max_attempts ]]; then
      # Exhausted retries
      return $exit_code
    fi

    # Calculate backoff with jitter
    # Formula: sleep_s = base_delay * attempt + (RANDOM % jitter_range)
    local exponential_delay=$((base_delay * attempt))
    local random_jitter=$((RANDOM % jitter_range))
    local sleep_seconds=$((exponential_delay + random_jitter))

    echo "  [retry] Attempt $attempt/$max_attempts failed (exit $exit_code) — retrying in ${sleep_seconds}s..." >&2
    sleep "$sleep_seconds"
  done
}

# ── Variant: Retry with Specific Exit Code Detection ────────────────────────
# Usage: spiral_api_retry_on_error <exit_code> <cmd> [arg1 arg2 ...]
# Retries ONLY if command exits with the specified code (e.g., 429, 529, 502)
spiral_api_retry_on_error() {
  local target_code="$1"
  shift
  local cmd=("$@")
  local attempt=0
  local max_attempts="$SPIRAL_RETRY_MAX_ATTEMPTS"
  local base_delay="$SPIRAL_RETRY_BASE_DELAY"
  local jitter_range="$SPIRAL_RETRY_JITTER_S"

  while true; do
    attempt=$((attempt + 1))

    # Execute the command
    "${cmd[@]}"
    local exit_code=$?

    # Not the target error code — return as-is
    if [[ $exit_code -ne $target_code ]]; then
      return $exit_code
    fi

    # Hit the target error code — check if we should retry
    if [[ $attempt -ge $max_attempts ]]; then
      # Exhausted retries
      return $exit_code
    fi

    # Calculate backoff with jitter
    local exponential_delay=$((base_delay * attempt))
    local random_jitter=$((RANDOM % jitter_range))
    local sleep_seconds=$((exponential_delay + random_jitter))

    echo "  [retry] Attempt $attempt/$max_attempts hit error $target_code — retrying in ${sleep_seconds}s..." >&2
    sleep "$sleep_seconds"
  done
}
