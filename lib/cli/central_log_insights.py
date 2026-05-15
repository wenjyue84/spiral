"""lib/cli/central_log_insights.py — Read-only query CLI for ~/.spiral/central.db.

Subcommands:
    summary           Total runs, projects, stories, cost, date range
    projects          Per-project: runs, pass rate %, cost, last run
    models            Model tier vs pass rate per complexity
    failures          Failure type distribution
    cost-trend        Daily cost trend
    velocity          Stories/hour per project
    runs              Recent runs

All support --json for machine consumption.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any


def _default_db_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".spiral", "central.db")


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or _default_db_path()
    if not os.path.exists(path):
        print(f"No central log found at {path}", file=sys.stderr)
        print("Run SPIRAL at least once with the central-log plugin enabled.", file=sys.stderr)
        sys.exit(1)
    con = sqlite3.connect(path, timeout=5)
    con.row_factory = sqlite3.Row
    return con


# ── ANSI helpers ─────────────────────────────────────────────────────────────

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
    if not _USE_COLOUR:
        return text
    return f"{_ANSI.get(colour, '')}{text}{_ANSI['reset']}"


# ── Subcommands ──────────────────────────────────────────────────────────────


def cmd_summary(args: argparse.Namespace) -> None:
    con = _connect(getattr(args, "db", None))
    row = con.execute("""
        SELECT
            COUNT(*) as total_runs,
            COUNT(DISTINCT project_name) as projects,
            COALESCE(SUM(stories_attempted), 0) as total_attempted,
            COALESCE(SUM(stories_passed), 0) as total_passed,
            COALESCE(SUM(stories_failed), 0) as total_failed,
            COALESCE(SUM(total_cost_usd), 0) as total_cost,
            COALESCE(SUM(total_duration_sec), 0) as total_duration,
            MIN(started_at) as first_run,
            MAX(started_at) as last_run
        FROM runs
    """).fetchone()

    data = dict(row)
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return

    print(_c("SPIRAL Central Log Summary", "bold"))
    print(f"  Runs:      {data['total_runs']}")
    print(f"  Projects:  {data['projects']}")
    print(f"  Stories:   {data['total_attempted']} attempted, {data['total_passed']} passed, {data['total_failed']} failed")
    if data["total_attempted"] > 0:
        rate = data["total_passed"] / data["total_attempted"] * 100
        colour = "green" if rate >= 70 else "yellow" if rate >= 50 else "red"
        print(f"  Pass rate: {_c(f'{rate:.1f}%', colour)}")
    print(f"  Cost:      ${data['total_cost']:.2f}")
    hours = data["total_duration"] / 3600
    print(f"  Duration:  {hours:.1f}h total")
    print(f"  Period:    {data['first_run'] or 'N/A'} — {data['last_run'] or 'N/A'}")
    con.close()


def cmd_projects(args: argparse.Namespace) -> None:
    con = _connect(getattr(args, "db", None))
    rows = con.execute("""
        SELECT
            project_name,
            COUNT(*) as runs,
            COALESCE(SUM(stories_attempted), 0) as attempted,
            COALESCE(SUM(stories_passed), 0) as passed,
            COALESCE(SUM(stories_failed), 0) as failed,
            COALESCE(SUM(total_cost_usd), 0) as cost,
            MAX(started_at) as last_run
        FROM runs
        GROUP BY project_name
        ORDER BY cost DESC
    """).fetchall()

    data = [dict(r) for r in rows]
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return

    print(_c(f"{'Project':<30} {'Runs':>5} {'Pass%':>6} {'Cost':>10} {'Last Run':<20}", "bold"))
    print("-" * 75)
    for r in data:
        rate = (r["passed"] / r["attempted"] * 100) if r["attempted"] > 0 else 0
        colour = "green" if rate >= 70 else "yellow" if rate >= 50 else "red"
        print(
            f"{r['project_name']:<30} {r['runs']:>5} "
            f"{_c(f'{rate:>5.1f}%', colour)} "
            f"${r['cost']:>9.2f} {(r['last_run'] or 'N/A'):<20}"
        )
    con.close()


def cmd_models(args: argparse.Namespace) -> None:
    con = _connect(getattr(args, "db", None))
    project_filter = getattr(args, "project", None)

    query = """
        SELECT
            model,
            estimated_complexity,
            COUNT(*) as attempts,
            SUM(CASE WHEN status = 'pass' THEN 1 ELSE 0 END) as passes,
            AVG(duration_sec) as avg_duration,
            AVG(cost_usd) as avg_cost
        FROM story_attempts
        WHERE model != ''
    """
    params: list[Any] = []
    if project_filter:
        query += " AND project_name = ?"
        params.append(project_filter)
    query += " GROUP BY model, estimated_complexity ORDER BY model, estimated_complexity"

    rows = con.execute(query, params).fetchall()
    data = [dict(r) for r in rows]

    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return

    print(_c(f"{'Model':<10} {'Complexity':<12} {'Attempts':>8} {'Pass%':>6} {'Avg $/story':>12} {'Avg sec':>8}", "bold"))
    print("-" * 60)
    for r in data:
        rate = (r["passes"] / r["attempts"] * 100) if r["attempts"] > 0 else 0
        colour = "green" if rate >= 70 else "yellow" if rate >= 50 else "red"
        complexity = r["estimated_complexity"] or "unknown"
        print(
            f"{r['model']:<10} {complexity:<12} {r['attempts']:>8} "
            f"{_c(f'{rate:>5.1f}%', colour)} "
            f"${r['avg_cost']:>11.4f} {r['avg_duration']:>7.0f}s"
        )
    con.close()


def cmd_failures(args: argparse.Namespace) -> None:
    con = _connect(getattr(args, "db", None))
    top_n = getattr(args, "top", 10)
    project_filter = getattr(args, "project", None)

    query = """
        SELECT failure_type, COUNT(*) as count
        FROM story_attempts
        WHERE status = 'fail' AND failure_type != ''
    """
    params: list[Any] = []
    if project_filter:
        query += " AND project_name = ?"
        params.append(project_filter)
    query += " GROUP BY failure_type ORDER BY count DESC LIMIT ?"
    params.append(top_n)

    rows = con.execute(query, params).fetchall()
    data = [dict(r) for r in rows]

    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return

    print(_c(f"{'Failure Type':<40} {'Count':>6}", "bold"))
    print("-" * 48)
    for r in data:
        print(f"{r['failure_type']:<40} {r['count']:>6}")
    con.close()


def cmd_cost_trend(args: argparse.Namespace) -> None:
    con = _connect(getattr(args, "db", None))
    days = getattr(args, "days", 30)

    rows = con.execute(
        """SELECT DATE(started_at) as day, SUM(total_cost_usd) as cost, COUNT(*) as runs
           FROM runs
           WHERE started_at >= DATE('now', ?)
           GROUP BY day ORDER BY day""",
        (f"-{days} days",),
    ).fetchall()

    data = [dict(r) for r in rows]
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return

    print(_c(f"{'Date':<12} {'Cost':>10} {'Runs':>5}", "bold"))
    print("-" * 30)
    for r in data:
        print(f"{r['day']:<12} ${r['cost']:>9.2f} {r['runs']:>5}")
    con.close()


def cmd_velocity(args: argparse.Namespace) -> None:
    con = _connect(getattr(args, "db", None))
    project_filter = getattr(args, "project", None)

    query = """
        SELECT
            project_name,
            COALESCE(SUM(stories_passed), 0) as passed,
            COALESCE(SUM(total_duration_sec), 0) as total_sec
        FROM runs
    """
    params: list[Any] = []
    if project_filter:
        query += " WHERE project_name = ?"
        params.append(project_filter)
    query += " GROUP BY project_name ORDER BY project_name"

    rows = con.execute(query, params).fetchall()
    data = []
    for r in rows:
        hours = r["total_sec"] / 3600 if r["total_sec"] > 0 else 0
        velocity = r["passed"] / hours if hours > 0 else 0
        data.append({"project_name": r["project_name"], "passed": r["passed"], "hours": round(hours, 1), "stories_per_hour": round(velocity, 2)})

    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return

    print(_c(f"{'Project':<30} {'Passed':>7} {'Hours':>7} {'Stories/hr':>11}", "bold"))
    print("-" * 58)
    for d in data:
        print(f"{d['project_name']:<30} {d['passed']:>7} {d['hours']:>7.1f} {d['stories_per_hour']:>11.2f}")
    con.close()


def cmd_runs(args: argparse.Namespace) -> None:
    con = _connect(getattr(args, "db", None))
    last_n = getattr(args, "last", 10)
    project_filter = getattr(args, "project", None)

    query = "SELECT * FROM runs"
    params: list[Any] = []
    if project_filter:
        query += " WHERE project_name = ?"
        params.append(project_filter)
    query += " ORDER BY started_at DESC LIMIT ?"
    params.append(last_n)

    rows = con.execute(query, params).fetchall()
    data = [dict(r) for r in rows]

    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return

    print(_c(f"{'Run ID':<16} {'Project':<20} {'Iter':>4} {'Pass':>5} {'Fail':>5} {'Cost':>8} {'Started':<20}", "bold"))
    print("-" * 82)
    for r in data:
        passed = r["stories_passed"] or 0
        failed = r["stories_failed"] or 0
        cost = r["total_cost_usd"] or 0
        iters = r["iterations"] or 0
        print(
            f"{(r['run_id'] or '')[:16]:<16} {(r['project_name'] or '')[:20]:<20} "
            f"{iters:>4} {passed:>5} {failed:>5} "
            f"${cost:>7.2f} {(r['started_at'] or 'N/A'):<20}"
        )
    con.close()


# ── Public dispatch (called from main.py) ────────────────────────────────────

def cmd_central_log(args: argparse.Namespace) -> None:
    """Dispatch central-log subcommands."""
    sub = getattr(args, "central_log_command", None)
    dispatch = {
        "summary": cmd_summary,
        "projects": cmd_projects,
        "models": cmd_models,
        "failures": cmd_failures,
        "cost-trend": cmd_cost_trend,
        "velocity": cmd_velocity,
        "runs": cmd_runs,
    }
    handler = dispatch.get(sub or "")
    if handler:
        handler(args)
    else:
        print("Usage: spiral central-log {summary|projects|models|failures|cost-trend|velocity|runs}")
        sys.exit(0)


def register_subparser(subparsers: Any) -> argparse.ArgumentParser:  # noqa: ANN401
    """Register the central-log subcommand tree on the main CLI parser."""
    cl_parser: argparse.ArgumentParser = subparsers.add_parser(
        "central-log",
        help="Cross-project telemetry insights from ~/.spiral/central.db",
    )
    cl_subs = cl_parser.add_subparsers(dest="central_log_command", metavar="COMMAND")

    # summary
    s = cl_subs.add_parser("summary", help="Total runs, projects, stories, cost, date range")
    s.add_argument("--json", action="store_true", help="Output JSON")
    s.add_argument("--db", default=None, help="Path to central.db (default: ~/.spiral/central.db)")

    # projects
    p = cl_subs.add_parser("projects", help="Per-project: runs, pass rate, cost, last run")
    p.add_argument("--json", action="store_true", help="Output JSON")
    p.add_argument("--db", default=None, help="Path to central.db")

    # models
    m = cl_subs.add_parser("models", help="Model tier vs pass rate per complexity")
    m.add_argument("--project", default=None, help="Filter by project name")
    m.add_argument("--json", action="store_true", help="Output JSON")
    m.add_argument("--db", default=None, help="Path to central.db")

    # failures
    f = cl_subs.add_parser("failures", help="Failure type distribution")
    f.add_argument("--top", type=int, default=10, help="Top N failure types (default: 10)")
    f.add_argument("--project", default=None, help="Filter by project name")
    f.add_argument("--json", action="store_true", help="Output JSON")
    f.add_argument("--db", default=None, help="Path to central.db")

    # cost-trend
    ct = cl_subs.add_parser("cost-trend", help="Daily cost trend")
    ct.add_argument("--days", type=int, default=30, help="Lookback days (default: 30)")
    ct.add_argument("--json", action="store_true", help="Output JSON")
    ct.add_argument("--db", default=None, help="Path to central.db")

    # velocity
    v = cl_subs.add_parser("velocity", help="Stories/hour per project")
    v.add_argument("--project", default=None, help="Filter by project name")
    v.add_argument("--json", action="store_true", help="Output JSON")
    v.add_argument("--db", default=None, help="Path to central.db")

    # runs
    r = cl_subs.add_parser("runs", help="Recent runs")
    r.add_argument("--last", type=int, default=10, help="Show last N runs (default: 10)")
    r.add_argument("--project", default=None, help="Filter by project name")
    r.add_argument("--json", action="store_true", help="Output JSON")
    r.add_argument("--db", default=None, help="Path to central.db")

    return cl_parser
