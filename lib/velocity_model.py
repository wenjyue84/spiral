#!/usr/bin/env python3
"""
velocity_model.py — Cross-iteration story velocity model for SPIRAL.

Reads results.tsv, groups rows by story_type (keyword heuristic on title),
computes empirical stats per type, and saves a velocity model JSON.

Used by cost_project.py to produce data-driven per-type cost estimates.

Usage:
    python lib/velocity_model.py --results results.tsv --output .spiral/velocity_model.json
    python lib/velocity_model.py --results results.tsv --report
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from constants import (
    INPUT_OUTPUT_RATIO,
    MIN_HISTORY_ROWS,
    PRICING,
    TOKENS_PER_SEC_OUTPUT,
)

# --- Story type keyword classification ---

# Ordered list of (story_type, [keywords]).
# First match wins; "general" is the catch-all at the end.
_STORY_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("test", ["test", "pytest", "bats", "coverage", "hypothesis", "regression"]),
    ("ci", ["ci", "github action", "workflow", "lint", "shellcheck", "shfmt"]),
    ("ui", ["ui", "dashboard", "tui", "widget", "render", "display", "visual"]),
    ("git_workflow", ["git fetch", "worktree", "commit", "branch", "push", "pull"]),
    ("schema", ["schema", "validate", "validation", "draft 2020"]),
    ("cost", ["cost", "token", "estimate", "budget", "projection"]),
    ("security", ["security", "secret", "scan", "auth", "credential"]),
    ("research", ["research", "gemini", "web search", "synthesis"]),
    ("story_management", ["story", "prd", "merge", "decompose", "phase"]),
    ("performance", ["performance", "speed", "fast", "cache", "parallel", "latency"]),
    ("observability", ["otel", "opentelemetry", "span", "metric", "trace", "log"]),
    ("general", []),  # catch-all
]


def classify_story(title: str) -> str:
    """Return the story_type for a given story title using keyword matching."""
    import re

    title_lower = title.lower()
    for story_type, keywords in _STORY_TYPE_RULES:
        if not keywords:  # catch-all
            return story_type
        for kw in keywords:
            # Use word-boundary matching for short (≤3 char) keywords to avoid
            # false matches like "ci" inside "cross-iteration".
            if len(kw) <= 3:
                if re.search(r"\b" + re.escape(kw) + r"\b", title_lower):
                    return story_type
            elif kw in title_lower:
                return story_type
    return "general"


def _tokens_from_duration(duration_sec: float) -> float:
    """Estimate total tokens from wall-clock duration (mirrors cost_project.py)."""
    output = duration_sec * TOKENS_PER_SEC_OUTPUT
    return output * (1 + INPUT_OUTPUT_RATIO)


def _cost_from_tokens(total_tokens: float, model_raw: str) -> float:
    """Estimate USD cost from total tokens and model string."""
    model = _normalise_model(model_raw)
    p = PRICING[model]
    output = total_tokens / (1 + INPUT_OUTPUT_RATIO)
    input_ = total_tokens - output
    return (input_ / 1_000_000) * p["input"] + (output / 1_000_000) * p["output"]


def _normalise_model(raw: str) -> str:
    raw_lower = raw.strip().lower() if raw else ""
    for key in PRICING:
        if key in raw_lower:
            return key
    return "sonnet"


# Rolling window: only use the last N rows per story type
_ROLLING_WINDOW = 50


def build_velocity_model(results_path: str) -> dict[str, Any]:
    """
    Read results.tsv and compute per-story-type stats.

    Returns a dict:
    {
        "story_types": {
            "<type>": {
                "samples": int,
                "mean_tokens": float,
                "mean_cost_usd": float,
                "pass_rate": float,
                "mean_retries": float
            },
            ...
        },
        "total_rows": int,
        "source": "<path>"
    }
    """
    if not os.path.isfile(results_path):
        return {"story_types": {}, "total_rows": 0, "source": results_path}

    # Collect raw rows per type (keep last _ROLLING_WINDOW per type)
    from collections import defaultdict, deque

    raw: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=_ROLLING_WINDOW))
    total_rows = 0

    with open(results_path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            total_rows += 1
            title = (row.get("story_title") or "").strip()
            if not title:
                continue
            story_type = classify_story(title)

            duration_raw = row.get("duration_sec") or ""
            try:
                duration = float(duration_raw)
            except (ValueError, TypeError):
                duration = 0.0

            status = (row.get("status") or "").strip().lower()
            retry_raw = row.get("retry_num") or "0"
            try:
                retry_num = int(retry_raw)
            except (ValueError, TypeError):
                retry_num = 0

            model_raw = (row.get("model") or "sonnet").strip()

            raw[story_type].append(
                {
                    "duration": duration,
                    "status": status,
                    "retry_num": retry_num,
                    "model": model_raw,
                }
            )

    # Compute stats per type
    story_types: dict[str, Any] = {}
    for story_type, rows in raw.items():
        usable = [r for r in rows if r["duration"] > 0]
        n = len(usable)

        if n == 0:
            tokens_vals = []
            cost_vals = []
        else:
            tokens_vals = [_tokens_from_duration(r["duration"]) for r in usable]
            cost_vals = [_cost_from_tokens(t, r["model"]) for t, r in zip(tokens_vals, usable)]

        mean_tokens = sum(tokens_vals) / len(tokens_vals) if tokens_vals else 0.0
        mean_cost = sum(cost_vals) / len(cost_vals) if cost_vals else 0.0

        pass_count = sum(1 for r in rows if r["status"] in ("pass", "commit", "merged"))
        pass_rate = pass_count / len(rows) if rows else 0.0

        retry_vals = [r["retry_num"] for r in rows]
        mean_retries = sum(retry_vals) / len(retry_vals) if retry_vals else 0.0

        story_types[story_type] = {
            "samples": len(rows),
            "usable_duration_samples": n,
            "mean_tokens": round(mean_tokens, 1),
            "mean_cost_usd": round(mean_cost, 6),
            "pass_rate": round(pass_rate, 4),
            "mean_retries": round(mean_retries, 2),
        }

    return {
        "story_types": story_types,
        "total_rows": total_rows,
        "source": results_path,
    }


def get_story_estimate(
    title: str,
    velocity_model: dict[str, Any],
    min_samples: int = MIN_HISTORY_ROWS,
) -> dict[str, Any] | None:
    """
    Return empirical stats for a story if enough history exists, else None.

    Returns dict with keys: story_type, samples, mean_tokens, mean_cost_usd,
    pass_rate, mean_retries. Returns None when history is below min_samples.
    """
    story_type = classify_story(title)
    types = velocity_model.get("story_types", {})
    entry = types.get(story_type)
    if entry is None:
        return None
    if entry.get("usable_duration_samples", entry.get("samples", 0)) < min_samples:
        return None
    return {"story_type": story_type, **entry}


def save_velocity_model(model: dict[str, Any], output_path: str) -> None:
    """Write velocity model JSON atomically."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    os.replace(tmp, output_path)


def load_velocity_model(path: str) -> dict[str, Any]:
    """Load velocity model JSON; return empty model on missing/corrupt file."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        return {"story_types": {}, "total_rows": 0, "source": path}


def format_report(model: dict[str, Any]) -> str:
    """Return a plain-text table of the velocity model."""
    types = model.get("story_types", {})
    if not types:
        return "  [velocity-model] No historical data available.\n"

    col_w = [18, 8, 12, 10, 12, 10]
    header = (
        f"  {'story_type':<{col_w[0]}} "
        f"{'samples':>{col_w[1]}} "
        f"{'mean_tokens':>{col_w[2]}} "
        f"{'mean_cost':>{col_w[3]}} "
        f"{'pass_rate':>{col_w[4]}} "
        f"{'est_retries':>{col_w[5]}}"
    )
    sep = "  " + "-" * (sum(col_w) + len(col_w) - 1)

    rows_out = [
        "",
        "  +-------------------------------------------------------------------+",
        "  |  SPIRAL -- Story Velocity Model                                   |",
        "  +-------------------------------------------------------------------+",
        "",
        header,
        sep,
    ]

    for story_type, entry in sorted(types.items()):
        samples = entry.get("samples", 0)
        mean_tokens = entry.get("mean_tokens", 0.0)
        mean_cost = entry.get("mean_cost_usd", 0.0)
        pass_rate = entry.get("pass_rate", 0.0)
        mean_retries = entry.get("mean_retries", 0.0)
        marker = "" if samples >= MIN_HISTORY_ROWS else "*"
        rows_out.append(
            f"  {story_type+marker:<{col_w[0]}} "
            f"{samples:>{col_w[1]}} "
            f"{int(mean_tokens):>{col_w[2]},} "
            f"${mean_cost:>{col_w[3]-1}.4f} "
            f"{pass_rate:>{col_w[4]}.1%} "
            f"{mean_retries:>{col_w[5]}.2f}"
        )

    rows_out.append(sep)
    rows_out.append(f"  * = fewer than {MIN_HISTORY_ROWS} samples; static default used for estimates")
    rows_out.append(f"  Total rows in results.tsv: {model.get('total_rows', 0)}")
    rows_out.append("")
    return "\n".join(rows_out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SPIRAL story velocity model builder")
    parser.add_argument("--results", default="results.tsv", help="Path to results.tsv")
    parser.add_argument(
        "--output",
        default=".spiral/velocity_model.json",
        help="Path to save velocity model JSON",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print velocity report table to stdout",
    )
    args = parser.parse_args(argv)

    model = build_velocity_model(args.results)
    save_velocity_model(model, args.output)

    if args.report:
        print(format_report(model))

    return 0


if __name__ == "__main__":
    sys.exit(main())
