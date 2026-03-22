"""tests/test_lint_prd_security.py — Security tests for lint-prd CLI (US-639).

Verifies that the lint-prd command:
  1. Never leaks credential-like patterns in error output
  2. Handles circular dependencies with non-zero exit and structured JSON (no traceback)
  3. Handles oversized fields (>1MB) without crashing or raising unhandled exceptions

All test functions are named with `us_639_security` so:
  uv run pytest tests/ -k us_639_security -v
selects exactly these tests.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# ── Helpers ───────────────────────────────────────────────────────────────────

_CRED_PATTERN = re.compile(r"(token|password|secret|key)\s*[:=]\s*\S+", re.IGNORECASE)

_STORY_TEMPLATE: dict[str, object] = {
    "title": "placeholder",
    "passes": False,
    "priority": "high",
    "description": "placeholder",
    "acceptanceCriteria": ["AC1"],
    "dependencies": [],
}


def _run_lint_prd(prd_path: Path) -> subprocess.CompletedProcess[str]:
    """Invoke lint-prd as a subprocess and return the completed process."""
    return subprocess.run(
        [sys.executable, "-m", "lib.prd.lint_prd", str(prd_path)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(Path(__file__).parent.parent),
    )


def _make_story(story_id: str, **overrides: object) -> dict[str, object]:
    story = dict(_STORY_TEMPLATE)
    story["id"] = story_id
    story.update(overrides)
    return story


# ── Test 1: No credential leakage ────────────────────────────────────────────


def test_us_639_security_no_credential_leakage(tmp_path: Path) -> None:
    """lint-prd error output must not contain credential-like patterns.

    Injects api_key=sk-test-secret-1234 into a story description and then
    intentionally creates a validation error (missing required field) so that
    the linter produces error output.  Asserts the output never echoes back
    the injected credential string.
    """
    # Story with credential in description field AND a missing 'passes' field
    # to force schema errors to be generated.
    bad_story: dict[str, object] = {
        "id": "US-001",
        "title": "Story with embedded credential",
        "description": "api_key=sk-test-secret-1234 password=hunter2 token=abc123",
        "acceptanceCriteria": ["AC1"],
        "dependencies": [],
        # intentionally omit 'passes' and 'priority' to trigger schema errors
    }
    prd = {
        "productName": "Security Test Product",
        "branchName": "main",
        "userStories": [bad_story],
    }
    prd_file = tmp_path / "prd_cred.json"
    prd_file.write_text(json.dumps(prd), encoding="utf-8")

    result = _run_lint_prd(prd_file)

    combined_output = result.stdout + result.stderr
    # Linter must not echo back the credential values
    assert not _CRED_PATTERN.search(combined_output), f"Credential pattern found in lint-prd output:\n{combined_output}"


# ── Test 2: Circular dep → non-zero exit, structured JSON, no traceback ───────


def test_us_639_security_circular_dep_exits_nonzero_structured_json(tmp_path: Path) -> None:
    """Circular dependency causes lint-prd to exit non-zero with structured JSON.

    Creates US-A → US-B → US-A circular dependency.  Asserts:
      - returncode != 0
      - stdout is valid JSON (not a raw Python traceback)
      - JSON has valid: false and at least one error with type == circular_dep
    """
    prd = {
        "productName": "Circular Test",
        "branchName": "main",
        "userStories": [
            _make_story("US-001", dependencies=["US-002"]),
            _make_story("US-002", dependencies=["US-001"]),
        ],
    }
    prd_file = tmp_path / "prd_circular.json"
    prd_file.write_text(json.dumps(prd), encoding="utf-8")

    result = _run_lint_prd(prd_file)

    # Must exit non-zero
    assert result.returncode != 0, f"Expected non-zero exit for circular deps, got {result.returncode}"

    # stdout must be valid JSON — not a raw Python traceback
    assert "Traceback (most recent call last)" not in result.stdout, (
        "lint-prd emitted a raw Python traceback instead of structured JSON"
    )
    report = json.loads(result.stdout)

    # Must be structured: valid=false, errors list present
    assert report.get("valid") is False
    assert isinstance(report.get("errors"), list)

    # At least one circular_dep error
    circ_errors = [e for e in report["errors"] if e.get("type") == "circular_dep"]
    assert len(circ_errors) >= 1, f"Expected circular_dep error, got: {report['errors']}"

    # The cycle must include both US-001 and US-002
    cycle = circ_errors[0].get("cycle", [])
    assert "US-001" in cycle and "US-002" in cycle, f"Cycle does not contain expected story IDs: {cycle}"


# ── Test 3: Oversized field → no crash, valid JSON output ────────────────────


def test_us_639_security_oversized_field_no_crash(tmp_path: Path) -> None:
    """lint-prd must not crash or raise unhandled exceptions on oversized fields.

    Creates a story with a description field exceeding 1 MB.  Asserts:
      - process completes (no timeout / MemoryError crash)
      - returncode is 0 or 1 (not an unhandled exception exit code)
      - stdout is valid JSON
    """
    oversized_description = "A" * (1024 * 1024 + 1)  # > 1 MB
    prd = {
        "productName": "Oversized Test",
        "branchName": "main",
        "userStories": [
            _make_story("US-001", description=oversized_description),
        ],
    }
    prd_file = tmp_path / "prd_oversized.json"
    prd_file.write_text(json.dumps(prd), encoding="utf-8")

    result = _run_lint_prd(prd_file)

    # Must not crash with an unhandled exception (exit code 2 is acceptable for
    # validation errors; we only disallow uncontrolled crashes)
    assert result.returncode in (0, 1, 2), (
        f"Unexpected exit code {result.returncode} — possible unhandled exception.\nstderr: {result.stderr[:500]}"
    )

    # stdout must be valid JSON — not a crash dump or traceback
    assert "Traceback (most recent call last)" not in result.stdout, (
        "lint-prd emitted a raw Python traceback on oversized field input"
    )
    report = json.loads(result.stdout)
    assert "valid" in report
    assert "errors" in report
