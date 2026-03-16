#!/usr/bin/env python3
"""
lib/batch_validate.py — Anthropic Message Batches API client for Phase S (US-390).

Submits story validation requests in bulk (50% cost vs sequential).
Falls back to a direct synchronous Messages API call for single-story runs.

Required env var: ANTHROPIC_API_KEY
Optional env var: SPIRAL_BATCH_API_URL (default: https://api.anthropic.com)

Public API
----------
build_batch_requests(stories, goal_text, forbidden_phrases)
    Build a list of batch request dicts (one per story).

submit_batch(requests, api_key, base_url)
    POST to /v1/messages/batches. Returns the batch response dict.

poll_batch(batch_id, api_key, base_url, max_wait_sec)
    Poll until processing_status == "ended". Returns list of result dicts.

parse_batch_results(results)
    Parse raw results into dict[custom_id -> {accepted, reason}].

validate_story_sync(story, goal_text, forbidden_phrases, api_key, base_url)
    Single-story synchronous fallback via direct /v1/messages call.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

__all__ = [
    "build_batch_requests",
    "submit_batch",
    "poll_batch",
    "poll_batch_until_complete",
    "parse_batch_results",
    "validate_story_sync",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL: str = "https://api.anthropic.com"
_API_VERSION: str = "2023-06-01"

# Use haiku (cheapest) for validation requests
_BATCH_MODEL: str = "claude-haiku-4-5-20251001"
_MAX_TOKENS: int = 256

# Polling: exponential backoff capped at 60 s
_POLL_INITIAL_SLEEP: float = 5.0
_POLL_MAX_SLEEP: float = 60.0
_POLL_BACKOFF: float = 1.5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": _API_VERSION,
        "content-type": "application/json",
    }


def _story_validation_prompt(
    story: dict[str, Any],
    goal_text: str,
    forbidden_phrases: list[str],
) -> str:
    """Build a validation prompt for a single story."""
    title = story.get("title", "")
    description = story.get("description", "")
    forbidden_block = (
        "\nForbidden topics (reject if matched): " + "; ".join(forbidden_phrases) if forbidden_phrases else ""
    )
    return (
        "You are a strict story validator for a software project.\n\n"
        f"Project goals:\n{goal_text}\n"
        f"{forbidden_block}\n\n"
        f"Story title: {title}\n"
        f"Story description: {description}\n\n"
        "Does this story align with the project goals and not violate forbidden topics?\n"
        'Respond ONLY with a JSON object: {"accepted": true or false, "reason": "brief reason"}'
    )


def _parse_llm_json(text: str) -> tuple[bool, str]:
    """Parse LLM text output into (accepted, reason). Defaults to accept on parse failure."""
    # Strip optional markdown fences
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        inner = [line for line in lines if not line.startswith("```")]
        cleaned = "\n".join(inner).strip()
    try:
        data: dict[str, Any] = json.loads(cleaned)
        accepted = bool(data.get("accepted", True))
        reason = str(data.get("reason", ""))
        return accepted, reason
    except (json.JSONDecodeError, TypeError, AttributeError):
        return True, f"parse_error: {text[:120]}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_batch_requests(
    stories: list[dict[str, Any]],
    goal_text: str,
    forbidden_phrases: list[str],
) -> list[dict[str, Any]]:
    """Build a list of batch request dicts (one per story).

    Each story must have a ``_custom_id`` field set before calling this
    function (use the story index as fallback if absent).

    Parameters
    ----------
    stories:
        List of story dicts. Each should have ``title`` and ``description``.
    goal_text:
        Concatenated project goals as a single string.
    forbidden_phrases:
        Phrases from the constitution that should trigger rejection.

    Returns
    -------
    list[dict[str, Any]]
        Batch request objects ready to POST to the API.
    """
    requests: list[dict[str, Any]] = []
    for i, story in enumerate(stories):
        custom_id = str(story.get("_custom_id", f"story-{i}"))
        requests.append(
            {
                "custom_id": custom_id,
                "params": {
                    "model": _BATCH_MODEL,
                    "max_tokens": _MAX_TOKENS,
                    "messages": [
                        {
                            "role": "user",
                            "content": _story_validation_prompt(story, goal_text, forbidden_phrases),
                        }
                    ],
                },
            }
        )
    return requests


def submit_batch(
    requests: list[dict[str, Any]],
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """POST to ``/v1/messages/batches``. Returns the batch response dict.

    The response includes an ``id`` field (the batch ID) and
    ``processing_status`` (initially ``"in_progress"``).

    Parameters
    ----------
    requests:
        List of batch request objects from :func:`build_batch_requests`.
    api_key:
        Anthropic API key.
    base_url:
        API base URL (override for testing).

    Returns
    -------
    dict[str, Any]
        Parsed batch creation response.

    Raises
    ------
    urllib.error.HTTPError
        On HTTP error responses from the API.
    """
    url = f"{base_url}/v1/messages/batches"
    payload = json.dumps({"requests": requests}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers=_make_headers(api_key),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return dict(json.loads(resp.read().decode("utf-8")))


def _get_batch_status(
    batch_id: str,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """GET ``/v1/messages/batches/{id}`` and return parsed response."""
    url = f"{base_url}/v1/messages/batches/{batch_id}"
    req = urllib.request.Request(url, headers=_make_headers(api_key), method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return dict(json.loads(resp.read().decode("utf-8")))


def _get_batch_results(
    batch_id: str,
    api_key: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """GET ``/v1/messages/batches/{id}/results`` and parse the JSONL stream."""
    url = f"{base_url}/v1/messages/batches/{batch_id}/results"
    req = urllib.request.Request(url, headers=_make_headers(api_key), method="GET")
    results: list[dict[str, Any]] = []
    with urllib.request.urlopen(req, timeout=60) as resp:
        for raw_line in resp:
            line = raw_line.strip()
            if line:
                results.append(dict(json.loads(line.decode("utf-8"))))
    return results


def poll_batch(
    batch_id: str,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    max_wait_sec: float = 3600.0,
) -> list[dict[str, Any]]:
    """Poll the batch until ``processing_status == "ended"``.

    Uses exponential backoff starting at ``_POLL_INITIAL_SLEEP`` seconds,
    capped at ``_POLL_MAX_SLEEP`` seconds.

    Parameters
    ----------
    batch_id:
        The batch ID returned by :func:`submit_batch`.
    api_key:
        Anthropic API key.
    base_url:
        API base URL (override for testing).
    max_wait_sec:
        Maximum seconds to wait before raising :class:`TimeoutError`.

    Returns
    -------
    list[dict[str, Any]]
        Raw result objects (one per batch request).

    Raises
    ------
    TimeoutError
        If the batch does not complete within ``max_wait_sec``.
    """
    sleep_sec = _POLL_INITIAL_SLEEP
    deadline = time.monotonic() + max_wait_sec
    while time.monotonic() < deadline:
        status = _get_batch_status(batch_id, api_key, base_url)
        if status.get("processing_status") == "ended":
            return _get_batch_results(batch_id, api_key, base_url)
        time.sleep(sleep_sec)
        sleep_sec = min(sleep_sec * _POLL_BACKOFF, _POLL_MAX_SLEEP)
    raise TimeoutError(f"Batch {batch_id!r} did not complete within {max_wait_sec:.0f}s")


def poll_batch_until_complete(
    batch_id: str,
    client: Any,
    max_wait_sec: float = 3600.0,
) -> Any:
    """Poll the batch using the Anthropic SDK client until ``processing_status == "ended"``.

    Uses exponential backoff starting at 2 seconds, doubling each attempt,
    capped at 60 seconds.

    Parameters
    ----------
    batch_id:
        The batch ID returned by the Message Batches API.
    client:
        Anthropic SDK client with a ``beta.messages.batches`` interface.
        Must support ``retrieve(batch_id)`` and ``results(batch_id)`` methods.
    max_wait_sec:
        Maximum seconds to wait before raising :class:`TimeoutError`
        (default 3600s).

    Returns
    -------
    Any
        The completed batch results iterable from
        ``client.beta.messages.batches.results(batch_id)``.

    Raises
    ------
    TimeoutError
        If the batch does not complete within ``max_wait_sec``.
    """
    sleep_sec: float = 2.0
    deadline = time.monotonic() + max_wait_sec
    while time.monotonic() < deadline:
        batch = client.beta.messages.batches.retrieve(batch_id)
        if getattr(batch, "processing_status", None) == "ended":
            return client.beta.messages.batches.results(batch_id)
        time.sleep(sleep_sec)
        sleep_sec = min(sleep_sec * 2.0, 60.0)
    raise TimeoutError(f"Batch {batch_id!r} did not complete within {max_wait_sec:.0f}s")


def parse_batch_results(
    results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Parse raw batch result objects into a decision map.

    Parameters
    ----------
    results:
        Raw result dicts from :func:`poll_batch`.

    Returns
    -------
    dict[str, dict[str, Any]]
        Maps ``custom_id`` → ``{"accepted": bool, "reason": str}``.
        Errored or unparseable results default to ``accepted=True``.
    """
    parsed: dict[str, dict[str, Any]] = {}
    for item in results:
        custom_id = str(item.get("custom_id", ""))
        result = item.get("result", {})
        result_type = result.get("type", "unknown") if isinstance(result, dict) else "unknown"

        if result_type == "succeeded":
            message = result.get("message", {}) if isinstance(result, dict) else {}
            content = message.get("content", []) if isinstance(message, dict) else []
            text = ""
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = str(block.get("text", ""))
                    break
            accepted, reason = _parse_llm_json(text)
        else:
            # errored / canceled / expired → default accept (non-fatal)
            accepted = True
            reason = f"batch_result_type={result_type}"

        parsed[custom_id] = {"accepted": accepted, "reason": reason}
    return parsed


def validate_story_sync(
    story: dict[str, Any],
    goal_text: str,
    forbidden_phrases: list[str],
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
) -> tuple[bool, str]:
    """Single-story synchronous fallback via direct ``/v1/messages`` call.

    Used when batch_size == 1 or when the caller opts out of batching.

    Parameters
    ----------
    story:
        Story dict with ``title`` and ``description`` fields.
    goal_text:
        Concatenated project goals as a single string.
    forbidden_phrases:
        Phrases from the constitution.
    api_key:
        Anthropic API key.
    base_url:
        API base URL (override for testing).

    Returns
    -------
    tuple[bool, str]
        ``(accepted, reason)`` pair.
    """
    url = f"{base_url}/v1/messages"
    payload = json.dumps(
        {
            "model": _BATCH_MODEL,
            "max_tokens": _MAX_TOKENS,
            "messages": [
                {
                    "role": "user",
                    "content": _story_validation_prompt(story, goal_text, forbidden_phrases),
                }
            ],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers=_make_headers(api_key),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data: dict[str, Any] = dict(json.loads(resp.read().decode("utf-8")))

    content = data.get("content", [])
    text = ""
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = str(block.get("text", ""))
            break
    return _parse_llm_json(text)
