#!/usr/bin/env python3
"""
lib/quality_judge.py — LLM-as-Judge continuous quality evaluation (US-248)

After Phase R and Phase I complete, this module invokes a cheap LLM judge
(haiku) to score outputs for quality on a 1-5 scale, storing results in
the checkpoint under _qualityScores.{phase}.

Shell integration:
  # After Phase R completes:
  "$SPIRAL_PYTHON" lib/quality_judge.py judge-phase-r \\
      --research-output "$SCRATCH_DIR/_research_output.json" \\
      --checkpoint "$CHECKPOINT_FILE" \\
      --iteration "$SPIRAL_ITER" \\
      --threshold "${SPIRAL_QUALITY_THRESHOLD:-3}" 2>/dev/null || true

  # After Phase I completes:
  "$SPIRAL_PYTHON" lib/quality_judge.py judge-phase-i \\
      --prd "$PRD_FILE" \\
      --checkpoint "$CHECKPOINT_FILE" \\
      --iteration "$SPIRAL_ITER" \\
      --threshold "${SPIRAL_QUALITY_THRESHOLD:-3}" 2>/dev/null || true

Silently no-ops when SPIRAL_QUALITY_JUDGE_DISABLE=1.
Always writes to checkpoint regardless of score.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json, configure_utf8_stdout, safe_read_json

configure_utf8_stdout()

_JUDGE_MODEL = os.environ.get("SPIRAL_JUDGE_MODEL", "claude-haiku-4-5-20251001")

_PHASE_R_PROMPT_TEMPLATE = """\
You are an expert technical researcher reviewing a set of story research outputs.

The research was generated to discover user stories for a software project.
Iteration: {iteration}

Research output summary (first 2000 chars):
{research_summary}

Rate the research output on two dimensions (1-5 integer scale):

1. **Relevance** (1=off-topic stories, 5=laser-focused on project goals)
2. **Completeness** (1=very sparse/missing key areas, 5=thorough coverage)

Respond ONLY with valid JSON (no markdown, no extra text):
{{
  "relevance": <1-5>,
  "completeness": <1-5>,
  "score": <average of relevance and completeness, one decimal>,
  "rationale": "<one sentence explaining the score>"
}}"""

_PHASE_I_PROMPT_TEMPLATE = """\
You are an expert code reviewer assessing implementation quality for a batch of stories.

Iteration: {iteration}
Stories attempted: {attempted}
Stories passed: {passed}
Pass rate: {pass_rate}%

Sample of implemented stories (acceptance criteria):
{stories_sample}

Rate the implementation batch on two dimensions (1-5 integer scale):

1. **Criteria Coverage** (1=criteria ignored, 5=all criteria addressed)
2. **Quality** (1=obvious errors/broken code, 5=clean, no obvious issues)

Respond ONLY with valid JSON (no markdown, no extra text):
{{
  "criteria_coverage": <1-5>,
  "quality": <1-5>,
  "score": <average of both dimensions, one decimal>,
  "rationale": "<one sentence explaining the score>"
}}"""


def _call_judge(prompt: str, timeout: int = 90) -> Optional[str]:
    """Invoke Claude CLI with the judge prompt. Returns output text or None."""
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
        print(f"  [quality-judge] Claude CLI error: {result.stderr[:200]}", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print("  [quality-judge] Timed out waiting for judge response", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"  [quality-judge] Failed to call judge: {exc}", file=sys.stderr)
        return None


def _parse_score_json(text: str) -> Optional[dict[str, Any]]:
    """Extract and parse JSON from judge response text."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        return None
    try:
        result: dict[str, Any] = json.loads(text[start:end])
        return result
    except json.JSONDecodeError:
        return None


def _update_checkpoint_scores(
    checkpoint_path: str,
    phase: str,
    score_record: dict[str, Any],
) -> None:
    """Upsert _qualityScores.{phase} in the checkpoint JSON."""
    data = safe_read_json(checkpoint_path, default={})
    quality_scores: dict[str, Any] = data.setdefault("_qualityScores", {})
    phase_scores: list[dict[str, Any]] = quality_scores.setdefault(phase, [])
    phase_scores.append(score_record)
    atomic_write_json(checkpoint_path, data)


def cmd_judge_phase_r(args: argparse.Namespace) -> None:
    """Score Phase R research output and write to checkpoint."""
    if os.environ.get("SPIRAL_QUALITY_JUDGE_DISABLE", "0") == "1":
        print("  [quality-judge] Disabled via SPIRAL_QUALITY_JUDGE_DISABLE=1", file=sys.stderr)
        return

    research_path = args.research_output
    if not os.path.isfile(research_path):
        print(f"  [quality-judge] Research output not found: {research_path}", file=sys.stderr)
        return

    try:
        with open(research_path, encoding="utf-8", errors="replace") as fh:
            research_text = fh.read(2000)
    except OSError as exc:
        print(f"  [quality-judge] Cannot read research output: {exc}", file=sys.stderr)
        return

    prompt = _PHASE_R_PROMPT_TEMPLATE.format(
        iteration=args.iteration,
        research_summary=research_text,
    )

    print("  [quality-judge] Scoring Phase R output...", file=sys.stderr)
    raw = _call_judge(prompt)
    parsed = _parse_score_json(raw or "")

    if parsed is None:
        print("  [quality-judge] Could not parse judge response for Phase R", file=sys.stderr)
        return

    score = float(parsed.get("score", 0))
    rationale = str(parsed.get("rationale", ""))
    record: dict[str, Any] = {
        "score": score,
        "relevance": parsed.get("relevance"),
        "completeness": parsed.get("completeness"),
        "rationale": rationale,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "iteration": args.iteration,
    }

    _update_checkpoint_scores(args.checkpoint, "R", record)

    threshold = float(args.threshold)
    indicator = "OK" if score >= threshold else "LOW"
    print(
        f"  [quality-judge] Phase R score: {score:.1f}/5 [{indicator}] — {rationale}",
        file=sys.stderr,
    )
    if score < threshold:
        print(
            f"  [quality-judge] WARNING: Phase R quality score {score:.1f} is below "
            f"threshold {threshold:.1f} (SPIRAL_QUALITY_THRESHOLD). "
            "Research output may be low quality — continuing.",
            file=sys.stderr,
        )


def cmd_judge_phase_i(args: argparse.Namespace) -> None:
    """Score Phase I implementation quality and write to checkpoint."""
    if os.environ.get("SPIRAL_QUALITY_JUDGE_DISABLE", "0") == "1":
        print("  [quality-judge] Disabled via SPIRAL_QUALITY_JUDGE_DISABLE=1", file=sys.stderr)
        return

    prd_path = args.prd
    prd = safe_read_json(prd_path, default={"userStories": []})
    stories = prd.get("userStories", [])

    # Summarise recently-passed stories for context
    passed_stories = [s for s in stories if s.get("passes") is True]
    attempted = len(stories)
    passed = len(passed_stories)
    pass_rate = round(100 * passed / attempted) if attempted > 0 else 0

    # Build a compact sample (up to 3 stories with acceptance criteria)
    sample_parts: list[str] = []
    for s in passed_stories[-3:]:
        sid = s.get("id", "?")
        title = s.get("title", "?")
        criteria = s.get("acceptanceCriteria", [])[:3]
        criteria_text = "\n".join(f"  - {c}" for c in criteria)
        sample_parts.append(f"[{sid}] {title}\n{criteria_text}")

    stories_sample = "\n\n".join(sample_parts) if sample_parts else "(no passed stories yet)"

    prompt = _PHASE_I_PROMPT_TEMPLATE.format(
        iteration=args.iteration,
        attempted=attempted,
        passed=passed,
        pass_rate=pass_rate,
        stories_sample=stories_sample,
    )

    print("  [quality-judge] Scoring Phase I output...", file=sys.stderr)
    raw = _call_judge(prompt)
    parsed = _parse_score_json(raw or "")

    if parsed is None:
        print("  [quality-judge] Could not parse judge response for Phase I", file=sys.stderr)
        return

    score = float(parsed.get("score", 0))
    rationale = str(parsed.get("rationale", ""))
    record: dict[str, Any] = {
        "score": score,
        "criteria_coverage": parsed.get("criteria_coverage"),
        "quality": parsed.get("quality"),
        "rationale": rationale,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "iteration": args.iteration,
        "pass_rate": pass_rate,
    }

    _update_checkpoint_scores(args.checkpoint, "I", record)

    threshold = float(args.threshold)
    indicator = "OK" if score >= threshold else "LOW"
    print(
        f"  [quality-judge] Phase I score: {score:.1f}/5 [{indicator}] — {rationale}",
        file=sys.stderr,
    )
    if score < threshold:
        print(
            f"  [quality-judge] WARNING: Phase I quality score {score:.1f} is below "
            f"threshold {threshold:.1f} (SPIRAL_QUALITY_THRESHOLD). "
            "Implementation quality may be degrading — continuing.",
            file=sys.stderr,
        )


def cmd_show(args: argparse.Namespace) -> None:
    """Display quality scores from the checkpoint."""
    data = safe_read_json(args.checkpoint, default={})
    quality_scores = data.get("_qualityScores", {})
    if not quality_scores:
        print("No quality scores recorded yet.")
        return

    for phase, records in sorted(quality_scores.items()):
        if not records:
            continue
        scores = [r.get("score", 0) for r in records if isinstance(r.get("score"), (int, float))]
        avg = sum(scores) / len(scores) if scores else 0
        latest = records[-1]
        print(
            f"Phase {phase}: avg={avg:.1f}/5  latest={latest.get('score', '?')}/5  "
            f"n={len(records)}  last=\"{latest.get('rationale', '')}\" "
            f"({latest.get('timestamp', '')})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM-as-Judge quality evaluation for SPIRAL phase outputs (US-248)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # judge-phase-r
    p_r = sub.add_parser("judge-phase-r", help="Score Phase R research output")
    p_r.add_argument("--research-output", required=True, help="Path to _research_output.json")
    p_r.add_argument("--checkpoint", required=True, help="Path to _checkpoint.json")
    p_r.add_argument("--iteration", type=int, default=1, help="Current iteration number")
    p_r.add_argument("--threshold", type=float, default=3.0, help="Warning threshold (1-5)")
    p_r.set_defaults(func=cmd_judge_phase_r)

    # judge-phase-i
    p_i = sub.add_parser("judge-phase-i", help="Score Phase I implementation quality")
    p_i.add_argument("--prd", required=True, help="Path to prd.json")
    p_i.add_argument("--checkpoint", required=True, help="Path to _checkpoint.json")
    p_i.add_argument("--iteration", type=int, default=1, help="Current iteration number")
    p_i.add_argument("--threshold", type=float, default=3.0, help="Warning threshold (1-5)")
    p_i.set_defaults(func=cmd_judge_phase_i)

    # show
    p_show = sub.add_parser("show", help="Display stored quality scores")
    p_show.add_argument("--checkpoint", required=True, help="Path to _checkpoint.json")
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
