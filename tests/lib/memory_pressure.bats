#!/usr/bin/env bats
# tests/lib/memory_pressure.bats — Unit tests for lib/memory-pressure-check.sh
#
# Run with: bats tests/lib/memory_pressure.bats
#
# Tests verify:
#   - spiral_pressure_level returns 0 when no pressure file exists
#   - spiral_pressure_level returns correct level from a fresh pressure file
#   - spiral_pressure_level returns 0 when pressure file is stale (>120s old)
#   - spiral_recommended_workers returns empty when no file
#   - spiral_recommended_workers returns value from fresh file
#   - spiral_should_skip_phase returns false (1) when no file
#   - spiral_should_skip_phase returns true (0) when phase is in skip_phases
#   - spiral_pressure_free_mb returns free MB from fresh file

setup() {
  export TMPDIR_MP="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_MP"

  # Provide JQ
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  local SPIRAL_HOME
  SPIRAL_HOME="$(cd "$(dirname "${BATS_TEST_DIRNAME}")/.." && pwd)"

  # Source the library under test
  source "$SPIRAL_HOME/lib/memory-pressure-check.sh"
}

teardown() {
  rm -rf "$TMPDIR_MP"
}

# ── Helper: write a fresh pressure file ──────────────────────────────────────

write_pressure_file() {
  local level="${1:-0}"
  local free_mb="${2:-8192}"
  local workers="${3:-4}"
  local model="${4:-}"
  local skip_phases="${5:-[]}"

  cat > "$_SPIRAL_PRESSURE_FILE" <<EOF
{
  "level": $level,
  "free_mb": $free_mb,
  "recommended_workers": $workers,
  "recommended_model": "${model}",
  "skip_phases": $skip_phases
}
EOF
  # Ensure the file appears fresh (touch to current time)
  touch "$_SPIRAL_PRESSURE_FILE"
}

# ── Test: no pressure file ────────────────────────────────────────────────────

@test "spiral_pressure_level returns 0 when no pressure file exists" {
  rm -f "$_SPIRAL_PRESSURE_FILE"
  run spiral_pressure_level
  [ "$output" = "0" ]
}

@test "spiral_recommended_workers returns empty string when no pressure file" {
  rm -f "$_SPIRAL_PRESSURE_FILE"
  run spiral_recommended_workers
  [ -z "$output" ]
}

@test "spiral_recommended_model returns empty string when no pressure file" {
  rm -f "$_SPIRAL_PRESSURE_FILE"
  run spiral_recommended_model
  [ -z "$output" ]
}

@test "spiral_should_skip_phase returns 1 (do not skip) when no pressure file" {
  rm -f "$_SPIRAL_PRESSURE_FILE"
  run spiral_should_skip_phase "R"
  [ "$status" -eq 1 ]
}

@test "spiral_pressure_free_mb returns empty when no pressure file" {
  rm -f "$_SPIRAL_PRESSURE_FILE"
  run spiral_pressure_free_mb
  [ -z "$output" ]
}

# ── Test: fresh pressure file with level 2 ───────────────────────────────────

@test "spiral_pressure_level returns level from fresh file" {
  write_pressure_file 2 4096 2 "haiku" '[]'
  run spiral_pressure_level
  [ "$output" = "2" ]
}

@test "spiral_pressure_level returns 4 when file has level 4 (high pressure)" {
  write_pressure_file 4 512 1 "haiku" '["R","T"]'
  run spiral_pressure_level
  [ "$output" = "4" ]
}

@test "spiral_pressure_level returns 0 when file has level 0 (no pressure)" {
  write_pressure_file 0 16384 8 "" '[]'
  run spiral_pressure_level
  [ "$output" = "0" ]
}

# ── Test: recommended workers from fresh file ─────────────────────────────────

@test "spiral_recommended_workers returns worker count from fresh file" {
  write_pressure_file 2 4096 3 "sonnet" '[]'
  run spiral_recommended_workers
  [ "$output" = "3" ]
}

@test "spiral_recommended_workers returns empty when recommended_workers is 0" {
  write_pressure_file 1 8192 0 "" '[]'
  run spiral_recommended_workers
  [ -z "$output" ]
}

# ── Test: spiral_should_skip_phase with skip list ────────────────────────────

@test "spiral_should_skip_phase returns 0 (skip) when phase is in skip_phases" {
  write_pressure_file 4 512 1 "haiku" '["R","T"]'
  run spiral_should_skip_phase "R"
  [ "$status" -eq 0 ]
}

@test "spiral_should_skip_phase returns 0 (skip) for second phase in list" {
  write_pressure_file 4 512 1 "haiku" '["R","T"]'
  run spiral_should_skip_phase "T"
  [ "$status" -eq 0 ]
}

@test "spiral_should_skip_phase returns 1 (do not skip) when phase not in list" {
  write_pressure_file 3 1024 2 "haiku" '["R","T"]'
  run spiral_should_skip_phase "I"
  [ "$status" -eq 1 ]
}

@test "spiral_should_skip_phase returns 1 when skip_phases is empty array" {
  write_pressure_file 1 4096 4 "" '[]'
  run spiral_should_skip_phase "R"
  [ "$status" -eq 1 ]
}

# ── Test: free MB from fresh file ────────────────────────────────────────────

@test "spiral_pressure_free_mb returns free MB from fresh file" {
  write_pressure_file 2 2048 2 "sonnet" '[]'
  run spiral_pressure_free_mb
  [ "$output" = "2048" ]
}

# ── Test: stale pressure file (simulate by backdating the file) ───────────────

@test "spiral_pressure_level returns 0 when pressure file is stale (>120s)" {
  write_pressure_file 3 1024 1 "haiku" '["R"]'
  # Backdate the file by 300 seconds to make it stale
  touch -d "300 seconds ago" "$_SPIRAL_PRESSURE_FILE" 2>/dev/null || \
    touch -A "-000500" "$_SPIRAL_PRESSURE_FILE" 2>/dev/null || \
    python3 -c "import os,time; os.utime('$_SPIRAL_PRESSURE_FILE', (time.time()-300, time.time()-300))" 2>/dev/null || \
    true
  # Only run the stale check if we could backdate the file
  local file_age
  local now_ts file_ts
  now_ts=$(date +%s)
  file_ts=$(stat -c %Y "$_SPIRAL_PRESSURE_FILE" 2>/dev/null || stat -f %m "$_SPIRAL_PRESSURE_FILE" 2>/dev/null || echo "$now_ts")
  file_age=$(( now_ts - file_ts ))
  if [[ "$file_age" -gt 120 ]]; then
    run spiral_pressure_level
    [ "$output" = "0" ]
  else
    skip "Could not backdate file to simulate stale state on this platform"
  fi
}

# ── Test: spiral_recommended_model ────────────────────────────────────────────

@test "spiral_recommended_model returns model from fresh file" {
  write_pressure_file 3 1024 1 "haiku" '[]'
  run spiral_recommended_model
  [ "$output" = "haiku" ]
}

@test "spiral_recommended_model returns empty string when model is empty" {
  write_pressure_file 0 16384 8 "" '[]'
  run spiral_recommended_model
  [ -z "$output" ]
}
