#!/usr/bin/env bats
# tests/security_scan.bats — Unit tests for run_security_scan() in ralph/ralph.sh
#
# Run with: bats tests/security_scan.bats
#
# Tests verify:
#   - SPIRAL_SECURITY_SCAN=false (default) → no-op, returns 0
#   - Scanner binary not found → skips with warning, returns 0
#   - No staged files → skips, returns 0
#   - Semgrep HIGH findings → returns 1 (fail)
#   - Semgrep MEDIUM-only findings → returns 0 (warning only)
#   - Semgrep clean → returns 0 (pass)
#   - SPIRAL_SECURITY_SCAN_TOOL=bandit → uses bandit parsing path
#   - Bandit HIGH findings → returns 1

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_SS
  TMPDIR_SS="$(mktemp -d)"

  export SPIRAL_SCRATCH_DIR="$TMPDIR_SS"
  export PRD_FILE="$TMPDIR_SS/prd.json"
  export PROGRESS_FILE="$TMPDIR_SS/progress.txt"
  export NEXT_STORY="US-TEST"
  export SPIRAL_SECURITY_SCAN="true"
  export SPIRAL_SECURITY_SCAN_TOOL="semgrep"
  export SPIRAL_SECURITY_SCAN_ARGS=""

  touch "$PROGRESS_FILE"

  # Resolve jq binary (same logic as other bats tests)
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Stub log_ralph_event to avoid real file writes
  log_ralph_event() {
    printf '%s %s\n' "$1" "${2:-}" >> "$TMPDIR_SS/events.log"
  }
  export -f log_ralph_event

  # Default git stub: returns one staged file (tests override as needed)
  git() {
    if [[ "$*" == *"--cached --name-only"* ]]; then
      echo "src/main.py"
    fi
  }
  export -f git

  # Source run_security_scan from ralph.sh
  source <(sed -n '/^run_security_scan()/,/^}/p' ralph/ralph.sh)
}

teardown() {
  rm -rf "$TMPDIR_SS"
  unset NEXT_STORY SPIRAL_SECURITY_SCAN SPIRAL_SECURITY_SCAN_TOOL SPIRAL_SECURITY_SCAN_ARGS
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "SPIRAL_SECURITY_SCAN=false: no-op, returns 0" {
  export SPIRAL_SECURITY_SCAN="false"
  run run_security_scan
  [ "$status" -eq 0 ]
}

@test "SPIRAL_SECURITY_SCAN unset: no-op, returns 0" {
  unset SPIRAL_SECURITY_SCAN
  run run_security_scan
  [ "$status" -eq 0 ]
}

@test "semgrep not found: skips with warning, returns 0" {
  # Override PATH so semgrep is not found
  semgrep() { return 127; }
  command() {
    if [[ "$*" == *"semgrep"* ]]; then return 1; fi
    builtin command "$@"
  }
  export -f semgrep command
  run run_security_scan
  [ "$status" -eq 0 ]
  [[ "$output" == *"not found"* ]]
}

@test "bandit not found: skips with warning, returns 0" {
  export SPIRAL_SECURITY_SCAN_TOOL="bandit"
  bandit() { return 127; }
  command() {
    if [[ "$*" == *"bandit"* ]]; then return 1; fi
    builtin command "$@"
  }
  export -f bandit command
  run run_security_scan
  [ "$status" -eq 0 ]
  [[ "$output" == *"not found"* ]]
}

@test "no staged files: skips, returns 0" {
  git() {
    if [[ "$*" == *"--cached --name-only"* ]]; then
      echo ""
    fi
  }
  export -f git
  run run_security_scan
  [ "$status" -eq 0 ]
  [[ "$output" == *"No staged files"* ]]
}

@test "semgrep: HIGH finding fails the scan (returns 1)" {
  local report_path="$TMPDIR_SS/security_scan_US-TEST.json"
  semgrep() {
    # Write HIGH-severity semgrep JSON output
    cat > "$report_path" <<'JSON'
{"results":[{"check_id":"r1","path":"src/main.py","extra":{"severity":"ERROR","message":"SQL injection"}}],"errors":[]}
JSON
    return 1
  }
  command() {
    if [[ "$*" == *"semgrep"* ]]; then return 0; fi
    builtin command "$@"
  }
  export -f semgrep command
  run run_security_scan
  [ "$status" -eq 1 ]
  [[ "$output" == *"FAILED"* ]]
}

@test "semgrep: MEDIUM-only findings returns 0 (warning only)" {
  local report_path="$TMPDIR_SS/security_scan_US-TEST.json"
  semgrep() {
    cat > "$report_path" <<'JSON'
{"results":[{"check_id":"r1","path":"src/main.py","extra":{"severity":"WARNING","message":"Hardcoded password"}}],"errors":[]}
JSON
    return 0
  }
  command() {
    if [[ "$*" == *"semgrep"* ]]; then return 0; fi
    builtin command "$@"
  }
  export -f semgrep command
  run run_security_scan
  [ "$status" -eq 0 ]
  [[ "$output" == *"WARNING"* ]]
}

@test "semgrep: no findings returns 0 (passed)" {
  local report_path="$TMPDIR_SS/security_scan_US-TEST.json"
  semgrep() {
    cat > "$report_path" <<'JSON'
{"results":[],"errors":[]}
JSON
    return 0
  }
  command() {
    if [[ "$*" == *"semgrep"* ]]; then return 0; fi
    builtin command "$@"
  }
  export -f semgrep command
  run run_security_scan
  [ "$status" -eq 0 ]
  [[ "$output" == *"Passed"* ]]
}

@test "semgrep: report written to SPIRAL_SCRATCH_DIR/security_scan_STORY_ID.json" {
  local report_path="$TMPDIR_SS/security_scan_US-TEST.json"
  semgrep() {
    cat > "$report_path" <<'JSON'
{"results":[],"errors":[]}
JSON
    return 0
  }
  command() {
    if [[ "$*" == *"semgrep"* ]]; then return 0; fi
    builtin command "$@"
  }
  export -f semgrep command
  run_security_scan
  [ -f "$report_path" ]
}

@test "bandit: HIGH finding fails the scan (returns 1)" {
  export SPIRAL_SECURITY_SCAN_TOOL="bandit"
  local report_path="$TMPDIR_SS/security_scan_US-TEST.json"
  # Stage a Python file
  git() {
    if [[ "$*" == *"--cached --name-only"* ]]; then
      echo "src/main.py"
    fi
  }
  export -f git
  bandit() {
    cat > "$report_path" <<'JSON'
{"results":[{"test_id":"B608","issue_text":"SQL injection","issue_severity":"HIGH","issue_confidence":"HIGH","filename":"src/main.py","line_number":10}],"errors":[]}
JSON
    return 1
  }
  command() {
    if [[ "$*" == *"bandit"* ]]; then return 0; fi
    builtin command "$@"
  }
  export -f bandit command
  run run_security_scan
  [ "$status" -eq 1 ]
  [[ "$output" == *"FAILED"* ]]
}
