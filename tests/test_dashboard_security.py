"""Security tests for SPIRAL dashboard endpoints (US-563).

Verifies that when SPIRAL_DASHBOARD_API_KEY is set, unauthenticated and
unauthorized requests are rejected and error responses contain no sensitive data.
"""

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app

_TEST_KEY = "test-spiral-api-key-12345"
_PROTECTED_PATHS = ["/profile", "/api/timeline", "/api/dashboard/research-cache"]


@pytest.fixture(autouse=True)
def enable_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set SPIRAL_DASHBOARD_API_KEY to activate auth middleware for each test."""
    monkeypatch.setenv("SPIRAL_DASHBOARD_API_KEY", _TEST_KEY)


def test_unauthenticated_returns_401_or_403() -> None:
    """Requests with no X-API-Key header must return 401 on protected endpoints."""
    client = TestClient(app, raise_server_exceptions=False)
    for path in _PROTECTED_PATHS:
        response = client.get(path)
        assert response.status_code in (401, 403), f"Expected 401/403 for {path}, got {response.status_code}"


def test_no_sensitive_data_in_error_response() -> None:
    """Error responses must not contain API tokens, passwords, or secrets."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/profile")
    assert response.status_code in (401, 403)
    body = response.text.lower()
    for key in ("token", "password", "secret", "api_key", "anthropic"):
        assert key not in body, f"Sensitive key '{key}' found in error response body: {body!r}"


def test_health_endpoint_requires_no_auth() -> None:
    """The /health endpoint must remain accessible without credentials."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/health")
    assert response.status_code == 200


def test_valid_api_key_grants_access() -> None:
    """A request with the correct X-API-Key header must be allowed through."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/profile", headers={"X-API-Key": _TEST_KEY})
    assert response.status_code == 200


def test_wrong_api_key_returns_403() -> None:
    """A request with the wrong X-API-Key header must return 403."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/profile", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 403
