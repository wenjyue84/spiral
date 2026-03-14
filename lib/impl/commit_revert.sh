#!/usr/bin/env bash
# lib/impl/commit_revert.sh — Phase I sub-stage: COMMIT OR REVERT
#
# Applied after each ralph worker invocation to either land or discard changes.
#
# On SUCCESS (story marked passes: true by ralph):
#   1. Merge worker's git worktree branch into main (or current) branch
#   2. Verify merge produced no conflicts (abort + revert if it does)
#   3. Run lib/spiral_assert.sh to confirm quality gates still pass
#   4. Commit with standardised message: "feat: {story_id} - {title}"
#
# On FAILURE (story still passes: false after ralph exits):
#   1. Discard all uncommitted changes in the worktree (git checkout .)
#   2. Drop the worktree branch — do NOT merge into main
#   3. Log failure reason to progress.txt
#   4. Hand control back to retry.sh for counter increment
#
# Parallel workers use git worktrees, so revert = drop the worktree branch.
# Sequential (single worker) mode: revert = git reset --hard HEAD.
#
# Inputs:
#   story_id        — story just attempted
#   worker_branch   — git branch created by the worker (parallel mode)
#   passes          — "true" or "false" (from prd.json after ralph exits)
#
# Outputs:
#   Merged commit on main (success) OR clean state with no new commits (failure)
#
# Used by: phase_i_implement.sh after each worker completes

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# commit_or_revert <story_id> <worker_branch> <passes>
commit_or_revert() {
  local story_id="$1"
  local worker_branch="$2"
  local passes="$3"

  if [[ "$passes" == "true" ]]; then
    echo "[Phase I / commit] $story_id passed — merging $worker_branch"
    # TODO: implement merge + quality gate assertion
  else
    echo "[Phase I / revert] $story_id failed — discarding $worker_branch"
    # TODO: implement branch drop + git reset
  fi
}
