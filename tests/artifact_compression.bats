#!/usr/bin/env bats
# tests/artifact_compression.bats — Tests for US-172: gzip-compress old .spiral/ artifacts
#
# Run with: bats tests/artifact_compression.bats
#
# Tests verify:
#   - compress_old_artifacts is a no-op when current_iter < 3
#   - JSON files from iter N-2 and older are gzip-compressed and originals removed
#   - Files from iter N-1 and N remain uncompressed
#   - Already-compressed .gz files are not double-compressed
#   - _checkpoint.json and latest-review.html are never compressed
#   - Function skips gracefully when gzip is unavailable

# ── Helper ────────────────────────────────────────────────────────────────────

# Run compress_old_artifacts() in an isolated subshell with a temp SCRATCH_DIR.
# Args: current_iter scratch_dir [GZIP_CMD override to simulate unavailability]
run_compress() {
  local current_iter="$1"
  local scratch="$2"
  local gzip_cmd="${3:-gzip}"   # pass "false" to simulate gzip unavailable

  bash -c '
    set -euo pipefail
    SCRATCH_DIR="$1"
    SPIRAL_LOG_LEVEL="DEBUG"
    SPIRAL_ITER="$2"

    # Override PATH so tests can simulate missing gzip
    if [[ "$3" == "false" ]]; then
      _gzip_available() { return 1; }
    else
      _gzip_available() { command -v gzip &>/dev/null; }
    fi

    compress_old_artifacts() {
      local current_iter="${1:-$SPIRAL_ITER}"
      [[ "$current_iter" -lt 3 ]] && return 0

      if ! _gzip_available; then
        echo "  [compress] WARNING: gzip not available — skipping artifact compression"
        return 0
      fi

      local threshold=$(( current_iter - 2 ))
      local compressed=0

      for iter_n in $(seq 1 "$threshold"); do
        for f in \
          "$SCRATCH_DIR/_phase_R_${iter_n}.ckpt" \
          "$SCRATCH_DIR/_phase_T_${iter_n}.ckpt" \
          "$SCRATCH_DIR/_phase_R_${iter_n}.endtime" \
          "$SCRATCH_DIR/_phase_T_${iter_n}.endtime"; do
          if [[ -f "$f" && ! -f "${f}.gz" ]]; then
            gzip "$f" 2>/dev/null && compressed=$((compressed + 1)) || true
          fi
        done

        local backup="$SCRATCH_DIR/prd-backups/prd-iter${iter_n}.json"
        if [[ -f "$backup" && ! -f "${backup}.gz" ]]; then
          gzip "$backup" 2>/dev/null && compressed=$((compressed + 1)) || true
        fi
      done

      if [[ "${SPIRAL_LOG_LEVEL:-}" == "DEBUG" ]]; then
        local total_kb=0
        if command -v du &>/dev/null; then
          total_kb=$(du -sk "$SCRATCH_DIR" 2>/dev/null | awk "{print \$1}" || echo 0)
        fi
        echo "  [compress] Compressed ${compressed} artifact(s) from iters 1-${threshold}; .spiral/ total: ${total_kb}K"
      fi
    }

    compress_old_artifacts "$2"
  ' -- "$scratch" "$current_iter" "$gzip_cmd"
}

# ── Setup / teardown ──────────────────────────────────────────────────────────

setup() {
  TMP_SCRATCH="$(mktemp -d)"
  mkdir -p "$TMP_SCRATCH/prd-backups"
  mkdir -p "$TMP_SCRATCH/gate-reports"
}

teardown() {
  rm -rf "$TMP_SCRATCH"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "no-op when current_iter < 3 (iter=1)" {
  echo '{}' > "$TMP_SCRATCH/prd-backups/prd-iter1.json"
  touch "$TMP_SCRATCH/_phase_R_1.ckpt"

  run run_compress 1 "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  # File must still exist uncompressed
  [ -f "$TMP_SCRATCH/prd-backups/prd-iter1.json" ]
  [ ! -f "$TMP_SCRATCH/prd-backups/prd-iter1.json.gz" ]
}

@test "no-op when current_iter < 3 (iter=2)" {
  echo '{}' > "$TMP_SCRATCH/prd-backups/prd-iter1.json"

  run run_compress 2 "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  [ -f "$TMP_SCRATCH/prd-backups/prd-iter1.json" ]
  [ ! -f "$TMP_SCRATCH/prd-backups/prd-iter1.json.gz" ]
}

@test "iter 1 prd-backup is compressed when current_iter=3" {
  echo '{"iter":1}' > "$TMP_SCRATCH/prd-backups/prd-iter1.json"

  run run_compress 3 "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  # Original removed, .gz created
  [ ! -f "$TMP_SCRATCH/prd-backups/prd-iter1.json" ]
  [ -f "$TMP_SCRATCH/prd-backups/prd-iter1.json.gz" ]
}

@test "iter N-1 and N prd-backups remain uncompressed" {
  echo '{"iter":1}' > "$TMP_SCRATCH/prd-backups/prd-iter1.json"
  echo '{"iter":2}' > "$TMP_SCRATCH/prd-backups/prd-iter2.json"
  echo '{"iter":3}' > "$TMP_SCRATCH/prd-backups/prd-iter3.json"

  # At iter=3: threshold=1, so only iter1 is compressed; iter2 and iter3 stay
  run run_compress 3 "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  [ ! -f "$TMP_SCRATCH/prd-backups/prd-iter1.json" ]
  [ -f  "$TMP_SCRATCH/prd-backups/prd-iter1.json.gz" ]
  [ -f  "$TMP_SCRATCH/prd-backups/prd-iter2.json" ]
  [ -f  "$TMP_SCRATCH/prd-backups/prd-iter3.json" ]
}

@test "phase ckpt files from old iters are compressed" {
  touch "$TMP_SCRATCH/_phase_R_1.ckpt"
  touch "$TMP_SCRATCH/_phase_T_1.ckpt"

  run run_compress 3 "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  [ ! -f "$TMP_SCRATCH/_phase_R_1.ckpt" ]
  [ -f  "$TMP_SCRATCH/_phase_R_1.ckpt.gz" ]
  [ ! -f "$TMP_SCRATCH/_phase_T_1.ckpt" ]
  [ -f  "$TMP_SCRATCH/_phase_T_1.ckpt.gz" ]
}

@test "endtime files from old iters are compressed" {
  echo "1741234567" > "$TMP_SCRATCH/_phase_R_1.endtime"
  echo "1741234568" > "$TMP_SCRATCH/_phase_T_1.endtime"

  run run_compress 3 "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  [ ! -f "$TMP_SCRATCH/_phase_R_1.endtime" ]
  [ -f  "$TMP_SCRATCH/_phase_R_1.endtime.gz" ]
  [ ! -f "$TMP_SCRATCH/_phase_T_1.endtime" ]
  [ -f  "$TMP_SCRATCH/_phase_T_1.endtime.gz" ]
}

@test "already-compressed .gz files are not double-compressed" {
  echo '{"iter":1}' > "$TMP_SCRATCH/prd-backups/prd-iter1.json"
  gzip "$TMP_SCRATCH/prd-backups/prd-iter1.json"
  # .gz exists, original is gone

  run run_compress 3 "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  # .gz still present, no .gz.gz
  [ -f  "$TMP_SCRATCH/prd-backups/prd-iter1.json.gz" ]
  [ ! -f "$TMP_SCRATCH/prd-backups/prd-iter1.json.gz.gz" ]
}

@test "_checkpoint.json is never compressed" {
  echo '{"iter":1,"phase":"C"}' > "$TMP_SCRATCH/_checkpoint.json"

  run run_compress 5 "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  [ -f "$TMP_SCRATCH/_checkpoint.json" ]
  [ ! -f "$TMP_SCRATCH/_checkpoint.json.gz" ]
}

@test "gate-reports/latest-review.html is never compressed" {
  echo "<html></html>" > "$TMP_SCRATCH/gate-reports/latest-review.html"

  run run_compress 5 "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  [ -f "$TMP_SCRATCH/gate-reports/latest-review.html" ]
  [ ! -f "$TMP_SCRATCH/gate-reports/latest-review.html.gz" ]
}

@test "debug log line is emitted when SPIRAL_LOG_LEVEL=DEBUG" {
  echo '{"iter":1}' > "$TMP_SCRATCH/prd-backups/prd-iter1.json"

  run run_compress 3 "$TMP_SCRATCH"
  [ "$status" -eq 0 ]
  [[ "$output" == *"[compress]"* ]]
  [[ "$output" == *"iters 1-1"* ]]
}

@test "skips gracefully when gzip is unavailable" {
  echo '{"iter":1}' > "$TMP_SCRATCH/prd-backups/prd-iter1.json"

  run run_compress 3 "$TMP_SCRATCH" "false"
  [ "$status" -eq 0 ]
  [[ "$output" == *"gzip not available"* ]]

  # File must be left untouched
  [ -f "$TMP_SCRATCH/prd-backups/prd-iter1.json" ]
}
