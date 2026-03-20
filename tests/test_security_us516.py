"""Security tests for auth/permission access control in SPIRAL dashboard (US-567).

Tests verify that when SPIRAL_DASHBOARD_API_KEY is set:
- Unauthorized requests (no credentials) are blocked with 401 or 403
- Error response bodies contain no sensitive data (tokens, passwords, secrets)

Runs in isolation without requiring external services.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app

_TEST_KEY = "test-security-us516-api-key-99887"
_PROTECTED_PATHS = ["/profile", "/api/timeline", "/api/dashboard/research-cache"]


@pytest.fixture()
def auth_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient with SPIRAL_DASHBOARD_API_KEY set (auth enabled)."""
    monkeypatch.setenv("SPIRAL_DASHBOARD_API_KEY", _TEST_KEY)
    return TestClient(app, raise_server_exceptions=False)


def test_unauthorized_access_blocked(auth_client: TestClient) -> None:
    """Requests with no X-API-Key header must be blocked with 401 or 403.

    Acceptance criterion: uv run pytest tests/test_security_us516.py::test_unauthorized_access_blocked -v
    """
    for path in _PROTECTED_PATHS:
        response = auth_client.get(path)
        assert response.status_code in (401, 403), (
            f"Expected 401 or 403 for {path} without credentials, got {response.status_code}"
        )


def test_no_sensitive_data_in_error(auth_client: TestClient) -> None:
    """Error response body must not contain tokens, passwords, or secrets.

    Acceptance criterion: uv run pytest tests/test_security_us516.py::test_no_sensitive_data_in_error -v
    """
    response = auth_client.get("/profile")
    assert response.status_code in (401, 403)

    body = response.text.lower()
    sensitive_patterns = [
        r"bearer\s+[a-z0-9_\-]+",  # Bearer tokens
        r"password",  # Password references
        r"api[_\-]?key\s*=",  # API key assignments
        r"secret",  # Secret references
        r"anthropic",  # Provider name (reveals auth system)
    ]
    for pattern in sensitive_patterns:
        assert not re.search(pattern, body), f"Error response leaked sensitive pattern '{pattern}': {body!r}"


def test_health_endpoint_bypasses_auth(auth_client: TestClient) -> None:
    """/health must remain accessible without credentials even when auth is enabled."""
    response = auth_client.get("/health")
    assert response.status_code == 200


def test_wrong_api_key_returns_403(auth_client: TestClient) -> None:
    """A request with an incorrect X-API-Key must be rejected with 403."""
    response = auth_client.get("/profile", headers={"X-API-Key": "wrong-key-xyz"})
    assert response.status_code == 403


def test_correct_api_key_grants_access(auth_client: TestClient) -> None:
    """A request with the correct X-API-Key must be allowed through."""
    response = auth_client.get("/profile", headers={"X-API-Key": _TEST_KEY})
    assert response.status_code == 200


def test_error_body_no_api_key_value(auth_client: TestClient) -> None:
    """The actual API key value must never appear in any error response."""
    response = auth_client.get("/profile")
    assert response.status_code in (401, 403)
    assert _TEST_KEY not in response.text, f"API key value leaked in error response: {response.text!r}"
