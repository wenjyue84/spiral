#!/usr/bin/env python3
"""
benchmark_runner.py -- Run a story across multiple model tiers and capture cost baselines.

Usage:
  python lib/benchmark_runner.py run <story-id> [--models haiku,sonnet,opus] [--prd prd.json]
  python lib/benchmark_runner.py list [--prd prd.json]
"""

import csv
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Model pricing per million input tokens
PRICING = {
    "haiku": 0.80,
    "sonnet": 3.00,
    "opus": 15.00,
}

TOKENS_PER_SEC_OUTPUT = 20
INPUT_OUTPUT_RATIO = 3.0


def _estimate_tokens_from_duration(duration_sec: float) -> tuple[float, float]:
    """Estimate input and output tokens from duration.

    Returns: (tokens_input, tokens_output)
    """
    output = duration_sec * TOKENS_PER_SEC_OUTPUT
    input_ = output * INPUT_OUTPUT_RATIO
    return (input_, output)


def _calculate_cost_usd(model: str, tokens_input: float) -> float:
    """Calculate cost in USD for input tokens."""
    model_norm = model.lower() if model else "sonnet"
    for key in PRICING:
        if key in model_norm:
            rate = PRICING[key]
            return (tokens_input / 1_000_000.0) * rate
    # Default to sonnet
    return (tokens_input / 1_000_000.0) * PRICING.get("sonnet", 3.00)


def _get_prd(prd_path: str) -> dict[str, Any]:
    """Load prd.json."""
    with open(prd_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}


def _find_story(prd: dict[str, Any], story_id: str) -> dict[str, Any] | None:
    """Find story by ID in prd.json."""
    stories = prd.get("userStories", [])
    if not isinstance(stories, list):
        return None
    for story in stories:
        if isinstance(story, dict) and story.get("id") == story_id:
            return story
    return None


def _run_story_with_model(
    story_id: str, model: str, prd_path: str, repo_root: str
) -> tuple[bool, float, str]:
    """Run a story with a specific model using Ralph worker.

    Returns: (success: bool, duration_sec: float, exit_code_str: str)
    """
    # Create a temporary Ralph invocation with the specific model
    # We use the claude CLI to run a story implementation attempt
    env = {
        "SPIRAL_MODEL": model,
        "SPIRAL_STORY": story_id,
        "SPIRAL_HOME": str(Path(__file__).parent.parent),
    }

    try:
        # Run ralph with the specific model and story
        cmd = [
            "bash",
            str(Path(__file__).parent.parent / "ralph" / "ralph.sh"),
            "1",  # max_iterations=1
            "--model",
            model,
            "--prd",
            prd_path,
            "--story",
            story_id,
        ]

        start_time = datetime.now(timezone.utc)
        result = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            timeout=600,  # 10 minute timeout per model run
            text=True,
        )
        end_time = datetime.now(timezone.utc)
        duration_sec = (end_time - start_time).total_seconds()

        success = result.returncode == 0
        exit_code = str(result.returncode)

        return (success, duration_sec, exit_code)

    except subprocess.TimeoutExpired:
        return (False, 600.0, "timeout")
    except Exception as e:
        print(f"[ERROR] Failed to run story {story_id} with {model}: {e}", file=sys.stderr)
        return (False, 0.0, "error")


def run_benchmark_story(
    story_id: str,
    prd_path: str,
    repo_root: str,
    models: list[str] | None = None,
) -> dict[str, Any]:
    """Run a story across multiple models and capture baselines.

    Returns: dict mapping model -> {tokens_used, cost_usd, duration_sec, exit_code}
    """
    if models is None:
        models = ["haiku", "sonnet", "opus"]

    prd = _get_prd(prd_path)
    story = _find_story(prd, story_id)
    if not story:
        print(f"[ERROR] Story {story_id} not found in {prd_path}", file=sys.stderr)
        sys.exit(1)

    results: dict[str, dict[str, Any]] = {}

    for model in models:
        print(f"[benchmark] Running {story_id} with {model}...", file=sys.stderr)
        success, duration_sec, exit_code = _run_story_with_model(
            story_id, model, prd_path, repo_root
        )

        # Estimate tokens from duration
        input_tokens, output_tokens = _estimate_tokens_from_duration(duration_sec)
        cost_usd = _calculate_cost_usd(model, input_tokens)

        results[model] = {
            "model": model,
            "tokens_used": int(input_tokens + output_tokens),
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "cost_usd": round(cost_usd, 6),
            "duration_sec": round(duration_sec, 2),
            "exit_code": exit_code,
            "success": success,
        }

        print(
            f"[benchmark] {model}: {duration_sec:.2f}s, "
            f"{int(input_tokens + output_tokens)} tokens, "
            f"${cost_usd:.4f}",
            file=sys.stderr,
        )

    # Save baseline
    _save_baseline(story_id, results, repo_root)

    # Output CSV to stdout
    print("\n=== Benchmark Results ===\n", file=sys.stderr)
    print(
        "model,tokens_used,input_tokens,output_tokens,cost_usd,duration_sec,exit_code"
    )
    for model in models:
        if model in results:
            r = results[model]
            print(
                f"{r['model']},{r['tokens_used']},{r['input_tokens']},"
                f"{r['output_tokens']},{r['cost_usd']:.6f},{r['duration_sec']},{r['exit_code']}"
            )

    return results


def _save_baseline(story_id: str, results: dict[str, Any], repo_root: str) -> None:
    """Append benchmark results to .spiral/model_baselines.json."""
    baselines_dir = Path(repo_root) / ".spiral"
    baselines_dir.mkdir(exist_ok=True)
    baselines_file = baselines_dir / "model_baselines.json"

    # Load existing baselines
    baselines = {}
    if baselines_file.exists():
        with open(baselines_file, "r", encoding="utf-8") as f:
            baselines = json.load(f)

    # Add/update this story's benchmark
    baselines[story_id] = {
        "story_id": story_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "benchmarks": results,
    }

    # Save updated baselines
    with open(baselines_file, "w", encoding="utf-8") as f:
        json.dump(baselines, f, indent=2)

    print(f"[benchmark] Saved to {baselines_file}", file=sys.stderr)


def list_benchmarks(prd_path: str, repo_root: str) -> None:
    """List previously benchmarked stories with statistics."""
    baselines_file = Path(repo_root) / ".spiral" / "model_baselines.json"

    if not baselines_file.exists():
        print("No benchmarks found. Run 'spiral benchmark-model <story-id>' first.")
        return

    with open(baselines_file, "r", encoding="utf-8") as f:
        baselines = json.load(f)

    if not baselines:
        print("No benchmarks found.")
        return

    prd = _get_prd(prd_path)
    story_map = {s.get("id"): s.get("title", "Unknown") for s in prd.get("userStories", [])}

    print("\n=== Model Baselines ===\n")
    print(
        f"{'Story ID':<12} {'Title':<40} {'Count':<6} {'Haiku':<15} {'Sonnet':<15} {'Opus':<15}"
    )
    print(f"{'-'*12} {'-'*40} {'-'*6} {'-'*15} {'-'*15} {'-'*15}")

    for story_id, data in sorted(baselines.items()):
        title = story_map.get(story_id, "Unknown")[:40]
        benchmarks = data.get("benchmarks", {})

        haiku_cost = benchmarks.get("haiku", {}).get("cost_usd", 0)
        sonnet_cost = benchmarks.get("sonnet", {}).get("cost_usd", 0)
        opus_cost = benchmarks.get("opus", {}).get("cost_usd", 0)

        print(
            f"{story_id:<12} {title:<40} {len(benchmarks):<6} "
            f"${haiku_cost:.4f}        ${sonnet_cost:.4f}        ${opus_cost:.4f}"
        )


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: spiral benchmark-model [run|list] <story-id>", file=sys.stderr)
        sys.exit(1)

    subcommand = sys.argv[1]
    prd_path = "prd.json"
    repo_root = Path.cwd()

    # Parse arguments
    for i in range(2, len(sys.argv)):
        if sys.argv[i] == "--prd":
            prd_path = sys.argv[i + 1]
        elif sys.argv[i] == "--project-root":
            repo_root = Path(sys.argv[i + 1])

    if subcommand == "run":
        if len(sys.argv) < 3:
            print(
                "Usage: spiral benchmark-model run <story-id> [--models haiku,sonnet,opus]",
                file=sys.stderr,
            )
            sys.exit(1)

        story_id = sys.argv[2]
        models = ["haiku", "sonnet", "opus"]

        # Parse --models flag
        for i in range(3, len(sys.argv)):
            if sys.argv[i] == "--models":
                models = sys.argv[i + 1].split(",")
                break

        run_benchmark_story(story_id, prd_path, str(repo_root), models)

    elif subcommand == "list":
        list_benchmarks(prd_path, str(repo_root))

    else:
        print(f"Unknown subcommand: {subcommand}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
