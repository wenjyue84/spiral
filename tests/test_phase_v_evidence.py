"""Tests for lib/phase_v_evidence.py — Phase V evidence aggregator."""

from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.phase_v_evidence import aggregate_evidence, aggregate_phase_v_summary, main, write_evidence_json


def test_aggregate_basic() -> None:
    prd = {
        "userStories": [
            {"id": "US-100", "passes": True},
            {"id": "US-101", "passes": False},
            {"id": "US-102"},
        ]
    }
    result = aggregate_evidence(prd)
    assert result["US-100"]["target"] == "PASS"
    assert result["US-101"]["target"] == "FAIL"
    assert result["US-102"]["target"] == "FAIL"


def test_aggregate_empty() -> None:
    assert aggregate_evidence({"userStories": []}) == {}
    assert aggregate_evidence({}) == {}


def test_main_writes_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        prd_path = os.path.join(tmp, "prd.json")
        out_path = os.path.join(tmp, "evidence.json")
        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump({"userStories": [{"id": "US-001", "passes": True}]}, f)
        rc = main(["--prd", prd_path, "--out", out_path])
        assert rc == 0
        data = json.loads(open(out_path, encoding="utf-8").read())
        assert data["US-001"]["target"] == "PASS"


def test_main_bad_prd() -> None:
    rc = main(["--prd", "/nonexistent/prd.json", "--out", "/dev/null"])
    assert rc == 1


def test_aggregator_parses_test_output() -> None:
    """Verify AC extraction, failing tests, and JSON schema."""
    from lib.phase_v_evidence import TestEvidenceAggregator

    agg = TestEvidenceAggregator()
    sample_output = (
        "collecting ...\n"
        "@spiral:ac:pass Create evidence aggregator class\n"
        "@spiral:ac:fail Generate per-story JSON evidence\n"
        "FAILED tests/test_foo.py::test_bar - AssertionError\n"
        "tests/test_foo.py:42: AssertionError\n"
        "FAILED tests/test_baz.py::test_qux\n"
        "1 passed, 2 failed\n"
    )
    result = agg.parse_output(sample_output, "US-999")

    assert result["story_id"] == "US-999"
    assert len(result["acceptance_criteria"]) == 2
    assert result["acceptance_criteria"][0]["status"] == "pass"
    assert result["acceptance_criteria"][0]["description"] == "Create evidence aggregator class"
    assert result["acceptance_criteria"][1]["status"] == "fail"
    assert len(result["failing_tests"]) == 2
    assert result["failing_tests"][0]["file"] == "tests/test_foo.py"
    assert result["failing_tests"][0]["name"] == "test_bar"
    assert result["failing_tests"][1]["file"] == "tests/test_baz.py"
    assert "file_assertions" in result

    # Test aggregate writes file
    with tempfile.TemporaryDirectory() as tmp:
        out = agg.aggregate(sample_output, "US-999", output_dir=tmp)
        assert os.path.isfile(out)
        data = json.loads(open(out, encoding="utf-8").read())
        assert data["story_id"] == "US-999"
        assert len(data["failing_tests"]) == 2


def test_write_evidence_json() -> None:
    """Per-story evidence file has required schema fields."""
    with tempfile.TemporaryDirectory() as tmp:
        out = write_evidence_json(
            story_id="US-1434",
            test_file="tests/test_phase_v_evidence.py",
            test_marker="phase_v",
            passed=True,
            duration_ms=1234,
            evidence_dir=tmp,
        )
        assert os.path.isfile(out)
        data = json.loads(open(out, encoding="utf-8").read())
        assert data["testFile"] == "tests/test_phase_v_evidence.py"
        assert data["testMarker"] == "phase_v"
        assert data["passed"] is True
        assert data["duration_ms"] == 1234
        assert "timestamp" in data
        # ISO8601 format: ends with Z
        assert data["timestamp"].endswith("Z")


def test_aggregate_phase_v_summary() -> None:
    """Summary JSON has correct schema and computed stats."""
    with tempfile.TemporaryDirectory() as tmp:
        evidence_dir = os.path.join(tmp, "evidence")
        summary_path = os.path.join(tmp, "phase_v_summary.json")
        # Write two evidence files
        write_evidence_json("US-1", "", "", passed=True, duration_ms=500, evidence_dir=evidence_dir)
        write_evidence_json("US-2", "", "", passed=False, duration_ms=200, evidence_dir=evidence_dir)
        write_evidence_json("US-3", "", "", passed=True, duration_ms=900, evidence_dir=evidence_dir)

        summary = aggregate_phase_v_summary(evidence_dir=evidence_dir, out_path=summary_path)

        assert summary["total_stories"] == 3
        assert summary["pass_count"] == 2
        assert summary["fail_count"] == 1
        assert summary["pass_rate_percent"] == pytest.approx(66.7, abs=0.1)
        assert isinstance(summary["slowest_tests"], list)
        assert summary["slowest_tests"][0]["duration_ms"] == 900

        # Verify file was written
        assert os.path.isfile(summary_path)
        on_disk = json.loads(open(summary_path, encoding="utf-8").read())
        assert on_disk["total_stories"] == 3


def test_main_per_story_flag() -> None:
    """--per-story writes evidence files and summary."""
    with tempfile.TemporaryDirectory() as tmp:
        prd_path = os.path.join(tmp, "prd.json")
        evidence_dir = os.path.join(tmp, "evidence")
        summary_path = os.path.join(tmp, "phase_v_summary.json")
        prd = {
            "userStories": [
                {"id": "US-10", "passes": True},
                {"id": "US-11", "passes": False},
            ]
        }
        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump(prd, f)
        rc = main(["--prd", prd_path, "--per-story", "--evidence-dir", evidence_dir, "--summary-out", summary_path])
        assert rc == 0
        assert os.path.isfile(os.path.join(evidence_dir, "US-10.json"))
        assert os.path.isfile(os.path.join(evidence_dir, "US-11.json"))
        assert os.path.isfile(summary_path)
        summary = json.loads(open(summary_path, encoding="utf-8").read())
        assert summary["pass_count"] == 1
        assert summary["fail_count"] == 1
