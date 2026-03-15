"""main.py — Spiral CLI entrypoint.

Subcommands:
  init      Run the interactive setup wizard (lib/setup.py)
  run       Execute spiral.sh with forwarded arguments
  status    Show PRD completion summary
  estimate  Show pre-flight API cost projection for pending stories
"""
import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

SPIRAL_SH = Path(__file__).parent / "spiral.sh"
PRD_FILE = Path(__file__).parent / "prd.json"
RESULTS_TSV = Path(__file__).parent / "results.tsv"
RETRY_COUNTS = Path(__file__).parent / "retry-counts.json"
SCRATCH_DIR = Path(__file__).parent / ".spiral"
CHECKPOINT_FILE = SCRATCH_DIR / "_checkpoint.json"

# ── ANSI colour helpers ───────────────────────────────────────────────────────
_USE_COLOUR = not os.environ.get("NO_COLOR") and sys.stdout.isatty()

_ANSI = {
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "grey": "\033[90m",
    "bold": "\033[1m",
    "reset": "\033[0m",
}


def _c(text: str, colour: str) -> str:
    """Wrap text in ANSI colour codes if colour output is enabled."""
    if not _USE_COLOUR:
        return text
    return f"{_ANSI.get(colour, '')}{text}{_ANSI['reset']}"


# ── Data helpers ──────────────────────────────────────────────────────────────

def _load_prd(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("userStories", [])


def _load_retry_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {k: int(v) for k, v in raw.items()}


def _load_results(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def _load_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _latest_spiral_iter(results: list[dict]) -> int:
    """Return the highest spiral_iter seen in results.tsv, or 0."""
    best = 0
    for row in results:
        try:
            best = max(best, int(row.get("spiral_iter", 0) or 0))
        except (ValueError, TypeError):
            pass
    return best


# ── Status classification ─────────────────────────────────────────────────────

def _classify_stories(
    stories: list[dict],
    retry_counts: dict[str, int],
) -> dict[str, list[dict]]:
    """Split stories into passed / in_progress / skipped / pending buckets."""
    buckets: dict[str, list[dict]] = {
        "passed": [],
        "in_progress": [],
        "skipped": [],
        "pending": [],
    }
    for s in stories:
        sid = s.get("id", "")
        if s.get("passes"):
            buckets["passed"].append(s)
        elif s.get("_skipped"):
            buckets["skipped"].append(s)
        elif retry_counts.get(sid, 0) > 0:
            buckets["in_progress"].append(s)
        else:
            buckets["pending"].append(s)
    return buckets


def _avg_retries(stories: list[dict], retry_counts: dict[str, int]) -> float:
    """Average retry count across a list of stories."""
    if not stories:
        return 0.0
    total = sum(retry_counts.get(s.get("id", ""), 0) for s in stories)
    return total / len(stories)


# ── Rendering ─────────────────────────────────────────────────────────────────

_STATUS_COLOUR = {
    "passed": "green",
    "in_progress": "yellow",
    "skipped": "red",
    "pending": "grey",
}

_STATUS_LABEL = {
    "passed": "passed",
    "in_progress": "in_progress",
    "skipped": "skipped",
    "pending": "pending",
}


def _render_rich(
    buckets: dict[str, list[dict]],
    retry_counts: dict[str, int],
    total: int,
    run_id: str,
    iteration: int,
) -> None:
    """Render using the rich library (preferred when available)."""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    header = f"SPIRAL Run: {run_id or 'unknown'}  |  Iteration: {iteration}"
    console.print(f"\n[bold]{header}[/bold]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("Percentage", justify="right")
    table.add_column("Avg Retries", justify="right")

    colour_map = {
        "passed": "green",
        "in_progress": "yellow",
        "skipped": "red",
        "pending": "grey50",
    }
    for status in ("passed", "in_progress", "skipped", "pending"):
        group = buckets[status]
        count = len(group)
        pct = f"{count / total * 100:.1f}%" if total else "0.0%"
        avg = f"{_avg_retries(group, retry_counts):.1f}"
        col = colour_map[status]
        table.add_row(
            f"[{col}]{_STATUS_LABEL[status]}[/{col}]",
            str(count),
            pct,
            avg,
        )

    console.print(table)
    console.print(f"[dim]Total: {total} stories[/dim]\n")


def _render_plain(
    buckets: dict[str, list[dict]],
    retry_counts: dict[str, int],
    total: int,
    run_id: str,
    iteration: int,
) -> None:
    """Render a plain aligned table (stdlib-only fallback)."""
    header = f"SPIRAL Run: {run_id or 'unknown'}  |  Iteration: {iteration}"
    print(f"\n{_c(header, 'bold')}\n")

    col_widths = (12, 7, 11, 12)
    header_row = (
        _c("Status".ljust(col_widths[0]), "bold"),
        _c("Count".rjust(col_widths[1]), "bold"),
        _c("Percentage".rjust(col_widths[2]), "bold"),
        _c("Avg Retries".rjust(col_widths[3]), "bold"),
    )
    sep = "-" * (sum(col_widths) + 3 * 2)
    print(f"  {'  '.join(header_row)}")
    print(f"  {sep}")

    for status in ("passed", "in_progress", "skipped", "pending"):
        group = buckets[status]
        count = len(group)
        pct = f"{count / total * 100:.1f}%" if total else "0.0%"
        avg = f"{_avg_retries(group, retry_counts):.1f}"
        colour = _STATUS_COLOUR[status]
        label = _c(_STATUS_LABEL[status].ljust(col_widths[0]), colour)
        print(
            f"  {label}  "
            f"{str(count).rjust(col_widths[1])}  "
            f"{pct.rjust(col_widths[2])}  "
            f"{avg.rjust(col_widths[3])}"
        )

    print(f"\n  Total: {total} stories\n")


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_estimate(args):
    """Show pre-flight API cost projection for pending stories."""
    import sys as _sys
    import importlib.util as _ilu

    cost_project_path = Path(__file__).parent / "lib" / "cost_project.py"
    spec = _ilu.spec_from_file_location("cost_project", cost_project_path)
    if spec is None or spec.loader is None:
        print("ERROR: lib/cost_project.py not found.")
        _sys.exit(3)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    argv = [
        "--prd", str(PRD_FILE),
        "--results", str(RESULTS_TSV),
        "--threshold", str(getattr(args, "threshold", 5.00)),
        "--default-tokens", str(getattr(args, "default_tokens", mod.DEFAULT_TOKENS_PER_STORY)),
    ]
    if getattr(args, "model", ""):
        argv += ["--model", args.model]
    if getattr(args, "yes", False):
        argv.append("--yes")

    rc = mod.main(argv)
    _sys.exit(rc)


def cmd_search(args) -> None:
    """Search prd.json stories by natural language query."""
    import sys as _sys

    sys.path.insert(0, str(Path(__file__).parent / "lib"))
    from search_stories import search_stories, format_table  # type: ignore[import-untyped]

    results = search_stories(
        PRD_FILE,
        args.query,
        top_k=args.top,
        scratch_dir=SCRATCH_DIR,
        force_fuzzy=getattr(args, "fuzzy", False),
    )

    if not results:
        print("No matching stories found.")
        _sys.exit(0)

    if getattr(args, "json", False):
        print(json.dumps(results, indent=2))
    else:
        print(format_table(results))
    _sys.exit(0)


def cmd_import_github(args) -> None:
    """Import GitHub Issues as SPIRAL user stories into prd.json."""
    sys.path.insert(0, str(Path(__file__).parent / "lib"))
    from import_github import import_github_issues  # type: ignore[import-untyped]

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print(
            "ERROR: GITHUB_TOKEN environment variable is not set.\n"
            "Create a GitHub token at https://github.com/settings/tokens "
            "and export it as GITHUB_TOKEN.",
            file=sys.stderr,
        )
        sys.exit(1)

    prd_path = str(PRD_FILE)
    if not PRD_FILE.exists():
        print(f"Error: {prd_path} not found", file=sys.stderr)
        sys.exit(1)

    try:
        added, skipped = import_github_issues(
            repo=args.repo,
            label=args.label,
            prd_path=prd_path,
            token=token,
            dry_run=getattr(args, "dry_run", False),
        )
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    for title in skipped:
        print(f"[skip] Duplicate: {title!r}")

    if getattr(args, "dry_run", False):
        if added:
            print(f"\n[dry-run] Would add {len(added)} story/stories:")
            for story in added:
                print(f"  {story['id']} ({story['priority']}) — {story['title']}")
        else:
            print("[dry-run] No new stories to add.")
        return

    if added:
        print(f"Added {len(added)} story/stories to prd.json:")
        for story in added:
            print(f"  {story['id']} ({story['priority']}) — {story['title']}")
    else:
        print("No new stories to add.")


def cmd_compact_prd(args) -> None:
    """Strip transient runtime fields from completed/skipped stories in prd.json."""
    sys.path.insert(0, str(Path(__file__).parent / "lib"))
    from compact_prd import compact_prd  # type: ignore[import-untyped]

    prd_path = str(PRD_FILE)
    if not PRD_FILE.exists():
        print(f"Error: {prd_path} not found", file=sys.stderr)
        sys.exit(1)

    result = compact_prd(
        prd_path,
        backup_dir=str(SCRATCH_DIR),
        dry_run=getattr(args, "dry_run", False),
    )

    n = result["stories_compacted"]
    m = result["fields_removed"]
    saved = result["bytes_saved"]
    backup = result["backup_path"]

    if getattr(args, "dry_run", False):
        print(f"[dry-run] Would compact {n} stories, remove {m} fields")
        return

    if m == 0:
        print("Nothing to compact — no transient fields found in eligible stories.")
        return

    kb_saved = saved / 1024
    print(f"Compacted {n} stories, removed {m} fields, saved {kb_saved:.1f} KB")
    if backup:
        print(f"Backup: {backup}")


def cmd_init(args):  # noqa: ARG001
    """Run the interactive setup wizard."""
    setup_py = Path(__file__).parent / "lib" / "setup.py"
    result = subprocess.run([sys.executable, str(setup_py)], check=False)
    sys.exit(result.returncode)


def cmd_run(args):
    """Forward to spiral.sh with any extra arguments."""
    extra = args.spiral_args or []
    os.execvp("bash", ["bash", str(SPIRAL_SH)] + extra)


def cmd_status(args):
    """Print a color-coded story progress table."""
    prd_path = PRD_FILE
    if not prd_path.exists():
        print("No prd.json found in current directory.")
        sys.exit(1)

    stories = _load_prd(prd_path)
    retry_counts = _load_retry_counts(RETRY_COUNTS)
    results = _load_results(RESULTS_TSV)
    checkpoint = _load_checkpoint(CHECKPOINT_FILE)

    total = len(stories)
    buckets = _classify_stories(stories, retry_counts)

    # Determine run ID and current iteration
    run_id: str = checkpoint.get("run_id", "") or os.environ.get("SPIRAL_RUN_ID", "")
    iteration: int = checkpoint.get("iter", 0) or _latest_spiral_iter(results)

    if getattr(args, "json", False):
        output = {
            "run_id": run_id,
            "iteration": iteration,
            "total": total,
            "statuses": {
                status: {
                    "count": len(group),
                    "percentage": round(len(group) / total * 100, 1) if total else 0.0,
                    "avg_retry_count": round(_avg_retries(group, retry_counts), 2),
                }
                for status, group in buckets.items()
            },
        }
        print(json.dumps(output, indent=2))
        return

    # Rich table (if available), else plain fallback
    try:
        import rich  # noqa: F401
        _render_rich(buckets, retry_counts, total, run_id, iteration)
    except ImportError:
        _render_plain(buckets, retry_counts, total, run_id, iteration)


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

    status_parser = subparsers.add_parser("status", help="Show color-coded story progress table")
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of a table",
    )

    estimate_parser = subparsers.add_parser(
        "estimate",
        help="Show pre-flight API cost projection for pending stories",
    )
    estimate_parser.add_argument(
        "--model",
        default="",
        metavar="MODEL",
        help="Model tier to use for projection (haiku|sonnet|opus)",
    )
    estimate_parser.add_argument(
        "--threshold",
        type=float,
        default=5.00,
        metavar="USD",
        help="Cost warning threshold in USD (default: 5.00; 0 = never prompt)",
    )
    estimate_parser.add_argument(
        "--default-tokens",
        type=int,
        default=8000,
        dest="default_tokens",
        metavar="N",
        help="Fallback tokens/story when history is unavailable (default: 8000)",
    )
    estimate_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt (CI mode)",
    )

    search_parser = subparsers.add_parser(
        "search",
        help="Find stories by natural language query",
    )
    search_parser.add_argument("query", help="Natural language search query")
    search_parser.add_argument(
        "--top",
        type=int,
        default=5,
        metavar="N",
        help="Max results to show (default: 5)",
    )
    search_parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON",
    )
    search_parser.add_argument(
        "--fuzzy",
        action="store_true",
        help="Force fuzzy matching (skip semantic search)",
    )

    compact_parser = subparsers.add_parser(
        "compact-prd",
        help="Strip transient runtime fields from completed/skipped stories in prd.json",
    )
    compact_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what would be removed without writing changes",
    )

    import_gh_parser = subparsers.add_parser(
        "import-github",
        help="Import GitHub Issues as SPIRAL user stories into prd.json",
    )
    import_gh_parser.add_argument(
        "--repo",
        required=True,
        metavar="OWNER/REPO",
        help="GitHub repository in owner/repo format (e.g. anthropics/claude-code)",
    )
    import_gh_parser.add_argument(
        "--label",
        default="spiral",
        metavar="LABEL",
        help="GitHub label to filter issues by (default: spiral)",
    )
    import_gh_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print stories that would be added without modifying prd.json",
    )

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "estimate":
        cmd_estimate(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "compact-prd":
        cmd_compact_prd(args)
    elif args.command == "import-github":
        cmd_import_github(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
