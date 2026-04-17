"""Security tests for SettingsTab access control (US-1215).

Verifies that dashboard config-related endpoints enforce auth
and error responses contain no sensitive data (tokens, passwords, keys).
"""

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app

_KEY = "test-spiral-api-key-us1215"
_EP = "/api/dashboard/overview"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPIRAL_DASHBOARD_API_KEY", _KEY)


def test_unauthenticated_get_config_returns_401() -> None:
    """Unauthenticated request must be rejected."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(_EP)
    assert r.status_code in (401, 403)


def test_us_1215_wrong_key_returns_403() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(_EP, headers={"X-API-Key": "bad-key"})
    assert r.status_code == 403


def test_error_response_contains_no_secrets() -> None:
    """Error response body must contain no token/password/key substrings."""
    client = TestClient(app, raise_server_exceptions=False)
    body = client.get(_EP).text.lower()
    for kw in ("password", "secret", "api_key", "anthropic", "token", "private_key"):
        assert kw not in body, f"Sensitive '{kw}' leaked: {body!r}"


def test_us_1215_valid_key_allowed() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(_EP, headers={"X-API-Key": _KEY})
    assert r.status_code not in (401, 403)
