#!/usr/bin/env bash
# lib/impl/commit_revert.sh — Phase I sub-stage: COMMIT OR REVERT
#
# Applied after each ralph worker invocation to either land or discard changes.
#
# TRANSACTIONAL SNAPSHOTS (US-343):
#   Before Ralph executes:
#     1. Create a git stash of all staged/unstaged changes
#     2. Record a manifest of non-git-tracked files in the project root and /tmp
#   After Ralph completes:
#     - On SUCCESS: Commit changes (stash is preserved but not applied)
#     - On FAILURE: Restore the stash + delete newly-created non-git files
#     - Log rollback outcome (success_rate, timing) to spiral_events.jsonl
#
# On SUCCESS (story marked passes: true by ralph):
#   1. Merge worker's git worktree branch into main (or current) branch
#   2. Verify merge produced no conflicts (abort + revert if it does)
#   3. Run lib/spiral_assert.sh to confirm quality gates still pass
#   4. Commit with standardised message: "feat: {story_id} - {title}"
#
# On FAILURE (story still passes: false after ralph exits):
#   1. Restore transactional snapshot (apply stash + delete new non-git files)
#   2. Discard all uncommitted changes in the worktree (git checkout .)
#   3. Drop the worktree branch — do NOT merge into main
#   4. Log failure reason to progress.txt
#   5. Hand control back to retry.sh for counter increment
#
# Parallel workers use git worktrees, so revert = drop the worktree branch.
# Sequential (single worker) mode: revert = git reset --hard HEAD.
#
# Inputs:
#   story_id        — story just attempted
#   worker_branch   — git branch created by the worker (parallel mode)
#   passes          — "true" or "false" (from prd.json after ralph exits)
#   SNAPSHOT_*      — env vars set by create_snapshot() before ralph runs
#
# Outputs:
#   Merged commit on main (success) OR clean state with no new commits (failure)
#
# Used by: phase_i_implement.sh after each worker completes

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# ── SNAPSHOT & RESTORE (US-343) ──────────────────────────────────────────────

# create_snapshot <snapshot_dir> <repo_root>
# Records git stash and non-git file manifest before Ralph execution.
# Returns: 0 on success, non-zero on error
# Exports: SNAPSHOT_STASH_SHA (git stash ref), SNAPSHOT_MANIFEST (file path)
create_snapshot() {
  local snapshot_dir="$1"
  local repo_root="$2"
  mkdir -p "$snapshot_dir" 2>/dev/null || return 1

  # Step 1: Create git stash of uncommitted changes
  local stash_output
  stash_output=$(cd "$repo_root" && git stash create 2>&1)
  SNAPSHOT_STASH_SHA="$stash_output"
  if [[ -z "$SNAPSHOT_STASH_SHA" ]]; then
    # No changes to stash; use a sentinel value
    SNAPSHOT_STASH_SHA="NONE"
  fi
  export SNAPSHOT_STASH_SHA

  # Step 2: Record manifest of non-git-tracked files
  SNAPSHOT_MANIFEST="$snapshot_dir/manifest-$$.txt"
  {
    # Files in project root (excluding .git and common ignore patterns)
    cd "$repo_root" && git ls-files --others --exclude-standard 2>/dev/null | sort || true
    # Files in /tmp matching SPIRAL patterns
    if [[ -d /tmp ]]; then
      find /tmp -maxdepth 2 \( -name "*spiral*" -o -name "*ralph*" -o -name "*worker*" \) 2>/dev/null | sort || true
    fi
  } >"$SNAPSHOT_MANIFEST"
  export SNAPSHOT_MANIFEST

  return 0
}

# restore_snapshot <snapshot_dir> <repo_root>
# Restores git stash and deletes non-git files created after snapshot.
# Returns: 0 on full success, 1 if stash restore failed, 2 if file cleanup failed
restore_snapshot() {
  local snapshot_dir="$1"
  local repo_root="$2"
  local _restore_status=0

  # Step 1: Restore git stash (if one was created)
  # Note: We use --index to restore both staged and unstaged changes, but fall back to plain apply on failure
  if [[ -n "$SNAPSHOT_STASH_SHA" && "$SNAPSHOT_STASH_SHA" != "NONE" ]]; then
    cd "$repo_root" || return 1
    if ! git stash apply --index "$SNAPSHOT_STASH_SHA" 2>&1; then
      # Fallback: try without --index flag (on older git or Windows)
      if ! git stash apply "$SNAPSHOT_STASH_SHA" 2>&1; then
        _restore_status=1
        echo "[ERROR] Failed to restore git stash $SNAPSHOT_STASH_SHA" >&2
      fi
    fi
  fi

  # Step 2: Delete non-git files that were created after snapshot
  if [[ -f "$SNAPSHOT_MANIFEST" ]]; then
    local _old_files
    _old_files=$(cat "$SNAPSHOT_MANIFEST" | sort)

    # Get current non-git files
    local _current_files
    _current_files=$(cd "$repo_root" && {
      git ls-files --others --exclude-standard 2>/dev/null | sort || true
    })

    # Files to delete = current - old (new files)
    local _to_delete
    _to_delete=$(comm -13 <(echo "$_old_files") <(echo "$_current_files") 2>/dev/null)

    if [[ -n "$_to_delete" ]]; then
      while IFS= read -r _file; do
        if [[ -n "$_file" ]]; then
          rm -rf "$repo_root/$_file" 2>/dev/null || {
            _restore_status=2
            echo "[WARNING] Failed to delete $repo_root/$_file" >&2
          }
        fi
      done <<<"$_to_delete"
    fi

    rm -f "$SNAPSHOT_MANIFEST" 2>/dev/null || true
  fi

  return $_restore_status
}

# log_rollback_event <story_id> <status> <elapsed_ms> [details]
# Logs a rollback event to spiral_events.jsonl
log_rollback_event() {
  local story_id="$1"
  local status="$2" # 'success', 'stash_restore_failed', 'file_cleanup_failed'
  local elapsed_ms="$3"
  local details="${4:-}"

  local _ts _ev_file _ev_json _py
  _ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  _ev_file="${SPIRAL_SCRATCH_DIR:-./}/spiral_events.jsonl"
  # shellcheck disable=SC2059
  _ev_json="$(printf '{"ts":"%s","event":"rollback_%s","story_id":"%s","run_id":"%s","elapsed_ms":%d%s}' \
    "$_ts" "$status" "$story_id" "${SPIRAL_RUN_ID:-}" "$elapsed_ms" \
    "${details:+,\"details\":\"$details\"}")"
  _py="${SPIRAL_PYTHON:-${PYTHON:-uv run python}}"
  _spiral_io="${SPIRAL_HOME:-${SPIRAL_ROOT:-.}}/lib/core/spiral_io.py"
  if [[ -f "$_spiral_io" ]]; then
    $_py "$_spiral_io" --append "$_ev_file" "$_ev_json" 2>/dev/null ||
      printf '%s\n' "$_ev_json" >>"$_ev_file" 2>/dev/null || true
  else
    printf '%s\n' "$_ev_json" >>"$_ev_file" 2>/dev/null || true
  fi
}

# ── DETACHED HEAD RECOVERY (US-461) ──────────────────────────────────────────

# recover_detached_worktree <worktree_path>
# Detects if a worktree is in detached HEAD state and resets it to main.
# Used to recover from worker crashes that leave the worktree in a bad state.
# Returns: 0 on success, 1 if already on a branch, 2 if reset fails
recover_detached_worktree() {
  local worktree_path="$1"

  if [[ ! -d "$worktree_path" ]]; then
    echo "[ERROR] Worktree does not exist: $worktree_path" >&2
    return 2
  fi

  # Check if HEAD is detached
  local _current_branch
  _current_branch=$(git -C "$worktree_path" rev-parse --abbrev-ref HEAD 2>/dev/null) || true

  if [[ "$_current_branch" == "HEAD" ]]; then
    # HEAD is detached — perform recovery
    echo "[recovery] Worktree $worktree_path is in detached HEAD state — recovering to main"

    # Reset worktree to main with staged and unstaged changes discarded
    git -C "$worktree_path" reset HEAD 2>/dev/null || true
    git -C "$worktree_path" checkout -- . 2>/dev/null || true
    git -C "$worktree_path" clean -fd 2>/dev/null || true

    # Attempt to checkout main branch
    if ! git -C "$worktree_path" checkout main 2>/dev/null; then
      if ! git -C "$worktree_path" checkout -b main origin/main 2>/dev/null; then
        echo "[ERROR] Failed to checkout main branch in $worktree_path" >&2
        return 2
      fi
    fi

    # Verify we're back on main
    _current_branch=$(git -C "$worktree_path" rev-parse --abbrev-ref HEAD 2>/dev/null) || true
    if [[ "$_current_branch" == "main" ]]; then
      echo "[recovery] Successfully recovered worktree to main branch"
      return 0
    else
      echo "[ERROR] Recovery failed — worktree still on $(_current_branch)" >&2
      return 2
    fi
  else
    # Already on a branch — no recovery needed
    return 1
  fi
}

# ── WORKTREE HEALTH CHECK (US-1107) ────────────────────────────────────────
#
# Pre-launch health check verifies each worktree is in a valid state before
# spawning ralph. Performs three checks and auto-repairs if any fail.
#
# worktree_health_check <worktree_path> <expected_branch>
# Verifies:
#   (1) HEAD is not detached
#   (2) Current branch matches expected worker branch
#   (3) No uncommitted changes
# Auto-repair: git checkout -B <expected_branch> main && git clean -fd
# Returns: 0 if healthy or repaired, 1 if unrecoverable
worktree_health_check() {
  local worktree_path="$1"
  local expected_branch="$2"

  if [[ ! -d "$worktree_path" ]]; then
    echo "[health-check] ERROR: Worktree does not exist: $worktree_path" >&2
    return 1
  fi

  local _current_branch
  _current_branch=$(git -C "$worktree_path" rev-parse --abbrev-ref HEAD 2>/dev/null) || true

  # Check (1): Detached HEAD?
  if [[ "$_current_branch" == "HEAD" ]]; then
    echo "[health-check] Worktree in detached HEAD state — auto-repairing"
    if ! git -C "$worktree_path" checkout -B "$expected_branch" main 2>/dev/null; then
      echo "[health-check] ERROR: Failed to repair detached HEAD" >&2
      return 1
    fi
    _current_branch="$expected_branch"
  fi

  # Check (2): Branch mismatch?
  if [[ "$_current_branch" != "$expected_branch" ]]; then
    echo "[health-check] Worktree on wrong branch ($(_current_branch) != $expected_branch) — auto-repairing"
    if ! git -C "$worktree_path" checkout -B "$expected_branch" main 2>/dev/null; then
      echo "[health-check] ERROR: Failed to checkout expected branch $expected_branch" >&2
      return 1
    fi
  fi

  # Check (3): Uncommitted changes?
  local _has_changes
  _has_changes=$(git -C "$worktree_path" status --porcelain 2>/dev/null | wc -l)
  if [[ "$_has_changes" -gt 0 ]]; then
    echo "[health-check] Worktree has uncommitted changes — auto-cleaning"
    git -C "$worktree_path" reset HEAD 2>/dev/null || true
    git -C "$worktree_path" checkout -- . 2>/dev/null || true
    git -C "$worktree_path" clean -fd 2>/dev/null || true
  fi

  # Final verification
  _current_branch=$(git -C "$worktree_path" rev-parse --abbrev-ref HEAD 2>/dev/null) || true
  if [[ "$_current_branch" != "$expected_branch" ]]; then
    echo "[health-check] ERROR: Verification failed — worktree not on $expected_branch" >&2
    return 1
  fi

  echo "[health-check] Worktree is healthy"
  return 0
}

# ── COMMIT OR REVERT ─────────────────────────────────────────────────────────

# commit_or_revert <story_id> <worker_branch> <passes>
commit_or_revert() {
  local story_id="$1"
  local worker_branch="$2"
  local passes="$3"

  if [[ "$passes" == "true" ]]; then
    echo "[Phase I / commit] $story_id passed — merging $worker_branch"

    # ── US-1088: Journal the prd.json write before merge ─────────────────────
    _TXN_JOURNAL="${SCRATCH_DIR:-${SPIRAL_ROOT:-.}/.spiral}/_prd_journal.jsonl"
    _PRD="${PRD_FILE:-prd.json}"
    _BAK="${_PRD}.bak"
    cp "$_PRD" "$_BAK" 2>/dev/null || true
    "${SPIRAL_PYTHON:-uv run python}" "${SPIRAL_HOME:-$SPIRAL_ROOT}/lib/resilience/txn_journal.py" \
      write-entry --journal "$_TXN_JOURNAL" --story-id "$story_id" \
      --operation update --prd "$_PRD" --backup "$_BAK" 2>/dev/null || true

    # TODO: implement merge + quality gate assertion

    # ── Protected-path audit (second defense after PreToolUse hook) ──
    # Catches modifications even if the hook was bypassed via Bash tool.
    local _PROTECTED_RE="^(spiral\.sh|spiral\.config\.sh|constitution\.md|pyproject\.toml|\.pre-commit-config\.yaml|lib/|ralph/|\.claude/hooks/|\.github/|\.specify/|tests/core/)"
    local _touched_protected
    _touched_protected=$(git diff --name-only HEAD 2>/dev/null | grep -E "$_PROTECTED_RE" || true)
    if [[ -n "$_touched_protected" ]]; then
      echo "[Phase I / BLOCKED] $story_id touched protected core files — auto-reverting:"
      echo "$_touched_protected" | sed 's/^/  - /'
      git checkout -- . 2>/dev/null || true
      passes="false"
    fi

    # ── Episodic memory write (non-fatal) ────────────────────────────
    if [[ "${SPIRAL_EPISODIC_MEMORY:-false}" == "true" ]]; then
      _approach="$(grep -A 15 "Story:.*${story_id}" "${SPIRAL_ROOT:-./}/progress.txt" 2>/dev/null | tail -15 | tr '\n' ' ' | cut -c1-300)"
      uv run python lib/resilience/episodic_memory.py write \
        "${SPIRAL_EPISODIC_DB:-.spiral/episodic_memory.db}" \
        "$story_id" "unknown" "${_approach:-no summary}" "pass" "${SPIRAL_ITERATION:-0}" \
        2>/dev/null || true
    fi
  else
    echo "[Phase I / revert] $story_id failed — discarding $worker_branch"
    # TODO: implement branch drop + git reset
  fi
}
