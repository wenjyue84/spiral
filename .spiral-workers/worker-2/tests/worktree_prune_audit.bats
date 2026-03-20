#!/usr/bin/env bats
# tests/worktree_prune_audit.bats — Tests for US-370: Worktree prune audit at startup
#
# Run with: bats tests/worktree_prune_audit.bats
#
# Tests verify:
#   - Startup dry-run detects stale worktree entries and writes audit log
#   - SPIRAL-owned stale entries (.spiral-workers/) are auto-pruned
#   - Non-SPIRAL stale entries trigger a warning (no auto-prune)
#   - Post-worker mini-audit logs worktree state via --porcelain

bats_require_minimum_version 1.7.0

# ── Setup / Teardown ─────────────────────────────────────────────────────────

setup() {
  TEST_REPO="$(mktemp -d)"
  cd "$TEST_REPO"
  git init -q
  git commit --allow-empty -m "init" -q
  SCRATCH_DIR="$TEST_REPO/.spiral"
  mkdir -p "$SCRATCH_DIR"
  WTREE_BASE="$TEST_REPO/.spiral-workers"
  mkdir -p "$WTREE_BASE"
}

teardown() {
  cd /
  # Unlock and remove any remaining worktrees
  for wt in "$WTREE_BASE"/worker-* "$TEST_REPO"/external-wt-*; do
    [[ -d "$wt" ]] || continue
    git -C "$TEST_REPO" worktree unlock "$wt" 2>/dev/null || true
    git -C "$TEST_REPO" worktree remove "$wt" --force 2>/dev/null || true
  done
  git -C "$TEST_REPO" worktree prune 2>/dev/null || true
  rm -rf "$TEST_REPO" 2>/dev/null || true
}

# ── Helper: simulate the startup audit logic from spiral.sh ──────────────────

_run_startup_audit() {
  local repo_root="$1"
  local scratch_dir="$2"

  local _WT_AUDIT_LOG="$scratch_dir/worktree_audit.log"
  local _WT_PRUNE_DRY
  _WT_PRUNE_DRY=$(git -C "$repo_root" worktree prune --dry-run --verbose 2>&1 || true)
  printf '%s\n' "$_WT_PRUNE_DRY" >"$_WT_AUDIT_LOG" 2>/dev/null || true

  local _WT_AUTO_PRUNED=0
  local _WT_EXTERNAL_WARN=0

  if [[ -n "$_WT_PRUNE_DRY" ]]; then
    while IFS= read -r _wt_line; do
      [[ -z "$_wt_line" ]] && continue
      # Extract admin record name: "Removing worktrees/<name>: ..." → <name>
      local _wt_admin_name=""
      if [[ "$_wt_line" =~ Removing\ worktrees/([^:]+): ]]; then
        _wt_admin_name="${BASH_REMATCH[1]}"
      fi
      if [[ -n "$_wt_admin_name" ]]; then
        # Resolve actual worktree path from .git/worktrees/<name>/gitdir
        local _wt_gitdir_file="$repo_root/.git/worktrees/$_wt_admin_name/gitdir"
        local _wt_actual_path=""
        [[ -f "$_wt_gitdir_file" ]] && _wt_actual_path=$(cat "$_wt_gitdir_file" 2>/dev/null || true)
        if echo "$_wt_actual_path" | grep -qF ".spiral-workers/"; then
          _WT_AUTO_PRUNED=$((_WT_AUTO_PRUNED + 1))
        else
          _WT_EXTERNAL_WARN=$((_WT_EXTERNAL_WARN + 1))
        fi
      else
        _WT_EXTERNAL_WARN=$((_WT_EXTERNAL_WARN + 1))
      fi
    done <<<"$_WT_PRUNE_DRY"

    if [[ "$_WT_AUTO_PRUNED" -gt 0 ]]; then
      git -C "$repo_root" worktree prune 2>/dev/null || true
      echo "AUTO_PRUNED=$_WT_AUTO_PRUNED"
    fi

    if [[ "$_WT_EXTERNAL_WARN" -gt 0 ]]; then
      echo "EXTERNAL_WARN=$_WT_EXTERNAL_WARN"
    fi
  fi

  echo "DRY_RUN_OUTPUT=$_WT_PRUNE_DRY"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "startup audit detects stale SPIRAL worktree and writes audit log" {
  # Create a worktree under .spiral-workers, then remove the directory
  local wt="$WTREE_BASE/worker-1"
  git -C "$TEST_REPO" worktree add "$wt" -b spiral-worker-1 HEAD
  rm -rf "$wt"

  # Run audit
  run _run_startup_audit "$TEST_REPO" "$SCRATCH_DIR"
  [ "$status" -eq 0 ]

  # Audit log file should exist
  [ -f "$SCRATCH_DIR/worktree_audit.log" ]

  # Audit log should contain reference to the stale entry
  run cat "$SCRATCH_DIR/worktree_audit.log"
  [[ "$output" == *"worker-1"* ]]
}

@test "startup audit auto-prunes stale SPIRAL-owned worktree entries" {
  # Create a worktree under .spiral-workers, then remove the directory
  local wt="$WTREE_BASE/worker-2"
  git -C "$TEST_REPO" worktree add "$wt" -b spiral-worker-2 HEAD
  rm -rf "$wt"

  # Confirm it's listed as stale before audit
  run git -C "$TEST_REPO" worktree prune --dry-run --verbose
  [[ "$output" == *"worker-2"* ]]

  # Run audit — should auto-prune
  run _run_startup_audit "$TEST_REPO" "$SCRATCH_DIR"
  [[ "$output" == *"AUTO_PRUNED="* ]]

  # After audit, the stale entry should be pruned
  run git -C "$TEST_REPO" worktree prune --dry-run --verbose
  [[ "$output" != *"worker-2"* ]]
}

@test "startup audit does NOT auto-prune non-SPIRAL worktree entries" {
  # Create a worktree OUTSIDE .spiral-workers/
  local ext_wt="$TEST_REPO/external-wt-1"
  git -C "$TEST_REPO" worktree add "$ext_wt" -b external-branch HEAD
  rm -rf "$ext_wt"

  # Run audit — should warn but NOT prune
  run _run_startup_audit "$TEST_REPO" "$SCRATCH_DIR"
  [[ "$output" == *"EXTERNAL_WARN="* ]]

  # Entry should still be stale (not pruned)
  run git -C "$TEST_REPO" worktree prune --dry-run --verbose
  [[ "$output" == *"external-wt-1"* ]]
}

@test "startup audit with no stale entries produces empty audit log" {
  # No worktrees created — nothing stale
  run _run_startup_audit "$TEST_REPO" "$SCRATCH_DIR"
  [ "$status" -eq 0 ]

  # Audit log should exist but be empty or just whitespace
  [ -f "$SCRATCH_DIR/worktree_audit.log" ]
  local content
  content=$(cat "$SCRATCH_DIR/worktree_audit.log" | tr -d '[:space:]')
  [ -z "$content" ]
}

@test "post-worker audit captures worktree list via --porcelain" {
  # Create a worktree (simulating an active worker)
  local wt="$WTREE_BASE/worker-5"
  git -C "$TEST_REPO" worktree add "$wt" -b spiral-worker-5 HEAD

  # Simulate post-worker audit (same logic as run_parallel_ralph.sh)
  local _WT_POST_AUDIT
  _WT_POST_AUDIT=$(git -C "$TEST_REPO" worktree list --porcelain 2>/dev/null || true)
  local _WT_POST_AUDIT_FILE="$SCRATCH_DIR/worktree_post_worker_5.log"
  printf '%s\n' "$_WT_POST_AUDIT" >"$_WT_POST_AUDIT_FILE" 2>/dev/null || true

  # Post-audit log should exist and contain worktree entries
  [ -f "$_WT_POST_AUDIT_FILE" ]
  run cat "$_WT_POST_AUDIT_FILE"
  [[ "$output" == *"worktree "* ]]

  # Should list the main worktree + the worker worktree
  local count
  count=$(grep -c '^worktree ' "$_WT_POST_AUDIT_FILE" || echo 0)
  [ "$count" -ge 2 ]
}
