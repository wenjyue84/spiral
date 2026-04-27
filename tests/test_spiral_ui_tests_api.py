"""Tests for /api/tests/latest and /api/tests/rerun backend endpoints (US-1293).

Tests verify:
- GET /api/tests/latest returns correct JSON schema from a pytest --json-report file
- POST /api/tests/rerun/:testId streams SSE events and ends with a status event
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.dashboard.routes.tests import parse_test_results, stream_rerun

# ── Minimal FastAPI test app ───────────────────────────────────────────────────

_app = FastAPI()


@_app.get("/api/tests/latest")
async def _latest() -> list[dict[str, Any]]:
    return parse_test_results()


@_app.post("/api/tests/rerun/{run_id:path}")
async def _rerun(run_id: str):  # type: ignore[return]
    from starlette.responses import StreamingResponse

    return StreamingResponse(stream_rerun(run_id), media_type="text/event-stream")


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def json_report(tmp_path: Path) -> Path:
    """Write a minimal pytest --json-report file and return its parent dir."""
    results_dir = tmp_path / "test-results"
    results_dir.mkdir()

    report: dict[str, Any] = {
        "created": "2026-04-27T00:00:00Z",
        "duration": 1.5,
        "tests": [
            {
                "nodeid": "tests/test_foo.py::test_passes",
                "outcome": "passed",
                "duration": 0.1,
            },
            {
                "nodeid": "tests/test_foo.py::test_fails",
                "outcome": "failed",
                "duration": 0.05,
                "call": {"longrepr": "AssertionError: expected 1 == 2"},
            },
        ],
        "summary": {"passed": 1, "failed": 1, "total": 2},
    }
    (results_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return results_dir


# ── parse_test_results unit tests ─────────────────────────────────────────────


def test_parse_returns_list_for_valid_report(json_report: Path) -> None:
    results = parse_test_results(str(json_report))
    assert isinstance(results, list)
    assert len(results) == 2


def test_parse_result_has_required_fields(json_report: Path) -> None:
    required = {"test_id", "test_name", "file", "status", "duration_ms", "error_message"}
    for item in parse_test_results(str(json_report)):
        assert required.issubset(item.keys()), f"Missing fields in {item}"


def test_parse_result_field_types(json_report: Path) -> None:
    for item in parse_test_results(str(json_report)):
        assert isinstance(item["test_id"], str)
        assert isinstance(item["test_name"], str)
        assert isinstance(item["file"], str)
        assert isinstance(item["status"], str)
        assert isinstance(item["duration_ms"], int)
        assert item["error_message"] is None or isinstance(item["error_message"], str)


def test_parse_failed_test_has_error_message(json_report: Path) -> None:
    results = parse_test_results(str(json_report))
    failed = next(r for r in results if r["status"] == "failed")
    assert failed["error_message"] is not None
    assert "AssertionError" in failed["error_message"]


def test_parse_passed_test_has_no_error_message(json_report: Path) -> None:
    results = parse_test_results(str(json_report))
    passed = next(r for r in results if r["status"] == "passed")
    assert passed["error_message"] is None


def test_parse_empty_dir_returns_empty_list(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert parse_test_results(str(empty_dir)) == []


def test_parse_missing_dir_returns_empty_list(tmp_path: Path) -> None:
    assert parse_test_results(str(tmp_path / "nonexistent")) == []


def test_parse_malformed_json_returns_empty_list(tmp_path: Path) -> None:
    results_dir = tmp_path / "bad"
    results_dir.mkdir()
    (results_dir / "bad.json").write_text("not json{{{", encoding="utf-8")
    assert parse_test_results(str(results_dir)) == []


# ── GET /api/tests/latest endpoint tests ──────────────────────────────────────


def test_tests_latest_endpoint(json_report: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tests/latest returns JSON array with correct schema."""
    monkeypatch.setattr(
        "lib.dashboard.routes.tests.parse_test_results",
        lambda *a, **kw: parse_test_results(str(json_report)),
    )
    client = TestClient(_app)
    response = client.get("/api/tests/latest")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    required = {"test_id", "test_name", "file", "status", "duration_ms", "error_message"}
    for item in data:
        assert required.issubset(item.keys())


# ── stream_rerun unit tests ────────────────────────────────────────────────────


def _collect_sse(gen: Generator[str, None, None]) -> list[dict[str, Any]]:
    """Collect and parse all SSE data payloads from a generator."""
    events: list[dict[str, Any]] = []
    for chunk in gen:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_stream_rerun_invalid_test_id_returns_fail() -> None:
    events = _collect_sse(stream_rerun("../../etc/passwd"))
    types = [e["type"] for e in events]
    assert "status" in types
    status_event = next(e for e in events if e["type"] == "status")
    assert status_event["result"] == "fail"


def test_stream_rerun_shell_metacharacters_blocked() -> None:
    events = _collect_sse(stream_rerun("tests/test_foo.py; rm -rf /"))
    status_event = next(e for e in events if e["type"] == "status")
    assert status_event["result"] == "fail"


def test_tests_rerun_streams_sse(tmp_path: Path) -> None:
    """POST /api/tests/rerun/:testId streams SSE events ending with status."""
    # Write a trivial passing test to a temp file
    test_file = tmp_path / "test_trivial.py"
    test_file.write_text("def test_ok(): assert True\n", encoding="utf-8")

    events: list[dict[str, Any]] = []
    for chunk in stream_rerun(str(test_file).replace("\\", "/")):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    # Must end with a status event containing pass or fail
    assert len(events) > 0
    last = events[-1]
    assert last["type"] == "status"
    assert last["result"] in ("pass", "fail")
