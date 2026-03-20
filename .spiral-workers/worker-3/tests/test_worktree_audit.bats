#!/usr/bin/env bats
# tests/test_worktree_audit.bats — WorktreeCreate/WorktreeRemove hook audit log test

setup() {
  TMPDIR="$(mktemp -d)"
  export AUDIT_FILE="$TMPDIR/.spiral/worktree-audit.jsonl"
  # Patch the hook script to write to TMPDIR
  mkdir -p "$TMPDIR/.spiral"
  # Run hook from TMPDIR so relative .spiral/ path works
  export HOOK_SCRIPT="$BATS_TEST_DIRNAME/../.claude/hooks/worktree_audit.sh"
}

teardown() {
  rm -rf "$TMPDIR"
}

@test "hook appends valid JSON entry with all required fields" {
  SAMPLE_INPUT='{"hook_event_name":"WorktreeCreate","worktree_path":".spiral-workers/worker-1","session_id":"sess-abc123"}'

  cd "$TMPDIR"
  echo "$SAMPLE_INPUT" | bash "$HOOK_SCRIPT"

  [ -f "$AUDIT_FILE" ]
  ENTRY=$(cat "$AUDIT_FILE")

  # Verify it is valid JSON
  echo "$ENTRY" | jq . >/dev/null

  # Verify required fields
  [ "$(echo "$ENTRY" | jq -r '.event')" = "WorktreeCreate" ]
  [ "$(echo "$ENTRY" | jq -r '.worktree_path')" = ".spiral-workers/worker-1" ]
  [ "$(echo "$ENTRY" | jq -r '.session_id')" = "sess-abc123" ]
  [ "$(echo "$ENTRY" | jq -r '.timestamp')" != "null" ]
  [ "$(echo "$ENTRY" | jq -r '.timestamp')" != "" ]
}

@test "hook appends separate entries for multiple events" {
  cd "$TMPDIR"
  echo '{"hook_event_name":"WorktreeCreate","worktree_path":"w1","session_id":"s1"}' | bash "$HOOK_SCRIPT"
  echo '{"hook_event_name":"WorktreeRemove","worktree_path":"w1","session_id":"s1"}' | bash "$HOOK_SCRIPT"

  LINE_COUNT=$(wc -l <"$AUDIT_FILE")
  [ "$LINE_COUNT" -eq 2 ]

  FIRST=$(sed -n '1p' "$AUDIT_FILE")
  SECOND=$(sed -n '2p' "$AUDIT_FILE")
  [ "$(echo "$FIRST" | jq -r '.event')" = "WorktreeCreate" ]
  [ "$(echo "$SECOND" | jq -r '.event')" = "WorktreeRemove" ]
}
