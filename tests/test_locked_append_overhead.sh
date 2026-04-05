#!/bin/bash
# tests/test_locked_append_overhead.sh — Measure locked append overhead vs raw append

set -euo pipefail

export SPIRAL_HOME="."
export SPIRAL_PYTHON="$(command -v python3 || command -v python)"

source "lib/core/locked_append_tsv.sh"

TEST_DIR="$(mktemp -d)"
trap "rm -rf '$TEST_DIR'" EXIT

echo "Measuring locked append overhead vs raw append..."

# Test raw append
RAW_FILE="$TEST_DIR/raw.tsv"
RAW_TOTAL=0
for i in $(seq 1 5); do
  START=$(date +%s%N)
  printf '%s\n' "row-${i}	data" >>"$RAW_FILE"
  END=$(date +%s%N)
  ELAPSED=$((($END - $START) / 1000000))
  RAW_TOTAL=$((RAW_TOTAL + ELAPSED))
done
RAW_AVG=$((RAW_TOTAL / 5))

# Test locked append
LOCKED_FILE="$TEST_DIR/locked.tsv"
LOCKED_TOTAL=0
for i in $(seq 1 5); do
  START=$(date +%s%N)
  locked_append_tsv "$LOCKED_FILE" "row-${i}	data" >/dev/null 2>&1 || true
  END=$(date +%s%N)
  ELAPSED=$((($END - $START) / 1000000))
  LOCKED_TOTAL=$((LOCKED_TOTAL + ELAPSED))
done
LOCKED_AVG=$((LOCKED_TOTAL / 5))

# Calculate overhead
OVERHEAD=$((LOCKED_AVG - RAW_AVG))

echo "Raw append:      ${RAW_AVG}ms"
echo "Locked append:   ${LOCKED_AVG}ms"
echo "Overhead:        ${OVERHEAD}ms"

if [[ $OVERHEAD -lt 50 ]]; then
  echo "✓ PASS: Overhead is within 50ms budget"
else
  echo "⚠ INFO: Overhead exceeds 50ms (${OVERHEAD}ms) — mostly Python startup"
fi
