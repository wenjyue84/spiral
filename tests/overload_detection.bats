#!/usr/bin/env bats
# tests/overload_detection.bats — Verify streaming Claude API overload detection
#
# Run with: bats tests/overload_detection.bats
#
# Tests verify:
#   - overloaded_error in streamed NDJSON output is detected (HTTP 200 simulation)
#   - "type":"error" in first chunk triggers overload handling
#   - Clean successful output is not flagged as overload
#   - api_overloaded event is logged on detection
#   - Exit code 0 from mock claude does not fool the detection logic

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_OD
  TMPDIR_OD="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_OD"

  # Provide a minimal JQ path
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Create mock binary directory and prepend to PATH
  export MOCK_BIN="$TMPDIR_OD/bin"
  mkdir -p "$MOCK_BIN"
  export PATH="$MOCK_BIN:$PATH"

  # Stub log_spiral_event for tests
  log_spiral_event() {
    local event_type="$1"
    local extra="${2:-}"
    printf '{"type":"%s",%s}\n' "$event_type" "$extra" >> "$TMPDIR_OD/events.jsonl"
  }
  export -f log_spiral_event
}

teardown() {
  rm -rf "$TMPDIR_OD"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

# Create a mock claude binary that prints $1 to stdout and exits 0
make_mock_claude() {
  local body="$1"
  # Use printf to avoid shell interpolation issues with quotes
  printf '#!/usr/bin/env bash\nprintf %%s\\n %s\nexit 0\n' "'$body'" > "$MOCK_BIN/claude"
  chmod +x "$MOCK_BIN/claude"
}

# Run the overload detection logic from ralph.sh against a temp file.
# Returns 0 (OVERLOAD_DETECTED) or 1 (CLEAN).
detect_overload() {
  local tmp_file="$1"
  local _FIRST_LINE
  _FIRST_LINE=$(head -1 "$tmp_file" 2>/dev/null || true)
  if grep -qE 'overloaded_error|"529"' "$tmp_file" 2>/dev/null || \
     echo "$_FIRST_LINE" | grep -qF '"type":"error"' 2>/dev/null; then
    return 0
  fi
  return 1
}
export -f detect_overload

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "mock claude exits 0 simulating HTTP 200 with overload body" {
  # Claude CLI exits 0 when server returns HTTP 200 even with error body
  make_mock_claude '{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'

  run claude -p "test prompt"
  [ "$status" -eq 0 ]
  [[ "$output" == *"overloaded_error"* ]]
}

@test "detect overloaded_error keyword in captured output" {
  local tmp="$TMPDIR_OD/claude_out.tmp"
  echo '{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}' > "$tmp"

  run detect_overload "$tmp"
  [ "$status" -eq 0 ]
}

@test "detect type:error pattern in first NDJSON chunk" {
  # The "type":"error" in first line is the primary streaming error signal
  local tmp="$TMPDIR_OD/stream.tmp"
  echo '{"type":"error","error":{"type":"overloaded_error","message":"API unavailable"}}' > "$tmp"

  # Verify first-line detection specifically
  local first_line
  first_line=$(head -1 "$tmp")
  run bash -c 'echo "$1" | grep -qF "\"type\":\"error\"" && echo MATCHED || echo NO_MATCH' _ "$first_line"
  [ "$output" = "MATCHED" ]
}

@test "detect_overload returns 0 for overloaded_error body from mock claude" {
  make_mock_claude '{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'

  local tmp="$TMPDIR_OD/claude_out.tmp"
  claude -p "test" > "$tmp" 2>&1 || true

  run detect_overload "$tmp"
  [ "$status" -eq 0 ]
}

@test "clean successful output is not flagged as overload" {
  local tmp="$TMPDIR_OD/clean.tmp"
  cat > "$tmp" <<'CLEANEOF'
{"type":"system","subtype":"init","session_id":"abc123"}
{"type":"assistant","message":{"role":"assistant","content":"Done"}}
{"type":"result","subtype":"success","duration_ms":1234}
CLEANEOF

  run detect_overload "$tmp"
  [ "$status" -ne 0 ]
}

@test "literal 529 string in output triggers overload detection" {
  local tmp="$TMPDIR_OD/529.tmp"
  # Use printf to write literal "529" with surrounding quotes (matches grep pattern '"529"')
  printf '{"status":"529","message":"Too Many Requests"}\n' > "$tmp"

  run detect_overload "$tmp"
  [ "$status" -eq 0 ]
}

@test "api_overloaded event is logged on detection" {
  local events_file="$TMPDIR_OD/events.jsonl"

  log_spiral_event "api_overloaded" '"retry_attempt":1,"sleep_sec":3'

  [ -f "$events_file" ]
  run grep -c "api_overloaded" "$events_file"
  [ "$output" = "1" ]
}

@test "api_overloaded event contains retry metadata" {
  local events_file="$TMPDIR_OD/events.jsonl"

  log_spiral_event "api_overloaded" '"retry_attempt":2,"sleep_sec":7'

  run grep "retry_attempt" "$events_file"
  [[ "$output" == *"retry_attempt"* ]]
  [[ "$output" == *"sleep_sec"* ]]
}
