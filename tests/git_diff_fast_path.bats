#!/usr/bin/env bats
# tests/git_diff_fast_path.bats — Tests for US-247: git diff-index fast-path
#
# Run with: bats tests/git_diff_fast_path.bats
#
# Tests verify:
#   - Clean worktrees skip full git status (fast path taken)
#   - Dirty worktrees fall through to full git status
#   - Skip count is logged: "Skipped full status on N/M worktrees (clean)"
#   - Mixed scenario: some clean, some dirty — correct split

# ── Helpers ───────────────────────────────────────────────────────────────────

# Run the US-247 fast-path worktree status block in a subshell.
# Mirrors the block in spiral.sh (US-218 + US-247 merged block).
# Args: REPO_ROOT
run_fast_path_check() {
  bash -c '
    set -euo pipefail

    REPO_ROOT="$1"
    SPIRAL_RUN_ID="test-run-247"
    SPIRAL_SCRATCH_DIR="$REPO_ROOT/.spiral"
    mkdir -p "$SPIRAL_SCRATCH_DIR"

    log_spiral_event() {
      local event_type="$1"
      local extra="$2"
      printf "{\"event\":\"%s\",%s}\n" "$event_type" "$extra" >> "$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"
    }

    # ── US-218 + US-247 block (mirrors spiral.sh) ──
    if [[ -d "$REPO_ROOT/.spiral-workers" ]]; then
      _DIRTY_WORKERS_CLEANED=()
      _DIFFIDX_SKIPPED=0
      _DIFFIDX_TOTAL=0
      for _wt_dir in "$REPO_ROOT/.spiral-workers"/worker-*; do
        [[ -d "$_wt_dir" ]] || continue
        _DIFFIDX_TOTAL=$((_DIFFIDX_TOTAL + 1))
        # Fast pre-check
        if git -C "$_wt_dir" diff-index --quiet HEAD -- 2>/dev/null; then
          _DIFFIDX_SKIPPED=$((_DIFFIDX_SKIPPED + 1))
          echo "[fast-path] SKIPPED full status for $(basename "$_wt_dir") (clean)"
          continue
        fi
        # Fall through to full status
        echo "[fast-path] RUNNING full status for $(basename "$_wt_dir") (dirty)"
        _wt_status=$(git -C "$_wt_dir" status --porcelain 2>/dev/null) || continue
        if [[ -n "$_wt_status" ]]; then
          _wt_name=$(basename "$_wt_dir")
          git -C "$_wt_dir" reset HEAD 2>/dev/null || true
          git -C "$_wt_dir" checkout -- . 2>/dev/null || true
          git -C "$_wt_dir" clean -fd 2>/dev/null || true
          _DIRTY_WORKERS_CLEANED+=("$_wt_name")
        fi
      done
      if [[ "$_DIFFIDX_TOTAL" -gt 0 ]]; then
        echo "[fast-path] Skipped full status on ${_DIFFIDX_SKIPPED}/${_DIFFIDX_TOTAL} worktrees (clean)"
      fi
      if [[ ${#_DIRTY_WORKERS_CLEANED[@]} -gt 0 ]]; then
        _cleaned_list=$(IFS=,; echo "${_DIRTY_WORKERS_CLEANED[*]}")
        echo "[fast-path] Reset ${#_DIRTY_WORKERS_CLEANED[@]} dirty worktree(s): $_cleaned_list"
      fi
    else
      echo "[fast-path] No .spiral-workers directory"
    fi
  ' -- "$1"
}

# Create a minimal git worktree for testing.
# Args: REPO WORKER_NAME
create_worker_worktree() {
  local repo="$1"
  local name="$2"
  local branch="spiral-test-$name"
  local wt_dir="$repo/.spiral-workers/$name"

  git -C "$repo" branch "$branch" 2>/dev/null || true
  git -C "$repo" worktree add "$wt_dir" "$branch" -q 2>/dev/null
}

# ── Setup / teardown ──────────────────────────────────────────────────────────

setup() {
  export TMPDIR_DFP
  TMPDIR_DFP="$(mktemp -d)"

  REPO="$TMPDIR_DFP/repo"
  mkdir -p "$REPO"
  git -C "$REPO" init -q
  git -C "$REPO" config user.email "test@spiral.test"
  git -C "$REPO" config user.name "Spiral Test"

  echo "initial" > "$REPO/README.md"
  git -C "$REPO" add README.md
  git -C "$REPO" commit -q -m "init"

  mkdir -p "$REPO/.spiral-workers"
  export REPO
}

teardown() {
  if [[ -d "$REPO/.spiral-workers" ]]; then
    for wt in "$REPO/.spiral-workers"/worker-*; do
      [[ -d "$wt" ]] && git -C "$REPO" worktree remove "$wt" --force 2>/dev/null || true
    done
  fi
  rm -rf "$TMPDIR_DFP"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "clean worktree: fast path taken, full status skipped" {
  create_worker_worktree "$REPO" "worker-1"

  run run_fast_path_check "$REPO"
  [ "$status" -eq 0 ]
  # Fast path message emitted
  [[ "$output" == *"SKIPPED full status for worker-1 (clean)"* ]]
  # Full status message NOT emitted
  [[ "$output" != *"RUNNING full status for worker-1"* ]]
}

@test "clean worktree: skip count logged correctly" {
  create_worker_worktree "$REPO" "worker-1"

  run run_fast_path_check "$REPO"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Skipped full status on 1/1 worktrees (clean)"* ]]
}

@test "dirty worktree (staged): full status runs, not skipped" {
  create_worker_worktree "$REPO" "worker-1"

  echo "staged change" > "$REPO/.spiral-workers/worker-1/staged.txt"
  git -C "$REPO/.spiral-workers/worker-1" add staged.txt

  run run_fast_path_check "$REPO"
  [ "$status" -eq 0 ]
  # Full status ran for dirty worktree
  [[ "$output" == *"RUNNING full status for worker-1 (dirty)"* ]]
  # Was NOT skipped
  [[ "$output" != *"SKIPPED full status for worker-1"* ]]
  # Reset was applied
  [[ "$output" == *"Reset 1 dirty worktree(s)"* ]]
}

@test "dirty worktree (unstaged modification): fast path detects dirty" {
  create_worker_worktree "$REPO" "worker-1"

  # Commit a file first, then modify it without staging
  echo "original" > "$REPO/.spiral-workers/worker-1/tracked.txt"
  git -C "$REPO/.spiral-workers/worker-1" add tracked.txt
  git -C "$REPO/.spiral-workers/worker-1" commit -q -m "add tracked"

  # Now modify without staging — diff-index should catch this
  echo "modified" > "$REPO/.spiral-workers/worker-1/tracked.txt"

  run run_fast_path_check "$REPO"
  [ "$status" -eq 0 ]
  [[ "$output" == *"RUNNING full status for worker-1 (dirty)"* ]]
}

@test "mixed: 2 clean + 1 dirty — correct skip count and reset" {
  create_worker_worktree "$REPO" "worker-1"
  create_worker_worktree "$REPO" "worker-2"
  create_worker_worktree "$REPO" "worker-3"

  # Make worker-2 dirty (staged change)
  echo "dirty" > "$REPO/.spiral-workers/worker-2/dirty.txt"
  git -C "$REPO/.spiral-workers/worker-2" add dirty.txt

  run run_fast_path_check "$REPO"
  [ "$status" -eq 0 ]
  # 2 of 3 skipped
  [[ "$output" == *"Skipped full status on 2/3 worktrees (clean)"* ]]
  # worker-2 was processed
  [[ "$output" == *"RUNNING full status for worker-2 (dirty)"* ]]
  # worker-1 and worker-3 were skipped
  [[ "$output" == *"SKIPPED full status for worker-1 (clean)"* ]]
  [[ "$output" == *"SKIPPED full status for worker-3 (clean)"* ]]
  # Reset count correct
  [[ "$output" == *"Reset 1 dirty worktree(s)"* ]]
}

@test "all clean: skip count is N/N" {
  create_worker_worktree "$REPO" "worker-1"
  create_worker_worktree "$REPO" "worker-2"

  run run_fast_path_check "$REPO"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Skipped full status on 2/2 worktrees (clean)"* ]]
  [[ "$output" != *"Reset"* ]]
}

@test "no .spiral-workers directory: graceful no-op" {
  rm -rf "$REPO/.spiral-workers"

  run run_fast_path_check "$REPO"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No .spiral-workers directory"* ]]
}
