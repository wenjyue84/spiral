"""tests.py — Parse test results and support test re-run SSE streaming.

Provides:
- parse_test_results(test_results_dir) → list of test result dicts
- stream_rerun(test_id) → generator of SSE-formatted strings
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Generator


def parse_test_results(test_results_dir: str = ".spiral/test-results") -> list[dict[str, Any]]:
    """Parse pytest --json-report output files from test_results_dir.

    Scans all *.json files in test_results_dir, uses the most recently modified
    one, and extracts per-test fields from the pytest-json-report format.

    Returns a list of dicts with keys:
        test_id, test_name, file, status, duration_ms, error_message
    Returns [] if directory is missing, empty, or file is malformed.
    """
    dir_path = Path(test_results_dir)
    if not dir_path.exists():
        return []

    json_files = sorted(dir_path.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not json_files:
        return []

    latest_file = json_files[-1]
    try:
        with open(latest_file, encoding="utf-8") as f:
            report = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    results: list[dict[str, Any]] = []
    for test in report.get("tests", []):
        nodeid: str = test.get("nodeid", "")
        parts = nodeid.split("::")
        file_path = parts[0] if parts else nodeid
        test_name = "::".join(parts[1:]) if len(parts) > 1 else nodeid

        outcome: str = test.get("outcome", "unknown")
        duration_ms = int(test.get("duration", 0.0) * 1000)

        error_message: str | None = None
        if outcome in ("failed", "error"):
            call_info = test.get("call") or {}
            longrepr = call_info.get("longrepr", "")
            error_message = str(longrepr) if longrepr else ""

        results.append(
            {
                "test_id": nodeid,
                "test_name": test_name,
                "file": file_path,
                "status": outcome,
                "duration_ms": duration_ms,
                "error_message": error_message,
            }
        )

    return results


# Regex for valid pytest node IDs — only safe filesystem + pytest characters
_VALID_TEST_ID = re.compile(r"^[\w./\-\[\]@:]+$")


def stream_rerun(test_id: str) -> Generator[str, None, None]:
    """Stream SSE events while re-running a specific pytest test.

    Sanitizes test_id to prevent command injection, then runs
    `python -m pytest <test_id> -v --tb=short` as a subprocess.

    Each stdout line is yielded as an SSE `data:` event.
    The final event is: data: {"type": "status", "result": "pass"|"fail"}
    """
    if not _VALID_TEST_ID.match(test_id):
        yield f"data: {json.dumps({'type': 'error', 'message': 'Invalid test_id'})}\n\n"
        yield f"data: {json.dumps({'type': 'status', 'result': 'fail'})}\n\n"
        return

    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pytest", test_id, "-v", "--tb=short"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            yield f"data: {json.dumps({'type': 'line', 'text': line.rstrip()})}\n\n"

        returncode = proc.wait()
        result = "pass" if returncode == 0 else "fail"
        yield f"data: {json.dumps({'type': 'status', 'result': result})}\n\n"
    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        yield f"data: {json.dumps({'type': 'status', 'result': 'fail'})}\n\n"
