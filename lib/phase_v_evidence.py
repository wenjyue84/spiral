"""Phase V evidence aggregator — writes .spiral/evidence.json after validation.

Reads prd.json and emits a mapping of story_id -> {target: PASS|FAIL} so
downstream consumers (dashboards, CI gates) have a single evidence file.

Usage:
  python lib/phase_v_evidence.py --prd prd.json --out .spiral/evidence.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def aggregate_evidence(prd: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return {story_id: {"target": "PASS"|"FAIL"}} for every story."""
    evidence: dict[str, dict[str, str]] = {}
    for story in prd.get("userStories", []):
        sid = story.get("id", "")
        if not sid:
            continue
        evidence[sid] = {"target": "PASS" if story.get("passes") else "FAIL"}
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase V evidence aggregator")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    parser.add_argument("--out", default=".spiral/evidence.json", help="Output path")
    args = parser.parse_args(argv)

    try:
        with open(args.prd, encoding="utf-8") as f:
            prd = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: Cannot read {args.prd}: {exc}", file=sys.stderr)
        return 1

    evidence = aggregate_evidence(prd)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)
    print(f"  [V] Evidence written: {args.out} ({len(evidence)} stories)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
