#!/usr/bin/env python3
"""
Regression tests for US-788: Phase I Stuck Story Diagnosis.

Tests verify that repeated identical failures are correctly diagnosed:
1. Detect identical failures with >70% error message overlap
2. Classify root cause into 4 categories:
   - model-resolvable: Syntax/logic errors fixable by better model
   - scope-too-large: Timeout/token limit — story too big
   - missing-knowledge: Import/undefined reference errors
   - external-dependency: API/network failures
3. Skip futile retries and provide targeted recommendations
4. Store diagnosis in _stuckDiagnosis field on story

Run with: pytest tests/ -k us_788 -v
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from lib.impl.stuck_diagnosis import (
    classify_failure,
    detect_identical_failures,
    diagnose,
    get_recommended_action,
    update_story_with_diagnosis,
)


@pytest.mark.us_788
class TestDetectIdenticalFailures:
    """Test detection of identical failures with >70% overlap."""

    def test_identical_timeout_errors(self) -> None:
        """Three identical timeout errors should be detected as identical."""
        failures = [
            "Timeout: operation timed out after 300 seconds",
            "Timeout: operation timed out after 300 seconds",
            "Timeout: operation timed out after 300 seconds",
        ]
        is_identical, overlap = detect_identical_failures(failures, 0.70)
        assert is_identical is True
        assert overlap > 0.9  # Should be very high for identical strings

    def test_similar_timeout_errors(self) -> None:
        """Similar timeout errors (not identical) should still meet overlap threshold."""
        failures = [
            "Error: operation timed out after 300 seconds during implementation",
            "Error: operation timed out after 300 seconds during implementation",
            "Timeout: operation timed out after 301 seconds during implementation",
        ]
        is_identical, overlap = detect_identical_failures(failures, 0.70)
        assert is_identical is True
        assert overlap > 0.85

    def test_different_errors(self) -> None:
        """Completely different errors should not be identical."""
        failures = [
            "Timeout: operation timed out",
            "SyntaxError: invalid syntax in line 42",
            "ConnectionError: could not resolve host",
        ]
        is_identical, overlap = detect_identical_failures(failures, 0.70)
        assert is_identical is False
        assert overlap < 0.70

    def test_single_failure(self) -> None:
        """Single failure should return is_identical=False."""
        failures = ["Timeout: operation timed out"]
        is_identical, overlap = detect_identical_failures(failures)
        assert is_identical is False
        assert overlap == 0.0

    def test_empty_failures(self) -> None:
        """Empty failure list should handle gracefully."""
        is_identical, overlap = detect_identical_failures([])
        assert is_identical is False
        assert overlap == 0.0

    def test_high_overlap_threshold(self) -> None:
        """High threshold (0.95) should require very similar errors."""
        failures = [
            "Timeout: operation timed out after 300 seconds",
            "Timeout: operation timed out after 301 seconds",
            "Timeout: operation timed out after 299 seconds",
        ]
        is_identical, overlap = detect_identical_failures(failures, 0.95)
        # These are similar but not 95%+ identical
        assert overlap < 0.95


@pytest.mark.us_788
class TestClassifyFailure:
    """Test classification of failures into 4 categories."""

    def test_classify_scope_too_large_timeout(self) -> None:
        """Timeout errors should classify as scope-too-large."""
        errors = [
            "Error: operation timed out after 300 seconds",
            "Deadline exceeded: could not complete in time",
        ]
        classification = classify_failure(errors)
        assert classification == "scope-too-large"

    def test_classify_scope_too_large_token_limit(self) -> None:
        """Token limit errors should classify as scope-too-large."""
        errors = [
            "Error: token limit exceeded",
            "Input too long: context window exceeded",
        ]
        classification = classify_failure(errors)
        assert classification == "scope-too-large"

    def test_classify_external_dependency_network(self) -> None:
        """Network errors should classify as external-dependency."""
        errors = [
            "ConnectionError: could not resolve host api.example.com",
            "HTTP 503: Service Unavailable",
        ]
        classification = classify_failure(errors)
        assert classification == "external-dependency"

    def test_classify_external_dependency_api_error(self) -> None:
        """API errors should classify as external-dependency."""
        errors = [
            "ApiError: rate limit exceeded",
            "Connection refused: cannot reach endpoint",
        ]
        classification = classify_failure(errors)
        assert classification == "external-dependency"

    def test_classify_missing_knowledge_import_error(self) -> None:
        """Import errors should classify as missing-knowledge."""
        errors = [
            "ImportError: cannot import prisma from somewhere",
            "ModuleNotFoundError: No module named 'unknown_lib'",
        ]
        classification = classify_failure(errors)
        assert classification == "missing-knowledge"

    def test_classify_missing_knowledge_undefined_reference(self) -> None:
        """Undefined reference errors should classify as missing-knowledge."""
        errors = [
            "NameError: function 'legacy_api' is not defined",
            "AttributeError: does not exist in this version",
        ]
        classification = classify_failure(errors)
        assert classification == "missing-knowledge"

    def test_classify_model_resolvable_syntax_error(self) -> None:
        """Syntax errors should classify as model-resolvable."""
        errors = [
            "SyntaxError: invalid syntax in line 42",
            "Parse error: unexpected token",
        ]
        classification = classify_failure(errors)
        assert classification == "model-resolvable"

    def test_classify_model_resolvable_assertion_error(self) -> None:
        """Assertion errors should classify as model-resolvable."""
        errors = [
            "AssertionError: acceptance criteria not met",
            "Test failed: expected 'hello' but got 'world'",
        ]
        classification = classify_failure(errors)
        assert classification == "model-resolvable"

    def test_classify_unknown(self) -> None:
        """Unrecognized errors should classify as unknown."""
        errors = ["Some obscure error that doesn't match any pattern"]
        classification = classify_failure(errors)
        assert classification == "unknown"

    def test_classify_with_empty_error(self) -> None:
        """Empty error strings should not break classification."""
        errors = ["", "Timeout: operation timed out", ""]
        classification = classify_failure(errors)
        assert classification == "scope-too-large"


@pytest.mark.us_788
class TestGetRecommendedAction:
    """Test recommended actions for each classification."""

    def test_action_external_dependency(self) -> None:
        """External dependency action should mention checking service status."""
        action = get_recommended_action("external-dependency")
        assert "dependency" in action.lower()
        assert "skip" in action.lower()

    def test_action_scope_too_large(self) -> None:
        """Scope too large action should mention decomposition."""
        action = get_recommended_action("scope-too-large")
        assert "split" in action.lower() or "decompos" in action.lower()

    def test_action_missing_knowledge(self) -> None:
        """Missing knowledge action should mention context."""
        action = get_recommended_action("missing-knowledge")
        assert "context" in action.lower() or "knowledge" in action.lower()

    def test_action_model_resolvable(self) -> None:
        """Model resolvable action should mention PRD/description."""
        action = get_recommended_action("model-resolvable")
        assert "prd" in action.lower() or "description" in action.lower()


@pytest.mark.us_788
class TestDiagnose:
    """Test main diagnose function end-to-end."""

    def test_diagnose_scope_too_large(self) -> None:
        """Diagnose should identify scope-too-large with high confidence."""
        failures = [
            "Timeout: operation timed out after 300 seconds",
            "Timeout: operation timed out after 300 seconds",
            "Timeout: operation timed out after 301 seconds",
        ]
        result = diagnose("US-123", failures)

        assert result["story_id"] == "US-123"
        assert result["classification"] == "scope-too-large"
        assert result["confidence"] > 0.5
        assert result["error_overlap_percent"] > 85.0
        assert result["failures_analyzed"] == 3

    def test_diagnose_external_dependency(self) -> None:
        """Diagnose should identify external-dependency."""
        failures = [
            "ConnectionError: could not resolve host api.example.com",
            "ConnectionError: could not resolve host api.example.com",
            "ConnectionError: could not resolve host api.example.com",
        ]
        result = diagnose("US-456", failures)

        assert result["classification"] == "external-dependency"
        assert result["confidence"] > 0.8

    def test_diagnose_no_failures(self) -> None:
        """Diagnose with no failures should return unknown."""
        result = diagnose("US-999", [])

        assert result["classification"] == "unknown"
        assert result["confidence"] == 0.0
        assert result["failures_analyzed"] == 0

    def test_diagnose_custom_threshold(self) -> None:
        """Diagnose should respect custom overlap threshold."""
        failures = [
            "Timeout after 100 seconds",
            "Timeout after 101 seconds",
            "Completely different error",
        ]
        # With 0.95 threshold, should not detect as identical
        result = diagnose("US-789", failures, overlap_threshold=0.95)
        # Even though first 2 are similar, 3rd is different, so avg overlap < 0.95
        assert result["confidence"] < 1.0


@pytest.mark.us_788
class TestUpdateStoryWithDiagnosis:
    """Test updating prd.json with diagnosis."""

    def test_update_story_successfully(self) -> None:
        """Should successfully add _stuckDiagnosis to story in prd.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prd_path = Path(tmpdir) / "prd.json"
            prd_data = {
                "userStories": [
                    {"id": "US-100", "title": "Test 1", "passes": False},
                    {"id": "US-200", "title": "Test 2", "passes": False},
                ]
            }
            prd_path.write_text(json.dumps(prd_data, indent=2))

            diagnosis = {
                "story_id": "US-100",
                "classification": "scope-too-large",
                "recommended_action": "Split story",
                "confidence": 0.95,
                "error_overlap_percent": 92.5,
                "failures_analyzed": 3,
            }

            success = update_story_with_diagnosis(str(prd_path), "US-100", diagnosis)
            assert success is True

            # Verify the update
            updated_data = json.loads(prd_path.read_text())
            story_100 = next(s for s in updated_data["userStories"] if s["id"] == "US-100")
            assert "_stuckDiagnosis" in story_100
            assert story_100["_stuckDiagnosis"]["classification"] == "scope-too-large"

    def test_update_nonexistent_story(self) -> None:
        """Should return False when story doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prd_path = Path(tmpdir) / "prd.json"
            prd_data = {"userStories": [{"id": "US-100", "title": "Test 1"}]}
            prd_path.write_text(json.dumps(prd_data, indent=2))

            diagnosis = {
                "story_id": "US-999",
                "classification": "external-dependency",
                "recommended_action": "Skip",
                "confidence": 0.8,
                "error_overlap_percent": 88.0,
                "failures_analyzed": 3,
            }

            success = update_story_with_diagnosis(str(prd_path), "US-999", diagnosis)
            assert success is False

    def test_update_invalid_prd(self) -> None:
        """Should return False for invalid prd.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prd_path = Path(tmpdir) / "prd.json"
            prd_path.write_text("{invalid json}")

            diagnosis = {
                "story_id": "US-100",
                "classification": "external-dependency",
                "recommended_action": "Skip",
                "confidence": 0.8,
                "error_overlap_percent": 88.0,
                "failures_analyzed": 3,
            }

            success = update_story_with_diagnosis(str(prd_path), "US-100", diagnosis)
            assert success is False


@pytest.mark.us_788
class TestIntegration:
    """Integration tests: end-to-end diagnosis workflow."""

    def test_full_workflow_timeout_scope_too_large(self) -> None:
        """Full workflow: 3 identical timeouts → scope-too-large diagnosis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prd_path = Path(tmpdir) / "prd.json"
            prd_data = {
                "userStories": [
                    {
                        "id": "US-850",
                        "title": "Large scope story",
                        "passes": False,
                        "acceptanceCriteria": ["AC1", "AC2"],
                    }
                ]
            }
            prd_path.write_text(json.dumps(prd_data, indent=2))

            # Simulate 3 timeout failures
            failures = [
                "Error: operation timed out after 300 seconds during implementation",
                "Error: operation timed out after 300 seconds during implementation",
                "Error: operation timed out after 300 seconds during implementation",
            ]

            # Diagnose
            diagnosis = diagnose("US-850", failures)
            assert diagnosis["classification"] == "scope-too-large"
            assert diagnosis["confidence"] > 0.8

            # Update prd.json
            success = update_story_with_diagnosis(str(prd_path), "US-850", diagnosis)
            assert success is True

            # Verify final state
            final_data = json.loads(prd_path.read_text())
            story = final_data["userStories"][0]
            assert story["_stuckDiagnosis"]["classification"] == "scope-too-large"
            assert story["_stuckDiagnosis"]["recommended_action"]
            assert "split" in story["_stuckDiagnosis"]["recommended_action"].lower()
