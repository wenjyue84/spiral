#!/usr/bin/env python3
"""SPIRAL — drift_check.py

Post-implementation drift check: compares a story's acceptanceCriteria against
the git diff produced by Phase I and asks an LLM to rate alignment.

Verdict thresholds (configurable via env vars):
  SPIRAL_DRIFT_PASS_THRESHOLD (default 70): driftScore >= this → pass
  SPIRAL_DRIFT_FAIL_THRESHOLD (default 40): driftScore < this  → fail
  40 <= driftScore < 70                                        → warn

Report written to:
  .spiral/workers/<story-id>/drift_report.json   (per-worker file)
  prd.json story._driftReport field              (annotated on story)

Usage (library):
    from drift_check import run_drift_check
    report = run_drift_check(story_id, acceptance_criteria, diff_text)

Usage (CLI):
    python lib/drift_check.py --story-id US-260 --prd prd.json \\
        --scratch-dir .spiral [--diff-file /tmp/diff.txt]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json, configure_utf8_stdout

configure_utf8_stdout()

# ── Constants ──────────────────────────────────────────────────────────────────

_DEFAULT_PASS_THRESHOLD = 70
_DEFAULT_FAIL_THRESHOLD = 40
_MAX_DIFF_CHARS = 6000   # truncate large diffs to avoid token bloat
_JUDGE_MODEL = "claude-haiku-4-5-20251001"  # fast, low-cost judge


# ── LLM call ──────────────────────────────────────────────────────────────────

def _call_claude(prompt: str, timeout: int = 90) -> str:
    """Call Claude CLI via subprocess and return raw text output."""
    cmd = [
        "claude",
        "-p", prompt,
        "--model", _JUDGE_MODEL,
        "--max-turns", "1",
        "--output-format", "text",
        "--dangerously-skip-permissions",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )
        if result.returncode == 0:
            return result.stdout.strip()
        print(
            f"  [drift] Claude CLI error (rc={result.returncode}): {result.stderr[:200]}",
            file=sys.stderr,
        )
        return ""
    except subprocess.TimeoutExpired:
        print("  [drift] Claude CLI timed out", file=sys.stderr)
        return ""
    except FileNotFoundError:
        print("  [drift] claude CLI not found — skipping LLM judge", file=sys.stderr)
        return ""
    except Exception as exc:  # noqa: BLE001
        print(f"  [drift] Claude CLI failed: {exc}", file=sys.stderr)
        return ""


# ── Core logic ─────────────────────────────────────────────────────────────────

def _build_prompt(acceptance_criteria: list[str], diff_text: str) -> str:
    criteria_block = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(acceptance_criteria))
    diff_snippet = diff_text[:_MAX_DIFF_CHARS]
    if len(diff_text) > _MAX_DIFF_CHARS:
        diff_snippet += "\n... [truncated] ..."
    return f"""You are a strict code-review auditor checking whether a software implementation
matches its acceptance criteria.

ACCEPTANCE CRITERIA:
{criteria_block}

GIT DIFF (implementation produced by Phase I):
```diff
{diff_snippet}
```

Evaluate how well the implementation satisfies EACH acceptance criterion.
For each criterion, decide: met / partial / absent.

Then compute:
  driftScore  = round(100 * met_count / total_count)   (0-100 integer)
  missingCriteria = list of criterion numbers that are absent
  scopeCreep  = list of short descriptions of out-of-scope changes (if any)
  verdict     = "pass" if driftScore >= 70, "warn" if >= 40, else "fail"

Respond ONLY with valid JSON (no prose, no markdown fences):
{{
  "driftScore": <integer 0-100>,
  "missingCriteria": [<criterion number>, ...],
  "scopeCreep": ["<short description>", ...],
  "verdict": "pass" | "warn" | "fail",
  "notes": "<one-sentence explanation>"
}}"""


def _parse_llm_response(text: str) -> dict[str, Any] | None:
    """Extract JSON object from LLM response text."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        return None
    try:
        result: dict[str, Any] = json.loads(text[start:end])
        return result
    except json.JSONDecodeError:
        return None


def _heuristic_report(diff_text: str, acceptance_criteria: list[str]) -> dict[str, Any]:
    """Fallback report when LLM is unavailable: score by diff non-emptiness."""
    has_diff = bool(diff_text.strip())
    score = 60 if has_diff else 0
    return {
        "driftScore": score,
        "missingCriteria": [],
        "scopeCreep": [],
        "verdict": "warn" if has_diff else "fail",
        "notes": "Heuristic: LLM judge unavailable; scored by diff presence only.",
        "_heuristic": True,
    }


def run_drift_check(
    story_id: str,
    acceptance_criteria: list[str],
    diff_text: str,
    pass_threshold: int = _DEFAULT_PASS_THRESHOLD,
    fail_threshold: int = _DEFAULT_FAIL_THRESHOLD,
) -> dict[str, Any]:
    """Run drift check and return the report dict.

    Parameters
    ----------
    story_id:            Story identifier (e.g. "US-260").
    acceptance_criteria: List of acceptance criterion strings.
    diff_text:           Raw ``git diff`` output for the implementation.
    pass_threshold:      Score >= this → verdict=pass (default 70).
    fail_threshold:      Score < this  → verdict=fail (default 40).

    Returns
    -------
    dict with keys: driftScore, missingCriteria, scopeCreep, verdict, notes,
    plus _storyId, _checkedAt, _passThreshold, _failThreshold.
    """
    if not acceptance_criteria:
        return {
            "driftScore": 100,
            "missingCriteria": [],
            "scopeCreep": [],
            "verdict": "pass",
            "notes": "No acceptance criteria to check against.",
            "_storyId": story_id,
            "_checkedAt": datetime.now(timezone.utc).isoformat(),
            "_passThreshold": pass_threshold,
            "_failThreshold": fail_threshold,
        }

    prompt = _build_prompt(acceptance_criteria, diff_text)
    llm_text = _call_claude(prompt)

    if llm_text:
        parsed = _parse_llm_response(llm_text)
    else:
        parsed = None

    if parsed is None:
        report = _heuristic_report(diff_text, acceptance_criteria)
    else:
        score = int(parsed.get("driftScore", 50))
        # Re-compute verdict using configured thresholds (may differ from model defaults)
        if score >= pass_threshold:
            verdict = "pass"
        elif score >= fail_threshold:
            verdict = "warn"
        else:
            verdict = "fail"
        report = {
            "driftScore": score,
            "missingCriteria": parsed.get("missingCriteria", []),
            "scopeCreep": parsed.get("scopeCreep", []),
            "verdict": verdict,
            "notes": parsed.get("notes", ""),
        }

    report["_storyId"] = story_id
    report["_checkedAt"] = datetime.now(timezone.utc).isoformat()
    report["_passThreshold"] = pass_threshold
    report["_failThreshold"] = fail_threshold
    return report


# ── I/O helpers ────────────────────────────────────────────────────────────────

def write_drift_report(
    report: dict[str, Any],
    scratch_dir: str,
    story_id: str,
) -> str:
    """Write the drift report to .spiral/workers/<story-id>/drift_report.json.

    Returns the path written.
    """
    out_dir = Path(scratch_dir) / "workers" / story_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(out_dir / "drift_report.json")
    atomic_write_json(out_path, report)
    return out_path


def update_prd_drift(prd_path: str, story_id: str, report: dict[str, Any]) -> None:
    """Patch prd.json story._driftReport with the drift report (non-automated field)."""
    path = Path(prd_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  [drift] Could not read prd.json: {exc}", file=sys.stderr)
        return

    updated = False
    for story in data.get("userStories", []):
        if story.get("id") == story_id:
            story["_driftReport"] = report
            updated = True
            break

    if not updated:
        print(f"  [drift] Story {story_id} not found in prd.json", file=sys.stderr)
        return

    try:
        atomic_write_json(prd_path, data)
    except OSError as exc:
        print(f"  [drift] Could not write prd.json: {exc}", file=sys.stderr)


def get_git_diff(repo_root: str, ref: str = "HEAD~1") -> str:
    """Return git diff output from *ref* to HEAD."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_root, "diff", ref],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception as exc:  # noqa: BLE001
        print(f"  [drift] git diff failed: {exc}", file=sys.stderr)
        return ""


def log_drift_event(
    events_file: str,
    story_id: str,
    report: dict[str, Any],
    iteration: int = 0,
) -> None:
    """Append a drift_check event to spiral_events.jsonl."""
    from spiral_io import append_jsonl

    record = {
        "event": "drift_check",
        "story_id": story_id,
        "iteration": iteration,
        "driftScore": report.get("driftScore"),
        "verdict": report.get("verdict"),
        "missingCriteria": report.get("missingCriteria", []),
        "scopeCreep": report.get("scopeCreep", []),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        append_jsonl(events_file, record)
    except OSError as exc:
        print(f"  [drift] Could not write events file: {exc}", file=sys.stderr)


# ── CLI ────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Post-Phase-I drift check: compare implementation against acceptance criteria.",
    )
    p.add_argument("--story-id", required=True, help="Story ID to check (e.g. US-260)")
    p.add_argument("--prd", default="prd.json", help="Path to prd.json (default: prd.json)")
    p.add_argument("--scratch-dir", default=".spiral", help="SPIRAL scratch directory (default: .spiral)")
    p.add_argument(
        "--diff-file",
        default=None,
        help="Path to a pre-generated diff file; omit to auto-run git diff HEAD~1",
    )
    p.add_argument(
        "--repo-root",
        default=".",
        help="Git repo root for auto-diff (default: current dir)",
    )
    p.add_argument(
        "--pass-threshold",
        type=int,
        default=int(os.environ.get("SPIRAL_DRIFT_PASS_THRESHOLD", _DEFAULT_PASS_THRESHOLD)),
        help="Score >= this → pass (default: SPIRAL_DRIFT_PASS_THRESHOLD or 70)",
    )
    p.add_argument(
        "--fail-threshold",
        type=int,
        default=int(os.environ.get("SPIRAL_DRIFT_FAIL_THRESHOLD", _DEFAULT_FAIL_THRESHOLD)),
        help="Score < this → fail (default: SPIRAL_DRIFT_FAIL_THRESHOLD or 40)",
    )
    p.add_argument(
        "--iteration",
        type=int,
        default=0,
        help="Current SPIRAL iteration number (for event log)",
    )
    p.add_argument(
        "--no-prd-update",
        action="store_true",
        help="Skip patching prd.json with _driftReport",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # Load story from prd.json
    prd_path = Path(args.prd)
    if not prd_path.exists():
        print(f"  [drift] prd.json not found at {prd_path}", file=sys.stderr)
        return 1

    data = json.loads(prd_path.read_text(encoding="utf-8"))
    story = next(
        (s for s in data.get("userStories", []) if s.get("id") == args.story_id),
        None,
    )
    if story is None:
        print(f"  [drift] Story {args.story_id} not found in prd.json", file=sys.stderr)
        return 1

    acceptance_criteria: list[str] = story.get("acceptanceCriteria", [])

    # Get diff
    if args.diff_file:
        diff_path = Path(args.diff_file)
        diff_text = diff_path.read_text(encoding="utf-8", errors="replace") if diff_path.exists() else ""
    else:
        diff_text = get_git_diff(args.repo_root)

    if not diff_text.strip():
        print(f"  [drift] WARNING: empty diff for {args.story_id} — no changes detected", file=sys.stderr)

    # Run check
    t0 = time.perf_counter()
    report = run_drift_check(
        story_id=args.story_id,
        acceptance_criteria=acceptance_criteria,
        diff_text=diff_text,
        pass_threshold=args.pass_threshold,
        fail_threshold=args.fail_threshold,
    )
    duration_ms = int((time.perf_counter() - t0) * 1000)

    # Write report file
    report_path = write_drift_report(report, args.scratch_dir, args.story_id)

    # Patch prd.json
    if not args.no_prd_update:
        update_prd_drift(args.prd, args.story_id, report)

    # Log event
    events_file = str(Path(args.scratch_dir) / "spiral_events.jsonl")
    log_drift_event(events_file, args.story_id, report, iteration=args.iteration)

    # Print summary
    verdict = report.get("verdict", "?")
    score = report.get("driftScore", 0)
    verdict_label = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}.get(verdict, verdict.upper())
    print(
        f"  [drift] {args.story_id}: score={score}/100 verdict={verdict_label} "
        f"({duration_ms}ms) → {report_path}"
    )
    if report.get("missingCriteria"):
        print(f"  [drift]   missing criteria: {report['missingCriteria']}")
    if report.get("scopeCreep"):
        print(f"  [drift]   scope creep: {report['scopeCreep']}")
    if report.get("notes"):
        print(f"  [drift]   notes: {report['notes']}")

    # Exit code: 0=pass/warn, 1=fail
    return 0 if verdict in ("pass", "warn") else 1


if __name__ == "__main__":
    sys.exit(main())
