#!/bin/bash
# tests/test_locked_append_tsv.sh — Test locked TSV appending with concurrent writers
#
# Verifies that the locked_append_tsv helper prevents corruption when multiple
# processes append to the same TSV file simultaneously.

set -euo pipefail

# Setup environment for locked_append_tsv helper
export SPIRAL_HOME="."
export SPIRAL_PYTHON="$(command -v python3 || command -v python)"

# Source the locked_append_tsv helper
source "lib/core/locked_append_tsv.sh"

TEST_DIR="$(mktemp -d)"
TEST_TSV="$TEST_DIR/test_results.tsv"
trap "rm -rf '$TEST_DIR'" EXIT

echo "Testing locked_append_tsv..."

# Test 1: Single append succeeds
locked_append_tsv "$TEST_TSV" "col1	col2	col3"
if [[ ! -f "$TEST_TSV" ]]; then
  echo "FAIL: File not created"
  exit 1
fi
if ! grep -q "col1	col2	col3" "$TEST_TSV"; then
  echo "FAIL: First row not appended correctly"
  exit 1
fi
echo "✓ Test 1: Single append succeeds"

# Test 2: Multiple sequential appends preserve all rows
locked_append_tsv "$TEST_TSV" "row2	val2	data2"
locked_append_tsv "$TEST_TSV" "row3	val3	data3"
LINES=$(wc -l <"$TEST_TSV" | tr -d ' ')
if [[ "$LINES" -ne 3 ]]; then
  echo "FAIL: Expected 3 lines, got $LINES"
  cat "$TEST_TSV"
  exit 1
fi
echo "✓ Test 2: Multiple sequential appends work"

# Test 3: Concurrent appends from multiple workers (simulated with background jobs)
rm -f "$TEST_TSV"
echo "Testing concurrent appends (3 workers × 5 rows each)..."
for worker in 1 2 3; do
  (
    for row in 1 2 3 4 5; do
      _row_data="worker-${worker}	row-${row}	data-${row}"
      locked_append_tsv "$TEST_TSV" "$_row_data"
      sleep 0.01  # Simulate work
    done
  ) &
done
wait
# Should have exactly 15 rows (3 workers × 5 rows)
FINAL_LINES=$(wc -l <"$TEST_TSV" | tr -d ' ')
if [[ "$FINAL_LINES" -ne 15 ]]; then
  echo "FAIL: Expected 15 rows, got $FINAL_LINES"
  echo "Contents:"
  cat "$TEST_TSV"
  exit 1
fi
# Verify no garbled lines (all lines should have exactly 2 tabs)
GARBLED=$(grep -cv '	.*	' "$TEST_TSV" || true)
if [[ "$GARBLED" -ne 0 ]]; then
  echo "FAIL: Found $GARBLED garbled lines (expected 0)"
  cat "$TEST_TSV"
  exit 1
fi
echo "✓ Test 3: Concurrent appends produce clean TSV (15 lines, no corruption)"

echo ""
echo "All tests passed!"
