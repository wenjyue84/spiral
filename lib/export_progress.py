#!/usr/bin/env python3
"""
export_progress.py — Bundle PRD, results, and metrics as a shareable snapshot.

Supports two output formats:
  json  — single JSON file with all data embedded + sha256 checksum in metadata
  zip   — ZIP archive containing individual files + README.md
"""

import csv
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_text(path: Path) -> str:
    """Read file as text, return empty string if missing."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _read_json(path: Path) -> Any:
    """Read JSON file, return None if missing or invalid."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _parse_results_tsv(path: Path) -> list[dict[str, Any]]:
    """Parse results.tsv into list of row dicts."""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                rows.append(dict(row))
    except (OSError, csv.Error):
        pass
    return rows


def _compute_metadata(
    prd: Any,
    results: list[dict[str, Any]],
    iteration: int,
    timestamp: str,
    checksum: str,
) -> dict[str, Any]:
    """Compute snapshot metadata from PRD and results."""
    pass_count = 0
    fail_count = 0
    if isinstance(prd, dict):
        for story in prd.get("userStories", []):
            if story.get("passes"):
                pass_count += 1
            else:
                fail_count += 1

    total_cost = 0.0
    for row in results:
        try:
            total_cost += float(row.get("cost_usd", 0) or 0)
        except (ValueError, TypeError):
            pass

    return {
        "iteration": iteration,
        "timestamp": timestamp,
        "passCount": pass_count,
        "failCount": fail_count,
        "totalCost": round(total_cost, 6),
        "checksum": checksum,
    }


def _sha256_of_content(content: str) -> str:
    """Compute sha256 hex digest of a string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def export_json(project_root: Path, output_path: Path, iteration: int = 0) -> Path:
    """
    Export spiral state as a single JSON file.

    Schema: { prd, results, learning, loopQuality, metadata }
    """
    prd_path = project_root / "prd.json"
    results_path = project_root / "results.tsv"
    learning_path = project_root / "learning.md"
    loop_quality_path = project_root / ".spiral" / "loop_quality.jsonl"

    prd = _read_json(prd_path)
    results = _parse_results_tsv(results_path)
    learning = _read_text(learning_path)

    loop_quality: list[Any] = []
    if loop_quality_path.exists():
        for line in loop_quality_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    loop_quality.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Checksum covers prd + results content
    prd_text = prd_path.read_text(encoding="utf-8") if prd_path.exists() else ""
    results_text = results_path.read_text(encoding="utf-8") if results_path.exists() else ""
    checksum = _sha256_of_content(prd_text + results_text)

    metadata = _compute_metadata(prd, results, iteration, timestamp, checksum)

    payload = {
        "prd": prd,
        "results": results,
        "learning": learning,
        "loopQuality": loop_quality,
        "metadata": metadata,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def export_zip(project_root: Path, output_path: Path, iteration: int = 0) -> Path:
    """
    Export spiral state as a ZIP archive.

    Contents: prd.json, results.tsv, learning.md, retry-counts.json, README.md
    """
    prd_path = project_root / "prd.json"
    results_path = project_root / "results.tsv"
    learning_path = project_root / "learning.md"
    retry_counts_path = project_root / "retry-counts.json"

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    prd_text = prd_path.read_text(encoding="utf-8") if prd_path.exists() else ""
    results_text = results_path.read_text(encoding="utf-8") if results_path.exists() else ""
    checksum = _sha256_of_content(prd_text + results_text)

    prd = _read_json(prd_path)
    results = _parse_results_tsv(results_path)
    metadata = _compute_metadata(prd, results, iteration, timestamp, checksum)

    readme = f"""# SPIRAL Progress Export

Exported: {timestamp}
Iteration: {iteration}
Pass count: {metadata["passCount"]}
Fail count: {metadata["failCount"]}
Total cost: ${metadata["totalCost"]:.4f}
SHA256 checksum (prd.json + results.tsv): {checksum}

## Contents

- prd.json           — Product backlog with all story statuses
- results.tsv        — Implementation attempt telemetry (model, tokens, cost, duration)
- learning.md        — Accumulated learning notes from SPIRAL iterations
- retry-counts.json  — Per-story retry counters
- README.md          — This file

## Usage

Import prd.json into a new SPIRAL project to continue from this state.
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src_path, arc_name in [
            (prd_path, "prd.json"),
            (results_path, "results.tsv"),
            (learning_path, "learning.md"),
            (retry_counts_path, "retry-counts.json"),
        ]:
            if src_path.exists():
                zf.write(src_path, arc_name)
        zf.writestr("README.md", readme)

    return output_path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: export-progress [--format json|zip] [--output PATH] [--iteration N]"""
    import sys

    args = argv if argv is not None else sys.argv[1:]

    fmt = "json"
    output_path: str | None = None
    iteration = 0
    project_root = Path(".")

    i = 0
    while i < len(args):
        if args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output_path = args[i + 1]
            i += 2
        elif args[i] == "--iteration" and i + 1 < len(args):
            try:
                iteration = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1])
            i += 2
        else:
            i += 1

    if fmt not in ("json", "zip"):
        print(f"[spiral] ERROR: Unknown format '{fmt}'. Use json or zip.", file=sys.stderr)
        return 1

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ext = "json" if fmt == "json" else "zip"
    default_name = f"spiral-export-{timestamp}.{ext}"
    dest = Path(output_path) if output_path else project_root / default_name

    if fmt == "json":
        out = export_json(project_root, dest, iteration)
    else:
        out = export_zip(project_root, dest, iteration)

    print(f"[spiral] Export complete: {out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
