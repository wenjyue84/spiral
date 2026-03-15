#!/usr/bin/env bats
# tests/subprocess_injection.bats — Integration tests for US-265 subprocess policy
#
# Run with: tests/bats-core/bin/bats tests/subprocess_injection.bats
#
# Tests verify:
#   - LLM-generated injection strings are not executed by the Python policy
#   - safe_run with shell=False passes metacharacters as literal arguments
#   - SubprocessPolicyViolation is raised (non-zero exit) for blocked executables

setup() {
  export TMPDIR_INJ
  TMPDIR_INJ="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_INJ"
}

teardown() {
  [[ -d "$TMPDIR_INJ" ]] && rm -rf "$TMPDIR_INJ"
}

# ── Helper: run safe_run via inline Python ────────────────────────────────────

_safe_run_py() {
  # Usage: _safe_run_py <phase> <cmd_json_array>
  # cmd_json_array: JSON array string, e.g. '["echo","hello"]'
  local phase="$1"
  local cmd_json="$2"
  python3 - "$phase" "$cmd_json" <<'PYEOF'
import sys, json, os
sys.path.insert(0, '.')
from lib.subprocess_policy import safe_run, SubprocessPolicyViolation
phase = sys.argv[1]
cmd = json.loads(sys.argv[2])
try:
    result = safe_run(cmd, phase=phase, capture_output=True, text=True)
    print(result.stdout, end='')
    sys.exit(result.returncode)
except SubprocessPolicyViolation as e:
    print(f"BLOCKED: {e}", file=sys.stderr)
    sys.exit(2)
except TypeError as e:
    print(f"TYPE_ERROR: {e}", file=sys.stderr)
    sys.exit(3)
PYEOF
}

# ── Test: LLM injection string $(rm -rf /) is not executed ───────────────────

@test "LLM-generated \$(rm -rf /) in argument does not execute the injection" {
  # Create a sentinel file that would be deleted if the injection ran
  SENTINEL="$TMPDIR_INJ/sentinel.txt"
  touch "$SENTINEL"

  # Run echo with the injection string as a literal argument
  run _safe_run_py "global" '["echo","$(rm -rf /)"]'

  # echo should succeed and output the literal string
  [ "$status" -eq 0 ]
  # Sentinel must still exist — injection was NOT executed
  [ -f "$SENTINEL" ]
  # The literal injection string must appear in stdout
  [[ "$output" == *'$(rm -rf /)'* ]]
}

# ── Test: semicolon injection does not fork a second command ─────────────────

@test "semicolon in argument is treated as literal, not as command separator" {
  MARKER="$TMPDIR_INJ/should_not_be_created.txt"

  run _safe_run_py "global" "[\"echo\",\"hello; touch $MARKER\"]"

  [ "$status" -eq 0 ]
  # The marker must NOT have been created
  [ ! -f "$MARKER" ]
  # 'hello' is in the output
  [[ "$output" == *"hello"* ]]
}

# ── Test: pipe metacharacter is literal ──────────────────────────────────────

@test "pipe | in argument is treated as literal string" {
  run _safe_run_py "global" '["echo","hello | cat /etc/passwd"]'

  [ "$status" -eq 0 ]
  [[ "$output" == *"|"* ]]
}

# ── Test: blocked executable in Phase I returns non-zero exit ────────────────

@test "curl blocked in Phase I returns exit code 2 (SubprocessPolicyViolation)" {
  run _safe_run_py "I" '["curl","https://example.com"]'
  [ "$status" -eq 2 ]
}

@test "wget blocked in Phase I returns exit code 2" {
  run _safe_run_py "I" '["wget","https://example.com"]'
  [ "$status" -eq 2 ]
}

@test "bash blocked in Phase I returns exit code 2" {
  run _safe_run_py "I" '["bash","-c","id"]'
  [ "$status" -eq 2 ]
}

@test "sh blocked in Phase I returns exit code 2" {
  run _safe_run_py "I" '["sh","-c","id"]'
  [ "$status" -eq 2 ]
}

# ── Test: allowed executable in Phase I succeeds ─────────────────────────────

@test "git allowed in Phase I succeeds" {
  run _safe_run_py "I" '["git","--version"]'
  [ "$status" -eq 0 ]
}

@test "python3 allowed in Phase I succeeds" {
  run _safe_run_py "I" '["python3","--version"]'
  [ "$status" -eq 0 ]
}

# ── Test: violation is logged to security-audit.jsonl ────────────────────────

@test "blocked command logs SubprocessPolicyViolation to security-audit.jsonl" {
  # Run (will be blocked → exit 2 is expected)
  _safe_run_py "I" '["curl","https://evil.example.com"]' 2>/dev/null || true

  AUDIT_LOG="$TMPDIR_INJ/security-audit.jsonl"
  [ -f "$AUDIT_LOG" ]

  run grep -q "SubprocessPolicyViolation" "$AUDIT_LOG"
  [ "$status" -eq 0 ]
}

@test "audit log entry contains blocked executable name" {
  _safe_run_py "I" '["wget","https://evil.example.com"]' 2>/dev/null || true

  AUDIT_LOG="$TMPDIR_INJ/security-audit.jsonl"
  run grep -q "wget" "$AUDIT_LOG"
  [ "$status" -eq 0 ]
}

# ── Test: string command raises TypeError (exit 3) ───────────────────────────

@test "passing a string instead of list raises TypeError" {
  local tmpscript="$TMPDIR_INJ/test_str_cmd.py"
  cat > "$tmpscript" << 'PYEOF'
import sys
sys.path.insert(0, '.')
from lib.subprocess_policy import safe_run
try:
    safe_run("echo hello", phase="I")
    sys.exit(0)
except TypeError:
    sys.exit(3)
PYEOF
  # run captures exit code in $status without aborting on non-zero
  run python3 "$tmpscript"
  # We expect exit 3 (TypeError raised)
  [ "$status" -eq 3 ]
}
