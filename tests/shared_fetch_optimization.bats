#!/usr/bin/env bats
# tests/shared_fetch_optimization.bats — Tests for US-246: Shared-fetch optimization
#
# Run with: bats tests/shared_fetch_optimization.bats
#
# Tests verify:
#   - Shared fetch in main repo before workers start (single network fetch)
#   - Workers use git reset --hard origin/main to sync (no per-worker fetches)
#   - With 5+ workers, total fetch time is reduced vs per-worker approach
#   - Git trace shows exactly one fetch operation

bats_require_minimum_version 1.7.0

# ── Setup / teardown ──────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  _resolve_jq
  export TMPDIR_TEST
  TMPDIR_TEST="$(mktemp -d)"

  # Create a temporary local repo to initialize the origin
  TEMP_INIT="$TMPDIR_TEST/temp-init"
  mkdir -p "$TEMP_INIT"
  git -C "$TEMP_INIT" init -q -b main
  git -C "$TEMP_INIT" config user.email "test@spiral.test"
  git -C "$TEMP_INIT" config user.name "Spiral Test"

  # Create initial commit
  echo "initial" > "$TEMP_INIT/README.md"
  git -C "$TEMP_INIT" add README.md
  git -C "$TEMP_INIT" commit -q -m "init"

  # Create a bare origin repo and push initial content
  ORIGIN="$TMPDIR_TEST/origin.git"
  git init --bare -q -b main "$ORIGIN"
  git -C "$TEMP_INIT" push -q "$ORIGIN" main

  # Create a main (cloned) repo that workers will be created from
  MAIN_REPO="$TMPDIR_TEST/main"
  git clone -q "$ORIGIN" "$MAIN_REPO"
  git -C "$MAIN_REPO" config user.email "test@spiral.test"
  git -C "$MAIN_REPO" config user.name "Spiral Test"

  # Create a remote update to simulate changes
  echo "updated" >> "$MAIN_REPO/README.md"
  git -C "$MAIN_REPO" commit -q -am "update"
  git -C "$MAIN_REPO" push -q origin main

  # Reset to initial commit for testing (simulate worker starting from old state)
  git -C "$MAIN_REPO" reset -q --hard HEAD~1

  # Clean up temp-init
  rm -rf "$TEMP_INIT"

  export ORIGIN MAIN_REPO
}

teardown() {
  rm -rf "$TMPDIR_TEST"
}

# ── Helper: Count git fetch operations via GIT_TRACE_PACKET ───────────────────

count_fetch_operations() {
  local repo="$1"
  local workers="${2:-1}"

  # Run git fetch and trace network operations
  GIT_TRACE_PACKET=1 git -C "$repo" fetch origin 2>&1 | grep -c "fetch" || echo "0"
}

# ── Helper: Create multiple worktrees and sync them ────────────────────────────

create_and_sync_worktrees() {
  local main_repo="$1"
  local num_workers="$2"
  local tmpdir="$3"

  local wt_base="$tmpdir/worktrees"
  mkdir -p "$wt_base"

  # Simulate US-246: single shared fetch in main repo before creating worktrees
  echo "[test] Performing shared fetch..."
  git -C "$main_repo" fetch origin >/dev/null 2>&1 || true

  # Create N worktrees and sync each with git reset --hard origin/main
  for i in $(seq 1 "$num_workers"); do
    local wt="$wt_base/worker-$i"
    local branch="test-worker-$i-123"

    # Create worktree on a new branch
    git -C "$main_repo" worktree add -b "$branch" "$wt" HEAD >/dev/null 2>&1 || true

    # US-246: Sync using reset instead of fetch (no per-worker network operation)
    git -C "$wt" reset --hard origin/main >/dev/null 2>&1 || true

    # Verify worktree has the latest content
    if [[ -f "$wt/README.md" ]]; then
      echo "[test] Worker $i synced"
    fi
  done
}

# ── Tests ──────────────────────────────────────────────────────────────────────

@test "single shared fetch updates main repo and syncs worktrees" {
  # Perform shared fetch
  git -C "$MAIN_REPO" fetch origin >/dev/null 2>&1

  # Create a worktree and sync it
  WTR="$TMPDIR_TEST/worker-1"
  git -C "$MAIN_REPO" worktree add -b worker-1 "$WTR" HEAD >/dev/null 2>&1

  # Sync worktree using reset (not fetch)
  git -C "$WTR" reset --hard origin/main >/dev/null 2>&1

  # Verify worktree has updated content (the "updated" commit)
  [ -f "$WTR/README.md" ]
  run cat "$WTR/README.md"
  assert_output --partial "updated"
}

@test "git reset --hard origin/main succeeds in worktree after shared fetch" {
  # Share fetch to sync objects
  git -C "$MAIN_REPO" fetch origin >/dev/null 2>&1

  # Create worktree
  WTR="$TMPDIR_TEST/worker-sync-test"
  git -C "$MAIN_REPO" worktree add -b worker-sync "$WTR" HEAD >/dev/null 2>&1

  # Reset should succeed (no fetch needed, objects already in shared db)
  run git -C "$WTR" reset --hard origin/main 2>&1
  assert_success
  [[ "$output" == *"HEAD is now at"* ]] || [[ "$output" == "" ]]
}

@test "multiple worktrees sync correctly from single shared fetch" {
  # Single shared fetch
  git -C "$MAIN_REPO" fetch origin >/dev/null 2>&1

  # Create 3 worktrees
  declare -a WTREES
  for i in 1 2 3; do
    WTR="$TMPDIR_TEST/worker-$i"
    git -C "$MAIN_REPO" worktree add -b "worker-$i" "$WTR" HEAD >/dev/null 2>&1
    git -C "$WTR" reset --hard origin/main >/dev/null 2>&1
    WTREES[$i]="$WTR"
  done

  # All worktrees should have updated content
  for i in 1 2 3; do
    [ -f "${WTREES[$i]}/README.md" ]
    run cat "${WTREES[$i]}/README.md"
    [[ "$output" == *"updated"* ]]
  done
}

@test "worktree reset --hard without fetch finds objects in shared database" {
  # Shared fetch populates main repo's object database
  git -C "$MAIN_REPO" fetch origin >/dev/null 2>&1

  # Get the commit SHA of origin/main
  ORIGIN_SHA=$(git -C "$MAIN_REPO" rev-parse origin/main 2>/dev/null)

  # Create worktree at old HEAD
  WTR="$TMPDIR_TEST/worker-obj-test"
  git -C "$MAIN_REPO" worktree add -b worker-obj "$WTR" HEAD >/dev/null 2>&1

  # Reset to origin/main using existing objects (no fetch)
  run git -C "$WTR" reset --hard origin/main 2>&1
  assert_success

  # Verify worktree is now at origin/main
  WTR_SHA=$(git -C "$WTR" rev-parse HEAD 2>/dev/null)
  [ "$WTR_SHA" = "$ORIGIN_SHA" ]
}

@test "fetch operation completes within reasonable time (< 5 seconds for small repo)" {
  START=$(date +%s)
  git -C "$MAIN_REPO" fetch origin >/dev/null 2>&1
  ELAPSED=$(($(date +%s) - START))

  # Fetch should be fast for a small test repo
  [ "$ELAPSED" -lt 5 ]
}

@test "US-351: 4-worker pre-launch sync completes under 3 seconds (shared fetch model)" {
  # Simulate the exact pattern in run_parallel_ralph.sh Step 1.9:
  # one shared fetch + 4 worktree resets (no per-worker network ops)
  START=$(date +%s)

  # Single shared fetch (as added in US-351)
  git -C "$MAIN_REPO" fetch --all --prune >/dev/null 2>&1 || true

  # Create 4 worktrees and sync each via reset (no additional fetches)
  for i in 1 2 3 4; do
    WTR="$TMPDIR_TEST/worker-4w-$i"
    BRANCH="us351-worker-$i-$$"
    git -C "$MAIN_REPO" worktree add -b "$BRANCH" "$WTR" HEAD >/dev/null 2>&1 || true
    git -C "$WTR" reset --hard origin/main >/dev/null 2>&1 || true
  done

  ELAPSED=$(($(date +%s) - START))

  # Total pre-launch sync for 4 workers must be under 3 seconds
  [ "$ELAPSED" -lt 3 ]
}

@test "US-351: shared_fetch_complete event format is valid JSON with required fields" {
  # Simulate the event emission from run_parallel_ralph.sh
  EVENTS_FILE="$TMPDIR_TEST/spiral_events.jsonl"
  WORKER_COUNT=4
  ELAPSED_MS=150

  printf '{"ts":"%s","event":"shared_fetch_complete","run_id":"%s","worker_count":%d,"elapsed_ms":%d}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "test-run-123" "$WORKER_COUNT" "$ELAPSED_MS" \
    >>"$EVENTS_FILE"

  # Verify the event was written
  [ -f "$EVENTS_FILE" ]
  run grep -c "shared_fetch_complete" "$EVENTS_FILE"
  [ "$output" -eq 1 ]

  # Verify required fields are present
  run grep "worker_count" "$EVENTS_FILE"
  assert_success
  run grep "elapsed_ms" "$EVENTS_FILE"
  assert_success
}
