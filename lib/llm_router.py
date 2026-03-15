#!/usr/bin/env python3
"""
lib/llm_router.py — Centralized LLM model selection for SPIRAL (US-294).

Encapsulates model selection logic into three tiers:
  - UTILITY   (haiku)   — small/trivial stories, retry 0
  - PRODUCTION (sonnet) — medium/large stories, retry 0–1
  - FRONTIER  (opus)    — any story on retry ≥ 2

Usage as CLI (called from ralph.sh):
  uv run python lib/llm_router.py --story US-123 [--retry 0] [--prd prd.json]

Outputs JSON:
  {"story_id": "US-123", "model": "claude-sonnet-4-6", "tier": "production",
   "complexity": "medium", "retry_count": 0, "routing_mode": "auto"}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

__all__ = [
    "ModelTier",
    "TaskContext",
    "LlmRouter",
    "TIER_TO_MODEL",
    "SHORT_TO_TIER",
]

# ---------------------------------------------------------------------------
# Model tier definitions
# ---------------------------------------------------------------------------

# Canonical Claude model IDs used by SPIRAL
_HAIKU_ID = "claude-haiku-4-5-20251001"
_SONNET_ID = "claude-sonnet-4-6"
_OPUS_ID = "claude-opus-4-6"


class ModelTier(Enum):
    """Three-tier routing ladder for SPIRAL model selection."""

    UTILITY = "utility"       # haiku  — cheap, fast, trivial tasks
    PRODUCTION = "production" # sonnet — default mid-tier
    FRONTIER = "frontier"     # opus   — complex / repeated failures


# Map tier → full Claude model ID
TIER_TO_MODEL: dict[ModelTier, str] = {
    ModelTier.UTILITY: _HAIKU_ID,
    ModelTier.PRODUCTION: _SONNET_ID,
    ModelTier.FRONTIER: _OPUS_ID,
}

# Allow short aliases used in spiral.sh / ralph.sh
SHORT_TO_TIER: dict[str, ModelTier] = {
    "haiku": ModelTier.UTILITY,
    "sonnet": ModelTier.PRODUCTION,
    "opus": ModelTier.FRONTIER,
    "utility": ModelTier.UTILITY,
    "production": ModelTier.PRODUCTION,
    "frontier": ModelTier.FRONTIER,
    _HAIKU_ID: ModelTier.UTILITY,
    _SONNET_ID: ModelTier.PRODUCTION,
    _OPUS_ID: ModelTier.FRONTIER,
}

# Escalation ladder: UTILITY → PRODUCTION → FRONTIER
_ESCALATION: list[ModelTier] = [
    ModelTier.UTILITY,
    ModelTier.PRODUCTION,
    ModelTier.FRONTIER,
]


# ---------------------------------------------------------------------------
# TaskContext
# ---------------------------------------------------------------------------


@dataclass
class TaskContext:
    """Routing inputs derived from a PRD story."""

    complexity: str = "medium"        # "small" | "medium" | "large"
    retry_count: int = 0
    token_estimate: int = 0           # estimated prompt tokens (optional)
    dependency_count: int = 0         # number of dependencies in prd.json


# ---------------------------------------------------------------------------
# LlmRouter
# ---------------------------------------------------------------------------


class LlmRouter:
    """Routes stories to the appropriate Claude model tier.

    Routing priority (highest first):
    1. ``SPIRAL_CLI_MODEL`` env var — explicit override (haiku/sonnet/opus or full ID)
    2. ``SPIRAL_MODEL_ROUTING`` == fixed tier name — config-level fixed tier
    3. Auto-routing: complexity + retry escalation heuristic
    """

    # Heuristic: complexity → base tier for retry 0
    _BASE_TIER: dict[str, ModelTier] = {
        "small": ModelTier.UTILITY,
        "medium": ModelTier.PRODUCTION,
        "large": ModelTier.PRODUCTION,  # large still starts at sonnet, not opus
    }

    def route(self, story: dict[str, Any], retry_count: int | None = None) -> str:
        """Return a full Claude model ID string for *story*.

        Parameters
        ----------
        story:
            A PRD story dict (must contain at least ``estimatedComplexity``).
        retry_count:
            Override the retry count.  If ``None``, reads ``story["_retryCount"]``
            or falls back to 0.
        """
        ctx = self._build_context(story, retry_count)
        tier = self._select_tier(ctx)
        return TIER_TO_MODEL[tier]

    def route_context(
        self, story: dict[str, Any], retry_count: int | None = None
    ) -> dict[str, Any]:
        """Return a dict with model ID plus routing metadata for logging/CLI."""
        ctx = self._build_context(story, retry_count)
        tier = self._select_tier(ctx)
        routing_mode = self._routing_mode()
        return {
            "story_id": story.get("id", ""),
            "model": TIER_TO_MODEL[tier],
            "tier": tier.value,
            "complexity": ctx.complexity,
            "retry_count": ctx.retry_count,
            "dependency_count": ctx.dependency_count,
            "routing_mode": routing_mode,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_context(
        self, story: dict[str, Any], retry_override: int | None
    ) -> TaskContext:
        complexity = str(story.get("estimatedComplexity", "medium")).lower()
        if complexity not in ("small", "medium", "large"):
            complexity = "medium"

        retry_count = (
            retry_override
            if retry_override is not None
            else int(story.get("_retryCount", 0))
        )
        deps: list[Any] = story.get("dependencies") or []
        dependency_count = len(deps)

        return TaskContext(
            complexity=complexity,
            retry_count=retry_count,
            dependency_count=dependency_count,
        )

    def _routing_mode(self) -> str:
        """Read SPIRAL_MODEL_ROUTING env var (default: 'auto')."""
        return os.environ.get("SPIRAL_MODEL_ROUTING", "auto")

    def _select_tier(self, ctx: TaskContext) -> ModelTier:
        """Apply routing priority rules and return a ModelTier."""

        # 1. Explicit CLI override (highest priority)
        cli_model = os.environ.get("SPIRAL_CLI_MODEL", "").strip()
        if cli_model:
            return SHORT_TO_TIER.get(cli_model, ModelTier.PRODUCTION)

        routing_mode = self._routing_mode()

        # 2. Fixed config tier (not 'auto')
        if routing_mode != "auto":
            return SHORT_TO_TIER.get(routing_mode, ModelTier.PRODUCTION)

        # 3. Auto-routing: base tier + retry escalation
        base = self._BASE_TIER.get(ctx.complexity, ModelTier.PRODUCTION)

        if ctx.retry_count <= 0:
            return base

        # On retry ≥ 2, always escalate to FRONTIER
        if ctx.retry_count >= 2:
            return ModelTier.FRONTIER

        # retry == 1: step up one tier
        try:
            idx = _ESCALATION.index(base)
            return _ESCALATION[min(idx + 1, len(_ESCALATION) - 1)]
        except ValueError:
            return ModelTier.FRONTIER


# ---------------------------------------------------------------------------
# CLI entry point (called from ralph.sh)
# ---------------------------------------------------------------------------


def _load_story(story_id: str, prd_path: str) -> dict[str, Any]:
    """Load a story dict from prd.json by ID."""
    prd_file = Path(prd_path)
    if not prd_file.exists():
        print(
            json.dumps({"error": f"prd.json not found at {prd_path}"}),
            file=sys.stderr,
        )
        sys.exit(1)

    with prd_file.open(encoding="utf-8") as fh:
        prd = json.load(fh)

    for s in prd.get("userStories", []):
        if s.get("id") == story_id:
            return s  # type: ignore[return-value]

    print(
        json.dumps({"error": f"story {story_id!r} not found in {prd_path}"}),
        file=sys.stderr,
    )
    sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Query SPIRAL LLM routing decision for a story",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python lib/llm_router.py --story US-123
  uv run python lib/llm_router.py --story US-123 --retry 1
  uv run python lib/llm_router.py --story US-123 --prd my_prd.json
""",
    )
    parser.add_argument("--story", required=True, help="Story ID, e.g. US-123")
    parser.add_argument(
        "--retry",
        type=int,
        default=None,
        help="Override retry count (default: read from prd.json _retryCount or 0)",
    )
    parser.add_argument(
        "--prd",
        default="prd.json",
        help="Path to prd.json (default: prd.json)",
    )

    args = parser.parse_args(argv)

    story = _load_story(args.story, args.prd)
    router = LlmRouter()
    result = router.route_context(story, retry_count=args.retry)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
