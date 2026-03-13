"""main.py — Spiral CLI entrypoint.

Subcommands:
  init    Run the interactive setup wizard (lib/setup.py)
  run     Execute spiral.sh with forwarded arguments
  status  Show PRD completion summary
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SPIRAL_SH = Path(__file__).parent / "spiral.sh"
PRD_FILE = Path(__file__).parent / "prd.json"


def cmd_init(args):  # noqa: ARG001
    """Run the interactive setup wizard."""
    setup_py = Path(__file__).parent / "lib" / "setup.py"
    result = subprocess.run([sys.executable, str(setup_py)], check=False)
    sys.exit(result.returncode)


def cmd_run(args):
    """Forward to spiral.sh with any extra arguments."""
    extra = args.spiral_args or []
    os.execvp("bash", ["bash", str(SPIRAL_SH)] + extra)


def cmd_status(args):  # noqa: ARG001
    """Print a concise PRD completion summary."""
    prd_path = PRD_FILE
    if not prd_path.exists():
        print("No prd.json found in current directory.")
        sys.exit(1)

    with open(prd_path, encoding="utf-8") as f:
        prd = json.load(f)

    stories = prd.get("userStories", [])
    total = len(stories)
    passed = sum(1 for s in stories if s.get("passes", False))
    pending = total - passed
    pct = int(passed / total * 100) if total else 0

    print(f"{passed}/{total} stories complete ({pct}%) -> {pending} pending")


def main():
    parser = argparse.ArgumentParser(
        prog="spiral",
        description="Spiral autonomous development loop CLI",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    subparsers.add_parser("init", help="Run the interactive setup wizard")

    run_parser = subparsers.add_parser("run", help="Execute spiral.sh (forwards all flags)")
    run_parser.add_argument("spiral_args", nargs=argparse.REMAINDER, metavar="ARGS",
                            help="Arguments forwarded to spiral.sh")

    subparsers.add_parser("status", help="Show PRD completion summary")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
