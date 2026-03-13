#!/usr/bin/env bats
# tests/lib/spiral_assert.bats — Unit tests for lib/spiral_assert.sh
#
# Run with: bats tests/lib/spiral_assert.bats
#
# Tests verify:
#   - _spiral_assert_fail logs to violation file and continues in warn mode
#   - _spiral_assert_fail exits 1 in strict mode
#   - spiral_assert_ids_unique passes with unique IDs, fails with duplicates
#   - spiral_assert_story_count_bounded passes below max, fails above max
#   - spiral_assert_passes_monotonic detects passes regression
#   - spiral_assert_merge_no_story_loss detects story count decrease
#   - spiral_assert_iteration_progress detects spinning

setup() {
  export TMPDIR_SA="$(mktemp -d)"
  export SCRATCH_DIR="$TMPDIR_SA"

  # Provide JQ
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Mock SPIRAL_PYTHON (needed by prd_valid and deps_dag assertions)
  export MOCK_BIN="$TMPDIR_SA/bin"
  mkdir -p "$MOCK_BIN"
  cat > "$MOCK_BIN/mock_python_pass.sh" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$MOCK_BIN/mock_python_pass.sh"
  export SPIRAL_PYTHON="$MOCK_BIN/mock_python_pass.sh"

  local SPIRAL_HOME_VAL
  SPIRAL_HOME_VAL="$(cd "$(dirname "${BATS_TEST_DIRNAME}")/.." && pwd)"
  export SPIRAL_HOME="$SPIRAL_HOME_VAL"

  # Set warn mode by default (non-exiting)
  export SPIRAL_ASSERT_MODE="warn"

  # Source the library under test
  source "$SPIRAL_HOME/lib/spiral_assert.sh"

  # Create fixture PRD files
  export FIXTURE_DIR="$TMPDIR_SA/fixtures"
  mkdir -p "$FIXTURE_DIR"

  # Valid PRD: 3 unique story IDs
  cat > "$FIXTURE_DIR/prd_unique.json" <<'EOF'
{
  "schemaVersion": 1,
  "projectName": "Test",
  "productName": "Test Product",
  "branchName": "main",
  "description": "Test PRD",
  "userStories": [
    {"id": "US-001", "title": "Story 1", "priority": "high", "description": "d", "acceptanceCriteria": [], "technicalNotes": [], "dependencies": [], "estimatedComplexity": "small", "passes": false},
    {"id": "US-002", "title": "Story 2", "priority": "medium", "description": "d", "acceptanceCriteria": [], "technicalNotes": [], "dependencies": [], "estimatedComplexity": "small", "passes": false},
    {"id": "US-003", "title": "Story 3", "priority": "low", "description": "d", "acceptanceCriteria": [], "technicalNotes": [], "dependencies": [], "estimatedComplexity": "small", "passes": true}
  ]
}
EOF

  # PRD with duplicate IDs
  cat > "$FIXTURE_DIR/prd_duplicate_ids.json" <<'EOF'
{
  "schemaVersion": 1,
  "projectName": "Test",
  "productName": "Test Product",
  "branchName": "main",
  "description": "Test PRD",
  "userStories": [
    {"id": "US-001", "title": "Story 1", "priority": "high", "description": "d", "acceptanceCriteria": [], "technicalNotes": [], "dependencies": [], "estimatedComplexity": "small", "passes": false},
    {"id": "US-001", "title": "Story 1 dup", "priority": "medium", "description": "d", "acceptanceCriteria": [], "technicalNotes": [], "dependencies": [], "estimatedComplexity": "small", "passes": false}
  ]
}
EOF

  # PRD with many stories (for count check)
  python3 -c "
import json
stories = [{'id': f'US-{i:03d}', 'title': f'Story {i}', 'priority': 'low',
            'description': 'd', 'acceptanceCriteria': [], 'technicalNotes': [],
            'dependencies': [], 'estimatedComplexity': 'small', 'passes': False}
           for i in range(1, 6)]
prd = {'schemaVersion': 1, 'projectName': 'T', 'productName': 'T', 'branchName': 'main',
       'description': 'T', 'userStories': stories}
print(json.dumps(prd))
" > "$FIXTURE_DIR/prd_5stories.json"

  export PRD_FILE="$FIXTURE_DIR/prd_unique.json"
}

teardown() {
  rm -rf "$TMPDIR_SA"
}

# ── Test: _spiral_assert_fail in warn mode ────────────────────────────────────

@test "_spiral_assert_fail logs to violation file in warn mode" {
  export SPIRAL_ASSERT_MODE="warn"
  _spiral_assert_fail "test_check" "Something went wrong"
  local log_file="$SCRATCH_DIR/_assert_violations.log"
  [ -f "$log_file" ]
  grep -q "test_check" "$log_file"
}

@test "_spiral_assert_fail does not exit in warn mode (continues execution)" {
  export SPIRAL_ASSERT_MODE="warn"
  run bash -c "
    source '$SPIRAL_HOME/lib/spiral_assert.sh'
    export SCRATCH_DIR='$SCRATCH_DIR'
    _spiral_assert_fail 'check' 'msg'
    echo 'continued'
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ "continued" ]]
}

@test "_spiral_assert_fail exits 1 in strict mode" {
  run bash -c "
    export SPIRAL_ASSERT_MODE=strict
    export SCRATCH_DIR='$SCRATCH_DIR'
    source '$SPIRAL_HOME/lib/spiral_assert.sh'
    _spiral_assert_fail 'strict_check' 'Should fail'
    echo 'should not reach here'
  "
  [ "$status" -eq 1 ]
  [[ ! "$output" =~ "should not reach here" ]]
}

# ── Test: spiral_assert_ids_unique ───────────────────────────────────────────

@test "spiral_assert_ids_unique passes with unique story IDs" {
  run spiral_assert_ids_unique "$FIXTURE_DIR/prd_unique.json"
  [ "$status" -eq 0 ]
}

@test "spiral_assert_ids_unique returns 1 with duplicate story IDs" {
  export SPIRAL_ASSERT_MODE="warn"
  run spiral_assert_ids_unique "$FIXTURE_DIR/prd_duplicate_ids.json"
  [ "$status" -ne 0 ]
}

@test "spiral_assert_ids_unique logs violation when duplicates found" {
  export SPIRAL_ASSERT_MODE="warn"
  spiral_assert_ids_unique "$FIXTURE_DIR/prd_duplicate_ids.json" || true
  local log_file="$SCRATCH_DIR/_assert_violations.log"
  [ -f "$log_file" ]
  grep -q "ids_unique" "$log_file"
}

# ── Test: spiral_assert_story_count_bounded ───────────────────────────────────

@test "spiral_assert_story_count_bounded passes when count below max" {
  export SPIRAL_MAX_TOTAL_STORIES=200
  run spiral_assert_story_count_bounded "$FIXTURE_DIR/prd_5stories.json"
  [ "$status" -eq 0 ]
}

@test "spiral_assert_story_count_bounded returns 1 when count exceeds max" {
  export SPIRAL_MAX_TOTAL_STORIES=3
  export SPIRAL_ASSERT_MODE="warn"
  run spiral_assert_story_count_bounded "$FIXTURE_DIR/prd_5stories.json"
  [ "$status" -ne 0 ]
  unset SPIRAL_MAX_TOTAL_STORIES
}

@test "spiral_assert_story_count_bounded logs violation when count exceeds max" {
  export SPIRAL_MAX_TOTAL_STORIES=3
  export SPIRAL_ASSERT_MODE="warn"
  spiral_assert_story_count_bounded "$FIXTURE_DIR/prd_5stories.json" || true
  local log_file="$SCRATCH_DIR/_assert_violations.log"
  [ -f "$log_file" ]
  grep -q "story_count_bounded" "$log_file"
  unset SPIRAL_MAX_TOTAL_STORIES
}

# ── Test: spiral_assert_passes_monotonic ─────────────────────────────────────

@test "spiral_assert_passes_monotonic passes when count increases" {
  # Baseline: 1 passing story
  echo "1" > "$SCRATCH_DIR/_passes_baseline"
  # prd_unique.json has 1 passing story (US-003)
  run spiral_assert_passes_monotonic "$FIXTURE_DIR/prd_unique.json"
  [ "$status" -eq 0 ]
}

@test "spiral_assert_passes_monotonic returns 1 when passes count decreases" {
  export SPIRAL_ASSERT_MODE="warn"
  # Baseline: 2 passing stories
  echo "2" > "$SCRATCH_DIR/_passes_baseline"
  # prd_unique.json has only 1 passing story — regression detected
  run spiral_assert_passes_monotonic "$FIXTURE_DIR/prd_unique.json"
  [ "$status" -ne 0 ]
}

@test "spiral_assert_passes_monotonic skips check when no baseline file" {
  rm -f "$SCRATCH_DIR/_passes_baseline"
  run spiral_assert_passes_monotonic "$FIXTURE_DIR/prd_unique.json"
  [ "$status" -eq 0 ]
}

@test "spiral_assert_passes_save_baseline creates baseline file" {
  rm -f "$SCRATCH_DIR/_passes_baseline"
  spiral_assert_passes_save_baseline "$FIXTURE_DIR/prd_unique.json"
  [ -f "$SCRATCH_DIR/_passes_baseline" ]
  local val
  val=$(cat "$SCRATCH_DIR/_passes_baseline")
  [ "$val" = "1" ]
}

# ── Test: spiral_assert_merge_no_story_loss ───────────────────────────────────

@test "spiral_assert_merge_no_story_loss passes when after >= before" {
  run spiral_assert_merge_no_story_loss 10 12
  [ "$status" -eq 0 ]
}

@test "spiral_assert_merge_no_story_loss passes when count stays same" {
  run spiral_assert_merge_no_story_loss 10 10
  [ "$status" -eq 0 ]
}

@test "spiral_assert_merge_no_story_loss returns 1 when count decreases" {
  export SPIRAL_ASSERT_MODE="warn"
  run spiral_assert_merge_no_story_loss 10 8
  [ "$status" -ne 0 ]
}

# ── Test: spiral_assert_iteration_progress ────────────────────────────────────

@test "spiral_assert_iteration_progress passes when zero_count below max" {
  run spiral_assert_iteration_progress 1 3
  [ "$status" -eq 0 ]
}

@test "spiral_assert_iteration_progress returns 1 when zero_count reaches max" {
  export SPIRAL_ASSERT_MODE="warn"
  run spiral_assert_iteration_progress 3 3
  [ "$status" -ne 0 ]
}

@test "spiral_assert_iteration_progress returns 1 when zero_count exceeds max" {
  export SPIRAL_ASSERT_MODE="warn"
  run spiral_assert_iteration_progress 5 3
  [ "$status" -ne 0 ]
}

# ── Test: assert_file_exists (using bats built-in check) ─────────────────────

@test "fixture prd_unique.json exists (file existence check)" {
  [ -f "$FIXTURE_DIR/prd_unique.json" ]
}

@test "fixture prd_duplicate_ids.json exists (file existence check)" {
  [ -f "$FIXTURE_DIR/prd_duplicate_ids.json" ]
}

@test "fixture prd_unique.json is valid JSON" {
  run "$JQ" empty "$FIXTURE_DIR/prd_unique.json"
  [ "$status" -eq 0 ]
}

# ── Test: JSON key assertions on fixture files ────────────────────────────────

@test "fixture prd_unique.json has schemaVersion key with value 1" {
  local val
  val=$("$JQ" -r '.schemaVersion' "$FIXTURE_DIR/prd_unique.json")
  [ "$val" = "1" ]
}

@test "fixture prd_unique.json has 3 user stories" {
  local count
  count=$("$JQ" '[.userStories | length] | .[0]' "$FIXTURE_DIR/prd_unique.json")
  [ "$count" = "3" ]
}

@test "fixture prd_duplicate_ids.json has duplicate IDs detectable by jq" {
  local total unique
  total=$("$JQ" '[.userStories | length] | .[0]' "$FIXTURE_DIR/prd_duplicate_ids.json")
  unique=$("$JQ" '[.userStories[].id] | unique | length' "$FIXTURE_DIR/prd_duplicate_ids.json")
  [ "$total" != "$unique" ]
}
