"""Security tests for SPIRAL self-monitoring dashboard (US-484).

Tests verify:
1. Unauthenticated access is properly blocked (401/403)
2. Error responses don't leak sensitive data (API keys, bearer tokens, etc.)
"""

from __future__ import annotations

import asyncio
import os
import re

import pytest

from lib.ui.spiral_live_server import SpiralLiveServer


class TestUnauthenticatedDashboard:
    """Test that dashboard enforces authentication when enabled."""

    def test_unauthenticated_dashboard_returns_401_or_403(
        self, spiral_server: SpiralLiveServer, mock_writer: object, with_auth: None
    ) -> None:
        """Verify unauthenticated requests to dashboard return 401/403.

        Acceptance criterion: Dashboard enforces auth; unauthenticated access
        is blocked with 401 (Unauthorized) status code.
        """
        # Reload the server module to pick up the auth token from fixture
        from lib.ui.spiral_live_server import SpiralLiveServer
        import importlib
        import lib.ui.spiral_live_server as dashboard_module

        importlib.reload(dashboard_module)
        spiral_server = SpiralLiveServer(host="127.0.0.1", port=5300)

        # Request without Authorization header
        headers: dict[str, str] = {}

        # Route a GET request to the dashboard root
        asyncio.run(
            spiral_server._route(
                method="GET",
                path="/",
                headers=headers,
                body=b"",
                writer=mock_writer,  # type: ignore[arg-type]
            )
        )

        # Verify response is 401 (Unauthorized) or 403 (Forbidden)
        status_code = mock_writer.get_status_code()  # type: ignore[attr-defined]
        assert status_code in (401, 403), f"Expected 401 or 403, got {status_code}"

    def test_authenticated_request_allowed(
        self, spiral_server: SpiralLiveServer, mock_writer: object, with_auth: None, auth_token: str
    ) -> None:
        """Verify authenticated requests with valid token are allowed.

        This is a positive test to ensure the auth mechanism works.
        """
        from lib.ui.spiral_live_server import SpiralLiveServer
        import importlib
        import lib.ui.spiral_live_server as dashboard_module

        importlib.reload(dashboard_module)
        spiral_server = SpiralLiveServer(host="127.0.0.1", port=5300)

        # Request with valid Authorization header
        headers = {"authorization": f"Bearer {auth_token}"}

        # Route a GET request to the dashboard root
        # It will route to _handle_index which should return 200
        asyncio.run(
            spiral_server._route(
                method="GET",
                path="/",
                headers=headers,
                body=b"",
                writer=mock_writer,  # type: ignore[arg-type]
            )
        )

        # Verify response is 200 (success)
        status_code = mock_writer.get_status_code()  # type: ignore[attr-defined]
        assert status_code == 200, f"Expected 200, got {status_code}"

    def test_wrong_token_returns_401(
        self, spiral_server: SpiralLiveServer, mock_writer: object, with_auth: None
    ) -> None:
        """Verify requests with incorrect token are rejected.

        Acceptance criterion: Invalid tokens are treated as unauthorized.
        """
        from lib.ui.spiral_live_server import SpiralLiveServer
        import importlib
        import lib.ui.spiral_live_server as dashboard_module

        importlib.reload(dashboard_module)
        spiral_server = SpiralLiveServer(host="127.0.0.1", port=5300)

        # Request with wrong Authorization header
        headers = {"authorization": "Bearer wrong-token"}

        asyncio.run(
            spiral_server._route(
                method="GET",
                path="/",
                headers=headers,
                body=b"",
                writer=mock_writer,  # type: ignore[arg-type]
            )
        )

        # Verify response is 401
        status_code = mock_writer.get_status_code()  # type: ignore[attr-defined]
        assert status_code == 401, f"Expected 401, got {status_code}"


class TestErrorResponseLeakage:
    """Test that error responses don't leak sensitive data."""

    def test_error_response_contains_no_secrets(
        self, spiral_server: SpiralLiveServer, mock_writer: object, without_auth: None
    ) -> None:
        """Verify error responses don't contain API keys or bearer tokens.

        Acceptance criterion: Error messages must not expose:
        - Bearer tokens (pattern: Bearer [A-Za-z0-9_-]+)
        - API keys (pattern: sk-[A-Za-z0-9]+)
        - Database passwords or credentials
        - File system paths that might be sensitive
        """
        # Request a non-existent endpoint to trigger an error
        headers: dict[str, str] = {}

        asyncio.run(
            spiral_server._route(
                method="GET",
                path="/nonexistent-endpoint",
                headers=headers,
                body=b"",
                writer=mock_writer,  # type: ignore[arg-type]
            )
        )

        # Get the response body
        response_body = mock_writer.get_response_body()  # type: ignore[attr-defined]
        response_str = str(response_body).lower()

        # Verify no secret patterns leak in error response
        secret_patterns = [
            r"bearer\s+[a-z0-9_-]+",  # Bearer tokens
            r"sk-[a-z0-9]+",  # API keys
            r"api.?key",  # API key references
            r"password",  # Password references
            r"token",  # Token references (in the context of secrets)
        ]

        for pattern in secret_patterns:
            assert not re.search(pattern, response_str), (
                f"Error response leaked secret pattern: {pattern}\n"
                f"Response: {response_body}"
            )

    def test_internal_server_error_sanitized(
        self, spiral_server: SpiralLiveServer, mock_writer: object, without_auth: None
    ) -> None:
        """Verify 500 errors don't expose internal exception details.

        Acceptance criterion: Generic error message instead of
        traceback or exception details.
        """
        # Manually trigger an error by sending invalid request
        # _send_error is called with generic message in exception handler
        asyncio.run(spiral_server._send_error(mock_writer, 500, "Internal Server Error"))  # type: ignore[arg-type]

        response_body = mock_writer.get_response_body()  # type: ignore[attr-defined]
        response_str = str(response_body)

        # Verify response contains only generic error message
        assert "error" in response_str
        assert "Internal Server Error" in response_str

        # Verify no stack traces or exception types exposed
        assert "traceback" not in response_str.lower()
        assert "exception" not in response_str.lower()

    def test_bad_json_error_response_sanitized(
        self, spiral_server: SpiralLiveServer, mock_writer: object, without_auth: None
    ) -> None:
        """Verify JSON parsing errors don't expose input data.

        Acceptance criterion: Generic error instead of echoing
        malformed input that might contain secrets.
        """
        headers = {"content-type": "application/json"}
        bad_body = b'{"incomplete": json'  # Malformed JSON

        # Simulate a POST that expects JSON
        asyncio.run(
            spiral_server._route(
                method="POST",
                path="/api/worker-start",
                headers=headers,
                body=bad_body,
                writer=mock_writer,  # type: ignore[arg-type]
            )
        )

        response_body = mock_writer.get_response_body()  # type: ignore[attr-defined]
        response_str = str(response_body)

        # Verify error response doesn't echo back the malformed input
        assert "incomplete" not in response_str, (
            "Error response echoed back user input; "
            "could leak sensitive data from malformed requests"
        )

    def test_no_auth_token_in_error_when_enabled(
        self, spiral_server: SpiralLiveServer, mock_writer: object, with_auth: None, auth_token: str
    ) -> None:
        """Verify auth token is never sent in error responses.

        Acceptance criterion: Even if a request fails, the auth token
        used should never appear in error response.
        """
        from lib.ui.spiral_live_server import SpiralLiveServer
        import importlib
        import lib.ui.spiral_live_server as dashboard_module

        importlib.reload(dashboard_module)
        spiral_server = SpiralLiveServer(host="127.0.0.1", port=5300)

        # Send request with valid token but to non-existent endpoint
        headers = {"authorization": f"Bearer {auth_token}"}

        asyncio.run(
            spiral_server._route(
                method="GET",
                path="/api/nonexistent-secret-endpoint",
                headers=headers,
                body=b"",
                writer=mock_writer,  # type: ignore[arg-type]
            )
        )

        response_body = mock_writer.get_response_body()  # type: ignore[attr-defined]
        response_str = str(response_body)

        # Verify the auth token is never in the response
        assert auth_token not in response_str, (
            f"Auth token leaked in error response: {auth_token}"
        )
