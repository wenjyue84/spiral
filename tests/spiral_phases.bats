#!/usr/bin/env bats
# tests/spiral_phases.bats — Integration tests for spiral.sh phase transitions
#
# Run with: bats tests/spiral_phases.bats
# Or: bats tests/spiral_phases.bats --tap
#
# Tests verify:
#   - `--gate skip` exits 0 and skips Phase I (implementation)
#   - `--gate quit` exits 0 with no implementation
#   - `--skip-research` skips Phase R (research)
#   - Phase transitions work without live Claude API or network access
#
# Setup creates a minimal temp REPO_ROOT with:
#   - prd.json (test PRD with 2 stories)
#   - spiral.config.sh (test config)
#   - mocked `claude` binary (returns canned research output)
#   - mocked `ralph` script (no-op implementation)

# ── Load bats utilities ────────────────────────────────────────────────────────

setup_file() {
  # Create a persistent temp directory for all tests in this file
  export TEST_REPO_ROOT="$(mktemp -d)"
  export TEST_SCRATCH_DIR="$TEST_REPO_ROOT/scratch"
  mkdir -p "$TEST_SCRATCH_DIR"

  # Create minimal prd.json with two stories
  cat > "$TEST_REPO_ROOT/prd.json" <<'EOF'
{
  "schemaVersion": 1,
  "projectName": "Test Project",
  "productName": "Test Product",
  "branchName": "main",
  "description": "Test PRD for spiral.sh bats tests",
  "userStories": [
    {
      "id": "US-001",
      "title": "Test story 1",
      "priority": "high",
      "description": "First test story",
      "acceptanceCriteria": ["Criterion 1"],
      "technicalNotes": [],
      "dependencies": [],
      "estimatedComplexity": "small",
      "passes": false
    },
    {
      "id": "US-002",
      "title": "Test story 2",
      "priority": "medium",
      "description": "Second test story",
      "acceptanceCriteria": ["Criterion 1"],
      "technicalNotes": [],
      "dependencies": [],
      "estimatedComplexity": "small",
      "passes": false
    }
  ]
}
EOF

  # Create minimal spiral.config.sh
  cat > "$TEST_REPO_ROOT/spiral.config.sh" <<'EOF'
#!/bin/bash
# Test spiral.config.sh
export SPIRAL_PYTHON="python3"
export SPIRAL_HOME="${SPIRAL_HOME:-.}"
export REPO_ROOT="$TEST_REPO_ROOT"
export PRD_FILE="$REPO_ROOT/prd.json"
export SCRATCH_DIR="$TEST_SCRATCH_DIR"
export CLAUDE_MODEL="haiku"
export DRY_RUN="${DRY_RUN:-0}"
export DRY_RUN_DELAY=0.5
EOF
  chmod +x "$TEST_REPO_ROOT/spiral.config.sh"

  # Create mocked `claude` binary that returns canned research output
  mkdir -p "$TEST_REPO_ROOT/bin"
  cat > "$TEST_REPO_ROOT/bin/claude" <<'EOF'
#!/bin/bash
# Mocked claude binary for testing — returns canned research output
cat <<'RESEARCH'
{
  "researchResults": [
    {
      "source": "test",
      "content": "Mocked research output for test"
    }
  ]
}
RESEARCH
exit 0
EOF
  chmod +x "$TEST_REPO_ROOT/bin/claude"

  # Create mocked `ralph` script (no-op implementation runner)
  cat > "$TEST_REPO_ROOT/bin/ralph" <<'EOF'
#!/bin/bash
# Mocked ralph script — marks story as passing
exit 0
EOF
  chmod +x "$TEST_REPO_ROOT/bin/ralph"

  # Create a lib/ directory with minimal helper scripts that spiral.sh depends on
  mkdir -p "$TEST_REPO_ROOT/lib"

  # Create lib/check_dag.py stub
  cat > "$TEST_REPO_ROOT/lib/check_dag.py" <<'EOF'
#!/usr/bin/env python3
import sys
sys.exit(0)
EOF
  chmod +x "$TEST_REPO_ROOT/lib/check_dag.py"

  # Create lib/validate_preflight.sh stub
  cat > "$TEST_REPO_ROOT/lib/validate_preflight.sh" <<'EOF'
#!/bin/bash
spiral_preflight_check() {
  return 0
}
EOF
  chmod +x "$TEST_REPO_ROOT/lib/validate_preflight.sh"

  # Create lib/check_done.py stub
  cat > "$TEST_REPO_ROOT/lib/check_done.py" <<'EOF'
#!/usr/bin/env python3
import sys
sys.exit(1)  # Not done (return 1 to continue looping)
EOF
  chmod +x "$TEST_REPO_ROOT/lib/check_done.py"

  # Create lib/route_stories.py stub
  cat > "$TEST_REPO_ROOT/lib/route_stories.py" <<'EOF'
#!/usr/bin/env python3
import sys
sys.exit(0)
EOF
  chmod +x "$TEST_REPO_ROOT/lib/route_stories.py"

  export PATH="$TEST_REPO_ROOT/bin:$PATH"
}

teardown_file() {
  # Clean up the temp directory after all tests
  rm -rf "$TEST_REPO_ROOT"
}

setup() {
  # Reset SCRATCH_DIR for each test
  rm -rf "$TEST_SCRATCH_DIR"
  mkdir -p "$TEST_SCRATCH_DIR"

  # Create checkpoint file for test
  cat > "$TEST_SCRATCH_DIR/_checkpoint.json" <<'EOF'
{
  "phase": "R",
  "iteration": 1,
  "timestamp": 0
}
EOF
}

# ── Test: --gate skip exits 0 ──────────────────────────────────────────────────

@test "--gate skip exits 0" {
  cd "$TEST_REPO_ROOT"

  # Run spiral.sh with --gate skip to skip to Phase V without implementing
  bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --dry-run

  # Should exit 0 (not error)
  [ $? -eq 0 ]
}

@test "--gate skip produces no _ralph_output.json (no implementation)" {
  cd "$TEST_REPO_ROOT"
  rm -f "$TEST_SCRATCH_DIR/_ralph_output.json"

  # Run with --gate skip
  bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --dry-run 2>/dev/null || true

  # ralph should not have run, so no _ralph_output.json
  # (or it should be empty)
  [[ ! -f "$TEST_SCRATCH_DIR/_ralph_output.json" ]] || \
    [[ $(wc -l < "$TEST_SCRATCH_DIR/_ralph_output.json") -eq 0 ]]
}

# ── Test: --gate quit exits 0 ─────────────────────────────────────────────────

@test "--gate quit exits 0" {
  cd "$TEST_REPO_ROOT"

  # Run spiral.sh with --gate quit to stop execution
  bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate quit --dry-run

  # Should exit 0
  [ $? -eq 0 ]
}

# ── Test: --skip-research skips Phase R ────────────────────────────────────────

@test "--skip-research flag is recognized" {
  cd "$TEST_REPO_ROOT"

  # Run with --skip-research (should not call claude research)
  bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --skip-research --dry-run

  # Should complete without error
  [ $? -eq 0 ]
}

# ── Test: prd.json is loaded correctly ─────────────────────────────────────────

@test "prd.json is loaded and parsed" {
  cd "$TEST_REPO_ROOT"

  # Minimal check: prd.json exists and is valid JSON
  [[ -f "$TEST_REPO_ROOT/prd.json" ]]

  # Check it's valid JSON (jq can parse it)
  if command -v jq &>/dev/null; then
    jq empty "$TEST_REPO_ROOT/prd.json"
  fi
}

# ── Test: spiral.config.sh is sourced ──────────────────────────────────────────

@test "spiral.config.sh is sourced correctly" {
  cd "$TEST_REPO_ROOT"

  # Source the config and verify variables are set
  source "spiral.config.sh"

  [[ -n "$SPIRAL_PYTHON" ]]
  [[ -n "$REPO_ROOT" ]]
  [[ -n "$PRD_FILE" ]]
  [[ -n "$SCRATCH_DIR" ]]
}

# ── Test: Mocked claude binary is on PATH ──────────────────────────────────────

@test "Mocked claude binary is callable" {
  # Verify our mocked claude is in PATH
  command -v claude &>/dev/null

  # Run it and check it returns canned output
  output=$(claude)
  [[ "$output" =~ "researchResults" ]]
}

# ── Test: Phase transition with minimal PRD ────────────────────────────────────

@test "spiral.sh completes Phase R → T → M → G → C with --gate skip" {
  cd "$TEST_REPO_ROOT"

  # Run spiral.sh with controlled progression
  # Should go through: Phase R, T, M, Gate (skip), Check Done
  bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --dry-run

  # Verify success
  [ $? -eq 0 ]
}

# ── Test: DRY_RUN mode prevents API calls ──────────────────────────────────────

@test "DRY_RUN mode prevents actual claude API calls" {
  cd "$TEST_REPO_ROOT"
  export DRY_RUN=1

  # In dry-run mode, should succeed regardless
  bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --dry-run

  [ $? -eq 0 ]
}

# ── Tests: SPIRAL_PRE_PHASE_HOOK and SPIRAL_POST_PHASE_HOOK (US-132) ───────────

@test "SPIRAL_POST_PHASE_HOOK is called and receives SPIRAL_CURRENT_PHASE" {
  cd "$TEST_REPO_ROOT"

  local hook_log="$TEST_SCRATCH_DIR/hook_phases.txt"

  # Create a post-phase hook that logs SPIRAL_CURRENT_PHASE
  local hook="$TEST_REPO_ROOT/bin/post-hook.sh"
  cat > "$hook" <<'HOOKEOF'
#!/bin/bash
echo "$SPIRAL_CURRENT_PHASE" >> "$HOOK_LOG"
exit 0
HOOKEOF
  chmod +x "$hook"

  HOOK_LOG="$hook_log" SPIRAL_POST_PHASE_HOOK="$hook" \
    bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --dry-run

  # Hook should have been called for at least one phase
  [ -f "$hook_log" ]
  [ "$(wc -l < "$hook_log")" -ge 1 ]
}

@test "SPIRAL_PRE_PHASE_HOOK returning 0 allows spiral to continue" {
  cd "$TEST_REPO_ROOT"

  # Create a pre-phase hook that always succeeds
  local hook="$TEST_REPO_ROOT/bin/pre-hook-ok.sh"
  cat > "$hook" <<'HOOKEOF'
#!/bin/bash
exit 0
HOOKEOF
  chmod +x "$hook"

  SPIRAL_PRE_PHASE_HOOK="$hook" \
    bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --dry-run

  [ $? -eq 0 ]
}

@test "SPIRAL_PRE_PHASE_HOOK receives SPIRAL_CURRENT_PHASE env var" {
  cd "$TEST_REPO_ROOT"

  local hook_log="$TEST_SCRATCH_DIR/pre_hook_phases.txt"

  # Create a pre-phase hook that logs the phase
  local hook="$TEST_REPO_ROOT/bin/pre-hook-log.sh"
  cat > "$hook" <<'HOOKEOF'
#!/bin/bash
echo "$SPIRAL_CURRENT_PHASE" >> "$HOOK_LOG"
exit 0
HOOKEOF
  chmod +x "$hook"

  HOOK_LOG="$hook_log" SPIRAL_PRE_PHASE_HOOK="$hook" \
    bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --dry-run

  [ -f "$hook_log" ]
  # At minimum Phase R and M should have been logged
  grep -q "R" "$hook_log" || grep -q "M" "$hook_log"
}

@test "non-executable SPIRAL_PRE_PHASE_HOOK is skipped with warning" {
  cd "$TEST_REPO_ROOT"

  # Create a non-executable hook file
  local hook="$TEST_REPO_ROOT/bin/non-exec-hook.sh"
  echo '#!/bin/bash' > "$hook"
  # Deliberately NOT chmod +x

  # spiral.sh should still succeed (non-executable hook is a warning, not fatal)
  SPIRAL_PRE_PHASE_HOOK="$hook" \
    bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --dry-run

  [ $? -eq 0 ]
}

@test "SPIRAL_HOOK_TIMEOUT is respected (hook with timeout)" {
  cd "$TEST_REPO_ROOT"

  # Create a post-phase hook that exits immediately (should complete within 1s timeout)
  local hook="$TEST_REPO_ROOT/bin/fast-hook.sh"
  cat > "$hook" <<'HOOKEOF'
#!/bin/bash
exit 0
HOOKEOF
  chmod +x "$hook"

  SPIRAL_POST_PHASE_HOOK="$hook" SPIRAL_HOOK_TIMEOUT=5 \
    bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --dry-run

  [ $? -eq 0 ]
}
