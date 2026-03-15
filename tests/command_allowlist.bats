#!/usr/bin/env bats
# tests/command_allowlist.bats — Unit tests for command allow-list gate (US-243)
#
# Run with: bats tests/command_allowlist.bats
#
# Tests verify:
#   - allowlist_load creates .spiral/command-allowlist.json with safe defaults
#   - cmd_allowed allows commands whose prefix is in the allow list
#   - cmd_allowed blocks commands matching deny patterns
#   - cmd_allowed uses global deny as fallback across all phases
#   - safe_run executes allowed commands and blocks forbidden ones
#   - cmd_log_blocked writes to .spiral/security-events.log
#   - allowlist_scan_stream_json detects bash tool_use deny-pattern commands

setup() {
  export TMPDIR_AL
  TMPDIR_AL="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_AL"
  export SPIRAL_ALLOWLIST_FILE="$TMPDIR_AL/command-allowlist.json"
  export SPIRAL_WORKER_ID="test-worker-1"

  # Source the library
  source lib/command_allowlist.sh
}

teardown() {
  [[ -d "$TMPDIR_AL" ]] && rm -rf "$TMPDIR_AL"
}

# ── Tests: allowlist_load ─────────────────────────────────────────────────────

@test "allowlist_load creates command-allowlist.json with safe defaults when missing" {
  rm -f "$SPIRAL_ALLOWLIST_FILE"
  allowlist_load
  [ -f "$SPIRAL_ALLOWLIST_FILE" ]
}

@test "allowlist_load creates valid JSON" {
  rm -f "$SPIRAL_ALLOWLIST_FILE"
  allowlist_load
  # Pass file path as CLI arg (MINGW64-safe: Git Bash translates CLI args to Windows paths)
  run python3 - "$SPIRAL_ALLOWLIST_FILE" <<'PYEOF'
import sys, json
with open(sys.argv[1], encoding='utf-8') as f:
    json.load(f)
print('ok')
PYEOF
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}

@test "allowlist_load default has R phase" {
  rm -f "$SPIRAL_ALLOWLIST_FILE"
  allowlist_load
  result=$(python3 - "$SPIRAL_ALLOWLIST_FILE" <<'PYEOF'
import sys, json
d = json.load(open(sys.argv[1], encoding='utf-8'))
print('R' in d)
PYEOF
  )
  [ "$result" = "True" ]
}

@test "allowlist_load default has I phase" {
  rm -f "$SPIRAL_ALLOWLIST_FILE"
  allowlist_load
  result=$(python3 - "$SPIRAL_ALLOWLIST_FILE" <<'PYEOF'
import sys, json
d = json.load(open(sys.argv[1], encoding='utf-8'))
print('I' in d)
PYEOF
  )
  [ "$result" = "True" ]
}

@test "allowlist_load default has V phase" {
  rm -f "$SPIRAL_ALLOWLIST_FILE"
  allowlist_load
  result=$(python3 - "$SPIRAL_ALLOWLIST_FILE" <<'PYEOF'
import sys, json
d = json.load(open(sys.argv[1], encoding='utf-8'))
print('V' in d)
PYEOF
  )
  [ "$result" = "True" ]
}

@test "allowlist_load default has M phase" {
  rm -f "$SPIRAL_ALLOWLIST_FILE"
  allowlist_load
  result=$(python3 - "$SPIRAL_ALLOWLIST_FILE" <<'PYEOF'
import sys, json
d = json.load(open(sys.argv[1], encoding='utf-8'))
print('M' in d)
PYEOF
  )
  [ "$result" = "True" ]
}

@test "allowlist_load does not overwrite existing allow-list file" {
  printf '%s\n' '{"global":{"allow":["custom_cmd"],"deny":[]}}' > "$SPIRAL_ALLOWLIST_FILE"
  allowlist_load
  result=$(python3 - "$SPIRAL_ALLOWLIST_FILE" <<'PYEOF'
import sys, json
d = json.load(open(sys.argv[1], encoding='utf-8'))
print(d['global']['allow'][0])
PYEOF
  )
  [ "$result" = "custom_cmd" ]
}

# ── Tests: cmd_allowed — allow ────────────────────────────────────────────────

@test "cmd_allowed allows command when deny list is empty" {
  printf '%s\n' '{"global":{"allow":["*"],"deny":[]},"I":{"allow":[],"deny":[]}}' > "$SPIRAL_ALLOWLIST_FILE"
  run cmd_allowed "git commit -m test" "I"
  [ "$status" -eq 0 ]
}

@test "cmd_allowed allows command not in any deny list" {
  printf '%s\n' '{"global":{"allow":[],"deny":["rm -rf"]},"I":{"allow":[],"deny":[]}}' > "$SPIRAL_ALLOWLIST_FILE"
  run cmd_allowed "git commit -m msg" "I"
  [ "$status" -eq 0 ]
}

@test "cmd_allowed allows commands not matching any deny pattern even in default policy" {
  rm -f "$SPIRAL_ALLOWLIST_FILE"
  allowlist_load
  # "ls" is in the Phase I allow list and not in any deny list — should be allowed
  run cmd_allowed "ls -la /tmp" "I"
  [ "$status" -eq 0 ]
}

@test "cmd_allowed allows curl in phase R" {
  rm -f "$SPIRAL_ALLOWLIST_FILE"
  allowlist_load
  run cmd_allowed "curl https://example.com" "R"
  [ "$status" -eq 0 ]
}

# ── Tests: cmd_allowed — deny ─────────────────────────────────────────────────

@test "cmd_allowed blocks command matching global deny list" {
  printf '%s\n' '{"global":{"allow":[],"deny":["rm -rf"]}}' > "$SPIRAL_ALLOWLIST_FILE"
  run cmd_allowed "rm -rf /important" "I"
  [ "$status" -eq 1 ]
}

@test "cmd_allowed blocks command matching phase-specific deny list" {
  printf '%s\n' '{"global":{"allow":["*"],"deny":[]},"I":{"allow":[],"deny":["git push"]}}' > "$SPIRAL_ALLOWLIST_FILE"
  run cmd_allowed "git push origin main" "I"
  [ "$status" -eq 1 ]
}

@test "cmd_allowed blocks git push --force in phase I default policy" {
  rm -f "$SPIRAL_ALLOWLIST_FILE"
  allowlist_load
  run cmd_allowed "git push --force origin main" "I"
  [ "$status" -eq 1 ]
}

@test "cmd_allowed blocks git reset --hard in phase R default policy" {
  rm -f "$SPIRAL_ALLOWLIST_FILE"
  allowlist_load
  run cmd_allowed "git reset --hard HEAD~1" "R"
  [ "$status" -eq 1 ]
}

@test "phase-specific deny blocks in that phase only" {
  printf '%s\n' '{"global":{"allow":["*"],"deny":[]},"I":{"allow":[],"deny":["git push"]}}' > "$SPIRAL_ALLOWLIST_FILE"
  # In phase I: git push is denied
  run cmd_allowed "git push origin main" "I"
  [ "$status" -eq 1 ]
  # In phase M: git push is allowed (not denied in M or global)
  run cmd_allowed "git push origin main" "M"
  [ "$status" -eq 0 ]
}

@test "global deny blocks across all phases" {
  printf '%s\n' '{"global":{"allow":[],"deny":["rm -rf"]},"I":{"allow":["*"],"deny":[]}}' > "$SPIRAL_ALLOWLIST_FILE"
  run cmd_allowed "rm -rf /var" "I"
  [ "$status" -eq 1 ]
}

# ── Tests: cmd_log_blocked ────────────────────────────────────────────────────

@test "cmd_log_blocked creates security-events.log" {
  cmd_log_blocked "rm -rf /important" "I" "test-worker"
  [ -f "$TMPDIR_AL/security-events.log" ]
}

@test "cmd_log_blocked writes command to security-events.log" {
  cmd_log_blocked "rm -rf /important" "I" "test-worker"
  run grep -q "rm -rf /important" "$TMPDIR_AL/security-events.log"
  [ "$status" -eq 0 ]
}

@test "cmd_log_blocked writes phase to security-events.log" {
  cmd_log_blocked "git push --force" "M" "worker-5"
  run grep -q "phase=M" "$TMPDIR_AL/security-events.log"
  [ "$status" -eq 0 ]
}

@test "cmd_log_blocked writes worker ID to security-events.log" {
  cmd_log_blocked "git reset --hard" "R" "worker-99"
  run grep -q "worker=worker-99" "$TMPDIR_AL/security-events.log"
  [ "$status" -eq 0 ]
}

@test "cmd_log_blocked writes BLOCKED marker to security-events.log" {
  cmd_log_blocked "rm -rf /" "I" "test"
  run grep -q "BLOCKED" "$TMPDIR_AL/security-events.log"
  [ "$status" -eq 0 ]
}

@test "cmd_log_blocked appends multiple violations" {
  cmd_log_blocked "rm -rf /" "I" "test"
  cmd_log_blocked "git push --force" "M" "test"
  count=$(grep -c "BLOCKED" "$TMPDIR_AL/security-events.log")
  [ "$count" -eq 2 ]
}

# ── Tests: safe_run ───────────────────────────────────────────────────────────

@test "safe_run executes allowed command" {
  printf '%s\n' '{"global":{"allow":["*"],"deny":[]}}' > "$SPIRAL_ALLOWLIST_FILE"
  run safe_run "I" "echo hello_safe"
  [ "$status" -eq 0 ]
  [ "$output" = "hello_safe" ]
}

@test "safe_run blocks forbidden command and does not execute it" {
  printf '%s\n' '{"global":{"allow":[],"deny":["echo bad"]}}' > "$SPIRAL_ALLOWLIST_FILE"
  MARKER_FILE="$TMPDIR_AL/should_not_exist.txt"
  run safe_run "I" "echo bad && touch $MARKER_FILE"
  [ "$status" -eq 1 ]
  [ ! -f "$MARKER_FILE" ]
}

@test "safe_run logs blocked command to security-events.log" {
  printf '%s\n' '{"global":{"allow":[],"deny":["rm -rf"]}}' > "$SPIRAL_ALLOWLIST_FILE"
  safe_run "I" "rm -rf /tmp/nonexistent" 2>/dev/null || true
  run grep -q "rm -rf" "$TMPDIR_AL/security-events.log"
  [ "$status" -eq 0 ]
}

# ── Tests: allowlist_scan_stream_json ─────────────────────────────────────────

@test "allowlist_scan_stream_json returns 0 for empty/missing file" {
  result=$(allowlist_scan_stream_json "$TMPDIR_AL/nonexistent.jsonl" "I" "US-TEST")
  [ "$result" -eq 0 ]
}

@test "allowlist_scan_stream_json detects denied bash command in stream-json" {
  printf '%s\n' '{"global":{"allow":[],"deny":["rm -rf"]},"I":{"allow":[],"deny":[]}}' > "$SPIRAL_ALLOWLIST_FILE"
  STREAM_FILE="$TMPDIR_AL/test_stream.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"rm -rf /important"}}]}}' > "$STREAM_FILE"
  result=$(allowlist_scan_stream_json "$STREAM_FILE" "I" "US-TEST")
  [ "$result" -eq 1 ]
}

@test "allowlist_scan_stream_json logs denied command to security-events.log" {
  printf '%s\n' '{"global":{"allow":[],"deny":["rm -rf"]}}' > "$SPIRAL_ALLOWLIST_FILE"
  STREAM_FILE="$TMPDIR_AL/test_stream2.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"rm -rf /var"}}]}}' > "$STREAM_FILE"
  # allowlist_scan_stream_json exits with violation count (non-zero when violations found)
  allowlist_scan_stream_json "$STREAM_FILE" "I" "US-TEST" >/dev/null || true
  run grep -q "rm -rf" "$TMPDIR_AL/security-events.log"
  [ "$status" -eq 0 ]
}

@test "allowlist_scan_stream_json ignores non-bash tool_use" {
  printf '%s\n' '{"global":{"allow":[],"deny":["rm -rf"]}}' > "$SPIRAL_ALLOWLIST_FILE"
  STREAM_FILE="$TMPDIR_AL/test_stream3.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"command":"rm -rf /var"}}]}}' > "$STREAM_FILE"
  result=$(allowlist_scan_stream_json "$STREAM_FILE" "I" "US-TEST")
  [ "$result" -eq 0 ]
}

@test "allowlist_scan_stream_json returns 0 for allowed commands" {
  rm -f "$SPIRAL_ALLOWLIST_FILE"
  allowlist_load
  STREAM_FILE="$TMPDIR_AL/test_stream4.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"ls -la"}}]}}' > "$STREAM_FILE"
  result=$(allowlist_scan_stream_json "$STREAM_FILE" "R" "US-TEST")
  [ "$result" -eq 0 ]
}
