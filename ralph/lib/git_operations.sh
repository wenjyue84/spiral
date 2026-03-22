#!/usr/bin/env bash
# ralph/lib/git_operations.sh — Git commit, reset, and conventional commit message builder
#
# Extracted from ralph.sh to reduce monolith size.
# Sourced by ralph.sh after JQ, PRD_FILE, log_ralph_event are defined.

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

do_git_commit() {
  local msg="$1"
  if declare -f policy_check >/dev/null 2>&1 && ! policy_check "git_commit" "I"; then
    echo "  [policy] BLOCKED: git_commit denied by .spiral/policy.json"
    declare -f policy_log_violation >/dev/null 2>&1 &&
      policy_log_violation "$PRD_FILE" "${NEXT_STORY:-}" "git_commit" "I" "${JQ:-jq}"
    log_ralph_event "policy_violation" \
      "\"story_id\":\"${NEXT_STORY:-}\",\"operation\":\"git_commit\",\"phase\":\"I\"" 2>/dev/null || true
    return 1
  fi
  if [[ -n "${SPIRAL_GIT_AUTHOR:-}" ]]; then
    local email="${SPIRAL_GIT_EMAIL:-spiral@noreply.local}"
    msg="${msg}
Generated-By: SPIRAL"
    git -c "user.name=${SPIRAL_GIT_AUTHOR}" -c "user.email=${email}" commit -m "$msg"
  else
    git commit -m "$msg"
  fi
}

do_story_reset() {
  local baseline="${1:-}"
  if declare -f policy_check >/dev/null 2>&1; then
    if ! policy_check "story_reset" "I"; then
      echo "  [policy] BLOCKED: story_reset denied by .spiral/policy.json"
      declare -f policy_log_violation >/dev/null 2>&1 &&
        policy_log_violation "$PRD_FILE" "${NEXT_STORY:-}" "story_reset" "I" "${JQ:-jq}"
      log_ralph_event "policy_violation" \
        "\"story_id\":\"${NEXT_STORY:-}\",\"operation\":\"story_reset\",\"phase\":\"I\"" 2>/dev/null || true
      return 0
    fi
  fi
  if [[ -n "$baseline" ]]; then
    git reset --hard "$baseline" 2>/dev/null || git checkout -- . 2>/dev/null || true
  else
    git checkout -- . 2>/dev/null || true
  fi
}

build_commit_msg() {
  local story_id="${1:-}" story_title="${2:-}" story_tags_csv="${3:-}"
  local first_file="${4:-}" spiral_run_id="${5:-}" iteration="${6:-}" duration="${7:-}"

  local commit_type="feat"
  local tag
  IFS=',' read -ra _tags <<<"$story_tags_csv"
  for tag in "${_tags[@]}"; do
    tag="${tag// /}"
    case "$tag" in
      feat | fix | chore | refactor | test | docs | perf | ci | build | style)
        commit_type="$tag"
        break
        ;;
    esac
  done

  local commit_scope=""
  if [[ -n "$first_file" ]]; then
    first_file="${first_file#./}"
    local top_dir="${first_file%%/*}"
    [[ "$top_dir" == "$first_file" ]] && top_dir="${first_file%.*}"
    commit_scope="$top_dir"
  fi

  local subject
  if [[ -n "$commit_scope" ]]; then
    subject="${commit_type}(${commit_scope}): ${story_title}"
  else
    subject="${commit_type}: ${story_title}"
  fi

  local body="Completed by Ralph iteration ${iteration} (${duration}m)"
  local trailers="Story: ${story_id}"
  [[ -n "$spiral_run_id" ]] && trailers="${trailers}
SPIRAL-Run: ${spiral_run_id}"

  printf '%s\n\n%s\n\n%s\n' "$subject" "$body" "$trailers"
}
