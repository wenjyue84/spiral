#!/usr/bin/env bats
# tests/phase_v_parallel.bats — Tests for US-148: Parallel Phase V test execution
#
# Run with: bats tests/phase_v_parallel.bats
#
# Tests verify:
#   - SPIRAL_PARALLEL_TESTS=false (default) → command unchanged
#   - SPIRAL_PARALLEL_TESTS=true + pytest + xdist installed → -n N appended
#   - SPIRAL_PARALLEL_TESTS=true + pytest + xdist missing → warn, no flag appended
#   - SPIRAL_PARALLEL_TESTS=true + bats + parallel installed → --jobs N appended
#   - SPIRAL_PARALLEL_TESTS=true + bats + parallel missing → warn, no flag appended
#   - SPIRAL_TEST_WORKERS explicit → uses that value, not nproc/2
#   - SPIRAL_TEST_WORKERS empty → nproc/2, minimum 1

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_PV
  TMPDIR_PV="$(mktemp -d)"

  # Stub helpers
  log_spiral_event() { printf '{"type":"%s"}\n' "$1" >> "$TMPDIR_PV/events.jsonl"; }
  export -f log_spiral_event

  # Default env
  export SPIRAL_PARALLEL_TESTS="false"
  export SPIRAL_TEST_WORKERS=""
  export SPIRAL_ITER=1
}

teardown() {
  rm -rf "$TMPDIR_PV"
}

# ── Helper: run the parallel injection logic ──────────────────────────────────
# Mirrors the US-148 block added to spiral.sh.
# Inputs: SPIRAL_PARALLEL_TESTS, SPIRAL_TEST_WORKERS, _EFFECTIVE_VALIDATE_CMD,
#         SPIRAL_PYTHON_HAS_XDIST (mock), PARALLEL_AVAILABLE (mock)
# Output: prints the final _EFFECTIVE_VALIDATE_CMD
run_parallel_injection() {
  local cmd="$1"
  local _EFFECTIVE_VALIDATE_CMD="$cmd"
  local SPIRAL_PARALLEL_TESTS="${SPIRAL_PARALLEL_TESTS:-false}"
  local SPIRAL_TEST_WORKERS="${SPIRAL_TEST_WORKERS:-}"
  local SPIRAL_ITER="${SPIRAL_ITER:-1}"

  # Mock SPIRAL_PYTHON: stub that either succeeds or fails import xdist
  local SPIRAL_PYTHON="${TMPDIR_PV}/mock_python.sh"
  if [[ "${SPIRAL_PYTHON_HAS_XDIST:-false}" == "true" ]]; then
    printf '#!/bin/bash\nif [[ "$*" == *"import xdist"* ]]; then exit 0; fi\necho "0.1.0"\n' > "$SPIRAL_PYTHON"
  else
    printf '#!/bin/bash\nif [[ "$*" == *"import xdist"* ]]; then exit 1; fi\n' > "$SPIRAL_PYTHON"
  fi
  chmod +x "$SPIRAL_PYTHON"

  # Mock parallel command availability
  if [[ "${PARALLEL_AVAILABLE:-false}" == "true" ]]; then
    local _parallel_dir="${TMPDIR_PV}/bin"
    mkdir -p "$_parallel_dir"
    printf '#!/bin/bash\nexit 0\n' > "$_parallel_dir/parallel"
    chmod +x "$_parallel_dir/parallel"
    export PATH="$_parallel_dir:$PATH"
  else
    # Ensure parallel is NOT in PATH by using a clean PATH without it
    export PATH="/usr/bin:/bin"
  fi

  if [[ "$SPIRAL_PARALLEL_TESTS" == "true" ]]; then
    local _NPROC _TEST_WORKERS
    if [[ -n "$SPIRAL_TEST_WORKERS" ]]; then
      _TEST_WORKERS="$SPIRAL_TEST_WORKERS"
    else
      _NPROC=$(nproc 2>/dev/null || echo 2)
      _TEST_WORKERS=$(( _NPROC / 2 ))
      [[ "$_TEST_WORKERS" -lt 1 ]] && _TEST_WORKERS=1
    fi
    if echo "$_EFFECTIVE_VALIDATE_CMD" | grep -q "pytest"; then
      if "$SPIRAL_PYTHON" -c "import xdist" 2>/dev/null; then
        _EFFECTIVE_VALIDATE_CMD="$_EFFECTIVE_VALIDATE_CMD -n $_TEST_WORKERS"
        echo "  [V] Parallel pytest: -n $_TEST_WORKERS (pytest-xdist)" >&2
        log_spiral_event "phase_v_parallel"
      else
        echo "  [V] WARN: SPIRAL_PARALLEL_TESTS=true but pytest-xdist not installed — running serial" >&2
      fi
    elif echo "$_EFFECTIVE_VALIDATE_CMD" | grep -qE "(^| )bats( |$)"; then
      if command -v parallel &>/dev/null; then
        _EFFECTIVE_VALIDATE_CMD="$_EFFECTIVE_VALIDATE_CMD --jobs $_TEST_WORKERS"
        echo "  [V] Parallel bats: --jobs $_TEST_WORKERS (GNU parallel)" >&2
        log_spiral_event "phase_v_parallel"
      else
        echo "  [V] WARN: SPIRAL_PARALLEL_TESTS=true but GNU parallel not installed — running serial" >&2
      fi
    fi
  fi

  echo "$_EFFECTIVE_VALIDATE_CMD"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "SPIRAL_PARALLEL_TESTS=false (default): command unchanged for pytest" {
  export SPIRAL_PARALLEL_TESTS="false"
  result=$(run_parallel_injection "uv run pytest tests/")
  [ "$result" = "uv run pytest tests/" ]
}

@test "SPIRAL_PARALLEL_TESTS=false (default): command unchanged for bats" {
  export SPIRAL_PARALLEL_TESTS="false"
  result=$(run_parallel_injection "bats tests/foo.bats")
  [ "$result" = "bats tests/foo.bats" ]
}

@test "pytest + xdist installed + SPIRAL_PARALLEL_TESTS=true: appends -n N" {
  export SPIRAL_PARALLEL_TESTS="true"
  export SPIRAL_PYTHON_HAS_XDIST="true"
  export SPIRAL_TEST_WORKERS="4"
  result=$(run_parallel_injection "uv run pytest tests/")
  [ "$result" = "uv run pytest tests/ -n 4" ]
}

@test "pytest + xdist missing + SPIRAL_PARALLEL_TESTS=true: no flag appended, warns" {
  export SPIRAL_PARALLEL_TESTS="true"
  export SPIRAL_PYTHON_HAS_XDIST="false"
  result=$(run_parallel_injection "uv run pytest tests/" 2>&1)
  # Command should be unchanged (last line is cmd, stderr has warn)
  final_cmd=$(run_parallel_injection "uv run pytest tests/")
  [ "$final_cmd" = "uv run pytest tests/" ]
  # Warning emitted
  [[ "$result" == *"pytest-xdist not installed"* ]]
}

@test "bats + GNU parallel installed + SPIRAL_PARALLEL_TESTS=true: appends --jobs N" {
  export SPIRAL_PARALLEL_TESTS="true"
  export PARALLEL_AVAILABLE="true"
  export SPIRAL_TEST_WORKERS="2"
  result=$(run_parallel_injection "bats tests/foo.bats")
  [ "$result" = "bats tests/foo.bats --jobs 2" ]
}

@test "bats + GNU parallel missing + SPIRAL_PARALLEL_TESTS=true: no flag appended, warns" {
  export SPIRAL_PARALLEL_TESTS="true"
  export PARALLEL_AVAILABLE="false"
  final_cmd=$(run_parallel_injection "bats tests/foo.bats")
  [ "$final_cmd" = "bats tests/foo.bats" ]
}

@test "SPIRAL_TEST_WORKERS explicit value is used for pytest-xdist" {
  export SPIRAL_PARALLEL_TESTS="true"
  export SPIRAL_PYTHON_HAS_XDIST="true"
  export SPIRAL_TEST_WORKERS="8"
  result=$(run_parallel_injection "uv run pytest tests/")
  [[ "$result" == *"-n 8"* ]]
}

@test "SPIRAL_TEST_WORKERS empty: uses nproc/2 (minimum 1) for pytest-xdist" {
  export SPIRAL_PARALLEL_TESTS="true"
  export SPIRAL_PYTHON_HAS_XDIST="true"
  export SPIRAL_TEST_WORKERS=""
  result=$(run_parallel_injection "uv run pytest tests/")
  # Result should contain -n <number>
  [[ "$result" =~ -n\ [0-9]+ ]]
  # Extract worker count
  workers=$(echo "$result" | grep -o '\-n [0-9]*' | grep -o '[0-9]*')
  [ "$workers" -ge 1 ]
}

@test "phase_v_parallel event logged when pytest-xdist active" {
  export SPIRAL_PARALLEL_TESTS="true"
  export SPIRAL_PYTHON_HAS_XDIST="true"
  export SPIRAL_TEST_WORKERS="2"
  run_parallel_injection "uv run pytest tests/" > /dev/null
  [ -f "$TMPDIR_PV/events.jsonl" ]
  grep -q "phase_v_parallel" "$TMPDIR_PV/events.jsonl"
}

@test "phase_v_parallel event logged when bats --jobs active" {
  export SPIRAL_PARALLEL_TESTS="true"
  export PARALLEL_AVAILABLE="true"
  export SPIRAL_TEST_WORKERS="2"
  run_parallel_injection "bats tests/foo.bats" > /dev/null
  [ -f "$TMPDIR_PV/events.jsonl" ]
  grep -q "phase_v_parallel" "$TMPDIR_PV/events.jsonl"
}

@test "non-pytest non-bats command is never modified" {
  export SPIRAL_PARALLEL_TESTS="true"
  export SPIRAL_PYTHON_HAS_XDIST="true"
  export PARALLEL_AVAILABLE="true"
  export SPIRAL_TEST_WORKERS="4"
  result=$(run_parallel_injection "npm run test")
  [ "$result" = "npm run test" ]
}
