"""Security tests for phase burn rate endpoint (US-1030).

Verifies that the phase burn rate endpoint enforces access control and
does not leak results.tsv data in error responses.
"""

import re

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app

_TEST_KEY = "test-spiral-api-key-12345"


@pytest.fixture(autouse=True)
def enable_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set SPIRAL_DASHBOARD_API_KEY to activate auth middleware for each test."""
    monkeypatch.setenv("SPIRAL_DASHBOARD_API_KEY", _TEST_KEY)


def test_unauth_burn_rate_returns_401() -> None:
    """GET /api/dashboard/phase-burn-rate must return 401/403 without X-API-Key header."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/dashboard/phase-burn-rate")
    assert response.status_code in (401, 403), (
        f"Expected 401/403 for unauthenticated request to /api/dashboard/phase-burn-rate, got {response.status_code}"
    )


def test_no_tsv_data_in_error_response() -> None:
    """Error response must not contain results.tsv data (story IDs, token counts, etc.)."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/dashboard/phase-burn-rate")
    assert response.status_code in (401, 403)

    body = response.text.lower()

    # Patterns that would indicate TSV data leakage
    tsv_patterns = [
        r"story_id",  # TSV column header
        r"us-\d{3,4}",  # Story ID format
        r"phase_[a-z]",  # Phase column format
        r"tokens",  # Token count column
        r"results\.tsv",  # Filename
        r"iteration",  # iteration column
        r"spiral_iter",  # spiral_iter column
    ]

    for pattern in tsv_patterns:
        assert not re.search(pattern, body, re.IGNORECASE), (
            f"TSV data pattern '{pattern}' found in error response body: {body!r}"
        )


def test_valid_api_key_grants_access() -> None:
    """Request with correct X-API-Key header should be allowed (assuming endpoint exists)."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/dashboard/phase-burn-rate", headers={"X-API-Key": _TEST_KEY})
    # Should not be 401/403; may be 404 if endpoint not yet implemented, or 200/data if it is
    assert response.status_code not in (401, 403), (
        f"Valid API key should not receive 401/403, got {response.status_code}"
    )


def test_wrong_api_key_returns_403() -> None:
    """Request with wrong X-API-Key header must return 403."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/dashboard/phase-burn-rate", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 403, f"Expected 403 for invalid API key, got {response.status_code}"


def test_no_sensitive_keys_in_error_response() -> None:
    """Error response must not contain keys like 'token', 'password', 'secret', 'api_key'."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/dashboard/phase-burn-rate")
    assert response.status_code in (401, 403)

    body = response.text.lower()
    sensitive_keys = ["token", "password", "secret", "api_key", "anthropic"]

    for key in sensitive_keys:
        assert key not in body, f"Sensitive key '{key}' found in error response body: {body!r}"
