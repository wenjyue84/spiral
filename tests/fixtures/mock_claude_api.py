"""MockClaudeAPI — subprocess-level Claude CLI interceptor for integration tests.

Intercepts subprocess.run calls to the 'claude' binary and returns
pre-injected responses or failures keyed by (phase, story_id).
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock, patch


class MockClaudeAPI:
    """Context-manager fixture that intercepts Claude CLI subprocess calls.

    Usage::

        with MockClaudeAPI() as mock:
            mock.inject_response("I", "US-001", {"result": "ok"})
            mock.inject_failure("R", "timeout")
            # ... run code that calls subprocess.run(["claude", ...])
    """

    def __init__(self) -> None:
        self._responses: dict[tuple[str, str], Any] = {}
        self._failures: dict[str, str] = {}
        self._call_log: list[list[str]] = []
        self._patch: Any = None

    def inject_response(self, phase: str, story_id: str, response_json: Any) -> None:
        """Register a JSON response for a given phase and story_id.

        Args:
            phase: SPIRAL phase letter, e.g. "I", "R", "V"
            story_id: Story identifier, e.g. "US-001"
            response_json: Any JSON-serialisable value returned as stdout
        """
        self._responses[(phase, story_id)] = response_json

    def inject_failure(self, phase: str, error_type: str) -> None:
        """Register a failure mode for a given phase.

        Args:
            phase: SPIRAL phase letter, e.g. "I", "R"
            error_type: "returncode" → exit 1; any other value → CalledProcessError
        """
        self._failures[phase] = error_type

    def get_response(self, phase: str, story_id: str) -> Any:
        """Return the injected response for (phase, story_id), or None."""
        return self._responses.get((phase, story_id))

    def get_failure(self, phase: str) -> str | None:
        """Return the injected failure mode for phase, or None."""
        return self._failures.get(phase)

    @property
    def call_log(self) -> list[list[str]]:
        """List of args lists from intercepted subprocess.run calls."""
        return self._call_log

    def crash_then_succeed(self) -> Any:
        """Return a side effect function that crashes on first call, succeeds on second.

        This helper creates a stateful side effect for testing worker respawn scenarios.
        First invocation: raises CalledProcessError
        Second+ invocations: returns successful CompletedProcess

        Returns:
            A callable that can be used as subprocess_mock.side_effect
        """
        call_count: dict[str, int] = {"value": 0}

        def side_effect(args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            call_count["value"] += 1
            if call_count["value"] == 1:
                # First call: simulate worker crash
                raise subprocess.CalledProcessError(1, args, stderr=b"Worker crashed")
            # Subsequent calls: success
            import json as _json

            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=_json.dumps({}).encode("utf-8"), stderr=b""
            )

        return side_effect

    def _make_side_effect(self) -> Any:
        _original = subprocess.run

        def _side_effect(args: Any, *pargs: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            arg_list = list(args) if isinstance(args, (list, tuple)) else [str(args)]
            is_claude = arg_list and str(arg_list[0]) in {"claude", "claude.exe"}

            if not is_claude:
                return _original(args, *pargs, **kwargs)

            self._call_log.append(arg_list)

            # Check for phase-level failure (wildcard story)
            for phase, error_type in self._failures.items():
                if error_type == "returncode":
                    return subprocess.CompletedProcess(args=arg_list, returncode=1, stdout=b"", stderr=b"")
                raise subprocess.CalledProcessError(1, arg_list, stderr=b"mock error")

            # Check for matching response
            for (phase, story_id), response in self._responses.items():
                import json as _json

                stdout = _json.dumps(response).encode("utf-8")
                return subprocess.CompletedProcess(args=arg_list, returncode=0, stdout=stdout, stderr=b"")

            # Default: success with empty output
            return subprocess.CompletedProcess(args=arg_list, returncode=0, stdout=b"", stderr=b"")

        return _side_effect

    def __enter__(self) -> "MockClaudeAPI":
        self._patch = patch("subprocess.run", side_effect=self._make_side_effect())
        self._mock: MagicMock = self._patch.start()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._patch is not None:
            self._patch.stop()
            self._patch = None
