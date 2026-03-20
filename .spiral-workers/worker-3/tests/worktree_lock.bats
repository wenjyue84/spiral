#!/usr/bin/env bats
# tests/worktree_lock.bats — Tests for US-372: --lock flag on git worktree add
#
# Run with: bats tests/worktree_lock.bats
#
# Tests verify:
#   - Worktree created with --lock survives git worktree prune
#   - Locked worktree can be unlocked then removed
#   - Lock reason is set correctly

bats_require_minimum_version 1.7.0

# ── Setup / Teardown ─────────────────────────────────────────────────────────

setup() {
  TEST_REPO="$(mktemp -d)"
  cd "$TEST_REPO"
  git init -q
  git commit --allow-empty -m "init" -q
  WTREE_BASE="$TEST_REPO/.spiral-workers"
  mkdir -p "$WTREE_BASE"
}

teardown() {
  cd /
  # Unlock and remove any remaining worktrees
  for wt in "$WTREE_BASE"/worker-*; do
    [[ -d "$wt" ]] || continue
    git -C "$TEST_REPO" worktree unlock "$wt" 2>/dev/null || true
    git -C "$TEST_REPO" worktree remove "$wt" --force 2>/dev/null || true
  done
  rm -rf "$TEST_REPO"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "locked worktree survives git worktree prune" {
  local wt="$WTREE_BASE/worker-1"

  # Create worktree with --lock (same pattern as run_parallel_ralph.sh)
  git -C "$TEST_REPO" worktree add --lock --reason "spiral-worker-1" "$wt" -b spiral-worker-1 HEAD

  # Remove the worktree directory (simulating a crash leaving stale admin record)
  rm -rf "$wt"

  # Prune should NOT remove the admin record because the worktree is locked
  git -C "$TEST_REPO" worktree prune

  # The worktree should still be listed (admin record preserved)
  # Match on worker directory name (paths may differ between MSYS and Windows-native git)
  run git -C "$TEST_REPO" worktree list --porcelain
  [[ "$output" == *"worker-1"* ]]

  # Cleanup: unlock so teardown can remove it
  git -C "$TEST_REPO" worktree unlock "$wt" 2>/dev/null || true
}

@test "unlocked worktree is pruned after directory removal" {
  local wt="$WTREE_BASE/worker-2"

  # Create worktree WITHOUT lock
  git -C "$TEST_REPO" worktree add "$wt" -b spiral-worker-2 HEAD

  # Remove the directory
  rm -rf "$wt"

  # Prune SHOULD remove the admin record (no lock protecting it)
  git -C "$TEST_REPO" worktree prune

  # The worktree should NOT be listed anymore
  run git -C "$TEST_REPO" worktree list --porcelain
  [[ "$output" != *"spiral-worker-2"* ]]
}

@test "locked worktree can be unlocked then removed" {
  local wt="$WTREE_BASE/worker-3"

  git -C "$TEST_REPO" worktree add --lock --reason "spiral-worker-3" "$wt" -b spiral-worker-3 HEAD

  # Unlock then remove (same pattern as cleanup in run_parallel_ralph.sh)
  git -C "$TEST_REPO" worktree unlock "$wt"
  run git -C "$TEST_REPO" worktree remove "$wt" --force
  [ "$status" -eq 0 ]

  # Should no longer be listed
  run git -C "$TEST_REPO" worktree list --porcelain
  [[ "$output" != *"spiral-worker-3"* ]]
}

@test "detached HEAD worktree with --lock survives prune" {
  local wt="$WTREE_BASE/worker-4"

  # Detached HEAD path (fallback in run_parallel_ralph.sh)
  git -C "$TEST_REPO" worktree add --detach --lock --reason "spiral-worker-4" "$wt" HEAD

  # Remove directory to simulate crash
  rm -rf "$wt"

  # Prune should preserve the locked admin record
  git -C "$TEST_REPO" worktree prune

  # Match on worker directory name (paths may differ between MSYS and Windows-native git)
  run git -C "$TEST_REPO" worktree list --porcelain
  [[ "$output" == *"worker-4"* ]]

  # Cleanup
  git -C "$TEST_REPO" worktree unlock "$wt" 2>/dev/null || true
}
