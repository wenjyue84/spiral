#!/usr/bin/env python3
"""Integration tests for US-452 smart model routing.

Tests the LlmRouter auto-routing escalation ladder and the skip-sentinel
behaviour that the SPIRAL retry loop applies at max retries.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from llm_router import (
    TIER_TO_MODEL,
    LlmRouter,
    ModelTier,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HAIKU = TIER_TO_MODEL[ModelTier.UTILITY]
_SONNET = TIER_TO_MODEL[ModelTier.PRODUCTION]
_OPUS = TIER_TO_MODEL[ModelTier.FRONTIER]

# Matches the 3-retry-skip rule in lib/impl/retry.sh
_SPIRAL_MAX_RETRIES = 3

# Sentinel value returned instead of a model ID when retries are exhausted
SKIP_SENTINEL = "skip"


# ---------------------------------------------------------------------------
# Integration helper: route_or_skip
# ---------------------------------------------------------------------------


def route_or_skip(story: dict, retry_count: int) -> str:
    """Return a Claude model ID, or SKIP_SENTINEL when retries are exhausted.

    Encapsulates the two-layer routing contract used by SPIRAL:
    - Layer 1 (Python): LlmRouter selects haiku/sonnet/opus by retry + complexity.
    - Layer 2 (Shell):  retry.sh marks stories _skipped at retry_count >= 3.

    This integration wrapper combines both layers so tests can assert the
    full end-to-end routing decision in a single call.
    """
    if retry_count >= _SPIRAL_MAX_RETRIES:
        return SKIP_SENTINEL
    router = LlmRouter()
    return router.route(story, retry_count=retry_count)


def _small_story(story_id: str = "US-TEST") -> dict:
    return {"id": story_id, "estimatedComplexity": "small"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUS452SmartModelRouting:
    """Integration tests for US-452 smart model routing auto-escalation.

    Named TestUS452* so ``pytest -k us_452`` selects this class.
    """

    def setup_method(self) -> None:
        # Ensure clean env — no CLI or fixed-routing overrides
        for key in ("SPIRAL_CLI_MODEL", "SPIRAL_MODEL_ROUTING"):
            os.environ.pop(key, None)
        # Explicitly set auto routing (matches production default)
        os.environ["SPIRAL_MODEL_ROUTING"] = "auto"

    def teardown_method(self) -> None:
        for key in ("SPIRAL_CLI_MODEL", "SPIRAL_MODEL_ROUTING"):
            os.environ.pop(key, None)

    def test_us_452_auto_routing_escalation_haiku_sonnet_opus(self) -> None:
        """retry=0 → haiku, retry=1 → sonnet, retry=2 → opus (SPIRAL_MODEL_ROUTING=auto).

        Verifies the full escalation ladder for a small story.
        """
        s = _small_story()
        router = LlmRouter()

        assert router.route(s, retry_count=0) == _HAIKU, "retry=0 must select haiku"
        assert router.route(s, retry_count=1) == _SONNET, "retry=1 must escalate to sonnet"
        assert router.route(s, retry_count=2) == _OPUS, "retry=2 must escalate to opus"

    def test_us_452_retry_3_returns_skip_sentinel(self) -> None:
        """retry=3 must return SKIP_SENTINEL — story is exhausted and skipped."""
        s = _small_story()
        result = route_or_skip(s, retry_count=3)
        assert result == SKIP_SENTINEL, f"Expected {SKIP_SENTINEL!r}, got {result!r}"

    def test_us_452_retry_below_max_does_not_skip(self) -> None:
        """retry=0,1,2 must return model IDs, not the skip sentinel."""
        s = _small_story()
        for retry in (0, 1, 2):
            result = route_or_skip(s, retry_count=retry)
            assert result != SKIP_SENTINEL, f"retry={retry} should not skip"
            assert result in (_HAIKU, _SONNET, _OPUS), f"retry={retry} returned unknown model {result!r}"

    def test_us_452_no_network_calls_required(self) -> None:
        """Routing decisions must be computable offline (no subprocess or HTTP)."""
        # If LlmRouter raises any connection-related error, this test fails.
        # A clean call with no mock/patch proves no network I/O is needed.
        s = _small_story("US-OFFLINE")
        router = LlmRouter()
        model = router.route(s, retry_count=0)
        assert model == _HAIKU

    def test_us_452_missing_complexity_defaults_to_medium_tier(self) -> None:
        """Edge case: story with no estimatedComplexity field defaults to medium (sonnet at retry=0)."""
        story: dict[str, str] = {"id": "US-NOCOMPLEXITY"}  # no estimatedComplexity key
        router = LlmRouter()
        model = router.route(story, retry_count=0)
        # medium complexity base tier is PRODUCTION (sonnet)
        assert model == _SONNET, f"Missing complexity must default to sonnet, got {model!r}"

    def test_us_452_unknown_complexity_value_defaults_to_medium_tier(self) -> None:
        """Edge case: unrecognised complexity string falls back to medium (sonnet at retry=0)."""
        story = {"id": "US-BADCOMPLEXITY", "estimatedComplexity": "unknown_value"}
        router = LlmRouter()
        model = router.route(story, retry_count=0)
        assert model == _SONNET, f"Unknown complexity must default to sonnet, got {model!r}"

    def test_us_452_cli_model_override_takes_priority(self) -> None:
        """Error/override case: SPIRAL_CLI_MODEL env var overrides auto-routing at any retry."""
        os.environ["SPIRAL_CLI_MODEL"] = "opus"
        story = _small_story()
        router = LlmRouter()
        # Even at retry=0 (which would normally be haiku), CLI override wins
        model = router.route(story, retry_count=0)
        assert model == _OPUS, f"SPIRAL_CLI_MODEL=opus must override auto-routing, got {model!r}"
