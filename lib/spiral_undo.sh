#!/usr/bin/env bash
# lib/spiral_undo.sh — Per-story undo stack for idempotent tool execution (US-239)
#
# Provides a lightweight JSONL undo log stored at .spiral/undo/STORY_ID.jsonl.
# Each destructive operation (checkpoint, branch_create, git_commit) is recorded
# before execution so the worktree can be cleanly restored on failure.
#
# Functions exported:
#   undo_log_record  <story_id> <operation> <target> <inverse_command>
#   undo_log_replay  <story_id>   — execute inverse_commands in reverse order
#   undo_log_cleanup <story_id>   — delete the undo log on successful merge
#   undo_log_exists  <story_id>   — returns 0 if log exists, 1 otherwise
#
# Undo log directory: ${SPIRAL_SCRATCH_DIR:-.spiral}/undo/
# Undo log format  : JSONL, one entry per line:
#   {"operation":"<op>","target":"<target>","inverse_command":"<cmd>","timestamp":"<ISO8601>"}

# ── Directory helper ──────────────────────────────────────────────────────────
_undo_log_path() {
  local story_id="$1"
  local undo_dir="${SPIRAL_SCRATCH_DIR:-.spiral}/undo"
  mkdir -p "$undo_dir"
  echo "$undo_dir/${story_id}.jsonl"
}

# ── undo_log_record ───────────────────────────────────────────────────────────
# Append one undo entry to the story's undo log.
#
# Args:
#   $1  story_id        e.g. "US-042"
#   $2  operation       "checkpoint" | "branch_create" | "git_commit"
#   $3  target          human-readable target (branch name, file path, SHA, …)
#   $4  inverse_command shell command that undoes the operation
undo_log_record() {
  local story_id="$1"
  local operation="$2"
  local target="$3"
  local inverse_command="$4"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local log_path
  log_path="$(_undo_log_path "$story_id")"

  # Escape double-quotes in fields to keep JSONL valid
  local safe_target safe_inverse
  safe_target="${target//\"/\\\"}"
  safe_inverse="${inverse_command//\"/\\\"}"

  printf '{"operation":"%s","target":"%s","inverse_command":"%s","timestamp":"%s"}\n' \
    "$operation" "$safe_target" "$safe_inverse" "$ts" \
    >> "$log_path"
}

# ── undo_log_replay ───────────────────────────────────────────────────────────
# Read the undo log for a story and execute each inverse_command in reverse
# order (last-in, first-out).  Stops on the first failed command.
#
# Returns:
#   0  all inverse commands succeeded (or log was empty / didn't exist)
#   1  at least one inverse command failed
undo_log_replay() {
  local story_id="$1"
  local log_path
  log_path="$(_undo_log_path "$story_id")"

  if [[ ! -f "$log_path" ]]; then
    echo "  [undo] No undo log found for $story_id"
    return 0
  fi

  echo "  [undo] Replaying undo log for $story_id (reverse order)..."

  # Read all lines into an array, then iterate in reverse
  local -a entries=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && entries+=("$line")
  done < "$log_path"

  local count="${#entries[@]}"
  if [[ "$count" -eq 0 ]]; then
    echo "  [undo] Undo log is empty — nothing to replay"
    return 0
  fi

  local failed=0
  for (( i = count - 1; i >= 0; i-- )); do
    local entry="${entries[$i]}"
    # Extract fields with simple parameter expansion (no jq dependency)
    local op inv_cmd
    op="$(echo "$entry" | grep -o '"operation":"[^"]*"' | cut -d'"' -f4)"
    inv_cmd="$(echo "$entry" | grep -o '"inverse_command":"[^"]*"' | cut -d'"' -f4)"

    echo "  [undo] [$op] running: $inv_cmd"
    if ! eval "$inv_cmd" 2>&1; then
      echo "  [undo] WARNING: inverse command failed for operation '$op'"
      failed=1
    fi
  done

  if [[ "$failed" -eq 0 ]]; then
    echo "  [undo] Replay complete — worktree restored to pre-story state"
  else
    echo "  [undo] Replay finished with errors — manual inspection may be needed"
  fi

  return "$failed"
}

# ── undo_log_cleanup ──────────────────────────────────────────────────────────
# Remove the undo log after the story successfully merges.
# This signals that the state is committed and no rollback is needed.
undo_log_cleanup() {
  local story_id="$1"
  local log_path
  log_path="$(_undo_log_path "$story_id")"
  if [[ -f "$log_path" ]]; then
    rm -f "$log_path"
    echo "  [undo] Cleaned up undo log for $story_id"
  fi
}

# ── undo_log_exists ───────────────────────────────────────────────────────────
# Returns 0 (true) if an undo log exists for the given story, 1 otherwise.
# Used at story start to detect a failed previous attempt.
undo_log_exists() {
  local story_id="$1"
  local log_path
  log_path="$(_undo_log_path "$story_id")"
  [[ -f "$log_path" ]]
}
