"""lib/trajectory_exporter.py — Export story execution traces as JSONL for RL fine-tuning.

Parses results.tsv and writes gzip-compressed JSONL to
.spiral/trajectory/export-YYYY-MM-DD-HHMMSS.jsonl.gz
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = [
    "story_id",
    "prompt",
    "decomposition_strategy",
    "response",
    "tokens_used",
    "success",
    "error_type",
    "model_tier",
    "retry_count",
]

TRAJECTORY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": REQUIRED_FIELDS,
    "properties": {
        "story_id": {"type": "string"},
        "prompt": {"type": "string"},
        "decomposition_strategy": {"type": "string"},
        "response": {"type": "string"},
        "tokens_used": {"type": "integer"},
        "success": {"type": "boolean"},
        "error_type": {"type": ["string", "null"]},
        "model_tier": {"type": "string"},
        "retry_count": {"type": "integer"},
    },
}


def validate_record(record: dict[str, Any]) -> list[str]:
    """Return list of field violations; empty means valid."""
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"missing field: {field}")
    return errors


class TrajectoryExporter:
    """Export story execution traces from results.tsv as JSONL training data."""

    def __init__(
        self,
        results_tsv: str | Path,
        project_root: str | Path = ".",
    ) -> None:
        self.results_tsv = Path(results_tsv)
        self.project_root = Path(project_root)

    def _parse_results_tsv(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        if not self.results_tsv.exists():
            return rows
        with open(self.results_tsv, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                rows.append(dict(row))
        return rows

    def _row_to_record(self, row: dict[str, str]) -> dict[str, Any]:
        status = row.get("status", "").lower()
        success = status == "keep"
        cache_read = int(row.get("cache_read_tokens", 0) or 0)
        cache_create = int(row.get("cache_creation_tokens", 0) or 0)
        tokens_used = cache_read + cache_create
        retry_count = int(row.get("retry_num", 0) or 0)
        model_tier = row.get("model", "unknown")
        error_type: str | None = None if success else (status if status else "unknown")
        story_id = row.get("story_id", "")
        story_title = row.get("story_title", "")
        decomposition = "retry" if retry_count > 0 else "sequential"
        outcome = "succeeded" if success else f"failed ({error_type})"
        return {
            "story_id": story_id,
            "prompt": f"Implement story {story_id} - {story_title}",
            "decomposition_strategy": decomposition,
            "response": f"Story {story_id} implementation {outcome} using {model_tier}",
            "tokens_used": tokens_used,
            "success": success,
            "error_type": error_type,
            "model_tier": model_tier,
            "retry_count": retry_count,
        }

    def to_jsonl(self, filter_dict: dict[str, str] | None = None) -> list[dict[str, Any]]:
        """Return list of trajectory records, optionally filtered."""
        rows = self._parse_results_tsv()
        records: list[dict[str, Any]] = []
        for row in rows:
            if not row.get("story_id"):
                continue
            if filter_dict:
                if any(row.get(k, "") != v for k, v in filter_dict.items()):
                    continue
            records.append(self._row_to_record(row))
        return records

    def export(
        self,
        output_path: str | Path | None = None,
        filter_dict: dict[str, str] | None = None,
    ) -> Path:
        """Export records to a gzipped JSONL file; returns the output path."""
        records = self.to_jsonl(filter_dict)
        if output_path is None:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
            out_dir = self.project_root / ".spiral" / "trajectory"
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / f"export-{ts}.jsonl.gz"
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(out, "wt", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")
        return out


def _parse_filter(filter_str: str) -> dict[str, str]:
    """Parse 'key=value' filter string into dict."""
    if "=" not in filter_str:
        raise argparse.ArgumentTypeError(f"Filter must be key=value, got: {filter_str}")
    k, _, v = filter_str.partition("=")
    return {k.strip(): v.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export SPIRAL story traces as JSONL training data")
    parser.add_argument("--results", default="results.tsv", help="Path to results.tsv")
    parser.add_argument("--output", default=None, help="Output .jsonl.gz path")
    parser.add_argument(
        "--filter",
        default=None,
        help="Filter records as key=value (e.g. model=sonnet)",
    )
    parser.add_argument("--project-root", default=".", help="Project root for default output dir")
    args = parser.parse_args(argv)

    filter_dict: dict[str, str] | None = None
    if args.filter:
        filter_dict = _parse_filter(args.filter)

    exporter = TrajectoryExporter(results_tsv=args.results, project_root=args.project_root)
    out_path = exporter.export(output_path=args.output, filter_dict=filter_dict)
    records = exporter.to_jsonl(filter_dict)
    print(f"[trajectory] Exported {len(records)} records to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
