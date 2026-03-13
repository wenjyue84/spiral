#!/usr/bin/env bats
# tests/lib/validate_preflight.bats — Unit tests for lib/validate_preflight.sh
#
# Run with: bats tests/lib/validate_preflight.bats
#
# Tests verify:
#   - spiral_preflight_check passes with a valid PRD and valid environment
#   - spiral_preflight_check exits non-zero when prd_schema.py (tool) signals failure
#   - Corrupt checkpoint is removed during preflight
#   - Invalid checkpoint phase is removed during preflight
#   - Valid checkpoint is preserved during preflight

setup() {
  export TMPDIR_PF="$(mktemp -d)"
  export SCRATCH_DIR="$TMPDIR_PF/scratch"
  mkdir -p "$SCRATCH_DIR"

  # Provide JQ
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Create a bin/ with mock prd_schema.py (pass by default)
  export MOCK_BIN="$TMPDIR_PF/bin"
  mkdir -p "$MOCK_BIN"

  # Default: mock SPIRAL_PYTHON that succeeds when running prd_schema.py
  cat > "$MOCK_BIN/mock_python_pass.sh" <<'EOF'
#!/bin/bash
# Mock SPIRAL_PYTHON: always exits 0 (schema valid)
exit 0
EOF
  chmod +x "$MOCK_BIN/mock_python_pass.sh"

  cat > "$MOCK_BIN/mock_python_fail.sh" <<'EOF'
#!/bin/bash
# Mock SPIRAL_PYTHON: always exits 1 (schema invalid)
echo "Schema validation error" >&2
exit 1
EOF
  chmod +x "$MOCK_BIN/mock_python_fail.sh"

  export SPIRAL_HOME="$(cd "$(dirname "${BATS_TEST_DIRNAME}")/.." && pwd)"
  export PRD_FILE="$TMPDIR_PF/prd.json"
  export SPIRAL_PYTHON="$MOCK_BIN/mock_python_pass.sh"

  # Create a minimal valid prd.json
  cat > "$PRD_FILE" <<'EOF'
{
  "schemaVersion": 1,
  "projectName": "Test",
  "productName": "Test Product",
  "branchName": "main",
  "description": "Test",
  "userStories": []
}
EOF

  # Source the library under test
  source "$SPIRAL_HOME/lib/validate_preflight.sh"
}

teardown() {
  rm -rf "$TMPDIR_PF"
}

# ── Test: passes with valid environment ─────────────────────────────────────

@test "spiral_preflight_check passes with valid prd.json and no checkpoint" {
  run spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"
  [ "$status" -eq 0 ]
  [[ "$output" =~ "All checks passed" ]]
}

# ── Test: exits non-zero when schema tool (prd_schema.py) signals failure ───

@test "spiral_preflight_check exits non-zero when prd_schema.py exits 1" {
  export SPIRAL_PYTHON="$MOCK_BIN/mock_python_fail.sh"
  run spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"
  [ "$status" -ne 0 ]
}

@test "spiral_preflight_check prints FATAL message on schema failure" {
  export SPIRAL_PYTHON="$MOCK_BIN/mock_python_fail.sh"
  run spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"
  [[ "$output" =~ "FATAL" ]]
}

# ── Test: corrupt checkpoint handling ───────────────────────────────────────

@test "corrupt checkpoint (invalid JSON) is removed by preflight" {
  local ckpt="$SCRATCH_DIR/_checkpoint.json"
  echo "NOT VALID JSON" > "$ckpt"
  run spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"
  [ "$status" -eq 0 ]
  [ ! -f "$ckpt" ]
}

@test "checkpoint missing required fields is removed by preflight" {
  local ckpt="$SCRATCH_DIR/_checkpoint.json"
  echo '{"iter": 1}' > "$ckpt"
  run spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"
  [ "$status" -eq 0 ]
  [ ! -f "$ckpt" ]
}

@test "checkpoint with invalid phase is removed by preflight" {
  local ckpt="$SCRATCH_DIR/_checkpoint.json"
  echo '{"iter": 1, "phase": "X", "ts": 1000}' > "$ckpt"
  run spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"
  [ "$status" -eq 0 ]
  [ ! -f "$ckpt" ]
}

# ── Test: valid checkpoint is preserved ─────────────────────────────────────

@test "valid checkpoint with phase R is preserved by preflight" {
  local ckpt="$SCRATCH_DIR/_checkpoint.json"
  echo '{"iter": 1, "phase": "R", "ts": 1000}' > "$ckpt"
  run spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"
  [ "$status" -eq 0 ]
  [ -f "$ckpt" ]
}

@test "valid checkpoint with phase I is preserved by preflight" {
  local ckpt="$SCRATCH_DIR/_checkpoint.json"
  echo '{"iter": 2, "phase": "I", "ts": 9999}' > "$ckpt"
  run spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"
  [ "$status" -eq 0 ]
  [ -f "$ckpt" ]
}

# ── Test: valid SPIRAL_MODEL_ROUTING values pass without warning ─────────────

@test "SPIRAL_MODEL_ROUTING=auto is accepted without warning" {
  export SPIRAL_MODEL_ROUTING="auto"
  run spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"
  [ "$status" -eq 0 ]
  [[ ! "$output" =~ "WARNING: Unknown SPIRAL_MODEL_ROUTING" ]]
}

@test "SPIRAL_MODEL_ROUTING=badvalue emits a WARNING" {
  export SPIRAL_MODEL_ROUTING="badvalue"
  run spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"
  [ "$status" -eq 0 ]
  [[ "$output" =~ "WARNING: Unknown SPIRAL_MODEL_ROUTING" ]]
  unset SPIRAL_MODEL_ROUTING
}

# ── Test: MAX_RETRIES validation ─────────────────────────────────────────────

@test "MAX_RETRIES=3 passes validation without warning" {
  export MAX_RETRIES="3"
  run spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"
  [ "$status" -eq 0 ]
  [[ ! "$output" =~ "WARNING: MAX_RETRIES" ]]
  unset MAX_RETRIES
}

@test "MAX_RETRIES=0 emits a WARNING (not positive integer)" {
  export MAX_RETRIES="0"
  run spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"
  [ "$status" -eq 0 ]
  [[ "$output" =~ "WARNING: MAX_RETRIES" ]]
  unset MAX_RETRIES
}
