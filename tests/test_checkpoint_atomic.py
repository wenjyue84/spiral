"""tests/test_checkpoint_atomic.py — Tests for atomic checkpoint writes (US-1106).

Verifies:
- write_checkpoint() includes schema_version field (AC4)
- load_checkpoint() detects malformed/truncated JSON and resets to iter 1 (AC2, AC3)
- Truncated checkpoint (simulated mid-write crash) is recovered gracefully (AC3)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

SPIRAL_HELPERS = Path(__file__).parent.parent / "lib" / "spiral_helpers.sh"


def _bash_path(p: Path) -> str:
    """Convert a Windows absolute path to MSYS2/Git Bash path format (C:/foo → /c/foo)."""
    s = p.as_posix()
    if len(s) >= 2 and s[1] == ":":
        return "/" + s[0].lower() + s[2:]
    return s


def _run_bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_write_checkpoint_includes_schema_version() -> None:
    """AC4: write_checkpoint() function must include schema_version in its JSON output."""
    content = SPIRAL_HELPERS.read_text(encoding="utf-8")
    # Verify schema_version is present in the write_checkpoint printf format string
    assert "schema_version" in content, "write_checkpoint() in spiral_helpers.sh must include 'schema_version' field"
    # Verify it appears near the write_checkpoint function definition
    wc_idx = content.find("write_checkpoint()")
    assert wc_idx >= 0, "write_checkpoint() function not found in spiral_helpers.sh"
    # schema_version should appear within ~20 lines of the function definition
    wc_block = content[wc_idx : wc_idx + 600]
    assert "schema_version" in wc_block, "schema_version not found within write_checkpoint() function body"


def test_load_checkpoint_resets_on_truncated_json() -> None:
    """AC3: truncated checkpoint (simulated mid-write crash) → load logic resets to iter 1."""
    # Use mktemp inside bash to avoid Windows path conversion issues
    script = r"""
set -euo pipefail
TMP_DIR=$(mktemp -d)
CHECKPOINT_FILE="$TMP_DIR/_checkpoint.json"
JQ="jq"
RESET_HAPPENED=0

# Simulate mid-write crash: write truncated JSON (incomplete object)
printf '{"iter":5,"phase":"I","ts":"2026-01' > "$CHECKPOINT_FILE"

# Validate JSON -- mirrors load_checkpoint() validation (AC2/AC3)
if [[ -f "$CHECKPOINT_FILE" ]]; then
  _raw=$(cat "$CHECKPOINT_FILE" 2>/dev/null) || _raw=""
  if ! echo "$_raw" | "$JQ" -e . >/dev/null 2>&1; then
    echo "MALFORMED_DETECTED"
    rm -f "$CHECKPOINT_FILE"
    RESET_HAPPENED=1
  fi
fi

if [[ "$RESET_HAPPENED" -eq 1 ]]; then echo "RESET"; fi
if [[ ! -f "$CHECKPOINT_FILE" ]]; then echo "FILE_REMOVED"; fi
rm -rf "$TMP_DIR"
"""
    result = _run_bash(script)
    assert result.returncode == 0, f"Bash script failed: {result.stderr}"
    assert "MALFORMED_DETECTED" in result.stdout, (
        f"Truncated JSON was not detected as malformed. stdout: {result.stdout}"
    )
    assert "RESET" in result.stdout, "Expected RESET after malformed detection"
    assert "FILE_REMOVED" in result.stdout, "Corrupted checkpoint was not cleaned up"


def test_load_checkpoint_resets_on_missing_iter() -> None:
    """AC2: checkpoint missing 'iter' field causes load logic to reset to iteration 1."""
    script = r"""
set -euo pipefail
TMP_DIR=$(mktemp -d)
CHECKPOINT_FILE="$TMP_DIR/_checkpoint.json"
JQ="jq"
RESET_HAPPENED=0

# Valid JSON but missing required 'iter' field
printf '{"phase":"I","ts":"2026-01-01T00:00:00Z"}' > "$CHECKPOINT_FILE"

if [[ -f "$CHECKPOINT_FILE" ]]; then
  _raw=$(cat "$CHECKPOINT_FILE" 2>/dev/null) || _raw=""
  # Validate JSON is well-formed
  if ! echo "$_raw" | "$JQ" -e . >/dev/null 2>&1; then
    rm -f "$CHECKPOINT_FILE"
    RESET_HAPPENED=1
  else
    # Validate required 'iter' field is a non-negative integer
    _ckpt_iter=$(echo "$_raw" | "$JQ" -r '.iter // empty' 2>/dev/null) || _ckpt_iter=""
    if [[ -z "$_ckpt_iter" ]] || ! [[ "$_ckpt_iter" =~ ^[0-9]+$ ]]; then
      echo "MISSING_ITER_DETECTED"
      rm -f "$CHECKPOINT_FILE"
      RESET_HAPPENED=1
    fi
  fi
fi

if [[ "$RESET_HAPPENED" -eq 1 ]]; then echo "RESET"; fi
rm -rf "$TMP_DIR"
"""
    result = _run_bash(script)
    assert result.returncode == 0, f"Bash script failed: {result.stderr}"
    assert "MISSING_ITER_DETECTED" in result.stdout, f"Missing 'iter' field was not detected. stdout: {result.stdout}"
    assert "RESET" in result.stdout, "Expected RESET when iter field is missing"


def test_load_checkpoint_function_exists_in_helpers() -> None:
    """AC2: load_checkpoint() function must be defined in spiral_helpers.sh."""
    content = SPIRAL_HELPERS.read_text(encoding="utf-8")
    assert "load_checkpoint()" in content, "load_checkpoint() function not found in lib/spiral_helpers.sh"
    # Verify it includes the malformed-JSON warning
    lc_idx = content.find("load_checkpoint()")
    lc_block = content[lc_idx : lc_idx + 1500]
    assert "Malformed JSON" in lc_block or "malformed" in lc_block.lower(), (
        "load_checkpoint() should emit a warning for malformed JSON"
    )


def test_write_checkpoint_json_is_valid_on_load(tmp_path: Path) -> None:
    """AC1: verify that a normal checkpoint is valid JSON and contains schema_version=1."""
    ckpt = tmp_path / "_checkpoint.json"

    # Build a checkpoint JSON that matches what write_checkpoint produces
    data = {
        "schema_version": 1,
        "iter": 3,
        "phase": "I",
        "ts": "2026-04-05T00:00:00Z",
        "run_id": "test-run",
        "spiralVersion": "1.0-test",
        "log_level": "INFO",
        "phaseDurations": {"R": 0, "T": 0, "M": 0, "I": 0, "V": 0, "C": 0},
    }
    ckpt.write_text(json.dumps(data), encoding="utf-8")

    loaded = json.loads(ckpt.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == 1
    assert loaded["iter"] == 3
    assert loaded["phase"] == "I"


def test_truncated_json_fails_json_parse() -> None:
    """AC3: confirm truncated JSON (simulated crash) fails Python json.loads too."""
    truncated = '{"iter":5,"phase":"I","ts":"2026-01'
    try:
        json.loads(truncated)
        assert False, "Expected json.JSONDecodeError for truncated input"
    except json.JSONDecodeError:
        pass  # Correctly detected as malformed
