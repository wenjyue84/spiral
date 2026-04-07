#!/usr/bin/env bash
# ralph/lib/story_lifecycle.sh — Story retry, decomposition, classification, experience capture
#
# Extracted from ralph.sh to reduce monolith size.
# Sourced by ralph.sh after JQ, PRD_FILE, PROGRESS_FILE, log_ralph_event are defined.

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# ── Retry tracking ───────────────────────────────────────────────
RETRY_FILE="retry-counts.json"
if [[ ! -f "$RETRY_FILE" ]] || ! $JQ -e . "$RETRY_FILE" >/dev/null 2>&1; then
  echo '{}' >"$RETRY_FILE"
fi
MAX_RETRIES=3
ESCALATION_FILE="escalation-counts.json"
MAX_ESCALATIONS=2

get_retry_count() {
  local story_id="$1"
  $JQ -r ".\"$story_id\" // 0" "$RETRY_FILE" | tr -d '\r'
}

increment_retry() {
  local story_id="$1"
  local current
  current=$(get_retry_count "$story_id")
  $JQ ".\"$story_id\" = $((current + 1))" "$RETRY_FILE" >"${RETRY_FILE}.tmp"
  mv "${RETRY_FILE}.tmp" "$RETRY_FILE"
}

reset_retry() {
  local story_id="$1"
  $JQ "del(.\"$story_id\")" "$RETRY_FILE" >"${RETRY_FILE}.tmp"
  mv "${RETRY_FILE}.tmp" "$RETRY_FILE"
}

if [[ ! -f "$ESCALATION_FILE" ]] || ! $JQ -e . "$ESCALATION_FILE" >/dev/null 2>&1; then
  echo '{}' >"$ESCALATION_FILE"
fi

get_escalation_count() {
  local story_id="$1"
  $JQ -r ".\"$story_id\" // 0" "$ESCALATION_FILE" | tr -d '\r'
}

increment_escalation() {
  local story_id="$1"
  local current
  current=$(get_escalation_count "$story_id")
  $JQ ".\"$story_id\" = $((current + 1))" "$ESCALATION_FILE" >"${ESCALATION_FILE}.tmp"
  mv "${ESCALATION_FILE}.tmp" "$ESCALATION_FILE"
}

reset_escalation() {
  local story_id="$1"
  $JQ "del(.\"$story_id\")" "$ESCALATION_FILE" >"${ESCALATION_FILE}.tmp"
  mv "${ESCALATION_FILE}.tmp" "$ESCALATION_FILE"
}

# ── Story completeness check (US-250) ────────────────────────────────
check_story_completeness() {
  local story_id="$1"
  local prd_file="$2"
  local title description ac_count
  title=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .title // empty" "$prd_file" | tr -d '\r')
  description=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .description // empty" "$prd_file" | tr -d '\r')
  ac_count=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .acceptanceCriteria // [] | length" "$prd_file" | tr -d '\r')
  if [[ -z "$title" || -z "$description" || "$ac_count" -eq 0 ]]; then
    echo "  [completeness] INCOMPLETE: title=$([[ -n "$title" ]] && echo "Y" || echo "N"), description=$([[ -n "$description" ]] && echo "Y" || echo "N"), acceptanceCriteria=$([[ "$ac_count" -gt 0 ]] && echo "Y" || echo "N")"
    return 1
  fi
  return 0
}

# ── Story decomposition ──────────────────────────────────────────
decompose_story() {
  local story_id="$1"
  local model="${2:-sonnet}"
  local from_parent
  from_parent=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | ._decomposedFrom // \"\"" "$PRD_FILE" | tr -d '\r')
  if [[ -n "$from_parent" ]]; then
    echo "  [decompose] $story_id is a sub-story of $from_parent -- skipping decomposition"
    return 1
  fi
  local python_cmd="${SPIRAL_PYTHON:-python3}"
  local decompose_script
  decompose_script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd)/lib/workers/decompose_story.py"
  if [[ ! -f "$decompose_script" ]]; then
    echo "  [decompose] decompose_story.py not found -- skipping"
    return 1
  fi
  local _fail_reason
  _fail_reason=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | ._failureReason // \"\"" "$PRD_FILE" 2>/dev/null | tr -d '\r' || true)
  local _git_root
  _git_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
  echo "  [decompose] Decomposing $story_id (failure: ${_fail_reason:-unknown})..."
  if "$python_cmd" "$decompose_script" \
    --prd "$PRD_FILE" --story-id "$story_id" --progress "$PROGRESS_FILE" \
    --git-root "$_git_root" --failure-reason "${_fail_reason:-}" --model "$model"; then
    echo "  [decompose] $story_id decomposed successfully"
    TOTAL_STORIES=$($JQ '[.userStories | length] | .[0]' "$PRD_FILE")
    return 0
  else
    echo "  [decompose] Failed to decompose $story_id -- will skip instead"
    return 1
  fi
}

# ── Auto-decompose at retry threshold ────────────────────────────
maybe_auto_decompose() {
  local story_id="$1" retry_now="$2" model="${3:-sonnet}"
  local threshold="${SPIRAL_DECOMPOSE_THRESHOLD:-2}"
  [[ "$threshold" -eq 0 ]] && return 1

  # Early aggressive decomposition on first failure for complex stories
  if [[ "${SPIRAL_DECOMPOSE_ON_FIRST_FAIL:-false}" == "true" && "$retry_now" -eq 1 ]]; then
    local complexity title_words complexity_rank threshold_rank
    local first_fail_complexity="${SPIRAL_DECOMPOSE_FIRST_FAIL_COMPLEXITY:-medium}"
    complexity=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .estimatedComplexity // \"medium\"" \
      "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo "medium")
    title_words=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .title // \"\"" \
      "$PRD_FILE" 2>/dev/null | wc -w || echo "0")
    case "$complexity" in small) complexity_rank=1 ;; medium) complexity_rank=2 ;; *) complexity_rank=3 ;; esac
    case "$first_fail_complexity" in small) threshold_rank=1 ;; medium) threshold_rank=2 ;; *) threshold_rank=3 ;; esac
    if [[ "$complexity_rank" -ge "$threshold_rank" || "$title_words" -gt 12 ]]; then
      echo "  [early-decompose] SPIRAL_DECOMPOSE_ON_FIRST_FAIL=true -- decomposing $story_id at retry 1 (complexity=$complexity, title_words=$title_words)"
      log_ralph_event "early_decompose" \
        "\"storyId\":\"$story_id\",\"complexity\":\"$complexity\",\"titleWords\":$title_words,\"threshold\":\"$first_fail_complexity\""
      if decompose_story "$story_id" "$model"; then
        $JQ "(.userStories[] | select(.id == \"$story_id\") | ._failureReason) = \"early_decomposed_on_first_fail\"" \
          "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
        $JQ "(.userStories[] | select(.id == \"$story_id\") | ._skipped) = true" \
          "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
        local child_ids
        child_ids=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | ._decomposedInto // [] | join(\",\")" \
          "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo "")
        log_ralph_event "early_decompose_done" \
          "\"storyId\":\"$story_id\",\"retryCount\":$retry_now,\"childIds\":\"$child_ids\""
        echo "EARLY-DECOMPOSED: $story_id at retry 1 (complexity=$complexity) -> $child_ids" >>"$PROGRESS_FILE"
        reset_retry "$story_id"
        return 0
      else
        echo "  [early-decompose] Decomposition failed for $story_id -- falling back to normal retry"
      fi
    fi
  fi

  [[ "$retry_now" -lt "$threshold" || "$retry_now" -ge "$MAX_RETRIES" ]] && return 1

  echo "  [auto-decompose] $story_id reached threshold $threshold after $retry_now attempt(s) -- decomposing early"
  if decompose_story "$story_id" "$model"; then
    $JQ "(.userStories[] | select(.id == \"$story_id\") | ._failureReason) = \"auto_decomposed\"" \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
    $JQ "(.userStories[] | select(.id == \"$story_id\") | ._skipped) = true" \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
    local child_ids
    child_ids=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | ._decomposedInto // [] | join(\",\")" \
      "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo "")
    log_ralph_event "auto_decompose" \
      "\"storyId\":\"$story_id\",\"retryCount\":$retry_now,\"threshold\":$threshold,\"childIds\":\"$child_ids\""
    echo "AUTO-DECOMPOSED: $story_id at retry $retry_now (threshold $threshold) -> $child_ids" >>"$PROGRESS_FILE"
    reset_retry "$story_id"
    return 0
  else
    echo "  [auto-decompose] decomposition failed for $story_id -- continuing with normal retry"
    return 1
  fi
}

# ── Results ledger ──────────────────────────────────────────────
RESULTS_FILE="results.tsv"
append_result() {
  local status="$1" commit_sha="${2:-}"
  local ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  local duration_sec=$((STORY_END - STORY_START))
  local model_col="${EFFECTIVE_MODEL:-${EFFECTIVE_TOOL:-unknown}}"
  if [[ ! -f "$RESULTS_FILE" ]]; then
    printf 'timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\twall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\tdecompose_secs\timpl_secs\tverify_secs\tretry_escalation_count\tfailure_root_cause\tfailed_files\tscope_tag\terror_signature\n' >"$RESULTS_FILE"
  fi
  local safe_title="${STORY_TITLE//$'\t'/ }"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$ts" "${SPIRAL_ITER:-0}" "$ITERATION" "$NEXT_STORY" "$safe_title" \
    "$status" "$duration_sec" "$model_col" "$RETRY_NOW" "$commit_sha" "${SPIRAL_RUN_ID:-}" \
    "${_CACHE_HIT:-false}" "${_CACHE_READ_TOKENS:-0}" "${_CACHE_CREATION_TOKENS:-0}" "${_REVIEW_TOKENS:-0}" \
    "${_WALL_SEC:-0}" "${_USER_CPU_S:-0}" "${_SYS_CPU_S:-0}" "${_PEAK_RSS_KB:-0}" \
    "${STORY_BATCH_ID:-}" \
    "${_DECOMPOSE_SECS:-0}" "${_IMPL_SECS:-0}" "${_VERIFY_SECS:-0}" "${_RETRY_ESCALATION_COUNT:-0}" \
    "${_FAILURE_ROOT_CAUSE:-}" "${_FAILED_FILES:-}" "${SPIRAL_SCOPE_TAG:-}" "${_ERROR_SIGNATURE:-}" \
    >>"$RESULTS_FILE"
}

# ── Failure root-cause classifier (US-547) ───────────────────────
classify_failure_root_cause() {
  local reason="${1:-}"
  local category="unknown"
  if echo "$reason" | grep -qiE 'exceeds.*max_tokens|max_tokens.*exceed|context.?length|token.?limit|context.?window|scope_exceeded|too.?large|time.?budget'; then
    category="scope_exceeded"
  elif echo "$reason" | grep -qiE 'rate.?limit|ratelimit|429|quota.?exceeded|too.?many.?requests|api_rate_limit'; then
    category="api_rate_limit"
  elif echo "$reason" | grep -qiE 'TypeError|ImportError|SyntaxError|AttributeError|NameError|type_error'; then
    category="type_error"
  elif echo "$reason" | grep -qiE 'timed?.?out|TimeoutError|timeout.*expired|deadline.?exceeded|validation_timeout|TIME_BUDGET'; then
    category="validation_timeout"
  elif echo "$reason" | grep -qiE 'model.{0,20}not.{0,20}capable|unsupported.{0,20}model|capability.{0,20}gap|model_capability_gap'; then
    category="model_capability_gap"
  fi
  _FAILURE_ROOT_CAUSE="$category"
  local log_dir="${REPO_ROOT:-.}/.spiral/logs"
  mkdir -p "$log_dir"
  local log_file="$log_dir/phase-i-${SPIRAL_ITER:-0}.log"
  {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] FAILURE_ROOT_CAUSE: $category"
    echo "  story_id=${NEXT_STORY:-unknown} retry=${RETRY_NOW:-0} reason=${reason:-none}"
  } >>"$log_file"
}

# ── Experience capture: exhausted-story summary ─────────────────
save_candidate_experience() {
  local story_id="$1"
  local candidate_file="${SPIRAL_CANDIDATE_FILE:-candidate_us.md}"
  local title description complexity failure_reason
  title=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .title // \"(unknown)\"" \
    "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo "(unknown)")
  description=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .description // \"\"" \
    "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo "")
  complexity=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .estimatedComplexity // \"medium\"" \
    "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo "medium")
  failure_reason=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | ._failureReason // \"(not recorded)\"" \
    "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo "(not recorded)")
  local ac_list
  ac_list=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .acceptanceCriteria // [] | .[] | \"- \" + ." \
    "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo "- (none)")
  local anti_patterns
  anti_patterns=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | ._antiPatterns // [] | to_entries[] | \"\(.key+1). \(.value)\"" \
    "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo "(none)")
  local progress_notes=""
  if [[ -f "${PROGRESS_FILE:-progress.txt}" ]]; then
    progress_notes=$(grep -A 12 -B 1 "$story_id" "${PROGRESS_FILE:-progress.txt}" 2>/dev/null | tail -30 || true)
  fi
  if [[ ! -f "$candidate_file" ]]; then
    {
      echo "# candidate_us.md -- Exhausted Story Experience Log"
      echo ""
      echo "Stories listed here hit MAX_RETRIES without passing. Each entry captures"
      echo "what was tried and why it failed, so future attempts start with better context."
      echo ""
    } >"$candidate_file"
  fi
  {
    echo ""
    echo "## [$story_id] $title"
    echo ""
    echo "**Status:** Exhausted (${MAX_RETRIES} attempts) | **Complexity:** $complexity | **Date:** $(date '+%Y-%m-%d')"
    echo ""
    echo "### Description"
    echo "$description"
    echo ""
    echo "### Why it failed"
    echo '```'
    echo "$failure_reason"
    echo '```'
    echo ""
    echo "### Anti-patterns -- do NOT repeat these"
    if [[ -n "$anti_patterns" && "$anti_patterns" != "(none)" ]]; then
      echo "$anti_patterns"
    else
      echo "(none recorded)"
    fi
    echo ""
    echo "### Progress notes from last attempts"
    echo '```'
    echo "${progress_notes:-(none found)}"
    echo '```'
    echo ""
    echo "### Acceptance Criteria (re-attempt checklist)"
    echo "$ac_list"
    echo ""
    echo "---"
  } >>"$candidate_file"
  echo "  [candidate] [$story_id] experience saved -> $candidate_file"
  log_ralph_event "candidate_saved" \
    "\"storyId\":\"$story_id\",\"complexity\":\"$complexity\",\"file\":\"$candidate_file\""
}
