"""lib/escalation_predictor.py — Model Escalation Prediction Engine (US-1058).

Predicts when stories will escalate to sonnet/opus based on token spend trajectory.
Uses linear regression on (attempt_number → total_tokens) to forecast next attempt.

Model thresholds:
  haiku  → sonnet  at 50_000 tokens
  sonnet → opus    at 150_000 tokens
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

# Token thresholds for model escalation (matches SPIRAL model routing config)
HAIKU_TO_SONNET_THRESHOLD: int = 50_000
SONNET_TO_OPUS_THRESHOLD: int = 150_000

MODEL_ORDER = ["haiku", "sonnet", "opus"]


@dataclass
class EscalationPrediction:
    story_id: str
    current_model: str
    predicted_model: str
    confidence_pct: float
    tokens_until_escalation: int
    attempt_count: int


def _total_tokens(row: dict[str, str]) -> int:
    """Sum all token columns for a single results.tsv row."""
    total = 0
    for col in ("cache_read_tokens", "cache_creation_tokens", "review_tokens"):
        try:
            total += int(row.get(col, 0) or 0)
        except (ValueError, TypeError):
            pass
    return total


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Return (slope, intercept) for a least-squares linear fit.

    Falls back to (0, mean_y) if there are fewer than 2 points or zero variance.
    """
    n = len(xs)
    if n < 2:
        mean_y = sum(ys) / max(n, 1)
        return 0.0, mean_y

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0.0:
        return 0.0, mean_y
    slope = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n)) / denom
    intercept = mean_y - slope * mean_x
    return slope, intercept


def _r_squared(xs: list[float], ys: list[float], slope: float, intercept: float) -> float:
    """Return R² goodness-of-fit (0..1). Returns 1.0 for single-point data."""
    if len(xs) < 2:
        return 1.0
    mean_y = sum(ys) / len(ys)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    if ss_tot == 0.0:
        return 1.0
    ss_res = sum((ys[i] - (slope * xs[i] + intercept)) ** 2 for i in range(len(xs)))
    return max(0.0, 1.0 - ss_res / ss_tot)


def _current_model_from_rows(rows: list[dict[str, str]]) -> str:
    """Return the model used in the most recent attempt (highest retry_num)."""
    best_retry = -1
    best_model = "haiku"
    for row in rows:
        try:
            retry = int(row.get("retry_num", 0) or 0)
        except (ValueError, TypeError):
            retry = 0
        model = (row.get("model") or "haiku").lower()
        if retry >= best_retry:
            best_retry = retry
            best_model = model
    return best_model


def predict_for_story(
    story_id: str,
    results_tsv: Path,
) -> EscalationPrediction | None:
    """Predict next-attempt model escalation for a single story.

    Returns None if the story has no rows in results.tsv.
    """
    rows: list[dict[str, str]] = []
    if results_tsv.exists():
        with open(results_tsv, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                if row.get("story_id") == story_id:
                    rows.append(row)

    if not rows:
        return None

    # Build (attempt_number, token_count) pairs sorted by retry_num
    attempt_tokens: list[tuple[int, int]] = []
    for row in rows:
        try:
            attempt = int(row.get("retry_num", 0) or 0)
        except (ValueError, TypeError):
            attempt = 0
        tokens = _total_tokens(row)
        attempt_tokens.append((attempt, tokens))

    attempt_tokens.sort(key=lambda x: x[0])
    xs = [float(a) for a, _ in attempt_tokens]
    ys = [float(t) for _, t in attempt_tokens]

    slope, intercept = _linear_regression(xs, ys)
    r2 = _r_squared(xs, ys, slope, intercept)

    # Predict tokens for next attempt
    next_attempt = (max(xs) + 1.0) if xs else 1.0
    predicted_tokens = max(0.0, slope * next_attempt + intercept)

    current_model = _current_model_from_rows(rows)
    current_tokens = ys[-1] if ys else 0.0

    # Determine escalation threshold to watch
    if current_model == "haiku":
        threshold = HAIKU_TO_SONNET_THRESHOLD
        next_model = "sonnet"
    elif current_model == "sonnet":
        threshold = SONNET_TO_OPUS_THRESHOLD
        next_model = "opus"
    else:
        # Already at opus — no further escalation
        return EscalationPrediction(
            story_id=story_id,
            current_model="opus",
            predicted_model="opus",
            confidence_pct=100.0,
            tokens_until_escalation=0,
            attempt_count=len(rows),
        )

    will_escalate = predicted_tokens >= threshold

    # Confidence: blend R² with trajectory steepness signal
    # High R² + obvious trend → high confidence
    base_confidence = r2 * 100.0
    # Boost confidence when the prediction is far beyond the threshold
    if will_escalate:
        overshoot_ratio = min(predicted_tokens / max(threshold, 1.0), 3.0)
        confidence_pct = min(99.0, base_confidence * overshoot_ratio)
    else:
        confidence_pct = min(99.0, base_confidence)

    # If only 1 data point and not near threshold, set lower confidence
    if len(rows) == 1:
        confidence_pct = min(confidence_pct, 60.0)

    predicted_model = next_model if will_escalate else current_model
    tokens_until = max(0, int(threshold - current_tokens))

    return EscalationPrediction(
        story_id=story_id,
        current_model=current_model,
        predicted_model=predicted_model,
        confidence_pct=round(confidence_pct, 1),
        tokens_until_escalation=tokens_until,
        attempt_count=len(rows),
    )


def predict_all_stories(
    results_tsv: Path,
) -> list[EscalationPrediction]:
    """Predict escalation for every story in results.tsv.

    Returns predictions sorted by escalation likelihood (descending confidence
    for escalating stories first).
    """
    if not results_tsv.exists():
        return []

    story_ids: list[str] = []
    seen: set[str] = set()
    with open(results_tsv, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            sid = row.get("story_id", "")
            if sid and sid not in seen:
                seen.add(sid)
                story_ids.append(sid)

    predictions: list[EscalationPrediction] = []
    for sid in story_ids:
        pred = predict_for_story(sid, results_tsv)
        if pred is not None:
            predictions.append(pred)

    # Sort: escalating stories first (by confidence desc), then stable stories
    def sort_key(p: EscalationPrediction) -> tuple[int, float]:
        escalating = 1 if p.predicted_model != p.current_model else 0
        return (-escalating, -p.confidence_pct)

    predictions.sort(key=sort_key)
    return predictions


def format_prediction(pred: EscalationPrediction) -> str:
    """Return a human-readable single-line summary for CLI output."""
    direction = (
        f"{pred.current_model} → {pred.predicted_model}"
        if pred.predicted_model != pred.current_model
        else f"stays {pred.current_model}"
    )
    escalation_note = ""
    if pred.predicted_model == pred.current_model and pred.tokens_until_escalation > 0:
        escalation_note = f"  ({pred.tokens_until_escalation:,} tokens until escalation)"
    return (
        f"{pred.story_id:<20} {direction:<25} "
        f"confidence={pred.confidence_pct:.0f}%  "
        f"attempts={pred.attempt_count}"
        f"{escalation_note}"
    )


def _sigmoid(x: float) -> float:
    """Logistic sigmoid for clamping confidence near threshold."""
    return 1.0 / (1.0 + math.exp(-x))
