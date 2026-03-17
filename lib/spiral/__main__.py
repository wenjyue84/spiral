"""Entry point for spiral package module execution."""

import sys
from pathlib import Path

# Add lib/ to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Check if subcommand is evals
if len(sys.argv) > 1 and sys.argv[1] == "evals":
    from spiral.evals import main

    sys.argv.pop(1)  # Remove 'evals' from args
    main()
else:
    print("Usage: python -m spiral.evals")
    sys.exit(1)
