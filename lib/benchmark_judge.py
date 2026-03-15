#!/usr/bin/env python3
"""
Benchmark Judge: Score model outputs using LLM-as-judge pattern.
Evaluates each model's implementation against story acceptance criteria.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def call_claude(prompt: str) -> str:
    """Call Claude CLI via subprocess (haiku model for speed/cost)."""
    cmd = [
        "claude",
        "-p", prompt,
        "--model", "claude-3-5-haiku-20241022",
        "--max-turns", "1",
        "--output-format", "text",
        "--dangerously-skip-permissions",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(f"  [judge] Claude CLI error: {result.stderr}", file=sys.stderr)
            return ""
    except Exception as e:
        print(f"  [judge] Claude CLI failed: {e}", file=sys.stderr)
        return ""


def score_model_output(
    story_id: str,
    story_title: str,
    acceptance_criteria: list,
    model_name: str,
    log_file: str,
    duration_s: int,
    passes: bool,
) -> dict:
    """Score a single model's implementation using LLM judge."""

    # Read the implementation log
    try:
        with open(log_file, "r") as f:
            log_content = f.read()[:1500]  # First 1500 chars to avoid token bloat
    except FileNotFoundError:
        log_content = "[Log file not found]"

    # Build scoring prompt
    prompt = f"""You are an expert code reviewer evaluating a story implementation.

Story ID: {story_id}
Story: {story_title}
Model: {model_name}
Duration: {duration_s}s
Compilation Status: {'PASSED' if passes else 'FAILED'}

Acceptance Criteria:
{chr(10).join(f'- {c}' for c in acceptance_criteria)}

Implementation Log (first 1500 chars):
{log_content}

Rate this implementation on a 1-5 scale for each dimension:
1. **Correctness**: Does it implement what was asked? (1=wrong, 5=perfect)
2. **Test Pass Rate**: Did the tests pass? (1=0%, 5=100%)
3. **Code Style**: Is the code clean and maintainable? (1=poor, 5=excellent)

Respond ONLY with JSON:
{{
  "correctness": <1-5>,
  "test_pass_rate": <1-5>,
  "code_style": <1-5>,
  "notes": "<brief explanation>"
}}"""

    response_text = call_claude(prompt)
    if response_text:
        try:
            # Extract JSON from response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                score_data = json.loads(response_text[json_start:json_end])
                return {
                    "correctness": score_data.get("correctness", 3),
                    "test_pass_rate": score_data.get("test_pass_rate", 3 if passes else 1),
                    "code_style": score_data.get("code_style", 3),
                    "notes": score_data.get("notes", ""),
                }
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback scoring based on pass status
    return {
        "correctness": 4 if passes else 2,
        "test_pass_rate": 5 if passes else 1,
        "code_style": 3,
        "notes": "Fallback scoring (LLM judge unavailable)",
    }


def main():
    """Main benchmark judge entry point."""
    parser = argparse.ArgumentParser(description="Score benchmark implementations")
    parser.add_argument("--story-id", required=True, help="Story ID (e.g., US-001)")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--benchmark-dir", required=True, help="Benchmark working directory")
    parser.add_argument("--results", required=True, help="JSON string with model results")
    parser.add_argument("--output", required=True, help="Output benchmark-results.jsonl path")

    args = parser.parse_args()

    # Load PRD to get story details
    try:
        with open(args.prd) as f:
            prd = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[judge] ERROR: Failed to load PRD: {e}", file=sys.stderr)
        return 1

    # Find story in PRD
    story = None
    for s in prd.get("userStories", []):
        if s["id"] == args.story_id:
            story = s
            break

    if not story:
        print(f"[judge] ERROR: Story {args.story_id} not found in PRD", file=sys.stderr)
        return 1

    # Parse results JSON
    try:
        results = json.loads(args.results)
    except json.JSONDecodeError as e:
        print(f"[judge] ERROR: Failed to parse results JSON: {e}", file=sys.stderr)
        return 1

    # Score each model
    benchmark_result = {
        "storyId": args.story_id,
        "storyTitle": story.get("title", ""),
        "timestamp": int(datetime.now().timestamp()),
        "models": [],
    }

    for model_name, model_result in results.items():
        log_file = os.path.join(args.benchmark_dir, f"log-{model_name}.txt")
        duration_s = model_result.get("duration_s", 0)
        passes = model_result.get("passes", False)

        # Score with LLM judge
        scores = score_model_output(
            args.story_id,
            story.get("title", ""),
            story.get("acceptanceCriteria", []),
            model_name,
            log_file,
            duration_s,
            passes,
        )

        # Compute overall score (average of dimensions)
        overall = (
            scores["correctness"] +
            scores["test_pass_rate"] +
            scores["code_style"]
        ) / 3.0

        benchmark_result["models"].append({
            "name": model_name,
            "passes": passes,
            "duration_s": duration_s,
            "scores": {
                "correctness": scores["correctness"],
                "test_pass_rate": scores["test_pass_rate"],
                "code_style": scores["code_style"],
                "overall": round(overall, 2),
            },
            "notes": scores["notes"],
        })

    # Write results to JSONL
    try:
        with open(args.output, "a") as f:
            f.write(json.dumps(benchmark_result) + "\n")
        print(f"[judge] Benchmark results written to {args.output}")
    except IOError as e:
        print(f"[judge] ERROR: Failed to write results: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
