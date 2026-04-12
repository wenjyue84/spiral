#!/usr/bin/env python3
"""
self_tune.py — Phase ST: Self-Tune engine.

Analyzes telemetry from recent SPIRAL iterations (results.tsv, events,
retry-counts.json) and outputs JSON with environment variable adjustments
to apply for the next iteration. The bash wrapper applies these via `export`.

8 tuning rules:
  1. Timeout scaling — increase/decrease based on timeout failure rate
  2. Diff limit scaling — adjust SPIRAL_MAX_DIFF_LINES by oversized_diff rate
  3. Model floor escalation — skip haiku/sonnet if success rate too low
  4. Worker count — reduce on merge conflicts, increase when stable
  5. Batch size — decrease on low velocity, increase on high velocity
  6. Decomposition threshold — lower when too many max-retries, raise when few
  7. Thinking effort — downgrade when cost doubles without proportional gains
  8. Memory pool scaling — increase tier allocation when RSS exceeds 80%
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Allow importing sibling modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.results_tsv import ResultsRecord, parse_results_tsv  # noqa: E402

# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class TuningAdjustment:
    """A single config adjustment with rationale."""

    setting: str
    old_value: str
    new_value: str
    rule_name: str
    reason: str


@dataclass
class IterationMetrics:
    """Aggregated metrics from one iteration's results.tsv rows."""

    iteration: int
    total_attempts: int = 0
    passed: int = 0
    failed: int = 0
    timeout_count: int = 0
    oversized_diff_count: int = 0
    conflict_count: int = 0
    max_retry_reached: int = 0  # stories reaching retry 3+
    retry_2_plus: int = 0
    avg_duration_sec: float = 0.0
    max_duration_sec: float = 0.0
    velocity: float = 0.0  # passed stories this iteration
    haiku_attempts: int = 0
    haiku_passes: int = 0
    sonnet_attempts: int = 0
    sonnet_passes: int = 0
    opus_attempts: int = 0
    opus_passes: int = 0
    peak_rss_values: list[int] = field(default_factory=list)
    model_rss: dict[str, list[int]] = field(default_factory=dict)
    failure_categories: dict[str, int] = field(default_factory=dict)
    cost_proxy: float = 0.0  # total duration / passed (rough cost-per-pass)


# ── Bounds for tunable settings ──────────────────────────────────────────────

BOUNDS: dict[str, tuple[int | float, int | float]] = {
    "SPIRAL_IMPL_TIMEOUT": (600, 7200),
    "SPIRAL_WORKER_TIMEOUT": (600, 7200),
    "SPIRAL_STORY_TIMEOUT_SMALL": (300, 3600),
    "SPIRAL_STORY_TIMEOUT_MEDIUM": (600, 5400),
    "SPIRAL_STORY_TIMEOUT_LARGE": (1200, 7200),
    "SPIRAL_VALIDATE_TIMEOUT": (300, 1800),
    "SPIRAL_MAX_DIFF_LINES": (400, 1500),
    "SPIRAL_ESCALATION_RETRY_SONNET": (0, 3),
    "SPIRAL_ESCALATION_RETRY_OPUS": (0, 3),
    "SPIRAL_RALPH_WORKERS": (1, 4),
    "SPIRAL_STORY_BATCH_SIZE": (3, 15),
    "SPIRAL_DECOMPOSE_THRESHOLD": (1, 4),
    "SPIRAL_POOL_TIER_SMALL": (512, 4096),
    "SPIRAL_POOL_TIER_MEDIUM": (768, 4096),
    "SPIRAL_POOL_TIER_LARGE": (1536, 4096),
}

EFFORT_LEVELS = ["medium", "high", "max"]

# ── Helpers ──────────────────────────────────────────────────────────────────


def _env_int(name: str, default: int) -> int:
    """Read an integer from environment with fallback."""
    try:
        return int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _clamp(value: int | float, setting: str) -> int:
    """Clamp value within BOUNDS for the setting."""
    lo, hi = BOUNDS.get(setting, (0, 999999))
    return int(max(lo, min(hi, value)))


def _is_timeout_failure(record: ResultsRecord) -> bool:
    """Check if a result row represents a timeout failure."""
    frc = (record.failure_root_cause or "").lower()
    status = (record.status or "").lower()
    return any(kw in frc for kw in ("timeout", "timed_out", "timed out", "deadline")) or (
        status in ("timeout", "error") and "timeout" in frc
    )


def _is_oversized_diff(record: ResultsRecord) -> bool:
    frc = (record.failure_root_cause or "").lower()
    cat = (record.error_category or "").lower()
    return "oversized_diff" in frc or "oversized_diff" in cat


def _has_conflicts(record: ResultsRecord) -> bool:
    if record.conflict_file_count:
        try:
            return int(record.conflict_file_count) > 0
        except ValueError:
            pass
    return bool(record.conflict_files and record.conflict_files.strip() not in ("", "[]"))


def _safe_int(val: str, default: int = 0) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


# ── Core engine ──────────────────────────────────────────────────────────────


class SelfTuner:
    """Analyzes telemetry and computes config adjustments."""

    def __init__(
        self,
        results_tsv_path: str,
        tuning_history_path: str,
        current_iteration: int,
        cooldown: int = 2,
    ) -> None:
        self.results_path = results_tsv_path
        self.tuning_history_path = tuning_history_path
        self.current_iter = current_iteration
        self.cooldown = cooldown
        self._records: list[ResultsRecord] = []
        self._history: list[dict[str, Any]] = []

    def load(self) -> None:
        """Load results.tsv and tuning history."""
        self._records = parse_results_tsv(self.results_path)
        self._history = self._load_tuning_history()

    def _load_tuning_history(self) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        path = Path(self.tuning_history_path)
        if not path.exists():
            return history
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    history.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return history

    def _last_adjusted_iter(self, setting: str) -> int | None:
        """Return the most recent iteration where `setting` was adjusted."""
        for entry in reversed(self._history):
            for adj in entry.get("adjustments", []):
                if adj.get("setting") == setting:
                    return entry.get("iteration")
        return None

    def _on_cooldown(self, setting: str) -> bool:
        last = self._last_adjusted_iter(setting)
        if last is None:
            return False
        return (self.current_iter - last) < self.cooldown

    def _metrics_for_iter(self, iteration: int) -> IterationMetrics:
        """Build aggregated metrics for a single iteration."""
        rows = [r for r in self._records if _safe_int(r.spiral_iter) == iteration]
        m = IterationMetrics(iteration=iteration)
        m.total_attempts = len(rows)
        if not rows:
            return m

        durations: list[float] = []
        total_duration = 0.0

        for r in rows:
            status = (r.status or "").lower()
            model = (r.model or "").lower()
            dur = 0.0
            try:
                dur = float(r.duration_sec or 0)
            except ValueError:
                pass
            durations.append(dur)
            total_duration += dur

            if status == "pass":
                m.passed += 1
            else:
                m.failed += 1

            if _is_timeout_failure(r):
                m.timeout_count += 1
            if _is_oversized_diff(r):
                m.oversized_diff_count += 1
            if _has_conflicts(r):
                m.conflict_count += 1

            retry = _safe_int(r.retry_num)
            if retry >= 3:
                m.max_retry_reached += 1
            if retry >= 2:
                m.retry_2_plus += 1

            # Model tracking
            if "haiku" in model:
                m.haiku_attempts += 1
                if status == "pass":
                    m.haiku_passes += 1
            elif "sonnet" in model:
                m.sonnet_attempts += 1
                if status == "pass":
                    m.sonnet_passes += 1
            elif "opus" in model:
                m.opus_attempts += 1
                if status == "pass":
                    m.opus_passes += 1

            # RSS tracking
            rss = _safe_int(r.peak_rss_kb)
            if rss > 0:
                m.peak_rss_values.append(rss)
                tier = "small" if "haiku" in model else ("medium" if "sonnet" in model else "large")
                m.model_rss.setdefault(tier, []).append(rss)

            # Failure categories
            frc = r.failure_root_cause or r.error_category or "unknown"
            if status != "pass":
                m.failure_categories[frc] = m.failure_categories.get(frc, 0) + 1

        m.velocity = float(m.passed)
        m.avg_duration_sec = total_duration / len(rows) if rows else 0.0
        m.max_duration_sec = max(durations) if durations else 0.0
        m.cost_proxy = total_duration / m.passed if m.passed > 0 else total_duration

        return m

    def _recent_metrics(self, lookback: int = 3) -> list[IterationMetrics]:
        """Get metrics for the last `lookback` iterations (most recent last)."""
        start = max(1, self.current_iter - lookback + 1)
        metrics = []
        for i in range(start, self.current_iter + 1):
            m = self._metrics_for_iter(i)
            if m.total_attempts > 0:
                metrics.append(m)
        return metrics

    # ── Tuning rules ─────────────────────────────────────────────────────────

    def _rule_timeout_scaling(self, recent: list[IterationMetrics]) -> list[TuningAdjustment]:
        """Rule 1: Scale timeouts based on timeout failure rate."""
        adjustments: list[TuningAdjustment] = []
        if not recent or len(recent) < 2:
            return adjustments

        last2 = recent[-2:]
        total = sum(m.total_attempts for m in last2)
        timeouts = sum(m.timeout_count for m in last2)
        if total == 0:
            return adjustments

        rate = timeouts / total

        timeout_vars = [
            ("SPIRAL_IMPL_TIMEOUT", 2400),
            ("SPIRAL_WORKER_TIMEOUT", 2400),
            ("SPIRAL_STORY_TIMEOUT_SMALL", 1200),
            ("SPIRAL_STORY_TIMEOUT_MEDIUM", 1800),
            ("SPIRAL_STORY_TIMEOUT_LARGE", 3600),
        ]

        if rate > 0.30:
            for var, default in timeout_vars:
                if self._on_cooldown(var):
                    continue
                current = _env_int(var, default)
                new_val = _clamp(int(current * 1.25), var)
                if new_val != current:
                    adjustments.append(
                        TuningAdjustment(
                            setting=var,
                            old_value=str(current),
                            new_value=str(new_val),
                            rule_name="timeout_scaling",
                            reason=f"Timeout rate {rate:.0%} > 30% in last 2 iters — increasing by 25%",
                        )
                    )
        elif rate < 0.05:
            # Check if avg duration is well below limit
            avg_dur = sum(m.avg_duration_sec for m in last2) / len(last2)
            limit = _env_int("SPIRAL_STORY_TIMEOUT_LARGE", 3600)
            if avg_dur < limit * 0.50:
                for var, default in timeout_vars:
                    if self._on_cooldown(var):
                        continue
                    current = _env_int(var, default)
                    new_val = _clamp(int(current * 0.85), var)
                    if new_val != current:
                        adjustments.append(
                            TuningAdjustment(
                                setting=var,
                                old_value=str(current),
                                new_value=str(new_val),
                                rule_name="timeout_scaling",
                                reason=(
                                    f"Timeout rate {rate:.0%} < 5%,"
                                    f" avg duration {avg_dur:.0f}s < 50% of limit"
                                    " — decreasing by 15%"
                                ),
                            )
                        )

        return adjustments

    def _rule_diff_limit(self, recent: list[IterationMetrics]) -> TuningAdjustment | None:
        """Rule 2: Adjust SPIRAL_MAX_DIFF_LINES by oversized_diff rate."""
        if self._on_cooldown("SPIRAL_MAX_DIFF_LINES"):
            return None
        if not recent:
            return None

        last2 = recent[-2:] if len(recent) >= 2 else recent
        total = sum(m.failed for m in last2)
        oversized = sum(m.oversized_diff_count for m in last2)

        current = _env_int("SPIRAL_MAX_DIFF_LINES", 800)

        if total > 0 and (oversized / total) > 0.20:
            new_val = _clamp(current + 200, "SPIRAL_MAX_DIFF_LINES")
            if new_val != current:
                return TuningAdjustment(
                    setting="SPIRAL_MAX_DIFF_LINES",
                    old_value=str(current),
                    new_value=str(new_val),
                    rule_name="diff_limit_scaling",
                    reason=(
                        f"{oversized}/{total} failures ({oversized / total:.0%}) are oversized_diff — increasing by 200"
                    ),
                )

        # Decrease if 0 oversized for 3+ iterations
        if len(recent) >= 3:
            last3_oversized = sum(m.oversized_diff_count for m in recent[-3:])
            if last3_oversized == 0 and current > 400:
                new_val = _clamp(current - 100, "SPIRAL_MAX_DIFF_LINES")
                if new_val != current:
                    return TuningAdjustment(
                        setting="SPIRAL_MAX_DIFF_LINES",
                        old_value=str(current),
                        new_value=str(new_val),
                        rule_name="diff_limit_scaling",
                        reason="0 oversized_diff failures for 3 iterations — decreasing by 100",
                    )

        return None

    def _rule_model_floor(self, recent: list[IterationMetrics]) -> list[TuningAdjustment]:
        """Rule 3: Skip haiku/sonnet if success rate is too low."""
        adjustments: list[TuningAdjustment] = []
        if len(recent) < 3:
            return adjustments

        last3 = recent[-3:]

        # Haiku success rate
        haiku_attempts = sum(m.haiku_attempts for m in last3)
        haiku_passes = sum(m.haiku_passes for m in last3)
        if haiku_attempts >= 3:  # need meaningful sample
            haiku_rate = haiku_passes / haiku_attempts
            if haiku_rate < 0.30:
                current = _env_int("SPIRAL_ESCALATION_RETRY_SONNET", 1)
                if current > 0 and not self._on_cooldown("SPIRAL_ESCALATION_RETRY_SONNET"):
                    adjustments.append(
                        TuningAdjustment(
                            setting="SPIRAL_ESCALATION_RETRY_SONNET",
                            old_value=str(current),
                            new_value="0",
                            rule_name="model_floor_escalation",
                            reason=(
                                f"Haiku success rate {haiku_rate:.0%} < 30%"
                                f" over 3 iters ({haiku_passes}/{haiku_attempts})"
                                " — skipping haiku"
                            ),
                        )
                    )

        # Sonnet success rate
        sonnet_attempts = sum(m.sonnet_attempts for m in last3)
        sonnet_passes = sum(m.sonnet_passes for m in last3)
        if sonnet_attempts >= 3:
            sonnet_rate = sonnet_passes / sonnet_attempts
            if sonnet_rate < 0.40:
                current = _env_int("SPIRAL_ESCALATION_RETRY_OPUS", 2)
                if current > 0 and not self._on_cooldown("SPIRAL_ESCALATION_RETRY_OPUS"):
                    adjustments.append(
                        TuningAdjustment(
                            setting="SPIRAL_ESCALATION_RETRY_OPUS",
                            old_value=str(current),
                            new_value="0",
                            rule_name="model_floor_escalation",
                            reason=(
                                f"Sonnet success rate {sonnet_rate:.0%} < 40%"
                                f" over 3 iters ({sonnet_passes}/{sonnet_attempts})"
                                " — starting at opus"
                            ),
                        )
                    )

        return adjustments

    def _rule_worker_count(self, recent: list[IterationMetrics]) -> TuningAdjustment | None:
        """Rule 4: Adjust worker count based on merge conflict rate."""
        if self._on_cooldown("SPIRAL_RALPH_WORKERS"):
            return None
        if not recent:
            return None

        current = _env_int("SPIRAL_RALPH_WORKERS", 2)

        # Reduce on high conflict rate
        last2 = recent[-2:] if len(recent) >= 2 else recent
        total = sum(m.total_attempts for m in last2)
        conflicts = sum(m.conflict_count for m in last2)
        if total > 0 and (conflicts / total) > 0.15:
            new_val = _clamp(current - 1, "SPIRAL_RALPH_WORKERS")
            if new_val != current:
                return TuningAdjustment(
                    setting="SPIRAL_RALPH_WORKERS",
                    old_value=str(current),
                    new_value=str(new_val),
                    rule_name="worker_count",
                    reason=f"Conflict rate {conflicts / total:.0%} > 15% — reducing workers by 1",
                )

        # Increase when stable (0 conflicts for 3 iters)
        if len(recent) >= 3:
            last3_conflicts = sum(m.conflict_count for m in recent[-3:])
            if last3_conflicts == 0 and current < 3:
                new_val = _clamp(current + 1, "SPIRAL_RALPH_WORKERS")
                if new_val != current:
                    return TuningAdjustment(
                        setting="SPIRAL_RALPH_WORKERS",
                        old_value=str(current),
                        new_value=str(new_val),
                        rule_name="worker_count",
                        reason="0 merge conflicts for 3 iterations — increasing workers by 1",
                    )

        return None

    def _rule_batch_size(self, recent: list[IterationMetrics]) -> TuningAdjustment | None:
        """Rule 5: Adjust batch size based on velocity."""
        if self._on_cooldown("SPIRAL_STORY_BATCH_SIZE"):
            return None
        if len(recent) < 2:
            return None

        current = _env_int("SPIRAL_STORY_BATCH_SIZE", 10)

        # Decrease on low velocity
        last2 = recent[-2:]
        if all(m.velocity < 1.0 for m in last2):
            new_val = _clamp(current - 2, "SPIRAL_STORY_BATCH_SIZE")
            if new_val != current:
                vels = [m.velocity for m in last2]
                return TuningAdjustment(
                    setting="SPIRAL_STORY_BATCH_SIZE",
                    old_value=str(current),
                    new_value=str(new_val),
                    rule_name="batch_size",
                    reason=f"Velocity {vels} < 1.0 for 2 consecutive iters — reducing batch by 2",
                )

        # Increase on high velocity
        if recent[-1].velocity > 4.0:
            new_val = _clamp(current + 2, "SPIRAL_STORY_BATCH_SIZE")
            if new_val != current:
                return TuningAdjustment(
                    setting="SPIRAL_STORY_BATCH_SIZE",
                    old_value=str(current),
                    new_value=str(new_val),
                    rule_name="batch_size",
                    reason=f"Velocity {recent[-1].velocity:.1f} > 4.0 — increasing batch by 2",
                )

        return None

    def _rule_decompose_threshold(self, recent: list[IterationMetrics]) -> TuningAdjustment | None:
        """Rule 6: Adjust decompose threshold based on max-retry rate."""
        if self._on_cooldown("SPIRAL_DECOMPOSE_THRESHOLD"):
            return None
        if not recent:
            return None

        current = _env_int("SPIRAL_DECOMPOSE_THRESHOLD", 3)
        last2 = recent[-2:] if len(recent) >= 2 else recent

        total = sum(m.total_attempts for m in last2)
        max_retries = sum(m.max_retry_reached for m in last2)

        if total > 0 and (max_retries / total) > 0.40:
            new_val = _clamp(current - 1, "SPIRAL_DECOMPOSE_THRESHOLD")
            if new_val != current:
                return TuningAdjustment(
                    setting="SPIRAL_DECOMPOSE_THRESHOLD",
                    old_value=str(current),
                    new_value=str(new_val),
                    rule_name="decompose_threshold",
                    reason=(
                        f"{max_retries}/{total} attempts ({max_retries / total:.0%}) hit max retry — lowering threshold"
                    ),
                )

        # Raise if very few reach retry 2
        retry2 = sum(m.retry_2_plus for m in last2)
        if total > 0 and (retry2 / total) < 0.10 and current < 4:
            new_val = _clamp(current + 1, "SPIRAL_DECOMPOSE_THRESHOLD")
            if new_val != current:
                return TuningAdjustment(
                    setting="SPIRAL_DECOMPOSE_THRESHOLD",
                    old_value=str(current),
                    new_value=str(new_val),
                    rule_name="decompose_threshold",
                    reason=(
                        f"Only {retry2 / total:.0%} reach retry 2+ — raising threshold (stories don't need early split)"
                    ),
                )

        return None

    def _rule_thinking_effort(self, recent: list[IterationMetrics]) -> TuningAdjustment | None:
        """Rule 7: Downgrade thinking effort if cost doubles without gains."""
        if self._on_cooldown("SPIRAL_THINKING_EFFORT"):
            return None
        if len(recent) < 3:
            return None

        current = _env_str("SPIRAL_THINKING_EFFORT", "max")
        if current not in EFFORT_LEVELS:
            return None
        idx = EFFORT_LEVELS.index(current)
        if idx == 0:  # already at minimum (medium)
            return None

        # Compare cost proxy: current vs 3 iters ago
        baseline = recent[0]
        latest = recent[-1]

        if baseline.cost_proxy <= 0 or latest.cost_proxy <= 0:
            return None

        cost_ratio = latest.cost_proxy / baseline.cost_proxy

        if cost_ratio >= 2.0:
            # Check if pass rate improved enough to justify the cost
            baseline_rate = baseline.passed / baseline.total_attempts if baseline.total_attempts > 0 else 0
            latest_rate = latest.passed / latest.total_attempts if latest.total_attempts > 0 else 0
            improvement = (latest_rate - baseline_rate) / max(baseline_rate, 0.01)

            if improvement < 0.20:
                new_effort = EFFORT_LEVELS[idx - 1]
                return TuningAdjustment(
                    setting="SPIRAL_THINKING_EFFORT",
                    old_value=current,
                    new_value=new_effort,
                    rule_name="thinking_effort",
                    reason=(
                        f"Cost-per-pass doubled ({cost_ratio:.1f}x)"
                        f" without proportional gain ({improvement:+.0%})"
                        " — downgrading effort"
                    ),
                )

        return None

    def _rule_memory_pool(self, recent: list[IterationMetrics]) -> list[TuningAdjustment]:
        """Rule 8: Scale memory pool tiers when RSS exceeds 80% of allocation."""
        adjustments: list[TuningAdjustment] = []
        if not recent:
            return adjustments

        tier_map = {
            "small": ("SPIRAL_POOL_TIER_SMALL", 768),
            "medium": ("SPIRAL_POOL_TIER_MEDIUM", 1536),
            "large": ("SPIRAL_POOL_TIER_LARGE", 2560),
        }

        # Aggregate RSS across recent iterations
        combined_rss: dict[str, list[int]] = {}
        for m in recent[-2:]:
            for tier, values in m.model_rss.items():
                combined_rss.setdefault(tier, []).extend(values)

        for tier, (var, default) in tier_map.items():
            if self._on_cooldown(var):
                continue
            rss_values = combined_rss.get(tier, [])
            if len(rss_values) < 3:
                continue

            allocation_kb = _env_int(var, default) * 1024  # MB → KB
            threshold = allocation_kb * 0.80
            exceeding = sum(1 for v in rss_values if v > threshold)
            rate = exceeding / len(rss_values)

            if rate > 0.30:
                current = _env_int(var, default)
                new_val = _clamp(current + 256, var)
                if new_val != current:
                    adjustments.append(
                        TuningAdjustment(
                            setting=var,
                            old_value=str(current),
                            new_value=str(new_val),
                            rule_name="memory_pool_scaling",
                            reason=f"{rate:.0%} of {tier} stories exceed 80% RSS allocation — increasing by 256MB",
                        )
                    )

        return adjustments

    # ── Main compute ─────────────────────────────────────────────────────────

    def compute_adjustments(self) -> list[TuningAdjustment]:
        """Run all 8 rules and return a list of adjustments."""
        recent = self._recent_metrics(lookback=3)
        if not recent:
            return []

        adjustments: list[TuningAdjustment] = []

        # Rule 1: Timeout scaling (returns list)
        adjustments.extend(self._rule_timeout_scaling(recent))

        # Rule 2: Diff limit
        adj = self._rule_diff_limit(recent)
        if adj:
            adjustments.append(adj)

        # Rule 3: Model floor (returns list)
        adjustments.extend(self._rule_model_floor(recent))

        # Rule 4: Worker count
        adj = self._rule_worker_count(recent)
        if adj:
            adjustments.append(adj)

        # Rule 5: Batch size
        adj = self._rule_batch_size(recent)
        if adj:
            adjustments.append(adj)

        # Rule 6: Decompose threshold
        adj = self._rule_decompose_threshold(recent)
        if adj:
            adjustments.append(adj)

        # Rule 7: Thinking effort
        adj = self._rule_thinking_effort(recent)
        if adj:
            adjustments.append(adj)

        # Rule 8: Memory pool (returns list)
        adjustments.extend(self._rule_memory_pool(recent))

        return adjustments

    def persist(self, adjustments: list[TuningAdjustment]) -> None:
        """Append adjustments to tuning_history.jsonl."""
        if not adjustments:
            return

        from datetime import datetime, timezone

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "iteration": self.current_iter,
            "adjustments": [asdict(a) for a in adjustments],
        }

        path = Path(self.tuning_history_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")


# ── CLI entry point ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """
    CLI entry point called by phase_st_self_tune.sh.

    Args: results_tsv tuning_history scratch_dir current_iter
    Output: JSON to stdout with {"adjustments": [...], "exports": {...}}
    """
    args = argv or sys.argv[1:]

    if len(args) < 4:
        print(
            "Usage: self_tune.py <results_tsv> <tuning_history> <scratch_dir> <current_iter>",
            file=sys.stderr,
        )
        return 1

    results_tsv = args[0]
    tuning_history = args[1]
    _scratch_dir = args[2]
    current_iter = int(args[3])

    if not Path(results_tsv).exists():
        # No results yet — nothing to tune
        print(json.dumps({"adjustments": [], "exports": {}}))
        return 0

    tuner = SelfTuner(
        results_tsv_path=results_tsv,
        tuning_history_path=tuning_history,
        current_iteration=current_iter,
    )
    tuner.load()
    adjustments = tuner.compute_adjustments()
    tuner.persist(adjustments)

    exports: dict[str, str] = {}
    adj_list: list[dict[str, str]] = []
    for a in adjustments:
        exports[a.setting] = a.new_value
        adj_list.append(asdict(a))

    output = {"adjustments": adj_list, "exports": exports}
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
