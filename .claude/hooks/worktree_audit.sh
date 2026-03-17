#!/usr/bin/env bash
# .claude/hooks/worktree_audit.sh — WorktreeCreate/WorktreeRemove audit logger
# Reads hook JSON from stdin, appends structured entry to .spiral/worktree-audit.jsonl
set -euo pipefail

AUDIT_FILE=".spiral/worktree-audit.jsonl"
mkdir -p ".spiral"

# Read full stdin payload
INPUT=$(cat)

# Extract fields using jq; default to empty string if missing
HOOK_EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // ""')
WORKTREE_PATH=$(echo "$INPUT" | jq -r '.worktree_path // .cwd // ""')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // ""')
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Append JSON log entry
jq -cn \
  --arg ts "$TIMESTAMP" \
  --arg ev "$HOOK_EVENT" \
  --arg wp "$WORKTREE_PATH" \
  --arg sid "$SESSION_ID" \
  '{timestamp: $ts, event: $ev, worktree_path: $wp, session_id: $sid}' \
  >> "$AUDIT_FILE"
