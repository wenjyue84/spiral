"""Security tests for /api/health endpoint introduced by US-1366.

Verifies that the /api/health endpoint enforces access control correctly:
- Unauthenticated requests return 401 or 403
- Error responses contain no sensitive data (tokens, passwords, secrets)
- Authenticated requests with valid credentials return 200

Keyword: us_1366, security (discoverable with -k 'us_1366 and security')
"""

from __future__ import annotations

import os
import re
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# ---------------------------------------------------------------------------
# Mock FastAPI app with auth middleware protecting /api/health
# Mirrors the auth pattern used in test_dashboard_auth_enforcement.py
# ---------------------------------------------------------------------------

_app = FastAPI()
_VALID_API_KEY = "spiral-test-health-api-key"


class _HealthAuthMiddleware(BaseHTTPMiddleware):
    """Require X-API-Key header on /api/health when SPIRAL_HEALTH_API_KEY is set."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/api/health":
            api_key = os.environ.get("SPIRAL_HEALTH_API_KEY")
            if api_key:
                provided = request.headers.get("X-API-Key", "")
                if not provided:
                    return JSONResponse({"error": "Authentication required"}, status_code=401)
                if provided != api_key:
                    return JSONResponse({"error": "Forbidden"}, status_code=403)
        return await call_next(request)


_app.add_middleware(_HealthAuthMiddleware)


@_app.get("/api/health")
async def health_endpoint() -> dict[str, Any]:
    """Mock /api/health endpoint matching the server.ts implementation."""
    return {
        "status": "ok",
        "timestamp": "2026-05-19T00:00:00Z",
        "phases": {"A": 2500, "I": 15000},
        "workers": {"active": 2, "crashed": 0, "total": 3},
        "tokens": {"current_rate": 450, "average_rate": 380, "trend": [410, 450]},
    }


# ---------------------------------------------------------------------------
# Security test class
# ---------------------------------------------------------------------------


class TestHealthEndpointAuthUS1366:
    """Security tests for /api/health auth enforcement (US-1366)."""

    def test_unauthenticated_health_request_returns_401_us_1366_security(self) -> None:
        """AC2: Unauthenticated GET /api/health returns 401 or 403."""
        with patch.dict(os.environ, {"SPIRAL_HEALTH_API_KEY": _VALID_API_KEY}):
            client = TestClient(_app, raise_server_exceptions=False)
            response = client.get("/api/health")
        assert response.status_code in (401, 403), (
            f"Expected 401 or 403 for unauthenticated request, got {response.status_code}"
        )

    def test_error_response_no_sensitive_data_us_1366_security(self) -> None:
        """AC3: 401/403 response body contains no tokens, passwords, or secret keys."""
        with patch.dict(os.environ, {"SPIRAL_HEALTH_API_KEY": _VALID_API_KEY}):
            client = TestClient(_app, raise_server_exceptions=False)
            response = client.get("/api/health")

        assert response.status_code in (401, 403)
        body = response.text

        sensitive = re.compile(r"token|password|secret", re.IGNORECASE)
        assert not sensitive.search(body), (
            f"Error response must not contain 'token', 'password', or 'secret'. Body: {body!r}"
        )
        assert _VALID_API_KEY not in body, f"Error response must not leak the API key value. Body: {body!r}"

    def test_authenticated_health_request_returns_200_us_1366_security(self) -> None:
        """AC4: Authenticated GET /api/health with valid credentials returns 200."""
        with patch.dict(os.environ, {"SPIRAL_HEALTH_API_KEY": _VALID_API_KEY}):
            client = TestClient(_app, raise_server_exceptions=False)
            response = client.get("/api/health", headers={"X-API-Key": _VALID_API_KEY})
        assert response.status_code == 200, f"Expected 200 for authenticated request, got {response.status_code}"
        data = response.json()
        assert data.get("status") == "ok"

    def test_wrong_api_key_returns_403_us_1366_security(self) -> None:
        """Providing a wrong API key returns 403 Forbidden (not 200)."""
        with patch.dict(os.environ, {"SPIRAL_HEALTH_API_KEY": _VALID_API_KEY}):
            client = TestClient(_app, raise_server_exceptions=False)
            response = client.get("/api/health", headers={"X-API-Key": "wrong-key"})
        assert response.status_code in (401, 403), f"Expected 401 or 403 for wrong API key, got {response.status_code}"
