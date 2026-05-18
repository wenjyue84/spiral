#!/usr/bin/env python3
"""
results_exporter.py — Export results.tsv as CSV or JSON for analytics.

Supports filtering by timestamp (--since) and status (--status).
Outputs story metrics: story_id, model, tokens, cost, duration, status.
"""

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Model pricing per million input tokens
PRICING = {
    "haiku": 0.80,
    "sonnet": 3.00,
    "opus": 15.00,
}

TOKENS_PER_SEC_OUTPUT = 20
INPUT_OUTPUT_RATIO = 3.0


def _total_tokens_from_duration(duration_sec: float) -> tuple[float, float]:
    """Calculate input and output tokens from duration.

    Returns: (tokens_input, tokens_output)
    """
    output = duration_sec * TOKENS_PER_SEC_OUTPUT
    input_ = output * INPUT_OUTPUT_RATIO
    return (input_, output)


def _cost_usd(model: str, tokens_input: float) -> float:
    """Calculate cost in USD for tokens."""
    model_norm = model.lower() if model else "sonnet"
    for key in PRICING:
        if key in model_norm:
            rate = PRICING[key]
            return (tokens_input / 1_000_000.0) * rate
    # Default to sonnet
    return (tokens_input / 1_000_000.0) * PRICING.get("sonnet", 3.00)


def _parse_iso8601(timestamp_str: str) -> datetime | None:
    """Parse ISO 8601 timestamp."""
    try:
        # Handle both formats: with Z and without
        ts = timestamp_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _get_phase_from_spiral_iter(spiral_iter: int | str, ralph_iter: int | str) -> str:
    """Extract phase letter from iteration numbers."""
    # In SPIRAL, phases cycle (A->R->T->S->E->M->X->G->I->V->C)
    # This is a simplification; could enhance with .spiral/_checkpoint.json
    phases = ["A", "R", "T", "S", "E", "M", "X", "G", "I", "V", "C"]
    try:
        s_iter = int(spiral_iter) if spiral_iter else 0
        r_iter = int(ralph_iter) if ralph_iter else 0
        # Use ralph_iter as phase index (simplified; actual implementation would read checkpoint)
        idx = r_iter % len(phases)
        return phases[idx]
    except (ValueError, TypeError):
        return "A"  # Default to phase A


def parse_results_tsv(results_path: Path) -> list[dict[str, Any]]:
    """Parse results.tsv and compute derived fields."""
    rows = []

    if not results_path.exists():
        return rows

    try:
        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if not reader.fieldnames:
                return rows

            for row in reader:
                # Compute derived fields
                duration_sec = float(row.get("duration_sec", 0) or 0)
                tokens_input, tokens_output = _total_tokens_from_duration(duration_sec)

                model = row.get("model", "sonnet").strip()
                cost_usd = _cost_usd(model, tokens_input)

                spiral_iter = row.get("spiral_iter", "0")
                ralph_iter = row.get("ralph_iter", "0")
                phase = _get_phase_from_spiral_iter(spiral_iter, ralph_iter)

                enhanced_row = {
                    "timestamp": row.get("timestamp", ""),
                    "iteration": spiral_iter,
                    "story_id": row.get("story_id", ""),
                    "model": model,
                    "tokens_input": round(tokens_input, 2),
                    "tokens_output": round(tokens_output, 2),
                    "cost_usd": round(cost_usd, 6),
                    "duration_sec": round(duration_sec, 2),
                    "status": row.get("status", "unknown").lower(),
                    "phase": phase,
                    "date_completed": row.get("timestamp", ""),
                }
                rows.append(enhanced_row)
    except Exception:
        pass

    return rows


def filter_rows(
    rows: list[dict[str, Any]],
    since: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Filter rows by timestamp and/or status."""
    filtered = []

    since_dt = None
    if since:
        since_dt = _parse_iso8601(since)

    for row in rows:
        # Check timestamp filter
        if since_dt:
            ts = _parse_iso8601(row.get("timestamp", ""))
            if ts and ts <= since_dt:
                continue

        # Check status filter
        if status:
            if row.get("status", "").lower() != status.lower():
                continue

        filtered.append(row)

    return filtered


def export_csv(
    rows: list[dict[str, Any]],
    output: Any = None,
) -> str | None:
    """
    Export rows as CSV (no headers for piping).

    Returns: CSV string (if output is None) or None (if written to file)
    """
    # CSV column order
    fieldnames = [
        "iteration",
        "story_id",
        "model",
        "tokens_input",
        "tokens_output",
        "cost_usd",
        "duration_sec",
        "status",
        "phase",
        "date_completed",
    ]

    if output is None:
        # Return as string
        import io

        f = io.StringIO()
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL, extrasaction="ignore")
        for row in rows:
            writer.writerow(row)
        return f.getvalue()
    else:
        # Write to file-like object or path
        if isinstance(output, (str, Path)):
            f = open(output, "w", encoding="utf-8", newline="")
        else:
            f = output

        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL, extrasaction="ignore")
        for row in rows:
            writer.writerow(row)

        if isinstance(output, (str, Path)):
            f.close()

        return None


def export_json(
    rows: list[dict[str, Any]],
    output: Any = None,
) -> str | None:
    """
    Export rows as newline-delimited JSON with metadata.

    First line: metadata object
    Following lines: one JSON object per row

    Returns: JSON string (if output is None) or None (if written to file)
    """
    if output is None:
        import io

        f = io.StringIO()
    elif isinstance(output, (str, Path)):
        f = open(output, "w", encoding="utf-8")
    else:
        f = output

    # Compute metadata
    iteration_count = len(set(row.get("iteration") for row in rows if row.get("iteration")))
    total_cost = sum(float(row.get("cost_usd", 0) or 0) for row in rows)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    metadata = {
        "type": "metadata",
        "timestamp": timestamp,
        "iteration_count": iteration_count,
        "total_cost_usd": round(total_cost, 6),
        "story_count": len(rows),
    }

    # Write metadata as first line
    f.write(json.dumps(metadata, ensure_ascii=False) + "\n")

    # Write each row
    for row in rows:
        # Compute phase_times (simplified: just duration for this phase)
        phase_times = {row.get("phase", "A"): row.get("duration_sec", 0)}
        row_with_phase_times = {**row, "phase_times": phase_times}
        f.write(json.dumps(row_with_phase_times, ensure_ascii=False) + "\n")

    if output is None:
        result = f.getvalue()
        f.close()
        return result
    elif isinstance(output, (str, Path)):
        f.close()

    return None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: export-results [--format csv|json] [--since ISO8601] [--status pass|fail|timeout] [--output PATH]"""
    args = argv if argv is not None else sys.argv[1:]

    fmt = "csv"
    since = None
    status = None
    output = None
    project_root = Path(".")

    i = 0
    while i < len(args):
        if args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
            i += 2
        elif args[i] == "--since" and i + 1 < len(args):
            since = args[i + 1]
            i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            status = args[i + 1]
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output = args[i + 1]
            i += 2
        elif args[i] == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1])
            i += 2
        else:
            i += 1

    # Validate format
    if fmt not in ("csv", "json"):
        print(f"[spiral] ERROR: Unknown format '{fmt}'. Use csv or json.", file=sys.stderr)
        return 1

    # Parse results
    results_path = project_root / "results.tsv"
    rows = parse_results_tsv(results_path)

    # Apply filters
    rows = filter_rows(rows, since=since, status=status)

    if not rows:
        print("[spiral] No results to export.", file=sys.stderr)
        return 0

    # Export
    try:
        if fmt == "csv":
            result = export_csv(rows, output=output)
            if result is not None:
                sys.stdout.write(result)
        else:  # json
            result = export_json(rows, output=output)
            if result is not None:
                sys.stdout.write(result)

        if output:
            print(f"[spiral] Exported {len(rows)} stories to {output}", file=sys.stderr)

        return 0
    except Exception as e:
        print(f"[spiral] ERROR: Failed to export: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
