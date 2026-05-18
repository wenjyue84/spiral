#!/usr/bin/env bats

setup() {
  export TEST_TMPDIR=$(mktemp -d)
  export RESULTS_FILE="$TEST_TMPDIR/results.jsonl"

  cat >"$RESULTS_FILE" <<'EOF'
{"phase": "A", "iteration": 1, "duration_sec": 45.2}
{"phase": "R", "iteration": 1, "duration_sec": 120.5}
{"phase": "T", "iteration": 1, "duration_sec": 30.2}
{"phase": "A", "iteration": 2, "duration_sec": 43.8}
{"phase": "R", "iteration": 2, "duration_sec": 125.3}
{"phase": "T", "iteration": 2, "duration_sec": 32.1}
{"phase": "A", "iteration": 3, "duration_sec": 46.1}
{"phase": "R", "iteration": 3, "duration_sec": 122.7}
{"phase": "T", "iteration": 3, "duration_sec": 31.5}
{"phase": "A", "iteration": 4, "duration_sec": 44.9}
{"phase": "R", "iteration": 4, "duration_sec": 123.2}
{"phase": "T", "iteration": 4, "duration_sec": 30.8}
{"phase": "A", "iteration": 5, "duration_sec": 45.5}
{"phase": "R", "iteration": 5, "duration_sec": 124.1}
{"phase": "T", "iteration": 5, "duration_sec": 31.3}
EOF
}

@test "CLI: spiral analyze-phases outputs table format" {
  run uv run python lib/phase_bottleneck_analyzer.py --results "$RESULTS_FILE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"PHASE BOTTLENECK ANALYSIS"* ]]
}

@test "CLI: spiral analyze-phases --json outputs newline-delimited JSON" {
  run uv run python lib/phase_bottleneck_analyzer.py --results "$RESULTS_FILE" --json
  [ "$status" -eq 0 ]
  [[ "$output" == *"phase_name"* ]]
}

@test "CLI: spiral analyze-phases handles missing file" {
  run uv run python lib/phase_bottleneck_analyzer.py --results /nonexistent/file.jsonl
  [ "$status" -eq 0 ]
}
