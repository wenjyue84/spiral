#!/bin/bash
# lib/crash_capture.sh — Capture worker crash tracebacks to .spiral/crashes/
# Source this file in spiral.sh; functions are called after ralph exits non-zero.
# US-279

# ── capture_crash — persist stderr/crash output to .spiral/crashes/ ──────────
# Args: $1=story_id  $2=exit_code  $3=worker_id  $4=stderr_file_or_log
# Writes crash file + updates index.json atomically.
capture_crash() {
  local story_id="${1:?capture_crash: story_id required}"
  local exit_code="${2:?capture_crash: exit_code required}"
  local worker_id="${3:-sequential}"
  local source_file="${4:-}"
  local scratch_dir="${SCRATCH_DIR:-.spiral}"

  local crash_dir="$scratch_dir/crashes"
  mkdir -p "$crash_dir"

  local ts
  ts=$(date -u +"%Y%m%dT%H%M%SZ")
  local crash_file="${crash_dir}/${story_id}_${ts}.txt"

  # Write crash content: from source file (stderr capture or worker log)
  if [[ -n "$source_file" && -f "$source_file" ]]; then
    # Extract last 200 lines (likely contains traceback + context)
    tail -200 "$source_file" > "$crash_file" 2>/dev/null || true
  else
    echo "No stderr capture available (exit_code=$exit_code)" > "$crash_file"
  fi

  # Prepend header
  local header
  header="# SPIRAL Crash Report
# Story:     $story_id
# Worker:    $worker_id
# Exit Code: $exit_code
# Timestamp: $ts
# ─────────────────────────────────────────
"
  local tmp_crash="${crash_file}.tmp"
  { printf '%s\n' "$header"; cat "$crash_file"; } > "$tmp_crash" 2>/dev/null && \
    mv "$tmp_crash" "$crash_file" || true

  # Update index.json atomically (temp-file rename)
  _update_crash_index "$crash_dir" "$story_id" "$ts" "$exit_code" "$worker_id" \
    "$(basename "$crash_file")"

  echo "  [crash] Captured crash for $story_id → $(basename "$crash_file")"
}

# ── _update_crash_index — append entry to index.json (atomic) ────────────────
_update_crash_index() {
  local crash_dir="$1"
  local story_id="$2"
  local timestamp="$3"
  local exit_code="$4"
  local worker_id="$5"
  local crash_file="$6"

  local index_file="$crash_dir/index.json"
  local tmp_index="${index_file}.tmp.$$"

  # Read existing index or start with empty array
  local existing="[]"
  if [[ -f "$index_file" ]]; then
    existing=$(cat "$index_file" 2>/dev/null || echo "[]")
    # Validate it's valid JSON array
    if ! echo "$existing" | "$JQ" 'type == "array"' >/dev/null 2>&1; then
      existing="[]"
    fi
  fi

  # Append new entry
  local new_entry
  new_entry=$("$JQ" -n \
    --arg sid "$story_id" \
    --arg ts "$timestamp" \
    --arg ec "$exit_code" \
    --arg wid "$worker_id" \
    --arg cf "$crash_file" \
    '{story_id: $sid, timestamp: $ts, exit_code: ($ec | tonumber), worker_id: $wid, crash_file: $cf}')

  echo "$existing" | "$JQ" --argjson entry "$new_entry" '. + [$entry]' \
    > "$tmp_index" 2>/dev/null && \
    mv "$tmp_index" "$index_file" || {
      rm -f "$tmp_index" 2>/dev/null
      return 1
    }
}

# ── prune_old_crashes — remove crash files older than retention period ────────
# Called on startup. Retention controlled by SPIRAL_CRASH_RETENTION_DAYS (default: 7).
prune_old_crashes() {
  local scratch_dir="${SCRATCH_DIR:-.spiral}"
  local crash_dir="$scratch_dir/crashes"
  local retention_days="${SPIRAL_CRASH_RETENTION_DAYS:-7}"

  [[ -d "$crash_dir" ]] || return 0

  local pruned=0

  # Prune crash text files older than retention
  while IFS= read -r -d '' old_file; do
    rm -f "$old_file" 2>/dev/null && pruned=$((pruned + 1))
  done < <(find "$crash_dir" -maxdepth 1 -name "*.txt" -type f -mtime +"$retention_days" -print0 2>/dev/null)

  # Rebuild index.json to remove entries for deleted files
  if [[ "$pruned" -gt 0 ]]; then
    local index_file="$crash_dir/index.json"
    if [[ -f "$index_file" ]]; then
      local tmp_index="${index_file}.tmp.$$"
      # Keep only entries whose crash_file still exists
      "$JQ" --arg dir "$crash_dir" \
        '[.[] | select(($dir + "/" + .crash_file) as $path | $path | test(".*"))]' \
        "$index_file" > "$tmp_index" 2>/dev/null || true
      # Re-filter to only existing files (jq can't check filesystem)
      local rebuilt="[]"
      if [[ -f "$tmp_index" ]]; then
        while IFS= read -r entry; do
          local cf
          cf=$(echo "$entry" | "$JQ" -r '.crash_file' 2>/dev/null)
          if [[ -f "$crash_dir/$cf" ]]; then
            rebuilt=$(echo "$rebuilt" | "$JQ" --argjson e "$entry" '. + [$e]')
          fi
        done < <("$JQ" -c '.[]' "$tmp_index" 2>/dev/null)
        echo "$rebuilt" > "$tmp_index" && mv "$tmp_index" "$index_file"
      fi
      rm -f "$tmp_index" 2>/dev/null
    fi
    echo "  [crash] Pruned $pruned crash file(s) older than ${retention_days} days"
  fi
}

# ── report_recent_crashes — show N most recent crashes (for spiral-doctor) ────
# Args: $1=count (default: 5)
report_recent_crashes() {
  local count="${1:-5}"
  local scratch_dir="${SCRATCH_DIR:-.spiral}"
  local crash_dir="$scratch_dir/crashes"
  local index_file="$crash_dir/index.json"

  if [[ ! -f "$index_file" ]]; then
    echo "  [doctor] [OK] No crash history found"
    return 0
  fi

  local total
  total=$("$JQ" 'length' "$index_file" 2>/dev/null || echo "0")

  if [[ "$total" -eq 0 ]]; then
    echo "  [doctor] [OK] No crashes recorded"
    return 0
  fi

  echo "  [doctor] [WARN] $total crash(es) recorded — showing last $count:"
  "$JQ" -r "sort_by(.timestamp) | reverse | .[:$count][] |
    \"    \\(.timestamp) | \\(.story_id) | exit \\(.exit_code) | worker \\(.worker_id) | \\(.crash_file)\"" \
    "$index_file" 2>/dev/null || echo "    (failed to read crash index)"
  return 0
}
