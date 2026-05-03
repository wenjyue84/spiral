#!/usr/bin/env bats
# tests/file_existence_gate.bats — Tests for file-existence gate
#
# Run with: bats tests/file_existence_gate.bats
#
# Tests verify:
#   - Empty filesTouch → fail
#   - filesTouch file doesn't exist → fail
#   - filesTouch file exists but not staged → fail
#   - Only prd.json in staged diff → fail (metadata-only)
#   - Valid file in filesTouch, staged, with content → pass
#   - Gate disabled via SPIRAL_GATE_STRICT_FILES=false → pass

bats_require_minimum_version 1.7.0

setup() {
  load test_helper/common-setup
  _resolve_jq

  TEST_DIR="$(mktemp -d)"
  export SCRATCH_DIR="$TEST_DIR/scratch"
  export SPIRAL_SCRATCH_DIR="$SCRATCH_DIR"
  export SPIRAL_GATE_STRICT_FILES="true"
  export SPIRAL_MIN_FILE_LINES="5"
  mkdir -p "$SCRATCH_DIR"

  # Create a git repo
  cd "$TEST_DIR" || return 1
  git init -b main . >/dev/null 2>&1
  git config user.email "test@test.com"
  git config user.name "Test"
  git config core.autocrlf false
  echo "initial" >README.md
  git add README.md
  git commit -m "init" >/dev/null 2>&1

  # Create prd.json
  export PRD_FILE="$TEST_DIR/prd.json"

  # Source quality_gates.sh
  local spiral_home
  spiral_home="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  # Stub log_ralph_event
  log_ralph_event() { :; }
  export -f log_ralph_event
  source "$spiral_home/ralph/lib/quality_gates.sh"
}

teardown() {
  cd /
  rm -rf "$TEST_DIR" 2>/dev/null || true
}

_write_prd() {
  local story_id="$1"
  shift
  local files_json="[]"
  if [[ $# -gt 0 ]]; then
    files_json=$(printf '%s\n' "$@" | $JQ -R . | $JQ -s .)
  fi
  cat >"$PRD_FILE" <<EOF
{
  "userStories": [{
    "id": "$story_id",
    "title": "Test story",
    "filesTouch": $files_json,
    "passes": false
  }]
}
EOF
}

@test "empty filesTouch fails gate" {
  _write_prd "US-001"
  run check_file_existence_gate "US-001"
  [[ "$status" -ne 0 ]]
}

@test "filesTouch file doesn't exist fails gate" {
  _write_prd "US-001" "src/nonexistent.ts"
  # Stage a real file so we have something
  echo "real content" > app.ts
  git add app.ts
  run check_file_existence_gate "US-001"
  [[ "$status" -ne 0 ]]
}

@test "filesTouch file exists but not staged fails gate" {
  _write_prd "US-001" "src/feature.ts"
  mkdir -p src
  # Create file with enough lines but don't stage it
  for i in $(seq 1 10); do echo "line $i"; done > src/feature.ts
  # Stage only prd.json
  git add prd.json
  run check_file_existence_gate "US-001"
  [[ "$status" -ne 0 ]]
}

@test "only metadata files staged fails gate (diff-sanity)" {
  _write_prd "US-001" "prd.json"
  git add prd.json
  run check_file_existence_gate "US-001"
  [[ "$status" -ne 0 ]]
}

@test "valid file in filesTouch staged with content passes gate" {
  mkdir -p src
  for i in $(seq 1 10); do echo "line $i"; done > src/feature.ts
  _write_prd "US-001" "src/feature.ts"
  git add src/feature.ts prd.json
  run check_file_existence_gate "US-001"
  [[ "$status" -eq 0 ]]
}

@test "gate disabled via SPIRAL_GATE_STRICT_FILES=false passes" {
  export SPIRAL_GATE_STRICT_FILES="false"
  _write_prd "US-001"
  run check_file_existence_gate "US-001"
  [[ "$status" -eq 0 ]]
}

@test "file with too few lines fails SPIRAL_MIN_FILE_LINES check" {
  mkdir -p src
  echo "x" > src/feature.ts
  _write_prd "US-001" "src/feature.ts"
  git add src/feature.ts prd.json
  run check_file_existence_gate "US-001"
  [[ "$status" -ne 0 ]]
}
