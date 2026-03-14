#!/usr/bin/env bats
# tests/test_rollback.bats — Unit tests for spiral.sh --rollback
#
# Run with: bats tests/test_rollback.bats
#
# Tests cover:
#   - Successful rollback: git revert called, prd.json reset to pending
#   - Missing _passedCommit error: exits ERR_ROLLBACK_FAILED (12) with message
#   - Dirty working-tree guard: exits ERR_ROLLBACK_FAILED (12) with message
#   - Story not found: exits ERR_STORY_NOT_FOUND (11)

SPIRAL_SH="$(cd "$(dirname "${BATS_TEST_DIRNAME}")" && pwd)/spiral.sh"

setup() {
  # Create a fresh temp git repo for each test
  TEST_REPO="$(mktemp -d)"
  export TEST_REPO

  # Init git repo with a dummy user (needed for commits)
  git -C "$TEST_REPO" init -b main -q 2>/dev/null || git -C "$TEST_REPO" init -q
  git -C "$TEST_REPO" config user.email "test@spiral.local"
  git -C "$TEST_REPO" config user.name "Spiral Test"

  # Create an initial commit so HEAD exists
  echo "initial" > "$TEST_REPO/README.md"
  git -C "$TEST_REPO" add README.md
  git -C "$TEST_REPO" commit -m "Initial commit" -q

  # Create a second commit to be reverted (this is _passedCommit)
  echo "story impl" > "$TEST_REPO/story.md"
  git -C "$TEST_REPO" add story.md
  git -C "$TEST_REPO" commit -m "feat: implement US-001" -q
  STORY_SHA=$(git -C "$TEST_REPO" rev-parse HEAD)
  export STORY_SHA

  # Create scratch dir
  SCRATCH_DIR="$TEST_REPO/.spiral"
  mkdir -p "$SCRATCH_DIR"
  export SCRATCH_DIR

  # Resolve Windows-compatible path for PRD_FILE (for Python assertions)
  # On MSYS2/Git Bash, convert /tmp/... to a Windows path for Python
  if command -v cygpath &>/dev/null; then
    WIN_TEST_REPO="$(cygpath -w "$TEST_REPO")"
  else
    WIN_TEST_REPO="$TEST_REPO"
  fi
  export WIN_TEST_REPO

  # Create prd.json with one passed story (with _passedCommit)
  cat > "$TEST_REPO/prd.json" <<PRDJSON
{
  "schemaVersion": 1,
  "projectName": "Test Project",
  "productName": "Test",
  "branchName": "main",
  "description": "Test PRD",
  "userStories": [
    {
      "id": "US-001",
      "title": "Test story one",
      "priority": "high",
      "description": "A story",
      "acceptanceCriteria": ["Works"],
      "technicalNotes": [],
      "dependencies": [],
      "estimatedComplexity": "small",
      "passes": true,
      "_passedCommit": "$STORY_SHA"
    }
  ]
}
PRDJSON

  # Create spiral.config.sh — do NOT set SPIRAL_HOME so spiral.sh keeps its own lib/
  cat > "$TEST_REPO/spiral.config.sh" <<CONFEOF
#!/bin/bash
export REPO_ROOT="$TEST_REPO"
export PRD_FILE="$TEST_REPO/prd.json"
export SCRATCH_DIR="$SCRATCH_DIR"
export SPIRAL_PYTHON="python3"
export SPIRAL_VALIDATE_CMD="echo 'test-validate-ok'"
CONFEOF
  chmod +x "$TEST_REPO/spiral.config.sh"
}

teardown() {
  rm -rf "$TEST_REPO"
}

# ── Test: successful rollback ─────────────────────────────────────────────────

@test "--rollback reverts commit and resets prd.json to pending" {
  cd "$TEST_REPO"

  run bash "$SPIRAL_SH" --rollback US-001

  # Should exit 0 on success
  [ "$status" -eq 0 ]

  # Read prd.json using cwd-relative path (avoids MSYS2/Windows path translation issues)
  passes=$(python3 -c "
import json, os
with open(os.path.join(os.getcwd(), 'prd.json'), encoding='utf-8') as f:
    d = json.load(f)
s = next(x for x in d['userStories'] if x['id'] == 'US-001')
print(str(s.get('passes', 'MISSING')).lower())
")
  [ "$passes" = "false" ]

  # _passedCommit should be absent
  has_commit=$(python3 -c "
import json, os
with open(os.path.join(os.getcwd(), 'prd.json'), encoding='utf-8') as f:
    d = json.load(f)
s = next(x for x in d['userStories'] if x['id'] == 'US-001')
print('yes' if '_passedCommit' in s else 'no')
")
  [ "$has_commit" = "no" ]

  # A revert commit should have been created
  revert_count=$(git -C "$TEST_REPO" log --oneline | grep -c "Revert" || true)
  [ "$revert_count" -ge 1 ]
}

# ── Test: missing _passedCommit ───────────────────────────────────────────────

@test "--rollback exits 12 when _passedCommit is absent" {
  cd "$TEST_REPO"

  # Remove _passedCommit from prd.json using Python with Windows-compatible path
  python3 -c "
import json, os
path = os.path.join(os.getcwd(), 'prd.json')
with open(path, encoding='utf-8') as f:
    d = json.load(f)
s = next(x for x in d['userStories'] if x['id'] == 'US-001')
s.pop('_passedCommit', None)
with open(path, 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=2)
"

  run bash "$SPIRAL_SH" --rollback US-001

  # Should exit 12 (ERR_ROLLBACK_FAILED)
  [ "$status" -eq 12 ]

  # Output should contain actionable error message
  [[ "$output" == *"no _passedCommit"* ]]
}

# ── Test: dirty working-tree guard ───────────────────────────────────────────

@test "--rollback exits 12 when working tree is dirty" {
  cd "$TEST_REPO"

  # Create an uncommitted TRACKED change (stage and unstage to make it modified)
  git -C "$TEST_REPO" add README.md
  echo "dirty change" >> "$TEST_REPO/README.md"

  run bash "$SPIRAL_SH" --rollback US-001

  # Should exit 12 (ERR_ROLLBACK_FAILED)
  [ "$status" -eq 12 ]

  # Output should mention uncommitted changes
  [[ "$output" == *"uncommitted changes"* ]]
}

# ── Test: story not found ─────────────────────────────────────────────────────

@test "--rollback exits 11 when story ID is not in prd.json" {
  cd "$TEST_REPO"

  run bash "$SPIRAL_SH" --rollback US-999

  # Should exit 11 (ERR_STORY_NOT_FOUND)
  [ "$status" -eq 11 ]

  [[ "$output" == *"not found"* ]]
}
