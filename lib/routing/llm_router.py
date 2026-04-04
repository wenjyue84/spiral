#!/usr/bin/env python3
"""
lib/llm_router.py — Centralized LLM model selection for SPIRAL (US-294, US-295, US-1093).

Encapsulates model selection logic into three tiers:
  - UTILITY   (haiku)   — small/trivial stories, retry 0
  - PRODUCTION (sonnet) — medium/large stories, retry 0–1
  - FRONTIER  (opus)    — any story on retry ≥ 2

Context-window-aware upgrade (US-295):
  Before dispatching, if estimated prompt tokens exceed
  model_context_limit * SPIRAL_CONTEXT_WINDOW_MARGIN the model is
  automatically upgraded one tier to prevent silent truncation.

Cost-per-win calibration (US-1093):
  On startup, loads .spiral/routing_calibration.json which contains
  cost_per_pass metrics per (model, complexity) bin. Escalation ladder
  is adjusted to skip tiers with poor cost/quality ratios.

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
import csv
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, cast

__all__ = [
    "ModelTier",
    "TaskContext",
    "LlmRouter",
    "TIER_TO_MODEL",
    "SHORT_TO_TIER",
    "MODEL_CONTEXT_LIMITS",
    "estimate_tokens",
    "get_thinking_budget",
    "load_calibration",
    "compute_calibration",
    "save_calibration",
    "CalibrationMetric",
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

    UTILITY = "utility"  # haiku  — cheap, fast, trivial tasks
    PRODUCTION = "production"  # sonnet — default mid-tier
    FRONTIER = "frontier"  # opus   — complex / repeated failures


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


# Minimum thinking budget when extended thinking is enabled (Anthropic API floor)
_MIN_THINKING_BUDGET = 1024

# ---------------------------------------------------------------------------
# Per-phase extended thinking budget (US-415)
# ---------------------------------------------------------------------------


def get_thinking_budget(phase: str = "") -> dict[str, Any]:
    """Return a ``thinking`` parameter dict for the Anthropic Messages API.

    Reads the phase-specific env var ``SPIRAL_THINKING_BUDGET_PHASE_<PHASE>``
    (where PHASE is one of I, S, R, M) with fallback to
    ``SPIRAL_THINKING_BUDGET_TOKENS``.

    Parameters
    ----------
    phase:
        Single-letter SPIRAL phase key (I, S, R, or M).  Case-insensitive.
        Pass an empty string to use only the global fallback.

    Returns
    -------
    dict
        ``{"type": "enabled", "budget_tokens": N}`` when budget > 0,
        ``{"type": "disabled"}`` when budget == 0,
        ``{}`` when neither env var is set (no thinking preference expressed).

    Notes
    -----
    Budget values between 1 and 1023 are clamped to the Anthropic API
    minimum of 1024 tokens.  Pass 0 to explicitly disable thinking.
    """
    phase_upper = phase.upper()
    phase_var = f"SPIRAL_THINKING_BUDGET_PHASE_{phase_upper}" if phase_upper else ""

    raw: str | None = None
    if phase_var:
        raw = os.environ.get(phase_var)
    if raw is None:
        raw = os.environ.get("SPIRAL_THINKING_BUDGET_TOKENS")

    if raw is None:
        return {}  # No preference expressed; caller decides

    try:
        budget = int(raw)
    except (ValueError, TypeError):
        return {}  # Malformed value; ignore silently

    if budget == 0:
        return {"type": "disabled"}

    # Enforce the Anthropic API minimum of 1024 tokens when enabled
    budget = max(budget, _MIN_THINKING_BUDGET)
    return {"type": "enabled", "budget_tokens": budget}


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
        import tiktoken

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

    complexity: str = "medium"  # "small" | "medium" | "large"
    retry_count: int = 0
    token_estimate: int = 0  # estimated prompt tokens (optional)
    dependency_count: int = 0  # number of dependencies in prd.json


# ---------------------------------------------------------------------------
# Calibration (US-1093)
# ---------------------------------------------------------------------------


@dataclass
class CalibrationMetric:
    """Cost-per-pass metric for a (model, complexity) pair (US-1093)."""

    model: str  # e.g., "haiku", "sonnet", "opus"
    complexity: str  # e.g., "small", "medium", "large"
    success_count: int  # number of pass statuses
    total_count: int  # total attempts
    avg_cost_per_pass: float  # average cost (tokens or USD) per successful attempt


def load_calibration(path: str) -> dict[tuple[str, str], CalibrationMetric] | None:
    """Load calibration data from .spiral/routing_calibration.json.

    Returns a dict mapping (model, complexity) → CalibrationMetric, or None if file doesn't exist.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        result = {}
        for key, metric_dict in data.items():
            model, complexity = key.split("|")
            result[(model, complexity)] = CalibrationMetric(**metric_dict)
        return result
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return None


def compute_calibration(results_tsv_path: str) -> dict[tuple[str, str], CalibrationMetric]:
    """Compute cost-per-pass metrics from results.tsv grouped by (model, complexity).

    Parses results.tsv, groups by (model, complexity bin), counts passes,
    and computes average cost per pass.

    Returns dict mapping (model, complexity) → CalibrationMetric.
    """
    metrics: dict[tuple[str, str], dict[str, Any]] = {}

    try:
        with open(results_tsv_path, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                return {}

            for row in reader:
                model = row.get("model", "").strip()
                if not model:
                    continue

                status = row.get("status", "").strip()
                complexity = row.get("estimatedComplexity", "medium").strip().lower()
                if complexity not in ("small", "medium", "large"):
                    complexity = "medium"

                # Estimate cost as cache_read_tokens + cache_creation_tokens or 0
                try:
                    cost = int(row.get("cache_read_tokens", "0") or "0") + int(
                        row.get("cache_creation_tokens", "0") or "0"
                    )
                except (ValueError, TypeError):
                    cost = 0

                key = (model, complexity)
                if key not in metrics:
                    metrics[key] = {"successes": 0, "total": 0, "total_cost": 0}

                metrics[key]["total"] += 1
                if status == "pass":
                    metrics[key]["successes"] += 1
                    metrics[key]["total_cost"] += cost

    except FileNotFoundError:
        return {}

    # Convert to CalibrationMetric objects
    result = {}
    for (model, complexity), data in metrics.items():
        success_count = data["successes"]
        total_count = data["total"]
        avg_cost = data["total_cost"] / success_count if success_count > 0 else 0
        result[(model, complexity)] = CalibrationMetric(
            model=model,
            complexity=complexity,
            success_count=success_count,
            total_count=total_count,
            avg_cost_per_pass=avg_cost,
        )

    return result


def save_calibration(metrics: dict[tuple[str, str], CalibrationMetric], path: str) -> None:
    """Save calibration metrics to .spiral/routing_calibration.json."""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for (model, complexity), metric in metrics.items():
            key = f"{model}|{complexity}"
            data[key] = asdict(metric)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass  # Non-fatal: calibration failure must not block startup


# ---------------------------------------------------------------------------
# LlmRouter
# ---------------------------------------------------------------------------


class LlmRouter:
    """Routes stories to the appropriate Claude model tier.

    Routing priority (highest first):
    1. ``SPIRAL_CLI_MODEL`` env var — explicit override (haiku/sonnet/opus or full ID)
    2. ``SPIRAL_MODEL_ROUTING`` == fixed tier name — config-level fixed tier
    3. Auto-routing: complexity + retry escalation heuristic (or calibrated heuristic if US-1093)
    4. Context-window upgrade: if prompt_tokens exceeds safety margin, step up one tier
       (US-295; applied after tier selection, before returning)
    """

    # Heuristic: complexity → base tier for retry 0
    _BASE_TIER: dict[str, ModelTier] = {
        "small": ModelTier.UTILITY,
        "medium": ModelTier.PRODUCTION,
        "large": ModelTier.PRODUCTION,  # large still starts at sonnet, not opus
    }

    def __init__(self) -> None:
        """Initialize router with optional calibration data (US-1093)."""
        self.calibration: dict[tuple[str, str], CalibrationMetric] | None = None
        self._calibration_loaded = False

    def _load_calibration(self) -> None:
        """Lazy-load calibration from .spiral/routing_calibration.json on first use."""
        if self._calibration_loaded:
            return
        self._calibration_loaded = True

        calib_path = os.environ.get(
            "SPIRAL_ROUTING_CALIBRATION",
            str(Path(__file__).parent.parent.parent / ".spiral" / "routing_calibration.json"),
        )
        self.calibration = load_calibration(calib_path)

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
        return str(result["model"])

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

    def _build_context(self, story: dict[str, Any], retry_override: int | None) -> TaskContext:
        complexity = str(story.get("estimatedComplexity", "medium")).lower()
        if complexity not in ("small", "medium", "large"):
            complexity = "medium"

        retry_count = retry_override if retry_override is not None else int(story.get("_retryCount", 0))
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

        # 3. Auto-routing: base tier + retry escalation (with optional calibration US-1093)
        self._load_calibration()  # Lazy-load from .spiral/routing_calibration.json
        base = self._BASE_TIER.get(ctx.complexity, ModelTier.PRODUCTION)

        if ctx.retry_count <= 0:
            # Check calibration: if base tier has poor cost/quality, skip to next tier
            if self.calibration:
                tier = self._find_best_tier_for_complexity(ctx.complexity)
                return tier
            return base

        # On retry ≥ 2, always escalate to FRONTIER
        if ctx.retry_count >= 2:
            return ModelTier.FRONTIER

        # retry == 1: step up one tier (with calibration override if available)
        try:
            if self.calibration:
                # Find the best tier given this complexity and retry count
                tier = self._find_best_tier_for_complexity(ctx.complexity)
                # If we're still at base tier after calibration check, escalate one more
                if tier == base:
                    idx = _ESCALATION.index(base)
                    return _ESCALATION[min(idx + 1, len(_ESCALATION) - 1)]
                return tier
            idx = _ESCALATION.index(base)
            return _ESCALATION[min(idx + 1, len(_ESCALATION) - 1)]
        except ValueError:
            return ModelTier.FRONTIER

    def _find_best_tier_for_complexity(self, complexity: str) -> ModelTier:
        """Find the best tier for a given complexity using calibration data.

        Skips tiers with poor cost/quality ratio: if a tier costs 2x for <10% quality gain over
        a cheaper tier, that expensive tier is skipped.
        """
        if not self.calibration:
            return self._BASE_TIER.get(complexity, ModelTier.PRODUCTION)

        # Gather metrics for all models in this complexity bin
        # Calibration stores both short names (haiku, sonnet, opus) and full IDs
        metrics_by_tier: dict[ModelTier, CalibrationMetric | None] = {}
        for tier in _ESCALATION:
            full_id = TIER_TO_MODEL[tier]
            # Try both short name and full ID lookup
            short_name = {
                ModelTier.UTILITY: "haiku",
                ModelTier.PRODUCTION: "sonnet",
                ModelTier.FRONTIER: "opus",
            }.get(tier, "")
            metric = self.calibration.get((short_name, complexity))
            if metric is None:
                metric = self.calibration.get((full_id, complexity))
            metrics_by_tier[tier] = metric

        # Find base tier
        base = self._BASE_TIER.get(complexity, ModelTier.PRODUCTION)
        base_metric = metrics_by_tier.get(base)

        # If no base metrics, return base tier
        if base_metric is None or base_metric.success_count == 0:
            return base

        base_win_rate = base_metric.success_count / base_metric.total_count
        base_cost = base_metric.avg_cost_per_pass

        # Check if base tier is worth the cost compared to cheaper alternatives
        # If a cheaper tier has similar quality (within 5%), prefer the cheaper one
        try:
            base_idx = _ESCALATION.index(base)
            # Check all lower tiers (cheaper options)
            for idx in range(base_idx - 1, -1, -1):
                cheaper_tier = _ESCALATION[idx]
                cheaper_metric = metrics_by_tier.get(cheaper_tier)
                if cheaper_metric is None or cheaper_metric.success_count == 0:
                    continue

                cheaper_win_rate = cheaper_metric.success_count / cheaper_metric.total_count
                cheaper_cost = cheaper_metric.avg_cost_per_pass

                # If base is 2x+ cost for <10% quality gain over cheaper tier, use cheaper tier
                if base_cost > 0 and cheaper_cost > 0:
                    cost_ratio = base_cost / cheaper_cost
                    quality_gain = base_win_rate - cheaper_win_rate
                    if cost_ratio >= 2.0 and quality_gain < 0.1:
                        return cheaper_tier  # Cheaper tier is good enough

        except ValueError:
            pass

        return base

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
            return cast(dict[str, Any], s)

    print(
        json.dumps({"error": f"story {story_id!r} not found in {prd_path}"}),
        file=sys.stderr,
    )
    sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Query SPIRAL LLM routing decision for a story, or compute calibration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python lib/llm_router.py --story US-123
  uv run python lib/llm_router.py --story US-123 --retry 1
  uv run python lib/llm_router.py --story US-123 --prd my_prd.json
  uv run python lib/llm_router.py --story US-123 --prompt-tokens 170000
  uv run python lib/llm_router.py --calibrate results.tsv
""",
    )
    parser.add_argument("--story", default=None, help="Story ID, e.g. US-123")
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
            "Estimated total prompt token count for context-window upgrade check (US-295). Pass 0 to skip (default: 0)."
        ),
    )
    parser.add_argument(
        "--events-file",
        default=None,
        dest="events_file",
        help="Path to spiral_events.jsonl for logging upgrade decisions (optional).",
    )
    parser.add_argument(
        "--calibrate",
        default=None,
        dest="calibrate_path",
        help="Compute calibration from results.tsv and save to .spiral/routing_calibration.json",
    )

    args = parser.parse_args(argv)

    # Handle calibration mode (US-1093)
    if args.calibrate_path:
        metrics = compute_calibration(args.calibrate_path)
        calib_path = os.environ.get(
            "SPIRAL_ROUTING_CALIBRATION",
            ".spiral/routing_calibration.json",
        )
        save_calibration(metrics, calib_path)
        print(json.dumps({"status": "ok", "metrics_computed": len(metrics), "saved_to": calib_path}))
        return

    # Handle routing mode (default)
    if not args.story:
        parser.error("--story is required unless --calibrate is used")

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
