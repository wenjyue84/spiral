#!/usr/bin/env python3
"""cli_explain_learning.py — Display temporal evolution of learned patterns.

Reads .spiral/pattern_evolution.jsonl and displays timeline graphs and
recommendations for when to apply patterns during future iterations.
"""

import json
import sys
from typing import Any


def load_pattern_evolution(jsonl_path: str) -> list[dict[str, Any]]:
    """Load pattern evolution metrics from JSONL file."""
    metrics = []
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    metrics.append(obj)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return metrics


def format_timeline(metric: dict[str, Any]) -> str:
    """Format a pattern's timeline as ASCII graph."""
    first_iter = metric.get("first_iteration", 0)
    last_iter = metric.get("last_iteration", 0)

    # Build simple ASCII timeline
    range_width = max(1, last_iter - first_iter + 1)
    timeline = ["["] + ["-"] * range_width + ["]"]
    return "".join(timeline)


def format_model_affinity(metric: dict[str, Any]) -> str:
    """Format model affinity ranking as human-readable text."""
    affinity = metric.get("model_affinity_rank", [])
    if not affinity:
        return "  No model affinity data"

    lines = []
    for i, (model, count) in enumerate(affinity, 1):
        lines.append(f"  {i}. {model} (used {count}x)")
    return "\n".join(lines)


def explain_learning(jsonl_path: str, pattern_type: str = "") -> None:
    """Display learned pattern evolution timeline and recommendations."""
    metrics = load_pattern_evolution(jsonl_path)

    if not metrics:
        print("[spiral] No pattern evolution data found.")
        return

    # Filter by pattern type if specified
    if pattern_type:
        metrics = [m for m in metrics if m.get("pattern_type") == pattern_type]

        if not metrics:
            print(f"[spiral] No patterns found matching type: {pattern_type}")
            return

    # Display header
    print("")
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  📈 PATTERN EVOLUTION TIMELINE")
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("")

    # Display each pattern
    for metric in sorted(metrics, key=lambda m: m.get("first_iteration", 0)):
        p_type = metric.get("pattern_type", "unknown")
        first = metric.get("first_iteration", 0)
        last = metric.get("last_iteration", 0)
        freq = metric.get("frequency", 0)

        print(f"  Pattern: {p_type}")
        print(f"    Timeline: Iter {first} → {last} ({last - first + 1} iterations)")
        print(f"    Frequency: {freq} occurrences")
        print(f"    Timeline: {format_timeline(metric)}")
        print("")
        print("  Model Affinity (helpful for):")
        print(format_model_affinity(metric))
        print("")
        print("  Recommendations:")
        if first <= 5:
            print("    • Early pattern — appears consistently from start")
            print("    • Apply early in iterations for reliability")
        elif last >= 15:  # Assume ~20 iterations typical
            print("    • Late-game pattern — emerges in later iterations")
            print("    • Most useful for complex/refined stories")
        else:
            print("    • Mid-range pattern — applies throughout iteration range")
        print("")

    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: cli_explain_learning.py <pattern_evolution.jsonl> [--pattern-type TYPE]")
        sys.exit(1)

    jsonl_file = sys.argv[1]
    pattern_type = ""

    # Parse optional --pattern-type argument
    for i, arg in enumerate(sys.argv[2:], 2):
        if arg == "--pattern-type" and i + 1 < len(sys.argv):
            pattern_type = sys.argv[i + 1]
            break

    explain_learning(jsonl_file, pattern_type)
