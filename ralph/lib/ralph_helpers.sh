#!/usr/bin/env bash
# ralph/lib/ralph_helpers.sh -- Small utility functions for Ralph agent loop
#
# Extracted from ralph.sh. Sourced early, after JQ, PRD_FILE are defined.
#
# Functions provided:
#   extract_stream_text     -- parse claude stream-json for assistant text
#   accumulate_anti_pattern -- inject failure reason as anti-pattern in prd.json
#   reject_story_gate       -- mark story failed at a quality gate
#   log_ralph_event         -- append JSONL event to spiral_events.jsonl
#   log_tool_call_from_code -- log tool call from code_execution (US-339)
#   accumulate_story_cost   -- per-story token cost tracking

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

SPIRAL_SCRATCH_DIR="${SPIRAL_SCRATCH_DIR:-.spiral}"

extract_stream_text() {
  local _file="$1"
  python3 - "$_file" <<'STREAM_TEXT_EOF'
import sys, json
parts = []
try:
    with open(sys.argv[1], encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get('type') == 'assistant':
                    msg = obj.get('message', obj)
                    for block in msg.get('content', []):
                        if block.get('type') == 'text':
                            parts.append(block.get('text', ''))
            except Exception:
                pass
except Exception:
    pass
print('\n'.join(parts))
STREAM_TEXT_EOF
}

accumulate_anti_pattern() {
  local default_reason="${1:-story_incomplete}"
  if [[ "${SPIRAL_ANTI_PATTERN_INJECT:-true}" == "true" ]]; then
    _AP_FAIL_REASON=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason // \"$default_reason\"" \
      "$PRD_FILE" 2>/dev/null | tr -d '\r"\\' | head -c 200 || echo "$default_reason")
    if [[ -n "$_AP_FAIL_REASON" ]]; then
      $JQ --arg sid "$NEXT_STORY" --arg note "$_AP_FAIL_REASON" \
        '(.userStories[] | select(.id == $sid) | ._antiPatterns) |= (. // []) + [$note]' \
        "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
    fi
  fi
}

reject_story_gate() {
  local failure_reason="$1" gate_name="$2" progress_msg="$3"
  do_story_reset "$PRE_STORY_SHA"
  $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" "$PRD_FILE" >"${PRD_FILE}.tmp"
  mv "${PRD_FILE}.tmp" "$PRD_FILE"
  $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason) = \"$failure_reason\"" "$PRD_FILE" >"${PRD_FILE}.tmp"
  mv "${PRD_FILE}.tmp" "$PRD_FILE"
  increment_retry "$NEXT_STORY"
  RETRY_NOW=$(get_retry_count "$NEXT_STORY")
  echo "[retry] $NEXT_STORY attempt $RETRY_NOW/$MAX_RETRIES ($gate_name gate failed)"
  append_result "reject"
  echo "## Iteration $ITERATION - $(date)" >>"$PROGRESS_FILE"
  echo "FAILED $gate_name: $STORY_TITLE (ID: $NEXT_STORY) -- $progress_msg -- attempt $RETRY_NOW/$MAX_RETRIES" >>"$PROGRESS_FILE"
  echo "" >>"$PROGRESS_FILE"
}

log_ralph_event() {
  local event="$1"
  local extra="${2:-}"
  local ts log_file line
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log_file="$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"
  if [[ -n "$extra" ]]; then
    line="{\"ts\":\"$ts\",\"event\":\"$event\",$extra}"
  else
    line="{\"ts\":\"$ts\",\"event\":\"$event\"}"
  fi
  printf '%s\n' "$line" >>"$log_file" 2>/dev/null || true
}

log_tool_call_from_code() {
  local tool_name="$1"
  local story_id="${2:-}"
  local extra="${3:-}"
  local caller_field="\"caller\":\"code_execution_20250825\",\"tool\":\"$tool_name\""
  [[ -n "$story_id" ]] && caller_field="$caller_field,\"story_id\":\"$story_id\""
  [[ -n "$extra" ]] && caller_field="$caller_field,$extra"
  log_ralph_event "tool_call_from_code" "$caller_field"
}

accumulate_story_cost() {
  local story_id="$1" tokens_input="${2:-0}" tokens_output="${3:-0}"
  local cache_creation="${4:-0}" cache_read="${5:-0}"
  local cost_file="$SPIRAL_SCRATCH_DIR/story_costs.json"
  local input_price="$SPIRAL_MODEL_INPUT_PRICE_PER_M"
  local output_price="$SPIRAL_MODEL_OUTPUT_PRICE_PER_M"

  local cumulative_usd
  cumulative_usd=$(
    python3 - <<PYEOF 2>/dev/null
import json, os, sys

story_id = '$story_id'
tokens_input = int('$tokens_input') if '$tokens_input'.isdigit() else 0
tokens_output = int('$tokens_output') if '$tokens_output'.isdigit() else 0
cache_creation = int('$cache_creation') if '$cache_creation'.isdigit() else 0
cache_read = int('$cache_read') if '$cache_read'.isdigit() else 0
input_price = float('$input_price')
output_price = float('$output_price')
cost_file = '$cost_file'

try:
    with open(cost_file, 'r', encoding='utf-8') as f:
        costs = json.load(f)
except (FileNotFoundError, json.JSONDecodeError, OSError):
    costs = {}

entry = costs.get(story_id, {'tokens_input': 0, 'tokens_output': 0, 'estimated_usd': 0.0})
entry['tokens_input'] = entry.get('tokens_input', 0) + tokens_input
entry['tokens_output'] = entry.get('tokens_output', 0) + tokens_output
non_cached_input = max(0, tokens_input - cache_creation - cache_read)
call_cost = ((non_cached_input / 1_000_000) * input_price
             + (cache_creation / 1_000_000) * input_price * 1.25
             + (cache_read / 1_000_000) * input_price * 0.1
             + (tokens_output / 1_000_000) * output_price)
entry['estimated_usd'] = round(entry.get('estimated_usd', 0.0) + call_cost, 6)
costs[story_id] = entry

tmp = cost_file + '.tmp'
try:
    os.makedirs(os.path.dirname(cost_file) or '.', exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(costs, f, indent=2)
    os.replace(tmp, cost_file)
except OSError as e:
    sys.stderr.write(f'[cost] WARNING: could not write {cost_file}: {e}\n')

print(entry['estimated_usd'])
PYEOF
  ) || true

  cumulative_usd="${cumulative_usd:-0}"
  log_ralph_event "cost_update" \
    "\"story_id\":\"$story_id\",\"tokens_input\":$tokens_input,\"tokens_output\":$tokens_output,\"estimated_usd\":$cumulative_usd" || true
  printf '%s' "$cumulative_usd"
}
