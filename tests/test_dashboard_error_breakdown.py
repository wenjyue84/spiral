#!/usr/bin/env python3
"""test_dashboard_error_breakdown.py — Tests for /api/dashboard/error-breakdown endpoint."""

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lib.dashboard.api import app


def test_error_breakdown_returns_200() -> None:
    """Endpoint returns HTTP 200."""
    client = TestClient(app)
    response = client.get("/api/dashboard/error-breakdown")
    assert response.status_code == 200


def test_error_breakdown_returns_correct_structure() -> None:
    """Response has phases, total_errors, iterations_filter keys."""
    client = TestClient(app)
    data = client.get("/api/dashboard/error-breakdown").json()
    assert "phases" in data
    assert "total_errors" in data
    assert "iterations_filter" in data
    assert isinstance(data["phases"], dict)
    assert isinstance(data["total_errors"], int)


def test_error_breakdown_default_iterations_filter() -> None:
    """Default filter is last_n with n=5."""
    client = TestClient(app)
    data = client.get("/api/dashboard/error-breakdown").json()
    assert data["iterations_filter"] == {"mode": "last_n", "n": 5}


def test_error_breakdown_custom_iterations() -> None:
    """Custom iterations parameter reflected in filter."""
    client = TestClient(app)
    data = client.get("/api/dashboard/error-breakdown?iterations=3").json()
    assert data["iterations_filter"] == {"mode": "last_n", "n": 3}


def test_error_breakdown_single_iteration_filter() -> None:
    """Single iteration filter mode."""
    client = TestClient(app)
    data = client.get("/api/dashboard/error-breakdown?iteration=2").json()
    assert data["iterations_filter"] == {"mode": "single", "iteration": 2}


def test_error_breakdown_invalid_iteration_returns_422() -> None:
    """iteration=0 returns 422."""
    client = TestClient(app)
    resp = client.get("/api/dashboard/error-breakdown?iteration=0")
    assert resp.status_code == 422


def test_error_breakdown_invalid_iterations_returns_422() -> None:
    """iterations=0 returns 422."""
    client = TestClient(app)
    resp = client.get("/api/dashboard/error-breakdown?iterations=0")
    assert resp.status_code == 422


def test_error_breakdown_with_tsv_data(tmp_path: Path) -> None:
    """Endpoint parses results.tsv and returns phase/category aggregation with story IDs."""
    tsv_content = textwrap.dedent("""\
        timestamp\tspiral_iter\tstory_id\tstatus\tmodel\tphase\terror_type
        2026-03-20T00:00:00\t1\tUS-101\tfailed\thaiku\tI\ttimeout
        2026-03-20T00:01:00\t1\tUS-102\tfailed\tsonnet\tI\tmodel_error
        2026-03-20T00:02:00\t1\tUS-103\tfailed\thaiku\tR\toom
        2026-03-20T00:03:00\t1\tUS-104\tkeep\thaiku\tI\t
        2026-03-20T00:04:00\t1\tUS-101\tfailed\thaiku\tI\ttimeout
    """)
    tsv_file = tmp_path / ".spiral" / "results.tsv"
    tsv_file.parent.mkdir(parents=True)
    tsv_file.write_text(tsv_content, encoding="utf-8")

    client = TestClient(app)
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        data = client.get("/api/dashboard/error-breakdown?iterations=5").json()
    finally:
        os.chdir(old_cwd)

    assert data["total_errors"] == 4
    assert "I" in data["phases"]
    assert data["phases"]["I"]["timeout"] == 2
    assert data["phases"]["I"]["model_error"] == 1
    assert "R" in data["phases"]
    assert data["phases"]["R"]["oom"] == 1

    # Verify story_ids are included
    assert "story_ids" in data
    assert "US-101" in data["story_ids"]["I"]["timeout"]
    assert "US-102" in data["story_ids"]["I"]["model_error"]
    assert "US-103" in data["story_ids"]["R"]["oom"]


def test_error_breakdown_story_ids_deduplicated(tmp_path: Path) -> None:
    """Same story failing twice in same phase/category appears only once in story_ids."""
    tsv_content = textwrap.dedent("""\
        timestamp\tspiral_iter\tstory_id\tstatus\tmodel\tphase\terror_type
        2026-03-20T00:00:00\t1\tUS-101\tfailed\thaiku\tI\ttimeout
        2026-03-20T00:01:00\t1\tUS-101\tfailed\tsonnet\tI\ttimeout
    """)
    tsv_file = tmp_path / ".spiral" / "results.tsv"
    tsv_file.parent.mkdir(parents=True)
    tsv_file.write_text(tsv_content, encoding="utf-8")

    client = TestClient(app)
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        data = client.get("/api/dashboard/error-breakdown").json()
    finally:
        os.chdir(old_cwd)

    assert data["story_ids"]["I"]["timeout"] == ["US-101"]
    assert data["total_errors"] == 2
