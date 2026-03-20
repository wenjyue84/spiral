#!/usr/bin/env python3
"""test_dashboard_profile.py — Integration tests for /profile endpoint."""

from fastapi.testclient import TestClient

from lib.dashboard.api import app


def test_profile_endpoint_returns_200():
    """Test /profile endpoint returns HTTP 200."""
    client = TestClient(app)
    response = client.get("/profile")
    assert response.status_code == 200


def test_profile_returns_correct_json_structure():
    """Test /profile returns JSON with correct keys."""
    client = TestClient(app)
    response = client.get("/profile")
    data = response.json()

    assert "mean_phase_durations" in data
    assert "slowest_stories" in data
    assert "escalation_frequency" in data


def test_profile_mean_phase_durations_has_required_keys():
    """Test mean_phase_durations has decompose_secs, impl_secs, verify_secs."""
    client = TestClient(app)
    response = client.get("/profile")
    data = response.json()

    mean_phases = data["mean_phase_durations"]
    assert "decompose_secs" in mean_phases
    assert "impl_secs" in mean_phases
    assert "verify_secs" in mean_phases

    # Verify they are numeric
    assert isinstance(mean_phases["decompose_secs"], (int, float))
    assert isinstance(mean_phases["impl_secs"], (int, float))
    assert isinstance(mean_phases["verify_secs"], (int, float))
