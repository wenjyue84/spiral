#!/usr/bin/env python3
"""Tests for lib/profile_trace.py and lib/spiral_events_reader.py."""

import json

import pytest

from lib.profile_trace import analyze_trace, export_trace
from lib.spiral_events_reader import read_results_tsv, unify_trace_data


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project with sample trace data."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    # Create results.tsv
    results_tsv = project_root / "results.tsv"
    hdr = "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\twall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\n"  # noqa: E501
    row1 = "2026-05-15T10:00:00Z\t1\t1\tUS-001\tTest Story 1\tpass\t100.5\thaiku\t0\tabc123\trun1\ttrue\t1000\t100\t0\t0\t0\t0\t0\t\n"  # noqa: E501
    row2 = "2026-05-15T10:05:00Z\t1\t2\tUS-002\tTest Story 2\tpass\t200.0\tsonnet\t1\tabc123\trun1\ttrue\t2000\t200\t0\t0\t0\t0\t0\t\n"  # noqa: E501
    results_content = hdr + row1 + row2
    results_tsv.write_text(results_content)

    # Create .spiral directory
    spiral_dir = project_root / ".spiral"
    spiral_dir.mkdir()

    # Create a mock worker log
    worker_log = spiral_dir / "worker-1.log"
    wlog_data = '{"iteration": 1, "worker_id": "1", "phase": "I", "start_unix_ms": 1715767200000, "duration_ms": 150, "status": "success"}\n'  # noqa: E501
    worker_log.write_text(wlog_data)

    return project_root


def test_read_results_tsv(tmp_project):
    """Test reading results.tsv."""
    results_path = tmp_project / "results.tsv"
    rows = read_results_tsv(str(results_path))

    assert len(rows) == 2
    assert rows[0]["story_id"] == "US-001"
    assert rows[0]["spiral_iter"] == 1
    assert rows[0]["duration_sec"] == 100.5
    assert rows[0]["retry_num"] == 0

    assert rows[1]["story_id"] == "US-002"
    assert rows[1]["duration_sec"] == 200.0
    assert rows[1]["retry_num"] == 1


def test_unify_trace_data(tmp_project):
    """Test unifying trace data from multiple sources."""
    results_path = tmp_project / "results.tsv"
    results_data = read_results_tsv(str(results_path))

    unified = unify_trace_data([], results_data, [])

    assert len(unified) == 2
    assert unified[0]["story_id"] == "US-001"
    assert unified[0]["iteration"] == 1
    assert unified[0]["escalation_count"] == 0

    assert unified[1]["escalation_count"] == 1


def test_export_trace_stdout(tmp_project, capsys):
    """Test exporting trace to stdout."""
    export_trace(
        from_iteration=1,
        to_iteration=1,
        output=None,
        project_root=str(tmp_project),
    )

    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")

    assert len(lines) >= 2
    for line in lines:
        if line:
            data = json.loads(line)
            assert "iteration" in data
            assert "status" in data


def test_export_trace_with_all_phases(tmp_project):
    """Test exporting trace with multiple phase sources."""
    output_file = tmp_project / "trace.jsonl"

    export_trace(
        output=str(output_file),
        project_root=str(tmp_project),
    )

    assert output_file.exists()
    with open(output_file) as f:
        lines = f.readlines()

    assert len(lines) >= 2
    for line in lines:
        data = json.loads(line)
        assert "iteration" in data
        assert "status" in data


def test_export_trace_with_iteration_filter(tmp_project):
    """Test exporting trace with iteration filter."""
    output_file = tmp_project / "trace_iter1.jsonl"

    export_trace(
        from_iteration=1,
        to_iteration=1,
        output=str(output_file),
        project_root=str(tmp_project),
    )

    assert output_file.exists()
    with open(output_file) as f:
        lines = f.readlines()

    for line in lines:
        data = json.loads(line)
        assert data["iteration"] == 1


def test_analyze_trace_empty_file(tmp_path, capsys):
    """Test analyzing empty trace file."""
    trace_file = tmp_path / "empty_trace.jsonl"
    trace_file.write_text("")

    analyze_trace(str(trace_file))
    captured = capsys.readouterr()

    assert "No trace entries found" in captured.out


def test_analyze_trace_with_data(tmp_project, capsys):
    """Test analyzing trace file with actual data."""
    output_file = tmp_project / "trace.jsonl"
    export_trace(
        output=str(output_file),
        project_root=str(tmp_project),
    )

    analyze_trace(str(output_file))
    captured = capsys.readouterr()

    assert "Phase Statistics" in captured.out
    assert "Count" in captured.out
    assert "Median Dur" in captured.out


def test_analyze_trace_nonexistent_file(capsys):
    """Test analyzing nonexistent trace file."""
    with pytest.raises(SystemExit) as exc:
        analyze_trace("/nonexistent/trace.jsonl")

    assert exc.value.code == 1
