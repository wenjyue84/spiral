#!/usr/bin/env python3
"""spiral_report.py — Post-hoc analysis of SPIRAL experiment results.

Reads results.tsv (produced by ralph.sh) and prints a summary report
with session stats, velocity trends, duration analysis, model breakdown,
and retry analysis.

stdlib-only — no pandas, numpy, or other external dependencies.

Usage:
    python lib/spiral_report.py [--results PATH] [--last-n N] [--json]
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from io import StringIO


def load_results(path, last_n=0):
    """Load results.tsv and return list of row dicts."""
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            # Coerce numeric fields
            for key in ("duration_sec", "retry_num", "spiral_iter", "ralph_iter"):
                if key in row and row[key]:
                    try:
                        row[key] = int(row[key])
                    except (ValueError, TypeError):
                        row[key] = 0
            rows.append(row)
    if last_n and last_n > 0:
        rows = rows[-last_n:]
    return rows


def section_summary(rows):
    """1. Session Summary — totals and status breakdown."""
    if not rows:
        return {"total": 0}
    timestamps = [r["timestamp"] for r in rows if r.get("timestamp")]
    date_range = f"{timestamps[0]} → {timestamps[-1]}" if len(timestamps) >= 2 else (timestamps[0] if timestamps else "?")

    status_counts: defaultdict[str, int] = defaultdict(int)
    for r in rows:
        status_counts[r.get("status", "unknown")] += 1

    total = len(rows)
    lines = [
        "  1. SESSION SUMMARY",
        f"     Total attempts:  {total}",
        f"     Date range:      {date_range}",
        "     Status breakdown:",
    ]
    for status in ("keep", "discard", "skip", "crash"):
        count = status_counts.get(status, 0)
        pct = count * 100.0 / total if total else 0
        lines.append(f"       {status:8s}  {count:4d}  ({pct:5.1f}%)")

    # Also show any unexpected statuses
    for status, count in sorted(status_counts.items()):
        if status not in ("keep", "discard", "skip", "crash"):
            pct = count * 100.0 / total if total else 0
            lines.append(f"       {status:8s}  {count:4d}  ({pct:5.1f}%)")

    return {
        "text": "\n".join(lines),
        "total": total,
        "date_range": date_range,
        "status_counts": dict(status_counts),
    }


def section_velocity(rows):
    """2. Velocity Trend — stories kept per hour, text bar chart."""
    # Group by spiral_iter
    iters: defaultdict[int, dict[str, int]] = defaultdict(lambda: {"keep": 0, "total": 0, "duration": 0})
    for r in rows:
        si = r.get("spiral_iter", 0)
        iters[si]["total"] += 1
        if r.get("status") == "keep":
            iters[si]["keep"] += 1
        iters[si]["duration"] += r.get("duration_sec", 0)

    if not iters:
        return {"text": "  2. VELOCITY TREND\n     (no data)"}

    lines = ["  2. VELOCITY TREND (stories kept per spiral iteration)"]
    max_keep = max(v["keep"] for v in iters.values()) or 1
    bar_width = 30

    for si in sorted(iters.keys()):
        data = iters[si]
        kept = data["keep"]
        bar_len = int(kept * bar_width / max_keep) if max_keep else 0
        bar = "█" * bar_len
        dur_h = data["duration"] / 3600.0 if data["duration"] else 0
        vel = kept / dur_h if dur_h > 0 else 0
        lines.append(f"     iter {si:3d}  {bar:<{bar_width}s}  {kept:3d} kept  ({vel:.1f}/hr)")

    return {"text": "\n".join(lines), "per_iter": dict(iters)}


def section_duration(rows):
    """3. Duration Stats — average duration by status."""
    durations = defaultdict(list)
    for r in rows:
        status = r.get("status", "unknown")
        dur = r.get("duration_sec", 0)
        durations[status].append(dur)

    if not durations:
        return {"text": "  3. DURATION STATS\n     (no data)"}

    lines = ["  3. DURATION STATS (average seconds by status)"]
    for status in ("keep", "discard", "skip", "crash"):
        if status in durations:
            vals = durations[status]
            avg = sum(vals) / len(vals)
            mn = min(vals)
            mx = max(vals)
            lines.append(f"     {status:8s}  avg {avg:7.0f}s  min {mn:5.0f}s  max {mx:5.0f}s  (n={len(vals)})")

    return {"text": "\n".join(lines), "by_status": {k: {"avg": sum(v)/len(v), "min": min(v), "max": max(v), "n": len(v)} for k, v in durations.items()}}


def section_models(rows):
    """4. Model Breakdown — attempts per model, success rate."""
    model_stats: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "keep": 0})
    for r in rows:
        model = r.get("model", "unknown")
        model_stats[model]["total"] += 1
        if r.get("status") == "keep":
            model_stats[model]["keep"] += 1

    if not model_stats:
        return {"text": "  4. MODEL BREAKDOWN\n     (no data)"}

    lines = ["  4. MODEL BREAKDOWN"]
    for model in sorted(model_stats.keys()):
        data = model_stats[model]
        rate = data["keep"] * 100.0 / data["total"] if data["total"] else 0
        lines.append(f"     {model:12s}  {data['total']:4d} attempts  {data['keep']:4d} kept  ({rate:5.1f}% success)")

    return {"text": "\n".join(lines), "by_model": {k: dict(v) for k, v in model_stats.items()}}


def section_retries(rows):
    """5. Retry Analysis — success rate by attempt number."""
    retry_stats: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "keep": 0})
    for r in rows:
        retry = r.get("retry_num", 0)
        label = f"attempt {retry + 1}" if isinstance(retry, int) else f"attempt {retry}"
        retry_stats[label]["total"] += 1
        if r.get("status") == "keep":
            retry_stats[label]["keep"] += 1

    if not retry_stats:
        return {"text": "  5. RETRY ANALYSIS\n     (no data)"}

    lines = ["  5. RETRY ANALYSIS (success rate by attempt number)"]
    for label in sorted(retry_stats.keys()):
        data = retry_stats[label]
        rate = data["keep"] * 100.0 / data["total"] if data["total"] else 0
        lines.append(f"     {label:12s}  {data['total']:4d} total  {data['keep']:4d} kept  ({rate:5.1f}% success)")

    return {"text": "\n".join(lines), "by_attempt": {k: dict(v) for k, v in retry_stats.items()}}


def section_cache_savings(rows):
    """6. Prompt Cache Savings — cache hit rate and estimated cost reduction."""
    # Anthropic sonnet pricing: $3/M input. Cache reads cost 10% → 90% savings per cached token.
    PRICING = {
        "haiku": 0.80,
        "sonnet": 3.00,
        "opus": 15.00,
    }
    DEFAULT_INPUT_PRICE = 3.00

    total_cache_hits = 0
    total_attempts = 0
    total_cache_read_tokens = 0
    total_savings_usd = 0.0
    per_model: defaultdict[str, dict] = defaultdict(lambda: {"hits": 0, "total": 0, "cache_read": 0, "savings": 0.0})

    for r in rows:
        model_raw = r.get("model", "")
        cache_hit = str(r.get("cache_hit", "false")).lower() == "true"
        try:
            cache_read_tokens = int(r.get("cache_read_tokens", 0) or 0)
        except (ValueError, TypeError):
            cache_read_tokens = 0

        model_key = "sonnet"
        for k in PRICING:
            if k in model_raw.lower():
                model_key = k
                break
        input_price = PRICING.get(model_key, DEFAULT_INPUT_PRICE)

        # Savings = cache_read_tokens * input_price * 0.90 / 1M (paid 10%, saved 90%)
        savings = (cache_read_tokens / 1_000_000) * input_price * 0.90

        total_attempts += 1
        if cache_hit:
            total_cache_hits += 1
        total_cache_read_tokens += cache_read_tokens
        total_savings_usd += savings

        per_model[model_key]["total"] += 1
        if cache_hit:
            per_model[model_key]["hits"] += 1
        per_model[model_key]["cache_read"] += cache_read_tokens
        per_model[model_key]["savings"] += savings

    if total_attempts == 0:
        return {"text": "  6. PROMPT CACHE SAVINGS\n     (no data)"}

    hit_rate = total_cache_hits * 100.0 / total_attempts if total_attempts else 0
    lines = [
        "  6. PROMPT CACHE SAVINGS",
        f"     Cache hit rate:   {total_cache_hits}/{total_attempts} stories ({hit_rate:.1f}%)",
        f"     Cache read tokens: {total_cache_read_tokens:,}",
        f"     Estimated savings: ${total_savings_usd:.4f} USD (90% discount on cached reads)",
    ]
    if len(per_model) > 1:
        lines.append("     Per-model breakdown:")
        for model in sorted(per_model.keys()):
            d = per_model[model]
            r = d["hits"] * 100.0 / d["total"] if d["total"] else 0
            lines.append(f"       {model:8s}  {d['hits']:3d}/{d['total']:3d} hits ({r:.0f}%)  "
                         f"{d['cache_read']:,} cache tokens  ${d['savings']:.4f} saved")

    return {
        "text": "\n".join(lines),
        "cache_hit_rate": hit_rate,
        "total_cache_read_tokens": total_cache_read_tokens,
        "estimated_savings_usd": round(total_savings_usd, 6),
    }


def main():
    parser = argparse.ArgumentParser(description="SPIRAL experiment report")
    parser.add_argument("--results", default="results.tsv", help="Path to results.tsv")
    parser.add_argument("--last-n", type=int, default=0, help="Only analyze last N rows")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    try:
        rows = load_results(args.results, args.last_n)
    except FileNotFoundError:
        print(f"  [report] No results file found at {args.results}", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print("  [report] results.tsv is empty — nothing to report")
        sys.exit(0)

    sections = [
        section_summary(rows),
        section_velocity(rows),
        section_duration(rows),
        section_models(rows),
        section_retries(rows),
        section_cache_savings(rows),
    ]

    if args.json:
        json_out = {}
        for s in sections:
            s_copy = {k: v for k, v in s.items() if k != "text"}
            json_out.update(s_copy)
        print(json.dumps(json_out, indent=2))
    else:
        print("")
        print("  ┌─ SPIRAL Experiment Report ──────────────────────┐")
        for s in sections:
            if "text" in s:
                print(s["text"])
                print("")
        print("  └─────────────────────────────────────────────────┘")


if __name__ == "__main__":
    main()
