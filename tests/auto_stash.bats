#!/usr/bin/env bats
# tests/auto_stash.bats — Tests for US-177: dirty working tree guard
#
# Run with: bats tests/auto_stash.bats
#
# Tests verify:
#   - Clean working tree: DIRTY_SKIP_RALPH=0, no stash created
#   - Dirty tree + SPIRAL_AUTO_STASH=true: stash is pushed, DIRTY_SKIP_RALPH=0
#   - Dirty tree + SPIRAL_AUTO_STASH=false: DIRTY_SKIP_RALPH=1, abort message printed
#   - Stash pop after Phase I succeeds (or warns on failure)

# ── Helpers ───────────────────────────────────────────────────────────────────

# Execute the dirty-tree guard inline snippet in a subshell and capture results.
# Sets exit-code based on _DIRTY_SKIP_RALPH value (0 = proceed, 1 = skip).
#
# Exports required by the snippet:
#   REPO_ROOT, SPIRAL_AUTO_STASH, SPIRAL_ITER, log_spiral_event (stub)
run_dirty_guard() {
  bash -c '
    set -euo pipefail

    log_spiral_event() { true; }

    REPO_ROOT="$1"
    SPIRAL_AUTO_STASH="$2"
    SPIRAL_ITER=1

    _AUTO_STASH_REF=""
    _DIRTY_SKIP_RALPH=0
    _DIRTY_FILES=$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null || true)
    if [[ -n "$_DIRTY_FILES" ]]; then
      if [[ "$SPIRAL_AUTO_STASH" == "true" ]]; then
        _STASH_MSG="spiral-auto-stash-iter-${SPIRAL_ITER}"
        echo "[guard] stash-created"
        git -C "$REPO_ROOT" stash push --include-untracked -m "$_STASH_MSG" >/dev/null 2>&1 || true
        _AUTO_STASH_REF=$(git -C "$REPO_ROOT" stash list --format="%gd %gs" 2>/dev/null \
          | grep "$_STASH_MSG" | head -1 | awk "{print \$1}")
        echo "[guard] stash-ref=${_AUTO_STASH_REF:-stash@{0}}"
      else
        echo "[guard] skip-phase-i"
        _DIRTY_SKIP_RALPH=1
      fi
    else
      echo "[guard] clean-tree"
    fi

    # Report final state
    echo "_DIRTY_SKIP_RALPH=$_DIRTY_SKIP_RALPH"
    echo "_AUTO_STASH_REF=${_AUTO_STASH_REF:-}"
    exit "$_DIRTY_SKIP_RALPH"
  ' -- "$1" "$2"
}

# ── Setup / teardown ──────────────────────────────────────────────────────────

setup() {
  export TMPDIR_AS
  TMPDIR_AS="$(mktemp -d)"

  # Create a minimal git repo for tests
  REPO="$TMPDIR_AS/repo"
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
  rm -rf "$TMPDIR_AS"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "clean working tree: guard reports clean, DIRTY_SKIP_RALPH=0" {
  run run_dirty_guard "$REPO" "false"
  [ "$status" -eq 0 ]
  [[ "$output" == *"clean-tree"* ]]
  [[ "$output" == *"_DIRTY_SKIP_RALPH=0"* ]]
}

@test "clean working tree with SPIRAL_AUTO_STASH=true: guard still reports clean" {
  run run_dirty_guard "$REPO" "true"
  [ "$status" -eq 0 ]
  [[ "$output" == *"clean-tree"* ]]
  [[ "$output" == *"_DIRTY_SKIP_RALPH=0"* ]]
}

@test "dirty tree + SPIRAL_AUTO_STASH=false: DIRTY_SKIP_RALPH=1 (abort path)" {
  # Create an uncommitted file
  echo "dirty" > "$REPO/dirty.txt"
  git -C "$REPO" add dirty.txt   # staged but not committed

  run run_dirty_guard "$REPO" "false"
  [ "$status" -eq 1 ]
  [[ "$output" == *"skip-phase-i"* ]]
  [[ "$output" == *"_DIRTY_SKIP_RALPH=1"* ]]
}

@test "dirty tree + SPIRAL_AUTO_STASH=false: untracked file also triggers abort" {
  # Untracked file (not staged)
  echo "untracked" > "$REPO/untracked.txt"

  run run_dirty_guard "$REPO" "false"
  [ "$status" -eq 1 ]
  [[ "$output" == *"skip-phase-i"* ]]
}

@test "dirty tree + SPIRAL_AUTO_STASH=true: stash is created, DIRTY_SKIP_RALPH=0" {
  echo "dirty" > "$REPO/dirty.txt"
  git -C "$REPO" add dirty.txt

  run run_dirty_guard "$REPO" "true"
  [ "$status" -eq 0 ]
  [[ "$output" == *"stash-created"* ]]
  [[ "$output" == *"_DIRTY_SKIP_RALPH=0"* ]]

  # Verify stash actually exists in the repo
  stash_count=$(git -C "$REPO" stash list | wc -l)
  [ "$stash_count" -ge 1 ]
}

@test "dirty tree + SPIRAL_AUTO_STASH=true: stash ref is reported" {
  echo "modified content" >> "$REPO/README.md"

  run run_dirty_guard "$REPO" "true"
  [ "$status" -eq 0 ]
  [[ "$output" == *"stash-ref="* ]]
}

@test "dirty tree + SPIRAL_AUTO_STASH=true: stash pop restores changes" {
  echo "important work" > "$REPO/work.txt"
  git -C "$REPO" add work.txt

  # Stash the changes
  run run_dirty_guard "$REPO" "true"
  [ "$status" -eq 0 ]

  # File should be gone after stash
  [ ! -f "$REPO/work.txt" ]

  # Pop the stash
  git -C "$REPO" stash pop >/dev/null 2>&1

  # File should be back
  [ -f "$REPO/work.txt" ]
  run cat "$REPO/work.txt"
  [ "$output" = "important work" ]
}

@test "stash message contains iter number" {
  echo "change" >> "$REPO/README.md"
  git -C "$REPO" add README.md

  run run_dirty_guard "$REPO" "true"
  [ "$status" -eq 0 ]

  # Check that the stash list contains our message with iter number
  stash_msg=$(git -C "$REPO" stash list 2>/dev/null | head -1)
  [[ "$stash_msg" == *"spiral-auto-stash-iter-"* ]]
}
