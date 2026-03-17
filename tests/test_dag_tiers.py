#!/usr/bin/env python3
"""Tests for DAG tier assignment (US-361)."""

import json
import sys
import os
import tempfile
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from check_dag import compute_tiers, find_cycles


def test_compute_tiers_no_deps():
    """Stories with no dependencies should be in tier 0."""
    stories = [
        {"id": "US-1", "title": "Story 1", "dependencies": [], "passes": False},
        {"id": "US-2", "title": "Story 2", "dependencies": [], "passes": False},
    ]
    tiers = compute_tiers(stories, set())
    assert tiers["US-1"] == 0
    assert tiers["US-2"] == 0


def test_compute_tiers_linear_chain():
    """US-2 depends on US-1 should be in tier 1."""
    stories = [
        {"id": "US-1", "title": "Story 1", "dependencies": [], "passes": False},
        {"id": "US-2", "title": "Story 2", "dependencies": ["US-1"], "passes": False},
        {"id": "US-3", "title": "Story 3", "dependencies": ["US-2"], "passes": False},
    ]
    tiers = compute_tiers(stories, set())
    assert tiers["US-1"] == 0
    assert tiers["US-2"] == 1
    assert tiers["US-3"] == 2


def test_compute_tiers_wide_tier():
    """Multiple stories can be in the same tier."""
    stories = [
        {"id": "US-1", "title": "Story 1", "dependencies": [], "passes": False},
        {"id": "US-2", "title": "Story 2", "dependencies": [], "passes": False},
        {"id": "US-3", "title": "Story 3", "dependencies": ["US-1"], "passes": False},
        {"id": "US-4", "title": "Story 4", "dependencies": ["US-2"], "passes": False},
    ]
    tiers = compute_tiers(stories, set())
    assert tiers["US-1"] == 0
    assert tiers["US-2"] == 0
    assert tiers["US-3"] == 1
    assert tiers["US-4"] == 1


def test_compute_tiers_diamond():
    """Diamond dependency: US-3, US-4 both depend on US-1, US-2 depends on both."""
    stories = [
        {"id": "US-1", "title": "Story 1", "dependencies": [], "passes": False},
        {"id": "US-2", "title": "Story 2", "dependencies": ["US-1"], "passes": False},
        {"id": "US-3", "title": "Story 3", "dependencies": ["US-1", "US-2"], "passes": False},
    ]
    tiers = compute_tiers(stories, set())
    assert tiers["US-1"] == 0
    assert tiers["US-2"] == 1
    assert tiers["US-3"] == 2


def test_compute_tiers_ignores_passed_stories():
    """Dependencies on passed stories don't count."""
    stories = [
        {"id": "US-1", "title": "Story 1", "dependencies": [], "passes": True},
        {"id": "US-2", "title": "Story 2", "dependencies": ["US-1"], "passes": False},
    ]
    # US-1 is already passed, so US-2 has no pending dependencies
    tiers = compute_tiers(stories, {"US-1"})
    assert tiers["US-2"] == 0  # No pending deps, so tier 0


def test_compute_tiers_invalid_dep():
    """Dependencies on non-existent stories are ignored."""
    stories = [
        {"id": "US-1", "title": "Story 1", "dependencies": ["NONEXISTENT"], "passes": False},
    ]
    tiers = compute_tiers(stories, set())
    assert tiers["US-1"] == 0  # Invalid dep ignored


def test_compute_tiers_complex():
    """Complex graph with multiple tiers."""
    stories = [
        {"id": "US-1", "title": "S1", "dependencies": [], "passes": False},
        {"id": "US-2", "title": "S2", "dependencies": [], "passes": False},
        {"id": "US-3", "title": "S3", "dependencies": ["US-1"], "passes": False},
        {"id": "US-4", "title": "S4", "dependencies": ["US-2"], "passes": False},
        {"id": "US-5", "title": "S5", "dependencies": ["US-3", "US-4"], "passes": False},
        {"id": "US-6", "title": "S6", "dependencies": [], "passes": False},
    ]
    tiers = compute_tiers(stories, set())
    # Tier 0: US-1, US-2, US-6 (no deps)
    # Tier 1: US-3, US-4 (depend on tier 0)
    # Tier 2: US-5 (depends on tier 1)
    assert tiers["US-1"] == 0
    assert tiers["US-2"] == 0
    assert tiers["US-6"] == 0
    assert tiers["US-3"] == 1
    assert tiers["US-4"] == 1
    assert tiers["US-5"] == 2


def test_dag_cycle_detection():
    """Circular dependencies should be detected."""
    stories = [
        {"id": "US-1", "title": "S1", "dependencies": ["US-2"], "passes": False},
        {"id": "US-2", "title": "S2", "dependencies": ["US-1"], "passes": False},
    ]
    cycles = find_cycles(stories)
    assert "US-1" in cycles
    assert "US-2" in cycles


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
