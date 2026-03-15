#!/usr/bin/env bats
# tests/prd_schema_validation.bats — Tests for US-263: prd.json schema validation
#
# Run with: bats tests/prd_schema_validation.bats

setup() {
  export TMPDIR_TEST
  TMPDIR_TEST="$(mktemp -d)"
  export SCRATCH_DIR="$TMPDIR_TEST"
  export SPIRAL_HOME="$PWD"

  # Prefer the uv venv Python (has jsonschema); fall back to system python3
  if [[ -f "$SPIRAL_HOME/.venv/Scripts/python.exe" ]]; then
    export SPIRAL_PYTHON="$SPIRAL_HOME/.venv/Scripts/python.exe"
  elif [[ -f "$SPIRAL_HOME/.venv/bin/python" ]]; then
    export SPIRAL_PYTHON="$SPIRAL_HOME/.venv/bin/python"
  else
    export SPIRAL_PYTHON="python3"
  fi

  # Helper: write a prd.json with given stories JSON array
  make_prd() {
    local file="$1"
    local stories="${2:-[]}"
    "$SPIRAL_PYTHON" -c "
import json, sys
stories = json.loads(sys.argv[1])
prd = {'productName': 'Test', 'branchName': 'main', 'userStories': stories}
with open(sys.argv[2], 'w', encoding='utf-8') as f:
    json.dump(prd, f)
" "$stories" "$file"
  }
  export -f make_prd

  # Check if jsonschema is available in the chosen Python
  export HAS_JSONSCHEMA
  if "$SPIRAL_PYTHON" -c "import jsonschema" 2>/dev/null; then
    HAS_JSONSCHEMA="true"
  else
    HAS_JSONSCHEMA="false"
  fi
}

teardown() {
  rm -rf "$TMPDIR_TEST"
}

# ── Valid PRD ─────────────────────────────────────────────────────────────────

@test "valid prd with correct priority passes validation" {
  local prd="$TMPDIR_TEST/prd.json"
  make_prd "$prd" '[{"id":"US-001","title":"Short title","priority":"high","passes":false,"acceptanceCriteria":["AC1"],"dependencies":[]}]'
  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd"
  [ "$status" -eq 0 ]
}

# ── Invalid priority — core AC for US-263 ────────────────────────────────────

@test "invalid priority value is rejected with non-zero exit" {
  local prd="$TMPDIR_TEST/prd.json"
  make_prd "$prd" '[{"id":"US-001","title":"My story","priority":"urgent","passes":false,"acceptanceCriteria":["AC1"],"dependencies":[]}]'
  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd" 2>&1
  [ "$status" -ne 0 ]
}

@test "invalid priority error message contains SCHEMA ERROR" {
  local prd="$TMPDIR_TEST/prd.json"
  make_prd "$prd" '[{"id":"US-001","title":"My story","priority":"urgent","passes":false,"acceptanceCriteria":["AC1"],"dependencies":[]}]'
  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd" 2>&1
  [ "$status" -ne 0 ]
  [[ "$output" == *"SCHEMA ERROR"* ]] || [[ "$output" == *"urgent"* ]]
}

@test "invalid priority error contains JSON Pointer path (requires jsonschema)" {
  if [[ "$HAS_JSONSCHEMA" != "true" ]]; then
    skip "jsonschema not available in $SPIRAL_PYTHON"
  fi
  local prd="$TMPDIR_TEST/prd.json"
  make_prd "$prd" '[{"id":"US-002","title":"Story two","priority":"INVALID","passes":false,"acceptanceCriteria":["AC1"],"dependencies":[]}]'
  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd" 2>&1
  [ "$status" -ne 0 ]
  # JSON Pointer format: /userStories/0/priority
  [[ "$output" == *"/userStories/0/priority"* ]]
  [[ "$output" == *"SCHEMA ERROR"* ]]
}

# ── validate-write mode ───────────────────────────────────────────────────────

@test "validate-write replaces prd.json when new content is valid" {
  local prd="$TMPDIR_TEST/prd.json"
  local new_prd="$TMPDIR_TEST/prd_new.json"
  make_prd "$prd" '[]'
  make_prd "$new_prd" '[{"id":"US-010","title":"New story","priority":"low","passes":false,"acceptanceCriteria":["AC1"],"dependencies":[]}]'
  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd" --validate-write "$new_prd"
  [ "$status" -eq 0 ]
  # prd.json should now contain US-010 — pass path as sys.argv to avoid POSIX→Windows translation
  "$SPIRAL_PYTHON" -c "
import json, sys
prd = json.load(open(sys.argv[1], encoding='utf-8'))
assert any(s['id'] == 'US-010' for s in prd['userStories']), 'US-010 not found after write'
" "$prd"
}

@test "validate-write rejects invalid content and creates prd.json.bak" {
  local prd="$TMPDIR_TEST/prd.json"
  local new_prd="$TMPDIR_TEST/prd_bad.json"
  make_prd "$prd" '[]'
  make_prd "$new_prd" '[{"id":"US-011","title":"Bad story","priority":"bogus","passes":false,"acceptanceCriteria":["AC1"],"dependencies":[]}]'
  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd" --validate-write "$new_prd" 2>&1
  [ "$status" -ne 0 ]
  # SCHEMA ERROR must appear in combined output
  [[ "$output" == *"SCHEMA ERROR"* ]] || [[ "$output" == *"bogus"* ]]
  # Backup must have been created — pass path as arg
  "$SPIRAL_PYTHON" -c "import sys, os; assert os.path.isfile(sys.argv[1]+'.bak'), f'{sys.argv[1]}.bak missing'" "$prd"
}

@test "validate-write restores prd.json from backup on validation failure" {
  local prd="$TMPDIR_TEST/prd.json"
  local new_prd="$TMPDIR_TEST/prd_bad.json"
  # prd.json starts with US-001
  make_prd "$prd" '[{"id":"US-001","title":"Original","priority":"high","passes":false,"acceptanceCriteria":["AC1"],"dependencies":[]}]'
  # new file has invalid priority
  make_prd "$new_prd" '[{"id":"US-002","title":"Bad","priority":"nope","passes":false,"acceptanceCriteria":["AC1"],"dependencies":[]}]'
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd" --validate-write "$new_prd" || true
  # prd.json should still contain US-001 (restored from backup)
  "$SPIRAL_PYTHON" -c "
import json, sys
prd = json.load(open(sys.argv[1], encoding='utf-8'))
assert any(s['id'] == 'US-001' for s in prd['userStories']), 'US-001 not found — restore failed'
" "$prd"
}

# ── Schema constraint checks (require jsonschema) ─────────────────────────────

@test "title exceeding maxLength 100 is flagged (requires jsonschema)" {
  if [[ "$HAS_JSONSCHEMA" != "true" ]]; then
    skip "jsonschema not available in $SPIRAL_PYTHON"
  fi
  local prd="$TMPDIR_TEST/prd.json"
  # Title of 101 characters
  local long_title
  long_title="$("$SPIRAL_PYTHON" -c "print('A' * 101)")"
  make_prd "$prd" "[{\"id\":\"US-020\",\"title\":\"$long_title\",\"priority\":\"low\",\"passes\":false,\"acceptanceCriteria\":[\"AC1\"],\"dependencies\":[]}]"
  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd" 2>&1
  [ "$status" -ne 0 ]
  [[ "$output" == *"SCHEMA ERROR"* ]]
}

@test "acceptanceCriteria with zero items is rejected (requires jsonschema)" {
  if [[ "$HAS_JSONSCHEMA" != "true" ]]; then
    skip "jsonschema not available in $SPIRAL_PYTHON"
  fi
  local prd="$TMPDIR_TEST/prd.json"
  make_prd "$prd" '[{"id":"US-030","title":"No AC","priority":"low","passes":false,"acceptanceCriteria":[],"dependencies":[]}]'
  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd" 2>&1
  [ "$status" -ne 0 ]
}
