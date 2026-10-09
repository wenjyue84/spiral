#!/usr/bin/env bats
# tests/sparse_checkout.bats
# US-376: sparse-checkout for worker worktrees.
# Worker sparse-checkout was DISABLED in run_parallel_ralph.sh (7366800d: it broke Ralph
# when files outside filesTouch were needed). The cone-mode helper now lives in
# lib/impl/worktree.sh; these tests pin that state so it is not re-enabled by accident.

PARALLEL_RALPH_SH="$BATS_TEST_DIRNAME/../lib/run_parallel_ralph.sh"
WORKTREE_SH="$BATS_TEST_DIRNAME/../lib/impl/worktree.sh"
CONFIG_SH="$BATS_TEST_DIRNAME/../spiral.config.sh"

# ── Sparse-checkout state in run_parallel_ralph.sh ─────────────────────────────

@test "run_parallel_ralph.sh includes US-376 sparse-checkout comment" {
  grep -q 'US-376.*Sparse-checkout' "$PARALLEL_RALPH_SH"
}

@test "run_parallel_ralph.sh no longer initializes sparse-checkout cone mode inline" {
  ! grep -qE '^[^#]*sparse-checkout init' "$PARALLEL_RALPH_SH"
}

@test "worktree.sh helper initializes sparse-checkout cone mode" {
  grep -q 'sparse-checkout init --cone' "$WORKTREE_SH"
}

@test "worktree.sh helper uses git sparse-checkout set with the given paths" {
  grep -q 'sparse-checkout set "\${paths_to_checkout\[@\]}"' "$WORKTREE_SH"
}

# ── Error handling ─────────────────────────────────────────────────────────────

@test "worktree.sh helper refuses to run with no paths" {
  grep -q 'requires at least one path' "$WORKTREE_SH"
  grep -q 'return 1' "$WORKTREE_SH"
}

@test "worktree.sh helper parses cleanly" {
  bash -n "$WORKTREE_SH"
}

@test "run_parallel_ralph.sh disables sparse-checkout on fallback" {
  grep -q 'sparse-checkout disable' "$PARALLEL_RALPH_SH" || grep -q 'sparse-checkout disabled' "$PARALLEL_RALPH_SH"
}

@test "run_parallel_ralph.sh does not depend on filesTouch for worker checkout" {
  # Workers get a full checkout, so no inline filesTouch directory extraction in worktree setup
  ! sed -n '/Overlay worker prd\.json/,/Fresh per-worker state/p' "$PARALLEL_RALPH_SH" | grep -v '^[[:space:]]*#' | grep -q 'filesTouch'
}

@test "run_parallel_ralph.sh worktree setup does not call jq to extract filesTouch directories" {
  ! sed -n '/Overlay worker prd\.json/,/Fresh per-worker state/p' "$PARALLEL_RALPH_SH" | grep -q '\$JQ.*filesTouch'
}

@test "run_parallel_ralph.sh extracts from all stories in worker prd.json" {
  grep -q 'userStories.*filesTouch' "$PARALLEL_RALPH_SH"
}

# ── Placement in worktree setup sequence ────────────────────────────────────────

@test "sparse-checkout decision happens after prd.json copy" {
  sed -n '/Overlay worker prd\.json/,/Fresh per-worker state/p' "$PARALLEL_RALPH_SH" | grep -q 'cp.*prd.json' &&
    sed -n '/Overlay worker prd\.json/,/Fresh per-worker state/p' "$PARALLEL_RALPH_SH" | grep -q 'sparse-checkout'
}

@test "sparse-checkout decision happens before fresh state files" {
  sed -n '/US-376.*parse-checkout/,/Fresh per-worker state/p' "$PARALLEL_RALPH_SH" | grep -q 'sparse-checkout'
}

# ── Compatibility with git worktree --lock flag ────────────────────────────────

@test "run_parallel_ralph.sh uses --lock flag with git worktree add" {
  grep -q 'git.*worktree add.*--lock' "$PARALLEL_RALPH_SH"
}

@test "git commands in worker setup are per-worktree (git -C WTREE)" {
  grep 'git -C "\$WTREE"' "$PARALLEL_RALPH_SH" | grep -q .
}

# ── Logging and diagnostics ────────────────────────────────────────────────────

@test "worktree.sh helper logs sparse-checkout configuration start" {
  grep -q 'Configuring sparse-checkout' "$WORKTREE_SH"
}

@test "run_parallel_ralph.sh logs when full checkout is used" {
  grep -q 'Full checkout' "$PARALLEL_RALPH_SH"
}
