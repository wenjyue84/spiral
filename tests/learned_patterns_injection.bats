#!/usr/bin/env bats
# tests/learned_patterns_injection.bats — Unit tests for US-1214 learned patterns injection
#
# Run with: tests/bats-core/bin/bats tests/learned_patterns_injection.bats
#
# Tests verify:
#   - ralph.sh injects learned patterns from Phase L into user prompt context
#   - Patterns are read from latest learned_patterns_iter_*.json file
#   - Top 3 patterns by frequency are injected
#   - If no patterns file, injection is skipped silently
#   - Learned patterns section appears in RALPH_USER_PROMPT with correct formatting

bats_require_minimum_version 1.7.0

setup() {
  load test_helper/common-setup
  _resolve_jq
  export TMPDIR_LP
  TMPDIR_LP="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_LP"

  # Set up minimal environment for prompt builder
  export PROMPT_FILE
  PROMPT_FILE="$TMPDIR_LP/prompt.txt"
  echo "System prompt content" >"$PROMPT_FILE"

  export NEXT_STORY="US-TEST-001"
  export STORY_TITLE="Test Story"
  export PRD_FILE="$TMPDIR_LP/prd.json"
  export PROGRESS_FILE="$TMPDIR_LP/progress.txt"
  export MAX_RETRIES=3
  export RETRY_NOW=0
  export RALPH_FOCUS=""
  export SPIRAL_EPISODIC_MEMORY="false"
  export SPIRAL_REPO_MAP="false"
  export SPIRAL_CONTEXT_MODE="diff"
  export SPIRAL_ANTI_PATTERN_INJECT="true"

  # Create minimal prd.json
  $JQ -n '{"userStories": []}' >"$PRD_FILE"

  # Create progress.txt
  echo "## Codebase Patterns" >"$PROGRESS_FILE"

  # Mock log_ralph_event (required by prompt_builder.sh)
  log_ralph_event() {
    # No-op for tests
    true
  }
  export -f log_ralph_event

  # Source the prompt_builder.sh library
  _PB_LIB="$(cd "$BATS_TEST_DIRNAME/.." && pwd)/ralph/lib/prompt_builder.sh"
  if [[ ! -f "$_PB_LIB" ]]; then
    skip "ralph/lib/prompt_builder.sh not found"
  fi
  source "$_PB_LIB"
}

teardown() {
  rm -rf "$TMPDIR_LP"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "US-1214: inject learned patterns from latest file" {
  # Create a mock learned_patterns_iter_1.json file
  local patterns_file="$SPIRAL_SCRATCH_DIR/learned_patterns_iter_1.json"
  $JQ -n '{
    "iteration": 1,
    "patterns": [
      {"pattern": "Always use specific exception types", "frequency": 15},
      {"pattern": "Add logging to failures", "frequency": 12},
      {"pattern": "Test edge cases with empty inputs", "frequency": 8},
      {"pattern": "Document breaking changes", "frequency": 5}
    ]
  }' >"$patterns_file"

  # Create story JSON with tags
  export STORY_JSON=$($JQ -n '{
    "id": "US-TEST-001",
    "title": "Test Story",
    "tags": ["improvement", "phase-i"],
    "filesTouch": []
  }')

  # Call build_ralph_prompts
  build_ralph_prompts

  # Verify patterns section appears in the prompt
  [[ "$RALPH_USER_PROMPT" == *"## Learned Patterns from Phase L"* ]]
  [[ "$RALPH_USER_PROMPT" == *"Always use specific exception types"* ]]
  [[ "$RALPH_USER_PROMPT" == *"Add logging to failures"* ]]
}

@test "US-1214: inject top 3 patterns (not all patterns)" {
  local patterns_file="$SPIRAL_SCRATCH_DIR/learned_patterns_iter_1.json"
  $JQ -n '{
    "iteration": 1,
    "patterns": [
      {"pattern": "Pattern A", "frequency": 100},
      {"pattern": "Pattern B", "frequency": 50},
      {"pattern": "Pattern C", "frequency": 25},
      {"pattern": "Pattern D", "frequency": 10}
    ]
  }' >"$patterns_file"

  export STORY_JSON=$($JQ -n '{
    "id": "US-TEST-001",
    "title": "Test Story",
    "tags": [],
    "filesTouch": []
  }')

  build_ralph_prompts

  # Should contain top 3 patterns
  [[ "$RALPH_USER_PROMPT" == *"Pattern A"* ]]
  [[ "$RALPH_USER_PROMPT" == *"Pattern B"* ]]
  [[ "$RALPH_USER_PROMPT" == *"Pattern C"* ]]
  # Should NOT contain Pattern D
  [[ "$RALPH_USER_PROMPT" != *"Pattern D"* ]]
}

@test "US-1214: skip silently when no patterns file exists" {
  # Ensure no patterns file exists
  rm -f "$SPIRAL_SCRATCH_DIR"/learned_patterns_iter_*.json

  export STORY_JSON=$($JQ -n '{
    "id": "US-TEST-001",
    "title": "Test Story",
    "tags": [],
    "filesTouch": []
  }')

  # Call build_ralph_prompts — should not error
  build_ralph_prompts

  # Should NOT have patterns section
  [[ "$RALPH_USER_PROMPT" != *"## Learned Patterns from Phase L"* ]]
}

@test "US-1214: skip when story JSON is empty" {
  local patterns_file="$SPIRAL_SCRATCH_DIR/learned_patterns_iter_1.json"
  $JQ -n '{
    "iteration": 1,
    "patterns": [
      {"pattern": "Should not be injected", "frequency": 100}
    ]
  }' >"$patterns_file"

  export STORY_JSON="{}"

  build_ralph_prompts

  # Should NOT have patterns section
  [[ "$RALPH_USER_PROMPT" != *"## Learned Patterns from Phase L"* ]]
}

@test "US-1214: format patterns with frequency count" {
  local patterns_file="$SPIRAL_SCRATCH_DIR/learned_patterns_iter_1.json"
  $JQ -n '{
    "iteration": 1,
    "patterns": [
      {"pattern": "Test pattern", "frequency": 42}
    ]
  }' >"$patterns_file"

  export STORY_JSON=$($JQ -n '{
    "id": "US-TEST-001",
    "title": "Test Story",
    "tags": [],
    "filesTouch": []
  }')

  build_ralph_prompts

  # Verify format: "- Pattern: <text> (observed Nx)"
  [[ "$RALPH_USER_PROMPT" == *"- Pattern: Test pattern (observed 42x)"* ]]
}
