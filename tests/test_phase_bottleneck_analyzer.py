import json

import pytest

from lib.phase_bottleneck_analyzer import PhaseBottleneckAnalyzer


@pytest.fixture
def tmp_results_jsonl(tmp_path):
    """Create a sample results.jsonl file with 5 iterations and 3 phases."""
    results_file = tmp_path / "results.jsonl"
    data = [
        {"phase": "A", "iteration": 1, "duration_sec": 45.2},
        {"phase": "R", "iteration": 1, "duration_sec": 120.5},
        {"phase": "T", "iteration": 1, "duration_sec": 30.2},
        {"phase": "A", "iteration": 2, "duration_sec": 43.8},
        {"phase": "R", "iteration": 2, "duration_sec": 125.3},
        {"phase": "T", "iteration": 2, "duration_sec": 32.1},
        {"phase": "A", "iteration": 3, "duration_sec": 46.1},
        {"phase": "R", "iteration": 3, "duration_sec": 122.7},
        {"phase": "T", "iteration": 3, "duration_sec": 31.5},
        {"phase": "A", "iteration": 4, "duration_sec": 44.9},
        {"phase": "R", "iteration": 4, "duration_sec": 123.2},
        {"phase": "T", "iteration": 4, "duration_sec": 30.8},
        {"phase": "A", "iteration": 5, "duration_sec": 45.5},
        {"phase": "R", "iteration": 5, "duration_sec": 124.1},
        {"phase": "T", "iteration": 5, "duration_sec": 31.3},
    ]
    with open(results_file, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item) + "\n")
    return results_file


def test_analyze_computes_statistics(tmp_results_jsonl):
    """Test that analyze() computes per-phase statistics correctly."""
    analyzer = PhaseBottleneckAnalyzer()
    report = analyzer.analyze(tmp_results_jsonl)

    assert report["iteration_count"] == 5
    assert len(report["phases"]) == 3

    # Check that we have A, R, T phases
    phases = {p["phase_name"]: p for p in report["phases"]}
    assert "A" in phases
    assert "R" in phases
    assert "T" in phases


def test_bottleneck_ranking_matches_manual(tmp_results_jsonl):
    """Test that bottleneck ranking is correct (sorted by total_time_sec)."""
    analyzer = PhaseBottleneckAnalyzer()
    report = analyzer.analyze(tmp_results_jsonl)

    phases = report["phases"]
    # Sorted by total_time_sec DESC
    assert phases[0]["phase_name"] == "R"  # Largest total time
    assert phases[1]["phase_name"] == "A"
    assert phases[2]["phase_name"] == "T"  # Smallest total time

    # Check that top 3 have ranks 1, 2, 3
    assert phases[0]["bottleneck_rank"] == 1
    assert phases[1]["bottleneck_rank"] == 2
    assert phases[2]["bottleneck_rank"] == 3


def test_recommendations_generated(tmp_results_jsonl):
    """Test that recommendations are generated for high-% phases."""
    analyzer = PhaseBottleneckAnalyzer()
    report = analyzer.analyze(tmp_results_jsonl)

    # Phase R should have a recommendation (>40% threshold)
    phases_dict = {p["phase_name"]: p for p in report["phases"]}
    phase_r = phases_dict["R"]
    assert phase_r["percent_of_total"] > 40
    assert len(phase_r["recommendation"]) > 0
    assert "research cache" in phase_r["recommendation"].lower()


def test_format_table_output(tmp_results_jsonl):
    """Test that format_table() produces readable output."""
    analyzer = PhaseBottleneckAnalyzer()
    report = analyzer.analyze(tmp_results_jsonl)

    table_output = analyzer.format_table(report)

    # Check that output contains expected sections
    assert "PHASE BOTTLENECK ANALYSIS" in table_output
    assert "PHASE |" in table_output
    assert ">>>" in table_output  # Top bottleneck highlight
    assert "RECOMMENDATIONS:" in table_output


def test_format_json_output(tmp_results_jsonl):
    """Test that format_json() produces valid newline-delimited JSON."""
    analyzer = PhaseBottleneckAnalyzer()
    report = analyzer.analyze(tmp_results_jsonl)

    json_output = analyzer.format_json(report)
    lines = json_output.strip().split("\n")

    # Should have 3 lines (one per phase)
    assert len(lines) == 3

    # Each line should be valid JSON
    for line in lines:
        obj = json.loads(line)
        assert "phase_name" in obj
        assert "mean_duration_sec" in obj
        assert "bottleneck_rank" in obj


def test_empty_results_file(tmp_path):
    """Test handling of empty results.jsonl file."""
    empty_file = tmp_path / "empty.jsonl"
    empty_file.write_text("", encoding="utf-8")

    analyzer = PhaseBottleneckAnalyzer()
    report = analyzer.analyze(empty_file)

    assert report["phases"] == []
    assert report["total_time_sec"] == 0.0
    assert report["iteration_count"] == 0


def test_nonexistent_results_file(tmp_path):
    """Test handling of nonexistent results.jsonl file."""
    nonexistent = tmp_path / "nonexistent.jsonl"

    analyzer = PhaseBottleneckAnalyzer()
    report = analyzer.analyze(nonexistent)

    assert report["phases"] == []
    assert report["total_time_sec"] == 0.0
    assert report["iteration_count"] == 0
