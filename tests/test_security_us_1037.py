"""Security tests for Phase Completion auth enforcement (US-1037).

Verifies that the worker-phase-swimlane endpoint (I→V→C phase tracking)
enforces API key access control and does not leak sensitive data in error
responses. Guards against regressions in dashboard auth middleware.
"""

import re

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app

_KEY = "test-spiral-api-key-us1037"
_EP = "/api/dashboard/worker-phase-swimlane"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPIRAL_DASHBOARD_API_KEY", _KEY)


class TestUS1037Security:
    """Security tests for Phase I→V→C worker completion endpoint (US-1037)."""

    def test_us_1037_unauth_returns_401(self) -> None:
        """Request without X-API-Key must be rejected with 401."""
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(_EP)
        assert r.status_code in (401, 403)

    def test_us_1037_wrong_key_returns_403(self) -> None:
        """Request with wrong API key must return 403."""
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(_EP, headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 403

    def test_us_1037_valid_key_allowed(self) -> None:
        """Request with correct API key must not be blocked (not 401/403)."""
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(_EP, headers={"X-API-Key": _KEY})
        assert r.status_code not in (401, 403)

    def test_us_1037_no_worker_internals_in_error(self) -> None:
        """Error response must not leak worker state internals."""
        client = TestClient(app, raise_server_exceptions=False)
        body = client.get(_EP).text.lower()
        leak_patterns = [
            r"worker_id",
            r"current_phase",
            r"phase_start_time",
            r"estimated_completion",
            r"spiral.worker",
            r"worktree",
        ]
        for p in leak_patterns:
            assert not re.search(p, body), f"Worker data '{p}' leaked in error: {body!r}"

    def test_us_1037_no_sensitive_keys_in_error(self) -> None:
        """Error response must not contain tokens, passwords, or secrets."""
        client = TestClient(app, raise_server_exceptions=False)
        body = client.get(_EP).text.lower()
        for key in ("password", "secret", "api_key", "anthropic"):
            assert key not in body, f"Sensitive '{key}' in error response: {body!r}"
