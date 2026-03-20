#!/usr/bin/env bats
# tests/test_config_audit.bats — ConfigChange hook audit and blocking tests

HOOK_SCRIPT="/c/Users/Jyue/.claude/hooks/config_audit.sh"

setup() {
  TMPDIR="$(mktemp -d)"
  export HOME="$TMPDIR"
  mkdir -p "$TMPDIR/.spiral"
}

teardown() {
  rm -rf "$TMPDIR"
}

@test "hook appends audit entry with required fields" {
  PAYLOAD='{"file_path":"spiral.config.sh","session_id":"sess-test1","source":"project_settings"}'

  echo "$PAYLOAD" | bash "$HOOK_SCRIPT"

  [ -f "$TMPDIR/.spiral/config-audit.jsonl" ]
  ENTRY=$(cat "$TMPDIR/.spiral/config-audit.jsonl")
  echo "$ENTRY" | jq . >/dev/null
  [ "$(echo "$ENTRY" | jq -r '.file_path')" = "spiral.config.sh" ]
  [ "$(echo "$ENTRY" | jq -r '.session_id')" = "sess-test1" ]
  [ "$(echo "$ENTRY" | jq -r '.source')" = "project_settings" ]
  [ -n "$(echo "$ENTRY" | jq -r '.timestamp')" ]
}

@test "hook blocks changes to .claude/settings.json with exit 2" {
  PAYLOAD='{"file_path":".claude/settings.json","session_id":"sess-test2","source":"project_settings"}'

  run bash "$HOOK_SCRIPT" <<<"$PAYLOAD"
  [ "$status" -eq 2 ]
  [[ "$output" =~ "BLOCKED" ]] || [[ "$stderr" =~ "BLOCKED" ]]
}

@test "hook blocks changes to .claude/settings.local.json with exit 2" {
  PAYLOAD='{"file_path":".claude/settings.local.json","session_id":"sess-test3","source":"project_settings"}'

  run bash "$HOOK_SCRIPT" <<<"$PAYLOAD"
  [ "$status" -eq 2 ]
}

@test "hook allows changes to non-protected files" {
  PAYLOAD='{"file_path":"prd.json","session_id":"sess-test4","source":"project_settings"}'

  run bash "$HOOK_SCRIPT" <<<"$PAYLOAD"
  [ "$status" -eq 0 ]
}
