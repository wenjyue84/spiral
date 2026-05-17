#!/bin/bash
# WhatsApp notification plugin -- POST-PHASE hook
#
# Fires after each SPIRAL phase. Reads .spiral/_checkpoint.json and
# results.tsv to extract iteration stats, then sends a summary message
# via SPIRAL_WHATSAPP_API_URL webhook.
#
# Required env:
#   SPIRAL_WHATSAPP_API_URL      -- webhook URL to send the notification
#   SPIRAL_NOTIFICATIONS_ENABLED -- must be "true" to enable (default: disabled)
#   SPIRAL_HOME                  -- root of the SPIRAL repo (auto-detected if unset)
#
# Message format:
#   Iteration N complete: X/Y stories passed, $Z.ZZ spent, +D from prev, ~R iterations left

set -euo pipefail

# Resolve SPIRAL_HOME -- BASH_SOURCE[0] is empty when run via bash -c, so guard it
if [[ -z "${SPIRAL_HOME:-}" ]]; then
  _src="${BASH_SOURCE[0]:-}"
  if [[ -n "$_src" && "$_src" != "." ]]; then
    _dir="$(cd "$(dirname "$_src")/../.." 2>/dev/null && pwd)" || _dir="."
  else
    _dir="."
  fi
  SPIRAL_HOME="$_dir"
fi

# Respect SPIRAL_NOTIFICATIONS_ENABLED flag -- skip if not explicitly enabled
if [[ "${SPIRAL_NOTIFICATIONS_ENABLED:-false}" != "true" ]]; then
  exit 0
fi

# Skip if webhook URL not configured
if [[ -z "${SPIRAL_WHATSAPP_API_URL:-}" ]]; then
  echo "  [whatsapp-notify] WARNING: SPIRAL_WHATSAPP_API_URL not set -- skipping notification" >&2
  exit 0
fi

# Read context from stdin (JSON from plugin system)
context=""
if read -t 1 -r line 2>/dev/null; then
  context="$line"
fi

# Locate jq (bundled or system)
JQ="jq"
if [[ -x "${SPIRAL_HOME}/ralph/jq.exe" ]]; then
  JQ="${SPIRAL_HOME}/ralph/jq.exe"
elif command -v jq >/dev/null 2>&1; then
  JQ="jq"
fi

# Extract iteration from checkpoint file
checkpoint_file="${SPIRAL_HOME}/.spiral/_checkpoint.json"
iteration=0
if [[ -f "$checkpoint_file" ]]; then
  _iter=$("$JQ" -r '.iter // 0' "$checkpoint_file" 2>/dev/null || echo "0")
  iteration="${_iter//[^0-9]/}"
  iteration="${iteration:-0}"
fi

# Parse results.tsv for current iteration stats
results_file="${SPIRAL_HOME}/results.tsv"
passed=0
total=0
cost_cents=0 # track cost in cents to avoid float arithmetic in bash

if [[ -f "$results_file" ]]; then
  while IFS=$'\t' read -r _ts iter_num _ralph _sid _stitle status _dur _model _retry \
    _sha _run _chit r_tok c_tok _rest; do
    [[ "$iter_num" == "spiral_iter" ]] && continue # header row
    [[ "$iter_num" != "$iteration" ]] && continue  # different iteration
    total=$((total + 1))
    if [[ "$status" == "pass" || "$status" == "passed" ]]; then
      passed=$((passed + 1))
    fi
    # Approx cost: $0.003/1K read tokens + $0.015/1K creation tokens
    r="${r_tok:-0}"
    [[ -z "$r" || "$r" =~ [^0-9] ]] && r=0
    c="${c_tok:-0}"
    [[ -z "$c" || "$c" =~ [^0-9] ]] && c=0
    cost_cents=$((cost_cents + (r * 3) / 1000 + (c * 15) / 1000))
  done <"$results_file"
fi

# Format cost as dollars
cost_dollars=$((cost_cents / 100))
cost_frac=$((cost_cents % 100))
cost_str="${cost_dollars}.$(printf '%02d' "$cost_frac")"

# Calculate delta vs previous iteration
prev_passed=0
prev_iter=$((iteration - 1))
if [[ -f "$results_file" && "$prev_iter" -ge 1 ]]; then
  while IFS=$'\t' read -r _ts iter_num _ralph _sid _stitle status _rest; do
    [[ "$iter_num" == "spiral_iter" ]] && continue
    [[ "$iter_num" != "$prev_iter" ]] && continue
    if [[ "$status" == "pass" || "$status" == "passed" ]]; then
      prev_passed=$((prev_passed + 1))
    fi
  done <"$results_file"
fi

delta=$((passed - prev_passed))
if [[ "$delta" -ge 0 ]]; then
  delta_str="+${delta}"
else
  delta_str="${delta}"
fi

# Estimate remaining iterations from pending story count
remaining_est="?"
prd_file="${SPIRAL_HOME}/prd.json"
if [[ -f "$prd_file" && "$delta" -gt 0 ]]; then
  pending=$("$JQ" -r '[.userStories[] | select(.passes != true)] | length' "$prd_file" 2>/dev/null || echo "0")
  pending="${pending//[^0-9]/}"
  pending="${pending:-0}"
  if [[ "$pending" -ge 0 ]]; then
    remaining_est=$(((pending + delta - 1) / delta))
  fi
fi

# Format message
message="Iteration ${iteration} complete: ${passed}/${total} stories passed, \$${cost_str} spent, ${delta_str} from prev, ~${remaining_est} iterations left"

# Build JSON payload
payload=$(printf '{"text":"%s","iteration":%s,"passed":%s,"total":%s}' \
  "$message" "$iteration" "$passed" "$total")

# Send notification (non-fatal -- never block SPIRAL on notification failure)
curl -s -X POST "${SPIRAL_WHATSAPP_API_URL}" \
  -H 'Content-Type: application/json' \
  --data "$payload" \
  --max-time 10 \
  >/dev/null 2>&1 ||
  echo "  [whatsapp-notify] WARNING: Failed to send notification to ${SPIRAL_WHATSAPP_API_URL}" >&2

exit 0
