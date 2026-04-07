#!/usr/bin/env bash
# lib/impl/retry.sh -- Phase I sub-stage: RETRY LOGIC
#
# Manages the per-story attempt counter and enforces the 3-retry-skip rule.
# Called by phase_i_implement.sh after each ralph worker invocation.
#
# Rules:
#   - Each story starts with retries: 0 in prd.json
#   - On failure: increment retries field in prd.json
#   - At retries >= 3: mark story _skipped: true, log reason to progress.txt
#   - Skipped stories are excluded from future worker dispatch
#   - On the 2nd failure: flag story for decomposition (calls decompose.sh)
#
# Retry escalation (SPIRAL_MODEL_ROUTING=auto):
#   - Attempt 1: assigned model (haiku/sonnet based on complexity)
#   - Attempt 2: escalate to sonnet
#   - Attempt 3: escalate to opus
#   - Attempt 4+: skip
#
# Inputs:
#   story_id        -- story that just failed
#   $PRD_FILE       -- prd.json (read + write retries field)
#
# Outputs:
#   $PRD_FILE (retries incremented; _skipped added at threshold)
#   progress.txt (skip reason appended)
#
# Used by: phase_i_implement.sh after each worker returns passes: false

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# ── Source prd.json atomic patch helper (US-1137) ──────────────────────────────
_RETRY_PRD_LOCK_HELPER="${SPIRAL_HOME:-$(dirname "${BASH_SOURCE[0]}")/../..}/lib/core/prd_lock.sh"
if [[ -f "$_RETRY_PRD_LOCK_HELPER" ]]; then
  source "$_RETRY_PRD_LOCK_HELPER"
fi

# invoke_exhaustion_analyzer <story_id> <attempts_json_file>
# Runs lib/impl/exhaustion_analyzer.py and writes the JSON report to
# .spiral/exhausted_stories/<story_id>_analysis.json.
# Silently skips if Python or the analyzer script is unavailable.
invoke_exhaustion_analyzer() {
  local story_id="$1"
  local attempts_file="${2:-}"
  local analyzer_script
  analyzer_script="$(dirname "${BASH_SOURCE[0]}")/exhaustion_analyzer.py"
  local output_dir=".spiral/exhausted_stories"
  local output_file="${output_dir}/${story_id}_analysis.json"

  if [[ ! -f "$analyzer_script" ]]; then
    echo "[Phase I / retry] exhaustion_analyzer.py not found, skipping report" >&2
    return 0
  fi
  if [[ -z "$attempts_file" || ! -f "$attempts_file" ]]; then
    echo "[Phase I / retry] No attempts file provided for $story_id, skipping exhaustion report" >&2
    return 0
  fi

  mkdir -p "$output_dir"
  if uv run python "$analyzer_script" \
    --story-id "$story_id" \
    --attempts "$attempts_file" \
    --output "$output_file" 2>&1; then
    echo "[Phase I / retry] Exhaustion report written: $output_file"
  else
    echo "[Phase I / retry] Exhaustion analyzer failed for $story_id (non-fatal)" >&2
  fi
  return 0
}

# capture_failed_files_from_stderr <stderr_file>
# Parses a Ralph stderr file for file-path failure signals.
# Outputs a JSON array string (e.g. '["src/a.py","lib/b.py"]') to stdout.
# Returns "[]" on any error.
capture_failed_files_from_stderr() {
  local stderr_file="${1:-}"
  local helper_script
  helper_script="$(dirname "${BASH_SOURCE[0]}")/file_aware_retry.py"

  if [[ ! -f "$helper_script" || ! -f "$stderr_file" ]]; then
    echo "[]"
    return 0
  fi

  local result
  result=$(uv run python "$helper_script" extract "$stderr_file" 2>/dev/null || echo "[]")
  echo "${result:-[]}"
}

# get_previous_failed_files <story_id> [results_tsv]
# Reads the failed_files JSON array from the last results.tsv row for story_id.
# Outputs a JSON array string to stdout.
get_previous_failed_files() {
  local story_id="${1:-}"
  local results_tsv="${2:-results.tsv}"
  local helper_script
  helper_script="$(dirname "${BASH_SOURCE[0]}")/file_aware_retry.py"

  if [[ ! -f "$helper_script" || -z "$story_id" || ! -f "$results_tsv" ]]; then
    echo "[]"
    return 0
  fi

  local result
  result=$(uv run python "$helper_script" get "$results_tsv" "$story_id" 2>/dev/null || echo "[]")
  echo "${result:-[]}"
}

# handle_story_failure <story_id> <current_retries> [failure_reason]
# Records the failure reason as an anti-pattern on the story (Strategy 1).
# Returns 0 always (non-fatal -- caller decides skip vs retry).
#
# When SPIRAL_ANTI_PATTERN_INJECT=true (default), appends failure_reason to
# _antiPatterns[] in prd.json so the next retry prompt shows a "FORBIDDEN
# APPROACHES" list and the agent tries a different implementation.
handle_story_failure() {
  local story_id="$1"
  local retries="$2"
  local failure_reason="${3:-}"
  local prd_file="${PRD_FILE:-prd.json}"
  local jq_bin="${JQ:-jq}"

  echo "[Phase I / retry] Story $story_id failed (attempt $((retries + 1)))"

  # Strategy 1: anti-pattern accumulation (structured with category)
  if [[ "${SPIRAL_ANTI_PATTERN_INJECT:-true}" == "true" && -n "$failure_reason" && -f "$prd_file" ]]; then
    # Truncate to 200 chars and strip characters unsafe for jq --arg
    local truncated
    truncated=$(printf '%s' "$failure_reason" | head -c 200 | tr -d '\n\r"\\')

    # Classify failure category from the reason text
    local category="unknown"
    case "$failure_reason" in
      *oversized_diff* | *diff\ size* | *too\ large*) category="oversized_diff" ;;
      *TypeError* | *type\ error* | *mypy*) category="type_error" ;;
      *lint* | *ruff* | *shellcheck* | *shfmt*) category="lint_error" ;;
      *test*fail* | *pytest* | *FAILED* | *assertion*) category="test_fail" ;;
      *import* | *ModuleNotFoundError*) category="import_error" ;;
      *timeout* | *timed\ out*) category="timeout" ;;
      *) category="runtime_error" ;;
    esac

    if [[ -n "$truncated" ]]; then
      atomic_patch_prd "$(dirname "$prd_file")" \
        '(.userStories[] | select(.id == $sid) | ._antiPatterns) |= (. // []) + [{
          "attempt": $attempt,
          "approach": $note,
          "category": $cat
        }]' \
        --arg sid "$story_id" --arg note "$truncated" \
        --arg cat "$category" --argjson attempt "$((retries + 1))" || true
      echo "[Phase I / retry] Anti-pattern recorded for $story_id [$cat]: ${truncated:0:60}..."
    fi
  fi
  return 0
}

# get_failure_type <stderr_file>
# Calls failure_categorizer.py on stderr output and returns one of 8 categories:
#   missing_dependency, syntax_error, type_error, test_assertion,
#   timeout, oom, context_overflow, other
# Returns "other" on any error or if stderr file is missing.
get_failure_type() {
  local stderr_file="${1:-}"
  local categorizer
  categorizer="$(dirname "${BASH_SOURCE[0]}")/../../lib/failure_categorizer.py"

  if [[ ! -f "$categorizer" || ! -f "$stderr_file" ]]; then
    echo "other"
    return 0
  fi

  local result
  result=$(uv run python -c "
from lib.failure_categorizer import categorize_failure
import sys
with open(sys.argv[1], encoding='utf-8', errors='replace') as f:
    stderr = f.read()
ftype, _ = categorize_failure(stderr, '')
print(ftype)
" "$stderr_file" 2>/dev/null) || result="other"
  echo "${result:-other}"
}

# select_retry_strategy <failure_type> <retry_count>
# Returns a retry strategy string based on failure classification.
# Strategies:
#   same_model    - retry with same model tier (error appended to prompt via anti-patterns)
#   scope_reduce  - call try_scope_reduction before retrying
#   extend_timeout - double the timeout for next attempt
#   decompose     - trigger story decomposition
#   skip          - mark story as skipped
#   escalate_model - escalate to next model tier (default/legacy behavior)
select_retry_strategy() {
  local failure_type="${1:-other}"
  local retry_count="${2:-0}"

  case "$failure_type" in
    missing_dependency | syntax_error | type_error)
      if [[ "$retry_count" -lt 2 ]]; then
        echo "same_model"
      else
        echo "escalate_model"
      fi
      ;;
    test_assertion)
      if [[ "$retry_count" -lt 1 ]]; then
        echo "same_model"
      elif [[ "$retry_count" -lt 2 ]]; then
        echo "escalate_model"
      else
        echo "skip"
      fi
      ;;
    context_overflow)
      if [[ "$retry_count" -lt 2 ]]; then
        echo "scope_reduce"
      else
        echo "skip"
      fi
      ;;
    timeout)
      if [[ "$retry_count" -lt 1 ]]; then
        echo "extend_timeout"
      elif [[ "$retry_count" -lt 2 ]]; then
        echo "decompose"
      else
        echo "skip"
      fi
      ;;
    oom)
      echo "skip"
      ;;
    *)
      # 'other' or unknown: use legacy escalation behavior
      if [[ "$retry_count" -lt 2 ]]; then
        echo "escalate_model"
      else
        echo "skip"
      fi
      ;;
  esac
}

# get_failed_files_for_story <story_id> [results_tsv_path]
# Reads results.tsv and returns a JSON array string of failed files from the
# most recent failed attempt for the given story. Returns "" if none found.
# Used by callers to build --files-only flag for Ralph retries (US-597).
get_failed_files_for_story() {
  local story_id="$1"
  local results_tsv="${2:-results.tsv}"
  local script_dir
  script_dir="$(dirname "${BASH_SOURCE[0]}")"

  if [[ ! -f "$results_tsv" ]]; then
    echo ""
    return 0
  fi

  local failed_json
  failed_json=$(uv run python "${script_dir}/file_aware_retry.py" get "$results_tsv" "$story_id" 2>/dev/null) || failed_json=""
  echo "$failed_json"
}

# try_scope_reduction <story_json_file> [budget_chars]
# Attempts to reduce story scope by deferring non-critical files (tests, docs, examples).
# Calls lib/scope_reducer.py reduce and writes the reduced story JSON to stdout.
# Returns 0 and prints reduced story JSON when reduction occurred (deferred > 0).
# Returns 1 if no reduction was possible (story already within budget or no noncritical files).
#
# Usage (US-744):
#   reduced_json=$(try_scope_reduction story_file.json 3000) && ...
try_scope_reduction() {
  local story_file="${1:-}"
  local budget="${2:-3000}"
  local scope_reducer
  scope_reducer="$(dirname "${BASH_SOURCE[0]}")/../scope_reducer.py"

  if [[ ! -f "$scope_reducer" || ! -f "$story_file" ]]; then
    echo "[Phase I / scope] scope_reducer.py or story file not found, skipping" >&2
    return 1
  fi

  local result
  result=$(uv run python "$scope_reducer" reduce "$story_file" --budget "$budget" 2>/dev/null) || {
    echo "[Phase I / scope] scope_reducer.py failed for $story_file" >&2
    return 1
  }

  local deferred_count
  deferred_count=$(printf '%s' "$result" | uv run python -c "
import json,sys
d=json.load(sys.stdin)
print(len(d.get('deferred_files',[])))
" 2>/dev/null) || deferred_count=0

  if [[ "$deferred_count" -gt 0 ]]; then
    echo "[Phase I / scope] Deferred $deferred_count non-critical files for scope reduction" >&2
    printf '%s' "$result" | uv run python -c "
import json,sys
d=json.load(sys.stdin)
print(json.dumps(d['reduced_story']))
" 2>/dev/null
    return 0
  else
    echo "[Phase I / scope] No non-critical files found to defer" >&2
    return 1
  fi
}

# build_files_only_args <failed_files_json>
# Converts a JSON array like '["src/a.py","lib/b.sh"]' into a space-separated
# string suitable for passing as --files-only args to a ralph command.
# Returns "" if input is empty or invalid (caller falls back to full retry).
build_files_only_args() {
  local failed_files_json="$1"

  if [[ -z "$failed_files_json" || "$failed_files_json" == "[]" ]]; then
    echo ""
    return 0
  fi

  local files_str
  files_str=$(uv run python -c "
import json, sys
try:
    files = json.loads(sys.argv[1])
    print(' '.join(str(f) for f in files if f))
except Exception:
    print('')
" "$failed_files_json" 2>/dev/null) || files_str=""
  echo "$files_str"
}

# extract_error_signature <log_file>
# Extracts structured error signature from ralph output.
# Calls failure_categorizer.py and returns JSON string:
#   '{"error_type":"timeout","error_message":"Error: execution timeout..."}'
# Returns '{"error_type":"other","error_message":"unknown error"}' on error.
extract_error_signature() {
  local log_file="${1:-}"

  if [[ ! -f "$log_file" ]]; then
    echo '{"error_type":"other","error_message":"log file not found"}'
    return 0
  fi

  local result
  result=$(uv run python -c "
import json, sys
from lib.failure_categorizer import categorize_failure
try:
    with open(sys.argv[1], encoding='utf-8', errors='replace') as f:
        output = f.read()
    ftype, fmsg = categorize_failure(output, '')
    print(json.dumps({'error_type': ftype, 'error_message': fmsg}))
except Exception as e:
    print(json.dumps({'error_type': 'other', 'error_message': str(e)[:200]}))
" "$log_file" 2>/dev/null)

  if [[ -z "$result" ]]; then
    result='{"error_type":"other","error_message":"extraction failed"}'
  fi
  echo "$result"
}

# get_error_hints <error_type>
# Returns targeted anti-pattern hint for a given error type.
# Hints are designed to guide the agent toward correcting the specific error.
get_error_hints() {
  local error_type="${1:-other}"

  case "$error_type" in
    missing_dependency)
      echo "Do NOT forget to import all required modules at the top of the file. Add missing imports before using them."
      ;;
    syntax_error)
      echo "Do NOT use invalid Python syntax. Check for unmatched brackets, quotes, or indentation errors. Fix all syntax issues."
      ;;
    type_error)
      echo "Do NOT pass arguments of incorrect types. Verify function signatures and ensure type compatibility. Use type hints to guide implementation."
      ;;
    test_assertion)
      echo "Do NOT make assumptions about test expectations. Re-read the test code and acceptance criteria carefully. Ensure implementation matches expected behavior."
      ;;
    timeout)
      echo "Do NOT use inefficient algorithms or infinite loops. Optimize performance and add timeouts to prevent hanging."
      ;;
    oom)
      echo "Do NOT create large objects in memory. Optimize data structures and avoid loading entire datasets at once."
      ;;
    context_overflow)
      echo "Do NOT provide overly verbose explanations or include unnecessary code. Keep implementation focused and concise."
      ;;
    *)
      echo "Do NOT repeat the same approach. Try a fundamentally different implementation strategy."
      ;;
  esac
}

# compare_error_signatures <sig1_json> <sig2_json>
# Compares two error signatures and returns:
#   'same' if error_type is identical
#   'different' if error_type differs
#   'unknown' if either signature is malformed
compare_error_signatures() {
  local sig1="${1:-}"
  local sig2="${2:-}"

  local type1 type2
  type1=$(echo "$sig1" | uv run python -c "import json,sys; d=json.load(sys.stdin); print(d.get('error_type','unknown'))" 2>/dev/null) || type1="unknown"
  type2=$(echo "$sig2" | uv run python -c "import json,sys; d=json.load(sys.stdin); print(d.get('error_type','unknown'))" 2>/dev/null) || type2="unknown"

  if [[ "$type1" == "unknown" || "$type2" == "unknown" ]]; then
    echo "unknown"
  elif [[ "$type1" == "$type2" ]]; then
    echo "same"
  else
    echo "different"
  fi
}
