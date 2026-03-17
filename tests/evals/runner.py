"""SPIRAL Evals runner — Orchestrates evaluation suite execution."""

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from evals.graders import DeterministicGrader, ModelGradedRubric


@dataclass
class TestCase:
    """Single evaluation test case."""

    input: str
    expected_output: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class EvalScore:
    """Score for a single eval."""

    eval_id: str
    eval_name: str
    total_tests: int
    passed_tests: int
    average_score: float
    status: str  # "pass" or "fail"
    details: List[Dict[str, Any]]


class EvalsRunner:
    """Main orchestrator for running SPIRAL evals."""

    def __init__(self, evals_dir: Path):
        """Initialize runner with evals directory."""
        self.evals_dir = evals_dir
        self.configs_dir = evals_dir / "configs"
        self.datasets_dir = evals_dir / "datasets"

    def load_eval_config(self, eval_file: Path) -> Dict[str, Any]:
        """Load YAML eval configuration."""
        with open(eval_file) as f:
            return yaml.safe_load(f)

    def load_dataset(self, csv_file: Path) -> List[TestCase]:
        """Load CSV dataset into TestCase objects."""
        test_cases = []
        with open(csv_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                test_cases.append(
                    TestCase(
                        input=row.get("input", ""),
                        expected_output=row.get("expected_output"),
                        metadata={k: v for k, v in row.items() if k not in ["input", "expected_output"]},
                    )
                )
        return test_cases

    def evaluate_single_test(
        self,
        test_case: TestCase,
        grading_criteria: List[Dict[str, Any]],
        model: Optional[str] = None,
    ) -> tuple[List[Dict[str, Any]], float]:
        """Evaluate a single test case against grading criteria."""
        results = []
        scores = []

        for criterion in grading_criteria:
            criterion_type = criterion.get("type")

            if criterion_type == "deterministic":
                result = DeterministicGrader.grade(
                    test_case.expected_output or "",
                    criterion.get("params", {}),
                )
                results.append(
                    {
                        "criterion": criterion.get("name", criterion_type),
                        "passed": result.passed,
                        "score": result.score,
                        "reasoning": result.reasoning,
                    }
                )
                scores.append(result.score)
            elif criterion_type == "model_graded":
                # Skip model-graded rubrics for now (placeholder for future LLM-judge)
                # Still include in results for visibility, but don't count toward score
                result = ModelGradedRubric.grade(
                    test_case.expected_output or "",
                    criterion.get("rubric", {}),
                    model,
                )
                results.append(
                    {
                        "criterion": criterion.get("name", criterion_type),
                        "passed": result.passed,
                        "score": result.score,
                        "reasoning": f"[PLACEHOLDER] {result.reasoning}",
                        "not_yet_implemented": True,
                    }
                )
                # Don't add to scores - model-graded rubrics aren't evaluated yet

        average_score = sum(scores) / len(scores) if scores else 0.0
        return results, average_score

    def run_eval(self, eval_config: Dict[str, Any]) -> EvalScore:
        """Run a single eval configuration."""
        eval_id = eval_config.get("id")
        eval_name = eval_config.get("name", eval_id)

        # Load dataset
        data_source = eval_config.get("data_source")
        dataset_file = self.datasets_dir / data_source
        test_cases = self.load_dataset(dataset_file)

        # Get grading criteria
        grading_criteria = eval_config.get("testing_criteria", [])
        model = eval_config.get("model")

        # Evaluate all test cases
        all_results = []
        all_scores = []
        passed_count = 0

        for i, test_case in enumerate(test_cases):
            test_results, avg_score = self.evaluate_single_test(test_case, grading_criteria, model)

            all_scores.append(avg_score)
            all_results.append(
                {
                    "test_index": i,
                    "input": test_case.input[:100],  # Truncate for readability
                    "criteria_results": test_results,
                    "average_score": avg_score,
                }
            )

            # Test passes if all deterministic criteria passed (ignore model-graded placeholders)
            deterministic_results = [r for r in test_results if not r.get("not_yet_implemented", False)]
            if deterministic_results and all(r["passed"] for r in deterministic_results):
                passed_count += 1

        # Calculate overall eval stats
        overall_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
        pass_rate = passed_count / len(test_cases) if test_cases else 0.0
        status = "pass" if pass_rate >= 0.8 else "fail"  # 80% pass threshold

        return EvalScore(
            eval_id=eval_id,
            eval_name=eval_name,
            total_tests=len(test_cases),
            passed_tests=passed_count,
            average_score=overall_score,
            status=status,
            details=all_results,
        )

    def run_all_evals(self) -> List[EvalScore]:
        """Run all evals in configs directory."""
        results = []

        # Find all YAML files in configs directory
        config_files = sorted(self.configs_dir.glob("*.yaml"))

        for config_file in config_files:
            try:
                config = self.load_eval_config(config_file)
                score = self.run_eval(config)
                results.append(score)
            except Exception as e:
                # If eval fails to load/run, still report it
                results.append(
                    EvalScore(
                        eval_id=config_file.stem,
                        eval_name=f"Error loading {config_file.name}",
                        total_tests=0,
                        passed_tests=0,
                        average_score=0.0,
                        status="fail",
                        details=[{"error": str(e)}],
                    )
                )

        return results

    @staticmethod
    def print_summary(results: List[EvalScore]) -> None:
        """Print summary of eval results."""
        print("\n" + "=" * 70)
        print("SPIRAL EVALS SUMMARY")
        print("=" * 70)

        total_evals = len(results)
        passed_evals = sum(1 for r in results if r.status == "pass")
        failed_evals = total_evals - passed_evals

        for result in results:
            status_symbol = "[PASS]" if result.status == "pass" else "[FAIL]"
            print(
                f"{status_symbol} {result.eval_name:40s} "
                f"{result.passed_tests}/{result.total_tests} tests "
                f"({result.average_score:.2%} avg score)"
            )

        print("\n" + "-" * 70)
        print(f"Total: {total_evals} evals | Passed: {passed_evals} | Failed: {failed_evals}")
        print("=" * 70 + "\n")

    @staticmethod
    def save_results(results: List[EvalScore], output_file: Path) -> None:
        """Save detailed results to JSON."""
        data = {
            "summary": {"total": len(results), "passed": sum(1 for r in results if r.status == "pass")},
            "evals": [asdict(r) for r in results],
        }
        with open(output_file, "w") as f:
            json.dump(data, f, indent=2)
