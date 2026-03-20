"""Security tests for lib/predict_cost.py (US-568).

Validates:
- Path traversal rejection on --history / --prd arguments
- Output JSON contains only expected schema keys
- Malformed/null story attributes produce clean errors (no Python tracebacks)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from io import StringIO
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.predict_cost import KNNEstimator, _validate_path, main, predict_story


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prd(tmp: str, stories: list[dict[str, Any]] | None = None) -> str:
    """Write a minimal prd.json and return its path."""
    if stories is None:
        stories = [
            {
                "id": "US-001",
                "title": "Test story",
                "passes": False,
                "estimatedComplexity": "small",
            }
        ]
    prd_path = os.path.join(tmp, "prd.json")
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump({"userStories": stories}, f)
    return prd_path


def _make_history(tmp: str, rows: int = 10) -> str:
    """Write a minimal results.tsv with enough rows for KNN."""
    tsv_path = os.path.join(tmp, "results.tsv")
    with open(tsv_path, "w", encoding="utf-8") as f:
        f.write("story_id\tstory_title\tmodel\ttokens_in\ttokens_out\tstatus\n")
        for i in range(rows):
            f.write(f"US-{i:03d}\tStory {i}\tsonnet\t1000\t500\tpass\n")
    return tsv_path


# ---------------------------------------------------------------------------
# Test: path traversal rejected
# ---------------------------------------------------------------------------


def test_path_traversal_rejected() -> None:
    """CLI rejects path traversal (e.g. ../../etc/passwd) and exits non-zero."""
    # Test 1: history file path traversal
    with tempfile.TemporaryDirectory() as tmp:
        prd = _make_prd(tmp)
        with pytest.raises(SystemExit) as exc_info:
            main(["--story-id", "US-001", "--prd", prd, "--history", "../../etc/passwd"])
        assert exc_info.value.code != 0

    # Test 2: prd file path traversal
    with tempfile.TemporaryDirectory() as tmp:
        history = _make_history(tmp)
        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "--story-id",
                    "US-001",
                    "--prd",
                    "../../etc/passwd",
                    "--history",
                    history,
                ]
            )
        assert exc_info.value.code != 0

    # Test 3: _validate_path rejects dotdot
    with pytest.raises(ValueError, match="path traversal"):
        _validate_path("../../etc/passwd", "test")

    # Test 4: _validate_path accepts normal paths
    _validate_path("results.tsv", "test")

    # Test 5: _validate_path accepts absolute paths
    _validate_path(os.path.abspath("results.tsv"), "test")


# ---------------------------------------------------------------------------
# Test: output schema only
# ---------------------------------------------------------------------------


def test_output_schema_only() -> None:
    """JSON stdout contains only the keys: estimated_tokens, estimated_cost,
    confidence_pct, similar_stories (the actual keys emitted by predict_cost)."""
    expected_keys = {"estimated_tokens", "estimated_cost", "confidence_pct", "similar_stories"}

    with tempfile.TemporaryDirectory() as tmp:
        prd = _make_prd(tmp)
        history = _make_history(tmp)

        old_stdout = sys.stdout
        sys.stdout = captured = StringIO()
        try:
            main(["--story-id", "US-001", "--prd", prd, "--history", history])
        finally:
            sys.stdout = old_stdout

        output = json.loads(captured.getvalue())
        assert set(output.keys()) == expected_keys, (
            f"Unexpected keys in output: {set(output.keys())} != {expected_keys}"
        )
        # Also verify value types
        assert isinstance(output["estimated_tokens"], (int, float))
        assert isinstance(output["estimated_cost"], (int, float))
        assert isinstance(output["confidence_pct"], (int, float))
        assert isinstance(output["similar_stories"], list)


# ---------------------------------------------------------------------------
# Test: malformed input no traceback
# ---------------------------------------------------------------------------


def test_malformed_input_no_traceback() -> None:
    """Empty/null story attributes produce a clean error message, no traceback."""
    # Test 1: nonexistent story ID
    with tempfile.TemporaryDirectory() as tmp:
        prd = _make_prd(tmp)
        history = _make_history(tmp)

        old_stderr = sys.stderr
        sys.stderr = captured_err = StringIO()
        try:
            with pytest.raises(SystemExit) as exc_info:
                main(
                    [
                        "--story-id",
                        "DOES-NOT-EXIST",
                        "--prd",
                        prd,
                        "--history",
                        history,
                    ]
                )
        finally:
            sys.stderr = old_stderr

        assert exc_info.value.code != 0
        err_output = captured_err.getvalue()
        # Should be a clean JSON error, not a Python traceback
        assert "Traceback" not in err_output
        if err_output.strip():
            parsed = json.loads(err_output)
            assert "error" in parsed

    # Test 2: empty PRD file
    with tempfile.TemporaryDirectory() as tmp:
        prd_path = os.path.join(tmp, "prd.json")
        with open(prd_path, "w") as f:
            f.write("")
        history = _make_history(tmp)

        old_stderr = sys.stderr
        sys.stderr = captured_err = StringIO()
        try:
            with pytest.raises(SystemExit) as exc_info:
                main(
                    [
                        "--story-id",
                        "US-001",
                        "--prd",
                        prd_path,
                        "--history",
                        history,
                    ]
                )
        finally:
            sys.stderr = old_stderr

        assert exc_info.value.code != 0
        err_output = captured_err.getvalue()
        assert "Traceback" not in err_output

    # Test 3: story with null attributes
    estimator = KNNEstimator()
    # Fit with no data (empty history)
    estimator._data = []
    result = estimator.predict({"id": None, "title": None, "estimatedComplexity": None})
    # Should return zero-confidence result, not crash
    assert result["confidence_pct"] == 0.0
    assert result["estimated_tokens"] == 0
