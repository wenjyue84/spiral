"""tests/test_token_guard.py — Unit tests for lib/token_guard.py (US-408).

Tests:
- count_tokens uses Anthropic API when SDK + key available
- count_tokens falls back to approximation when SDK missing
- count_tokens falls back to approximation when API key not set
- guard_story returns story unchanged when under budget
- guard_story trims and emits event when over budget
- CLI: stdout is valid JSON, stderr warning on truncation
- CLI: empty stdin returns exit code 1
- estimate_pending_tokens counts over-budget stories correctly
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add lib/ to path so token_guard can be imported directly
LIB_DIR = str(Path(__file__).parent.parent / "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

import token_guard  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MINIMAL_STORY: dict = {
    "id": "US-999",
    "title": "Test story",
    "description": "A short description.",
    "acceptanceCriteria": ["AC1", "AC2"],
    "passes": False,
}

_LARGE_STORY: dict = {
    "id": "US-998",
    "title": "Large story",
    "description": "A" * 300_000,  # ~75 000 tokens approximation
    "_researchOutput": "B" * 300_000,
    "acceptanceCriteria": ["AC"],
    "passes": False,
}


# ---------------------------------------------------------------------------
# count_tokens_anthropic
# ---------------------------------------------------------------------------


class TestCountTokensAnthropic(unittest.TestCase):
    def test_returns_none_when_sdk_missing(self):
        """Should return None when 'anthropic' package cannot be imported."""
        with patch.dict("sys.modules", {"anthropic": None}):
            result = token_guard.count_tokens_anthropic([{"role": "user", "content": "hello"}], "sonnet")
        self.assertIsNone(result)

    def test_returns_none_when_api_key_absent(self):
        """Should return None when ANTHROPIC_API_KEY is empty."""
        mock_anthropic = MagicMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
            with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
                result = token_guard.count_tokens_anthropic([{"role": "user", "content": "hello"}], "sonnet")
        self.assertIsNone(result)
        # Client should NOT have been constructed without a key
        mock_anthropic.Anthropic.assert_not_called()

    def test_calls_api_and_returns_input_tokens(self):
        """Should call count_tokens API and return input_tokens value."""
        mock_response = MagicMock()
        mock_response.input_tokens = 42

        mock_client = MagicMock()
        mock_client.beta.messages.count_tokens.return_value = mock_response

        mock_anthropic = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        messages = [{"role": "user", "content": "hello world"}]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
            with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
                result = token_guard.count_tokens_anthropic(messages, "sonnet")

        self.assertEqual(result, 42)
        mock_client.beta.messages.count_tokens.assert_called_once()
        call_kwargs = mock_client.beta.messages.count_tokens.call_args
        self.assertIn("token-counting-2024-11-01", call_kwargs.kwargs.get("betas", []))

    def test_returns_none_on_api_error(self):
        """Should return None (not raise) when the API call fails."""
        mock_client = MagicMock()
        mock_client.beta.messages.count_tokens.side_effect = RuntimeError("network error")

        mock_anthropic = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
            with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
                result = token_guard.count_tokens_anthropic([{"role": "user", "content": "hi"}], "sonnet")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# count_tokens (public function with fallback)
# ---------------------------------------------------------------------------


class TestCountTokens(unittest.TestCase):
    def test_uses_api_when_available(self):
        """count_tokens returns (api_result, 'anthropic_api') when SDK works."""
        with patch.object(token_guard, "count_tokens_anthropic", return_value=100):
            count, method = token_guard.count_tokens([{"role": "user", "content": "test"}], "sonnet")
        self.assertEqual(count, 100)
        self.assertEqual(method, "anthropic_api")

    def test_falls_back_to_approx_when_api_returns_none(self):
        """count_tokens returns (approx, 'approx') when API is unavailable."""
        with patch.object(token_guard, "count_tokens_anthropic", return_value=None):
            count, method = token_guard.count_tokens([{"role": "user", "content": "hello"}], "sonnet")
        self.assertGreater(count, 0)
        self.assertEqual(method, "approx")


# ---------------------------------------------------------------------------
# guard_story
# ---------------------------------------------------------------------------


class TestGuardStory(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp()

    def test_no_trim_when_under_budget(self):
        """Small story under budget should be returned unchanged."""
        with patch.object(token_guard, "count_tokens_anthropic", return_value=100):
            trimmed, count, was_truncated = token_guard.guard_story(
                _MINIMAL_STORY,
                model="sonnet",
                budget=150_000,
                scratch_dir=self.scratch,
            )
        self.assertFalse(was_truncated)
        self.assertEqual(trimmed["id"], "US-999")
        self.assertEqual(count, 100)

    def test_truncates_when_over_budget(self):
        """Story over budget should be trimmed and was_truncated=True."""
        # count_tokens returns over-budget count; API not mocked so falls back to approx
        # _LARGE_STORY has ~600k chars so approx tokens >> default budget
        with patch.object(token_guard, "count_tokens_anthropic", return_value=None):
            trimmed, count, was_truncated = token_guard.guard_story(
                _LARGE_STORY,
                model="sonnet",
                budget=1_000,  # extremely low budget to force truncation
                scratch_dir=self.scratch,
            )
        self.assertTrue(was_truncated)
        # _researchOutput should be stripped (first in TRUNCATION_ORDER)
        self.assertNotIn("_researchOutput", trimmed)
        # Core fields must remain
        self.assertEqual(trimmed["id"], "US-998")

    def test_emits_event_to_jsonl_when_truncated(self):
        """A token_budget_exceeded event must be written to spiral_events.jsonl."""
        with patch.object(token_guard, "count_tokens_anthropic", return_value=None):
            token_guard.guard_story(
                _LARGE_STORY,
                model="sonnet",
                budget=1_000,
                scratch_dir=self.scratch,
            )
        events_path = os.path.join(self.scratch, "spiral_events.jsonl")
        self.assertTrue(os.path.isfile(events_path), "spiral_events.jsonl not created")
        with open(events_path, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertTrue(any(e.get("event") == "token_budget_exceeded" for e in lines))
        evt = next(e for e in lines if e.get("event") == "token_budget_exceeded")
        self.assertEqual(evt["story_id"], "US-998")
        self.assertIn("dropped_fields", evt)
        self.assertIn("method", evt)

    def test_no_event_when_under_budget(self):
        """No event should be written when the story fits within budget."""
        with patch.object(token_guard, "count_tokens_anthropic", return_value=50):
            token_guard.guard_story(
                _MINIMAL_STORY,
                model="sonnet",
                budget=150_000,
                scratch_dir=self.scratch,
            )
        events_path = os.path.join(self.scratch, "spiral_events.jsonl")
        if os.path.isfile(events_path):
            with open(events_path, encoding="utf-8") as f:
                lines = [json.loads(line) for line in f if line.strip()]
            self.assertEqual(lines, [])


# ---------------------------------------------------------------------------
# CLI (main function)
# ---------------------------------------------------------------------------


class TestTokenGuardCLI(unittest.TestCase):
    def test_cli_emits_json_on_stdout(self):
        """CLI should output valid JSON story to stdout."""
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with patch.object(token_guard, "count_tokens_anthropic", return_value=50):
            with redirect_stdout(buf):
                rc = token_guard.main(["--story", json.dumps(_MINIMAL_STORY), "--budget", "150000"])
        self.assertEqual(rc, 0)
        result = json.loads(buf.getvalue())
        self.assertEqual(result["id"], "US-999")

    def test_cli_returns_1_on_empty_input(self):
        """CLI should return exit code 1 when no story JSON is provided."""
        import io

        buf = io.StringIO("")
        with patch("sys.stdin", buf):
            rc = token_guard.main([])
        self.assertEqual(rc, 1)

    def test_cli_returns_1_on_invalid_json(self):
        """CLI should return exit code 1 on invalid JSON input."""
        rc = token_guard.main(["--story", "not-json"])
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# estimate_pending_tokens
# ---------------------------------------------------------------------------


class TestEstimatePendingTokens(unittest.TestCase):
    def test_counts_over_budget_stories(self):
        """estimate_pending_tokens should count stories whose approx tokens exceed budget."""
        prd = {
            "userStories": [
                {"id": "US-1", "passes": False, "description": "short"},
                {
                    "id": "US-2",
                    "passes": False,
                    "description": "X" * 800_000,  # > 150k token approx
                },
                {"id": "US-3", "passes": True, "description": "done"},
            ]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(prd, f)
            prd_path = f.name

        try:
            stats = token_guard.estimate_pending_tokens(prd_path, model="sonnet", budget=150_000)
        finally:
            os.unlink(prd_path)

        self.assertEqual(stats["pending"], 2)  # US-3 is passed
        self.assertEqual(stats["over_budget"], 1)  # only US-2 is large
        self.assertEqual(stats["budget"], 150_000)

    def test_returns_zeros_when_prd_missing(self):
        stats = token_guard.estimate_pending_tokens("/nonexistent/prd.json")
        self.assertEqual(stats["pending"], 0)
        self.assertEqual(stats["over_budget"], 0)


if __name__ == "__main__":
    unittest.main()
