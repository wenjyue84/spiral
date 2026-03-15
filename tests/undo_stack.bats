#!/usr/bin/env bats
# tests/undo_stack.bats — Unit tests for lib/spiral_undo.sh (US-239)
#
# Run with: bats tests/undo_stack.bats
#
# Tests verify:
#   - undo_log_record appends valid JSONL entries
#   - undo_log_exists returns 0 when log present, 1 when absent
#   - undo_log_replay executes inverse_commands in reverse (LIFO) order
#   - undo_log_cleanup removes the log file
#   - Mid-story failure scenario: simulated git commit followed by undo restores HEAD

# ── Setup / teardown ──────────────────────────────────────────────────────────

setup() {
  export SPIRAL_SCRATCH_DIR
  SPIRAL_SCRATCH_DIR="$(mktemp -d)"

  # Source the undo library under test
  source "lib/spiral_undo.sh"

  # Create a minimal git repo for tests that exercise real git operations
  export REPO
  REPO="$(mktemp -d)"
  git -C "$REPO" init -q
  git -C "$REPO" config user.email "test@spiral.test"
  git -C "$REPO" config user.name "Spiral Test"
  echo "initial" > "$REPO/README.md"
  git -C "$REPO" add README.md
  git -C "$REPO" commit -q -m "init"
}

teardown() {
  rm -rf "$SPIRAL_SCRATCH_DIR" "$REPO"
}

# ── Tests: undo_log_record ────────────────────────────────────────────────────

@test "undo_log_record creates undo directory" {
  undo_log_record "US-001" "checkpoint" "HEAD:abc123" "git reset --hard abc123"
  [ -d "$SPIRAL_SCRATCH_DIR/undo" ]
}

@test "undo_log_record creates a JSONL file for the story" {
  undo_log_record "US-042" "checkpoint" "HEAD:abc" "git reset --hard abc"
  [ -f "$SPIRAL_SCRATCH_DIR/undo/US-042.jsonl" ]
}

@test "undo_log_record appends multiple entries" {
  undo_log_record "US-042" "checkpoint"    "HEAD:abc" "git reset --hard abc"
  undo_log_record "US-042" "branch_create" "feature/US-042" "git branch -D feature/US-042"
  undo_log_record "US-042" "git_commit"    "pre-commit:abc" "git reset --hard abc"
  line_count=$(wc -l < "$SPIRAL_SCRATCH_DIR/undo/US-042.jsonl")
  [ "$line_count" -eq 3 ]
}

@test "undo_log_record writes valid JSON with required fields" {
  undo_log_record "US-001" "checkpoint" "HEAD:deadbeef" "git reset --hard deadbeef"
  local entry
  entry=$(head -1 "$SPIRAL_SCRATCH_DIR/undo/US-001.jsonl")
  # Check required fields are present
  [[ "$entry" == *'"operation":"checkpoint"'* ]]
  [[ "$entry" == *'"target":"HEAD:deadbeef"'* ]]
  [[ "$entry" == *'"inverse_command":"git reset --hard deadbeef"'* ]]
  [[ "$entry" == *'"timestamp":'* ]]
}

@test "undo_log_record isolates per-story logs" {
  undo_log_record "US-001" "checkpoint" "HEAD:aaa" "git reset --hard aaa"
  undo_log_record "US-002" "checkpoint" "HEAD:bbb" "git reset --hard bbb"
  [ -f "$SPIRAL_SCRATCH_DIR/undo/US-001.jsonl" ]
  [ -f "$SPIRAL_SCRATCH_DIR/undo/US-002.jsonl" ]
  # US-001 log has only one line
  line_count=$(wc -l < "$SPIRAL_SCRATCH_DIR/undo/US-001.jsonl")
  [ "$line_count" -eq 1 ]
}

# ── Tests: undo_log_exists ────────────────────────────────────────────────────

@test "undo_log_exists returns 1 when no log present" {
  run undo_log_exists "US-999"
  [ "$status" -eq 1 ]
}

@test "undo_log_exists returns 0 after undo_log_record" {
  undo_log_record "US-007" "checkpoint" "HEAD:abc" "git reset --hard abc"
  run undo_log_exists "US-007"
  [ "$status" -eq 0 ]
}

# ── Tests: undo_log_cleanup ───────────────────────────────────────────────────

@test "undo_log_cleanup removes the log file" {
  undo_log_record "US-010" "checkpoint" "HEAD:abc" "git reset --hard abc"
  [ -f "$SPIRAL_SCRATCH_DIR/undo/US-010.jsonl" ]
  undo_log_cleanup "US-010"
  [ ! -f "$SPIRAL_SCRATCH_DIR/undo/US-010.jsonl" ]
}

@test "undo_log_cleanup is a no-op when no log exists" {
  # Should not fail even when no log present
  run undo_log_cleanup "US-999"
  [ "$status" -eq 0 ]
}

@test "undo_log_exists returns 1 after cleanup" {
  undo_log_record "US-011" "checkpoint" "HEAD:abc" "git reset --hard abc"
  undo_log_cleanup "US-011"
  run undo_log_exists "US-011"
  [ "$status" -eq 1 ]
}

# ── Tests: undo_log_replay ────────────────────────────────────────────────────

@test "undo_log_replay returns 0 when no log present" {
  run undo_log_replay "US-999"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No undo log found"* ]]
}

@test "undo_log_replay returns 0 on empty log" {
  mkdir -p "$SPIRAL_SCRATCH_DIR/undo"
  touch "$SPIRAL_SCRATCH_DIR/undo/US-050.jsonl"
  run undo_log_replay "US-050"
  [ "$status" -eq 0 ]
}

@test "undo_log_replay executes inverse_commands in LIFO order" {
  # Record ordering via a shared state file
  local order_file="$SPIRAL_SCRATCH_DIR/order.txt"

  undo_log_record "US-100" "checkpoint"    "first"  "echo first  >> $order_file"
  undo_log_record "US-100" "branch_create" "second" "echo second >> $order_file"
  undo_log_record "US-100" "git_commit"    "third"  "echo third  >> $order_file"

  undo_log_replay "US-100"

  # Should be replayed in reverse: third, second, first
  run cat "$order_file"
  [ "${lines[0]}" = "third" ]
  [ "${lines[1]}" = "second" ]
  [ "${lines[2]}" = "first" ]
}

# ── Integration: mid-story failure restores worktree via undo log ─────────────

@test "mid-story failure: undo log restores HEAD to pre-story SHA" {
  # Capture baseline SHA
  local baseline
  baseline=$(git -C "$REPO" rev-parse HEAD)

  # Simulate ralph.sh: record checkpoint entry
  local undo_cmd="git -C $REPO reset --hard $baseline"
  undo_log_record "US-SIM" "checkpoint" "HEAD:$baseline" "$undo_cmd"

  # Simulate a story that writes a file and commits
  echo "story work" > "$REPO/story.txt"
  git -C "$REPO" add story.txt
  git -C "$REPO" commit -q -m "story commit"

  # Verify HEAD has advanced
  local after_commit
  after_commit=$(git -C "$REPO" rev-parse HEAD)
  [ "$after_commit" != "$baseline" ]

  # Simulate failure: replay undo log — should reset HEAD back to baseline
  run undo_log_replay "US-SIM"
  [ "$status" -eq 0 ]

  # HEAD should be back to baseline
  local restored
  restored=$(git -C "$REPO" rev-parse HEAD)
  [ "$restored" = "$baseline" ]

  # story.txt should be gone (reset --hard cleans working tree)
  [ ! -f "$REPO/story.txt" ]
}

@test "re-running a story after undo does not double-apply: stale log detected" {
  # Record a checkpoint entry (simulating a prior failed run)
  undo_log_record "US-IDEM" "checkpoint" "HEAD:abc" "true"

  # undo_log_exists should return 0 — stale log exists
  run undo_log_exists "US-IDEM"
  [ "$status" -eq 0 ]
}
