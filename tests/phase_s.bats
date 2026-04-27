#!/usr/bin/env bats
# tests/phase_s.bats — Integration tests for US-1339: duplicate_detector wired into phase_s.sh
#
# Run with: bash tests/bats-core/bin/bats tests/phase_s.bats

bats_require_minimum_version 1.7.0

setup() {
  load test_helper/common-setup
  TEST_TMP="$(mktemp -d)"
  export TEST_TMP
  export SCRATCH_DIR="$TEST_TMP/.spiral"
  mkdir -p "$SCRATCH_DIR"

  export SPIRAL_HOME
  SPIRAL_HOME="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  export SPIRAL_PYTHON
  if [ -f "$SPIRAL_HOME/.venv/Scripts/python.exe" ]; then
    SPIRAL_PYTHON="$SPIRAL_HOME/.venv/Scripts/python.exe"
  else
    SPIRAL_PYTHON="$(command -v python3)"
  fi
}

teardown() {
  "$SPIRAL_PYTHON" -c "import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$TEST_TMP"
}

# ── CLI tests ─────────────────────────────────────────────────────────────────

@test "duplicate_detector CLI exits 0 with empty stories list" {
  echo '{"stories":[]}' >"$TEST_TMP/stories.json"
  run env PYTHONPATH="$SPIRAL_HOME" "$SPIRAL_PYTHON" -m lib.phase_s.duplicate_detector \
    "$TEST_TMP/stories.json"
  assert_success
}

@test "duplicate_detector CLI exits 0 with single story" {
  cat >"$TEST_TMP/stories.json" <<'EOF'
{"stories":[{"id":"US-001","title":"Add login feature","description":"Add user login"}]}
EOF
  run env PYTHONPATH="$SPIRAL_HOME" "$SPIRAL_PYTHON" -m lib.phase_s.duplicate_detector \
    "$TEST_TMP/stories.json"
  assert_success
}

@test "duplicate_detector CLI emits DUPLICATE_CANDIDATE for identical story titles" {
  cat >"$TEST_TMP/stories.json" <<'EOF'
{
  "stories": [
    {"id": "US-010", "title": "Wire validation module into spiral loop", "description": "Connect the validation module to the spiral.sh main loop"},
    {"id": "US-011", "title": "Wire validation module into spiral loop", "description": "Connect the validation module to the spiral.sh main loop"}
  ]
}
EOF
  run env PYTHONPATH="$SPIRAL_HOME" "$SPIRAL_PYTHON" -m lib.phase_s.duplicate_detector \
    "$TEST_TMP/stories.json"
  assert_success
  assert_output --partial "DUPLICATE_CANDIDATE:"
  assert_output --partial "US-010"
  assert_output --partial "US-011"
}

@test "DUPLICATE_CANDIDATE line format is 'DUPLICATE_CANDIDATE: <id_a> / <id_b> (<score>)'" {
  cat >"$TEST_TMP/stories.json" <<'EOF'
{
  "stories": [
    {"id": "US-020", "title": "Implement duplicate story detection in phase S", "description": "Detect near-duplicate stories using embeddings"},
    {"id": "US-021", "title": "Implement duplicate story detection in phase S", "description": "Detect near-duplicate stories using embeddings"}
  ]
}
EOF
  run env PYTHONPATH="$SPIRAL_HOME" "$SPIRAL_PYTHON" -m lib.phase_s.duplicate_detector \
    "$TEST_TMP/stories.json"
  assert_success
  assert_output --regexp "DUPLICATE_CANDIDATE: US-0[0-9]+ / US-0[0-9]+ \([0-9]+\.[0-9]+\)"
}

@test "duplicate_detector CLI exits 0 with missing file (no crash)" {
  run env PYTHONPATH="$SPIRAL_HOME" "$SPIRAL_PYTHON" -m lib.phase_s.duplicate_detector \
    "$TEST_TMP/nonexistent.json"
  assert_success
}

@test "duplicate_detector CLI outputs DUPLICATE_CANDIDATE via pre-built validated stories file" {
  # Build a validated_stories.json directly to test the CLI in isolation
  cat >"$TEST_TMP/validated.json" <<'EOF'
{
  "stories": [
    {"id": "DUP-A", "title": "Wire dedup module into spiral phase S validation", "description": "Connect dedup detection to phase S"},
    {"id": "DUP-B", "title": "Wire dedup module into spiral phase S validation", "description": "Connect dedup detection to phase S"}
  ]
}
EOF
  run env PYTHONPATH="$SPIRAL_HOME" "$SPIRAL_PYTHON" -m lib.phase_s.duplicate_detector \
    "$TEST_TMP/validated.json"
  assert_success
  assert_output --partial "DUPLICATE_CANDIDATE: DUP-A / DUP-B"
}

# ── Shell integration tests ───────────────────────────────────────────────────

@test "run_phase_story_validate exits 0 and produces _validated_stories.json" {
  source "$SPIRAL_HOME/lib/phases/phase_s_story_validate.sh"

  cat >"$TEST_TMP/prd.json" <<'EOF'
{"schemaVersion":1,"projectName":"T","userStories":[],"goals":[]}
EOF

  cat >"$SCRATCH_DIR/_research_output.json" <<'EOF'
{
  "stories": [
    {"id":"US-A","title":"Wire validation module into spiral loop","description":"Connect validation","priority":"high","acceptanceCriteria":["Module wired"],"technicalNotes":["foo"],"dependencies":[],"estimatedComplexity":"small"}
  ]
}
EOF
  echo '{"stories":[]}' >"$SCRATCH_DIR/_test_stories_output.json"

  export RESEARCH_OUTPUT="$SCRATCH_DIR/_research_output.json"
  export TEST_OUTPUT="$SCRATCH_DIR/_test_stories_output.json"
  export PRD_FILE="$TEST_TMP/prd.json"
  export SPIRAL_STORY_VALIDATE_MIN_OVERLAP=0

  run run_phase_story_validate "1" \
    "$RESEARCH_OUTPUT" "$TEST_OUTPUT" "$PRD_FILE" "$SCRATCH_DIR" \
    "$SPIRAL_PYTHON" "$SPIRAL_HOME"

  assert_success
  [ -f "$SCRATCH_DIR/_validated_stories.json" ]
}
