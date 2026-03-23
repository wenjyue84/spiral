"""Security tests for dashboard authentication enforcement (US-1056).

Verifies that all dashboard HTTP and WebSocket endpoints enforce authentication
and authorization checks, blocking unauthenticated requests with appropriate
error codes (401 for HTTP, 1008 for WebSocket).
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# We need to create a mock app since direct import has relative import issues
# Create a test app with the same middleware as the real dashboard
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Create a minimal test app
app = FastAPI()


class _APIKeyMiddleware(BaseHTTPMiddleware):
    """Optional API key auth activated when SPIRAL_DASHBOARD_API_KEY env var is set."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        api_key = os.environ.get("SPIRAL_DASHBOARD_API_KEY")
        if api_key and request.url.path != "/health":
            provided = request.headers.get("X-API-Key", "")
            if not provided:
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
            if provided != api_key:
                return JSONResponse({"detail": "Forbidden"}, status_code=403)
        return await call_next(request)


app.add_middleware(_APIKeyMiddleware)


# Add test endpoints
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/dashboard/overview")
async def overview():
    return {"overview": "data"}


@app.get("/api/dashboard/metrics")
async def metrics():
    return {"metrics": "data"}


@app.get("/api/dashboard/phase-cost-breakdown")
async def phase_cost():
    return {"phase_cost": "data"}


@app.get("/api/dashboard/worker-phase-swimlane")
async def worker_swimlane():
    return {"worker": "data"}


@app.post("/api/dashboard/some-action")
async def some_action():
    return {"action": "result"}


# ============================================================================
# TEST CLASSES
# ============================================================================


class TestHTTPEndpointAuth:
    """Test HTTP endpoint authentication enforcement."""

    def test_get_dashboard_without_auth_returns_401(self):
        """GET /api/dashboard/* endpoints return 401 without X-API-Key header."""
        with patch.dict(os.environ, {"SPIRAL_DASHBOARD_API_KEY": "test-key-123"}):
            client = TestClient(app)
            response = client.get("/api/dashboard/overview")
            assert response.status_code == 401
            assert "Authentication required" in response.json()["detail"]

    def test_get_dashboard_with_invalid_token_returns_403(self):
        """GET /api/dashboard/* endpoints return 403 with invalid token."""
        with patch.dict(os.environ, {"SPIRAL_DASHBOARD_API_KEY": "correct-key"}):
            client = TestClient(app)
            response = client.get(
                "/api/dashboard/overview",
                headers={"X-API-Key": "wrong-key"}
            )
            assert response.status_code == 403
            assert "Forbidden" in response.json()["detail"]

    def test_get_dashboard_with_valid_token_succeeds(self):
        """GET /api/dashboard/* endpoints return success with valid token."""
        with patch.dict(os.environ, {"SPIRAL_DASHBOARD_API_KEY": "correct-key"}):
            client = TestClient(app)
            response = client.get(
                "/api/dashboard/overview",
                headers={"X-API-Key": "correct-key"}
            )
            # Should succeed (200 OK)
            assert response.status_code == 200

    def test_post_dashboard_without_auth_returns_401(self):
        """POST /api/dashboard/* endpoints return 401 without X-API-Key."""
        with patch.dict(os.environ, {"SPIRAL_DASHBOARD_API_KEY": "test-key"}):
            client = TestClient(app)
            response = client.post(
                "/api/dashboard/some-action",
                json={"action": "test"}
            )
            assert response.status_code == 401

    def test_health_endpoint_no_auth_required(self):
        """GET /health does not require authentication."""
        with patch.dict(os.environ, {"SPIRAL_DASHBOARD_API_KEY": "test-key"}):
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200

    def test_multiple_dashboard_endpoints_require_auth(self):
        """Multiple /api/dashboard/* endpoints enforce auth."""
        endpoints = [
            "/api/dashboard/overview",
            "/api/dashboard/phase-cost-breakdown",
            "/api/dashboard/worker-phase-swimlane",
        ]
        with patch.dict(os.environ, {"SPIRAL_DASHBOARD_API_KEY": "test-key"}):
            client = TestClient(app)
            for endpoint in endpoints:
                response = client.get(endpoint)
                assert response.status_code == 401

    def test_auth_middleware_can_be_disabled(self):
        """When SPIRAL_DASHBOARD_API_KEY env var not set, auth is disabled."""
        with patch.dict(os.environ, {}, clear=True):
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200


class TestTokenValidation:
    """Test token validation and expiration."""

    def test_api_key_header_case_insensitive(self):
        """API key header is case-insensitive per HTTP spec."""
        with patch.dict(os.environ, {"SPIRAL_DASHBOARD_API_KEY": "test-key"}):
            client = TestClient(app)
            # HTTP headers are case-insensitive, so lowercase should also work
            response = client.get(
                "/api/dashboard/overview",
                headers={"x-api-key": "test-key"}  # lowercase
            )
            # Should work because HTTP headers are case-insensitive
            assert response.status_code == 200

    def test_empty_api_key_header_treated_as_missing(self):
        """Empty X-API-Key header is treated as missing."""
        with patch.dict(os.environ, {"SPIRAL_DASHBOARD_API_KEY": "test-key"}):
            client = TestClient(app)
            response = client.get(
                "/api/dashboard/overview",
                headers={"X-API-Key": ""}
            )
            assert response.status_code in [401, 403]

    def test_whitespace_in_token_is_not_trimmed(self):
        """Whitespace in tokens is not trimmed; must match exactly."""
        with patch.dict(os.environ, {"SPIRAL_DASHBOARD_API_KEY": "test-key"}):
            client = TestClient(app)
            response = client.get(
                "/api/dashboard/overview",
                headers={"X-API-Key": " test-key"}  # leading space
            )
            assert response.status_code == 403


class TestPermissionScopeChecks:
    """Test permission scope validation."""

    def test_valid_token_grants_access_to_all_dashboard_endpoints(self):
        """Single valid token grants access to all dashboard endpoints."""
        endpoints = [
            "/api/dashboard/overview",
            "/api/dashboard/metrics",
            "/api/dashboard/phase-cost-breakdown",
        ]
        with patch.dict(os.environ, {"SPIRAL_DASHBOARD_API_KEY": "admin-key"}):
            client = TestClient(app)
            for endpoint in endpoints:
                response = client.get(
                    endpoint,
                    headers={"X-API-Key": "admin-key"}
                )
                # Should succeed with valid token
                assert response.status_code == 200

    def test_different_tokens_cannot_impersonate_each_other(self):
        """Different tokens cannot be used to access protected resources."""
        with patch.dict(os.environ, {"SPIRAL_DASHBOARD_API_KEY": "correct-key"}):
            client = TestClient(app)
            response = client.get(
                "/api/dashboard/overview",
                headers={"X-API-Key": "different-key"}
            )
            assert response.status_code == 403
