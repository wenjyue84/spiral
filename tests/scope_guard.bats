#!/usr/bin/env bats
# tests/scope_guard.bats — Tests for US-356: Scope guard validates changed files
#                          against story filesTouch field before git commit
#
# Run with: bats tests/scope_guard.bats
#
# Tests verify:
#   - In-scope files pass the guard
#   - Out-of-scope files produce a WARN (default mode)
#   - SPIRAL_STRICT_SCOPE_GUARD=true returns non-zero on out-of-scope files
#   - Empty filesTouch skips the check (no false positives)
#   - Event is logged to spiral_events.jsonl with correct fields

# ── Helpers ──────────────────────────────────────────────────────────────────

_setup_scope_env() {
  export TEST_DIR
  TEST_DIR="$(mktemp -d)"
  export SCRATCH_DIR="$TEST_DIR/scratch"
  export SPIRAL_SCRATCH_DIR="$SCRATCH_DIR"
  export SPIRAL_STRICT_SCOPE_GUARD="false"
  mkdir -p "$SCRATCH_DIR"

  # Detect jq
  if command -v jq &>/dev/null; then
    JQ="jq"
  elif [[ -f "$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/ralph/jq.exe" ]]; then
    JQ="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/ralph/jq.exe"
  else
    skip "jq not available"
  fi
  export JQ

  # Create a git repo with a file
  cd "$TEST_DIR" || return 1
  git init -b main . >/dev/null 2>&1
  git config user.email "test@test.com"
  git config user.name "Test"
  git config core.autocrlf false
  echo "initial" > README.md
  git add README.md
  git commit -m "init" >/dev/null 2>&1

  # Create prd.json with a story that has filesTouch
  export PRD_FILE="$TEST_DIR/prd.json"
}

_write_prd_with_scope() {
  local files_touch="$1"
  cat > "$PRD_FILE" <<EOFPRD
{
  "userStories": [
    {
      "id": "US-TEST",
      "title": "Test story",
      "priority": "high",
      "passes": false,
      "filesTouch": $files_touch
    }
  ]
}
EOFPRD
}

# Source only check_scope_guard and log_ralph_event from ralph.sh
_source_scope_guard() {
  # We define the functions inline to avoid sourcing the entire ralph.sh
  # which has many side effects.
  eval "$(cat <<'EOFUNC'
log_ralph_event() {
  local event="$1"
  local extra="${2:-}"
  local ts log_file line
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log_file="$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"
  if [[ -n "$extra" ]]; then
    line="{\"ts\":\"$ts\",\"event\":\"$event\",$extra}"
  else
    line="{\"ts\":\"$ts\",\"event\":\"$event\"}"
  fi
  printf '%s\n' "$line" >>"$log_file" 2>/dev/null || true
}
EOFUNC
)"

  # Source check_scope_guard from ralph.sh by extracting it
  local ralph_sh
  ralph_sh="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/ralph/ralph.sh"
  # Extract the function using sed
  eval "$(sed -n '/^check_scope_guard()/,/^}/p' "$ralph_sh")"
}

_teardown_scope_env() {
  cd /
  rm -rf "$TEST_DIR"
}

# ── Tests ────────────────────────────────────────────────────────────────────

@test "scope guard: in-scope files pass" {
  _setup_scope_env
  _source_scope_guard
  _write_prd_with_scope '["src/main.py", "tests/test_main.py"]'

  # Create and stage an in-scope file
  mkdir -p src
  echo "code" > src/main.py
  git add src/main.py

  run check_scope_guard "US-TEST"
  echo "status=$status output=$output"
  [ "$status" -eq 0 ]

  # Verify event logged
  local events_file="$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"
  [ -f "$events_file" ]
  grep -q '"result":"pass"' "$events_file"

  _teardown_scope_env
}

@test "scope guard: out-of-scope files produce WARN in default mode" {
  _setup_scope_env
  _source_scope_guard
  _write_prd_with_scope '["src/main.py"]'

  # Create and stage an out-of-scope file
  mkdir -p config
  echo "secret" > config/settings.yaml
  git add config/settings.yaml

  run check_scope_guard "US-TEST"
  echo "status=$status output=$output"
  # Default mode: returns 0 (warn only)
  [ "$status" -eq 0 ]
  # Should mention the warning
  [[ "$output" == *"WARNING"* ]]
  [[ "$output" == *"config/settings.yaml"* ]]

  # Event should have result=warn
  grep -q '"result":"warn"' "$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"

  _teardown_scope_env
}

@test "scope guard: SPIRAL_STRICT_SCOPE_GUARD=true aborts on out-of-scope files" {
  _setup_scope_env
  _source_scope_guard
  export SPIRAL_STRICT_SCOPE_GUARD="true"
  _write_prd_with_scope '["src/main.py"]'

  # Create and stage an out-of-scope file
  mkdir -p lib
  echo "rogue" > lib/rogue.py
  git add lib/rogue.py

  run check_scope_guard "US-TEST"
  echo "status=$status output=$output"
  # Strict mode: returns 1 (abort)
  [ "$status" -eq 1 ]
  [[ "$output" == *"aborting commit"* ]]

  # Event should have result=abort
  grep -q '"result":"abort"' "$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"

  _teardown_scope_env
}

@test "scope guard: empty filesTouch skips check" {
  _setup_scope_env
  _source_scope_guard
  _write_prd_with_scope '[]'

  # Stage any file
  echo "anything" > newfile.txt
  git add newfile.txt

  run check_scope_guard "US-TEST"
  echo "status=$status output=$output"
  [ "$status" -eq 0 ]

  # Event should have result=skip
  grep -q '"result":"skip"' "$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"

  _teardown_scope_env
}

@test "scope guard: subdirectory prefix matching works" {
  _setup_scope_env
  _source_scope_guard
  _write_prd_with_scope '["src/"]'

  # Create and stage a file under src/ (should match via prefix)
  mkdir -p src/utils
  echo "helper" > src/utils/helper.py
  git add src/utils/helper.py

  run check_scope_guard "US-TEST"
  echo "status=$status output=$output"
  [ "$status" -eq 0 ]

  # Event should have result=pass
  grep -q '"result":"pass"' "$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"

  _teardown_scope_env
}

@test "scope guard: event contains story_id and out_of_scope file list" {
  _setup_scope_env
  _source_scope_guard
  _write_prd_with_scope '["src/main.py"]'

  # Stage an out-of-scope file
  echo "rogue" > rogue.txt
  git add rogue.txt

  run check_scope_guard "US-TEST"

  local events_file="$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"
  [ -f "$events_file" ]
  # Verify story_id field
  grep -q '"story_id":"US-TEST"' "$events_file"
  # Verify out_of_scope contains the file
  grep -q '"rogue.txt"' "$events_file"
  # Verify out_of_scope_count
  grep -q '"out_of_scope_count":1' "$events_file"

  _teardown_scope_env
}
