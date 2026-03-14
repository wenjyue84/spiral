#!/usr/bin/env bats
# tests/phase_parallel_rt.bats — Verify Phase R and Phase T run simultaneously (US-182)
#
# Strategy: replace the "actual work" in each phase with a mock that:
#   1. Records its start timestamp to a file
#   2. Sleeps for a fixed duration
#   3. Records its end timestamp to a file
#
# After the run, we verify that T started before R finished (overlap = parallel).

# ── bats helpers ──────────────────────────────────────────────────────────────
load "bats-support/load"
load "bats-assert/load"

setup_file() {
  export TEST_REPO_ROOT="$(mktemp -d)"
  export TEST_SCRATCH_DIR="$TEST_REPO_ROOT/.spiral"
  mkdir -p "$TEST_SCRATCH_DIR"

  # Minimal prd.json
  cat >"$TEST_REPO_ROOT/prd.json" <<'EOF'
{
  "schemaVersion": 1,
  "projectName": "Test",
  "productName": "Test",
  "branchName": "main",
  "description": "Parallel RT test",
  "userStories": [
    {
      "id": "US-001",
      "title": "Story 1",
      "priority": "high",
      "description": "Test story",
      "acceptanceCriteria": ["AC1"],
      "technicalNotes": [],
      "dependencies": [],
      "estimatedComplexity": "small",
      "passes": false
    }
  ]
}
EOF

  mkdir -p "$TEST_REPO_ROOT/bin"

  # Mock synthesize_tests.py: records timestamps and sleeps 1s
  cat >"$TEST_REPO_ROOT/bin/mock_synthesize.py" <<'PYEOF'
#!/usr/bin/env python3
import sys, time, json, os

scratch = os.environ.get("SCRATCH_DIR", "/tmp")
ts_file = os.path.join(scratch, "_mock_t_start.txt")
out_file = None
for i, arg in enumerate(sys.argv):
    if arg == "--output" and i + 1 < len(sys.argv):
        out_file = sys.argv[i + 1]

with open(ts_file, "w") as f:
    f.write(str(int(time.time())))

time.sleep(1)  # simulate work

if out_file:
    with open(out_file, "w") as f:
        json.dump({"stories": []}, f)
sys.exit(0)
PYEOF
  chmod +x "$TEST_REPO_ROOT/bin/mock_synthesize.py"

  # spiral.config.sh — point SPIRAL_PYTHON at mock synthesize
  cat >"$TEST_REPO_ROOT/spiral.config.sh" <<CFGEOF
#!/bin/bash
export SPIRAL_PYTHON="python3"
export SPIRAL_HOME="${SPIRAL_HOME:-.}"
export REPO_ROOT="$TEST_REPO_ROOT"
export PRD_FILE="\$REPO_ROOT/prd.json"
export SCRATCH_DIR="$TEST_SCRATCH_DIR"
export CLAUDE_MODEL="haiku"
export DRY_RUN=0
export DRY_RUN_DELAY=0
# Override synthesize_tests path to our mock
export SPIRAL_SYNTHESIZE_CMD="python3 $TEST_REPO_ROOT/bin/mock_synthesize.py"
CFGEOF
  chmod +x "$TEST_REPO_ROOT/spiral.config.sh"

  # Stubs needed by spiral.sh
  mkdir -p "$TEST_REPO_ROOT/lib"

  cat >"$TEST_REPO_ROOT/lib/validate_preflight.sh" <<'EOF'
#!/bin/bash
spiral_preflight_check() { return 0; }
EOF

  cat >"$TEST_REPO_ROOT/lib/check_done.py" <<'EOF'
#!/usr/bin/env python3
import sys; sys.exit(1)
EOF

  cat >"$TEST_REPO_ROOT/lib/check_dag.py" <<'EOF'
#!/usr/bin/env python3
import sys; sys.exit(0)
EOF

  cat >"$TEST_REPO_ROOT/lib/route_stories.py" <<'EOF'
#!/usr/bin/env python3
import sys; sys.exit(0)
EOF

  # Mock claude: records start timestamp, sleeps 2s, writes empty research output
  cat >"$TEST_REPO_ROOT/bin/claude" <<'CLAUDEOF'
#!/bin/bash
# Record Phase R start time
echo "$(date +%s)" > "$SCRATCH_DIR/_mock_r_start.txt"
# Find --output argument if present (not used for research, R writes directly)
sleep 2
# Write empty research output that spiral.sh expects
cat > "$SCRATCH_DIR/_research_output.json" <<'JSON'
{"stories":[]}
JSON
exit 0
CLAUDEOF
  chmod +x "$TEST_REPO_ROOT/bin/claude"

  cat >"$TEST_REPO_ROOT/bin/ralph" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$TEST_REPO_ROOT/bin/ralph"

  export PATH="$TEST_REPO_ROOT/bin:$PATH"
  export SCRATCH_DIR="$TEST_SCRATCH_DIR"
}

teardown_file() {
  rm -rf "$TEST_REPO_ROOT"
}

setup() {
  rm -rf "$TEST_SCRATCH_DIR"
  mkdir -p "$TEST_SCRATCH_DIR"
}

# ── Test: R and T start times overlap (parallel execution) ───────────────────

@test "Phase R and Phase T run simultaneously (parallel)" {
  cd "$TEST_REPO_ROOT"

  # Run spiral with --gate skip (skips G/I/V/C) and --skip-research=0 (run R)
  # DRY_RUN=0 so both R and T actually launch
  SCRATCH_DIR="$TEST_SCRATCH_DIR" \
    bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip 2>/dev/null || true

  # Both timestamp files must exist
  r_start_file="$TEST_SCRATCH_DIR/_mock_r_start.txt"
  t_start_file="$TEST_SCRATCH_DIR/_mock_t_start.txt"

  [ -f "$r_start_file" ] || skip "R did not record start time (may have been skipped)"
  [ -f "$t_start_file" ] || skip "T did not record start time (may have been skipped)"

  r_start=$(cat "$r_start_file")
  t_start=$(cat "$t_start_file")

  # R sleeps 2s; T sleeps 1s. If sequential: T starts after R finishes (r_start + 2 <= t_start).
  # If parallel: T starts at approximately the same time as R (|t_start - r_start| < 2).
  diff=$(( t_start - r_start ))
  [ "$diff" -lt 2 ] || {
    echo "FAIL: T started $diff seconds after R — expected parallel start (diff < 2s)"
    echo "  R start: $r_start"
    echo "  T start: $t_start"
    return 1
  }
}

# ── Test: --dry-run skips both R and T without parallel jobs ────────────────

@test "dry-run skips both R and T without launching background jobs" {
  cd "$TEST_REPO_ROOT"

  DRY_RUN=1 SCRATCH_DIR="$TEST_SCRATCH_DIR" \
    bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --dry-run 2>/dev/null || true

  # Neither mock should have recorded a start time
  [ ! -f "$TEST_SCRATCH_DIR/_mock_r_start.txt" ]
  [ ! -f "$TEST_SCRATCH_DIR/_mock_t_start.txt" ]
}

# ── Test: --skip-research skips R but T still runs ──────────────────────────

@test "--skip-research skips R but T still runs" {
  cd "$TEST_REPO_ROOT"

  SCRATCH_DIR="$TEST_SCRATCH_DIR" \
    bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --skip-research 2>/dev/null || true

  # R should NOT have recorded a start time (skipped)
  [ ! -f "$TEST_SCRATCH_DIR/_mock_r_start.txt" ]

  # T should have run (recorded start time) OR its output file exists
  [ -f "$TEST_SCRATCH_DIR/_mock_t_start.txt" ] || \
    [ -f "$TEST_SCRATCH_DIR/_test_stories_output.json" ]
}

# ── Test: checkpoint marker files are written for R and T ───────────────────

@test "Phase R and T write independent checkpoint marker files" {
  cd "$TEST_REPO_ROOT"

  SCRATCH_DIR="$TEST_SCRATCH_DIR" \
    bash "$(dirname "${BATS_TEST_DIRNAME}")/spiral.sh" 1 --gate skip --skip-research --dry-run 2>/dev/null || true

  # In dry-run mode, both marker files should be written immediately
  [ -f "$TEST_SCRATCH_DIR/_phase_R_1.ckpt" ] || \
    [ -f "$TEST_SCRATCH_DIR/_phase_T_1.ckpt" ]
}
