#!/usr/bin/env bash
# lib/flaky_tests.sh — Flaky bats test detection and quarantine registry (US-240)
#
# Tracks per-test pass/fail history across gate runs in .spiral/flaky-tests.json.
# Tests exceeding SPIRAL_FLAKY_THRESHOLD are quarantined (failures still execute
# but do not cause the Gate phase to fail). Quarantine lifts after N consecutive
# passes (default 10, configurable via SPIRAL_FLAKY_CONSEC).
#
# Functions exported:
#   flaky_record_result  <test_name> <"pass"|"fail">
#   flaky_is_quarantined <test_name>   — returns 0 if quarantined, 1 otherwise
#   flaky_report                       — prints all quarantined tests + failure rates
#   flaky_gate_exit_code <test_name> <exit_code>   — returns 0 for quarantined tests
#   flaky_list_quarantined             — prints quarantined test names (one per line)
#
# Registry: ${SPIRAL_SCRATCH_DIR:-.spiral}/flaky-tests.json
# Config:
#   SPIRAL_FLAKY_THRESHOLD  — failure ratio above which a test is quarantined (default: 0.3)
#   SPIRAL_FLAKY_WINDOW     — number of recent runs to consider (default: 20)
#   SPIRAL_FLAKY_CONSEC     — consecutive passes required to lift quarantine (default: 10)

# ── Internal helpers ──────────────────────────────────────────────────────────

_flaky_registry_path() {
  local scratch_dir="${SPIRAL_SCRATCH_DIR:-.spiral}"
  echo "${scratch_dir}/flaky-tests.json"
}

# Python helper script path (written to a temp file on first use)
_FLAKY_PY_HELPER=""

# Write the Python helper to a temp file (only once per process)
_flaky_ensure_py_helper() {
  if [[ -n "$_FLAKY_PY_HELPER" && -f "$_FLAKY_PY_HELPER" ]]; then
    return 0
  fi
  _FLAKY_PY_HELPER=$(mktemp /tmp/flaky_helper_XXXXXX.py)
  cat > "$_FLAKY_PY_HELPER" <<'PYEOF'
#!/usr/bin/env python3
"""
Flaky test registry helper.

Usage:
  python3 flaky_helper.py record <registry_file> <test_name> <pass|fail> <threshold> <window> <consec>
  python3 flaky_helper.py is_quarantined <registry_file> <test_name>
  python3 flaky_helper.py list_quarantined <registry_file>
  python3 flaky_helper.py report <registry_file>
"""

import json, sys, os, tempfile, shutil
from datetime import datetime, timezone

def _load(registry_file):
    if os.path.isfile(registry_file):
        try:
            with open(registry_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save(registry_file, registry):
    d = os.path.dirname(registry_file)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = registry_file + ".tmp." + str(os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    shutil.move(tmp, registry_file)

def cmd_record(registry_file, test_name, result, threshold, window, consec_target):
    """Record a pass or fail for test_name."""
    registry = _load(registry_file)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result_val = 1 if result == "pass" else 0

    entry = registry.get(test_name, {
        "passes": 0, "failures": 0, "quarantined": False,
        "lastSeen": ts, "history": [], "consecutivePasses": 0,
    })

    history = entry.get("history", [])
    history.append(result_val)
    if len(history) > window:
        history = history[-window:]

    passes = sum(history)
    failures = len(history) - passes
    total = len(history)

    # Update consecutive pass counter
    consec = (entry.get("consecutivePasses", 0) + 1) if result_val == 1 else 0

    quarantined = entry.get("quarantined", False)

    # Lift quarantine after N consecutive passes (takes precedence over re-quarantine)
    if quarantined and consec >= consec_target:
        quarantined = False
        # Reset history to only the recent consecutive passes to avoid immediate re-quarantine
        history = [1] * min(consec, window)
        passes = len(history)
        failures = 0
        total = len(history)
    elif not quarantined and total >= 5:
        # Only quarantine if not already quarantined and enough samples
        ratio = failures / total
        if ratio > threshold:
            quarantined = True

    entry["passes"] = passes
    entry["failures"] = failures
    entry["quarantined"] = quarantined
    entry["lastSeen"] = ts
    entry["history"] = history
    entry["consecutivePasses"] = consec

    registry[test_name] = entry
    _save(registry_file, registry)

def cmd_is_quarantined(registry_file, test_name):
    """Print 'true' or 'false'."""
    registry = _load(registry_file)
    entry = registry.get(test_name, {})
    print("true" if entry.get("quarantined", False) else "false")

def cmd_list_quarantined(registry_file):
    """Print quarantined test names, one per line."""
    registry = _load(registry_file)
    for name, entry in sorted(registry.items()):
        if entry.get("quarantined", False):
            print(name)

def cmd_report(registry_file):
    """Print human-readable report."""
    import sys, io
    # Force UTF-8 output on Windows to avoid cp1252 encoding errors
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    registry = _load(registry_file)
    quarantined = {k: v for k, v in registry.items() if v.get("quarantined", False)}

    print()
    print("  +------------------------------------------------------+")
    print("  |  Flaky Test Registry Report                          |")
    print("  +------------------------------------------------------+")
    print()
    print(f"  Total tracked tests : {len(registry)}")
    print(f"  Quarantined tests   : {len(quarantined)}")
    print()

    if not quarantined:
        print("  No quarantined tests.")
    else:
        print("  Quarantined tests (failures do NOT block gate):")
        print()
        for name, entry in sorted(quarantined.items()):
            total = entry.get("passes", 0) + entry.get("failures", 0)
            failures = entry.get("failures", 0)
            ratio = failures / total if total > 0 else 0.0
            consec = entry.get("consecutivePasses", 0)
            last_seen = entry.get("lastSeen", "unknown")
            print(f"  [QUARANTINED] {name}")
            print(f"      failure rate : {ratio:.1%}  ({failures}/{total} runs)")
            print(f"      consecutive passes : {consec}")
            print(f"      last seen : {last_seen[:19]}")
            print()

    not_quarantined_flaky = [
        (k, v) for k, v in sorted(registry.items())
        if not v.get("quarantined", False) and v.get("failures", 0) > 0
    ]
    if not_quarantined_flaky:
        print("  Watched tests (not yet quarantined):")
        for name, entry in not_quarantined_flaky:
            total = entry.get("passes", 0) + entry.get("failures", 0)
            failures = entry.get("failures", 0)
            ratio = failures / total if total > 0 else 0.0
            print(f"  ~ {name}  ({ratio:.1%} failure rate, {failures}/{total} runs)")
        print()

if __name__ == "__main__":
    cmd = sys.argv[1]
    reg_file = sys.argv[2]

    if cmd == "record":
        test_name = sys.argv[3]
        result = sys.argv[4]
        threshold = float(sys.argv[5])
        window = int(sys.argv[6])
        consec = int(sys.argv[7])
        cmd_record(reg_file, test_name, result, threshold, window, consec)
    elif cmd == "is_quarantined":
        test_name = sys.argv[3]
        cmd_is_quarantined(reg_file, test_name)
    elif cmd == "list_quarantined":
        cmd_list_quarantined(reg_file)
    elif cmd == "report":
        cmd_report(reg_file)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
PYEOF
}

# ── flaky_record_result ───────────────────────────────────────────────────────
# Record a single pass or fail for a test name.
#
# Args:
#   $1  test_name    string identifier for the test
#   $2  result       "pass" or "fail"
flaky_record_result() {
  local test_name="$1"
  local result="$2"
  local threshold="${SPIRAL_FLAKY_THRESHOLD:-0.3}"
  local window="${SPIRAL_FLAKY_WINDOW:-20}"
  local consec_target="${SPIRAL_FLAKY_CONSEC:-10}"
  local reg_path
  reg_path="$(_flaky_registry_path)"

  _flaky_ensure_py_helper
  python3 "$_FLAKY_PY_HELPER" record "$reg_path" "$test_name" "$result" \
    "$threshold" "$window" "$consec_target"
}

# ── flaky_is_quarantined ──────────────────────────────────────────────────────
# Returns 0 (true in bash) if the test is currently quarantined.
#
# Args:
#   $1  test_name
flaky_is_quarantined() {
  local test_name="$1"
  local reg_path
  reg_path="$(_flaky_registry_path)"

  _flaky_ensure_py_helper
  local result
  result=$(python3 "$_FLAKY_PY_HELPER" is_quarantined "$reg_path" "$test_name" 2>/dev/null)
  [[ "$result" == "true" ]]
}

# ── flaky_gate_exit_code ──────────────────────────────────────────────────────
# Given a test name and its original exit code, returns 0 if the test is
# quarantined (so its failure does not block the gate) or the original exit
# code otherwise.
#
# Args:
#   $1  test_name
#   $2  exit_code   (original exit code from the test runner)
flaky_gate_exit_code() {
  local test_name="$1"
  local exit_code="$2"

  if [[ "$exit_code" -ne 0 ]] && flaky_is_quarantined "$test_name"; then
    echo 0
  else
    echo "$exit_code"
  fi
}

# ── flaky_report ──────────────────────────────────────────────────────────────
# Print a human-readable report of all quarantined tests and their failure rates.
flaky_report() {
  local reg_path
  reg_path="$(_flaky_registry_path)"

  _flaky_ensure_py_helper
  python3 "$_FLAKY_PY_HELPER" report "$reg_path"
}

# ── flaky_list_quarantined ────────────────────────────────────────────────────
# Print each quarantined test name on its own line (machine-readable).
flaky_list_quarantined() {
  local reg_path
  reg_path="$(_flaky_registry_path)"

  _flaky_ensure_py_helper
  python3 "$_FLAKY_PY_HELPER" list_quarantined "$reg_path"
}
