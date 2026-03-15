"""main.py — Spiral CLI entrypoint.

Subcommands:
  init          Run the interactive setup wizard (lib/setup.py)
  run           Execute spiral.sh with forwarded arguments
  status        Show PRD completion summary
  estimate      Show pre-flight API cost projection for pending stories
  graph         Generate Mermaid dependency graph from prd.json
  config        Configuration utilities
    export-env  Export spiral.config.sh SPIRAL_* variables as a .env file
  worktree      Git worktree management utilities
    audit       Audit all spiral worker worktrees for health anomalies
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
CALIBRATION_FILE = Path(__file__).parent / "calibration.jsonl"

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
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return {k: int(v) for k, v in raw.items()}
    except (json.JSONDecodeError, ValueError):
        return {}


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


def _load_drift_reports(scratch_dir: Path) -> dict[str, dict]:
    """Load drift_report.json files from .spiral/workers/<story-id>/.

    Returns a mapping of story_id → drift report dict.
    """
    reports: dict[str, dict] = {}
    workers_dir = scratch_dir / "workers"
    if not workers_dir.is_dir():
        return reports
    for story_dir in workers_dir.iterdir():
        report_file = story_dir / "drift_report.json"
        if report_file.exists():
            try:
                with open(report_file, encoding="utf-8") as f:
                    data = json.load(f)
                story_id = data.get("_storyId") or story_dir.name
                reports[story_id] = data
            except (json.JSONDecodeError, OSError):
                pass
    return reports


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


def _load_calibration(path: Path) -> list[dict]:
    """Load calibration.jsonl records."""
    if not path.exists():
        return []
    records = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return records


def _compute_calibration_stats(records: list[dict]) -> dict:
    """Compute calibration statistics grouped by complexity tier.

    Returns:
        {
            'small': {'median_duration': N, 'count': N, 'stories': [...]},
            'medium': {...},
            'large': {...},
        }
    """
    by_complexity: dict[str, list[dict]] = {"small": [], "medium": [], "large": []}

    for record in records:
        complexity = record.get("estimated_complexity", "unknown")
        if complexity in by_complexity:
            by_complexity[complexity].append(record)

    stats = {}
    for complexity, group in by_complexity.items():
        if not group:
            stats[complexity] = {
                "median_duration": 0,
                "count": 0,
                "stories": [],
                "passed": 0,
                "failed": 0,
            }
            continue

        durations = sorted([r.get("actual_duration_s", 0) for r in group])
        median = durations[len(durations) // 2] if durations else 0

        passed = sum(1 for r in group if r.get("passed"))
        failed = len(group) - passed

        stats[complexity] = {
            "median_duration": median,
            "count": len(group),
            "stories": group,
            "passed": passed,
            "failed": failed,
        }

    return stats


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


# ── SAST indicator rendering (US-262) ─────────────────────────────────────────

_SAST_COLOUR = {"pass": "green", "warn": "yellow", "fail": "red", "blocked-by-sast": "red"}
_SAST_ICON = {"pass": "●", "warn": "◐", "fail": "✗", "blocked-by-sast": "✗"}


def _get_sast_status(story: dict) -> str:  # type: ignore[type-arg]
    """Return SAST status for a story from _sast_status field or gate-report files."""
    return story.get("_sast_status", "")  # type: ignore[no-any-return]


def _load_sast_reports(scratch_dir: Path) -> dict[str, dict]:  # type: ignore[type-arg]
    """Load per-story SAST reports from .spiral/gate-reports/<story-id>_sast.json.

    Returns a mapping of story_id → report dict.
    """
    reports: dict[str, dict] = {}  # type: ignore[type-arg]
    gate_dir = scratch_dir / "gate-reports"
    if not gate_dir.is_dir():
        return reports
    for report_file in gate_dir.glob("*_sast.json"):
        # Extract story ID: filename pattern is <story-id>_sast.json
        story_id = report_file.stem.replace("_sast", "")
        if story_id.startswith("_"):
            continue  # skip _sast_scan.json temporary file
        try:
            with open(report_file, encoding="utf-8") as f:
                data = json.load(f)
            reports[story_id] = data
        except (json.JSONDecodeError, OSError):
            pass
    return reports


def _render_sast_rich(stories: list[dict], sast_reports: dict[str, dict]) -> None:  # type: ignore[type-arg]
    """Render per-story SAST indicator table using Rich."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print("\n[bold]SPIRAL SAST Report[/bold]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Story ID", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Status", justify="center")
    table.add_column("SAST", justify="center")

    for story in stories:
        sid = story.get("id", "")
        title = (story.get("title") or "")[:55]
        passes = story.get("passes", False)
        skipped = story.get("_skipped", False)

        if passes:
            status_cell = "[green]passed[/green]"
        elif skipped:
            status_cell = "[red]skipped[/red]"
        else:
            status_cell = "[grey50]pending[/grey50]"

        sast_status = _get_sast_status(story)
        if sast_status:
            col = _SAST_COLOUR.get(sast_status, "grey50")
            icon = _SAST_ICON.get(sast_status, "?")
            sast_cell = f"[{col}]{icon} {sast_status}[/{col}]"
        elif sid in sast_reports:
            sast_cell = "[green]● pass[/green]"
        else:
            sast_cell = "[grey50]—[/grey50]"

        table.add_row(sid, title, status_cell, sast_cell)

    console.print(table)
    checked = sum(1 for s in stories if _get_sast_status(s) or s.get("id", "") in sast_reports)
    console.print(f"[dim]SAST data available for {checked}/{len(stories)} stories.[/dim]\n")


def _render_sast_plain(stories: list[dict], sast_reports: dict[str, dict]) -> None:  # type: ignore[type-arg]
    """Render per-story SAST indicator table (stdlib fallback)."""
    print(f"\n{_c('SPIRAL SAST Report', 'bold')}\n")
    header = (
        _c("Story ID".ljust(10), "bold"),
        _c("Status".ljust(10), "bold"),
        _c("SAST".ljust(16), "bold"),
        _c("Title", "bold"),
    )
    sep = "-" * 75
    print(f"  {'  '.join(header)}")
    print(f"  {sep}")

    for story in stories:
        sid = story.get("id", "")
        title = (story.get("title") or "")[:45]
        passes = story.get("passes", False)
        skipped = story.get("_skipped", False)

        if passes:
            status_str = _c("passed".ljust(10), "green")
        elif skipped:
            status_str = _c("skipped".ljust(10), "red")
        else:
            status_str = _c("pending".ljust(10), "grey")

        sast_status = _get_sast_status(story)
        if sast_status:
            col = _SAST_COLOUR.get(sast_status, "grey")
            sast_str = _c(sast_status.ljust(16), col)
        elif sid in sast_reports:
            sast_str = _c("pass".ljust(16), "green")
        else:
            sast_str = "—".ljust(16)

        print(f"  {sid.ljust(10)}  {status_str}  {sast_str}  {title}")

    checked = sum(1 for s in stories if _get_sast_status(s) or s.get("id", "") in sast_reports)
    print(f"\n  SAST data available for {checked}/{len(stories)} stories.\n")


# ── Drift indicator rendering (US-260) ────────────────────────────────────────

_DRIFT_COLOUR = {"pass": "green", "warn": "yellow", "fail": "red"}
_DRIFT_ICON = {"pass": "●", "warn": "◐", "fail": "✗"}


def _render_drift_rich(stories: list[dict], drift_reports: dict[str, dict]) -> None:
    """Render per-story drift indicator table using Rich."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print("\n[bold]SPIRAL Drift Report[/bold]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Story ID", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Status", justify="center")
    table.add_column("Drift", justify="center")
    table.add_column("Score", justify="right")

    for story in stories:
        sid = story.get("id", "")
        title = (story.get("title") or "")[:55]
        passes = story.get("passes", False)
        skipped = story.get("_skipped", False)

        if passes:
            status_cell = "[green]passed[/green]"
        elif skipped:
            status_cell = "[red]skipped[/red]"
        else:
            status_cell = "[grey50]pending[/grey50]"

        report = drift_reports.get(sid)
        if report:
            verdict = report.get("verdict", "?")
            score = report.get("driftScore", "?")
            col = _DRIFT_COLOUR.get(verdict, "grey50")
            icon = _DRIFT_ICON.get(verdict, "?")
            drift_cell = f"[{col}]{icon} {verdict}[/{col}]"
            score_cell = f"[{col}]{score}[/{col}]"
        else:
            drift_cell = "[grey50]—[/grey50]"
            score_cell = "[grey50]—[/grey50]"

        table.add_row(sid, title, status_cell, drift_cell, score_cell)

    console.print(table)
    checked = sum(1 for s in stories if s.get("id", "") in drift_reports)
    console.print(f"[dim]Drift data available for {checked}/{len(stories)} stories.[/dim]\n")


def _render_drift_plain(stories: list[dict], drift_reports: dict[str, dict]) -> None:
    """Render per-story drift indicator table (stdlib fallback)."""
    print(f"\n{_c('SPIRAL Drift Report', 'bold')}\n")
    header = (
        _c("Story ID".ljust(10), "bold"),
        _c("Status".ljust(10), "bold"),
        _c("Drift".ljust(8), "bold"),
        _c("Score".rjust(6), "bold"),
        _c("Title", "bold"),
    )
    sep = "-" * 75
    print(f"  {'  '.join(header)}")
    print(f"  {sep}")

    for story in stories:
        sid = story.get("id", "")
        title = (story.get("title") or "")[:45]
        passes = story.get("passes", False)
        skipped = story.get("_skipped", False)

        if passes:
            status_str = _c("passed".ljust(10), "green")
        elif skipped:
            status_str = _c("skipped".ljust(10), "red")
        else:
            status_str = _c("pending".ljust(10), "grey")

        report = drift_reports.get(sid)
        if report:
            verdict = report.get("verdict", "?")
            score = str(report.get("driftScore", "?"))
            col = _DRIFT_COLOUR.get(verdict, "grey")
            drift_str = _c(verdict.ljust(8), col)
            score_str = _c(score.rjust(6), col)
        else:
            drift_str = "—".ljust(8)
            score_str = "—".rjust(6)

        print(f"  {sid.ljust(10)}  {status_str}  {drift_str}  {score_str}  {title}")

    checked = sum(1 for s in stories if s.get("id", "") in drift_reports)
    print(f"\n  Drift data available for {checked}/{len(stories)} stories.\n")


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


def cmd_import_jira(args) -> None:
    """Import Jira issues as SPIRAL user stories into prd.json."""
    sys.path.insert(0, str(Path(__file__).parent / "lib"))
    from import_jira import import_jira_issues  # type: ignore[import-untyped]

    email = os.environ.get("JIRA_USER_EMAIL", "").strip()
    api_token = os.environ.get("JIRA_API_TOKEN", "").strip()

    if not email or not api_token:
        missing = []
        if not email:
            missing.append("JIRA_USER_EMAIL")
        if not api_token:
            missing.append("JIRA_API_TOKEN")
        print(
            f"ERROR: Missing environment variable(s): {', '.join(missing)}\n"
            "Set JIRA_USER_EMAIL and JIRA_API_TOKEN before running this command.\n"
            "Generate an API token at https://id.atlassian.com/manage-profile/security/api-tokens",
            file=sys.stderr,
        )
        sys.exit(1)

    prd_path = str(PRD_FILE)
    if not PRD_FILE.exists():
        print(f"Error: {prd_path} not found", file=sys.stderr)
        sys.exit(1)

    jql = getattr(args, "jql", None)
    project = getattr(args, "project", None)
    if not jql and not project:
        print("ERROR: Provide either --project PROJECT or --jql 'JQL query'", file=sys.stderr)
        sys.exit(1)

    try:
        added, skipped = import_jira_issues(
            host=args.host,
            project=project,
            jql=jql,
            prd_path=prd_path,
            email=email,
            api_token=api_token,
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
                key = story.get("_jiraKey", "")
                key_str = f" [{key}]" if key else ""
                print(f"  {story['id']} ({story['priority']}){key_str} — {story['title']}")
        else:
            print("[dry-run] No new stories to add.")
        return

    if added:
        print(f"Added {len(added)} story/stories to prd.json:")
        for story in added:
            key = story.get("_jiraKey", "")
            key_str = f" [{key}]" if key else ""
            print(f"  {story['id']} ({story['priority']}){key_str} — {story['title']}")
    else:
        print("No new stories to add.")


def cmd_import_csv(args) -> None:
    """Bulk-import user stories from a CSV file into prd.json."""
    sys.path.insert(0, str(Path(__file__).parent / "lib"))
    from import_csv import import_csv_stories  # type: ignore[import-untyped]

    delimiter = args.delimiter.encode("raw_unicode_escape").decode("unicode_escape")

    try:
        added, skipped, errors = import_csv_stories(
            csv_path=args.csv_file,
            prd_path=str(PRD_FILE),
            delimiter=delimiter,
            dry_run=getattr(args, "dry_run", False),
        )
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    for msg in errors:
        print(f"[warn] {msg}")

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


def cmd_graph(args) -> None:
    """Generate Mermaid dependency graph from prd.json."""
    sys.path.insert(0, str(Path(__file__).parent / "lib"))
    from dependency_graph import cmd_graph as _graph  # type: ignore[import-untyped]

    from pathlib import Path as _Path

    output = _Path(args.output) if args.output else None
    rc = _graph(PRD_FILE, output)
    sys.exit(rc)


def cmd_export_report(args) -> None:
    """Generate a Markdown (or JSON) story status report from prd.json."""
    import time

    if not PRD_FILE.exists():
        print(f"Error: {PRD_FILE} not found", file=sys.stderr)
        sys.exit(1)

    stories = _load_prd(PRD_FILE)
    retry_counts = _load_retry_counts(RETRY_COUNTS)
    results = _load_results(RESULTS_TSV)

    total = len(stories)
    buckets = _classify_stories(stories, retry_counts)
    passed_count = len(buckets["passed"])
    pass_rate = round(passed_count / total * 100, 1) if total else 0.0

    # Compute total API cost from results.tsv (best-effort)
    total_cost: float = 0.0
    for row in results:
        try:
            total_cost += float(row.get("cost_usd", 0) or 0)
        except (ValueError, TypeError):
            pass

    # Determine output path
    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path(f"SPIRAL_REPORT_{timestamp_str}.md")

    fmt = getattr(args, "format", "markdown")

    # ── JSON format ─────────────────────────────────────────────────────────
    if fmt == "json":
        def _story_to_dict(s: dict) -> dict:
            sid = s.get("id", "")
            return {
                "id": sid,
                "title": s.get("title", ""),
                "status": (
                    "passed" if s.get("passes")
                    else "skipped" if s.get("_skipped")
                    else "pending"
                ),
                "passedCommit": s.get("_passedCommit"),
                "failureReason": s.get("_failureReason"),
                "retryCount": retry_counts.get(sid, 0),
            }

        output = {
            "generated": timestamp_str,
            "summary": {
                "total": total,
                "passed": passed_count,
                "passRate": pass_rate,
                "totalCostUsd": round(total_cost, 4) if total_cost else None,
            },
            "stories": {
                "passed": [_story_to_dict(s) for s in buckets["passed"]],
                "skipped": [_story_to_dict(s) for s in buckets["skipped"]],
                "pending": [_story_to_dict(s) for s in buckets["pending"]],
            },
        }
        content = json.dumps(output, indent=2)
        out_path.write_text(content, encoding="utf-8")
        print(f"Report written to {out_path}")
        return

    # ── Markdown format ──────────────────────────────────────────────────────
    lines: list[str] = []

    lines.append("# SPIRAL Story Status Report")
    lines.append("")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    lines.append("")

    # Summary section
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Stories | {total} |")
    lines.append(f"| Passed | {passed_count} |")
    lines.append(f"| Failed / Skipped | {len(buckets['skipped'])} |")
    lines.append(f"| Pending | {len(buckets['pending']) + len(buckets['in_progress'])} |")
    lines.append(f"| Pass Rate | {pass_rate}% |")
    if total_cost:
        lines.append(f"| Total API Cost | ${total_cost:.4f} |")
    lines.append("")

    def _story_row(s: dict) -> str:
        sid = s.get("id", "")
        title = s.get("title", "")
        retries = retry_counts.get(sid, 0)
        passed_commit = s.get("_passedCommit", "")
        failure_reason = s.get("_failureReason", "")
        commit_cell = f"`{passed_commit[:8]}`" if passed_commit else "—"
        reason_cell = failure_reason if failure_reason else "—"
        return f"| {sid} | {title} | {retries} | {commit_cell} | {reason_cell} |"

    # Passed Stories
    lines.append(f"## Passed Stories ({len(buckets['passed'])})")
    lines.append("")
    if buckets["passed"]:
        lines.append("| ID | Title | Retries | Commit | Notes |")
        lines.append("|----|-------|---------|--------|-------|")
        for s in buckets["passed"]:
            lines.append(_story_row(s))
    else:
        lines.append("_No stories have passed yet._")
    lines.append("")

    # Failed / Skipped Stories
    skipped_list = buckets["skipped"]
    lines.append(f"## Failed / Skipped Stories ({len(skipped_list)})")
    lines.append("")
    if skipped_list:
        lines.append("| ID | Title | Retries | Commit | Failure Reason |")
        lines.append("|----|-------|---------|--------|----------------|")
        for s in skipped_list:
            lines.append(_story_row(s))
    else:
        lines.append("_No stories skipped._")
    lines.append("")

    # Pending Stories (includes in_progress)
    pending_all = buckets["pending"] + buckets["in_progress"]
    lines.append(f"## Pending Stories ({len(pending_all)})")
    lines.append("")
    if pending_all:
        lines.append("| ID | Title | Retries | Commit | Notes |")
        lines.append("|----|-------|---------|--------|-------|")
        for s in pending_all:
            lines.append(_story_row(s))
    else:
        lines.append("_No pending stories — all done!_")
    lines.append("")

    content = "\n".join(lines)
    out_path.write_text(content, encoding="utf-8")
    print(f"Report written to {out_path}")


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

    # ── US-260: --drift flag → per-story drift indicator table ────────────
    if getattr(args, "drift", False):
        drift_reports = _load_drift_reports(SCRATCH_DIR)
        if getattr(args, "json", False):
            output = [
                {
                    "id": s.get("id", ""),
                    "title": s.get("title", ""),
                    "passes": s.get("passes", False),
                    "drift": drift_reports.get(s.get("id", "")),
                }
                for s in stories
            ]
            print(json.dumps(output, indent=2))
            return
        try:
            import rich  # noqa: F401
            _render_drift_rich(stories, drift_reports)
        except ImportError:
            _render_drift_plain(stories, drift_reports)
        return

    # ── US-262: --sast flag → per-story SAST indicator table ──────────────
    if getattr(args, "sast", False):
        sast_reports = _load_sast_reports(SCRATCH_DIR)
        if getattr(args, "json", False):
            output = [
                {
                    "id": s.get("id", ""),
                    "title": s.get("title", ""),
                    "passes": s.get("passes", False),
                    "sast": _get_sast_status(s) or ("pass" if s.get("id", "") in sast_reports else None),
                    "_sast_warnings": s.get("_sast_warnings"),
                }
                for s in stories
            ]
            print(json.dumps(output, indent=2))
            return
        try:
            import rich  # noqa: F401
            _render_sast_rich(stories, sast_reports)
        except ImportError:
            _render_sast_plain(stories, sast_reports)
        return

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


def cmd_calibration_report(args):
    """Print calibration analysis: estimated vs actual complexity tracking."""
    if not CALIBRATION_FILE.exists():
        print(f"No calibration data found ({CALIBRATION_FILE.name}). Run SPIRAL to record data.")
        return

    records = _load_calibration(CALIBRATION_FILE)
    if not records:
        print("No calibration records found.")
        return

    stats = _compute_calibration_stats(records)

    if getattr(args, "json", False):
        # JSON output
        output = {}
        for complexity, data in stats.items():
            output[complexity] = {
                "median_duration_s": data["median_duration"],
                "count": data["count"],
                "passed": data["passed"],
                "failed": data["failed"],
            }
        print(json.dumps(output, indent=2))
        return

    # Plain table output
    print(f"\n{_c('SPIRAL Complexity Calibration Report', 'bold')}\n")
    print(f"Total records: {len(records)}\n")

    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(show_header=True, header_style="bold")
        table.add_column("Complexity", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Median Duration (s)", justify="right")
        table.add_column("Passed", justify="right", style="green")
        table.add_column("Failed", justify="right", style="red")

        for complexity in ("small", "medium", "large"):
            data = stats[complexity]
            table.add_row(
                complexity,
                str(data["count"]),
                str(data["median_duration"]),
                str(data["passed"]),
                str(data["failed"]),
            )

        console.print(table)

        # Flag underestimated stories (>2x median)
        underestimated = []
        for complexity in ("small", "medium", "large"):
            data = stats[complexity]
            median = data["median_duration"]
            for story in data["stories"]:
                if story.get("actual_duration_s", 0) > median * 2 and story.get("actual_duration_s", 0) > 0:
                    underestimated.append(story)

        if underestimated:
            console.print(f"\n{_c('Underestimated Stories (>2x median for their tier):', 'yellow')}\n")
            underest_table = Table(show_header=True, header_style="bold")
            underest_table.add_column("Story ID", style="cyan")
            underest_table.add_column("Title")
            underest_table.add_column("Est.", justify="right")
            underest_table.add_column("Actual (s)", justify="right")
            underest_table.add_column("Ratio", justify="right")

            for story in underestimated[:10]:  # Show top 10
                story_id = story.get("story_id", "")
                title = story.get("story_title", "")[:40]
                estimated = story.get("estimated_complexity", "?")
                actual = story.get("actual_duration_s", 0)
                complexity = story.get("estimated_complexity", "small")
                median = stats[complexity]["median_duration"]
                ratio = actual / median if median > 0 else 0
                underest_table.add_row(story_id, title, estimated, str(actual), f"{ratio:.1f}x")

            console.print(underest_table)

    except ImportError:
        # Fallback plain text
        for complexity in ("small", "medium", "large"):
            data = stats[complexity]
            median = data["median_duration"]
            count = data["count"]
            passed = data["passed"]
            failed = data["failed"]
            if count > 0:
                print(f"  {complexity:8} | median: {median:6}s | count: {count:4} | ✓ {passed:3} ✗ {failed:3}")


def cmd_worktree_audit(args) -> None:
    """Audit git worktrees for health anomalies (US-231).

    Detects: stale locks, detached HEAD, missing branch, duplicate branch
    checkout, worktree directory missing from disk.

    Exits 0 when clean, 1 when anomalies found (or --fix applied).
    """
    import time

    repo_root = Path(__file__).parent
    worktree_base = repo_root / ".spiral-workers"
    fix_mode: bool = getattr(args, "fix", False)
    json_mode: bool = getattr(args, "json_output", False)
    lock_age_limit: int = 5  # minutes

    anomalies: list[dict] = []

    # ── 1. Parse `git worktree list --porcelain` ─────────────────────────────
    result = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )
    raw = result.stdout

    # Parse porcelain blocks (blank-line-separated)
    worktrees: list[dict] = []
    block: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            if block:
                worktrees.append(block)
                block = {}
            continue
        if line.startswith("worktree "):
            block["path"] = line[len("worktree "):].strip()
        elif line.startswith("HEAD "):
            block["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            block["branch"] = line[len("branch "):].strip()
        elif line == "detached":
            block["detached"] = True
        elif line.startswith("prunable"):
            block["prunable"] = True
        elif line.startswith("locked"):
            block["locked"] = True
    if block:
        worktrees.append(block)

    # Skip the main worktree (first entry)
    worker_worktrees = worktrees[1:] if len(worktrees) > 1 else []

    # ── 2. Anomaly: worktree directory missing from disk ─────────────────────
    for wt in worker_worktrees:
        wt_path = Path(wt.get("path", ""))
        if not wt_path.exists():
            anomalies.append({
                "type": "missing_directory",
                "path": str(wt_path),
                "safe_to_fix": True,
                "remediation": "Run `git worktree prune` to remove the stale admin record.",
                "detail": "Git admin record exists but the worktree directory is missing from disk.",
            })

    # ── 3. Anomaly: prunable admin records ───────────────────────────────────
    for wt in worker_worktrees:
        if wt.get("prunable"):
            wt_path = wt.get("path", "<unknown>")
            anomalies.append({
                "type": "prunable_record",
                "path": str(wt_path),
                "safe_to_fix": True,
                "remediation": "Run `git worktree prune` to clean up this stale record.",
                "detail": "Git reports this worktree as prunable (gitdir points to non-existent location).",
            })

    # ── 4. Anomaly: detached HEAD ─────────────────────────────────────────────
    for wt in worker_worktrees:
        if wt.get("detached"):
            wt_path = wt.get("path", "<unknown>")
            anomalies.append({
                "type": "detached_head",
                "path": str(wt_path),
                "safe_to_fix": False,
                "remediation": f"Manually checkout a branch: `git -C '{wt_path}' checkout -b <branch-name>`.",
                "detail": f"Worktree HEAD is detached at {wt.get('head', 'unknown')}.",
            })

    # ── 5. Anomaly: missing branch ────────────────────────────────────────────
    for wt in worker_worktrees:
        branch_ref = wt.get("branch", "")
        if not branch_ref or wt.get("detached"):
            continue
        branch_name = branch_ref.replace("refs/heads/", "")
        check = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", branch_ref],
            capture_output=True,
            text=True,
        )
        if check.returncode != 0:
            wt_path = wt.get("path", "<unknown>")
            anomalies.append({
                "type": "missing_branch",
                "path": str(wt_path),
                "branch": branch_name,
                "safe_to_fix": False,
                "remediation": f"Recreate the branch: `git -C '{wt_path}' checkout -b {branch_name}`.",
                "detail": f"Branch '{branch_name}' referenced by worktree no longer exists.",
            })

    # ── 6. Anomaly: duplicate branch checkout ────────────────────────────────
    branch_to_paths: dict[str, list[str]] = {}
    for wt in worker_worktrees:
        branch_ref = wt.get("branch", "")
        if not branch_ref or wt.get("detached"):
            continue
        branch_name = branch_ref.replace("refs/heads/", "")
        branch_to_paths.setdefault(branch_name, []).append(wt.get("path", "<unknown>"))

    for branch, paths in branch_to_paths.items():
        if len(paths) > 1:
            anomalies.append({
                "type": "duplicate_branch_checkout",
                "branch": branch,
                "paths": paths,
                "safe_to_fix": False,
                "remediation": f"Remove duplicate worktree: `git worktree remove --force <path>`.",
                "detail": f"Branch '{branch}' is checked out in {len(paths)} worktrees simultaneously.",
            })

    # ── 7. Anomaly: stale locks ───────────────────────────────────────────────
    if worktree_base.is_dir():
        for worker_dir in worktree_base.iterdir():
            if not worker_dir.is_dir():
                continue
            # Resolve .git pointer to find actual git dir
            git_ptr = worker_dir / ".git"
            if git_ptr.is_file():
                git_dir_line = git_ptr.read_text(encoding="utf-8", errors="replace").strip()
                if git_dir_line.startswith("gitdir:"):
                    git_dir = Path(git_dir_line[len("gitdir:"):].strip())
                else:
                    git_dir = worker_dir / ".git"
            else:
                git_dir = worker_dir / ".git"

            if not git_dir.is_dir():
                continue

            now = time.time()
            for lock_file in git_dir.glob("*.lock"):
                try:
                    age_secs = now - lock_file.stat().st_mtime
                    age_mins = age_secs / 60
                except OSError:
                    age_mins = 0.0

                if age_mins >= lock_age_limit:
                    anomalies.append({
                        "type": "stale_lock",
                        "path": str(lock_file),
                        "age_minutes": round(age_mins, 1),
                        "safe_to_fix": True,
                        "remediation": f"Remove the stale lock: `rm '{lock_file}'`.",
                        "detail": f"Lock file is {round(age_mins, 1)} minutes old (threshold: {lock_age_limit} min).",
                    })

    # ── 8. Apply --fix for safe anomalies ────────────────────────────────────
    fixed: list[dict] = []
    skipped_unsafe: list[dict] = []
    if fix_mode:
        run_prune = False
        for a in anomalies:
            if not a["safe_to_fix"]:
                skipped_unsafe.append(a)
                continue
            if a["type"] in ("missing_directory", "prunable_record"):
                run_prune = True
                fixed.append(a)
            elif a["type"] == "stale_lock":
                lock_path = Path(a["path"])
                try:
                    lock_path.unlink(missing_ok=True)
                    fixed.append(a)
                except OSError as exc:
                    a["fix_error"] = str(exc)
                    skipped_unsafe.append(a)

        if run_prune:
            subprocess.run(
                ["git", "-C", str(repo_root), "worktree", "prune"],
                capture_output=True,
            )

    # ── 9. Output ─────────────────────────────────────────────────────────────
    report = {
        "anomalies": anomalies,
        "total": len(anomalies),
        "clean": len(anomalies) == 0,
    }
    if fix_mode:
        report["fixed"] = len(fixed)
        report["skipped_unsafe"] = len(skipped_unsafe)

    if json_mode:
        print(json.dumps(report, indent=2))
    else:
        if report["clean"]:
            print(_c("✓ All worktrees are healthy (no anomalies detected).", "green"))
        else:
            print(_c(f"✗ {len(anomalies)} anomaly(ies) found:", "red"))
            for a in anomalies:
                atype = _c(a["type"], "yellow")
                print(f"\n  [{atype}]")
                print(f"    Detail:      {a.get('detail', '')}")
                path_key = "path" if "path" in a else ("paths" if "paths" in a else None)
                if path_key:
                    print(f"    Path:        {a[path_key]}")
                if "branch" in a:
                    print(f"    Branch:      {a['branch']}")
                if "age_minutes" in a:
                    print(f"    Age:         {a['age_minutes']} min")
                safe = _c("yes", "green") if a["safe_to_fix"] else _c("no (manual action needed)", "red")
                print(f"    Safe fix:    {safe}")
                print(f"    Remediation: {a['remediation']}")
            if fix_mode:
                print(f"\n  Fixed: {len(fixed)}  |  Unsafe (skipped): {len(skipped_unsafe)}")

    sys.exit(0 if report["clean"] else 1)


def cmd_config_export_env(args) -> None:
    """Export spiral.config.sh SPIRAL_* variables to a .env file.

    Parses variable assignments from spiral.config.sh, writes KEY=VALUE
    lines to a .env file compatible with 'docker run --env-file' and
    GitHub Actions env-file syntax.  Sensitive variable names (containing
    TOKEN, KEY, or SECRET) are masked in the stdout preview but written
    in full to the output file.
    """
    import re

    # ── Locate spiral.config.sh ───────────────────────────────────────────
    config_env = os.environ.get("SPIRAL_CONFIG_PATH", "").strip()
    if config_env:
        config_file = Path(config_env)
    else:
        # Try cwd first (how spiral.sh resolves it), then next to main.py
        cwd_config = Path.cwd() / "spiral.config.sh"
        config_file = cwd_config if cwd_config.exists() else Path(__file__).parent / "spiral.config.sh"

    if not config_file.exists():
        print(
            f"ERROR: spiral.config.sh not found at {config_file}\n"
            "Set SPIRAL_CONFIG_PATH or run from your project root.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Determine output path ─────────────────────────────────────────────
    output_arg = getattr(args, "output", None)
    output_path = Path(output_arg) if output_arg else SCRATCH_DIR / ".env"

    # ── Parse the config file ─────────────────────────────────────────────
    # Match both  `export SPIRAL_VAR=value`  and  `SPIRAL_VAR=value`
    assign_re = re.compile(r"^\s*(?:export\s+)?(SPIRAL_[A-Z0-9_]+)=(.*?)(?:\s*#.*)?$")
    # Detect dynamic bash expressions: $VAR, ${VAR}, $(cmd), backticks
    dynamic_re = re.compile(r"(\$\(|`|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*)")
    # Sensitive variable names
    sensitive_re = re.compile(r"(TOKEN|KEY|SECRET)", re.IGNORECASE)

    entries: list[tuple[str, str]] = []   # (key, cleaned_value)
    dynamic_warnings: list[str] = []

    with open(config_file, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            m = assign_re.match(line)
            if not m:
                continue

            key = m.group(1)
            raw_val = m.group(2).strip()

            # Strip surrounding single or double quotes
            if len(raw_val) >= 2 and raw_val[0] == raw_val[-1] and raw_val[0] in ('"', "'"):
                raw_val = raw_val[1:-1]

            # Warn about dynamic expressions
            if dynamic_re.search(raw_val):
                dynamic_warnings.append(
                    f"  line {lineno}: {key} contains a dynamic expression "
                    f"(value may be incorrect): {raw_val[:60]!r}"
                )

            entries.append((key, raw_val))

    if not entries:
        print(f"No SPIRAL_* variables found in {config_file}.")
        sys.exit(0)

    # ── Write .env file ───────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    env_lines = [f"{key}={val}" for key, val in entries]
    output_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    # ── Stdout preview ────────────────────────────────────────────────────
    print(f"Exported {len(entries)} variable(s) to {output_path}\n")
    print("Preview (sensitive values masked with ***):")
    for key, val in entries:
        if sensitive_re.search(key):
            display = "***"
        elif len(val) > 60:
            display = val[:57] + "..."
        else:
            display = val
        print(f"  {key}={display}")

    if dynamic_warnings:
        print(
            f"\n[warn] {len(dynamic_warnings)} dynamic bash expression(s) detected — "
            "static extraction may be incomplete or incorrect:"
        )
        for w in dynamic_warnings:
            print(w)

    print(
        "\n[ok] .env is compatible with 'docker run --env-file' "
        "and GitHub Actions env-file syntax."
    )


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
    status_parser.add_argument(
        "--drift",
        action="store_true",
        help="Show per-story drift indicator column (green/yellow/red) from Phase I drift check",
    )
    status_parser.add_argument(
        "--sast",
        action="store_true",
        help="Show per-story SAST column (pass/warn/fail) from Phase G Semgrep scan",
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

    import_jira_parser = subparsers.add_parser(
        "import-jira",
        help="Import Jira issues as SPIRAL user stories into prd.json",
    )
    import_jira_parser.add_argument(
        "--host",
        required=True,
        metavar="HOST",
        help="Jira Cloud hostname (e.g. mycompany.atlassian.net)",
    )
    import_jira_parser.add_argument(
        "--project",
        default=None,
        metavar="PROJECT",
        help="Jira project key used to build a default JQL filter (e.g. ENG)",
    )
    import_jira_parser.add_argument(
        "--jql",
        default=None,
        metavar="JQL",
        help="Raw JQL query to select issues (overrides --project filter)",
    )
    import_jira_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print stories that would be added without modifying prd.json",
    )

    import_csv_parser = subparsers.add_parser(
        "import-csv",
        help="Bulk-import user stories from a CSV spreadsheet into prd.json",
    )
    import_csv_parser.add_argument(
        "csv_file",
        metavar="CSV_FILE",
        help="Path to the CSV file containing stories",
    )
    import_csv_parser.add_argument(
        "--delimiter",
        default=",",
        metavar="CHAR",
        help="CSV field delimiter (default: comma). Use '\\t' for TSV files.",
    )
    import_csv_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print stories that would be added without modifying prd.json",
    )

    graph_parser = subparsers.add_parser(
        "graph",
        help="Generate Mermaid dependency graph from prd.json",
    )
    graph_parser.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Write graph to FILE (e.g. docs/dependency-graph.md); default: stdout",
    )

    report_parser = subparsers.add_parser(
        "export-report",
        help="Generate a Markdown story status report from prd.json",
    )
    report_parser.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Write report to FILE; default: SPIRAL_REPORT_<timestamp>.md in current directory",
    )
    report_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format: markdown (default) or json for CI artifact ingestion",
    )

    config_parser = subparsers.add_parser(
        "config",
        help="Configuration utilities",
    )
    config_subs = config_parser.add_subparsers(dest="config_command", metavar="COMMAND")
    export_env_parser = config_subs.add_parser(
        "export-env",
        help="Export spiral.config.sh SPIRAL_* variables as a .env file",
    )
    export_env_parser.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help=(
            "Write .env to FILE (default: .spiral/.env). "
            "Compatible with 'docker run --env-file' and GitHub Actions env-file syntax."
        ),
    )

    # ── worktree subcommand (US-231) ──────────────────────────────────────────
    worktree_parser = subparsers.add_parser(
        "worktree",
        help="Git worktree management utilities",
    )
    worktree_subs = worktree_parser.add_subparsers(dest="worktree_command", metavar="COMMAND")
    audit_parser = worktree_subs.add_parser(
        "audit",
        help="Audit all spiral worker worktrees for health anomalies",
    )
    audit_parser.add_argument(
        "--fix",
        action="store_true",
        dest="fix",
        help="Auto-resolve safe anomalies (prune missing records, remove stale locks)",
    )
    audit_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output machine-parseable JSON instead of human-readable text",
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
    elif args.command == "import-jira":
        cmd_import_jira(args)
    elif args.command == "import-csv":
        cmd_import_csv(args)
    elif args.command == "graph":
        cmd_graph(args)
    elif args.command == "export-report":
        cmd_export_report(args)
    elif args.command == "config":
        config_command = getattr(args, "config_command", None)
        if config_command == "export-env":
            cmd_config_export_env(args)
        else:
            config_parser.print_help()
            sys.exit(0)
    elif args.command == "worktree":
        worktree_command = getattr(args, "worktree_command", None)
        if worktree_command == "audit":
            cmd_worktree_audit(args)
        else:
            worktree_parser.print_help()
            sys.exit(0)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
