"""test_federated_merge.py — Tests for federated_merge() namespace-aware deduplication."""

from __future__ import annotations

import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.impl.federated_merge import federated_merge


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
