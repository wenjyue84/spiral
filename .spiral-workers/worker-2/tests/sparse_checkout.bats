#!/usr/bin/env bats
# tests/sparse_checkout.bats
# US-376: Verify sparse-checkout cone mode initialization for worker worktrees

PARALLEL_RALPH_SH="$BATS_TEST_DIRNAME/../lib/run_parallel_ralph.sh"
CONFIG_SH="$BATS_TEST_DIRNAME/../spiral.config.sh"

# ── Sparse-checkout initialization code presence ────────────────────────────────

@test "run_parallel_ralph.sh includes US-376 sparse-checkout comment" {
  grep -q 'US-376.*sparse-checkout' "$PARALLEL_RALPH_SH"
}

@test "run_parallel_ralph.sh initializes sparse-checkout cone mode" {
  grep -q 'sparse-checkout init --cone' "$PARALLEL_RALPH_SH"
}

@test "run_parallel_ralph.sh extracts directories from filesTouch" {
  grep -q 'filesTouch.*unique' "$PARALLEL_RALPH_SH"
}

@test "run_parallel_ralph.sh uses git sparse-checkout set with stdin" {
  grep -q 'sparse-checkout set --stdin' "$PARALLEL_RALPH_SH"
}

# ── Error handling and fallback ─────────────────────────────────────────────────

@test "run_parallel_ralph.sh has fallback when sparse-checkout init fails" {
  grep -q 'WARNING.*sparse-checkout init failed' "$PARALLEL_RALPH_SH"
}

@test "run_parallel_ralph.sh has fallback when sparse-checkout set fails" {
  grep -q 'WARNING.*sparse-checkout set failed' "$PARALLEL_RALPH_SH"
}

@test "run_parallel_ralph.sh disables sparse-checkout on fallback" {
  grep -q 'sparse-checkout disable' "$PARALLEL_RALPH_SH"
}

@test "run_parallel_ralph.sh handles empty filesTouch gracefully" {
  grep -q 'No filesTouch defined' "$PARALLEL_RALPH_SH"
}

# ── JQ query for directory extraction ───────────────────────────────────────────

@test "run_parallel_ralph.sh uses jq to extract unique directories from filesTouch" {
  grep -q '\$JQ.*filesTouch.*unique' "$PARALLEL_RALPH_SH"
}

@test "run_parallel_ralph.sh extracts from all stories in worker prd.json" {
  grep -q 'userStories.*filesTouch' "$PARALLEL_RALPH_SH"
}

# ── Placement in worktree setup sequence ────────────────────────────────────────

@test "sparse-checkout initialization happens after prd.json copy" {
  # Extract lines from 'Overlay worker prd.json' comment to sparse-checkout init
  sed -n '/Overlay worker prd\.json/,/sparse-checkout init/p' "$PARALLEL_RALPH_SH" | grep -q 'cp.*prd.json' &&
    sed -n '/Overlay worker prd\.json/,/sparse-checkout init/p' "$PARALLEL_RALPH_SH" | grep -q 'sparse-checkout init'
}

@test "sparse-checkout initialization happens before fresh state files" {
  # Extract lines from sparse-checkout to 'Fresh per-worker state'
  sed -n '/US-376.*sparse-checkout/,/Fresh per-worker state/p' "$PARALLEL_RALPH_SH" | grep -q 'sparse-checkout'
}

# ── Compatibility with git worktree --lock flag ────────────────────────────────

@test "run_parallel_ralph.sh uses --lock flag with git worktree add" {
  grep -q 'git.*worktree add.*--lock' "$PARALLEL_RALPH_SH"
}

@test "git sparse-checkout commands are per-worktree (not shared)" {
  # Verify each worker uses -C "$WTREE" with sparse-checkout commands
  grep 'sparse-checkout' "$PARALLEL_RALPH_SH" | grep -q '\-C.*"\$WTREE"'
}

# ── Logging and diagnostics ────────────────────────────────────────────────────

@test "run_parallel_ralph.sh logs sparse-checkout initialization start" {
  grep -q 'Configuring sparse-checkout' "$PARALLEL_RALPH_SH"
}

@test "run_parallel_ralph.sh logs when full checkout is used (no filesTouch)" {
  grep -q 'full checkout' "$PARALLEL_RALPH_SH"
}
