"""costs.py — Parse results.tsv and compute cost breakdown metrics.

Provides:
- parse_costs_from_results_tsv(results_path) → dict with cost metrics
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Per-token cost rates by model family (same as in api.py)
_PHASE_COST_RATE: dict[str, float] = {"haiku": 2.5e-7, "sonnet": 3e-6, "opus": 1.5e-5}


def parse_costs_from_results_tsv(results_path: str) -> dict[str, Any]:
    """Parse results.tsv and return cost breakdown metrics.

    Args:
        results_path: Path to results.tsv file (typically "results.tsv" or ".spiral/results.tsv")

    Returns:
        dict with keys:
        - phases: dict keyed by phase letter (empty dict if no phase data available)
        - total_tokens: sum of cache_read_tokens + cache_creation_tokens + review_tokens
        - total_cost_usd: total estimated USD cost
        - spend_rate_per_story: average cost per story
        - iteration_count: number of unique spiral_iter values

        Returns empty/zero values if results.tsv is missing or empty.
    """
    file_path = Path(results_path)

    # Default response for missing/empty file
    default_response = {
        "phases": {},
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "spend_rate_per_story": 0.0,
        "iteration_count": 0,
    }

    if not file_path.exists():
        return default_response

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if len(lines) < 2:
            return default_response

        # Parse header
        header_line = lines[0].strip()
        headers = header_line.split("\t")

        # Find column indices
        try:
            cache_read_idx = headers.index("cache_read_tokens")
            cache_creation_idx = headers.index("cache_creation_tokens")
            review_idx = headers.index("review_tokens")
            model_idx = headers.index("model")
            spiral_iter_idx = headers.index("spiral_iter")
        except ValueError:
            return default_response

        # Parse data rows
        total_tokens = 0
        total_cost = 0.0
        iterations_set: set[str] = set()
        story_count = 0

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue

            parts = line.split("\t")
            story_count += 1

            # Extract tokens
            try:
                cache_read = int(parts[cache_read_idx] or 0)
            except (ValueError, IndexError):
                cache_read = 0

            try:
                cache_creation = int(parts[cache_creation_idx] or 0)
            except (ValueError, IndexError):
                cache_creation = 0

            try:
                review = int(parts[review_idx] or 0)
            except (ValueError, IndexError):
                review = 0

            tokens = cache_read + cache_creation + review
            total_tokens += tokens

            # Extract model and compute cost
            try:
                model = (parts[model_idx] or "haiku").lower()
            except IndexError:
                model = "haiku"

            # Extract model base name (e.g., "sonnet-4-6" -> "sonnet")
            model_base = model.split("-")[0]
            rate = _PHASE_COST_RATE.get(model_base, _PHASE_COST_RATE["haiku"])
            total_cost += tokens * rate

            # Track iterations
            try:
                iter_num = parts[spiral_iter_idx].strip()
                if iter_num:
                    iterations_set.add(iter_num)
            except IndexError:
                pass

        # Compute metrics
        iteration_count = len(iterations_set)
        spend_rate_per_story = total_cost / max(story_count, 1)

        return {
            "phases": {},  # No per-phase breakdown available in results.tsv
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "spend_rate_per_story": round(spend_rate_per_story, 6),
            "iteration_count": iteration_count,
        }

    except (OSError, IOError):
        return default_response
    except Exception:
        # Catch any unexpected parsing errors and return defaults
        return default_response
