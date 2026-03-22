#!/usr/bin/env bash
# ralph/lib/ollama_fallback.sh -- Ollama API fallback, pre-warm, and policy-based local fallback
#
# Extracted from ralph.sh. Sourced after log_ralph_event, log_spiral_event,
# SPIRAL_SCRATCH_DIR are defined.

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

call_ollama_fallback() {
  local sys_file="$1"
  local usr_file="$2"
  local model="${SPIRAL_OLLAMA_FALLBACK_MODEL}"
  local host="${SPIRAL_OLLAMA_HOST:-http://localhost:11434/v1}"
  echo "  [ollama] Calling Ollama model: $model at $host"
  local payload
  payload=$(python3 -c "
import json, sys
system = open(sys.argv[1]).read()
user = open(sys.argv[2]).read()
model = sys.argv[3]
print(json.dumps({'model': model, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], 'stream': False, 'temperature': 0.1}))
" "$sys_file" "$usr_file" "$model" 2>/dev/null) || {
    echo "  [ollama] ERROR: failed to build JSON payload"; return 1
  }
  local response
  response=$(curl -sf -X POST "${host}/chat/completions" \
    -H "Content-Type: application/json" -d "$payload" \
    --connect-timeout 10 --max-time 300 2>/dev/null)
  local curl_rc=$?
  if [[ "$curl_rc" -eq 7 ]]; then
    echo "  [ollama] ERROR: connection refused (curl exit 7) -- is Ollama running at ${host}?"
    return 1
  elif [[ "$curl_rc" -eq 28 ]]; then
    echo "  [ollama] ERROR: connection timed out (curl exit 28)"; return 1
  elif [[ "$curl_rc" -ne 0 ]]; then
    echo "  [ollama] ERROR: curl failed (exit $curl_rc)"; return 1
  fi
  local content
  content=$(echo "$response" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(data['choices'][0]['message']['content'])
" 2>/dev/null) || content="$response"
  printf '%s\n' "$content"
}

ollama_prewarm() {
  local policy="${SPIRAL_LOCAL_FALLBACK_POLICY:-}"
  [[ -z "$policy" || "$policy" == "deny" ]] && return 0
  local base_url="${SPIRAL_OLLAMA_BASE_URL:-http://localhost:11434}"
  local model="${SPIRAL_OLLAMA_MODEL:-llama3.2}"
  echo "  [ollama] Pre-warm: GET ${base_url}/api/tags (policy: ${policy}, model: ${model})"
  local tags
  if ! tags=$(curl -sf --connect-timeout 5 --max-time 10 "${base_url}/api/tags" 2>/dev/null); then
    echo "  [ollama] WARNING: Ollama unreachable at ${base_url} -- fallback may cold-start (~13s)"
    log_ralph_event "ollama_prewarm_failed" \
      "\"url\":\"${base_url}\",\"model\":\"${model}\",\"policy\":\"${policy}\""
    return 0
  fi
  if echo "$tags" | grep -q "\"name\":\"${model}" 2>/dev/null; then
    echo "  [ollama] [OK] Model '${model}' pre-loaded at ${base_url}"
  else
    echo "  [ollama] WARNING: Model '${model}' absent from /api/tags -- cold-start ~13s on first use"
    log_ralph_event "ollama_model_absent" \
      "\"url\":\"${base_url}\",\"model\":\"${model}\",\"policy\":\"${policy}\""
  fi
}

apply_local_fallback_policy() {
  local reason="$1" rl_out="$2"
  local policy="${SPIRAL_LOCAL_FALLBACK_POLICY:-}"
  [[ -z "$policy" ]] && return 1
  local base_url="${SPIRAL_OLLAMA_BASE_URL:-http://localhost:11434}"
  local model="${SPIRAL_OLLAMA_MODEL:-llama3.2}"
  case "$policy" in
    deny)
      echo "LOCAL_FALLBACK_DENIED: ${reason}"
      log_spiral_event "local_fallback_denied" \
        "\"story_id\":\"${NEXT_STORY:-}\",\"reason\":\"${reason}\",\"model_used\":\"none\",\"original_error\":\"${reason}\",\"policy\":\"deny\""
      exit 2
      ;;
    allow | local-only)
      mkdir -p "${SPIRAL_SCRATCH_DIR}"
      local sys_tmp="${SPIRAL_SCRATCH_DIR}/_ol261_sys_$$.tmp"
      local usr_tmp="${SPIRAL_SCRATCH_DIR}/_ol261_usr_$$.tmp"
      printf '%s' "${RALPH_SYSTEM_PROMPT:-}" >"$sys_tmp"
      printf '%s' "${RALPH_USER_PROMPT:-}" >"$usr_tmp"
      echo "  [ollama] '${policy}' policy: invoking local model ${model} at ${base_url}"
      local _sv_model="${SPIRAL_OLLAMA_FALLBACK_MODEL}" _sv_host="${SPIRAL_OLLAMA_HOST}"
      SPIRAL_OLLAMA_FALLBACK_MODEL="${model}"
      SPIRAL_OLLAMA_HOST="${base_url}/v1"
      local _rc=0
      if call_ollama_fallback "$sys_tmp" "$usr_tmp" >"$rl_out"; then
        _OLLAMA_USED=1
        log_spiral_event "local_fallback_used" \
          "\"story_id\":\"${NEXT_STORY:-}\",\"reason\":\"${reason}\",\"model_used\":\"${model}\",\"original_error\":\"${reason}\",\"policy\":\"${policy}\""
        echo "  [ollama] Local fallback succeeded"
      else
        _rc=1; >"$rl_out"
        log_spiral_event "local_fallback_failed" \
          "\"story_id\":\"${NEXT_STORY:-}\",\"reason\":\"${reason}\",\"model_used\":\"${model}\",\"original_error\":\"${reason}\",\"policy\":\"${policy}\""
        echo "  [ollama] Local fallback failed -- story will be retried later"
      fi
      SPIRAL_OLLAMA_FALLBACK_MODEL="${_sv_model}"
      SPIRAL_OLLAMA_HOST="${_sv_host}"
      rm -f "$sys_tmp" "$usr_tmp"
      return $_rc
      ;;
    *)
      echo "  [ollama] WARNING: unknown SPIRAL_LOCAL_FALLBACK_POLICY '${policy}' -- ignoring"
      return 1
      ;;
  esac
}
