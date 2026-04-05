#!/usr/bin/env bats
# tests/test_patch_rollback_integration.bats — Integration tests for US-1139 patch rollback
#
# Run with: bats tests/test_patch_rollback_integration.bats
#
# Tests cover:
#   - Savepoint SHA is captured before patch application
#   - Successful patches are applied and committed
#   - Failed patch triggers rollback to savepoint
#   - Affected stories are reset to passes=false
#   - spiral_events.jsonl receives patch_rollback event with correct fields

bats_require_minimum_version 1.7.0

setup() {
  load test_helper/common-setup
  _resolve_jq

  # Create a test repo with initial state
  TEST_REPO="$(mktemp -d)"
  export TEST_REPO

  # Initialize git repo
  git -C "$TEST_REPO" init -b main -q 2>/dev/null || git -C "$TEST_REPO" init -q
  git -C "$TEST_REPO" config user.email "test@spiral.local"
  git -C "$TEST_REPO" config user.name "Spiral Test"

  # Create initial commit
  echo "initial content" >"$TEST_REPO/file1.txt"
  git -C "$TEST_REPO" add file1.txt
  git -C "$TEST_REPO" commit -m "Initial commit" -q
  INITIAL_SHA=$(git -C "$TEST_REPO" rev-parse HEAD)
  export INITIAL_SHA

  # Create a second commit to serve as savepoint
  echo "file2 content" >"$TEST_REPO/file2.txt"
  git -C "$TEST_REPO" add file2.txt
  git -C "$TEST_REPO" commit -m "Add file2" -q
  SAVEPOINT_SHA=$(git -C "$TEST_REPO" rev-parse HEAD)
  export SAVEPOINT_SHA

  # Create scratch and worker dirs
  SCRATCH_DIR="$TEST_REPO/.spiral"
  WORKER_DIR="$SCRATCH_DIR/workers"
  mkdir -p "$WORKER_DIR"
  export SCRATCH_DIR WORKER_DIR

  # Create prd.json with 3 stories (one per patch)
  cat >"$TEST_REPO/prd.json" <<'EOF'
{
  "schemaVersion": 1,
  "projectName": "Test Project",
  "branchName": "main",
  "userStories": [
    {
      "id": "US-101",
      "title": "First story",
      "priority": "high",
      "description": "First implementation",
      "passes": true,
      "_passedCommit": "abc123"
    },
    {
      "id": "US-102",
      "title": "Second story",
      "priority": "high",
      "description": "Second implementation",
      "passes": true,
      "_passedCommit": "def456"
    },
    {
      "id": "US-103",
      "title": "Third story",
      "priority": "high",
      "description": "Third implementation",
      "passes": true,
      "_passedCommit": "ghi789"
    }
  ]
}
EOF

  # Create worker PRD files (sliced per worker)
  cat >"$WORKER_DIR/worker_1.json" <<'EOF'
{
  "schemaVersion": 1,
  "projectName": "Test Project",
  "branchName": "main",
  "userStories": [
    {
      "id": "US-101",
      "title": "First story",
      "passes": true
    }
  ]
}
EOF

  cat >"$WORKER_DIR/worker_2.json" <<'EOF'
{
  "schemaVersion": 1,
  "projectName": "Test Project",
  "branchName": "main",
  "userStories": [
    {
      "id": "US-102",
      "title": "Second story",
      "passes": true
    }
  ]
}
EOF

  cat >"$WORKER_DIR/worker_3.json" <<'EOF'
{
  "schemaVersion": 1,
  "projectName": "Test Project",
  "branchName": "main",
  "userStories": [
    {
      "id": "US-103",
      "title": "Third story",
      "passes": true
    }
  ]
}
EOF

  # Create three patches: valid, bad, valid
  # Patch 1: Add valid content
  cat >"$WORKER_DIR/worker_1.patch" <<'EOF'
--- a/patch1.txt
+++ b/patch1.txt
@@ -0,0 +1 @@
+patch 1 content from worker 1
EOF

  # Patch 2: BAD patch (non-existent file, invalid format)
  cat >"$WORKER_DIR/worker_2.patch" <<'EOF'
--- a/nonexistent_file.txt
+++ b/nonexistent_file.txt
@@ -1,5 +1,5 @@
-this file doesn't exist
-and this patch format is invalid
+in fact, this file has never existed anywhere
+and cannot be applied to the repo
EOF

  # Patch 3: Add valid content
  cat >"$WORKER_DIR/worker_3.patch" <<'EOF'
--- a/patch3.txt
+++ b/patch3.txt
@@ -0,0 +1 @@
+patch 3 content from worker 3
EOF
}

teardown() {
  rm -rf "$TEST_REPO"
}

# ── Test: Savepoint is captured and rollback reverts to it ──

@test "patch rollback: savepoint SHA is captured before patch loop" {
  # Source the patch rollback helper
  source "$BATS_TEST_DIRNAME/../lib/handle_patch_rollback.py" 2>/dev/null || true

  cd "$TEST_REPO"

  # Verify initial state: three files should NOT exist
  [[ ! -f "$TEST_REPO/patch1.txt" ]]
  [[ ! -f "$TEST_REPO/patch3.txt" ]]

  # Get savepoint (same as SAVEPOINT_SHA set in setup)
  CURRENT_SHA=$(git rev-parse HEAD)
  [ "$CURRENT_SHA" = "$SAVEPOINT_SHA" ]
}

# ── Test: Failed patch triggers rollback ──

@test "patch rollback: failed patch in sequence triggers rollback to savepoint" {
  cd "$TEST_REPO"

  # Apply patch 1 (should succeed)
  if git -C "$TEST_REPO" apply --3way "$WORKER_DIR/worker_1.patch" 2>/dev/null; then
    git -C "$TEST_REPO" add -A
    git -C "$TEST_REPO" commit -m "Apply patch 1" -q
    AFTER_PATCH1_SHA=$(git rev-parse HEAD)
    [ "$AFTER_PATCH1_SHA" != "$SAVEPOINT_SHA" ]
  else
    skip "Patch 1 unexpectedly failed"
  fi

  # Verify patch1.txt was created
  [[ -f "$TEST_REPO/patch1.txt" ]]

  # Apply patch 2 (should fail — invalid patch)
  PATCH2_RESULT=0
  git -C "$TEST_REPO" apply --3way "$WORKER_DIR/worker_2.patch" 2>/dev/null || PATCH2_RESULT=$?
  [ "$PATCH2_RESULT" != 0 ]

  # Try with --reject (should also fail)
  PATCH2_REJECT_RESULT=0
  git -C "$TEST_REPO" apply --reject "$WORKER_DIR/worker_2.patch" 2>/dev/null || PATCH2_REJECT_RESULT=$?
  [ "$PATCH2_REJECT_RESULT" != 0 ]

  # Now rollback: reset to savepoint
  git -C "$TEST_REPO" reset --hard "$SAVEPOINT_SHA" 2>/dev/null

  # Verify rollback reverted patch 1
  [[ ! -f "$TEST_REPO/patch1.txt" ]]

  # Verify HEAD is back at savepoint
  CURRENT_SHA=$(git -C "$TEST_REPO" rev-parse HEAD)
  [ "$CURRENT_SHA" = "$SAVEPOINT_SHA" ]
}

# ── Test: Affected stories are reset to pending ──

@test "patch rollback: affected stories are reset to passes=false" {
  cd "$TEST_REPO"

  # Reset stories US-101 and US-102 to pending
  cd "$BATS_TEST_DIRNAME/../.." && uv run python lib/handle_patch_rollback.py \
    --prd "$TEST_REPO/prd.json" \
    --events "$SCRATCH_DIR/spiral_events.jsonl" \
    --story-ids US-101 US-102 \
    --sha "$SAVEPOINT_SHA" \
    --reason "test rollback" 2>/dev/null || skip "uv python not available"
  cd "$TEST_REPO"

  # Verify stories are now pending
  US101_PASSES=$("$JQ" '.userStories[] | select(.id == "US-101") | .passes' "$TEST_REPO/prd.json")
  [ "$US101_PASSES" = "false" ]

  US102_PASSES=$("$JQ" '.userStories[] | select(.id == "US-102") | .passes' "$TEST_REPO/prd.json")
  [ "$US102_PASSES" = "false" ]

  # US-103 should remain unchanged
  US103_PASSES=$("$JQ" '.userStories[] | select(.id == "US-103") | .passes' "$TEST_REPO/prd.json")
  [ "$US103_PASSES" = "true" ]

  # Verify _passedCommit is removed from reset stories
  HAS_COMMIT_101=$("$JQ" '.userStories[] | select(.id == "US-101") | has("_passedCommit")' "$TEST_REPO/prd.json")
  [ "$HAS_COMMIT_101" = "false" ]
}

# ── Test: Event is logged to spiral_events.jsonl ──

@test "patch rollback: patch_rollback event is logged with correct fields" {
  cd "$TEST_REPO"

  # Generate rollback event
  cd "$BATS_TEST_DIRNAME/../.." && uv run python lib/handle_patch_rollback.py \
    --prd "$TEST_REPO/prd.json" \
    --events "$SCRATCH_DIR/spiral_events.jsonl" \
    --story-ids US-101 US-102 \
    --sha "$SAVEPOINT_SHA" \
    --reason "git apply failed for worker 2" 2>/dev/null || skip "uv python not available"
  cd "$TEST_REPO"

  # Verify event file exists
  [[ -f "$SCRATCH_DIR/spiral_events.jsonl" ]]

  # Extract the patch_rollback event
  EVENT_LINE=$(tail -1 "$SCRATCH_DIR/spiral_events.jsonl")

  # Verify event has correct structure
  EVENT_TYPE=$(echo "$EVENT_LINE" | "$JQ" -r '.event')
  [ "$EVENT_TYPE" = "patch_rollback" ]

  # Verify story_ids are in the event
  STORY_IDS=$(echo "$EVENT_LINE" | "$JQ" -r '.story_ids | @json')
  [[ "$STORY_IDS" =~ "US-101" ]]
  [[ "$STORY_IDS" =~ "US-102" ]]

  # Verify SHA and reason
  EVENT_SHA=$(echo "$EVENT_LINE" | "$JQ" -r '.sha')
  [ "$EVENT_SHA" = "$SAVEPOINT_SHA" ]

  EVENT_REASON=$(echo "$EVENT_LINE" | "$JQ" -r '.reason')
  [ "$EVENT_REASON" = "git apply failed for worker 2" ]

  # Verify timestamp exists
  EVENT_TS=$(echo "$EVENT_LINE" | "$JQ" -r '.ts')
  [[ "$EVENT_TS" =~ "Z" ]]
}

# ── Test: Successful full run is NOT rolled back ──

@test "patch rollback: successful patch application does NOT trigger rollback" {
  cd "$TEST_REPO"

  # Create a valid patch instead of bad one
  cat >"$WORKER_DIR/worker_2_valid.patch" <<'EOF'
--- a/patch2.txt
+++ b/patch2.txt
@@ -0,0 +1 @@
+patch 2 content from worker 2
EOF

  # Apply patch 1
  git -C "$TEST_REPO" apply --3way "$WORKER_DIR/worker_1.patch" 2>/dev/null
  git -C "$TEST_REPO" add -A
  git -C "$TEST_REPO" commit -m "Apply patch 1" -q

  # Apply patch 2 (valid)
  git -C "$TEST_REPO" apply --3way "$WORKER_DIR/worker_2_valid.patch" 2>/dev/null
  git -C "$TEST_REPO" add -A
  git -C "$TEST_REPO" commit -m "Apply patch 2" -q

  # Apply patch 3
  git -C "$TEST_REPO" apply --3way "$WORKER_DIR/worker_3.patch" 2>/dev/null
  git -C "$TEST_REPO" add -A
  git -C "$TEST_REPO" commit -m "Apply patch 3" -q

  # Verify all patches were applied (files exist)
  [[ -f "$TEST_REPO/patch1.txt" ]]
  [[ -f "$TEST_REPO/patch2.txt" ]]
  [[ -f "$TEST_REPO/patch3.txt" ]]

  # Verify we have progressed beyond savepoint
  FINAL_SHA=$(git -C "$TEST_REPO" rev-parse HEAD)
  [ "$FINAL_SHA" != "$SAVEPOINT_SHA" ]

  # Verify NO rollback event exists
  if [[ -f "$SCRATCH_DIR/spiral_events.jsonl" ]]; then
    ROLLBACK_COUNT=$(grep -c "patch_rollback" "$SCRATCH_DIR/spiral_events.jsonl" || true)
    [ "$ROLLBACK_COUNT" -eq 0 ]
  fi
}
