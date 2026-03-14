#!/usr/bin/env bash
# lib/phases/phase_i_implement.sh — Phase I: IMPLEMENT (orchestrator)
#
# Orchestrates the implementation sub-pipeline for each story batch.
# Sources and calls the three sub-stage modules in order.
#
# Sub-stages (lib/impl/):
#   decompose.sh      — split oversized stories before attempting them
#   retry.sh          — manage per-story attempt counter (max 3, then skip)
#   commit_revert.sh  — commit on success, revert + log on failure
#
# High-level flow:
#   1. Route stories → assign model (haiku/sonnet/opus) per story complexity
#   2. DAG cycle check → abort if story dependency graph has cycles
#   3. Memory check → reduce worker count if RAM is low
#   4. For each batch:
#        a. decompose.sh  — pre-split large stories
#        b. spawn ralph workers (sequential or parallel via git worktrees)
#        c. retry.sh      — on story failure, increment counter; skip at 3
#        d. commit_revert.sh — apply or roll back worker output
#
# Inputs:
#   $PRD_FILE, $RALPH_WORKERS, $RALPH_MAX_ITERS, $SPIRAL_STORY_BATCH_SIZE
#
# Outputs:
#   $PRD_FILE (stories marked passes: true on success)
#   progress.txt (learning log appended by each ralph invocation)
#
# Config vars:
#   SPIRAL_IMPL_TIMEOUT      — seconds per ralph call (default: 600)
#   RALPH_WORKERS            — parallel worker count (default: 1)
#   SPIRAL_LOW_POWER_MODE    — auto-reduce workers under memory pressure
#   SPIRAL_STORY_BATCH_SIZE  — max stories per batch (0 = all)
#
# TODO: extract Phase I block from spiral.sh (lines 1976–2331) into this file.
#       Sub-stage modules in lib/impl/ are already stubbed.

source "$(dirname "${BASH_SOURCE[0]}")/../impl/decompose.sh"
source "$(dirname "${BASH_SOURCE[0]}")/../impl/retry.sh"
source "$(dirname "${BASH_SOURCE[0]}")/../impl/commit_revert.sh"

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_implement() {
  local iter="$1"
  echo "[Phase I] IMPLEMENT — iteration $iter"
  # TODO: implement (migrated from spiral.sh lines 1976–2331)
  :
}
