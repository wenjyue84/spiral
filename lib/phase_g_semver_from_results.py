"""lib/phase_g_semver_from_results.py — Phase G SemVer Calculation from results.tsv.

Calculates semantic version bumps based on story retry counts from results.tsv.
This is used to determine version bumps when stories encounter implementation challenges.

Rules (deterministic, pure function):
  - 2+ stories with retry_count >= 3 -> bump minor, reset patch
  - Otherwise (0-1 stories with retry_count >= 3) -> bump patch

Usage:
    from phase_g_semver_from_results import calculate_version_from_results_tsv
    next_ver = calculate_version_from_results_tsv("1.2.3", "results.tsv")
"""

from __future__ import annotations

import csv
from pathlib import Path


def _parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse a semver version string into (major, minor, patch).

    Args:
        version_str: Version string like "1.2.3" (with or without 'v' prefix)

    Returns:
        Tuple of (major, minor, patch) as integers

    Raises:
        ValueError: If version string doesn't match X.Y.Z format
    """
    v = version_str.lstrip("v")
    try:
        parts = v.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid version format: {version_str}")
        return int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError) as e:
        raise ValueError(f"Invalid version format: {version_str}") from e


def calculate_version_from_results_tsv(
    previous_version: str,
    results_tsv_path: str | Path,
) -> str:
    """Calculate next semver version based on results.tsv retry counts.

    Pure function: deterministic given the same inputs.

    Rules:
      - Count stories with retry_count >= 3
      - If 2+ such stories -> bump minor, reset patch
      - Otherwise -> bump patch

    Args:
        previous_version: Previous version string (e.g. "1.2.3" or "v1.2.3")
        results_tsv_path: Path to results.tsv file

    Returns:
        Next version string without 'v' prefix (e.g. "1.3.0" or "1.2.4")

    Raises:
        ValueError: If version format invalid or TSV file not found
        OSError: If TSV file cannot be read
    """
    major, minor, patch = _parse_version(previous_version)

    # Read results.tsv and count stories with retry_count >= 3
    tsv_path = Path(results_tsv_path)
    if not tsv_path.exists():
        raise ValueError(f"results.tsv not found: {results_tsv_path}")

    high_retry_stories: set[str] = set()

    with open(tsv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError("results.tsv is empty or invalid")

        for row in reader:
            try:
                retry_count = int(row.get("retry_num", 0) or 0)
                story_id = row.get("story_id", "")
                if retry_count >= 3 and story_id:
                    high_retry_stories.add(story_id)
            except (ValueError, TypeError):
                # Skip rows with invalid retry_num
                continue

    # Apply bump rules
    if len(high_retry_stories) >= 2:
        # Minor bump: 2+ stories with retry_count >= 3
        return f"{major}.{minor + 1}.0"
    else:
        # Patch bump: 0-1 stories with retry_count >= 3
        return f"{major}.{minor}.{patch + 1}"
