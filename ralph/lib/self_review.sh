#!/usr/bin/env bash
# ralph/lib/self_review.sh -- Phase I.5: LLM self-review gate (US-145)
#
# Extracted from ralph.sh. Sourced after JQ, PRD_FILE, SPIRAL_SCRATCH_DIR,
# log_spiral_event are defined.

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

_REVIEW_TOKENS=0
run_self_review() {
  local story_id="$1"
  _REVIEW_TOKENS=0

  local _diff
  _diff=$(git diff HEAD 2>/dev/null | head -500)
  if [[ -z "$_diff" ]]; then
    _diff=$(git diff HEAD~1 HEAD 2>/dev/null | head -500)
  fi
  if [[ -z "$_diff" ]]; then
    echo "  [review] No diff to review -- Phase I.5 skipped"
    return 0
  fi

  local _story_title _story_desc _story_ac
  _story_title=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .title // \"\"" "$PRD_FILE" 2>/dev/null | tr -d '\r')
  _story_desc=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .description // \"\"" "$PRD_FILE" 2>/dev/null | tr -d '\r')
  _story_ac=$($JQ -r ".userStories[] | select(.id == \"$story_id\") | .acceptanceCriteria // [] | .[] | \"- \" + ." "$PRD_FILE" 2>/dev/null | tr -d '\r' | head -20)

  local _review_system
  _review_system='You are a senior code reviewer performing a pre-validation review. Given a story specification and a git diff, identify bugs, security issues, and spec deviations. Respond with ONLY a valid JSON object -- no markdown, no explanation -- matching exactly: {"issues":[{"severity":"critical|major|minor","location":"<file:line or description>","description":"<concise description of the issue>"}]}. Use severity "critical" only for bugs that will definitely cause test failures, security vulnerabilities, or hard spec violations. Use "major" for significant issues and "minor" for style/quality concerns. If there are no issues, respond with: {"issues":[]}'

  local _review_user
  _review_user="## Story Specification

Title: ${_story_title}
Description: ${_story_desc}

Acceptance Criteria:
${_story_ac:-  (none listed)}

## Git Diff (truncated to 500 lines)

\`\`\`diff
${_diff}
\`\`\`

Review the diff against the story specification above. Output ONLY the JSON object."

  local _review_model="${SPIRAL_SELF_REVIEW_MODEL:-haiku}"
  local _review_tmp="${SPIRAL_SCRATCH_DIR:-/tmp}/_review_raw_$$.tmp"
  mkdir -p "${SPIRAL_SCRATCH_DIR:-/tmp}"

  echo "  [Phase I.5] Sending ${#_diff} chars of diff to ${_review_model} for self-review..."
  (
    unset CLAUDECODE
    claude -p "$_review_user" \
      --model "$_review_model" \
      --append-system-prompt "$_review_system" \
      --betas prompt-caching-2024-07-31 \
      --max-turns 1 \
      --output-format stream-json \
      --dangerously-skip-permissions \
      </dev/null 2>/dev/null
  ) >"$_review_tmp" 2>/dev/null || true

  if [[ -f "$_review_tmp" ]]; then
    local _rl
    _rl=$(grep -m1 '"type":"result"' "$_review_tmp" 2>/dev/null || true)
    if [[ -n "$_rl" ]]; then
      local _ri _ro
      _ri=$($JQ -r '.usage.input_tokens // 0' <<<"$_rl" 2>/dev/null || echo 0)
      _ro=$($JQ -r '.usage.output_tokens // 0' <<<"$_rl" 2>/dev/null || echo 0)
      [[ "$_ri" =~ ^[0-9]+$ ]] && [[ "$_ro" =~ ^[0-9]+$ ]] && _REVIEW_TOKENS=$((_ri + _ro)) || _REVIEW_TOKENS=0
    fi
  fi

  local _review_text=""
  if [[ -f "$_review_tmp" ]]; then
    local _rl2
    _rl2=$(grep -m1 '"type":"result"' "$_review_tmp" 2>/dev/null || true)
    if [[ -n "$_rl2" ]]; then
      _review_text=$($JQ -r '.result // ""' <<<"$_rl2" 2>/dev/null | tr -d '\r' || true)
    fi
  fi
  rm -f "$_review_tmp"

  _review_text=$(printf '%s' "$_review_text" | sed 's/^```json[[:space:]]*//' | sed 's/^```[[:space:]]*//' | sed 's/```[[:space:]]*$//' | tr -d '\r')

  local _critical_count=0 _total_count=0
  if [[ -n "$_review_text" ]] && echo "$_review_text" | $JQ empty 2>/dev/null; then
    _critical_count=$(echo "$_review_text" | $JQ '[.issues[] | select(.severity == "critical")] | length' 2>/dev/null || echo 0)
    _total_count=$(echo "$_review_text" | $JQ '.issues | length' 2>/dev/null || echo 0)
    [[ "$_critical_count" =~ ^[0-9]+$ ]] || _critical_count=0
    [[ "$_total_count" =~ ^[0-9]+$ ]] || _total_count=0
  else
    echo "  [Phase I.5] WARNING: review response was not valid JSON -- treating as no issues"
    echo "  [Phase I.5] Raw response (first 200 chars): ${_review_text:0:200}"
    _REVIEW_TOKENS=0
    return 0
  fi

  echo "  [Phase I.5] Review complete: ${_total_count} issue(s) (${_critical_count} critical) | tokens: ${_REVIEW_TOKENS}"
  log_spiral_event "self_review" \
    "\"story_id\":\"$story_id\",\"critical\":${_critical_count},\"total\":${_total_count},\"review_tokens\":${_REVIEW_TOKENS}"

  if [[ "$_critical_count" -gt 0 ]]; then
    echo "  [Phase I.5] Critical issues found -- re-entering Phase I:"
    echo "$_review_text" | $JQ -r '.issues[] | select(.severity == "critical") | "    - [\(.severity)] \(.location): \(.description)"' 2>/dev/null || true

    local _issues_json
    _issues_json=$(echo "$_review_text" | $JQ -c '.issues // []' 2>/dev/null || echo '[]')
    $JQ --argjson issues "$_issues_json" \
      "(.userStories[] | select(.id == \"$story_id\") | ._selfReviewIssues) = \$issues" \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true

    return 1
  fi

  return 0
}
