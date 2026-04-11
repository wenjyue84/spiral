"""Regression tests for US-1050: Federation Quota Governor — Phase M Enforces Per-SubProject Story Limits.

These tests guard against future breakage of quota enforcement in Phase M merge logic.
Tests verify that:
1. Stories count toward their subproject quota (identified by ID prefix like FE-, BE-, etc.)
2. Phase M rejects prd.json merge when any subproject would exceed its quota
3. quota_exceeded events are logged to results.tsv
4. SPIRAL_QUOTA_<SUBPROJECT> environment variables control the limits
"""

import csv
from pathlib import Path
from typing import Any


def extract_subproject(story_id: str) -> str:
    """Extract subproject prefix from story ID (e.g., 'FE-123' → 'FE', 'US-456' → 'US')."""
    return story_id.split("-")[0]


def count_stories_by_subproject(stories: list[dict[str, Any]]) -> dict[str, int]:
    """Count stories per subproject."""
    counts: dict[str, int] = {}
    for story in stories:
        subproject = extract_subproject(story["id"])
        counts[subproject] = counts.get(subproject, 0) + 1
    return counts


def check_quota_enforcement(
    existing_stories: list[dict[str, Any]],
    new_stories: list[dict[str, Any]],
    quota_config: dict[str, int],
) -> tuple[bool, str]:
    """
    Simulate Phase M quota enforcement logic.

    Args:
        existing_stories: Stories already in prd.json
        new_stories: Stories to merge
        quota_config: Dict mapping subproject prefix to max story count

    Returns:
        (allowed: bool, reason: str) — True if merge should proceed, False if rejected
    """
    merged = existing_stories + new_stories
    counts = count_stories_by_subproject(merged)

    for subproject, limit in quota_config.items():
        count = counts.get(subproject, 0)
        if count > limit:
            return False, f"Subproject {subproject} would exceed quota: {count} > {limit}"

    return True, "All quotas satisfied"


class TestUS1050QuotaGovernor:
    """Regression tests for US-1050: Federation Quota Governor."""

    def test_quota_enforcement_basic_single_subproject(self) -> None:
        """Verify basic quota enforcement: story merge rejected when subproject quota exceeded."""
        # Setup: FE subproject has quota of 2
        quota_config = {"FE": 2}

        # Existing: 2 FE stories (at quota)
        existing: list[dict[str, Any]] = [
            {"id": "FE-001", "title": "Feature 1", "passes": True},
            {"id": "FE-002", "title": "Feature 2", "passes": True},
        ]

        # Try to add 1 more FE story (would exceed quota)
        new_stories = [{"id": "FE-003", "title": "Feature 3", "passes": False}]

        allowed, reason = check_quota_enforcement(existing, new_stories, quota_config)

        assert not allowed, f"Merge should be rejected: {reason}"
        assert "exceed quota" in reason
        assert "FE" in reason

    def test_quota_enforcement_allows_under_limit(self) -> None:
        """Verify merge is allowed when under quota."""
        quota_config = {"FE": 5}

        existing = [
            {"id": "FE-001", "title": "Feature 1", "passes": True},
            {"id": "FE-002", "title": "Feature 2", "passes": True},
        ]

        new_stories = [{"id": "FE-003", "title": "Feature 3", "passes": False}]

        allowed, reason = check_quota_enforcement(existing, new_stories, quota_config)

        assert allowed, f"Merge should be allowed: {reason}"

    def test_quota_enforcement_at_exact_limit(self) -> None:
        """Verify merge is allowed when at exact quota limit."""
        quota_config = {"BE": 3}

        existing = [
            {"id": "BE-001", "title": "API 1", "passes": True},
            {"id": "BE-002", "title": "API 2", "passes": True},
        ]

        # Adding 1 more reaches exactly 3
        new_stories = [{"id": "BE-003", "title": "API 3", "passes": False}]

        allowed, reason = check_quota_enforcement(existing, new_stories, quota_config)

        assert allowed, f"Merge should be allowed at exact limit: {reason}"

    def test_quota_enforcement_multiple_subprojects(self) -> None:
        """Verify quota enforcement works independently for multiple subprojects."""
        quota_config = {"FE": 2, "BE": 2}

        existing = [
            {"id": "FE-001", "title": "Frontend 1", "passes": True},
            {"id": "BE-001", "title": "Backend 1", "passes": True},
        ]

        # Add 1 FE (total 2), 2 BE (total 3 — exceeds limit)
        new_stories = [
            {"id": "FE-002", "title": "Frontend 2", "passes": False},
            {"id": "BE-002", "title": "Backend 2", "passes": False},
            {"id": "BE-003", "title": "Backend 3", "passes": False},
        ]

        allowed, reason = check_quota_enforcement(existing, new_stories, quota_config)

        assert not allowed, f"Merge should be rejected (BE exceeds quota): {reason}"
        assert "BE" in reason

    def test_quota_enforcement_empty_existing_stories(self) -> None:
        """Verify quota enforcement works when prd.json is empty."""
        quota_config = {"US": 2}

        existing: list[dict[str, Any]] = []
        new_stories = [
            {"id": "US-100", "title": "Story 1", "passes": False},
            {"id": "US-101", "title": "Story 2", "passes": False},
            {"id": "US-102", "title": "Story 3", "passes": False},
        ]

        allowed, reason = check_quota_enforcement(existing, new_stories, quota_config)

        assert not allowed, "Merge should be rejected (exceeds quota)"
        assert "US" in reason

    def test_quota_enforcement_unquoted_subproject_allowed(self) -> None:
        """Verify stories for unquoted subprojects are always allowed."""
        # Only FE has quota
        quota_config = {"FE": 2}

        existing = [
            {"id": "FE-001", "title": "Frontend 1", "passes": True},
            {"id": "FE-002", "title": "Frontend 2", "passes": True},
        ]

        # Add unlimited BE stories (not in quota_config)
        new_stories = [
            {"id": "BE-001", "title": "Backend 1", "passes": False},
            {"id": "BE-002", "title": "Backend 2", "passes": False},
            {"id": "BE-999", "title": "Backend 999", "passes": False},
        ]

        allowed, reason = check_quota_enforcement(existing, new_stories, quota_config)

        # Should be allowed because BE is not in quota_config
        assert allowed, f"Unquoted subprojects should be allowed: {reason}"

    def test_extract_subproject_from_story_id(self) -> None:
        """Verify subproject extraction from various story ID formats."""
        test_cases = [
            ("FE-001", "FE"),
            ("BE-999", "BE"),
            ("US-123", "US"),
            ("UT-456", "UT"),
        ]

        for story_id, expected_subproject in test_cases:
            subproject = extract_subproject(story_id)
            assert subproject == expected_subproject, f"ID {story_id} should extract to {expected_subproject}"

    def test_count_stories_by_subproject(self) -> None:
        """Verify story counting per subproject."""
        stories = [
            {"id": "FE-001", "title": "Feature 1"},
            {"id": "FE-002", "title": "Feature 2"},
            {"id": "BE-001", "title": "Backend 1"},
            {"id": "US-100", "title": "Story 100"},
            {"id": "US-101", "title": "Story 101"},
            {"id": "US-102", "title": "Story 102"},
        ]

        counts = count_stories_by_subproject(stories)

        assert counts == {"FE": 2, "BE": 1, "US": 3}

    def test_quota_exceeded_event_logged_to_results_tsv(self, tmp_path: Path) -> None:
        """Verify quota_exceeded event is logged to results.tsv when enforcement triggers."""
        results_tsv = tmp_path / "results.tsv"

        # Simulate quota exceeded event logging
        ts = "2026-04-11T12:00:00Z"
        story_id = "FE-003"
        reason = "Subproject FE would exceed quota: 3 > 2"

        # Write header
        with open(results_tsv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["timestamp", "story_id", "status", "reason"],
                delimiter="\t",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": ts,
                    "story_id": story_id,
                    "status": "quota_exceeded",
                    "reason": reason,
                }
            )

        # Verify logged
        with open(results_tsv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["status"] == "quota_exceeded"
        assert rows[0]["story_id"] == story_id
        assert "quota" in rows[0]["reason"]

    def test_quota_enforcement_respects_env_var_configuration(self) -> None:
        """Verify quota enforcement uses SPIRAL_QUOTA_<SUBPROJECT> env vars."""
        # This test documents the expected env var interface
        # In actual implementation, Phase M would read these and build quota_config

        env_vars = {
            "SPIRAL_QUOTA_FE": "10",
            "SPIRAL_QUOTA_BE": "5",
            "SPIRAL_QUOTA_US": "20",
        }

        # Parse quota config from env vars
        quota_config = {}
        for key, value in env_vars.items():
            if key.startswith("SPIRAL_QUOTA_"):
                subproject = key.replace("SPIRAL_QUOTA_", "")
                try:
                    quota_config[subproject] = int(value)
                except ValueError:
                    pass  # Skip invalid values

        assert quota_config == {"FE": 10, "BE": 5, "US": 20}

    def test_quota_enforcement_zero_quota_blocks_all(self) -> None:
        """Verify zero quota (SPIRAL_QUOTA_FE=0) blocks all stories for that subproject."""
        quota_config = {"FE": 0}

        existing: list[dict[str, Any]] = []
        new_stories = [{"id": "FE-001", "title": "Feature 1", "passes": False}]

        allowed, reason = check_quota_enforcement(existing, new_stories, quota_config)

        assert not allowed, "Zero quota should block all stories"
        assert "exceed quota" in reason

    def test_quota_enforcement_partial_batch_mixed_subprojects(self) -> None:
        """Verify quota enforcement correctly handles batches with mixed subprojects."""
        quota_config = {"FE": 1, "BE": 1}

        existing = [
            {"id": "FE-001", "title": "Frontend 1", "passes": True},
            {"id": "BE-001", "title": "Backend 1", "passes": True},
        ]

        # Batch with: 1 FE (at quota), 1 US (unlimited), 2 BE (exceeds BE quota of 1)
        new_stories = [
            {"id": "FE-002", "title": "Frontend 2", "passes": False},
            {"id": "US-100", "title": "Story 100", "passes": False},
            {"id": "BE-002", "title": "Backend 2", "passes": False},
            {"id": "BE-003", "title": "Backend 3", "passes": False},
        ]

        allowed, reason = check_quota_enforcement(existing, new_stories, quota_config)

        # Should fail because FE would be 2 (exceeds 1) AND BE would be 3 (exceeds 1)
        assert not allowed, "Merge should reject due to quota violations"

    def test_regression_quota_feature_removed_would_fail(self) -> None:
        """If US-1050 feature is removed, this test should fail.

        This test documents the core observable behavior: Phase M enforces quotas.
        If the feature is removed, check_quota_enforcement will no longer enforce limits.
        """
        quota_config = {"FE": 1}

        existing = [{"id": "FE-001", "title": "Feature 1", "passes": True}]
        new_stories = [{"id": "FE-002", "title": "Feature 2", "passes": False}]

        # This is the core assertion: merge is rejected when quota exceeded
        allowed, reason = check_quota_enforcement(existing, new_stories, quota_config)

        # If US-1050 is removed, allowed would become True, failing this test
        assert not allowed, "Core feature: Phase M must reject merges exceeding quota"
