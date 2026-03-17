"""Tests for SPIRAL Evals framework."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Add tests/ to path so we can import evals modules
sys.path.insert(0, str(Path(__file__).parent))

from evals.graders import (
    DeterministicGrader,
    ModelGradedRubric,
    check_list_length,
    check_no_errors,
    check_regex_match,
    check_required_fields,
    check_string_contains,
    check_valid_json,
)
from evals.runner import EvalsRunner, TestCase


class TestGraders:
    """Test deterministic graders."""

    def test_check_valid_json_valid(self):
        """Test valid JSON detection."""
        result = check_valid_json('{"key": "value"}')
        assert result.passed is True
        assert result.score == 1.0

    def test_check_valid_json_invalid(self):
        """Test invalid JSON detection."""
        result = check_valid_json("{invalid json}")
        assert result.passed is False
        assert result.score == 0.0

    def test_check_required_fields_all_present(self):
        """Test required fields when all present."""
        output = '{"id": "US-001", "title": "Test"}'
        result = check_required_fields(output, ["id", "title"])
        assert result.passed is True
        assert result.score == 1.0

    def test_check_required_fields_missing(self):
        """Test required fields when some missing."""
        output = '{"id": "US-001"}'
        result = check_required_fields(output, ["id", "title"])
        assert result.passed is False
        assert result.score == 0.0

    def test_check_regex_match_found(self):
        """Test regex match when pattern found."""
        result = check_regex_match("This is a test", r"test")
        assert result.passed is True
        assert result.score == 1.0

    def test_check_regex_match_not_found(self):
        """Test regex match when pattern not found."""
        result = check_regex_match("This is a test", r"missing", required=True)
        assert result.passed is False
        assert result.score == 0.0

    def test_check_list_length_within_bounds(self):
        """Test list length within bounds."""
        output = '["a", "b", "c"]'
        result = check_list_length(output, min_length=2, max_length=4)
        assert result.passed is True
        assert result.score == 1.0

    def test_check_list_length_too_short(self):
        """Test list length too short."""
        output = '["a"]'
        result = check_list_length(output, min_length=2)
        assert result.passed is False
        assert result.score == 0.0

    def test_check_string_contains_all_found(self):
        """Test string contains when all found."""
        result = check_string_contains("hello world test", ["hello", "world"], all_required=True)
        assert result.passed is True
        assert result.score == 1.0

    def test_check_string_contains_some_missing(self):
        """Test string contains when some missing."""
        result = check_string_contains("hello world", ["hello", "missing"], all_required=True)
        assert result.passed is False

    def test_check_no_errors_clean(self):
        """Test no errors check when output is clean."""
        result = check_no_errors('{"status": "success"}')
        assert result.passed is True
        assert result.score == 1.0

    def test_check_no_errors_with_keywords(self):
        """Test no errors check when error keywords present."""
        result = check_no_errors('{"status": "error occurred"}')
        assert result.passed is False
        assert result.score == 0.0


class TestDeterministicGrader:
    """Test deterministic grader runner."""

    def test_grade_valid_json(self):
        """Test grading with valid_json checker."""
        result = DeterministicGrader.grade('{"key": "value"}', {"type": "valid_json"})
        assert result.passed is True
        assert result.score == 1.0

    def test_grade_required_fields(self):
        """Test grading with required_fields checker."""
        result = DeterministicGrader.grade('{"id": "US-001"}', {"type": "required_fields", "required_fields": ["id"]})
        assert result.passed is True

    def test_grade_unknown_checker(self):
        """Test grading with unknown checker type."""
        result = DeterministicGrader.grade('{}', {"type": "unknown_checker"})
        assert result.passed is False


class TestModelGradedRubric:
    """Test model-graded rubric placeholder."""

    def test_grade_returns_placeholder(self):
        """Test that model-graded rubric returns placeholder."""
        result = ModelGradedRubric.grade("{}", {})
        assert result.passed is False
        assert "not yet implemented" in result.reasoning.lower()


class TestTestCase:
    """Test TestCase data class."""

    def test_test_case_creation(self):
        """Test creating a test case."""
        tc = TestCase(input="test input", expected_output='{"result": "success"}', metadata={"phase": "s"})
        assert tc.input == "test input"
        assert tc.expected_output == '{"result": "success"}'
        assert tc.metadata == {"phase": "s"}


class TestEvalsRunner:
    """Test EvalsRunner orchestrator."""

    def test_runner_initialization(self):
        """Test initializing runner."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evals_dir = Path(tmpdir)
            runner = EvalsRunner(evals_dir)
            assert runner.evals_dir == evals_dir

    def test_load_eval_config(self):
        """Test loading eval configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evals_dir = Path(tmpdir)
            configs_dir = evals_dir / "configs"
            configs_dir.mkdir()

            # Create test YAML
            config_file = configs_dir / "test.yaml"
            config_file.write_text("id: test\nname: Test Eval\ndata_source: test.csv\n")

            runner = EvalsRunner(evals_dir)
            config = runner.load_eval_config(config_file)
            assert config["id"] == "test"
            assert config["name"] == "Test Eval"

    def test_load_dataset(self):
        """Test loading CSV dataset."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evals_dir = Path(tmpdir)
            datasets_dir = evals_dir / "datasets"
            datasets_dir.mkdir()

            # Create test CSV
            csv_file = datasets_dir / "test.csv"
            csv_file.write_text("input,expected_output\ntest1,output1\ntest2,output2\n")

            runner = EvalsRunner(evals_dir)
            test_cases = runner.load_dataset(csv_file)
            assert len(test_cases) == 2
            assert test_cases[0].input == "test1"
            assert test_cases[0].expected_output == "output1"

    def test_evaluate_single_test_deterministic(self):
        """Test evaluating single test with deterministic criteria."""
        runner = EvalsRunner(Path("."))
        test_case = TestCase(input="test", expected_output='{"id": "US-001"}')
        criteria = [{"type": "deterministic", "params": {"type": "required_fields", "required_fields": ["id"]}}]

        results, avg_score = runner.evaluate_single_test(test_case, criteria)
        assert len(results) == 1
        assert results[0]["passed"] is True
        assert avg_score == 1.0

    def test_print_summary(self):
        """Test printing summary."""
        from evals.runner import EvalScore

        results = [
            EvalScore(
                "test_1",
                "Test Eval 1",
                total_tests=5,
                passed_tests=5,
                average_score=1.0,
                status="pass",
                details=[],
            ),
            EvalScore(
                "test_2",
                "Test Eval 2",
                total_tests=5,
                passed_tests=3,
                average_score=0.8,
                status="fail",
                details=[],
            ),
        ]

        # Should not raise
        EvalsRunner.print_summary(results)

    def test_save_results(self):
        """Test saving results to JSON."""
        from evals.runner import EvalScore

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "results.json"
            results = [
                EvalScore(
                    "test_1",
                    "Test Eval",
                    total_tests=5,
                    passed_tests=5,
                    average_score=1.0,
                    status="pass",
                    details=[],
                ),
            ]

            EvalsRunner.save_results(results, output_file)
            assert output_file.exists()

            # Verify JSON structure
            data = json.loads(output_file.read_text())
            assert "summary" in data
            assert "evals" in data
            assert data["summary"]["total"] == 1
            assert data["summary"]["passed"] == 1


class TestEvalsIntegration:
    """Integration tests for evals framework."""

    def test_run_all_evals_in_project(self):
        """Test running all evals in project."""
        # Use the actual evals directory from the project
        project_root = Path(__file__).parent.parent
        evals_dir = project_root / "tests" / "evals"

        if not evals_dir.exists():
            pytest.skip("evals directory not found")

        runner = EvalsRunner(evals_dir)
        results = runner.run_all_evals()

        assert len(results) > 0
        # All evals should have been processed
        for result in results:
            assert result.eval_id
            assert result.eval_name
            assert result.total_tests >= 0
            assert 0 <= result.passed_tests <= result.total_tests
            assert 0 <= result.average_score <= 1.0
