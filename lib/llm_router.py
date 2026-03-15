#!/usr/bin/env python3
"""
lib/llm_router.py — Centralized LLM model selection for SPIRAL (US-294, US-295).

Encapsulates model selection logic into three tiers:
  - UTILITY   (haiku)   — small/trivial stories, retry 0
  - PRODUCTION (sonnet) — medium/large stories, retry 0–1
  - FRONTIER  (opus)    — any story on retry ≥ 2

Context-window-aware upgrade (US-295):
  Before dispatching, if estimated prompt tokens exceed
  model_context_limit * SPIRAL_CONTEXT_WINDOW_MARGIN the model is
  automatically upgraded one tier to prevent silent truncation.

Usage as CLI (called from ralph.sh):
  uv run python lib/llm_router.py --story US-123 [--retry 0] [--prd prd.json]
  uv run python lib/llm_router.py --story US-123 --prompt-tokens 150000

Outputs JSON:
  {"story_id": "US-123", "model": "claude-sonnet-4-6", "tier": "production",
   "complexity": "medium", "retry_count": 0, "routing_mode": "auto",
   "context_window_upgrade": false}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

__all__ = [
    "ModelTier",
    "TaskContext",
    "LlmRouter",
    "TIER_TO_MODEL",
    "SHORT_TO_TIER",
    "MODEL_CONTEXT_LIMITS",
    "estimate_tokens",
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
# Context window limits (US-295)
# ---------------------------------------------------------------------------

# Token limits per model — all Claude 4.x models share a 200k context window
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    _HAIKU_ID: 200_000,
    _SONNET_ID: 200_000,
    _OPUS_ID: 200_000,
}

# Default safety margin: upgrade if prompt exceeds 85% of the context window
_DEFAULT_CONTEXT_WINDOW_MARGIN = 0.85


# ---------------------------------------------------------------------------
# Token estimation (US-295)
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Estimate token count for *text*.

    Uses tiktoken (cl100k_base) when available; falls back to the
    4-chars-per-token approximation otherwise.

    Parameters
    ----------
    text:
        The combined prompt text to estimate.

    Returns
    -------
    int
        Estimated token count (always ≥ 0).
    """
    if not text:
        return 0
    try:
        import tiktoken  # type: ignore[import]
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return len(text) // 4


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
    4. Context-window upgrade: if prompt_tokens exceeds safety margin, step up one tier
       (US-295; applied after tier selection, before returning)
    """

    # Heuristic: complexity → base tier for retry 0
    _BASE_TIER: dict[str, ModelTier] = {
        "small": ModelTier.UTILITY,
        "medium": ModelTier.PRODUCTION,
        "large": ModelTier.PRODUCTION,  # large still starts at sonnet, not opus
    }

    def route(
        self,
        story: dict[str, Any],
        retry_count: int | None = None,
        prompt_tokens: int = 0,
        events_file: str | None = None,
    ) -> str:
        """Return a full Claude model ID string for *story*.

        Parameters
        ----------
        story:
            A PRD story dict (must contain at least ``estimatedComplexity``).
        retry_count:
            Override the retry count.  If ``None``, reads ``story["_retryCount"]``
            or falls back to 0.
        prompt_tokens:
            Estimated total prompt token count.  When > 0, a context-window
            safety check is applied and the model may be upgraded one tier
            (US-295).
        events_file:
            Path to ``spiral_events.jsonl``.  If ``None``, read from
            ``$SCRATCH_DIR/spiral_events.jsonl`` or skip logging.
        """
        result = self.route_context(
            story,
            retry_count=retry_count,
            prompt_tokens=prompt_tokens,
            events_file=events_file,
        )
        return result["model"]

    def route_context(
        self,
        story: dict[str, Any],
        retry_count: int | None = None,
        prompt_tokens: int = 0,
        events_file: str | None = None,
    ) -> dict[str, Any]:
        """Return a dict with model ID plus routing metadata for logging/CLI.

        Parameters
        ----------
        story:
            A PRD story dict.
        retry_count:
            Override the retry count.
        prompt_tokens:
            Estimated total prompt token count for context-window upgrade check
            (US-295).  Pass 0 to skip the check.
        events_file:
            Path to ``spiral_events.jsonl`` for logging upgrade decisions.
            If ``None``, falls back to ``$SCRATCH_DIR/spiral_events.jsonl``.
        """
        ctx = self._build_context(story, retry_count)
        tier = self._select_tier(ctx)
        routing_mode = self._routing_mode()

        # US-295: context-window-aware upgrade
        context_window_upgrade = False
        if prompt_tokens > 0:
            tier, context_window_upgrade = self._apply_context_window_upgrade(
                tier=tier,
                prompt_tokens=prompt_tokens,
                story_id=story.get("id", ""),
                events_file=events_file,
            )

        return {
            "story_id": story.get("id", ""),
            "model": TIER_TO_MODEL[tier],
            "tier": tier.value,
            "complexity": ctx.complexity,
            "retry_count": ctx.retry_count,
            "dependency_count": ctx.dependency_count,
            "routing_mode": routing_mode,
            "context_window_upgrade": context_window_upgrade,
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

    def _apply_context_window_upgrade(
        self,
        tier: ModelTier,
        prompt_tokens: int,
        story_id: str,
        events_file: str | None,
    ) -> tuple[ModelTier, bool]:
        """Check if *prompt_tokens* exceeds the safety margin for *tier*.

        If it does, upgrade one tier and log a ``context_window_upgrade``
        event to ``spiral_events.jsonl`` (US-295).

        Returns
        -------
        tuple[ModelTier, bool]
            The (possibly upgraded) tier and a flag indicating whether
            an upgrade occurred.
        """
        margin = float(os.environ.get("SPIRAL_CONTEXT_WINDOW_MARGIN", str(_DEFAULT_CONTEXT_WINDOW_MARGIN)))
        model_id = TIER_TO_MODEL[tier]
        limit = MODEL_CONTEXT_LIMITS.get(model_id, 200_000)
        threshold = int(limit * margin)

        if prompt_tokens <= threshold:
            return tier, False

        # Upgrade one tier
        try:
            idx = _ESCALATION.index(tier)
            upgraded_tier = _ESCALATION[min(idx + 1, len(_ESCALATION) - 1)]
        except ValueError:
            upgraded_tier = ModelTier.FRONTIER

        if upgraded_tier == tier:
            # Already at FRONTIER, no upgrade possible
            return tier, False

        # Log the upgrade decision
        self._log_context_window_upgrade(
            from_tier=tier,
            to_tier=upgraded_tier,
            estimated_tokens=prompt_tokens,
            story_id=story_id,
            events_file=events_file,
        )

        return upgraded_tier, True

    def _log_context_window_upgrade(
        self,
        from_tier: ModelTier,
        to_tier: ModelTier,
        estimated_tokens: int,
        story_id: str,
        events_file: str | None,
    ) -> None:
        """Append a context_window_upgrade event to spiral_events.jsonl."""
        # Resolve events file path
        if events_file is None:
            scratch_dir = os.environ.get("SCRATCH_DIR", "")
            if scratch_dir:
                events_file = os.path.join(scratch_dir, "spiral_events.jsonl")
            else:
                # Fallback: .spiral/ relative to this module's repo root
                repo_root = Path(__file__).parent.parent
                events_file = str(repo_root / ".spiral" / "spiral_events.jsonl")

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        run_id = os.environ.get("SPIRAL_RUN_ID", "")
        level = os.environ.get("SPIRAL_LOG_LEVEL", "INFO")

        entry: dict[str, Any] = {
            "ts": ts,
            "event": "context_window_upgrade",
            "run_id": run_id,
            "level": level,
            "story_id": story_id,
            "from_model": TIER_TO_MODEL[from_tier],
            "to_model": TIER_TO_MODEL[to_tier],
            "estimated_tokens": estimated_tokens,
            "chosen_model": TIER_TO_MODEL[to_tier],
        }

        # Inject W3C traceparent fields when available
        traceparent = os.environ.get("TRACEPARENT", "")
        if traceparent:
            entry["trace_id"] = traceparent[3:35]
            entry["span_id"] = traceparent[36:52]

        try:
            Path(events_file).parent.mkdir(parents=True, exist_ok=True)
            with open(events_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # Non-fatal: event logging must not block story dispatch


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
  uv run python lib/llm_router.py --story US-123 --prompt-tokens 170000
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
    parser.add_argument(
        "--prompt-tokens",
        type=int,
        default=0,
        dest="prompt_tokens",
        help=(
            "Estimated total prompt token count for context-window upgrade check "
            "(US-295). Pass 0 to skip (default: 0)."
        ),
    )
    parser.add_argument(
        "--events-file",
        default=None,
        dest="events_file",
        help="Path to spiral_events.jsonl for logging upgrade decisions (optional).",
    )

    args = parser.parse_args(argv)

    story = _load_story(args.story, args.prd)
    router = LlmRouter()
    result = router.route_context(
        story,
        retry_count=args.retry,
        prompt_tokens=args.prompt_tokens,
        events_file=args.events_file,
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
