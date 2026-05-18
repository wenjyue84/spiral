"""Tests for lib/phase_v_evidence.py — Phase V evidence aggregator."""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.phase_v_evidence import aggregate_evidence, main


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
