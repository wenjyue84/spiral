#!/usr/bin/env python3
"""
Calibration tracker: Records actual vs estimated complexity metrics for stories.

Usage:
  python3 lib/calibration_tracker.py record \
    --story-id US-123 \
    --estimated-complexity small \
    --actual-duration-s 120 \
    --phase-retries 2 \
    --passed true \
    --output calibration.jsonl

  python3 lib/calibration_tracker.py report \
    --calibration-file calibration.jsonl \
    --prd prd.json
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Dict, List
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import append_jsonl

def record_calibration(
    story_id: str,
    estimated_complexity: str,
    actual_duration_s: int,
    phase_retries: int,
    passed: bool,
    output_file: str,
) -> None:
    """Record a calibration entry for a completed story."""
    record = {
        "story_id": story_id,
        "estimated_complexity": estimated_complexity,
        "actual_duration_s": actual_duration_s,
        "phase_retries": phase_retries,
        "passed": passed,
    }
    
    # Append to JSONL file
    append_jsonl(str(output_file), record)

def load_calibration_file(calibration_file: str) -> List[Dict]:
    """Load all calibration records from JSONL file."""
    records = []
    path = Path(calibration_file)
    if not path.exists():
        return records
    
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    
    return records

def compute_calibration_report(calibration_file: str, prd_file: Optional[str] = None) -> Dict:
    """Compute calibration statistics: median durations, underestimated stories."""
    records = load_calibration_file(calibration_file)
    
    if not records:
        return {
            "total_completed": 0,
            "by_tier": {},
            "underestimated": [],
            "pass_rate": 0.0,
        }
    
    # Group by complexity tier
    by_tier = defaultdict(list)
    for record in records:
        tier = record.get("estimated_complexity", "unknown")
        by_tier[tier].append(record["actual_duration_s"])
    
    # Compute median per tier
    medians = {}
    for tier, durations in by_tier.items():
        sorted_durations = sorted(durations)
        mid = len(sorted_durations) // 2
        if len(sorted_durations) % 2 == 0:
            medians[tier] = (sorted_durations[mid-1] + sorted_durations[mid]) / 2
        else:
            medians[tier] = sorted_durations[mid]
    
    # Flag underestimated (actual > 2x median)
    underestimated = []
    for record in records:
        tier = record.get("estimated_complexity")
        median = medians.get(tier, 0)
        if median > 0 and record["actual_duration_s"] > (median * 2):
            underestimated.append({
                "story_id": record["story_id"],
                "estimated": tier,
                "actual_duration_s": record["actual_duration_s"],
                "median_for_tier_s": median,
                "ratio": round(record["actual_duration_s"] / median, 2),
            })
    
    # Compute pass rate
    passed = sum(1 for r in records if r.get("passed", False))
    pass_rate = (passed / len(records)) * 100 if records else 0
    
    # Get rolling window (last 20 completed stories)
    recent_records = records[-20:]
    
    return {
        "total_completed": len(records),
        "by_tier": {
            tier: {
                "count": len(durations),
                "median_s": round(medians.get(tier, 0), 2),
                "min_s": min(durations),
                "max_s": max(durations),
            }
            for tier, durations in by_tier.items()
        },
        "recent_window": {
            "stories": len(recent_records),
            "by_tier": {
                tier: {
                    "count": len(durations),
                    "median_s": round((sorted(durations)[len(durations)//2] if durations else 0), 2),
                }
                for tier, durations in defaultdict(list, {
                    r["estimated_complexity"]: [r["actual_duration_s"]]
                    for r in recent_records
                }).items()
            },
        },
        "underestimated": underestimated,
        "pass_rate": round(pass_rate, 1),
    }

def main():
    parser = argparse.ArgumentParser(description="Track actual vs estimated story complexity")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # record subcommand
    record_parser = subparsers.add_parser("record", help="Record a story's calibration data")
    record_parser.add_argument("--story-id", required=True, help="Story ID")
    record_parser.add_argument("--estimated-complexity", required=True, choices=["small", "medium", "large"])
    record_parser.add_argument("--actual-duration-s", type=int, required=True, help="Actual duration in seconds")
    record_parser.add_argument("--phase-retries", type=int, default=0, help="Number of retries during phases")
    record_parser.add_argument("--passed", type=lambda x: x.lower() == "true", required=True, help="Whether story passed")
    record_parser.add_argument("--output", default="calibration.jsonl", help="Output file path")
    
    # report subcommand
    report_parser = subparsers.add_parser("report", help="Generate calibration report")
    report_parser.add_argument("--calibration-file", default="calibration.jsonl", help="Input calibration file")
    report_parser.add_argument("--prd", help="Optional: PRD file for enrichment")
    
    args = parser.parse_args()
    
    if args.command == "record":
        record_calibration(
            story_id=args.story_id,
            estimated_complexity=args.estimated_complexity,
            actual_duration_s=args.actual_duration_s,
            phase_retries=args.phase_retries,
            passed=args.passed,
            output_file=args.output,
        )
        print(f"✓ Recorded calibration: {args.story_id} ({args.estimated_complexity}): {args.actual_duration_s}s", file=sys.stderr)
    
    elif args.command == "report":
        report = compute_calibration_report(args.calibration_file, args.prd)
        print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
