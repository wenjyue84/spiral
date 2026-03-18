"""
SPIRAL Evals Runner - OpenAI Evals-style behavioral testing for SPIRAL phases.

Loads YAML eval definitions, executes deterministic and model-graded checks,
aggregates scores, and reports pass/fail per eval.
"""

import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml  # type: ignore[import-untyped]


@dataclass
class DeterministicCheckResult:
    """Result of a deterministic check."""

    name: str
    passed: bool
    score: float  # 0-1
    reason: str


@dataclass
class ModelGradedResult:
    """Result of a model-graded check."""

    name: str
    score: float  # 0-10, normalized to 0-1
    reason: str


@dataclass
class EvalResult:
    """Aggregated result for an eval."""

    eval_name: str
    passed: bool
    deterministic_score: float
    model_score: float
    final_score: float
    deterministic_checks: List[DeterministicCheckResult]
    model_checks: List[ModelGradedResult]
    pass_threshold: float
    num_cases: int
    failed_cases: List[int]


class EvalRunner:
    """Runs evals against loaded YAML definitions and data."""

    def __init__(self, eval_dir: Path):
        """Initialize runner with path to evals directory."""
        self.eval_dir = Path(eval_dir)
        self.evals: List[Dict[str, Any]] = []
        self.results: List[EvalResult] = []

    def discover_evals(self) -> List[Path]:
        """Discover all eval.yaml files in eval_dir and subdirectories."""
        eval_files = list(self.eval_dir.rglob("eval.yaml"))
        return sorted(eval_files)

    def load_eval(self, eval_file: Path) -> Dict[str, Any]:
        """Load a single eval.yaml file."""
        with open(eval_file, "r") as f:
            eval_def_raw = yaml.safe_load(f)
        eval_def: Dict[str, Any] = eval_def_raw if isinstance(eval_def_raw, dict) else {}
        eval_def["_path"] = eval_file
        return eval_def

    def load_dataset(self, eval_def: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Load CSV dataset for an eval."""
        data_source = eval_def.get("data_source")
        if not data_source:
            return []

        # Resolve relative paths from the eval.yaml file's directory
        eval_path: Any = eval_def.get("_path", self.eval_dir / "eval.yaml")
        eval_file_dir = Path(eval_path).parent if eval_path else self.eval_dir

        # Resolve data_source path relative to eval file location
        data_source_str = str(data_source)
        if Path(data_source_str).is_absolute():
            data_path = Path(data_source_str)
        else:
            data_path = eval_file_dir / data_source_str

        rows = []
        with open(data_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row is not None:
                    rows.append(row)
        return rows

    def run_deterministic_check(self, check: Dict[str, Any], data_row: Dict[str, Any]) -> DeterministicCheckResult:
        """Execute a single deterministic check."""
        name = check.get("name", "unknown")
        check_type = check.get("check_type")
        field_path = check.get("field", "")

        # Extract field value from data row
        field_value = self._extract_field(data_row, field_path)

        passed = True
        reason = ""

        if check_type == "regex":
            pattern = check.get("pattern", "")
            if not field_value or not re.match(pattern, str(field_value)):
                passed = False
                reason = f"Value '{field_value}' does not match pattern '{pattern}'"
            else:
                reason = f"Value '{field_value}' matches pattern"

        elif check_type == "field_nonempty":
            if not field_value or str(field_value).strip() == "":
                passed = False
                reason = "Field is empty"
            else:
                reason = f"Field has value: {str(field_value)[:50]}"

        elif check_type == "enum":
            allowed = check.get("allowed_values", [])
            if field_value not in allowed:
                passed = False
                reason = f"Value '{field_value}' not in allowed set: {allowed}"
            else:
                reason = f"Value '{field_value}' is in allowed set"

        elif check_type == "min_length":
            min_chars = check.get("min_chars", 0)
            if not field_value or len(str(field_value)) < min_chars:
                passed = False
                reason = f"Length {len(str(field_value)) if field_value else 0} < {min_chars}"
            else:
                reason = f"Length {len(str(field_value))} >= {min_chars}"

        score = 1.0 if passed else 0.0

        return DeterministicCheckResult(name=name, passed=passed, score=score, reason=reason)

    def run_model_graded_check(self, check: Dict[str, Any], data_row: Dict[str, Any]) -> ModelGradedResult:
        """
        Execute a model-graded check.

        For now, returns a placeholder. In production, would call Claude API.
        """
        name = check.get("name", "unknown")
        rubric = check.get("rubric", "")
        field_path = check.get("field", "")

        field_value = self._extract_field(data_row, field_path)
        expected_field = check.get("expected_field")
        expected_value = data_row.get(expected_field) if expected_field else None

        # Placeholder: score based on field length and expected value match
        # In production, would call Claude with rubric to score
        if field_value:
            # Simple heuristic: longer = better (0-10 scale)
            length_score = min(10, len(str(field_value)) / 20)
        else:
            length_score = 0

        # If expected_value matches quality assessment, boost score
        if expected_field and expected_value:
            expected_lower = str(expected_value).lower()
            if expected_lower == "high":
                # Boost score if expected is high
                length_score = min(10, length_score + 3)
            elif expected_lower == "medium":
                length_score = min(10, length_score + 1)

        normalized_score = length_score / 10.0  # Normalize to 0-1

        return ModelGradedResult(
            name=name,
            score=normalized_score,
            reason=f"Model-graded rubric evaluation (heuristic: {length_score:.1f}/10)",
        )

    def run_eval(self, eval_def: Dict[str, Any]) -> EvalResult:
        """Run a complete eval against its dataset."""
        eval_name = eval_def.get("name", "unknown")
        dataset = self.load_dataset(eval_def)
        testing_criteria = eval_def.get("testing_criteria", {})
        aggregation = eval_def.get("score_aggregation", {})

        deterministic_checks = testing_criteria.get("deterministic", [])
        model_checks = testing_criteria.get("model_graded", [])

        all_det_results: List[DeterministicCheckResult] = []
        all_model_results: List[ModelGradedResult] = []
        failed_cases: List[int] = []

        for case_idx, data_row in enumerate(dataset):
            det_results: List[DeterministicCheckResult] = []
            model_results: List[ModelGradedResult] = []

            # Run deterministic checks
            for check in deterministic_checks:
                det_result = self.run_deterministic_check(check, data_row)
                det_results.append(det_result)

            # Run model-graded checks
            for check in model_checks:
                model_result = self.run_model_graded_check(check, data_row)
                model_results.append(model_result)

            all_det_results.extend(det_results)
            all_model_results.extend(model_results)

            # Check if case passed
            case_det_passed = all(r.passed for r in det_results)
            case_model_score = sum(r.score for r in model_results) / len(model_results) if model_results else 0.5
            if not case_det_passed or case_model_score < 0.5:
                failed_cases.append(case_idx)

        # Calculate aggregate scores
        det_weight = aggregation.get("deterministic_weight", 0.5)
        model_weight = aggregation.get("model_weight", 0.5)
        pass_threshold = aggregation.get("pass_threshold", 0.75)

        det_score = sum(r.score for r in all_det_results) / len(all_det_results) if all_det_results else 0.5
        model_score = sum(r.score for r in all_model_results) / len(all_model_results) if all_model_results else 0.5

        final_score = (det_score * det_weight) + (model_score * model_weight)
        passed = final_score >= pass_threshold

        return EvalResult(
            eval_name=eval_name,
            passed=passed,
            deterministic_score=det_score,
            model_score=model_score,
            final_score=final_score,
            deterministic_checks=all_det_results,
            model_checks=all_model_results,
            pass_threshold=pass_threshold,
            num_cases=len(dataset),
            failed_cases=failed_cases,
        )

    def run_all_evals(self) -> List[EvalResult]:
        """Discover and run all evals."""
        eval_files = self.discover_evals()
        self.results = []

        for eval_file in eval_files:
            try:
                eval_def = self.load_eval(eval_file)
                result = self.run_eval(eval_def)
                self.results.append(result)
            except Exception as e:
                print(f"Error running eval {eval_file}: {e}", file=sys.stderr)

        return self.results

    def print_summary(self) -> None:
        """Print human-readable summary of all eval results."""
        if not self.results:
            print("No evals run.")
            return

        print("\n" + "=" * 70)
        print("SPIRAL EVALS SUMMARY")
        print("=" * 70)

        for result in self.results:
            status = "[PASS]" if result.passed else "[FAIL]"
            print(f"\n{status} {result.eval_name}")
            print(f"  Score: {result.final_score:.2%} (threshold: {result.pass_threshold:.2%})")
            print(f"  Deterministic: {result.deterministic_score:.2%} (weight: 0.6)")
            print(f"  Model-graded: {result.model_score:.2%} (weight: 0.4)")
            print(f"  Cases tested: {result.num_cases}")
            if result.failed_cases:
                print(f"  Failed cases: {result.failed_cases}")

        print("\n" + "=" * 70)
        total_passed = sum(1 for r in self.results if r.passed)
        print(f"TOTAL: {total_passed}/{len(self.results)} evals passed")
        print("=" * 70 + "\n")

    def to_json(self) -> str:
        """Convert results to JSON."""
        results_data = [asdict(r) for r in self.results]
        return json.dumps(results_data, indent=2, default=str)

    @staticmethod
    def _extract_field(data: Dict[str, Any], field_path: str) -> Any:
        """Extract nested field from data dict using dot notation."""
        parts = field_path.split(".")
        current: Any = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, str):
                # Try JSON parsing if current is a JSON string
                try:
                    parsed = json.loads(current)
                    if isinstance(parsed, dict):
                        current = parsed.get(part)
                    else:
                        return None
                except (json.JSONDecodeError, TypeError, AttributeError):
                    return None
            else:
                return None
        return current


def run_evals(eval_dir: Optional[Path] = None) -> int:
    """Main entry point for eval runner."""
    if eval_dir is None:
        eval_dir = Path(__file__).parent.parent / "tests" / "evals"

    runner = EvalRunner(eval_dir)
    results = runner.run_all_evals()
    runner.print_summary()

    # Return 0 if all passed, 1 if any failed
    return 0 if all(r.passed for r in results) else 1
