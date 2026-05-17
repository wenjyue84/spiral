#!/usr/bin/env python3
"""Export and analyze SPIRAL execution traces for phase bottleneck detection."""

import argparse
import json
import os
import sys
from typing import Any

from lib.spiral_events_reader import read_results_tsv, read_worker_logs, unify_trace_data


def export_trace(
    from_iteration: int | None = None,
    to_iteration: int | None = None,
    filter_phase: str | None = None,
    output: str | None = None,
    project_root: str = ".",
) -> None:
    """Export execution trace as JSONL file."""
    results_path = os.path.join(project_root, "results.tsv")
    worker_log_dir = os.path.join(project_root, ".spiral")

    results_data = read_results_tsv(results_path)
    worker_data = read_worker_logs(worker_log_dir)

    trace_entries = unify_trace_data(
        [],
        results_data,
        worker_data,
        from_iteration=from_iteration,
        to_iteration=to_iteration,
        filter_phase=filter_phase,
    )

    if output is None:
        # Output to stdout
        for entry in trace_entries:
            print(json.dumps(entry))
    else:
        # Write to file
        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            for entry in trace_entries:
                f.write(json.dumps(entry) + "\n")
        print(f"[spiral] Trace exported to {output} ({len(trace_entries)} entries)")


def analyze_trace(trace_file: str) -> None:
    """Analyze trace file and output ASCII table with phase statistics."""
    if not os.path.exists(trace_file):
        print(f"[spiral] ERROR: Trace file not found: {trace_file}", file=sys.stderr)
        sys.exit(1)

    # Read trace entries
    entries: list[dict[str, Any]] = []
    try:
        with open(trace_file, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        print(f"[spiral] ERROR: Failed to read trace file: {e}", file=sys.stderr)
        sys.exit(1)

    if not entries:
        print("[spiral] No trace entries found")
        return

    # Group by phase
    phase_stats: dict[str, dict[str, Any]] = {}
    for entry in entries:
        phase = entry.get("phase") or "UNKNOWN"
        if phase not in phase_stats:
            phase_stats[phase] = {
                "count": 0,
                "durations": [],
                "total_tokens": 0,
                "total_cost": 0.0,
                "escalations": 0,
                "api_latencies": [],
            }

        stats = phase_stats[phase]
        stats["count"] += 1
        duration = entry.get("duration_ms", 0)
        if duration:
            stats["durations"].append(duration)
        stats["total_tokens"] += (entry.get("tokens_in", 0) or 0) + (entry.get("tokens_out", 0) or 0)
        stats["escalations"] += entry.get("escalation_count", 0)
        latency = entry.get("api_latency_ms", 0)
        if latency:
            stats["api_latencies"].append(latency)

    # Compute derived stats
    computed: dict[str, dict[str, Any]] = {}
    for phase, stats in phase_stats.items():
        durations = stats["durations"]
        latencies = stats["api_latencies"]
        durations.sort()
        latencies.sort()

        computed[phase] = {
            "count": stats["count"],
            "median_duration_ms": durations[len(durations) // 2] if durations else 0,
            "p95_latency_ms": latencies[int(len(latencies) * 0.95)] if latencies else 0,
            "total_tokens": stats["total_tokens"],
            "total_cost_usd": stats["total_cost"],
            "escalation_rate": stats["escalations"] / stats["count"] if stats["count"] > 0 else 0.0,
        }

    # Output ASCII table
    print("\n[spiral] Phase Statistics from Trace Analysis")
    print("=" * 120)
    header = (
        f"{'Phase':<10} {'Count':>8} {'Median Dur':>12} {'P95 Latency':>12} "
        f"{'Total Tokens':>14} {'Cost':>10} {'Esc.Rate':>10}"
    )
    print(header)
    print("-" * 120)

    slowest_phase = ""
    slowest_dur = 0
    costliest_phase = ""
    costliest = 0.0

    for phase in sorted(computed.keys()):
        stats = computed[phase]
        print(
            f"{phase:<10} {stats['count']:>8} {stats['median_duration_ms']:>12.0f}ms {stats['p95_latency_ms']:>12.0f}ms "
            f"{stats['total_tokens']:>14} ${stats['total_cost_usd']:>9.4f} {stats['escalation_rate']:>9.2%}"
        )
        if stats["median_duration_ms"] > slowest_dur:
            slowest_dur = stats["median_duration_ms"]
            slowest_phase = phase
        if stats["total_cost_usd"] > costliest:
            costliest = stats["total_cost_usd"]
            costliest_phase = phase

    print("=" * 120)
    if slowest_phase:
        print(f"\n[spiral] Slowest phase: {slowest_phase} (median {slowest_dur:.0f}ms)")
    if costliest_phase:
        print(f"[spiral] Highest-cost phase: {costliest_phase} (${costliest:.4f})")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="SPIRAL trace export and analysis")
    subparsers = parser.add_subparsers(dest="subcommand")

    # export-trace subcommand
    export = subparsers.add_parser("export-trace", help="Export execution trace as JSONL")
    export.add_argument("--from-iteration", type=int, help="Start iteration (inclusive)")
    export.add_argument("--to-iteration", type=int, help="End iteration (inclusive)")
    export.add_argument("--filter-phase", help="Filter by phase [A-L]")
    export.add_argument("--output", help="Output file (stdout if omitted)")
    export.add_argument("--project-root", default=".", help="Project root directory")

    # analyze-trace subcommand
    analyze = subparsers.add_parser("analyze-trace", help="Analyze trace file and output statistics")
    analyze.add_argument("trace_file", help="Path to trace JSONL file")

    args = parser.parse_args()

    if args.subcommand == "export-trace":
        export_trace(
            from_iteration=args.from_iteration,
            to_iteration=args.to_iteration,
            filter_phase=args.filter_phase,
            output=args.output,
            project_root=args.project_root,
        )
    elif args.subcommand == "analyze-trace":
        analyze_trace(args.trace_file)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
