"""Entry point for spiral.evals module execution.

Run with: python -m spiral.evals
"""

import sys
from pathlib import Path

# Add project root paths to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "tests"))
sys.path.insert(0, str(project_root / "lib"))

from tests.evals.runner import EvalsRunner


def main():
    """Main entry point for evals runner."""
    evals_dir = project_root / "tests" / "evals"

    if not evals_dir.exists():
        print(f"Error: evals directory not found at {evals_dir}")
        sys.exit(1)

    # Run all evals
    runner = EvalsRunner(evals_dir)
    results = runner.run_all_evals()

    # Print summary
    runner.print_summary(results)

    # Save detailed results
    output_file = project_root / ".spiral" / "evals_results.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    runner.save_results(results, output_file)
    print(f"Detailed results saved to {output_file}\n")

    # Exit with error code if any eval failed
    failed = sum(1 for r in results if r.status == "fail")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
