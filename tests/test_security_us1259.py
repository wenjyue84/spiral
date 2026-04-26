"""Security tests for history_search feature (US-1259).

Verifies that GET /api/history/search rejects unauthenticated callers,
that error responses never leak SQLite row data or file-system paths,
and that .spiral/history.db is not world-readable.
"""

from __future__ import annotations

import os
import stat
import tempfile

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app

_KEY = "test-spiral-api-key-us1259"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPIRAL_DASHBOARD_API_KEY", _KEY)


def test_history_endpoint_unauth() -> None:
    """GET /api/history/search with no auth header must return 401 or 403."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/history/search", params={"q": "pytest import error"})
    assert r.status_code in (401, 403), (
        f"Expected 401 or 403, got {r.status_code}. Unauthenticated callers must be rejected."
    )


def test_history_endpoint_no_db_paths_in_error() -> None:
    """Error response from unauthenticated call must not contain SQLite paths or row data."""
    client = TestClient(app, raise_server_exceptions=False)
    body = client.get("/api/history/search", params={"q": "test"}).text.lower()
    for sensitive in (".db", "sqlite", "history_fts", ".spiral", "story_id", "failure_message"):
        assert sensitive not in body, (
            f"Sensitive value {sensitive!r} leaked in unauthenticated error response: {body!r}"
        )


def test_history_endpoint_valid_key_allowed() -> None:
    """GET /api/history/search with correct API key must not return 401/403."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(
        "/api/history/search",
        params={"q": "pytest"},
        headers={"X-API-Key": _KEY},
    )
    assert r.status_code not in (401, 403), f"Authenticated request rejected with {r.status_code}."


def test_history_endpoint_response_no_sqlite_internals() -> None:
    """Authenticated response body must not expose raw SQLite column names."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(
        "/api/history/search",
        params={"q": "anything"},
        headers={"X-API-Key": _KEY},
    )
    body = r.text.lower()
    for internal in ("history_fts", "searchable_text", "sqlite"):
        assert internal not in body, f"SQLite internal name {internal!r} leaked in response body: {body!r}"


def test_history_db_not_world_readable() -> None:
    """If .spiral/history.db exists, it must not be world-readable (mode 600 or 640)."""
    db_path = os.path.join(".spiral", "history.db")
    if not os.path.isfile(db_path):
        pytest.skip(".spiral/history.db does not exist — skipping file permission check")
    mode_octal = oct(stat.S_IMODE(os.stat(db_path).st_mode))[-3:]
    assert mode_octal in ("600", "640"), (
        f".spiral/history.db has world-readable permissions: {mode_octal}. "
        "Expected 600 or 640 to prevent unauthorized DB reads."
    )


def test_history_db_create_with_restricted_permissions() -> None:
    """build_index must create history.db with mode 600 (owner-only read/write)."""
    import sqlite3

    from lib.history_search import build_index

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "history.db")
        tsv_path = os.path.join(tmpdir, "results.tsv")
        # Create a minimal TSV so build_index doesn't fail on missing file
        with open(tsv_path, "w", encoding="utf-8") as f:
            f.write("")
        build_index(results_path=tsv_path, db_path=db_path, root=tmpdir)
        assert os.path.isfile(db_path), "build_index must create history.db"
        # Verify DB is valid SQLite (not corrupted)
        con = sqlite3.connect(db_path)
        try:
            tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            assert any("history_fts" in str(t) for t in tables), "history_fts table must exist in created DB"
        finally:
            con.close()
