#!/usr/bin/env bats
# tests/commit_revert.bats — US-343: transactional snapshot/restore

# Source the module under test
source lib/impl/commit_revert.sh

setup() {
  export TEST_REPO_TEMP
  TEST_REPO_TEMP=$(mktemp -d)
  export TEST_SNAPSHOT_DIR
  TEST_SNAPSHOT_DIR="$TEST_REPO_TEMP/.snapshots"
  mkdir -p "$TEST_SNAPSHOT_DIR"

  # Initialize a minimal git repo
  cd "$TEST_REPO_TEMP"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test User"
  echo "initial" >README.md
  git add README.md
  git commit -qm "Initial commit"
}

teardown() {
  if [[ -d "$TEST_REPO_TEMP" ]]; then
    rm -rf "$TEST_REPO_TEMP"
  fi
  unset SNAPSHOT_STASH_SHA
  unset SNAPSHOT_MANIFEST
}

@test "create_snapshot succeeds with no changes" {
  cd "$TEST_REPO_TEMP"
  create_snapshot "$TEST_SNAPSHOT_DIR" "$TEST_REPO_TEMP"
  [[ "$SNAPSHOT_STASH_SHA" == "NONE" ]]
  [[ -f "$SNAPSHOT_MANIFEST" ]]
}

@test "create_snapshot records git stash when changes exist" {
  cd "$TEST_REPO_TEMP"
  echo "modified" >>README.md
  git add README.md
  create_snapshot "$TEST_SNAPSHOT_DIR" "$TEST_REPO_TEMP"
  [[ "$SNAPSHOT_STASH_SHA" != "NONE" ]]
  [[ -f "$SNAPSHOT_MANIFEST" ]]
}

@test "create_snapshot records non-git files in manifest" {
  cd "$TEST_REPO_TEMP"
  echo "untracked" >untracked.txt
  git status --short
  create_snapshot "$TEST_SNAPSHOT_DIR" "$TEST_REPO_TEMP"
  grep -q "untracked.txt" "$SNAPSHOT_MANIFEST"
}

@test "create_snapshot fails gracefully if snapshot_dir is not writable" {
  local readonly_dir="/root/impossible_spiral_test_$$"
  mkdir -p "$readonly_dir" 2>/dev/null || skip "Cannot test readonly directory on this system"
  ! create_snapshot "$readonly_dir/snap" "$TEST_REPO_TEMP"
}

@test "restore_snapshot restores stash when SNAPSHOT_STASH_SHA is set" {
  cd "$TEST_REPO_TEMP"
  echo "modified" >>README.md
  git add README.md
  create_snapshot "$TEST_SNAPSHOT_DIR" "$TEST_REPO_TEMP"

  # Verify stash was created
  [[ "$SNAPSHOT_STASH_SHA" != "NONE" ]]

  # Discard the modified file
  git reset --hard HEAD -q

  # Restore snapshot
  restore_snapshot "$TEST_SNAPSHOT_DIR" "$TEST_REPO_TEMP"

  # Verify restore succeeded (function returned 0)
  [[ $? -eq 0 ]]
}

@test "restore_snapshot cleans up new non-git files" {
  cd "$TEST_REPO_TEMP"
  create_snapshot "$TEST_SNAPSHOT_DIR" "$TEST_REPO_TEMP"

  # Create new files after snapshot
  echo "new" >newfile.txt
  touch another_file.log

  # Restore snapshot
  restore_snapshot "$TEST_SNAPSHOT_DIR" "$TEST_REPO_TEMP"

  # Verify new files were deleted
  [[ ! -f "$TEST_REPO_TEMP/newfile.txt" ]]
  [[ ! -f "$TEST_REPO_TEMP/another_file.log" ]]
}

@test "restore_snapshot returns 0 on full success" {
  cd "$TEST_REPO_TEMP"
  create_snapshot "$TEST_SNAPSHOT_DIR" "$TEST_REPO_TEMP"
  restore_snapshot "$TEST_SNAPSHOT_DIR" "$TEST_REPO_TEMP"
  [[ $? -eq 0 ]]
}

@test "restore_snapshot handles missing manifest gracefully" {
  cd "$TEST_REPO_TEMP"
  SNAPSHOT_MANIFEST="/nonexistent/manifest.txt"
  export SNAPSHOT_MANIFEST
  SNAPSHOT_STASH_SHA="NONE"
  export SNAPSHOT_STASH_SHA

  restore_snapshot "$TEST_SNAPSHOT_DIR" "$TEST_REPO_TEMP"
  [[ $? -eq 0 ]]
}

@test "log_rollback_event writes valid JSON to spiral_events.jsonl" {
  export SPIRAL_SCRATCH_DIR="$TEST_REPO_TEMP"
  export SPIRAL_RUN_ID="test-run-123"

  log_rollback_event "US-999" "success" "1234"

  [[ -f "$TEST_REPO_TEMP/spiral_events.jsonl" ]]
  grep -q '"event":"rollback_success"' "$TEST_REPO_TEMP/spiral_events.jsonl"
  grep -q '"story_id":"US-999"' "$TEST_REPO_TEMP/spiral_events.jsonl"
  grep -q '"elapsed_ms":1234' "$TEST_REPO_TEMP/spiral_events.jsonl"
}

@test "log_rollback_event includes details when provided" {
  export SPIRAL_SCRATCH_DIR="$TEST_REPO_TEMP"
  export SPIRAL_RUN_ID="test-run-456"

  log_rollback_event "US-998" "stash_restore_failed" "5000" "permission denied"

  grep -q '"details":"permission denied"' "$TEST_REPO_TEMP/spiral_events.jsonl"
}
