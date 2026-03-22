"""Shared test fixtures and Hypothesis strategies for SPIRAL property tests."""

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

# Ensure lib/ and project root are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))


# ── Common settings for suppressing slow-generation health checks ──────────
# The PRD strategy is inherently composite; suppress slow/large warnings.
HEALTH_SUPPRESSED = [HealthCheck.too_slow, HealthCheck.large_base_example]

# ── US-368: Hypothesis settings profiles for CI vs dev test execution ──────
# ci       — thorough coverage for CI pipelines (high example count, no deadline)
# dev      — fast local feedback loop (low example count, 500ms deadline)
# thorough — pre-release deep testing (very high example count, no deadline)
settings.register_profile("ci", max_examples=500, deadline=None)
settings.register_profile("dev", max_examples=50, deadline=500)
settings.register_profile("thorough", max_examples=2000, deadline=None)

# Load profile from env var (defaults to 'dev' for fast local runs)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))

# ── Hypothesis strategies ──────────────────────────────────────────────────

PRIORITIES = ["critical", "high", "medium", "low"]
COMPLEXITIES = ["small", "medium", "large"]

# Lightweight text strategies (avoid expensive full-unicode generation)
_title_st = st.from_regex(r"[A-Za-z][A-Za-z0-9 _-]{2,30}", fullmatch=True)
_desc_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz 0123456789.,",
    min_size=0,
    max_size=60,
)
_ac_item_st = st.from_regex(r"[A-Za-z][A-Za-z0-9 ]{2,40}", fullmatch=True)
_note_st = st.from_regex(r"[A-Za-z][A-Za-z0-9 ]{2,30}", fullmatch=True)
_file_st = st.from_regex(r"[a-z][a-z0-9_/]{1,20}\.(py|js|ts|sh)", fullmatch=True)
_epic_id_st = st.from_regex(r"[a-z][a-z0-9_-]{1,15}", fullmatch=True)


@st.composite
def valid_prd(draw, min_stories=1, max_stories=10):
    """Generate a valid prd.json dict with consistent forward-only dependencies.

    Uses sequential IDs (US-001, US-002, ...) to avoid collision loops.
    Dependencies only reference earlier IDs, guaranteeing a valid DAG.
    """
    n = draw(st.integers(min_value=min_stories, max_value=max_stories))

    stories = []
    for i in range(n):
        sid = f"US-{i + 1:03d}"
        earlier_ids = [f"US-{j + 1:03d}" for j in range(i)]

        # Pick deps from earlier IDs only (forward deps = no cycles)
        deps = []
        if earlier_ids:
            deps = draw(
                st.lists(
                    st.sampled_from(earlier_ids),
                    max_size=min(2, len(earlier_ids)),
                    unique=True,
                )
            )

        story = {
            "id": sid,
            "title": draw(_title_st),
            "passes": draw(st.booleans()),
            "priority": draw(st.sampled_from(PRIORITIES)),
            "description": draw(_desc_st),
            "acceptanceCriteria": draw(st.lists(_ac_item_st, min_size=1, max_size=3)),
            "dependencies": deps,
        }

        # Optional fields (coin flip)
        if draw(st.booleans()):
            story["estimatedComplexity"] = draw(st.sampled_from(COMPLEXITIES))
        if draw(st.booleans()):
            story["technicalNotes"] = draw(st.lists(_note_st, max_size=2))
        if draw(st.booleans()):
            story["filesTouch"] = draw(st.lists(_file_st, max_size=3))
        if draw(st.booleans()):
            story["epicId"] = draw(_epic_id_st)

        stories.append(story)

    product = draw(st.from_regex(r"[A-Z][a-z]{2,10}", fullmatch=True))
    branch = draw(st.from_regex(r"[a-z]{2,10}", fullmatch=True))

    return {
        "productName": product,
        "branchName": branch,
        "userStories": stories,
    }


@st.composite
def invalid_prd_missing_field(draw):
    """Generate a PRD with one required field missing."""
    prd = draw(valid_prd(min_stories=1, max_stories=3))
    field = draw(st.sampled_from(["productName", "branchName", "userStories"]))
    del prd[field]
    return prd, field


@st.composite
def prd_with_duplicate_ids(draw):
    """Generate a PRD that has duplicate story IDs."""
    prd = draw(valid_prd(min_stories=2, max_stories=4))
    # Duplicate first story's ID onto last
    prd["userStories"][-1]["id"] = prd["userStories"][0]["id"]
    return prd


@st.composite
def prd_with_cycle(draw):
    """Generate a PRD that has a dependency cycle."""
    prd = draw(valid_prd(min_stories=3, max_stories=5))
    stories = prd["userStories"]
    # Create cycle: last depends on second-to-last, which depends on last
    stories[-1]["dependencies"] = [stories[-2]["id"]]
    stories[-2]["dependencies"] = [stories[-1]["id"]]
    return prd


@st.composite
def prd_with_dangling_dep(draw):
    """Generate a PRD with a dependency pointing to a non-existent ID."""
    prd = draw(valid_prd(min_stories=1, max_stories=3))
    # US-9999 will never be generated by our sequential strategy
    prd["userStories"][0]["dependencies"] = ["US-9999"]
    return prd


@pytest.fixture
def yaml_file() -> Callable[[str], dict[str, Any]]:
    """Load a .github YAML file as a dict (offline — no GitHub API calls).

    Usage::

        def test_something(yaml_file):
            data = yaml_file(".github/actions/lint-shell/action.yml")
            assert "runs" in data
    """
    repo_root = Path(__file__).parent.parent

    def _load(relative_path: str) -> dict[str, Any]:
        path = repo_root / relative_path
        with open(path, encoding="utf-8") as f:
            result: dict[str, Any] = yaml.safe_load(f)
        assert isinstance(result, dict), f"Expected dict at top level of {path}"
        return result

    return _load


@pytest.fixture
def example_prd():
    """Load the example prd.json."""
    path = os.path.join(os.path.dirname(__file__), "..", "templates", "prd.example.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def tmp_prd(tmp_path):
    """Create a temp prd.json and return its path."""

    def _write(prd_dict):
        path = tmp_path / "prd.json"
        path.write_text(json.dumps(prd_dict, indent=2), encoding="utf-8")
        return str(path)

    return _write


# ── Dashboard security testing fixtures ─────────────────────────────────────


class MockStreamWriter:
    """Mock asyncio.StreamWriter for testing HTTP responses."""

    def __init__(self) -> None:
        self.data: bytearray = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        """Write data to buffer."""
        self.data.extend(data)

    async def drain(self) -> None:
        """No-op drain."""
        pass

    def close(self) -> None:
        """Mark as closed."""
        self.closed = True

    async def wait_closed(self) -> None:
        """No-op wait_closed."""
        pass

    def get_response_body(self) -> dict:
        """Parse response body as JSON."""
        response_str = self.data.decode("utf-8", errors="replace")
        # Split headers and body by \r\n\r\n
        parts = response_str.split("\r\n\r\n", 1)
        if len(parts) < 2:
            return {}
        body_str = parts[1]
        if not body_str:
            return {}
        try:
            return json.loads(body_str)
        except json.JSONDecodeError:
            return {}

    def get_status_code(self) -> int:
        """Extract HTTP status code from response."""
        response_str = self.data.decode("utf-8", errors="replace")
        # First line is "HTTP/1.1 <code> <message>"
        first_line = response_str.split("\r\n")[0]
        parts = first_line.split(" ")
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except ValueError:
                return 0
        return 0


@pytest.fixture
def spiral_server():
    """Provide a SpiralLiveServer instance for testing."""
    from lib.ui.spiral_live_server import SpiralLiveServer

    return SpiralLiveServer(host="127.0.0.1", port=5300)


@pytest.fixture
def mock_writer():
    """Provide a mock StreamWriter for testing."""
    return MockStreamWriter()


@pytest.fixture
def auth_token():
    """Provide a test auth token."""
    return "test-token-secret-123"


@pytest.fixture
def with_auth(auth_token):
    """Set up environment with auth token enabled."""
    old_value = os.environ.get("SPIRAL_DASHBOARD_AUTH_TOKEN")
    os.environ["SPIRAL_DASHBOARD_AUTH_TOKEN"] = auth_token
    # Re-import to reload the _AUTH_TOKEN global
    import importlib

    from lib.ui import spiral_live_server

    importlib.reload(spiral_live_server)
    yield
    if old_value is None:
        os.environ.pop("SPIRAL_DASHBOARD_AUTH_TOKEN", None)
    else:
        os.environ["SPIRAL_DASHBOARD_AUTH_TOKEN"] = old_value
    importlib.reload(spiral_live_server)


@pytest.fixture
def without_auth():
    """Ensure auth token is not set."""
    old_value = os.environ.get("SPIRAL_DASHBOARD_AUTH_TOKEN")
    os.environ.pop("SPIRAL_DASHBOARD_AUTH_TOKEN", None)
    # Re-import to reload the _AUTH_TOKEN global
    import importlib

    from lib.ui import spiral_live_server

    importlib.reload(spiral_live_server)
    yield
    if old_value is not None:
        os.environ["SPIRAL_DASHBOARD_AUTH_TOKEN"] = old_value
    importlib.reload(spiral_live_server)


# ── US-476: Mock Claude Client Fixture ──────────────────────────────────────


class MockClaudeClient:
    """Mock Claude API client for testing Phase R/S without live API calls."""

    def __init__(self, response_data=None, error_mode=None):
        """Initialize mock client.

        Args:
            response_data: Pre-recorded API response dict
            error_mode: "rate_limit" for 429, "malformed" for invalid JSON, None for success
        """
        self.response_data = response_data or self._default_response()
        self.error_mode = error_mode
        self.call_count = 0

    @staticmethod
    def _default_response():
        """Default Phase R research response."""
        return {
            "stories": [
                {
                    "id": "US-500",
                    "title": "Research Story 1: Weather Initiative",
                    "description": "Discovered story candidate from research phase",
                    "priority": "high",
                    "source": "https://research.example.com/story1",
                    "_source": "research",
                    "acceptanceCriteria": ["Criterion 1", "Criterion 2"],
                }
            ]
        }

    def chat_completion(self, messages, **kwargs):
        """Simulate Claude chat_completion API call.

        Args:
            messages: List of message dicts
            **kwargs: Additional API parameters (model, max_tokens, etc.)

        Returns:
            Dict with response or raises exception for error modes
        """
        self.call_count += 1

        # Simulate error modes
        if self.error_mode == "rate_limit":
            raise ValueError("429 Too Many Requests - Rate limited")
        if self.error_mode == "malformed":
            raise ValueError("Malformed JSON response from API")

        # Return success response
        return {
            "id": "msg_12345",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": json.dumps(self.response_data)}],
            "model": kwargs.get("model", "claude-3-5-sonnet-20241022"),
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 150, "output_tokens": 200},
        }


@pytest.fixture
def mock_claude_client():
    """Fixture: Provide a MockClaudeClient for testing.

    Returns a mock client that can be configured with different response modes.
    Tests can instantiate with custom response data or error modes.
    """
    return MockClaudeClient()


# ── US-693: Mock API fixtures for full SPIRAL loop integration tests ──────────


class MockClaudeAPI:
    """Mock Claude API with configurable response for Phase R/S/I testing."""

    def __init__(self, response_data: dict[str, object] | None = None) -> None:
        """Initialize mock Claude API.

        Args:
            response_data: Pre-recorded API response dict
        """
        self.response_data = response_data or self._default_response()
        self.call_count = 0

    @staticmethod
    def _default_response() -> dict[str, object]:
        """Default Phase R research response with story candidates."""
        return {
            "stories": [
                {
                    "id": "US-100",
                    "title": "Research Story 1",
                    "description": "Discovered from research phase",
                    "priority": "high",
                    "_source": "research",
                    "acceptanceCriteria": ["Criterion A", "Criterion B"],
                }
            ]
        }

    def messages_create(self, **kwargs: object) -> dict[str, object]:
        """Mock messages.create() API call.

        Returns:
            Dict with mocked Claude response
        """
        self.call_count += 1
        return {
            "id": f"msg_{self.call_count}",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": json.dumps(self.response_data)}],
            "model": "claude-3-5-sonnet-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 150, "output_tokens": 200},
        }


class MockGeminiAPI:
    """Mock Gemini API with configurable response for Phase R web search."""

    def __init__(self, response_data: dict[str, object] | None = None) -> None:
        """Initialize mock Gemini API.

        Args:
            response_data: Pre-recorded API response dict
        """
        self.response_data = response_data or self._default_response()
        self.call_count = 0

    @staticmethod
    def _default_response() -> dict[str, object]:
        """Default Gemini web search response."""
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "research_findings": [
                                            {
                                                "title": "Web Research Story 1",
                                                "url": "https://research.example.com",
                                                "summary": "Found via web research",
                                            }
                                        ]
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }

    def generate_content(self, **kwargs: object) -> dict[str, object]:
        """Mock generate_content() API call.

        Returns:
            Dict with mocked Gemini response
        """
        self.call_count += 1
        return self.response_data


@pytest.fixture
def mock_claude_api() -> MockClaudeAPI:
    """Fixture: Provide a MockClaudeAPI for Phase R/S/I integration testing.

    Returns a mock Claude API that simulates API responses without external calls.
    """
    return MockClaudeAPI()


@pytest.fixture
def mock_gemini_api() -> MockGeminiAPI:
    """Fixture: Provide a MockGeminiAPI for Phase R web search integration testing.

    Returns a mock Gemini API that simulates web search responses without external calls.
    """
    return MockGeminiAPI()
