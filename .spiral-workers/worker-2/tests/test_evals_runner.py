"""
Tests for SPIRAL Evals Runner.

Comprehensive test suite for evals_runner.py functionality.
"""

import sys
from pathlib import Path

import pytest

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from evals_runner import (
    DeterministicCheckResult,
    EvalResult,
    EvalRunner,
    ModelGradedResult,
)


class TestDeterministicCheckResult:
    """Tests for DeterministicCheckResult dataclass."""

    def test_create_passing_check(self) -> None:
        """Test creating a passing check result."""
        result = DeterministicCheckResult(name="test_check", passed=True, score=1.0, reason="All good")
        assert result.name == "test_check"
        assert result.passed is True
        assert result.score == 1.0
        assert result.reason == "All good"

    def test_create_failing_check(self) -> None:
        """Test creating a failing check result."""
        result = DeterministicCheckResult(name="test_check", passed=False, score=0.0, reason="Failed validation")
        assert result.passed is False
        assert result.score == 0.0


class TestModelGradedResult:
    """Tests for ModelGradedResult dataclass."""

    def test_create_model_result(self) -> None:
        """Test creating a model-graded result."""
        result = ModelGradedResult(name="quality_check", score=0.75, reason="Good quality")
        assert result.name == "quality_check"
        assert result.score == 0.75
        assert result.reason == "Good quality"


class TestEvalResult:
    """Tests for EvalResult dataclass."""

    def test_create_passing_eval(self) -> None:
        """Test creating a passing eval result."""
        det_checks = [
            DeterministicCheckResult("check1", True, 1.0, "pass"),
            DeterministicCheckResult("check2", True, 1.0, "pass"),
        ]
        model_checks = [ModelGradedResult("model1", 0.8, "good")]

        result = EvalResult(
            eval_name="test_eval",
            passed=True,
            deterministic_score=1.0,
            model_score=0.8,
            final_score=0.92,
            deterministic_checks=det_checks,
            model_checks=model_checks,
            pass_threshold=0.75,
            num_cases=2,
            failed_cases=[],
        )

        assert result.eval_name == "test_eval"
        assert result.passed is True
        assert result.final_score == 0.92


class TestEvalRunner:
    """Tests for EvalRunner class."""

    def test_init(self, tmp_path: Path) -> None:
        """Test EvalRunner initialization."""
        runner = EvalRunner(tmp_path)
        assert runner.eval_dir == tmp_path
        assert runner.evals == []
        assert runner.results == []

    def test_extract_field_simple(self) -> None:
        """Test simple field extraction."""
        data = {"id": "US-001", "title": "Test"}
        value = EvalRunner._extract_field(data, "id")
        assert value == "US-001"

    def test_extract_field_nested(self) -> None:
        """Test nested field extraction."""
        data = {
            "story": {"id": "US-001", "title": "Test"},
        }
        value = EvalRunner._extract_field(data, "story.id")
        assert value == "US-001"

    def test_extract_field_missing(self) -> None:
        """Test extraction of missing field."""
        data = {"id": "US-001"}
        value = EvalRunner._extract_field(data, "missing")
        assert value is None

    def test_extract_field_from_json_string(self) -> None:
        """Test field extraction from JSON string."""
        data = {
            "input_story": '{"id":"US-001","title":"Test"}',
        }
        value = EvalRunner._extract_field(data, "input_story.id")
        assert value == "US-001"

    def test_discover_evals(self, tmp_path: Path) -> None:
        """Test discovering eval.yaml files."""
        # Create nested eval directories
        (tmp_path / "phase1").mkdir()
        (tmp_path / "phase1" / "eval.yaml").write_text("name: phase1")
        (tmp_path / "phase2").mkdir()
        (tmp_path / "phase2" / "eval.yaml").write_text("name: phase2")

        runner = EvalRunner(tmp_path)
        evals = runner.discover_evals()

        assert len(evals) == 2
        assert all(e.name == "eval.yaml" for e in evals)

    def test_regex_check_pass(self) -> None:
        """Test regex deterministic check that passes."""
        runner = EvalRunner(Path("."))
        check = {
            "name": "id_format",
            "check_type": "regex",
            "field": "id",
            "pattern": "^US-[0-9]{3}$",
        }
        data = {"id": "US-001"}

        result = runner.run_deterministic_check(check, data)

        assert result.passed is True
        assert result.score == 1.0

    def test_regex_check_fail(self) -> None:
        """Test regex deterministic check that fails."""
        runner = EvalRunner(Path("."))
        check = {
            "name": "id_format",
            "check_type": "regex",
            "field": "id",
            "pattern": "^US-[0-9]{3}$",
        }
        data = {"id": "INVALID-001"}

        result = runner.run_deterministic_check(check, data)

        assert result.passed is False
        assert result.score == 0.0

    def test_nonempty_check_pass(self) -> None:
        """Test field_nonempty check that passes."""
        runner = EvalRunner(Path("."))
        check = {
            "name": "has_title",
            "check_type": "field_nonempty",
            "field": "title",
        }
        data = {"title": "My Feature"}

        result = runner.run_deterministic_check(check, data)

        assert result.passed is True

    def test_nonempty_check_fail(self) -> None:
        """Test field_nonempty check that fails."""
        runner = EvalRunner(Path("."))
        check = {
            "name": "has_title",
            "check_type": "field_nonempty",
            "field": "title",
        }
        data = {"title": ""}

        result = runner.run_deterministic_check(check, data)

        assert result.passed is False

    def test_enum_check_pass(self) -> None:
        """Test enum check that passes."""
        runner = EvalRunner(Path("."))
        check = {
            "name": "valid_priority",
            "check_type": "enum",
            "field": "priority",
            "allowed_values": ["critical", "high", "medium", "low"],
        }
        data = {"priority": "high"}

        result = runner.run_deterministic_check(check, data)

        assert result.passed is True

    def test_enum_check_fail(self) -> None:
        """Test enum check that fails."""
        runner = EvalRunner(Path("."))
        check = {
            "name": "valid_priority",
            "check_type": "enum",
            "field": "priority",
            "allowed_values": ["critical", "high", "medium", "low"],
        }
        data = {"priority": "invalid"}

        result = runner.run_deterministic_check(check, data)

        assert result.passed is False

    def test_min_length_check_pass(self) -> None:
        """Test min_length check that passes."""
        runner = EvalRunner(Path("."))
        check = {
            "name": "sufficient_content",
            "check_type": "min_length",
            "field": "description",
            "min_chars": 10,
        }
        data = {"description": "This is a long enough description"}

        result = runner.run_deterministic_check(check, data)

        assert result.passed is True

    def test_min_length_check_fail(self) -> None:
        """Test min_length check that fails."""
        runner = EvalRunner(Path("."))
        check = {
            "name": "sufficient_content",
            "check_type": "min_length",
            "field": "description",
            "min_chars": 50,
        }
        data = {"description": "Short"}

        result = runner.run_deterministic_check(check, data)

        assert result.passed is False

    def test_model_graded_check(self) -> None:
        """Test model-graded check execution."""
        runner = EvalRunner(Path("."))
        check = {
            "name": "quality",
            "rubric": "Quality assessment",
            "field": "output",
            "expected_field": "expected_quality",
        }
        data = {"output": "This is a detailed implementation", "expected_quality": "high"}

        result = runner.run_model_graded_check(check, data)

        assert result.name == "quality"
        assert 0.0 <= result.score <= 1.0


class TestEvalIntegration:
    """Integration tests for the full eval runner."""

    def test_run_evals_with_real_files(self) -> None:
        """Test running evals against real eval files in tests/evals/."""
        evals_dir = Path(__file__).parent / "evals"
        if not evals_dir.exists():
            pytest.skip("evals directory not found")

        runner = EvalRunner(evals_dir)
        results = runner.run_all_evals()

        assert len(results) > 0
        assert all(isinstance(r, EvalResult) for r in results)

    def test_print_summary_with_results(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test print_summary output."""
        runner = EvalRunner(Path("."))
        runner.results = [
            EvalResult(
                eval_name="test_eval",
                passed=True,
                deterministic_score=0.9,
                model_score=0.8,
                final_score=0.87,
                deterministic_checks=[],
                model_checks=[],
                pass_threshold=0.75,
                num_cases=5,
                failed_cases=[],
            )
        ]

        runner.print_summary()
        captured = capsys.readouterr()

        assert "SPIRAL EVALS SUMMARY" in captured.out
        assert "test_eval" in captured.out
        assert "1/1 evals passed" in captured.out
