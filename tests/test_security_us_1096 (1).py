"""Security tests for lesson injection enrichment (US-1096).

Verifies auth enforcement and ensures lesson/enrichment data
is not leaked in error responses from related dashboard endpoints.
"""

import re

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app

_KEY = "test-spiral-api-key-99999"
_EP = "/api/dashboard/error-breakdown"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPIRAL_DASHBOARD_API_KEY", _KEY)


class TestUS1096Security:
    """Security tests for Phase L→E lesson injection (US-1096)."""

    def test_us_1096_unauth_returns_401(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(_EP)
        assert r.status_code in (401, 403)

    def test_us_1096_wrong_key_returns_403(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(_EP, headers={"X-API-Key": "bad"})
        assert r.status_code == 403

    def test_us_1096_valid_key_allowed(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(_EP, headers={"X-API-Key": _KEY})
        assert r.status_code not in (401, 403)

    def test_us_1096_no_lesson_data_in_error(self) -> None:
        """Error response must not leak lesson store internals."""
        client = TestClient(app, raise_server_exceptions=False)
        body = client.get(_EP).text.lower()
        leak_patterns = [
            r"learned_lessons",
            r"_lessons_applied",
            r"lesson_matcher",
            r"confidence.*0\.\d",
            r"seen_count",
            r"error_category",
            r"\.jsonl",
            r"_match_score",
        ]
        for p in leak_patterns:
            assert not re.search(p, body), f"Lesson data '{p}' leaked: {body!r}"

    def test_us_1096_no_sensitive_keys_in_error(self) -> None:
        """Error response must not contain tokens, passwords, or secrets."""
        client = TestClient(app, raise_server_exceptions=False)
        body = client.get(_EP).text.lower()
        for key in ("password", "secret", "api_key", "anthropic"):
            assert key not in body, f"Sensitive '{key}' in error: {body!r}"
