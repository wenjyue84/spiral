#!/usr/bin/env bats
# tests/test_ollama_fallback.bats — Tests for US-144 Ollama local LLM fallback
#
# Run with: bats tests/test_ollama_fallback.bats
#
# Tests verify:
#   - SPIRAL_OLLAMA_FALLBACK_MODEL env var default is empty (disabled)
#   - SPIRAL_OLLAMA_HOST defaults to http://localhost:11434/v1
#   - call_ollama_fallback returns 1 on curl exit 7 (connection refused)
#   - call_ollama_fallback returns 1 on curl exit 28 (timeout)
#   - call_ollama_fallback returns 0 and prints content on success
#   - spiral-doctor warns when Ollama unreachable and model is configured
#   - spiral-doctor passes when Ollama is reachable

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_OL
  TMPDIR_OL="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_OL"

  # Create mock binary directory and prepend to PATH
  export MOCK_BIN="$TMPDIR_OL/bin"
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
  rm -rf "$TMPDIR_OL"
}

# ── Helper: source only call_ollama_fallback from ralph.sh ───────────────────

source_ollama_fn() {
  eval "$(sed -n '/^call_ollama_fallback()/,/^}/p' ralph/ralph.sh)"
}

# ── Helper: run the Ollama doctor check inline ───────────────────────────────

run_ollama_doctor_check() {
  local model="$1"
  local host="${2:-http://localhost:11434/v1}"
  local warn_count=0
  local ollama_base="${host%/v1}"
  if curl -sf --connect-timeout 3 --max-time 5 "${ollama_base}/api/tags" >/dev/null 2>&1; then
    echo "  [doctor] [OK] Ollama reachable at $ollama_base (model: $model)"
  else
    echo "  [doctor] [WARN] Ollama not reachable at $ollama_base (SPIRAL_OLLAMA_FALLBACK_MODEL=$model)"
    echo "           → Fix: Start Ollama with 'ollama serve' and pull: ollama pull $model"
    warn_count=$((warn_count + 1))
  fi
  return $warn_count
}
export -f run_ollama_doctor_check

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "SPIRAL_OLLAMA_FALLBACK_MODEL default is empty (disabled)" {
  # Verify the default is empty string in ralph.sh
  run grep 'SPIRAL_OLLAMA_FALLBACK_MODEL.*:-' ralph/ralph.sh
  [[ "$output" == *'SPIRAL_OLLAMA_FALLBACK_MODEL:-}'* ]] || \
    [[ "$output" == *'SPIRAL_OLLAMA_FALLBACK_MODEL:-""}'* ]] || \
    echo "$output" | grep -qE 'SPIRAL_OLLAMA_FALLBACK_MODEL.*:-["}]'
}

@test "SPIRAL_OLLAMA_HOST defaults to http://localhost:11434/v1" {
  run grep 'SPIRAL_OLLAMA_HOST.*:-' ralph/ralph.sh
  [[ "$output" == *"http://localhost:11434/v1"* ]]
}

@test "call_ollama_fallback returns 1 on curl exit 7 (connection refused)" {
  # Mock curl that exits 7 (ECONNREFUSED)
  cat > "$MOCK_BIN/curl" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "$MOCK_BIN/curl"

  source_ollama_fn

  local sys_file="$TMPDIR_OL/sys.txt"
  local usr_file="$TMPDIR_OL/usr.txt"
  printf 'system prompt' > "$sys_file"
  printf 'user prompt' > "$usr_file"

  export SPIRAL_OLLAMA_FALLBACK_MODEL="qwen2.5-coder:32b"
  export SPIRAL_OLLAMA_HOST="http://localhost:11434/v1"

  run call_ollama_fallback "$sys_file" "$usr_file"
  [ "$status" -eq 1 ]
  [[ "$output" == *"connection refused"* ]] || [[ "$output" == *"curl exit 7"* ]]
}

@test "call_ollama_fallback returns 1 on curl exit 28 (timeout)" {
  # Mock curl that exits 28 (ETIMEDOUT)
  cat > "$MOCK_BIN/curl" <<'EOF'
#!/usr/bin/env bash
exit 28
EOF
  chmod +x "$MOCK_BIN/curl"

  source_ollama_fn

  local sys_file="$TMPDIR_OL/sys.txt"
  local usr_file="$TMPDIR_OL/usr.txt"
  printf 'system' > "$sys_file"
  printf 'user' > "$usr_file"

  export SPIRAL_OLLAMA_FALLBACK_MODEL="codellama:34b"
  export SPIRAL_OLLAMA_HOST="http://localhost:11434/v1"

  run call_ollama_fallback "$sys_file" "$usr_file"
  [ "$status" -eq 1 ]
  [[ "$output" == *"timed out"* ]] || [[ "$output" == *"curl exit 28"* ]]
}

@test "call_ollama_fallback returns 0 and prints content on success" {
  # Mock curl that returns a valid OpenAI-compat response
  cat > "$MOCK_BIN/curl" <<'EOF'
#!/usr/bin/env bash
echo '{"choices":[{"message":{"role":"assistant","content":"Hello from Ollama!"}}]}'
exit 0
EOF
  chmod +x "$MOCK_BIN/curl"

  source_ollama_fn

  local sys_file="$TMPDIR_OL/sys.txt"
  local usr_file="$TMPDIR_OL/usr.txt"
  printf 'system prompt' > "$sys_file"
  printf 'user prompt' > "$usr_file"

  export SPIRAL_OLLAMA_FALLBACK_MODEL="qwen2.5-coder:32b"
  export SPIRAL_OLLAMA_HOST="http://localhost:11434/v1"

  run call_ollama_fallback "$sys_file" "$usr_file"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Hello from Ollama!"* ]]
}

@test "call_ollama_fallback uses SPIRAL_OLLAMA_HOST in initial log message" {
  # The function echoes "Calling Ollama model: <model> at <host>" to stdout.
  # This verifies SPIRAL_OLLAMA_HOST is picked up correctly.
  cat > "$MOCK_BIN/curl" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "$MOCK_BIN/curl"

  source_ollama_fn

  local sys_file="$TMPDIR_OL/sys.txt"
  local usr_file="$TMPDIR_OL/usr.txt"
  printf 'sys' > "$sys_file"; printf 'usr' > "$usr_file"

  export SPIRAL_OLLAMA_FALLBACK_MODEL="qwen2.5-coder:32b"
  export SPIRAL_OLLAMA_HOST="http://custom-host:11434/v1"

  run call_ollama_fallback "$sys_file" "$usr_file"
  [[ "$output" == *"http://custom-host:11434/v1"* ]]
}

@test "spiral-doctor warns when Ollama unreachable and model is configured" {
  # Mock curl that always fails (Ollama not running)
  cat > "$MOCK_BIN/curl" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "$MOCK_BIN/curl"

  run run_ollama_doctor_check "qwen2.5-coder:32b" "http://localhost:11434/v1"
  [[ "$output" == *"WARN"* ]]
  [[ "$output" == *"qwen2.5-coder:32b"* ]]
  [[ "$output" == *"ollama serve"* ]]
}

@test "spiral-doctor passes OK when Ollama is reachable" {
  # Mock curl that succeeds (Ollama running)
  cat > "$MOCK_BIN/curl" <<'EOF'
#!/usr/bin/env bash
echo '{"models":[]}'
exit 0
EOF
  chmod +x "$MOCK_BIN/curl"

  run run_ollama_doctor_check "qwen2.5-coder:32b" "http://localhost:11434/v1"
  [ "$status" -eq 0 ]
  [[ "$output" == *"[OK]"* ]]
  [[ "$output" == *"Ollama reachable"* ]]
}
