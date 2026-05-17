"""Security tests for SettingsTab endpoints access control (US-1215/US-1326).

Verifies that GET /api/config and POST /api/config endpoints consumed by
the SettingsTab component enforce authentication and error responses
contain no sensitive data (tokens, passwords, secrets).
"""

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app

_KEY = "test-spiral-api-key-us1215"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPIRAL_DASHBOARD_API_KEY", _KEY)


def test_settings_save_unauthenticated() -> None:
    """POST /api/config with no auth header must be rejected."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/config", json={"SPIRAL_MAX_PENDING": "5"})
    assert r.status_code in (401, 403)


def test_settings_fetch_unauthenticated() -> None:
    """GET /api/config with no auth header must be rejected."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/config")
    assert r.status_code in (401, 403)


def test_settings_error_no_secret_leak() -> None:
    """Error body from POST /api/config must not leak sensitive keywords."""
    client = TestClient(app, raise_server_exceptions=False)
    body = client.post("/api/config", json={}).text.lower()
    for kw in ("password", "secret", "token", "api_key", "anthropic", "private_key"):
        assert kw not in body, f"Sensitive '{kw}' leaked in POST /api/config error: {body!r}"


def test_get_config_error_response_contains_no_secrets() -> None:
    """Error body from GET /api/config must not leak sensitive keywords."""
    client = TestClient(app, raise_server_exceptions=False)
    body = client.get("/api/config").text.lower()
    for kw in ("password", "secret", "token", "api_key", "anthropic", "private_key"):
        assert kw not in body, f"Sensitive '{kw}' leaked in GET /api/config error: {body!r}"


def test_post_config_valid_key_allowed() -> None:
    """POST /api/config with correct key must not return 401/403."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post(
        "/api/config",
        json={"SPIRAL_MAX_PENDING": "5"},
        headers={"X-API-Key": _KEY},
    )
    assert r.status_code not in (401, 403)


def test_get_config_valid_key_allowed() -> None:
    """GET /api/config with correct key must not return 401/403."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/config", headers={"X-API-Key": _KEY})
    assert r.status_code not in (401, 403)
