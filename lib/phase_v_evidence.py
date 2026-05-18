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
import re
import sys
from typing import Any


class TestEvidenceAggregator:
    """Parse test stdout/stderr for AC markers and pytest failures."""

    _AC_PATTERN = re.compile(r"@spiral:ac:(pass|fail)\s+(.+)")
    _FAIL_PATTERN = re.compile(r"FAILED\s+(\S+?)::(\S+)")
    _LOC_PATTERN = re.compile(r"(\S+\.py):(\d+)")
    _FILE_ASSERT = re.compile(
        r"assert.*(?:exists|is_file|is_dir)\(\).*['\"](.+?)['\"]|"
        r"os\.path\.(?:exists|isfile)\(['\"](.+?)['\"]\)"
    )

    def parse_output(self, test_output: str, story_id: str) -> dict[str, Any]:
        """Extract AC statuses, failing tests, and file assertions."""
        criteria: list[dict[str, str]] = []
        failing_tests: list[dict[str, Any]] = []
        file_assertions: list[dict[str, Any]] = []

        for line in test_output.splitlines():
            ac_m = self._AC_PATTERN.search(line)
            if ac_m:
                criteria.append({"description": ac_m.group(2).strip(), "status": ac_m.group(1)})
                continue
            fail_m = self._FAIL_PATTERN.search(line)
            if fail_m:
                entry: dict[str, Any] = {"file": fail_m.group(1), "name": fail_m.group(2)}
                loc_m = self._LOC_PATTERN.search(line)
                if loc_m:
                    entry["line"] = int(loc_m.group(2))
                failing_tests.append(entry)
                continue
            fa_m = self._FILE_ASSERT.search(line)
            if fa_m:
                path = fa_m.group(1) or fa_m.group(2)
                file_assertions.append({"path": path, "exists": os.path.exists(path)})

        return {
            "story_id": story_id,
            "acceptance_criteria": criteria,
            "failing_tests": failing_tests,
            "file_assertions": file_assertions,
        }

    def aggregate(self, test_output: str, story_id: str, output_dir: str = ".spiral/verification_evidence") -> str:
        """Parse output and write per-story JSON evidence file."""
        evidence = self.parse_output(test_output, story_id)
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"{story_id}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(evidence, f, indent=2)
        return out_path


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
