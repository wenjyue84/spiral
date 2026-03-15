#!/usr/bin/env bats
# tests/local_fallback_policy.bats — Tests for US-261 local Ollama fallback policy
#
# Run with: bats tests/local_fallback_policy.bats
#
# Tests verify:
#   - SPIRAL_LOCAL_FALLBACK_POLICY/SPIRAL_OLLAMA_BASE_URL/SPIRAL_OLLAMA_MODEL defaults
#   - ollama_prewarm logs warning when Ollama unreachable (non-fatal)
#   - ollama_prewarm logs [OK] when model found in /api/tags
#   - ollama_prewarm skips when policy=deny or policy is empty
#   - apply_local_fallback_policy with 'deny' → exit 2 + LOCAL_FALLBACK_DENIED message
#   - apply_local_fallback_policy with 'allow' → calls Ollama, returns 0 on success
#   - apply_local_fallback_policy with 'allow' → returns 1 on Ollama failure
#   - apply_local_fallback_policy with 'local-only' → calls Ollama (same as allow)
#   - apply_local_fallback_policy with empty policy → returns 1 (disabled)

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_LP
  TMPDIR_LP="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_LP"

  # Create mock binary directory and prepend to PATH
  export MOCK_BIN="$TMPDIR_LP/bin"
  mkdir -p "$MOCK_BIN"
  export PATH="$MOCK_BIN:$PATH"

  # Resolve jq binary
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Stub log_spiral_event and log_ralph_event (not needed in unit tests)
  log_spiral_event() { true; }
  export -f log_spiral_event
  log_ralph_event() { true; }
  export -f log_ralph_event
}

teardown() {
  rm -rf "$TMPDIR_LP"
}

# ── Helpers: source individual functions from ralph.sh ────────────────────────

source_prewarm_fn() {
  # Source call_ollama_fallback (dependency of apply_local_fallback_policy)
  eval "$(sed -n '/^call_ollama_fallback()/,/^}/p' ralph/ralph.sh)"
  # Source ollama_prewarm
  eval "$(sed -n '/^ollama_prewarm()/,/^}/p' ralph/ralph.sh)"
}

source_policy_fn() {
  eval "$(sed -n '/^call_ollama_fallback()/,/^}/p' ralph/ralph.sh)"
  eval "$(sed -n '/^apply_local_fallback_policy()/,/^}/p' ralph/ralph.sh)"
}

# ── Default value tests ───────────────────────────────────────────────────────

@test "SPIRAL_LOCAL_FALLBACK_POLICY default is empty (disabled)" {
  run grep 'SPIRAL_LOCAL_FALLBACK_POLICY.*:-' ralph/ralph.sh
  # Default must be empty string (feature off by default)
  echo "$output" | grep -qE 'SPIRAL_LOCAL_FALLBACK_POLICY.*:-["}]'
}

@test "SPIRAL_OLLAMA_BASE_URL defaults to http://localhost:11434" {
  run grep 'SPIRAL_OLLAMA_BASE_URL.*:-' ralph/ralph.sh
  [[ "$output" == *"http://localhost:11434"* ]]
}

@test "SPIRAL_OLLAMA_MODEL defaults to llama3.2" {
  run grep 'SPIRAL_OLLAMA_MODEL.*:-' ralph/ralph.sh
  [[ "$output" == *"llama3.2"* ]]
}

# ── ollama_prewarm tests ───────────────────────────────────────────────────────

@test "ollama_prewarm skips when policy is empty (disabled)" {
  source_prewarm_fn

  export SPIRAL_LOCAL_FALLBACK_POLICY=""
  run ollama_prewarm
  [ "$status" -eq 0 ]
  # No output expected (returns immediately)
  [[ -z "$output" ]]
}

@test "ollama_prewarm skips when policy=deny" {
  source_prewarm_fn

  export SPIRAL_LOCAL_FALLBACK_POLICY="deny"
  run ollama_prewarm
  [ "$status" -eq 0 ]
  [[ -z "$output" ]]
}

@test "ollama_prewarm logs warning when Ollama unreachable (non-fatal)" {
  # Mock curl that always fails (connection refused)
  cat > "$MOCK_BIN/curl" << 'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "$MOCK_BIN/curl"

  source_prewarm_fn

  export SPIRAL_LOCAL_FALLBACK_POLICY="allow"
  export SPIRAL_OLLAMA_BASE_URL="http://localhost:11434"
  export SPIRAL_OLLAMA_MODEL="llama3.2"

  run ollama_prewarm
  # Must NOT abort (exit 0) — warning only
  [ "$status" -eq 0 ]
  [[ "$output" == *"WARNING"* ]]
  [[ "$output" == *"unreachable"* ]]
}

@test "ollama_prewarm logs [OK] when model found in /api/tags" {
  # Mock curl returning tags with the expected model
  cat > "$MOCK_BIN/curl" << 'EOF'
#!/usr/bin/env bash
echo '{"models":[{"name":"llama3.2","size":1234}]}'
exit 0
EOF
  chmod +x "$MOCK_BIN/curl"

  source_prewarm_fn

  export SPIRAL_LOCAL_FALLBACK_POLICY="allow"
  export SPIRAL_OLLAMA_BASE_URL="http://localhost:11434"
  export SPIRAL_OLLAMA_MODEL="llama3.2"

  run ollama_prewarm
  [ "$status" -eq 0 ]
  [[ "$output" == *"[OK]"* ]]
  [[ "$output" == *"pre-loaded"* ]]
}

@test "ollama_prewarm warns when model absent from /api/tags (non-fatal)" {
  # Mock curl returning tags WITHOUT the expected model
  cat > "$MOCK_BIN/curl" << 'EOF'
#!/usr/bin/env bash
echo '{"models":[{"name":"other-model:latest"}]}'
exit 0
EOF
  chmod +x "$MOCK_BIN/curl"

  source_prewarm_fn

  export SPIRAL_LOCAL_FALLBACK_POLICY="local-only"
  export SPIRAL_OLLAMA_BASE_URL="http://localhost:11434"
  export SPIRAL_OLLAMA_MODEL="llama3.2"

  run ollama_prewarm
  [ "$status" -eq 0 ]
  [[ "$output" == *"WARNING"* ]]
  [[ "$output" == *"absent"* ]]
}

# ── apply_local_fallback_policy tests ────────────────────────────────────────

@test "deny policy exits with code 2 and prints LOCAL_FALLBACK_DENIED" {
  source_policy_fn

  export SPIRAL_LOCAL_FALLBACK_POLICY="deny"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_LP"
  export NEXT_STORY="US-999"

  local out_file="$TMPDIR_LP/out.txt"

  run apply_local_fallback_policy "Claude API unreachable" "$out_file"
  [ "$status" -eq 2 ]
  [[ "$output" == *"LOCAL_FALLBACK_DENIED"* ]]
  [[ "$output" == *"Claude API unreachable"* ]]
}

@test "deny policy never silently reroutes (output file not written)" {
  source_policy_fn

  export SPIRAL_LOCAL_FALLBACK_POLICY="deny"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_LP"
  export NEXT_STORY="US-999"

  local out_file="$TMPDIR_LP/out.txt"

  # Ignore exit status (will be 2); check file not created
  run apply_local_fallback_policy "cloud failed" "$out_file" || true
  [[ ! -f "$out_file" ]] || [[ ! -s "$out_file" ]]
}

@test "allow policy calls Ollama and returns 0 on success" {
  # Mock curl returning valid OpenAI-compat response
  cat > "$MOCK_BIN/curl" << 'EOF'
#!/usr/bin/env bash
echo '{"choices":[{"message":{"role":"assistant","content":"Story implemented"}}]}'
exit 0
EOF
  chmod +x "$MOCK_BIN/curl"

  source_policy_fn

  export SPIRAL_LOCAL_FALLBACK_POLICY="allow"
  export SPIRAL_OLLAMA_BASE_URL="http://localhost:11434"
  export SPIRAL_OLLAMA_MODEL="llama3.2"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_LP"
  export RALPH_SYSTEM_PROMPT="system prompt"
  export RALPH_USER_PROMPT="user prompt"
  export NEXT_STORY="US-999"

  local out_file="$TMPDIR_LP/out.txt"

  run apply_local_fallback_policy "cloud unavailable" "$out_file"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Local fallback succeeded"* ]]
}

@test "allow policy returns 1 when Ollama call fails" {
  # Mock curl that always fails
  cat > "$MOCK_BIN/curl" << 'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "$MOCK_BIN/curl"

  source_policy_fn

  export SPIRAL_LOCAL_FALLBACK_POLICY="allow"
  export SPIRAL_OLLAMA_BASE_URL="http://localhost:11434"
  export SPIRAL_OLLAMA_MODEL="llama3.2"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_LP"
  export RALPH_SYSTEM_PROMPT="system prompt"
  export RALPH_USER_PROMPT="user prompt"
  export NEXT_STORY="US-999"

  local out_file="$TMPDIR_LP/out.txt"

  run apply_local_fallback_policy "cloud unavailable" "$out_file"
  [ "$status" -eq 1 ]
  [[ "$output" == *"failed"* ]]
}

@test "local-only policy calls Ollama (behaves like allow)" {
  # Mock curl returning valid response
  cat > "$MOCK_BIN/curl" << 'EOF'
#!/usr/bin/env bash
echo '{"choices":[{"message":{"role":"assistant","content":"Local model output"}}]}'
exit 0
EOF
  chmod +x "$MOCK_BIN/curl"

  source_policy_fn

  export SPIRAL_LOCAL_FALLBACK_POLICY="local-only"
  export SPIRAL_OLLAMA_BASE_URL="http://localhost:11434"
  export SPIRAL_OLLAMA_MODEL="llama3.2"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_LP"
  export RALPH_SYSTEM_PROMPT="system"
  export RALPH_USER_PROMPT="user"
  export NEXT_STORY="US-999"

  local out_file="$TMPDIR_LP/out.txt"

  run apply_local_fallback_policy "local-only policy: bypassing cloud" "$out_file"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Local fallback succeeded"* ]]
}

@test "empty policy returns 1 (feature disabled — no Ollama call)" {
  source_policy_fn

  export SPIRAL_LOCAL_FALLBACK_POLICY=""
  export SPIRAL_SCRATCH_DIR="$TMPDIR_LP"

  local out_file="$TMPDIR_LP/out.txt"

  run apply_local_fallback_policy "some failure" "$out_file"
  [ "$status" -eq 1 ]
  # Output file should not be written
  [[ ! -s "$out_file" ]]
}

@test "local-only policy is referenced in 529 loop shortcut in ralph.sh" {
  # Verify that ralph.sh contains the local-only early-exit logic
  run grep -c 'local-only policy' ralph/ralph.sh
  [[ "$output" -ge 1 ]]
}

@test "spiral_events.jsonl receives structured local_fallback_used event on allow" {
  # Mock curl returning valid response
  cat > "$MOCK_BIN/curl" << 'EOF'
#!/usr/bin/env bash
echo '{"choices":[{"message":{"role":"assistant","content":"done"}}]}'
exit 0
EOF
  chmod +x "$MOCK_BIN/curl"

  # Use a real log_spiral_event that writes to a file
  local events_file="$TMPDIR_LP/spiral_events.jsonl"
  log_spiral_event() {
    local evt="$1" extra="${2:-}"
    local ts="2026-01-01T00:00:00Z"
    if [[ -n "$extra" ]]; then
      printf '{"event_type":"%s",%s}\n' "$evt" "$extra" >> "$events_file"
    else
      printf '{"event_type":"%s"}\n' "$evt" >> "$events_file"
    fi
  }
  export -f log_spiral_event

  source_policy_fn

  export SPIRAL_LOCAL_FALLBACK_POLICY="allow"
  export SPIRAL_OLLAMA_BASE_URL="http://localhost:11434"
  export SPIRAL_OLLAMA_MODEL="llama3.2"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_LP"
  export RALPH_SYSTEM_PROMPT="sys"
  export RALPH_USER_PROMPT="usr"
  export NEXT_STORY="US-261"

  local out_file="$TMPDIR_LP/out.txt"
  apply_local_fallback_policy "cloud failed" "$out_file" || true

  # Check that a local_fallback_used event was written with required fields
  run grep -l 'local_fallback_used' "$events_file"
  [ "$status" -eq 0 ]

  run grep 'model_used' "$events_file"
  [ "$status" -eq 0 ]

  run grep 'original_error' "$events_file"
  [ "$status" -eq 0 ]
}
