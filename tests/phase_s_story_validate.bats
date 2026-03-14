#!/usr/bin/env bats
# tests/phase_s_story_validate.bats — Unit tests for Phase S story validation
#
# Run with: bats tests/phase_s_story_validate.bats
#
# Tests verify:
#   - Off-topic stories (no keyword overlap with goals) are rejected
#   - On-topic stories (keyword overlap >= min) are accepted
#   - Constitution violations are rejected when SPIRAL_SPECKIT_CONSTITUTION is set
#   - Phase S produces _validated_stories.json and _story_rejected.json
#   - Empty goals list causes all stories to be accepted (no false rejections)
#   - Missing research/test-stories files are handled gracefully
#
# NOTE (Windows/Git bash): Python inline -c strings don't get POSIX→Windows path
# translation. All paths passed to Python must be via sys.argv (not -c literals).

setup() {
  TEST_TMP="$(mktemp -d)"
  export TEST_TMP
  export SCRATCH_DIR="$TEST_TMP/.spiral"
  mkdir -p "$SCRATCH_DIR"

  export SPIRAL_HOME
  SPIRAL_HOME="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  export SPIRAL_PYTHON
  SPIRAL_PYTHON="$(command -v python3)"

  # Paths for output files
  export VALIDATED_OUT="$SCRATCH_DIR/_validated_stories.json"
  export REJECTED_OUT="$SCRATCH_DIR/_story_rejected.json"

  # Minimal prd.json with goals[]
  cat > "$TEST_TMP/prd.json" <<'EOF'
{
  "schemaVersion": 1,
  "projectName": "Spiral",
  "productName": "Spiral CLI",
  "branchName": "main",
  "description": "Autonomous development loop",
  "goals": [
    "Wire the four new lib modules into the live spiral.sh loop",
    "Enable Chrome DevTools MCP as a first-class visual validation tool in Phase V"
  ],
  "userStories": []
}
EOF

  # Research output with on-topic and off-topic stories
  cat > "$SCRATCH_DIR/_research_output.json" <<'EOF'
{
  "stories": [
    {
      "id": "CAND-001",
      "title": "Wire validation module into spiral loop",
      "description": "Connect the validation lib module to the spiral.sh main loop for automated checks",
      "priority": "high",
      "acceptanceCriteria": ["Module sourced in spiral.sh"],
      "technicalNotes": [],
      "dependencies": [],
      "estimatedComplexity": "small"
    },
    {
      "id": "CAND-002",
      "title": "Add recipe management for the cafe menu",
      "description": "Build a recipe database for the cafe to track ingredients and costs",
      "priority": "low",
      "acceptanceCriteria": ["Recipe CRUD works"],
      "technicalNotes": [],
      "dependencies": [],
      "estimatedComplexity": "medium"
    },
    {
      "id": "CAND-003",
      "title": "Enable Chrome DevTools MCP visual validation",
      "description": "Integrate Chrome DevTools MCP as a visual validation tool in the spiral Phase V pipeline",
      "priority": "medium",
      "acceptanceCriteria": ["DevTools MCP called in Phase V"],
      "technicalNotes": [],
      "dependencies": [],
      "estimatedComplexity": "medium"
    }
  ]
}
EOF

  # Empty test-stories output
  echo '{"stories":[]}' > "$SCRATCH_DIR/_test_stories_output.json"
}

teardown() {
  # Use Python to remove temp dir (handles Windows paths correctly)
  "$SPIRAL_PYTHON" -c "import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$TEST_TMP"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

# Count stories in a JSON file at the given key.
# Passes path via sys.argv so Git bash→Windows path translation works.
py_count_stories() {
  local file="$1"
  "$SPIRAL_PYTHON" -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(len(d.get('stories', [])))
except Exception:
    print(0)
" "$file" 2>/dev/null || echo "0"
}

# Read a field from the first story in a JSON file's .stories array.
py_first_story_field() {
  local file="$1" field="$2"
  "$SPIRAL_PYTHON" -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d['stories'][0].get(sys.argv[2], ''))
except Exception:
    print('')
" "$file" "$field" 2>/dev/null || echo ""
}

# Check if any story in the .stories array has a field containing a substring.
py_any_field_contains() {
  local file="$1" field="$2" substr="$3"
  "$SPIRAL_PYTHON" -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    match = any(sys.argv[3].lower() in s.get(sys.argv[2], '').lower()
                for s in d.get('stories', []))
    print('yes' if match else 'no')
except Exception:
    print('no')
" "$file" "$field" "$substr" 2>/dev/null || echo "no"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "off-topic stories are rejected and on-topic stories are accepted" {
  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/validate_stories.py" \
    --prd "$TEST_TMP/prd.json" \
    --research "$SCRATCH_DIR/_research_output.json" \
    --test-stories "$SCRATCH_DIR/_test_stories_output.json" \
    --validated-out "$VALIDATED_OUT" \
    --rejected-out "$REJECTED_OUT" \
    --min-overlap 1

  [ "$status" -eq 0 ]
  [ -f "$VALIDATED_OUT" ]
  [ -f "$REJECTED_OUT" ]

  # CAND-001 and CAND-003 have goal keywords (spiral, loop, module, chrome, devtools, validation)
  # CAND-002 (cafe recipe) has zero overlap with goals → rejected
  accepted=$(py_count_stories "$VALIDATED_OUT")
  rejected=$(py_count_stories "$REJECTED_OUT")

  [ "$accepted" -eq 2 ]
  [ "$rejected" -eq 1 ]
}

@test "rejected story has _rejection_reason field" {
  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/validate_stories.py" \
    --prd "$TEST_TMP/prd.json" \
    --research "$SCRATCH_DIR/_research_output.json" \
    --test-stories "$SCRATCH_DIR/_test_stories_output.json" \
    --validated-out "$VALIDATED_OUT" \
    --rejected-out "$REJECTED_OUT" \
    --min-overlap 1

  [ "$status" -eq 0 ]

  has_reason=$(py_any_field_contains "$REJECTED_OUT" "_rejection_reason" "goal")
  [ "$has_reason" = "yes" ]
}

@test "off-topic story title matches the cafe recipe story" {
  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/validate_stories.py" \
    --prd "$TEST_TMP/prd.json" \
    --research "$SCRATCH_DIR/_research_output.json" \
    --test-stories "$SCRATCH_DIR/_test_stories_output.json" \
    --validated-out "$VALIDATED_OUT" \
    --rejected-out "$REJECTED_OUT" \
    --min-overlap 1

  [ "$status" -eq 0 ]

  rejected_title=$(py_first_story_field "$REJECTED_OUT" "title")
  [ "$rejected_title" = "Add recipe management for the cafe menu" ]
}

@test "min-overlap 0 accepts all stories regardless of topic" {
  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/validate_stories.py" \
    --prd "$TEST_TMP/prd.json" \
    --research "$SCRATCH_DIR/_research_output.json" \
    --test-stories "$SCRATCH_DIR/_test_stories_output.json" \
    --validated-out "$VALIDATED_OUT" \
    --rejected-out "$REJECTED_OUT" \
    --min-overlap 0

  [ "$status" -eq 0 ]

  accepted=$(py_count_stories "$VALIDATED_OUT")
  rejected=$(py_count_stories "$REJECTED_OUT")

  [ "$accepted" -eq 3 ]
  [ "$rejected" -eq 0 ]
}

@test "empty goals list causes all stories to be accepted" {
  cat > "$TEST_TMP/prd.json" <<'EOF'
{
  "schemaVersion": 1,
  "projectName": "Spiral",
  "userStories": [],
  "goals": []
}
EOF

  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/validate_stories.py" \
    --prd "$TEST_TMP/prd.json" \
    --research "$SCRATCH_DIR/_research_output.json" \
    --test-stories "$SCRATCH_DIR/_test_stories_output.json" \
    --validated-out "$VALIDATED_OUT" \
    --rejected-out "$REJECTED_OUT" \
    --min-overlap 1

  [ "$status" -eq 0 ]

  accepted=$(py_count_stories "$VALIDATED_OUT")
  [ "$accepted" -eq 3 ]
}

@test "constitution violations are rejected when constitution file is set" {
  local constitution="$TEST_TMP/constitution.md"
  cat > "$constitution" <<'EOF'
# Project Constitution

NOT: cafe
NOT: recipe
AVOID: food and beverage stories
EOF

  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/validate_stories.py" \
    --prd "$TEST_TMP/prd.json" \
    --research "$SCRATCH_DIR/_research_output.json" \
    --test-stories "$SCRATCH_DIR/_test_stories_output.json" \
    --validated-out "$VALIDATED_OUT" \
    --rejected-out "$REJECTED_OUT" \
    --constitution "$constitution" \
    --min-overlap 0

  [ "$status" -eq 0 ]

  rejected=$(py_count_stories "$REJECTED_OUT")
  [ "$rejected" -ge 1 ]

  has_constitution_reason=$(py_any_field_contains "$REJECTED_OUT" "_rejection_reason" "constitution")
  [ "$has_constitution_reason" = "yes" ]
}

@test "missing research file produces empty validated output without error" {
  # Remove the research file so it doesn't exist
  "$SPIRAL_PYTHON" -c "import os, sys; os.remove(sys.argv[1])" "$SCRATCH_DIR/_research_output.json"

  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/validate_stories.py" \
    --prd "$TEST_TMP/prd.json" \
    --research "$SCRATCH_DIR/_research_output.json" \
    --test-stories "$SCRATCH_DIR/_test_stories_output.json" \
    --validated-out "$VALIDATED_OUT" \
    --rejected-out "$REJECTED_OUT" \
    --min-overlap 1

  [ "$status" -eq 0 ]
  [ -f "$VALIDATED_OUT" ]

  accepted=$(py_count_stories "$VALIDATED_OUT")
  [ "$accepted" -eq 0 ]
}

@test "stories from test-stories file are also validated" {
  cat > "$SCRATCH_DIR/_test_stories_output.json" <<'EOF'
{
  "stories": [
    {
      "id": "TEST-001",
      "title": "Fix broken hostel booking widget",
      "description": "The hostel booking calendar widget fails on mobile browsers",
      "priority": "high",
      "acceptanceCriteria": ["Booking works on mobile"],
      "technicalNotes": [],
      "dependencies": [],
      "estimatedComplexity": "small"
    }
  ]
}
EOF

  run "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/validate_stories.py" \
    --prd "$TEST_TMP/prd.json" \
    --research "$SCRATCH_DIR/_research_output.json" \
    --test-stories "$SCRATCH_DIR/_test_stories_output.json" \
    --validated-out "$VALIDATED_OUT" \
    --rejected-out "$REJECTED_OUT" \
    --min-overlap 1

  [ "$status" -eq 0 ]

  # CAND-002 (cafe) and TEST-001 (hostel booking) have no goal-keyword overlap → rejected
  rejected=$(py_count_stories "$REJECTED_OUT")
  [ "$rejected" -ge 2 ]
}

@test "run_phase_story_validate shell function produces _validated_stories.json" {
  source "$SPIRAL_HOME/lib/phases/phase_s_story_validate.sh"

  export RESEARCH_OUTPUT="$SCRATCH_DIR/_research_output.json"
  export TEST_OUTPUT="$SCRATCH_DIR/_test_stories_output.json"
  export PRD_FILE="$TEST_TMP/prd.json"
  export SPIRAL_STORY_VALIDATE_MIN_OVERLAP=1

  run run_phase_story_validate "1" \
    "$RESEARCH_OUTPUT" "$TEST_OUTPUT" "$PRD_FILE" "$SCRATCH_DIR" \
    "$SPIRAL_PYTHON" "$SPIRAL_HOME"

  [ "$status" -eq 0 ]
  [ -f "$SCRATCH_DIR/_validated_stories.json" ]
  [ -f "$SCRATCH_DIR/_story_rejected.json" ]
}
