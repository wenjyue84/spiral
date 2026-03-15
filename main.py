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
  dlq           Dead-letter queue management (US-227)
    promote     Move exhausted stories (retry >= SPIRAL_MAX_RETRIES) to DLQ state
    list        Show all dead-lettered stories with failure reason and timestamp
    replay      Re-enqueue a DLQ story after human review
"""
import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SPIRAL_SH = Path(__file__).parent / "spiral.sh"
PRD_FILE = Path(__file__).parent / "prd.json"
RESULTS_TSV = Path(__file__).parent / "results.tsv"
RETRY_COUNTS = Path(__file__).parent / "retry-counts.json"
SCRATCH_DIR = Path(__file__).parent / ".spiral"
CHECKPOINT_FILE = SCRATCH_DIR / "_checkpoint.json"
CALIBRATION_FILE = Path(__file__).parent / "calibration.jsonl"
DLQ_AUDIT_LOG = SCRATCH_DIR / "audit.log"

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


# ── Audit log ────────────────────────────────────────────────────────────────

def _write_audit_log(event: str, payload: dict, audit_path: "Path | None" = None) -> None:
    """Append a JSONL audit entry to .spiral/audit.log."""
    if audit_path is None:
        audit_path = DLQ_AUDIT_LOG
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **payload,
    }
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ── Status classification ─────────────────────────────────────────────────────

def _classify_stories(
    stories: list[dict],
    retry_counts: dict[str, int],
) -> dict[str, list[dict]]:
    """Split stories into passed / in_progress / skipped / dlq / pending buckets."""
    buckets: dict[str, list[dict]] = {
        "passed": [],
        "in_progress": [],
        "skipped": [],
        "dlq": [],
        "pending": [],
    }
    for s in stories:
        sid = s.get("id", "")
        if s.get("passes"):
            buckets["passed"].append(s)
        elif s.get("_dlq"):
            buckets["dlq"].append(s)
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
    "dlq": "grey",
    "pending": "grey",
}

_STATUS_LABEL = {
    "passed": "passed",
    "in_progress": "in_progress",
    "skipped": "skipped",
    "dlq": "dlq",
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
        "dlq": "magenta",
        "pending": "grey50",
    }
    for status in ("passed", "in_progress", "skipped", "dlq", "pending"):
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
    dlq_count = len(buckets.get("dlq", []))
    if dlq_count:
        console.print(f"[magenta bold]⚠ DLQ: {dlq_count} story/stories dead-lettered — run 'spiral dlq list' to review[/magenta bold]")
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

    for status in ("passed", "in_progress", "skipped", "dlq", "pending"):
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

    dlq_count = len(buckets.get("dlq", []))
    if dlq_count:
        print(f"\n  {_c(f'WARNING: {dlq_count} story/stories dead-lettered — run spiral dlq list', 'red')}")
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


# ── DLQ commands (US-227) ─────────────────────────────────────────────────────

def cmd_dlq_promote(args) -> None:  # noqa: ARG001
    """Move stories that exhausted retries into DLQ state in prd.json.

    A story is promoted when its retry count in retry-counts.json is >=
    SPIRAL_MAX_RETRIES (default 3) and it has not already passed or been DLQ'd.
    """
    max_retries = int(os.environ.get("SPIRAL_MAX_RETRIES", "3"))
    dry_run = getattr(args, "dry_run", False)

    if not PRD_FILE.exists():
        print("No prd.json found.", file=sys.stderr)
        sys.exit(1)

    with open(PRD_FILE, encoding="utf-8") as f:
        prd = json.load(f)

    retry_counts = _load_retry_counts(RETRY_COUNTS)
    stories = prd.get("userStories", [])
    promoted: list[str] = []

    for s in stories:
        sid = s.get("id", "")
        if s.get("passes") or s.get("_dlq") or s.get("_skipped") or s.get("_decomposed"):
            continue
        count = retry_counts.get(sid, 0)
        if count >= max_retries:
            if not dry_run:
                s["_dlq"] = True
                s["_dlqMetadata"] = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "retryCount": count,
                    "reason": f"Exhausted {count} retries (SPIRAL_MAX_RETRIES={max_retries})",
                }
                _write_audit_log(
                    "dlq_promote",
                    {"story_id": sid, "retry_count": count, "max_retries": max_retries},
                )
            promoted.append(sid)

    if promoted:
        if not dry_run:
            with open(PRD_FILE, "w", encoding="utf-8") as f:
                json.dump(prd, f, indent=2, ensure_ascii=False)
                f.write("\n")
            print(f"[dlq] Promoted {len(promoted)} story/stories to DLQ: {', '.join(promoted)}")
        else:
            print(f"[dlq] dry-run: would promote {len(promoted)} story/stories: {', '.join(promoted)}")
    else:
        print("[dlq] No stories eligible for DLQ promotion.")


def cmd_dlq_list(args) -> None:
    """List all stories currently in DLQ state."""
    json_out = getattr(args, "json_output", False)

    if not PRD_FILE.exists():
        if json_out:
            print("[]")
        else:
            print("No prd.json found.", file=sys.stderr)
        return

    stories = _load_prd(PRD_FILE)
    dlq_stories = [s for s in stories if s.get("_dlq")]

    if json_out:
        output = [
            {
                "id": s.get("id", ""),
                "title": s.get("title", ""),
                "dlqMetadata": s.get("_dlqMetadata", {}),
            }
            for s in dlq_stories
        ]
        print(json.dumps(output, indent=2))
        return

    if not dlq_stories:
        print("[dlq] No stories in dead-letter queue.")
        return

    print(f"\n{_c('Dead-Letter Queue', 'bold')} — {len(dlq_stories)} story/stories\n")
    col_id = 10
    col_title = 45
    col_ts = 26
    col_retries = 7
    header = (
        _c("ID".ljust(col_id), "bold") + "  "
        + _c("Title".ljust(col_title), "bold") + "  "
        + _c("DLQ Timestamp".ljust(col_ts), "bold") + "  "
        + _c("Retries".rjust(col_retries), "bold")
    )
    sep = "-" * (col_id + col_title + col_ts + col_retries + 6)
    print(f"  {header}")
    print(f"  {sep}")
    for s in dlq_stories:
        meta = s.get("_dlqMetadata", {})
        ts = meta.get("timestamp", "unknown")[:19].replace("T", " ")
        retries = str(meta.get("retryCount", "?"))
        title = s.get("title", "")[:col_title]
        print(
            f"  {s.get('id', '').ljust(col_id)}  "
            f"{title.ljust(col_title)}  "
            f"{ts.ljust(col_ts)}  "
            f"{retries.rjust(col_retries)}"
        )
    print()


def cmd_dlq_replay(args) -> None:
    """Re-enqueue a DLQ story after human review.

    Validates the story is in DLQ state, resets its retry count to 0,
    clears the _dlq flag, and writes an audit log entry.
    """
    story_id: str = args.story
    dry_run = getattr(args, "dry_run", False)

    if not PRD_FILE.exists():
        print("No prd.json found.", file=sys.stderr)
        sys.exit(1)

    with open(PRD_FILE, encoding="utf-8") as f:
        prd = json.load(f)

    stories = prd.get("userStories", [])
    target = next((s for s in stories if s.get("id") == story_id), None)

    if target is None:
        print(f"[dlq] Story '{story_id}' not found in prd.json.", file=sys.stderr)
        sys.exit(1)

    if not target.get("_dlq"):
        print(f"[dlq] Story '{story_id}' is not in DLQ state (current: passes={target.get('passes')}, _skipped={target.get('_skipped')}).", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        print(f"[dlq] dry-run: would replay '{story_id}' (reset retry count, clear _dlq flag)")
        return

    # Clear DLQ fields
    target.pop("_dlq", None)
    target.pop("_dlqMetadata", None)

    # Reset retry count in retry-counts.json
    retry_counts = _load_retry_counts(RETRY_COUNTS)
    retry_counts[story_id] = 0
    RETRY_COUNTS.parent.mkdir(parents=True, exist_ok=True)
    with open(RETRY_COUNTS, "w", encoding="utf-8") as f:
        json.dump(retry_counts, f, indent=2)
        f.write("\n")

    # Write updated prd.json
    with open(PRD_FILE, "w", encoding="utf-8") as f:
        json.dump(prd, f, indent=2, ensure_ascii=False)
        f.write("\n")

    _write_audit_log("dlq_replay", {"story_id": story_id})
    print(f"[dlq] Story '{story_id}' re-enqueued: retry count reset to 0, _dlq cleared.")


def cmd_init(args):  # noqa: ARG001
    """Run the interactive setup wizard."""
    setup_py = Path(__file__).parent / "lib" / "setup.py"
    result = subprocess.run([sys.executable, str(setup_py)], check=False)
    sys.exit(result.returncode)


def cmd_run(args):
    """Forward to spiral.sh with any extra arguments."""
    extra = args.spiral_args or []
    os.execvp("bash", ["bash", str(SPIRAL_SH)] + extra)


def _story_status_icon(story: dict, retry_counts: dict[str, int], unicode_ok: bool = True) -> str:
    """Return a status icon for a story node in the dependency tree."""
    sid = story.get("id", "")
    if story.get("passes"):
        return "\u2713" if unicode_ok else "v"
    if story.get("_dlq") or story.get("_skipped"):
        return "\u2298" if unicode_ok else "x"
    if retry_counts.get(sid, 0) > 0:
        return "~"
    return "\u25cb" if unicode_ok else "o"


def _render_dep_tree(
    stories: list[dict],
    retry_counts: dict[str, int],
    quiet: bool = False,
) -> None:
    """Render an ASCII dependency tree of stories to stdout.

    Root nodes (no dependencies) are shown at the top level.
    Children are indented using Unicode box-drawing characters.
    Cycles are detected and displayed with a [CYCLE] marker.
    """
    # Determine Unicode vs ASCII based on stdout encoding
    try:
        enc = (sys.stdout.encoding or "ascii").lower()
        unicode_ok = enc.startswith(("utf", "unicode"))
    except Exception:
        unicode_ok = False

    if unicode_ok:
        branch = "\u251c\u2500\u2500 "   # ├──
        last   = "\u2514\u2500\u2500 "   # └──
        vert   = "\u2502   "              # │
        blank  = "    "
    else:
        branch = "+-- "
        last   = "`-- "
        vert   = "|   "
        blank  = "    "

    # Index stories by id
    by_id: dict[str, dict] = {s.get("id", ""): s for s in stories if s.get("id")}

    # Build children map: parent_id → [child_id, ...]
    children: dict[str, list[str]] = {sid: [] for sid in by_id}
    has_parent: set[str] = set()
    for s in stories:
        for dep in s.get("dependencies", []):
            if dep in children:
                children[dep].append(s.get("id", ""))
                has_parent.add(s.get("id", ""))

    roots = [sid for sid in by_id if sid not in has_parent]
    roots.sort()

    def _node_label(story: dict) -> str:
        sid = story.get("id", "")
        if quiet:
            return sid
        icon = _story_status_icon(story, retry_counts, unicode_ok=unicode_ok)
        title = story.get("title", "")[:50]
        return f"{icon} {sid}  {title}"

    visited: set[str] = set()

    def _print_node(sid: str, prefix: str, is_last: bool) -> None:
        connector = last if is_last else branch
        story = by_id.get(sid, {"id": sid, "title": "(unknown)"})
        if sid in visited:
            label = sid if quiet else f"[CYCLE] {sid}"
            print(prefix + connector + label)
            return
        visited.add(sid)
        print(prefix + connector + _node_label(story))
        kids = children.get(sid, [])
        kids_sorted = sorted(kids)
        child_prefix = prefix + (blank if is_last else vert)
        for i, kid in enumerate(kids_sorted):
            _print_node(kid, child_prefix, i == len(kids_sorted) - 1)
        visited.discard(sid)  # allow same node in different branches (non-cycle)

    if not roots:
        # All stories have parents — likely all have cycles; just list all
        roots = sorted(by_id.keys())

    print()
    for i, root in enumerate(roots):
        _print_node(root, "", i == len(roots) - 1)
    print()


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

    # ── US-216: --tree flag → ASCII dependency tree ────────────────────────
    if getattr(args, "tree", False):
        quiet = getattr(args, "quiet", False) or os.environ.get("SPIRAL_LOG_LEVEL", "") == "quiet"
        _render_dep_tree(stories, retry_counts, quiet=quiet)
        return

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

    # ── 1. Count prunable admin records via git porcelain ────────────────────
    # On Windows/MSYS the path field in prunable entries is unreliable (git
    # reports the main repo path instead of the original worker path).  We
    # count prunable records and report a single aggregate anomaly rather than
    # one per record.
    result = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )
    prunable_count = result.stdout.count("prunable ")

    if prunable_count > 0:
        anomalies.append({
            "type": "prunable_records",
            "count": prunable_count,
            "safe_to_fix": True,
            "remediation": "Run `git worktree prune` to remove stale admin records.",
            "detail": (
                f"{prunable_count} git worktree admin record(s) are prunable "
                "(gitdir pointer(s) reference non-existent locations)."
            ),
        })

    # ── 2. Scan physical .spiral-workers/ dirs ────────────────────────────────
    # These are the actual worker worktrees on disk.  Use git directly on each
    # worker dir to get HEAD / branch state — avoids MSYS path issues.
    physical_workers: list[Path] = []
    if worktree_base.is_dir():
        physical_workers = sorted(
            p for p in worktree_base.iterdir() if p.is_dir()
        )

    def _msys_to_win(raw: str) -> Path:
        """Convert MSYS-style /c/foo paths to Windows C:/foo on win32."""
        import re
        m = re.match(r"^/([a-zA-Z])/(.*)", raw.replace("\\", "/"))
        if m:
            drive, rest = m.group(1).upper(), m.group(2)
            return Path(f"{drive}:/{rest}")
        return Path(raw)

    # ── 3. Anomaly: worktree directory missing from disk ─────────────────────
    # We derive expected worker paths from `.git/worktrees/` admin dirs.
    git_worktrees_dir = repo_root / ".git" / "worktrees"
    if git_worktrees_dir.is_dir():
        for wt_admin in git_worktrees_dir.iterdir():
            if not wt_admin.is_dir():
                continue
            gitdir_file = wt_admin / "gitdir"
            if not gitdir_file.exists():
                continue
            # gitdir contains path like <worktree>/.git — strip last component
            gitdir_content = gitdir_file.read_text(encoding="utf-8", errors="replace").strip()
            # Handle MSYS-style /c/... paths on Windows
            gitdir_path = _msys_to_win(gitdir_content)
            if not gitdir_path.is_absolute():
                gitdir_path = wt_admin / gitdir_path
            wt_dir = gitdir_path.parent
            try:
                exists = wt_dir.exists()
            except (OSError, ValueError):
                exists = False
            if not exists:
                anomalies.append({
                    "type": "missing_directory",
                    "path": str(wt_dir),
                    "admin_name": wt_admin.name,
                    "safe_to_fix": True,
                    "remediation": "Run `git worktree prune` to remove the stale admin record.",
                    "detail": (
                        f"Worktree admin record '{wt_admin.name}' exists but its "
                        f"directory '{wt_dir}' is missing from disk."
                    ),
                })

    # ── 4. Per-worker checks: detached HEAD, missing branch ──────────────────
    branch_to_workers: dict[str, list[str]] = {}
    for worker_dir in physical_workers:
        # Detached HEAD check
        head_check = subprocess.run(
            ["git", "-C", str(worker_dir), "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
        )
        if head_check.returncode != 0:
            # Distinguish: true detached HEAD vs orphaned directory (admin record pruned)
            sha_check = subprocess.run(
                ["git", "-C", str(worker_dir), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
            )
            if sha_check.returncode != 0:
                # git can't resolve HEAD at all → orphaned worktree directory
                anomalies.append({
                    "type": "orphaned_directory",
                    "path": str(worker_dir),
                    "safe_to_fix": True,
                    "remediation": (
                        f"Remove the orphaned directory: `rm -rf '{worker_dir}'` "
                        "or re-add it as a worktree with `git worktree add`."
                    ),
                    "detail": (
                        "Directory exists in .spiral-workers/ but is no longer a valid "
                        "git worktree (admin record likely pruned)."
                    ),
                })
            else:
                sha = sha_check.stdout.strip() or "unknown"
                anomalies.append({
                    "type": "detached_head",
                    "path": str(worker_dir),
                    "safe_to_fix": False,
                    "remediation": (
                        f"Checkout a branch: `git -C '{worker_dir}' checkout -b <branch-name>`."
                    ),
                    "detail": f"Worktree HEAD is detached at {sha}.",
                })
            continue

        branch_name = head_check.stdout.strip()

        # Missing branch check (branch ref must exist in main repo)
        branch_ref = f"refs/heads/{branch_name}"
        ref_check = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", branch_ref],
            capture_output=True,
            text=True,
        )
        if ref_check.returncode != 0:
            anomalies.append({
                "type": "missing_branch",
                "path": str(worker_dir),
                "branch": branch_name,
                "safe_to_fix": False,
                "remediation": (
                    f"Recreate the branch: `git -C '{worker_dir}' checkout -b {branch_name}`."
                ),
                "detail": (
                    f"Branch '{branch_name}' referenced by worktree no longer exists in the main repo."
                ),
            })
            continue

        branch_to_workers.setdefault(branch_name, []).append(str(worker_dir))

    # ── 5. Anomaly: duplicate branch checkout ────────────────────────────────
    for branch, paths in branch_to_workers.items():
        if len(paths) > 1:
            anomalies.append({
                "type": "duplicate_branch_checkout",
                "branch": branch,
                "paths": paths,
                "safe_to_fix": False,
                "remediation": "Remove a duplicate: `git worktree remove --force <path>`.",
                "detail": (
                    f"Branch '{branch}' is checked out in {len(paths)} worktrees simultaneously."
                ),
            })

    # ── 6. Anomaly: stale locks ───────────────────────────────────────────────
    now = time.time()
    for worker_dir in physical_workers:
        git_ptr = worker_dir / ".git"
        if git_ptr.is_file():
            git_dir_line = git_ptr.read_text(encoding="utf-8", errors="replace").strip()
            if git_dir_line.startswith("gitdir:"):
                raw_path = git_dir_line[len("gitdir:"):].strip()
                # On MSYS, paths may be Windows-style; resolve relative to worker_dir
                git_dir = Path(raw_path)
                if not git_dir.is_absolute():
                    git_dir = worker_dir / git_dir
            else:
                git_dir = worker_dir / ".git"
        else:
            git_dir = worker_dir / ".git"

        if not git_dir.is_dir():
            continue

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
                    "detail": (
                        f"Lock file is {round(age_mins, 1)} minutes old "
                        f"(threshold: {lock_age_limit} min)."
                    ),
                })

    # ── 7. Apply --fix for safe anomalies ────────────────────────────────────
    fixed: list[dict] = []
    skipped_unsafe: list[dict] = []
    if fix_mode:
        run_prune = False
        for a in anomalies:
            if not a["safe_to_fix"]:
                skipped_unsafe.append(a)
                continue
            if a["type"] in ("prunable_records", "missing_directory"):
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

    # ── 8. Output ─────────────────────────────────────────────────────────────
    report: dict = {
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
            print(_c("OK All worktrees are healthy (no anomalies detected).", "green"))
        else:
            print(_c(f"FAIL {len(anomalies)} anomaly(ies) found:", "red"))
            for a in anomalies:
                atype = _c(a["type"], "yellow")
                print(f"\n  [{atype}]")
                print(f"    Detail:      {a.get('detail', '')}")
                if "path" in a:
                    print(f"    Path:        {a['path']}")
                if "paths" in a:
                    print(f"    Paths:       {a['paths']}")
                if "branch" in a:
                    print(f"    Branch:      {a['branch']}")
                if "count" in a:
                    print(f"    Count:       {a['count']}")
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
    status_parser.add_argument(
        "--tree",
        action="store_true",
        help="Render a Unicode/ASCII dependency tree of stories instead of the status table",
    )
    status_parser.add_argument(
        "--quiet",
        action="store_true",
        help="With --tree: show only story IDs (no titles or status icons)",
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

    # ── dlq subcommand (US-227) ───────────────────────────────────────────────
    dlq_parser = subparsers.add_parser(
        "dlq",
        help="Dead-letter queue management for permanently failed stories",
    )
    dlq_subs = dlq_parser.add_subparsers(dest="dlq_command", metavar="COMMAND")

    dlq_promote_parser = dlq_subs.add_parser(
        "promote",
        help="Move exhausted stories (retry >= SPIRAL_MAX_RETRIES) to DLQ state",
    )
    dlq_promote_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what would be promoted without modifying prd.json",
    )

    dlq_list_parser = dlq_subs.add_parser(
        "list",
        help="Show all dead-lettered stories with failure reason and timestamp",
    )
    dlq_list_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output machine-parseable JSON",
    )

    dlq_replay_parser = dlq_subs.add_parser(
        "replay",
        help="Re-enqueue a DLQ story after human review (resets retry count)",
    )
    dlq_replay_parser.add_argument(
        "--story",
        required=True,
        metavar="STORY_ID",
        help="Story ID to replay (e.g. US-123)",
    )
    dlq_replay_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what would change without modifying any files",
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
    elif args.command == "dlq":
        dlq_command = getattr(args, "dlq_command", None)
        if dlq_command == "promote":
            cmd_dlq_promote(args)
        elif dlq_command == "list":
            cmd_dlq_list(args)
        elif dlq_command == "replay":
            cmd_dlq_replay(args)
        else:
            dlq_parser.print_help()
            sys.exit(0)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
