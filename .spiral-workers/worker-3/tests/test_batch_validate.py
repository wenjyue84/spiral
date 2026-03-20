"""Unit tests for lib/batch_validate.py — request construction and response parsing.

These tests are fully offline: all HTTP calls are mocked so no real API key
or network access is required.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import batch_validate as bv

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _story(title: str = "Improve docs", description: str = "Add README") -> dict[str, Any]:
    return {"title": title, "description": description}


def _make_fake_response(data: Any, status: int = 200) -> MagicMock:
    """Return a mock context-manager response with .read() and iteration."""
    body = json.dumps(data).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _make_fake_jsonl_response(lines: list[Any]) -> MagicMock:
    """Return a mock context-manager response whose __iter__ yields JSONL lines."""
    encoded_lines = [json.dumps(line).encode("utf-8") for line in lines]
    mock_resp = MagicMock()
    mock_resp.__iter__ = MagicMock(return_value=iter(encoded_lines))
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# TestBuildBatchRequests
# ---------------------------------------------------------------------------


class TestBuildBatchRequests:
    """Tests for build_batch_requests()."""

    def test_returns_one_request_per_story(self) -> None:
        stories = [_story("S1"), _story("S2"), _story("S3")]
        reqs = bv.build_batch_requests(stories, "goal text", [])
        assert len(reqs) == 3

    def test_custom_id_uses_story_field(self) -> None:
        stories = [{"title": "A", "description": "", "_custom_id": "my-id"}]
        reqs = bv.build_batch_requests(stories, "goals", [])
        assert reqs[0]["custom_id"] == "my-id"

    def test_custom_id_defaults_to_index(self) -> None:
        stories = [_story("A"), _story("B")]
        reqs = bv.build_batch_requests(stories, "goals", [])
        assert reqs[0]["custom_id"] == "story-0"
        assert reqs[1]["custom_id"] == "story-1"

    def test_request_has_required_params_fields(self) -> None:
        stories = [_story()]
        reqs = bv.build_batch_requests(stories, "build a product", [])
        params = reqs[0]["params"]
        assert "model" in params
        assert "max_tokens" in params
        assert "messages" in params
        assert len(params["messages"]) == 1
        assert params["messages"][0]["role"] == "user"

    def test_prompt_contains_story_title(self) -> None:
        stories = [_story(title="Unique title XYZ")]
        reqs = bv.build_batch_requests(stories, "goals", [])
        prompt = reqs[0]["params"]["messages"][0]["content"]
        assert "Unique title XYZ" in prompt

    def test_prompt_contains_goal_text(self) -> None:
        stories = [_story()]
        reqs = bv.build_batch_requests(stories, "Build a rocket", [])
        prompt = reqs[0]["params"]["messages"][0]["content"]
        assert "Build a rocket" in prompt

    def test_prompt_contains_forbidden_phrases(self) -> None:
        stories = [_story()]
        reqs = bv.build_batch_requests(stories, "goals", ["delete everything", "rm -rf"])
        prompt = reqs[0]["params"]["messages"][0]["content"]
        assert "delete everything" in prompt
        assert "rm -rf" in prompt

    def test_empty_stories_returns_empty_list(self) -> None:
        assert bv.build_batch_requests([], "goals", []) == []

    def test_model_is_set(self) -> None:
        stories = [_story()]
        reqs = bv.build_batch_requests(stories, "goals", [])
        assert reqs[0]["params"]["model"] == bv._BATCH_MODEL


# ---------------------------------------------------------------------------
# TestParseBatchResults
# ---------------------------------------------------------------------------


class TestParseBatchResults:
    """Tests for parse_batch_results()."""

    def _make_succeeded(self, custom_id: str, text: str) -> dict[str, Any]:
        return {
            "custom_id": custom_id,
            "result": {
                "type": "succeeded",
                "message": {"content": [{"type": "text", "text": text}]},
            },
        }

    def _make_errored(self, custom_id: str, error_type: str = "server_error") -> dict[str, Any]:
        return {
            "custom_id": custom_id,
            "result": {"type": "errored", "error": {"type": error_type}},
        }

    def test_accepted_true(self) -> None:
        raw = [self._make_succeeded("s0", '{"accepted": true, "reason": "ok"}')]
        out = bv.parse_batch_results(raw)
        assert out["s0"]["accepted"] is True
        assert out["s0"]["reason"] == "ok"

    def test_accepted_false(self) -> None:
        raw = [self._make_succeeded("s0", '{"accepted": false, "reason": "off-topic"}')]
        out = bv.parse_batch_results(raw)
        assert out["s0"]["accepted"] is False
        assert "off-topic" in out["s0"]["reason"]

    def test_defaults_to_accept_on_parse_error(self) -> None:
        raw = [self._make_succeeded("s0", "not valid json at all")]
        out = bv.parse_batch_results(raw)
        assert out["s0"]["accepted"] is True
        assert "parse_error" in out["s0"]["reason"]

    def test_defaults_to_accept_on_errored_result(self) -> None:
        raw = [self._make_errored("s1")]
        out = bv.parse_batch_results(raw)
        assert out["s1"]["accepted"] is True
        assert "errored" in out["s1"]["reason"]

    def test_multiple_results(self) -> None:
        raw = [
            self._make_succeeded("s0", '{"accepted": true, "reason": "good"}'),
            self._make_succeeded("s1", '{"accepted": false, "reason": "bad"}'),
            self._make_errored("s2"),
        ]
        out = bv.parse_batch_results(raw)
        assert len(out) == 3
        assert out["s0"]["accepted"] is True
        assert out["s1"]["accepted"] is False
        assert out["s2"]["accepted"] is True

    def test_markdown_fenced_json_parsed(self) -> None:
        text = '```json\n{"accepted": false, "reason": "violates"}\n```'
        raw = [self._make_succeeded("s0", text)]
        out = bv.parse_batch_results(raw)
        assert out["s0"]["accepted"] is False

    def test_empty_results_returns_empty_dict(self) -> None:
        assert bv.parse_batch_results([]) == {}

    def test_missing_content_block_defaults_accept(self) -> None:
        raw = [
            {
                "custom_id": "s0",
                "result": {"type": "succeeded", "message": {"content": []}},
            }
        ]
        out = bv.parse_batch_results(raw)
        assert out["s0"]["accepted"] is True


# ---------------------------------------------------------------------------
# TestSubmitBatch
# ---------------------------------------------------------------------------


class TestSubmitBatch:
    """Tests for submit_batch() — mocks urlopen."""

    def test_posts_to_correct_endpoint(self) -> None:
        response = _make_fake_response({"id": "batch_abc", "processing_status": "in_progress"})
        with patch("urllib.request.urlopen", return_value=response) as mock_open:
            _result = bv.submit_batch([{"custom_id": "s0", "params": {}}], "sk-test", "https://api.test")
        call_args = mock_open.call_args
        req = call_args[0][0]
        assert req.full_url == "https://api.test/v1/messages/batches"
        assert req.method == "POST"

    def test_returns_batch_id(self) -> None:
        response = _make_fake_response({"id": "msgbatch_123", "processing_status": "in_progress"})
        with patch("urllib.request.urlopen", return_value=response):
            result = bv.submit_batch([], "sk-test")
        assert result["id"] == "msgbatch_123"

    def test_api_key_in_header(self) -> None:
        response = _make_fake_response({"id": "b1", "processing_status": "in_progress"})
        with patch("urllib.request.urlopen", return_value=response) as mock_open:
            bv.submit_batch([], "my-secret-key")
        req = mock_open.call_args[0][0]
        assert req.headers.get("X-api-key") == "my-secret-key"


# ---------------------------------------------------------------------------
# TestPollBatch
# ---------------------------------------------------------------------------


class TestPollBatch:
    """Tests for poll_batch() — mocks _get_batch_status and _get_batch_results."""

    def test_returns_results_when_ended_immediately(self) -> None:
        status = {"processing_status": "ended"}
        results = [{"custom_id": "s0", "result": {"type": "succeeded", "message": {"content": []}}}]
        with (
            patch.object(bv, "_get_batch_status", return_value=status),
            patch.object(bv, "_get_batch_results", return_value=results),
        ):
            out = bv.poll_batch("batch_1", "key")
        assert out == results

    def test_polls_until_ended(self) -> None:
        statuses = [
            {"processing_status": "in_progress"},
            {"processing_status": "in_progress"},
            {"processing_status": "ended"},
        ]
        results: list[dict[str, Any]] = []
        calls: list[int] = []

        def fake_status(bid: str, key: str, base: str) -> dict[str, Any]:
            calls.append(1)
            return statuses[len(calls) - 1]

        with (
            patch.object(bv, "_get_batch_status", side_effect=fake_status),
            patch.object(bv, "_get_batch_results", return_value=results),
            patch("time.sleep"),  # don't actually sleep
        ):
            out = bv.poll_batch("batch_1", "key")

        assert len(calls) == 3
        assert out == results

    def test_raises_timeout_if_never_ends(self) -> None:
        with (
            patch.object(bv, "_get_batch_status", return_value={"processing_status": "in_progress"}),
            patch("time.sleep"),
            patch("time.monotonic", side_effect=[0.0, 0.5, 999.0]),
        ):
            with pytest.raises(TimeoutError, match="did not complete"):
                bv.poll_batch("batch_1", "key", max_wait_sec=1.0)


# ---------------------------------------------------------------------------
# TestPollBatchUntilComplete
# ---------------------------------------------------------------------------


class TestPollBatchUntilComplete:
    """Tests for poll_batch_until_complete() — uses mock Anthropic SDK client."""

    def _make_batch(self, status: str) -> MagicMock:
        """Return a mock batch object with the given processing_status."""
        batch = MagicMock()
        batch.processing_status = status
        return batch

    def test_returns_results_when_ended_immediately(self) -> None:
        client = MagicMock()
        client.beta.messages.batches.retrieve.return_value = self._make_batch("ended")
        results = MagicMock()
        client.beta.messages.batches.results.return_value = results

        out = bv.poll_batch_until_complete("batch_1", client)

        assert out is results
        client.beta.messages.batches.retrieve.assert_called_once_with("batch_1")
        client.beta.messages.batches.results.assert_called_once_with("batch_1")

    def test_polls_until_ended(self) -> None:
        client = MagicMock()
        statuses = ["in_progress", "in_progress", "ended"]
        client.beta.messages.batches.retrieve.side_effect = [self._make_batch(s) for s in statuses]
        results = MagicMock()
        client.beta.messages.batches.results.return_value = results

        with patch("time.sleep"):
            out = bv.poll_batch_until_complete("batch_1", client)

        assert out is results
        assert client.beta.messages.batches.retrieve.call_count == 3

    def test_raises_timeout_if_never_ends(self) -> None:
        client = MagicMock()
        client.beta.messages.batches.retrieve.return_value = self._make_batch("in_progress")

        with (
            patch("time.sleep"),
            patch("time.monotonic", side_effect=[0.0, 0.5, 999.0]),
        ):
            with pytest.raises(TimeoutError, match="did not complete"):
                bv.poll_batch_until_complete("batch_1", client, max_wait_sec=1.0)

    def test_backoff_starts_at_2s_and_doubles(self) -> None:
        client = MagicMock()
        # 6 in_progress then ended → 6 sleeps recorded
        statuses = ["in_progress"] * 6 + ["ended"]
        client.beta.messages.batches.retrieve.side_effect = [self._make_batch(s) for s in statuses]
        client.beta.messages.batches.results.return_value = MagicMock()

        sleep_calls: list[float] = []
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            bv.poll_batch_until_complete("batch_1", client)

        # Expected: 2, 4, 8, 16, 32, 60 (capped)
        assert sleep_calls[0] == 2.0
        assert sleep_calls[1] == 4.0
        assert sleep_calls[2] == 8.0
        assert sleep_calls[3] == 16.0
        assert sleep_calls[4] == 32.0
        assert sleep_calls[5] == 60.0

    def test_backoff_stays_capped_at_60(self) -> None:
        client = MagicMock()
        # Enough in_progress to confirm cap persists
        statuses = ["in_progress"] * 9 + ["ended"]
        client.beta.messages.batches.retrieve.side_effect = [self._make_batch(s) for s in statuses]
        client.beta.messages.batches.results.return_value = MagicMock()

        sleep_calls: list[float] = []
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            bv.poll_batch_until_complete("batch_1", client)

        # After hitting 60s cap (at index 5), all subsequent sleeps are 60s
        assert sleep_calls[5] == 60.0
        assert sleep_calls[6] == 60.0
        assert sleep_calls[7] == 60.0
        assert sleep_calls[8] == 60.0

    def test_default_max_wait_is_3600(self) -> None:
        """Verifies the function signature default without actually waiting."""
        client = MagicMock()
        client.beta.messages.batches.retrieve.return_value = self._make_batch("ended")
        client.beta.messages.batches.results.return_value = MagicMock()
        import inspect

        sig = inspect.signature(bv.poll_batch_until_complete)
        assert sig.parameters["max_wait_sec"].default == 3600.0


# ---------------------------------------------------------------------------
# TestValidateStorySync
# ---------------------------------------------------------------------------


class TestValidateStorySync:
    """Tests for validate_story_sync() — mocks urlopen."""

    def test_accepted_story(self) -> None:
        body = {"content": [{"type": "text", "text": '{"accepted": true, "reason": "fits goals"}'}]}
        response = _make_fake_response(body)
        with patch("urllib.request.urlopen", return_value=response):
            ok, reason = bv.validate_story_sync(_story(), "goals", [], "sk-test")
        assert ok is True
        assert "fits goals" in reason

    def test_rejected_story(self) -> None:
        body = {"content": [{"type": "text", "text": '{"accepted": false, "reason": "off-topic"}'}]}
        response = _make_fake_response(body)
        with patch("urllib.request.urlopen", return_value=response):
            ok, reason = bv.validate_story_sync(_story(), "goals", [], "sk-test")
        assert ok is False
        assert "off-topic" in reason

    def test_posts_to_messages_endpoint(self) -> None:
        body = {"content": [{"type": "text", "text": '{"accepted": true, "reason": "ok"}'}]}
        response = _make_fake_response(body)
        with patch("urllib.request.urlopen", return_value=response) as mock_open:
            bv.validate_story_sync(_story(), "goals", [], "key", "https://api.example")
        req = mock_open.call_args[0][0]
        assert req.full_url == "https://api.example/v1/messages"


# ---------------------------------------------------------------------------
# TestValidateStorySyncVotes
# ---------------------------------------------------------------------------


class TestValidateStorySyncVotes:
    """Tests for validate_story_sync_votes() — majority voting with mocked urlopen."""

    def test_single_vote_behaves_like_sync(self) -> None:
        """With num_votes=1, should behave identically to validate_story_sync (no voting overhead)."""
        body = {"content": [{"type": "text", "text": '{"accepted": true, "reason": "fits goals"}'}]}
        response = _make_fake_response(body)
        with patch("urllib.request.urlopen", return_value=response):
            ok, reason, votes_accept, votes_reject = bv.validate_story_sync_votes(
                _story(), "goals", [], "sk-test", num_votes=1
            )
        assert ok is True
        assert votes_accept == 1
        assert votes_reject == 0

    def test_three_votes_majority_accept(self) -> None:
        """With 3 votes: 2 accept, 1 reject → final decision is accept."""
        body_accept = {"content": [{"type": "text", "text": '{"accepted": true, "reason": "ok"}'}]}
        body_reject = {"content": [{"type": "text", "text": '{"accepted": false, "reason": "no"}'}]}
        responses = [
            _make_fake_response(body_accept),
            _make_fake_response(body_accept),
            _make_fake_response(body_reject),
        ]

        with patch("urllib.request.urlopen", side_effect=responses):
            ok, reason, votes_accept, votes_reject = bv.validate_story_sync_votes(
                _story(), "goals", [], "sk-test", num_votes=3
            )
        assert ok is True
        assert votes_accept == 2
        assert votes_reject == 1
        assert "Voting" in reason

    def test_three_votes_majority_reject(self) -> None:
        """With 3 votes: 1 accept, 2 reject → final decision is reject."""
        body_accept = {"content": [{"type": "text", "text": '{"accepted": true, "reason": "ok"}'}]}
        body_reject = {"content": [{"type": "text", "text": '{"accepted": false, "reason": "no"}'}]}
        responses = [
            _make_fake_response(body_accept),
            _make_fake_response(body_reject),
            _make_fake_response(body_reject),
        ]

        with patch("urllib.request.urlopen", side_effect=responses):
            ok, reason, votes_accept, votes_reject = bv.validate_story_sync_votes(
                _story(), "goals", [], "sk-test", num_votes=3
            )
        assert ok is False
        assert votes_accept == 1
        assert votes_reject == 2
        assert "Voting" in reason

    def test_tie_defaults_to_reject(self) -> None:
        """With 2 votes: 1 accept, 1 reject → tie defaults to reject."""
        body_accept = {"content": [{"type": "text", "text": '{"accepted": true, "reason": "ok"}'}]}
        body_reject = {"content": [{"type": "text", "text": '{"accepted": false, "reason": "no"}'}]}
        responses = [
            _make_fake_response(body_accept),
            _make_fake_response(body_reject),
        ]

        with patch("urllib.request.urlopen", side_effect=responses):
            ok, reason, votes_accept, votes_reject = bv.validate_story_sync_votes(
                _story(), "goals", [], "sk-test", num_votes=2
            )
        assert ok is False
        assert votes_accept == 1
        assert votes_reject == 1

    def test_five_votes_mixed(self) -> None:
        """With 5 votes: 3 accept, 2 reject → final decision is accept."""
        body_accept = {"content": [{"type": "text", "text": '{"accepted": true, "reason": "ok"}'}]}
        body_reject = {"content": [{"type": "text", "text": '{"accepted": false, "reason": "no"}'}]}
        responses = [
            _make_fake_response(body_accept),
            _make_fake_response(body_accept),
            _make_fake_response(body_accept),
            _make_fake_response(body_reject),
            _make_fake_response(body_reject),
        ]

        with patch("urllib.request.urlopen", side_effect=responses):
            ok, reason, votes_accept, votes_reject = bv.validate_story_sync_votes(
                _story(), "goals", [], "sk-test", num_votes=5
            )
        assert ok is True
        assert votes_accept == 3
        assert votes_reject == 2
