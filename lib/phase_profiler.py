#!/usr/bin/env python3
"""
lib/phase_profiler.py -- Phase execution time analysis and reporting.

Reads .spiral/_phase_timings.jsonl (JSON Lines format) and produces:
1. Formatted ASCII table of phase durations
2. Summary statistics (total runtime, slowest phase, recommendations)
3. Handles incomplete/missing data gracefully
"""

import json
import sys
from pathlib import Path
from typing import Optional


def parse_timings(jsonl_path: str) -> list[dict]:
    """
    Parse .spiral/_phase_timings.jsonl and return list of timing records.

    Each record expected: {phase: 'R', start_ms: <int>, end_ms: <int>}

    Returns:
        List of dicts with parsed timing data, computed duration_ms
    Raises:
        FileNotFoundError if jsonl_path doesn't exist
    """
    path = Path(jsonl_path)
    if not path.exists():
        raise FileNotFoundError(f"Phase timings file not found: {jsonl_path}")

    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                # Validate required fields
                if "phase" in record and "start_ms" in record and "end_ms" in record:
                    record["duration_ms"] = max(0, record["end_ms"] - record["start_ms"])
                    records.append(record)
            except json.JSONDecodeError:
                # Skip malformed lines
                continue

    return records


def format_profile_table(records: list[dict]) -> str:
    """
    Format phase timing records into a human-readable ASCII table.

    Outputs:
    - Table sorted by duration (descending)
    - Columns: Phase | Duration (s) | Pct | Status
    - Summary: total runtime, slowest phase, >30% phases
    - Handles missing data (marks status as 'incomplete')
    """
    if not records:
        return "No phase timings recorded.\n"

    # Sort by duration descending
    sorted_records = sorted(records, key=lambda r: r.get("duration_ms", 0), reverse=True)

    # Compute total duration
    total_ms = sum(r.get("duration_ms", 0) for r in sorted_records)
    total_s = total_ms / 1000.0 if total_ms > 0 else 0

    # Build table
    lines = []
    lines.append("")
    lines.append("  Phase Execution Profile")
    lines.append("  " + "─" * 68)
    lines.append(f"  {'Phase':<8} {'Duration (s)':>15} {'Pct':>8} {'Status':<30}")
    lines.append("  " + "─" * 68)

    high_impact_phases = []
    for record in sorted_records:
        phase = record.get("phase", "?")
        duration_ms = record.get("duration_ms", 0)
        duration_s = duration_ms / 1000.0

        # Compute percentage
        if total_ms > 0:
            pct = (duration_ms / total_ms) * 100
        else:
            pct = 0

        # Determine status
        if "start_ms" in record and "end_ms" in record:
            status = "✓ complete"
        else:
            status = "⚠ incomplete"

        # Track high-impact phases (>30%)
        if pct > 30:
            high_impact_phases.append((phase, pct))

        # Format and append line
        line = f"  {phase:<8} {duration_s:>15.2f} {pct:>7.1f}% {status:<30}"
        lines.append(line)

    lines.append("  " + "─" * 68)
    lines.append(f"  {'TOTAL':<8} {total_s:>15.2f} {100.0:>7.1f}%")
    lines.append("")

    # Add summary
    if sorted_records:
        slowest = sorted_records[0]
        slowest_phase = slowest.get("phase", "?")
        slowest_s = slowest.get("duration_ms", 0) / 1000.0
        lines.append(f"  Slowest phase: {slowest_phase} ({slowest_s:.2f}s)")

    if high_impact_phases:
        lines.append("")
        lines.append("  ⚠ High-impact phases (>30% of total):")
        for phase, pct in high_impact_phases:
            lines.append(f"    - Phase {phase}: {pct:.1f}%")
        lines.append("    Consider optimizing these phases for faster iteration.")

    lines.append("")
    return "\n".join(lines)


def main():
    """CLI entry point: read jsonl_path and print formatted table."""
    if len(sys.argv) < 2:
        print("Usage: phase_profiler.py <path_to_phase_timings.jsonl>")
        sys.exit(1)

    jsonl_path = sys.argv[1]

    try:
        records = parse_timings(jsonl_path)
        output = format_profile_table(records)
        print(output)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
