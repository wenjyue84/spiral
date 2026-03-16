#!/usr/bin/env bats
# tests/stdin_isolation.bats — Verify ralph worker stdin is isolated via /dev/null
#
# Run with: bats tests/stdin_isolation.bats
#
# Tests verify:
#   - A mock worker script that reads stdin receives EOF immediately (<100ms)
#   - The ralph.sh claude invocation contains "< /dev/null" as a stdin redirect

bats_require_minimum_version 1.7.0

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup
  _resolve_jq
  export TMPDIR_SI="$(mktemp -d)"
}

teardown() {
  rm -rf "$TMPDIR_SI"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "stdin_isolation: mock worker reading stdin gets EOF within 100ms" {
  # Write a worker script that reads from stdin and exits 0 on EOF, 1 on timeout
  worker="$TMPDIR_SI/mock_worker.sh"
  result_file="$TMPDIR_SI/result"
  cat > "$worker" << 'EOF'
#!/usr/bin/env bash
# Attempt to read from stdin with a 1-second timeout.
# If stdin is /dev/null, read returns immediately with EOF (exit code 1 from read).
# Write the elapsed time and exit status.
start=$(date +%s%N 2>/dev/null || echo 0)
if read -t 1 line; then
  echo "got_input" > "$1"
else
  echo "eof" > "$1"
fi
end=$(date +%s%N 2>/dev/null || echo 0)
elapsed=$(( (end - start) / 1000000 ))
echo "$elapsed" >> "$1"
EOF
  chmod +x "$worker"

  # Launch worker with stdin redirected from /dev/null (simulating ralph.sh pattern)
  bash "$worker" "$result_file" < /dev/null

  # Verify result: should be "eof" (not "got_input")
  result_line=$(head -1 "$result_file")
  [ "$result_line" = "eof" ]

  # Verify elapsed time < 100ms (stdin EOF must be immediate)
  elapsed_ms=$(tail -1 "$result_file")
  # Fallback: if nanoseconds not available (elapsed=0), skip timing check
  if [ "$elapsed_ms" -gt 0 ] 2>/dev/null; then
    [ "$elapsed_ms" -lt 100 ]
  fi
}

@test "stdin_isolation: ralph.sh contains /dev/null stdin redirect on claude invocation" {
  # Verify the fix is present in the source file
  grep -q '< /dev/null' ralph/ralph.sh
}

@test "stdin_isolation: redirect appears on the main claude worker invocation line" {
  # The redirect must be on the line that pipes into tee + stream-formatter (main worker)
  # This ensures the fix is on the actual worker call, not somewhere unrelated
  grep -A2 'dangerously-skip-permissions' ralph/ralph.sh | grep -q '< /dev/null'
}
