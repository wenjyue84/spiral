#!/usr/bin/env bats
# tests/test_claude_api_probe.bats — Tests for US-179 Claude API reachability probe
#
# Run with: bats tests/test_claude_api_probe.bats
#
# Tests verify:
#   - check_claude_api() returns PASS when curl succeeds
#   - check_claude_api() returns FAIL when curl fails (network error)
#   - check_claude_api() returns FAIL when ANTHROPIC_API_KEY is empty
#   - check_claude_api() is skipped when SPIRAL_SKIP_API_CHECK=true
#   - preflight probe is skipped in --dry-run mode
#   - preflight probe is skipped when SPIRAL_SKIP_API_CHECK=true
#   - preflight probe exits ERR_API_DOWN (14) when API unreachable

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_API
  TMPDIR_API="$(mktemp -d)"

  export MOCK_BIN="$TMPDIR_API/bin"
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

  # Provide a dummy API key so key-presence checks pass by default
  export ANTHROPIC_API_KEY="test-key-us179"
  export SPIRAL_SKIP_API_CHECK=""
  export DRY_RUN=0
}

teardown() {
  rm -rf "$TMPDIR_API"
}

# ── Helper: source only check_claude_api from spiral_doctor.sh ───────────────

source_check_claude_api() {
  eval "$(sed -n '/^check_claude_api()/,/^}/p' lib/spiral_doctor.sh)"
}

# ── check_claude_api unit tests ───────────────────────────────────────────────

@test "check_claude_api returns OK when curl succeeds" {
  cat > "$MOCK_BIN/curl" <<'EOF'
#!/usr/bin/env bash
echo '{"models":[]}'
exit 0
EOF
  chmod +x "$MOCK_BIN/curl"
  source_check_claude_api

  run check_claude_api
  [ "$status" -eq 0 ]
  [[ "$output" == *"[OK]"* ]]
  [[ "$output" == *"Claude API reachable"* ]]
}

@test "check_claude_api returns ERROR when curl fails (network error)" {
  cat > "$MOCK_BIN/curl" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "$MOCK_BIN/curl"
  source_check_claude_api

  run check_claude_api
  [ "$status" -eq 1 ]
  [[ "$output" == *"[ERROR]"* ]]
  [[ "$output" == *"not reachable"* ]]
}

@test "check_claude_api returns ERROR when curl times out" {
  cat > "$MOCK_BIN/curl" <<'EOF'
#!/usr/bin/env bash
exit 28
EOF
  chmod +x "$MOCK_BIN/curl"
  source_check_claude_api

  run check_claude_api
  [ "$status" -eq 1 ]
  [[ "$output" == *"[ERROR]"* ]]
}

@test "check_claude_api returns ERROR when ANTHROPIC_API_KEY is empty" {
  source_check_claude_api
  export ANTHROPIC_API_KEY=""

  run check_claude_api
  [ "$status" -eq 1 ]
  [[ "$output" == *"[ERROR]"* ]]
  [[ "$output" == *"ANTHROPIC_API_KEY is not set"* ]]
}

@test "check_claude_api returns SKIP when SPIRAL_SKIP_API_CHECK=true" {
  source_check_claude_api
  export SPIRAL_SKIP_API_CHECK="true"

  run check_claude_api
  [ "$status" -eq 0 ]
  [[ "$output" == *"SKIP"* ]]
}

@test "check_claude_api hint mentions SPIRAL_SKIP_API_CHECK on failure" {
  cat > "$MOCK_BIN/curl" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "$MOCK_BIN/curl"
  source_check_claude_api

  run check_claude_api
  [ "$status" -eq 1 ]
  [[ "$output" == *"SPIRAL_SKIP_API_CHECK"* ]]
}

# ── preflight integration tests ───────────────────────────────────────────────

# Helper: source only spiral_preflight_check from validate_preflight.sh
source_preflight() {
  # Also need JQ available
  eval "$(cat lib/validate_preflight.sh)"
}

@test "preflight skips API probe in dry-run mode" {
  # We don't mock curl at all — if the probe ran, it would try a real network call
  # (or fail in this test env). The skip path must short-circuit before curl.
  source_preflight

  # Provide a minimal environment so the other checks pass
  export DRY_RUN=1
  export SPIRAL_PYTHON="${SPIRAL_PYTHON:-python3}"
  export SPIRAL_HOME="$(pwd)"
  export PRD_FILE="$(pwd)/prd.json"
  export SCRATCH_DIR="$TMPDIR_API"
  export SPIRAL_SKIP_API_CHECK=""

  # We only care that the dry-run skip message appears; the probe must not fire.
  run bash -c "
    source lib/validate_preflight.sh
    # Stub out the other checks that would fail in isolation
    SPIRAL_PYTHON=true
    JQ=jq
    spiral_preflight_check '$PRD_FILE' '$TMPDIR_API'
  "
  [[ "$output" == *"Skipping Claude API check"* ]]
  [[ "$output" == *"dry-run"* ]]
}

@test "preflight skips API probe when SPIRAL_SKIP_API_CHECK=true" {
  export DRY_RUN=0
  export SPIRAL_SKIP_API_CHECK="true"

  run bash -c "
    export SPIRAL_SKIP_API_CHECK=true
    export DRY_RUN=0
    export ANTHROPIC_API_KEY=test-key
    source lib/validate_preflight.sh
    SPIRAL_PYTHON=true
    JQ=jq
    spiral_preflight_check '$(pwd)/prd.json' '$TMPDIR_API'
  "
  [[ "$output" == *"Skipping Claude API check"* ]]
  [[ "$output" == *"SPIRAL_SKIP_API_CHECK=true"* ]]
}

@test "preflight exits 14 (ERR_API_DOWN) when curl fails" {
  cat > "$MOCK_BIN/curl" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "$MOCK_BIN/curl"

  # ERR_API_DOWN must equal 14
  run bash -c "
    export PATH='$MOCK_BIN:\$PATH'
    export DRY_RUN=0
    export SPIRAL_SKIP_API_CHECK=''
    export ANTHROPIC_API_KEY=test-key
    readonly ERR_API_DOWN=14
    source lib/validate_preflight.sh
    SPIRAL_PYTHON=true
    JQ=jq
    spiral_preflight_check '$(pwd)/prd.json' '$TMPDIR_API'
  "
  [ "$status" -eq 14 ]
  [[ "$output" == *"FATAL"* ]]
  [[ "$output" == *"not reachable"* ]]
}

@test "preflight exits 14 when ANTHROPIC_API_KEY is empty" {
  run bash -c "
    export DRY_RUN=0
    export SPIRAL_SKIP_API_CHECK=''
    export ANTHROPIC_API_KEY=''
    readonly ERR_API_DOWN=14
    source lib/validate_preflight.sh
    SPIRAL_PYTHON=true
    JQ=jq
    spiral_preflight_check '$(pwd)/prd.json' '$TMPDIR_API'
  "
  [ "$status" -eq 14 ]
  [[ "$output" == *"ANTHROPIC_API_KEY"* ]]
}
