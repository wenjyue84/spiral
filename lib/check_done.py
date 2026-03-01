#!/usr/bin/env python3
"""
SPIRAL Phase C — Check Done
Exits 0 if: all prd.json stories pass AND latest test report has 0 failures.
Exits 1 otherwise (loop continues).
"""
import argparse
import json
import os
import sys
import time


def find_latest_report(reports_dir: str) -> str | None:
    if not os.path.isdir(reports_dir):
        return None
    subdirs = sorted(
        [d for d in os.listdir(reports_dir) if os.path.isdir(os.path.join(reports_dir, d))],
        reverse=True,
    )
    for d in subdirs:
        candidate = os.path.join(reports_dir, d, "report.json")
        if os.path.isfile(candidate):
            return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="SPIRAL check-done gate")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    parser.add_argument("--reports-dir", default="test-reports", help="Test reports directory")
    args = parser.parse_args()

    # ── Check prd.json ────────────────────────────────────────────
    if not os.path.isfile(args.prd):
        print(f"[check_done] ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    with open(args.prd, encoding="utf-8") as f:
        prd = json.load(f)

    stories = prd.get("userStories", [])
    total = len(stories)
    pending = [s for s in stories if not s.get("passes")]
    done = total - len(pending)

    print(f"[check_done] PRD: {done}/{total} stories complete, {len(pending)} pending")

    if pending:
        print("[check_done] Pending stories:")
        for s in pending:
            print(f"  [{s['id']}] {s['title']} (priority: {s.get('priority', '?')})")

    # ── Check latest test report ──────────────────────────────────
    report_path = find_latest_report(args.reports_dir)
    if not report_path:
        print(
            f"[check_done] WARNING: No test report found in {args.reports_dir}/ — run tests first",
            file=sys.stderr,
        )
        print("[check_done] RESULT: INCOMPLETE (no test report)")
        return 1

    report_age_min = (time.time() - os.path.getmtime(report_path)) / 60
    if report_age_min > 120:
        print(
            f"[check_done] WARNING: Test report is {report_age_min:.0f} min old — "
            "results may be stale; re-run tests for accurate check",
            file=sys.stderr,
        )

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    summary = report.get("summary", {})
    failed = summary.get("failed", 0)
    errored = summary.get("errored", 0)
    passed = summary.get("passed", 0)
    test_total = summary.get("total", 0)
    pass_rate = summary.get("pass_rate", "?")

    print(f"[check_done] Tests ({os.path.basename(os.path.dirname(report_path))}): "
          f"{passed}/{test_total} pass ({pass_rate}), {failed} failed, {errored} errored")

    # ── Decision ─────────────────────────────────────────────────
    prd_done = len(pending) == 0
    tests_clean = (failed == 0 and errored == 0)

    if prd_done and tests_clean:
        print("[check_done] RESULT: SPIRAL COMPLETE — all stories done and 100% tests pass!")
        return 0

    reasons = []
    if not prd_done:
        reasons.append(f"{len(pending)} pending stories")
    if not tests_clean:
        reasons.append(f"{failed + errored} test failure(s)")
    print(f"[check_done] RESULT: INCOMPLETE ({', '.join(reasons)})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
