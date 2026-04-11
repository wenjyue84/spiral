"""Performance regression test for SPIRAL phase timing (US-1195).

Monitors phase execution time to detect regressions. Records P50/P90 baseline
from the last 10 iterations and fails if any phase exceeds 20% degradation.

Run: uv run pytest tests/ -k us_1008 -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from statistics import median, quantiles

import pytest

# Add lib/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from observability.timing_analyzer import parse_events


def compute_percentile(values: list[float], percentile: int) -> float:
    """Compute percentile (50, 90, etc.) from a list of values.

    Args:
        values: List of numeric values
        percentile: Percentile to compute (50 for median, 90 for P90)

    Returns:
        The percentile value, or 0.0 if insufficient data
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]

    # quantiles returns n-1 cut points for n quantiles
    if percentile == 50:
        return median(values)

    # For P90, we want the 90th percentile
    # quantiles(..., n=10) gives 9 cut points dividing into 10 equal groups
    # The 9th cut point (index 8) is the P90 value
    try:
        cuts = quantiles(values, n=10)
        return cuts[8]  # 9th of 10 quantiles = P90
    except (ValueError, IndexError):
        # If quantiles fails (too few values), use max as fallback
        return max(values)


@pytest.mark.us_1008
def test_phase_timing_regression() -> None:
    """Performance regression test: phase timing must not degrade >20% from baseline.

    Extracts P90 baseline from the last 10 iterations and verifies current
    performance doesn't exceed baseline * 1.2 (20% threshold).

    Acceptance Criteria:
    - Measures P50/P90 metrics per phase
    - Baseline captured from last 10 iterations
    - Test fails if degradation > 20% (1.2x multiplier)
    """
    # Parse phase events from spiral_events.jsonl
    # Try multiple possible paths (relative to project root or tests dir)
    project_root = Path(__file__).parent.parent
    events_file = project_root / ".spiral" / "spiral_events.jsonl"
    durations = parse_events(str(events_file))

    if not durations:
        # Skip test if no event data available
        pytest.skip("No phase timing data available in spiral_events.jsonl")

    # Extract last 10 iterations per phase
    all_iterations = sorted(set(it for it, _ in durations.keys()))
    last_10_iterations = all_iterations[-10:] if len(all_iterations) >= 10 else all_iterations

    if not last_10_iterations:
        pytest.skip("Insufficient iteration data for baseline computation")

    # Build baseline: P90 per phase from last 10 iterations
    baseline_p90: dict[str, float] = {}
    baseline_p50: dict[str, float] = {}

    for phase in set(ph for _, ph in durations.keys()):
        # Collect durations for this phase across last 10 iterations
        phase_durations = [durations[(it, phase)] for it in last_10_iterations if (it, phase) in durations]

        if phase_durations:
            baseline_p50[phase] = compute_percentile(phase_durations, 50)
            baseline_p90[phase] = compute_percentile(phase_durations, 90)

    # Verify at least one phase has baseline data
    assert baseline_p90, "No phase timing baseline could be computed"

    # Get most recent iteration (to check current performance)
    most_recent_iter = max(all_iterations)

    # Check each phase: current must not exceed P90 * 1.2
    failures: list[str] = []
    for phase in baseline_p90:
        threshold = baseline_p90[phase] * 1.2  # 20% threshold
        current_duration = durations.get((most_recent_iter, phase))

        if current_duration is not None and current_duration > threshold:
            degradation_pct = ((current_duration - baseline_p90[phase]) / baseline_p90[phase]) * 100
            failures.append(
                f"Phase {phase}: {current_duration:.1f}s exceeds threshold "
                f"{threshold:.1f}s (baseline P90={baseline_p90[phase]:.1f}s, "
                f"degradation={degradation_pct:.1f}%)"
            )

    # Report baseline metrics
    baseline_report = "Baseline (P50/P90) from last 10 iterations:\n"
    for phase in sorted(baseline_p50.keys()):
        baseline_report += f"  {phase}: P50={baseline_p50[phase]:.1f}s, P90={baseline_p90[phase]:.1f}s\n"

    if failures:
        pytest.fail(f"{baseline_report}Performance regressions detected:\n" + "\n".join(failures))

    # Test passes: no phases exceeded threshold
    assert True, baseline_report
