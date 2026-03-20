#!/usr/bin/env bats
# tests/test_cost_ceiling.bats — Tests for SPIRAL_COST_CEILING pre-Phase I budget gate
#
# Run with: bats tests/test_cost_ceiling.bats
#
# Tests cover:
#   - budget_analyzer.py detects when cost would exceed ceiling
#   - rollback_story.py removes lowest-priority pending story
#   - budget gate logic re-checks after rollback
#   - no alert when SPIRAL_COST_CEILING is unset or within budget

bats_require_minimum_version 1.7.0
SPIRAL_ROOT="$(cd "$(dirname "${BATS_TEST_DIRNAME}")" && pwd)"
LIB_HOME="$SPIRAL_ROOT/lib"

setup() {
  load test_helper/common-setup
  _resolve_jq

  # Create a fresh temp dir for test artifacts
  TEST_WORK="$(mktemp -d)"
  export TEST_WORK
  export SPIRAL_ROOT
  export LIB_HOME
}

teardown() {
  rm -rf "$TEST_WORK"
}

# ── Test 1: budget_analyzer.py detects budget exceeded ────────────────────────

@test "budget_analyzer: detects when cost would exceed ceiling" {
  # Create minimal prd.json with 2 pending stories
  cat >"$TEST_WORK/prd.json" <<'PRDJSON'
{
  "schemaVersion": 1,
  "userStories": [
    {"id": "US-001", "title": "Story 1", "passes": false, "model": "sonnet", "priority": "high"},
    {"id": "US-002", "title": "Story 2", "passes": false, "model": "haiku", "priority": "low"}
  ]
}
PRDJSON

  # Create empty results.tsv (no prior spend)
  cat >"$TEST_WORK/results.tsv" <<EOF
story_id	model	tokens	duration_sec	cost_usd
EOF

  # Set cost ceiling to $0.001 (very low, will definitely be exceeded)
  cd "$SPIRAL_ROOT"
  run python3 << 'PYEOF'
import json, sys, os
sys.path.insert(0, './lib')
from budget_analyzer import check_budget_gate
from pathlib import Path

prd = Path(os.environ['TEST_WORK']) / 'prd.json'
results = Path(os.environ['TEST_WORK']) / 'results.tsv'

result = check_budget_gate(prd, results, cost_ceiling_usd=0.001)
print(json.dumps(result, indent=2))
PYEOF

  # Should detect that budget would be exceeded
  assert_output --partial '"would_exceed": true'
}

# ── Test 2: budget_analyzer returns correct structure ─────────────────────────

@test "budget_analyzer: returns cost breakdown with pending count" {
  cat >"$TEST_WORK/prd.json" <<'PRDJSON'
{
  "schemaVersion": 1,
  "userStories": [
    {"id": "US-001", "title": "Story 1", "passes": false, "model": "sonnet", "priority": "high"},
    {"id": "US-002", "title": "Story 2", "passes": false, "model": "haiku", "priority": "medium"}
  ]
}
PRDJSON

  cat >"$TEST_WORK/results.tsv" <<EOF
story_id	model	tokens	duration_sec	cost_usd
EOF

  cd "$SPIRAL_ROOT"
  run python3 << 'PYEOF'
import json, sys, os
sys.path.insert(0, './lib')
from budget_analyzer import check_budget_gate
from pathlib import Path

prd = Path(os.environ['TEST_WORK']) / 'prd.json'
results = Path(os.environ['TEST_WORK']) / 'results.tsv'

result = check_budget_gate(prd, results, cost_ceiling_usd=10.0)
print(result['pending_count'])
PYEOF

  assert_output "2"
}

# ── Test 3: rollback_story removes lowest-priority pending story ────────────────

@test "rollback_story: removes lowest-priority pending story" {
  cat >"$TEST_WORK/prd.json" <<'PRDJSON'
{
  "schemaVersion": 1,
  "userStories": [
    {"id": "US-001", "title": "Critical", "passes": false, "priority": "critical"},
    {"id": "US-002", "title": "High", "passes": false, "priority": "high"},
    {"id": "US-003", "title": "Low", "passes": false, "priority": "low"}
  ]
}
PRDJSON

  # Call rollback_story.py
  cd "$SPIRAL_ROOT"
  run python3 << 'PYEOF'
import json, sys, os
sys.path.insert(0, './lib')
from rollback_story import rollback_story
from pathlib import Path

result = rollback_story(Path(os.environ['TEST_WORK']) / 'prd.json')
print(json.dumps(result, indent=2))
PYEOF

  # Should succeed and report removed story
  assert_output --partial '"success": true'
  assert_output --partial '"removed_story_id": "US-003"'
  assert_output --partial '"remaining_pending": 2'

  # Verify prd.json was modified
  cd "$SPIRAL_ROOT"
  remaining=$(python3 << 'PYEOF2'
import json, os
with open(os.path.join(os.environ['TEST_WORK'], 'prd.json')) as f:
    d = json.load(f)
print(len([s for s in d['userStories'] if not s.get('passes')]))
PYEOF2
)
  [ "$remaining" -eq 2 ]
}

# ── Test 4: rollback_story honors priority order (critical > high > medium > low) ──

@test "rollback_story: honors priority ranking (lowest=last to remove)" {
  # 3 stories: low, critical, medium; should remove low
  cat >"$TEST_WORK/prd.json" <<'PRDJSON'
{
  "schemaVersion": 1,
  "userStories": [
    {"id": "US-001", "title": "Low story", "passes": false, "priority": "low"},
    {"id": "US-002", "title": "Critical story", "passes": false, "priority": "critical"},
    {"id": "US-003", "title": "Medium story", "passes": false, "priority": "medium"}
  ]
}
PRDJSON

  cd "$SPIRAL_ROOT"
  run python3 << 'PYEOF'
import json, sys, os
sys.path.insert(0, './lib')
from rollback_story import rollback_story
from pathlib import Path

result = rollback_story(Path(os.environ['TEST_WORK']) / 'prd.json')
print(result['removed_story_id'])
PYEOF

  assert_output "US-001"
}

# ── Test 5: no budget alert when SPIRAL_COST_CEILING is unset (None/0) ────────

@test "budget_analyzer: returns would_exceed=false when ceiling is None" {
  cat >"$TEST_WORK/prd.json" <<'PRDJSON'
{
  "schemaVersion": 1,
  "userStories": [
    {"id": "US-001", "title": "Story", "passes": false, "model": "sonnet"}
  ]
}
PRDJSON

  cat >"$TEST_WORK/results.tsv" <<EOF
story_id	model	tokens	duration_sec	cost_usd
EOF

  cd "$SPIRAL_ROOT"
  run python3 << 'PYEOF'
import json, sys, os
sys.path.insert(0, './lib')
from budget_analyzer import check_budget_gate
from pathlib import Path

prd = Path(os.environ['TEST_WORK']) / 'prd.json'
results = Path(os.environ['TEST_WORK']) / 'results.tsv'

result = check_budget_gate(prd, results, cost_ceiling_usd=None)
print(json.dumps(result, indent=2))
PYEOF

  assert_output --partial '"would_exceed": false'
}

# ── Test 6: no budget alert when estimated cost is within ceiling ─────────────

@test "budget_analyzer: returns would_exceed=false when cost within ceiling" {
  cat >"$TEST_WORK/prd.json" <<'PRDJSON'
{
  "schemaVersion": 1,
  "userStories": [
    {"id": "US-001", "title": "Small story", "passes": false, "model": "haiku", "priority": "low"}
  ]
}
PRDJSON

  cat >"$TEST_WORK/results.tsv" <<EOF
story_id	model	tokens	duration_sec	cost_usd
EOF

  # Very high ceiling ($10,000) — cost should be within budget
  cd "$SPIRAL_ROOT"
  run python3 << 'PYEOF'
import json, sys, os
sys.path.insert(0, './lib')
from budget_analyzer import check_budget_gate
from pathlib import Path

prd = Path(os.environ['TEST_WORK']) / 'prd.json'
results = Path(os.environ['TEST_WORK']) / 'results.tsv'

result = check_budget_gate(prd, results, cost_ceiling_usd=10000.0)
print(json.dumps(result, indent=2))
PYEOF

  assert_output --partial '"would_exceed": false'
}

# ── Test 7: rollback_story handles no pending stories (error case) ────────────

@test "rollback_story: returns error when no pending stories" {
  # Create prd.json with only completed stories
  cat >"$TEST_WORK/prd.json" <<'PRDJSON'
{
  "schemaVersion": 1,
  "userStories": [
    {"id": "US-001", "title": "Done", "passes": true}
  ]
}
PRDJSON

  cd "$SPIRAL_ROOT"
  run python3 << 'PYEOF'
import json, sys, os
sys.path.insert(0, './lib')
from rollback_story import rollback_story
from pathlib import Path

result = rollback_story(Path(os.environ['TEST_WORK']) / 'prd.json')
print(json.dumps(result, indent=2))
PYEOF

  # Should fail gracefully
  assert_output --partial '"success": false'
  assert_output --partial 'No pending stories'
}
