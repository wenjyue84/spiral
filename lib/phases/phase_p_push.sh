#!/usr/bin/env bash
# Phase P: Push — git push after validation passes (with rebase conflict handling)
#
# Pushes committed changes to origin/main with automatic rebase to handle
# diverged branches. If rebase conflicts occur, logs warning and skips push
# but does NOT abort the SPIRAL loop.
#
# Steps:
#   1. git fetch origin main
#   2. git rebase origin/main (onto current branch)
#   3. If rebase succeeds: git push origin main
#   4. If rebase conflicts: log WARNING and skip push
#   5. Always continue (never abort loop)

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_push() {
  echo ""
  if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
    echo "  [Phase P] PUSH — skipped (--dry-run)"
    return 0
  fi

  echo "  [Phase P] PUSH — fetching from origin and rebasing..."

  # ── Step 1: Fetch origin/main to get latest remote commits ─────────────────
  if ! git -C "$REPO_ROOT" fetch origin main 2>/dev/null; then
    echo "  [P] WARNING: git fetch origin main failed (network issue?)"
    echo "  [P] Skipping push; continuing without aborting loop"
    return 0
  fi

  # ── Step 2: Attempt rebase to integrate origin/main changes ────────────────
  # This handles the case where origin/main has diverged from our local main
  if ! git -C "$REPO_ROOT" rebase origin/main 2>/dev/null; then
    # Rebase failed — likely due to conflicts
    echo "  [P] WARNING: git rebase origin/main failed (conflicts detected)"

    # Abort the rebase to return to clean state
    git -C "$REPO_ROOT" rebase --abort 2>/dev/null || true

    echo "  [P] Rebase aborted; skipping push and continuing (conflicts left in worktree for manual resolution)"
    return 0
  fi

  # ── Step 3: Rebase succeeded — push to origin/main ──────────────────────────
  if git -C "$REPO_ROOT" push origin main 2>/dev/null; then
    echo "  [P] Pushed to origin/main successfully"
    return 0
  else
    # Push failed (non-conflict reasons: network, permissions, etc.)
    echo "  [P] WARNING: git push origin main failed (check network/permissions)"
    echo "  [P] Continuing without aborting loop"
    return 0
  fi
}
