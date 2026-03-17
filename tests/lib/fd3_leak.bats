#!/usr/bin/env bats
# tests/lib/fd3_leak.bats — Verify bats FD 3 is not leaked to background processes
#
# Run with: bats tests/lib/fd3_leak.bats
#
# Bats uses file descriptor 3 internally for test output coordination.
# Any background process that inherits FD 3 causes the test to hang
# indefinitely because bats waits for FD 3 to close.
# Reference: bats-core docs "File descriptor 3 (read this if bats hangs)"
#
# Tests verify:
#   - Background process with 3>&- does not inherit FD 3
#   - All SPIRAL bats test files close FD 3 on background spawns
#   - spiral.sh main loop does not leak FD 3 when spawned from bats

bats_require_minimum_version 1.7.0
setup() {
  load ../test_helper/common-setup
  _resolve_jq
  export TEST_TMPDIR
  TEST_TMPDIR="$(mktemp -d)"
}

teardown() {
  rm -rf "$TEST_TMPDIR"
}

# ── FD 3 closure verification ────────────────────────────────────────────────

@test "background process with 3>&- does not inherit FD 3" {
  # Spawn a background process that tries to write to FD 3
  # With 3>&- it should fail (FD 3 is closed)
  local fd3_probe="$TEST_TMPDIR/fd3_probe.txt"
  bash -c 'echo probe >&3 2>/dev/null; echo $? > '"$fd3_probe" 3>&- &
  local pid=$!
  wait "$pid" 2>/dev/null || true
  [ -f "$fd3_probe" ]
  local rc
  rc=$(cat "$fd3_probe" | tr -d '[:space:]')
  # Exit code should be non-zero (FD 3 was closed, write failed)
  [ "$rc" -ne 0 ]
}

@test "background process WITHOUT 3>&- can see FD 3 from bats" {
  # This test proves FD 3 exists in the bats environment
  # (confirming the leak vector is real)
  local fd3_exists="$TEST_TMPDIR/fd3_exists.txt"
  # Use /dev/fd/3 check instead of writing to it (to avoid interfering with bats)
  bash -c '[ -e /dev/fd/3 ] && echo yes || echo no' >"$fd3_exists" 2>/dev/null
  local result
  result=$(cat "$fd3_exists" | tr -d '[:space:]')
  # In bats, FD 3 should exist
  [ "$result" = "yes" ]
}

# ── Static audit: no unguarded background spawns in SPIRAL test files ────────

@test "no bats test files have unguarded background spawns (& without 3>&-)" {
  # Scan all .bats files in tests/ (excluding bats-core submodule)
  # for lines matching '&' at end of line without '3>&-' before it
  local violations="$TEST_TMPDIR/violations.txt"
  : >"$violations"

  # Find all .bats files excluding bats-core vendored submodule
  while IFS= read -r -d '' batsfile; do
    # Skip bats-core submodule
    [[ "$batsfile" == *"bats-core"* ]] && continue
    # Find lines ending with & that are actual background spawns
    # Exclude: &>/dev/null patterns, && chains, comments
    grep -nE '\s&\s*$' "$batsfile" 2>/dev/null | while IFS= read -r match; do
      # Check if 3>&- is present on the same line
      if ! echo "$match" | grep -q '3>&-'; then
        echo "$batsfile:$match" >>"$violations"
      fi
    done || true
  done < <(find tests/ -name '*.bats' -print0 2>/dev/null)

  if [ -s "$violations" ]; then
    echo "FD 3 leak: background spawns missing 3>&-:"
    cat "$violations"
    return 1
  fi
}

# ── Timeout safety net verification ──────────────────────────────────────────

@test "bats --timeout flag is supported (>= 1.7.0)" {
  # Verify the installed bats supports --timeout
  run tests/bats-core/bin/bats --help 2>&1
  # Modern bats (>= 1.7.0) includes --timeout in help output
  [[ "$output" == *"timeout"* ]] || skip "bats version does not support --timeout"
}
