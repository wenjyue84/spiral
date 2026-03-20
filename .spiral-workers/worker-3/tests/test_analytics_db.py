"""Tests for lib/analytics_db.py — DuckDB read layer over flat files."""

import json
import os
import tempfile

import pytest

from lib.analytics_db import AnalyticsDB


@pytest.fixture
def project_dir(tmp_path):
    """Create a minimal SPIRAL project directory with test data."""
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir()

    # results.tsv
    results = tmp_path / "results.tsv"
    results.write_text(
        "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
        "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit\t"
        "cache_read_tokens\tcache_creation_tokens\treview_tokens\twall_seconds\t"
        "user_cpu_s\tsys_cpu_s\tpeak_rss_kb\n"
        "2026-03-18T10:00:00Z\t1\t0\tUS-001\tAdd login\tpass\t120\tclaude-sonnet-4-6\t0\tabc123\trun-1\t0\t0\t0\t0\t130\t5\t2\t512000\n"
        "2026-03-18T10:05:00Z\t1\t0\tUS-002\tAdd logout\tfail\t60\tclaude-haiku-4-5\t0\tdef456\trun-1\t0\t0\t0\t0\t65\t3\t1\t256000\n"
        "2026-03-18T10:10:00Z\t1\t1\tUS-002\tAdd logout\tpass\t90\tclaude-sonnet-4-6\t1\tghi789\trun-1\t1\t500\t0\t0\t95\t4\t1\t300000\n"
        "2026-03-18T11:00:00Z\t2\t0\tUS-003\tDashboard\tkeep\t200\tclaude-opus-4-6\t0\tjkl012\trun-1\t0\t0\t0\t0\t210\t8\t3\t800000\n",
        encoding="utf-8",
    )

    # spiral_events.jsonl
    events = spiral_dir / "spiral_events.jsonl"
    events.write_text(
        json.dumps({"ts": "2026-03-18T10:00:00Z", "event": "phase_start", "phase": "R"}) + "\n"
        + json.dumps({"ts": "2026-03-18T10:01:00Z", "event": "phase_end", "phase": "R"}) + "\n"
        + json.dumps({"ts": "2026-03-18T10:02:00Z", "event": "route_story_assigned", "story_id": "US-001", "model_tier": "sonnet"}) + "\n"
        + json.dumps({"ts": "2026-03-18T10:03:00Z", "event": "phase_start", "phase": "I"}) + "\n",
        encoding="utf-8",
    )

    # calibration.jsonl
    cal = tmp_path / "calibration.jsonl"
    cal.write_text(
        json.dumps({"story_id": "US-001", "estimated_complexity": "small", "actual_duration_s": 120, "passed": True}) + "\n"
        + json.dumps({"story_id": "US-002", "estimated_complexity": "small", "actual_duration_s": 150, "passed": True}) + "\n"
        + json.dumps({"story_id": "US-003", "estimated_complexity": "medium", "actual_duration_s": 200, "passed": True}) + "\n",
        encoding="utf-8",
    )

    # prd.json
    prd = tmp_path / "prd.json"
    prd.write_text(
        json.dumps({
            "userStories": [
                {"id": "US-001", "title": "Add login", "passes": True, "estimatedComplexity": "small"},
                {"id": "US-002", "title": "Add logout", "passes": True, "estimatedComplexity": "small"},
                {"id": "US-003", "title": "Dashboard", "passes": False, "estimatedComplexity": "medium"},
            ]
        }),
        encoding="utf-8",
    )

    return str(tmp_path)


def test_overview(project_dir):
    db = AnalyticsDB(project_dir)
    overview = db.overview()
    assert overview["total_attempts"] == 4
    assert overview["iterations"] == 2
    assert overview["passes"] == 3  # pass + keep
    assert overview["failures"] == 1
    db.close()


def test_model_performance(project_dir):
    db = AnalyticsDB(project_dir)
    perf = db.model_performance()
    assert len(perf) == 3
    models = {r["model"] for r in perf}
    assert "claude-sonnet-4-6" in models
    assert "claude-haiku-4-5" in models
    assert "claude-opus-4-6" in models
    db.close()


def test_retry_analysis(project_dir):
    db = AnalyticsDB(project_dir)
    retries = db.retry_analysis()
    assert len(retries) == 2  # retry 0 and retry 1
    retry_0 = next(r for r in retries if r["retry"] == 0)
    assert retry_0["attempts"] == 3
    db.close()


def test_iteration_velocity(project_dir):
    db = AnalyticsDB(project_dir)
    vel = db.iteration_velocity()
    assert len(vel) == 2  # iterations 1 and 2
    iter1 = next(v for v in vel if v["iteration"] == 1)
    assert iter1["total_attempts"] == 3
    db.close()


def test_bottlenecks(project_dir):
    db = AnalyticsDB(project_dir)
    bots = db.bottlenecks(top_n=5)
    # US-002 has most attempts (2)
    assert bots[0]["story_id"] == "US-002"
    assert bots[0]["attempts"] == 2
    db.close()


def test_cost_by_model(project_dir):
    db = AnalyticsDB(project_dir)
    costs = db.cost_by_model()
    assert len(costs) == 3
    # Opus should be most expensive per hour
    opus = next(c for c in costs if c["model"] == "claude-opus-4-6")
    assert opus["estimated_cost_usd"] > 0
    db.close()


def test_event_counts_by_type(project_dir):
    db = AnalyticsDB(project_dir)
    counts = db.event_counts_by_type()
    assert len(counts) == 3  # phase_start, phase_end, route_story_assigned
    phase_starts = next(c for c in counts if c["event"] == "phase_start")
    assert phase_starts["count"] == 2
    db.close()


def test_calibration_report(project_dir):
    db = AnalyticsDB(project_dir)
    report = db.calibration_report()
    assert len(report) > 0
    assert "small" in {r["estimated_complexity"] for r in report}
    db.close()


def test_stories_with_results(project_dir):
    db = AnalyticsDB(project_dir)
    rows = db.stories_with_results()
    assert len(rows) == 3
    us1 = next(r for r in rows if r["id"] == "US-001")
    assert us1["passes"] is True
    db.close()


def test_custom_query(project_dir):
    db = AnalyticsDB(project_dir)
    rows = db.query("SELECT story_id, count(*) as n FROM results GROUP BY story_id ORDER BY n DESC")
    assert rows[0]["story_id"] == "US-002"
    assert rows[0]["n"] == 2
    db.close()


def test_refresh(project_dir):
    db = AnalyticsDB(project_dir)
    initial = db.overview()

    # Append a new row
    with open(os.path.join(project_dir, "results.tsv"), "a", encoding="utf-8") as f:
        f.write("2026-03-18T12:00:00Z\t3\t0\tUS-004\tNew feature\tpass\t100\tclaude-sonnet-4-6\t0\txyz\trun-2\t0\t0\t0\t0\t110\t5\t2\t400000\n")

    db.refresh()
    updated = db.overview()
    assert updated["total_attempts"] == initial["total_attempts"] + 1
    db.close()


def test_empty_project():
    """AnalyticsDB should work with no data files."""
    with tempfile.TemporaryDirectory() as tmp:
        spiral_dir = os.path.join(tmp, ".spiral")
        os.makedirs(spiral_dir)
        db = AnalyticsDB(tmp)
        overview = db.overview()
        assert overview.get("total_attempts") is None or overview["total_attempts"] == 0
        db.close()


def test_resource_usage_percentiles(project_dir):
    db = AnalyticsDB(project_dir)
    usage = db.resource_usage_percentiles()
    assert len(usage) > 0
    sonnet = next((u for u in usage if u["model"] == "claude-sonnet-4-6"), None)
    assert sonnet is not None
    assert sonnet["wall_p50"] > 0
    db.close()
