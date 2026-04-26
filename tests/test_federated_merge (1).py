"""test_federated_merge.py — Tests for federated_merge() namespace-aware deduplication."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.impl.federated_merge import federated_merge
from lib.impl.phase_m_federated_order import order_federated_stories_by_dependency


def test_namespace_isolation() -> None:
    """Test that same ID from different namespaces are accepted; same-namespace duplicates are rejected."""
    stories = [
        {"id": "PROJ1/US-100", "title": "Story in PROJ1"},
        {"id": "PROJ2/US-100", "title": "Story in PROJ2"},
        {"id": "PROJ1/US-100", "title": "Duplicate in PROJ1"},
    ]

    accepted, rejected, errors = federated_merge(stories)

    # PROJ1/US-100 and PROJ1/US-100 should collide and be rejected
    assert len(rejected) == 2, f"Expected 2 rejected (PROJ1/US-100 duplicates), got {len(rejected)}"
    assert all(s["id"] == "PROJ1/US-100" for s in rejected), "Rejected stories should both be PROJ1/US-100"

    # PROJ2/US-100 should be accepted (different namespace)
    assert len(accepted) == 1, f"Expected 1 accepted (PROJ2/US-100), got {len(accepted)}"
    assert accepted[0]["id"] == "PROJ2/US-100"

    # Error log should mention the conflict
    assert len(errors) == 1, f"Expected 1 error, got {len(errors)}"
    assert "PROJ1/US-100" in errors[0], "Error should mention the conflicting ID"
    assert "appears 2 times" in errors[0], "Error should mention count of duplicates"


def test_phase_m_integration() -> None:
    """Test that order_federated_stories_by_dependency calls federated_merge and handles rejections."""
    # Load the multi-project fixture
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "federated_prd_multi_project.json"
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"

    with open(fixture_path, encoding="utf-8") as f:
        fixture_data = json.load(f)

    stories = fixture_data.get("userStories", [])
    assert len(stories) == 3, f"Expected 3 stories in fixture, got {len(stories)}"

    # Call order_federated_stories_by_dependency which should deduplicate then sort
    result = order_federated_stories_by_dependency(stories)

    # After dedup, only 1 story should remain (both PROJ1/US-100 instances rejected, PROJ2/US-100 accepted)
    assert len(result) == 1, f"Expected 1 story after dedup, got {len(result)}"

    # Verify that PROJ1/US-100 duplicates were rejected (neither PROJ1/US-100 in result)
    proj1_stories = [s for s in result if s["id"] == "PROJ1/US-100"]
    assert len(proj1_stories) == 0, "Both PROJ1/US-100 instances should be rejected due to duplicates"

    # Verify PROJ2/US-100 is present (only story that should remain)
    proj2_stories = [s for s in result if s["id"] == "PROJ2/US-100"]
    assert len(proj2_stories) == 1, "PROJ2/US-100 should be accepted (unique)"
    assert proj2_stories[0]["title"] == "Story in project 2"
