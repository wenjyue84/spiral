#!/usr/bin/env python3
"""Tests for lib/llm_router.py — centralized model selection (US-294)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from llm_router import (
    LlmRouter,
    ModelTier,
    SHORT_TO_TIER,
    TIER_TO_MODEL,
    TaskContext,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HAIKU = TIER_TO_MODEL[ModelTier.UTILITY]
_SONNET = TIER_TO_MODEL[ModelTier.PRODUCTION]
_OPUS = TIER_TO_MODEL[ModelTier.FRONTIER]


def story(
    complexity: str = "medium",
    retry: int = 0,
    deps: list[str] | None = None,
    story_id: str = "US-000",
) -> dict:
    s: dict = {
        "id": story_id,
        "estimatedComplexity": complexity,
        "_retryCount": retry,
    }
    if deps is not None:
        s["dependencies"] = deps
    return s


# ---------------------------------------------------------------------------
# ModelTier enum
# ---------------------------------------------------------------------------


class TestModelTierEnum:
    def test_three_tiers_exist(self):
        assert ModelTier.UTILITY.value == "utility"
        assert ModelTier.PRODUCTION.value == "production"
        assert ModelTier.FRONTIER.value == "frontier"

    def test_tier_to_model_has_all_keys(self):
        for tier in ModelTier:
            assert tier in TIER_TO_MODEL, f"{tier} missing from TIER_TO_MODEL"

    def test_short_aliases(self):
        assert SHORT_TO_TIER["haiku"] == ModelTier.UTILITY
        assert SHORT_TO_TIER["sonnet"] == ModelTier.PRODUCTION
        assert SHORT_TO_TIER["opus"] == ModelTier.FRONTIER


# ---------------------------------------------------------------------------
# TaskContext dataclass
# ---------------------------------------------------------------------------


class TestTaskContext:
    def test_defaults(self):
        ctx = TaskContext()
        assert ctx.complexity == "medium"
        assert ctx.retry_count == 0
        assert ctx.token_estimate == 0
        assert ctx.dependency_count == 0

    def test_custom_values(self):
        ctx = TaskContext(complexity="large", retry_count=2, dependency_count=3)
        assert ctx.complexity == "large"
        assert ctx.retry_count == 2
        assert ctx.dependency_count == 3


# ---------------------------------------------------------------------------
# LlmRouter.route — tier transitions
# ---------------------------------------------------------------------------


class TestLlmRouterTierTransitions:
    def setup_method(self):
        # Ensure clean env
        for k in ("SPIRAL_CLI_MODEL", "SPIRAL_MODEL_ROUTING"):
            os.environ.pop(k, None)

    def test_small_retry0_returns_haiku(self):
        r = LlmRouter()
        assert r.route(story("small", 0)) == _HAIKU

    def test_medium_retry0_returns_sonnet(self):
        r = LlmRouter()
        assert r.route(story("medium", 0)) == _SONNET

    def test_large_retry0_returns_sonnet(self):
        r = LlmRouter()
        assert r.route(story("large", 0)) == _SONNET

    def test_small_retry1_escalates_to_sonnet(self):
        r = LlmRouter()
        assert r.route(story("small", 1)) == _SONNET

    def test_medium_retry1_escalates_to_opus(self):
        r = LlmRouter()
        assert r.route(story("medium", 1)) == _OPUS

    def test_large_retry1_escalates_to_opus(self):
        r = LlmRouter()
        assert r.route(story("large", 1)) == _OPUS

    def test_any_retry2_returns_opus(self):
        r = LlmRouter()
        for c in ("small", "medium", "large"):
            assert r.route(story(c, 2)) == _OPUS, f"complexity={c}"

    def test_any_retry3_returns_opus(self):
        r = LlmRouter()
        assert r.route(story("small", 3)) == _OPUS

    def test_unknown_complexity_defaults_to_medium_tier(self):
        r = LlmRouter()
        s = {"id": "US-X", "estimatedComplexity": "gigantic", "_retryCount": 0}
        assert r.route(s) == _SONNET

    def test_retry_from_story_field(self):
        r = LlmRouter()
        s = {"id": "US-Y", "estimatedComplexity": "small", "_retryCount": 2}
        assert r.route(s) == _OPUS

    def test_retry_override_wins_over_story_field(self):
        r = LlmRouter()
        s = {"id": "US-Z", "estimatedComplexity": "small", "_retryCount": 99}
        # Override to retry=0 → should use base tier for small
        assert r.route(s, retry_count=0) == _HAIKU


# ---------------------------------------------------------------------------
# LlmRouter — config override cases
# ---------------------------------------------------------------------------


class TestLlmRouterConfigOverride:
    def setup_method(self):
        for k in ("SPIRAL_CLI_MODEL", "SPIRAL_MODEL_ROUTING"):
            os.environ.pop(k, None)

    def teardown_method(self):
        for k in ("SPIRAL_CLI_MODEL", "SPIRAL_MODEL_ROUTING"):
            os.environ.pop(k, None)

    def test_cli_model_haiku_forces_haiku(self):
        os.environ["SPIRAL_CLI_MODEL"] = "haiku"
        r = LlmRouter()
        # Even large+retry2 should return haiku
        assert r.route(story("large", 2)) == _HAIKU

    def test_cli_model_opus_forces_opus(self):
        os.environ["SPIRAL_CLI_MODEL"] = "opus"
        r = LlmRouter()
        assert r.route(story("small", 0)) == _OPUS

    def test_cli_model_full_id(self):
        os.environ["SPIRAL_CLI_MODEL"] = TIER_TO_MODEL[ModelTier.PRODUCTION]
        r = LlmRouter()
        assert r.route(story("small", 0)) == _SONNET

    def test_fixed_routing_sonnet(self):
        os.environ["SPIRAL_MODEL_ROUTING"] = "sonnet"
        r = LlmRouter()
        assert r.route(story("small", 0)) == _SONNET
        assert r.route(story("large", 3)) == _SONNET

    def test_fixed_routing_haiku(self):
        os.environ["SPIRAL_MODEL_ROUTING"] = "haiku"
        r = LlmRouter()
        assert r.route(story("large", 5)) == _HAIKU

    def test_cli_model_overrides_fixed_routing(self):
        os.environ["SPIRAL_MODEL_ROUTING"] = "haiku"
        os.environ["SPIRAL_CLI_MODEL"] = "opus"
        r = LlmRouter()
        assert r.route(story("small", 0)) == _OPUS

    def test_auto_routing_default(self):
        os.environ["SPIRAL_MODEL_ROUTING"] = "auto"
        r = LlmRouter()
        assert r.route(story("small", 0)) == _HAIKU

    def test_unknown_routing_mode_falls_back_to_production(self):
        os.environ["SPIRAL_MODEL_ROUTING"] = "unknown_mode"
        r = LlmRouter()
        # unknown SHORT_TO_TIER lookup falls back to PRODUCTION
        assert r.route(story("small", 0)) == _SONNET


# ---------------------------------------------------------------------------
# LlmRouter.route_context — metadata
# ---------------------------------------------------------------------------


class TestRouteContext:
    def setup_method(self):
        for k in ("SPIRAL_CLI_MODEL", "SPIRAL_MODEL_ROUTING"):
            os.environ.pop(k, None)

    def test_route_context_fields(self):
        r = LlmRouter()
        s = story("medium", 0, deps=["US-001", "US-002"], story_id="US-100")
        ctx = r.route_context(s)
        assert ctx["story_id"] == "US-100"
        assert ctx["model"] in TIER_TO_MODEL.values()
        assert ctx["tier"] in (t.value for t in ModelTier)
        assert ctx["complexity"] == "medium"
        assert ctx["retry_count"] == 0
        assert ctx["dependency_count"] == 2
        assert ctx["routing_mode"] == "auto"

    def test_route_context_routing_mode_reflects_env(self):
        os.environ["SPIRAL_MODEL_ROUTING"] = "sonnet"
        r = LlmRouter()
        ctx = r.route_context(story())
        assert ctx["routing_mode"] == "sonnet"
        os.environ.pop("SPIRAL_MODEL_ROUTING")


# ---------------------------------------------------------------------------
# CLI (main())
# ---------------------------------------------------------------------------


class TestCLI:
    def setup_method(self):
        for k in ("SPIRAL_CLI_MODEL", "SPIRAL_MODEL_ROUTING"):
            os.environ.pop(k, None)

    def _write_prd(self, stories: list[dict], tmp_path: Path) -> str:
        prd = {"userStories": stories}
        path = tmp_path / "prd.json"
        path.write_text(json.dumps(prd), encoding="utf-8")
        return str(path)

    def test_cli_prints_json(self, tmp_path, capsys):
        prd_path = self._write_prd(
            [{"id": "US-10", "estimatedComplexity": "medium"}], tmp_path
        )
        main(["--story", "US-10", "--prd", prd_path])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert result["story_id"] == "US-10"
        assert result["model"] == _SONNET
        assert result["tier"] == "production"

    def test_cli_retry_override(self, tmp_path, capsys):
        prd_path = self._write_prd(
            [{"id": "US-11", "estimatedComplexity": "small"}], tmp_path
        )
        main(["--story", "US-11", "--retry", "2", "--prd", prd_path])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert result["model"] == _OPUS

    def test_cli_missing_story_exits_nonzero(self, tmp_path):
        prd_path = self._write_prd([], tmp_path)
        with pytest.raises(SystemExit) as exc:
            main(["--story", "US-999", "--prd", prd_path])
        assert exc.value.code != 0

    def test_cli_missing_prd_exits_nonzero(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            main(["--story", "US-001", "--prd", str(tmp_path / "nonexistent.json")])
        assert exc.value.code != 0

    def test_cli_haiku_for_small(self, tmp_path, capsys):
        prd_path = self._write_prd(
            [{"id": "US-20", "estimatedComplexity": "small"}], tmp_path
        )
        main(["--story", "US-20", "--prd", prd_path])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert result["model"] == _HAIKU
        assert result["tier"] == "utility"
