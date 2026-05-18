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
from datetime import datetime, timezone
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


def write_evidence_json(
    story_id: str,
    test_file: str,
    test_marker: str,
    passed: bool,
    duration_ms: int,
    evidence_dir: str = ".spiral/evidence",
) -> str:
    """Write per-story evidence JSON to <evidence_dir>/<story_id>.json.

    Schema: {testFile, testMarker, passed, duration_ms, timestamp}
    """
    os.makedirs(evidence_dir, exist_ok=True)
    out_path = os.path.join(evidence_dir, f"{story_id}.json")
    payload: dict[str, Any] = {
        "testFile": test_file,
        "testMarker": test_marker,
        "passed": passed,
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return out_path


def aggregate_phase_v_summary(
    evidence_dir: str = ".spiral/evidence",
    out_path: str = ".spiral/phase_v_summary.json",
) -> dict[str, Any]:
    """Read all per-story evidence files and compute aggregate stats.

    Returns summary with total_stories, pass_count, fail_count,
    pass_rate_percent, slowest_tests: [{story_id, duration_ms}].
    """
    records: list[dict[str, Any]] = []
    if os.path.isdir(evidence_dir):
        for fname in sorted(os.listdir(evidence_dir)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(evidence_dir, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    rec = json.load(f)
                rec.setdefault("story_id", fname[:-5])
                records.append(rec)
            except (OSError, json.JSONDecodeError):
                pass

    total = len(records)
    pass_count = sum(1 for r in records if r.get("passed", False))
    fail_count = total - pass_count
    pass_rate = round(pass_count / total * 100, 1) if total > 0 else 0.0
    slowest = sorted(records, key=lambda r: int(r.get("duration_ms", 0)), reverse=True)[:5]
    slowest_list = [{"story_id": r.get("story_id", ""), "duration_ms": int(r.get("duration_ms", 0))} for r in slowest]

    summary: dict[str, Any] = {
        "total_stories": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate_percent": pass_rate,
        "slowest_tests": slowest_list,
    }

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary


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
    parser.add_argument("--out", default=".spiral/evidence.json", help="Output path for aggregate evidence")
    parser.add_argument("--per-story", action="store_true", help="Write per-story evidence JSONs from prd.json")
    parser.add_argument("--evidence-dir", default=".spiral/evidence", help="Directory for per-story evidence files")
    parser.add_argument("--summary-out", default=".spiral/phase_v_summary.json", help="Path for phase_v_summary.json")
    args = parser.parse_args(argv)

    try:
        with open(args.prd, encoding="utf-8") as f:
            prd = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: Cannot read {args.prd}: {exc}", file=sys.stderr)
        return 1

    if args.per_story:
        written = 0
        for story in prd.get("userStories", []):
            sid = story.get("id", "")
            if not sid:
                continue
            verification = story.get("verification") or {}
            test_files: list[str] = verification.get("testFiles") or []
            test_file = test_files[0] if test_files else ""
            test_marker: str = verification.get("testMarker") or ""
            passed = bool(story.get("passes"))
            write_evidence_json(sid, test_file, test_marker, passed, 0, args.evidence_dir)
            written += 1
        summary = aggregate_phase_v_summary(args.evidence_dir, args.summary_out)
        print(
            f"  [V] Evidence: {written} stories → {args.evidence_dir}/; "
            f"summary: {summary['pass_count']}/{summary['total_stories']} pass "
            f"({summary['pass_rate_percent']}%) → {args.summary_out}"
        )
        return 0

    evidence = aggregate_evidence(prd)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)
    print(f"  [V] Evidence written: {args.out} ({len(evidence)} stories)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
