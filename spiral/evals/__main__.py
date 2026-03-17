"""
Entry point for SPIRAL Evals module.

Usage:
    uv run python -m spiral.evals
"""

import sys
from pathlib import Path

# Add lib directory to path for imports
lib_path = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_path))

from evals_runner import run_evals

if __name__ == "__main__":
    sys.exit(run_evals())
