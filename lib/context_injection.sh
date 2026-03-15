#!/usr/bin/env bash
# lib/context_injection.sh — US-280: File context injection (diff or full)
#
# Exports: build_files_context()
#
# Usage:
#   source lib/context_injection.sh
#   output=$(build_files_context "$story_json")

# ── build_files_context ───────────────────────────────────────────────────────
# Reads filesTouch from STORY_JSON; returns context text on stdout.
#
# SPIRAL_CONTEXT_MODE=diff  → git diff HEAD~N -- files (default)
# SPIRAL_CONTEXT_MODE=full  → cat each file
#
# Falls back to full content when diff is empty (new file).
# Truncates at SPIRAL_MAX_DIFF_LINES with a notice.
#
# Args:
#   $1 — story JSON string (must contain .filesTouch array)
#
# Env:
#   SPIRAL_CONTEXT_MODE  (diff|full, default: diff)
#   SPIRAL_DIFF_DEPTH    (integer, default: 3)
#   SPIRAL_MAX_DIFF_LINES (integer, default: 500; 0 = no limit)
#   JQ                   (path to jq binary)
build_files_context() {
  local story_json="$1"
  local context_mode="${SPIRAL_CONTEXT_MODE:-diff}"
  local diff_depth="${SPIRAL_DIFF_DEPTH:-3}"
  local max_lines="${SPIRAL_MAX_DIFF_LINES:-500}"
  local jq_bin="${JQ:-jq}"

  # Extract filesTouch array as newline-separated list
  local files_list
  files_list=$(printf '%s' "$story_json" | "$jq_bin" -r '(.filesTouch // []) | .[]' 2>/dev/null | tr -d '\r' || true)
  if [[ -z "$files_list" ]]; then
    return 0  # nothing to inject
  fi

  local output=""
  local total_lines=0
  local truncated=0

  while IFS= read -r fpath; do
    [[ -z "$fpath" ]] && continue
    local file_section=""

    if [[ "$context_mode" == "diff" ]]; then
      # Compute diff against HEAD~N for this file
      local diff_out
      diff_out=$(git diff --unified=5 "HEAD~${diff_depth}" -- "$fpath" 2>/dev/null || true)
      if [[ -z "$diff_out" ]]; then
        # Empty diff: new file or unchanged relative to HEAD~N; fall back to full content
        if [[ -f "$fpath" ]]; then
          local full_out
          full_out=$(cat "$fpath" 2>/dev/null || true)
          if [[ -n "$full_out" ]]; then
            file_section="### File (new/unchanged): $fpath
\`\`\`
${full_out}
\`\`\`"
          fi
        fi
      else
        file_section="### Diff (last ${diff_depth} commits): $fpath
\`\`\`diff
${diff_out}
\`\`\`"
      fi
    else
      # Full mode: read entire file
      if [[ -f "$fpath" ]]; then
        local full_out
        full_out=$(cat "$fpath" 2>/dev/null || true)
        if [[ -n "$full_out" ]]; then
          file_section="### File: $fpath
\`\`\`
${full_out}
\`\`\`"
        fi
      fi
    fi

    if [[ -z "$file_section" ]]; then
      continue
    fi

    # Count lines in this section
    local section_lines
    section_lines=$(printf '%s\n' "$file_section" | wc -l)

    if [[ "$max_lines" -gt 0 && $(( total_lines + section_lines )) -gt "$max_lines" ]]; then
      # Truncate: take only the remaining budget
      local remaining=$(( max_lines - total_lines ))
      if [[ "$remaining" -gt 0 ]]; then
        file_section=$(printf '%s\n' "$file_section" | head -n "$remaining")
        file_section="${file_section}
[... truncated at SPIRAL_MAX_DIFF_LINES=${max_lines} ...]"
      else
        file_section="[... $fpath omitted — SPIRAL_MAX_DIFF_LINES=${max_lines} reached ...]"
      fi
      truncated=1
    fi

    output="${output}${file_section}

"
    total_lines=$(( total_lines + section_lines ))
    [[ "$truncated" -eq 1 ]] && break
  done <<<"$files_list"

  if [[ -n "$output" ]]; then
    printf '## File Context (SPIRAL_CONTEXT_MODE=%s)\n\n%s' "$context_mode" "$output"
  fi
}
