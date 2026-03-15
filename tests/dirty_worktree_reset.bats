#!/usr/bin/env bats
# tests/dirty_worktree_reset.bats — Tests for US-218: Detect and reset dirty worker worktrees
#
# Run with: bats tests/dirty_worktree_reset.bats
#
# Tests verify:
#   - Clean worktrees are left untouched (no reset, no event)
#   - Dirty worktree with staged changes is detected and reset
#   - Dirty worktree with unstaged modifications is detected and reset
#   - Dirty worktree with untracked files is detected and cleaned
#   - worker_reset_dirty_worktree event is emitted to spiral_events.jsonl
#   - Multiple dirty worktrees are all cleaned and reported
#   - Non-existent .spiral-workers directory is handled gracefully

# ── Helpers ───────────────────────────────────────────────────────────────────

# Run the US-218 dirty-worktree detection block from spiral.sh in a subshell.
# Args: REPO_ROOT (must contain .spiral-workers/worker-* dirs)
run_dirty_reset() {
  bash -c '
    set -euo pipefail

    REPO_ROOT="$1"
    SPIRAL_RUN_ID="test-run-218"
    SPIRAL_SCRATCH_DIR="$REPO_ROOT/.spiral"
    mkdir -p "$SPIRAL_SCRATCH_DIR"

    log_spiral_event() {
      local event_type="$1"
      local extra="$2"
      printf "{\"event\":\"%s\",%s}\n" "$event_type" "$extra" >> "$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"
    }

    # ── US-218 block (extracted from spiral.sh lines 1342-1374) ──
    if [[ -d "$REPO_ROOT/.spiral-workers" ]]; then
      _DIRTY_WORKERS_CLEANED=()
      for _wt_dir in "$REPO_ROOT/.spiral-workers"/worker-*; do
        [[ -d "$_wt_dir" ]] || continue
        _wt_status=$(git -C "$_wt_dir" status --porcelain 2>/dev/null) || continue
        if [[ -n "$_wt_status" ]]; then
          _wt_name=$(basename "$_wt_dir")
          echo "[reset] Dirty worktree detected: $_wt_name"
          if [[ -f "$_wt_dir/.git" ]]; then
            _wt_git_dir=$(sed "s/^gitdir: //" "$_wt_dir/.git" 2>/dev/null || true)
            [[ -n "$_wt_git_dir" && -f "$_wt_git_dir/index.lock" ]] && rm -f "$_wt_git_dir/index.lock"
          fi
          git -C "$_wt_dir" reset HEAD 2>/dev/null || true
          git -C "$_wt_dir" checkout -- . 2>/dev/null || true
          git -C "$_wt_dir" clean -fd 2>/dev/null || true
          _DIRTY_WORKERS_CLEANED+=("$_wt_name")
        fi
      done
      if [[ ${#_DIRTY_WORKERS_CLEANED[@]} -gt 0 ]]; then
        _cleaned_list=$(IFS=,; echo "${_DIRTY_WORKERS_CLEANED[*]}")
        echo "[reset] Reset ${#_DIRTY_WORKERS_CLEANED[@]} dirty worktree(s): $_cleaned_list"
        log_spiral_event "worker_reset_dirty_worktree" \
          "\"worktrees\":[$(printf "\"%s\"," "${_DIRTY_WORKERS_CLEANED[@]}" | sed "s/,$//")],\"count\":${#_DIRTY_WORKERS_CLEANED[@]}"
      else
        echo "[reset] All worktrees clean"
      fi
    else
      echo "[reset] No .spiral-workers directory"
    fi
  ' -- "$1"
}

# Create a git worktree at the given path under .spiral-workers.
# Args: REPO_ROOT WORKER_NAME
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
  export TMPDIR_DWR
  TMPDIR_DWR="$(mktemp -d)"

  # Create a minimal git repo
  REPO="$TMPDIR_DWR/repo"
  mkdir -p "$REPO"
  git -C "$REPO" init -q
  git -C "$REPO" config user.email "test@spiral.test"
  git -C "$REPO" config user.name "Spiral Test"

  # Initial commit so the repo has a HEAD
  echo "initial" > "$REPO/README.md"
  git -C "$REPO" add README.md
  git -C "$REPO" commit -q -m "init"

  export REPO
}

teardown() {
  # Remove worktrees before deleting the temp dir
  if [[ -d "$REPO/.spiral-workers" ]]; then
    for wt in "$REPO/.spiral-workers"/worker-*; do
      [[ -d "$wt" ]] && git -C "$REPO" worktree remove "$wt" --force 2>/dev/null || true
    done
  fi
  rm -rf "$TMPDIR_DWR"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "no .spiral-workers directory: graceful no-op" {
  run run_dirty_reset "$REPO"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No .spiral-workers directory"* ]]
}

@test "clean worktree: no reset, reports clean" {
  mkdir -p "$REPO/.spiral-workers"
  create_worker_worktree "$REPO" "worker-1"

  run run_dirty_reset "$REPO"
  [ "$status" -eq 0 ]
  [[ "$output" == *"All worktrees clean"* ]]

  # No event logged
  [ ! -f "$REPO/.spiral/spiral_events.jsonl" ] || \
    ! grep -q "worker_reset_dirty_worktree" "$REPO/.spiral/spiral_events.jsonl"
}

@test "worktree with staged changes: detected and reset" {
  mkdir -p "$REPO/.spiral-workers"
  create_worker_worktree "$REPO" "worker-1"

  # Stage a change in the worktree
  echo "dirty" > "$REPO/.spiral-workers/worker-1/dirty.txt"
  git -C "$REPO/.spiral-workers/worker-1" add dirty.txt

  run run_dirty_reset "$REPO"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Dirty worktree detected: worker-1"* ]]
  [[ "$output" == *"Reset 1 dirty worktree(s)"* ]]

  # Verify worktree is now clean
  wt_status=$(git -C "$REPO/.spiral-workers/worker-1" status --porcelain 2>/dev/null)
  [ -z "$wt_status" ]
}

@test "worktree with unstaged modifications: detected and reset" {
  mkdir -p "$REPO/.spiral-workers"
  create_worker_worktree "$REPO" "worker-1"

  # Modify a tracked file without staging
  echo "modified" >> "$REPO/.spiral-workers/worker-1/README.md"

  run run_dirty_reset "$REPO"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Dirty worktree detected: worker-1"* ]]

  # Verify worktree is now clean
  wt_status=$(git -C "$REPO/.spiral-workers/worker-1" status --porcelain 2>/dev/null)
  [ -z "$wt_status" ]
}

@test "worktree with untracked files: detected and cleaned" {
  mkdir -p "$REPO/.spiral-workers"
  create_worker_worktree "$REPO" "worker-1"

  # Add an untracked file
  echo "untracked" > "$REPO/.spiral-workers/worker-1/leftover.txt"

  run run_dirty_reset "$REPO"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Dirty worktree detected: worker-1"* ]]

  # Verify untracked file was removed
  [ ! -f "$REPO/.spiral-workers/worker-1/leftover.txt" ]
}

@test "worker_reset_dirty_worktree event emitted to spiral_events.jsonl" {
  mkdir -p "$REPO/.spiral-workers"
  create_worker_worktree "$REPO" "worker-1"

  echo "dirty" > "$REPO/.spiral-workers/worker-1/dirty.txt"
  git -C "$REPO/.spiral-workers/worker-1" add dirty.txt

  run run_dirty_reset "$REPO"
  [ "$status" -eq 0 ]

  # Check the event file
  [ -f "$REPO/.spiral/spiral_events.jsonl" ]
  grep -q "worker_reset_dirty_worktree" "$REPO/.spiral/spiral_events.jsonl"
  grep -q '"worker-1"' "$REPO/.spiral/spiral_events.jsonl"
  grep -q '"count":1' "$REPO/.spiral/spiral_events.jsonl"
}

@test "multiple dirty worktrees: all cleaned and reported" {
  mkdir -p "$REPO/.spiral-workers"
  create_worker_worktree "$REPO" "worker-1"
  create_worker_worktree "$REPO" "worker-2"

  # Dirty both worktrees
  echo "dirty1" > "$REPO/.spiral-workers/worker-1/dirty.txt"
  git -C "$REPO/.spiral-workers/worker-1" add dirty.txt

  echo "dirty2" >> "$REPO/.spiral-workers/worker-2/README.md"

  run run_dirty_reset "$REPO"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Dirty worktree detected: worker-1"* ]]
  [[ "$output" == *"Dirty worktree detected: worker-2"* ]]
  [[ "$output" == *"Reset 2 dirty worktree(s)"* ]]

  # Both worktrees should be clean now
  wt1_status=$(git -C "$REPO/.spiral-workers/worker-1" status --porcelain 2>/dev/null)
  wt2_status=$(git -C "$REPO/.spiral-workers/worker-2" status --porcelain 2>/dev/null)
  [ -z "$wt1_status" ]
  [ -z "$wt2_status" ]

  # Event should list both workers
  grep -q '"count":2' "$REPO/.spiral/spiral_events.jsonl"
}

@test "mixed clean and dirty worktrees: only dirty ones reset" {
  mkdir -p "$REPO/.spiral-workers"
  create_worker_worktree "$REPO" "worker-1"
  create_worker_worktree "$REPO" "worker-2"

  # Only dirty worker-2
  echo "dirty" > "$REPO/.spiral-workers/worker-2/dirty.txt"
  git -C "$REPO/.spiral-workers/worker-2" add dirty.txt

  run run_dirty_reset "$REPO"
  [ "$status" -eq 0 ]
  [[ "$output" != *"Dirty worktree detected: worker-1"* ]]
  [[ "$output" == *"Dirty worktree detected: worker-2"* ]]
  [[ "$output" == *"Reset 1 dirty worktree(s)"* ]]
}
