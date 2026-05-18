#!/usr/bin/env python3
"""lib/dry_run_planner.py -- Preview execution plan without API calls"""

import json
import sys
from dataclasses import dataclass
from typing import Any


@dataclass
class PhaseEstimate:
    """Token estimate for a single phase"""

    name: str
    story_count: int
    estimated_tokens: int


@dataclass
class ExecutionPlan:
    """Complete execution plan for N iterations"""

    num_iterations: int
    phases: list[PhaseEstimate]
    total_estimated_tokens: int
    worker_plan: str


def plan_execution(prd_dict: dict[str, Any], num_iterations: int) -> ExecutionPlan:
    """Plan N iterations of SPIRAL phases without making API calls.

    Estimates tokens based on story count and phase characteristics.
    """
    stories = prd_dict.get("userStories", [])
    story_count = len(stories)

    # Phase token estimates (rough heuristics per iteration)
    # These are per-iteration estimates, multiplied by num_iterations
    phase_configs = [
        ("A: AI Suggestions", 2000),  # token cost
        ("R: Research", 5000),  # web search costs
        ("T: Test Synthesis", 3000),  # test generation
        ("S: Story Validate", 1000),  # validation
        ("E: Enrichment", 1500),  # context building
        ("M: Merge", 500),  # prd.json manipulation
        ("X: Context Build", 800),  # symbol mapping
        ("G: Gate", 200),  # human/auto gate
        ("I: Implement", 15000),  # implementation (biggest)
        ("V: Validate", 3000),  # test execution
        ("C: Check Done", 200),  # completion check
        ("L: Learning", 500),  # episodic memory
    ]

    # Adjust estimates based on story count (more stories = more tokens in some phases)
    # Phases like R, T, S, E scale with story count
    # Phases like I, V scale with stories being implemented
    scaling_factors = {
        "R: Research": 1.0 + (story_count / 100),  # scales with search volume
        "T: Test Synthesis": 1.0 + (story_count / 150),  # test generation scales
        "S: Story Validate": 0.5,  # lighter, ~50% of base
        "I: Implement": 1.0 + (story_count / 50),  # heavy scaling
    }

    phases = []
    total_tokens = 0

    for phase_name, base_tokens in phase_configs:
        # Get scaling factor if phase scales with story count
        scale = scaling_factors.get(phase_name, 1.0)
        phase_tokens = int(base_tokens * scale * num_iterations)

        phase_est = PhaseEstimate(
            name=phase_name,
            story_count=story_count,
            estimated_tokens=phase_tokens,
        )
        phases.append(phase_est)
        total_tokens += phase_tokens

    # Worker plan: single-worker default based on memory feedback
    worker_plan = "1 worker (sequential)"

    return ExecutionPlan(
        num_iterations=num_iterations,
        phases=phases,
        total_estimated_tokens=total_tokens,
        worker_plan=worker_plan,
    )


def format_ascii_tree(plan: ExecutionPlan) -> str:
    """Format execution plan as ASCII tree for terminal display."""
    lines = []
    lines.append("")
    lines.append("  SPIRAL Dry-Run Execution Plan")
    lines.append("  " + "=" * 50)
    lines.append("")
    lines.append(f"  Iterations      : {plan.num_iterations}")
    lines.append(f"  Stories         : {plan.phases[0].story_count}")
    lines.append(f"  Workers         : {plan.worker_plan}")
    lines.append("")
    lines.append("  Phase Breakdown (tokens per iteration):")
    lines.append("  " + "-" * 50)

    for phase in plan.phases:
        # Format: phase_name (story_count stories) | tokens
        phase_per_iter = phase.estimated_tokens // plan.num_iterations
        lines.append(f"    {phase.name:<25} │ {phase_per_iter:>8,} tokens/iter")

    lines.append("  " + "-" * 50)
    total_per_iter = plan.total_estimated_tokens // plan.num_iterations
    lines.append(f"    {'TOTAL':<25} │ {total_per_iter:>8,} tokens/iter")
    lines.append(f"    {'(across all iterations)':<25} │ {plan.total_estimated_tokens:>8,} tokens")
    lines.append("")

    # Add cost estimate (rough pricing)
    # Haiku: $0.80 / 1M, Sonnet: $3.00 / 1M, Opus: $15.00 / 1M
    # Assume mix: 40% haiku, 50% sonnet, 10% opus
    haiku_rate = 0.80 / 1_000_000
    sonnet_rate = 3.00 / 1_000_000
    opus_rate = 15.00 / 1_000_000

    haiku_tokens = int(plan.total_estimated_tokens * 0.40)
    sonnet_tokens = int(plan.total_estimated_tokens * 0.50)
    opus_tokens = int(plan.total_estimated_tokens * 0.10)

    estimated_cost = haiku_tokens * haiku_rate + sonnet_tokens * sonnet_rate + opus_tokens * opus_rate

    lines.append(f"  Estimated Cost  : ${estimated_cost:.2f} USD")
    lines.append("")

    return "\n".join(lines)


def format_json_plan(plan: ExecutionPlan) -> dict[str, Any]:
    """Format execution plan as JSON structure."""
    return {
        "num_iterations": plan.num_iterations,
        "phases": [
            {
                "name": p.name,
                "estimated_tokens": p.estimated_tokens,
                "story_count": p.story_count,
            }
            for p in plan.phases
        ],
        "total_estimated_cost": plan.total_estimated_tokens,  # AC says key is total_estimated_cost
        "worker_plan": plan.worker_plan,
    }


def main() -> None:
    """Main entry point for dry-run command."""
    if len(sys.argv) < 2:
        print(
            "[spiral] ERROR: Usage: spiral dry-run <num_iterations> [--output json]",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        num_iters = int(sys.argv[1])
    except ValueError:
        print(
            f"[spiral] ERROR: Invalid iteration count: {sys.argv[1]}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parse --output flag
    output_format = "ascii"  # default
    for i, arg in enumerate(sys.argv):
        if arg == "--output" and i + 1 < len(sys.argv):
            output_format = sys.argv[i + 1]
            break

    # Load prd.json (default location)
    try:
        with open("prd.json", encoding="utf-8") as f:
            prd_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[spiral] ERROR: Failed to load prd.json: {e}", file=sys.stderr)
        sys.exit(1)

    # Generate plan
    plan = plan_execution(prd_data, num_iters)

    # Output result
    if output_format == "json":
        print(json.dumps(format_json_plan(plan), indent=2))
    else:
        # Default to ASCII tree
        print(format_ascii_tree(plan))

    sys.exit(0)


if __name__ == "__main__":
    main()
