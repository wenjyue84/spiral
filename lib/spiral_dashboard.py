#!/usr/bin/env python3
"""spiral_dashboard.py — Generate HTML metrics dashboard for SPIRAL sessions.

Reads prd.json, results.tsv, and retry-counts.json to produce a self-contained
HTML dashboard with velocity trends, model performance, retry analysis,
bottlenecks, and decomposition effectiveness.

stdlib-only — no external dependencies.

Usage:
    python lib/spiral_dashboard.py --prd prd.json --results results.tsv --open
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
from statistics import median

# Force UTF-8 stdout — prevents UnicodeEncodeError on Windows cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── Cost Constants ───────────────────────────────────────────────────────────
COST_PER_HOUR = {"haiku": 0.04, "sonnet": 0.24, "opus": 2.40}

# ── Data Loaders ─────────────────────────────────────────────────────────────

def load_prd(path: str) -> dict:
    """Load prd.json, return full dict. Returns empty structure if missing."""
    if not os.path.isfile(path):
        return {"userStories": []}
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def load_results(path: str) -> list[dict]:
    """Load results.tsv, coerce numeric fields. Returns [] if missing."""
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            for key in ("duration_sec", "retry_num", "spiral_iter", "ralph_iter",
                        "input_tokens", "output_tokens"):
                if key in row and row[key]:
                    try:
                        row[key] = int(row[key])
                    except (ValueError, TypeError):
                        row[key] = 0
            rows.append(row)
    return rows


def load_retries(path: str) -> dict:
    """Load retry-counts.json. Returns {} if missing."""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def load_iter_summary(path: str) -> dict:
    """Load _iteration_summary.json. Returns {} if missing or invalid."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def load_progress(path: str, max_entries: int = 10) -> list[str]:
    """Load progress.txt and return last *max_entries* iteration sections.

    Splits on ``## Iteration`` headers.  Returns [] if file is absent or empty.
    """
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    if not content.strip():
        return []
    sections = re.split(r"(?=^## Iteration)", content, flags=re.MULTILINE)
    # Keep only sections that actually start with the header
    sections = [s.strip() for s in sections if s.strip().startswith("## Iteration")]
    return sections[-max_entries:]


# ── Manual skip IDs (from environment) ───────────────────────────────────────

def _get_manual_skip_ids() -> set[str]:
    """Return set of story IDs from SPIRAL_SKIP_STORY_IDS env var."""
    raw = os.environ.get("SPIRAL_SKIP_STORY_IDS", "")
    return {s.strip() for s in raw.split(",") if s.strip()}


# ── Metrics Computation ──────────────────────────────────────────────────────

def compute_overview(prd: dict, results: list[dict]) -> dict:
    stories = prd.get("userStories", [])
    total = len(stories)
    passed = sum(1 for s in stories if s.get("passes"))
    decomposed = sum(1 for s in stories if s.get("_decomposed"))
    sub_stories = sum(1 for s in stories if s.get("_decomposedFrom"))
    skipped = sum(1 for s in stories if s.get("_skipped"))
    pending = sum(1 for s in stories if not s.get("passes") and not s.get("_decomposed") and not s.get("_skipped"))
    effective_total = total - decomposed
    completion_pct = (passed / effective_total * 100) if effective_total > 0 else 0

    # Time range from results
    timestamps = []
    for r in results:
        ts = r.get("timestamp", "")
        if ts:
            try:
                timestamps.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
            except (ValueError, TypeError):
                pass

    elapsed_str = "N/A"
    if len(timestamps) >= 2:
        delta = max(timestamps) - min(timestamps)
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60
        elapsed_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"

    iters = max((r.get("spiral_iter", 0) for r in results), default=0) if results else 0

    est_cost = sum(
        r.get("duration_sec", 0) / 3600 * COST_PER_HOUR.get(r.get("model", ""), 0.24)
        for r in results
    )

    return {
        "total": total,
        "passed": passed,
        "pending": pending,
        "decomposed": decomposed,
        "skipped": skipped,
        "sub_stories": sub_stories,
        "completion_pct": completion_pct,
        "total_attempts": len(results),
        "elapsed": elapsed_str,
        "iterations": iters,
        "est_cost": est_cost,
    }


def compute_velocity(results: list[dict]) -> list[dict]:
    if not results:
        return []
    by_iter = defaultdict(list)
    for r in results:
        by_iter[r.get("spiral_iter", 0)].append(r)

    velocity = []
    for it in sorted(by_iter):
        rows = by_iter[it]
        kept = sum(1 for r in rows if r.get("status") == "keep")
        total_dur = sum(r.get("duration_sec", 0) for r in rows)
        dur_hours = total_dur / 3600 if total_dur > 0 else 0.001
        velocity.append({
            "iter": it,
            "kept": kept,
            "total": len(rows),
            "duration_hours": dur_hours,
            "velocity": kept / dur_hours if dur_hours > 0 else 0,
        })
    return velocity


def compute_status_breakdown(prd: dict, results: list[dict]) -> dict:
    stories = prd.get("userStories", [])
    story_status = {
        "passed": sum(1 for s in stories if s.get("passes")),
        "pending": sum(1 for s in stories if not s.get("passes") and not s.get("_decomposed") and not s.get("_skipped")),
        "decomposed": sum(1 for s in stories if s.get("_decomposed")),
        "skipped": sum(1 for s in stories if s.get("_skipped")),
    }
    attempt_status: defaultdict[str, int] = defaultdict(int)
    for r in results:
        attempt_status[r.get("status", "unknown")] += 1
    return {"stories": story_status, "attempts": dict(attempt_status)}


def compute_model_performance(results: list[dict]) -> list[dict]:
    if not results:
        return []
    by_model = defaultdict(list)
    for r in results:
        by_model[r.get("model", "unknown")].append(r)

    perf = []
    for model, rows in sorted(by_model.items()):
        kept = sum(1 for r in rows if r.get("status") == "keep")
        durations = [r.get("duration_sec", 0) for r in rows if r.get("duration_sec")]
        avg_dur = sum(durations) / len(durations) if durations else 0
        med_dur = median(durations) if durations else 0
        perf.append({
            "model": model,
            "total": len(rows),
            "kept": kept,
            "success_rate": (kept / len(rows) * 100) if rows else 0,
            "avg_duration": avg_dur,
            "median_duration": med_dur,
        })
    perf.sort(key=lambda x: x["success_rate"], reverse=True)
    return perf


def compute_retry_analysis(results: list[dict]) -> list[dict]:
    if not results:
        return []
    by_attempt = defaultdict(list)
    for r in results:
        by_attempt[r.get("retry_num", 0)].append(r)

    analysis = []
    for attempt in sorted(by_attempt):
        rows = by_attempt[attempt]
        kept = sum(1 for r in rows if r.get("status") == "keep")
        analysis.append({
            "attempt": attempt + 1,  # 1-based display
            "total": len(rows),
            "kept": kept,
            "success_rate": (kept / len(rows) * 100) if rows else 0,
        })
    return analysis


def compute_bottlenecks(results: list[dict], retries: dict, prd: dict) -> dict:
    # Most retried stories
    story_titles = {s["id"]: s.get("title", "") for s in prd.get("userStories", [])}
    top_retried = sorted(retries.items(), key=lambda x: x[1], reverse=True)[:5]
    most_retried = [
        {"story_id": sid, "title": story_titles.get(sid, ""), "retries": count}
        for sid, count in top_retried if count > 0
    ]

    # Longest duration (kept stories)
    kept = [r for r in results if r.get("status") == "keep" and r.get("duration_sec")]
    kept.sort(key=lambda x: x.get("duration_sec", 0), reverse=True)
    longest = [
        {
            "story_id": r.get("story_id", ""),
            "title": r.get("story_title", ""),
            "duration_sec": r.get("duration_sec", 0),
            "duration_min": round(r.get("duration_sec", 0) / 60, 1),
        }
        for r in kept[:5]
    ]

    return {"most_retried": most_retried, "longest_duration": longest}


def compute_failure_reasons(prd: dict) -> list[dict]:
    """Return list of stories that have a _failureReason set."""
    stories = prd.get("userStories", [])
    return [
        {
            "story_id": s["id"],
            "title": s.get("title", ""),
            "reason": s["_failureReason"],
        }
        for s in stories
        if s.get("_failureReason")
    ]


def compute_iteration_velocity(results: list[dict]) -> dict:
    """Return {iter: count} dict — stories with status=='keep' per spiral_iter."""
    by_iter: dict[int, int] = {}
    for r in results:
        it = r.get("spiral_iter", 0)
        if not isinstance(it, int):
            try:
                it = int(it)
            except (ValueError, TypeError):
                it = 0
        if r.get("status") == "keep":
            by_iter[it] = by_iter.get(it, 0) + 1
    return by_iter


def compute_epics(prd: dict) -> list[dict]:
    """Compute per-epic stats: name, total stories, % complete."""
    stories = prd.get("userStories", [])
    epics_meta = prd.get("epics", []) if isinstance(prd.get("epics"), list) else []
    epic_title_map = {e["id"]: e.get("title", e["id"]) for e in epics_meta if isinstance(e, dict) and "id" in e}

    groups: dict[str, list[dict]] = {}
    for s in stories:
        eid = s.get("epicId", "")
        if not eid:
            eid = "__ungrouped__"
        groups.setdefault(eid, []).append(s)

    result = []
    for eid in sorted(k for k in groups if k != "__ungrouped__"):
        g = groups[eid]
        passed = sum(1 for s in g if s.get("passes"))
        total = len(g)
        result.append({
            "id": eid,
            "title": epic_title_map.get(eid, eid),
            "total": total,
            "passed": passed,
            "pct": (passed / total * 100) if total > 0 else 0,
        })
    if "__ungrouped__" in groups:
        g = groups["__ungrouped__"]
        passed = sum(1 for s in g if s.get("passes"))
        total = len(g)
        result.append({
            "id": "__ungrouped__",
            "title": "Ungrouped",
            "total": total,
            "passed": passed,
            "pct": (passed / total * 100) if total > 0 else 0,
        })
    return result


def detect_orphaned_worktrees(workers_dir: str = ".spiral-workers") -> list[dict]:
    """Detect orphaned git worktrees by cross-referencing PID files with live processes.

    Scans ``.spiral-workers/worker-N/worker.pid`` files.  For each, checks if the
    PID is alive via ``os.kill(pid, 0)``.  ``ProcessLookupError`` means the process
    is dead; ``PermissionError`` means it is alive but not owned by us.

    Returns list of dicts: {worker_dir, path, pid, suggested_cmd}.
    """
    orphans = []
    if not os.path.isdir(workers_dir):
        return orphans

    for entry in sorted(os.listdir(workers_dir)):
        worker_path = os.path.join(workers_dir, entry)
        if not os.path.isdir(worker_path):
            continue
        pid_file = os.path.join(worker_path, "worker.pid")
        if not os.path.isfile(pid_file):
            continue

        try:
            with open(pid_file, encoding="utf-8") as f:
                pid = int(f.read().strip())
        except (ValueError, OSError):
            continue

        is_dead = False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            is_dead = True
        except PermissionError:
            # Process exists but is not owned by us — treat as alive.
            is_dead = False
        except OSError:
            # Catch-all (e.g. ESRCH on Windows via errno).
            is_dead = True

        if is_dead:
            abs_path = os.path.abspath(worker_path)
            orphans.append({
                "worker_dir": entry,
                "path": abs_path,
                "pid": pid,
                "suggested_cmd": f"git worktree remove {abs_path}",
            })

    return orphans


def compute_decomposition(prd: dict) -> dict:
    stories = prd.get("userStories", [])
    parents = [s for s in stories if s.get("_decomposed")]
    children = [s for s in stories if s.get("_decomposedFrom")]
    children_passed = sum(1 for c in children if c.get("passes"))

    details = []
    for p in parents:
        child_ids = p.get("_decomposedInto", [])
        child_objs = [s for s in stories if s["id"] in child_ids]
        details.append({
            "parent_id": p["id"],
            "parent_title": p.get("title", ""),
            "children": [{"id": c["id"], "title": c.get("title", ""), "passes": c.get("passes", False)} for c in child_objs],
        })

    return {
        "total_decomposed": len(parents),
        "children_passed": children_passed,
        "children_total": len(children),
        "effectiveness_pct": (children_passed / len(children) * 100) if children else 0,
        "details": details,
    }


def compute_stale_stories(prd: dict, stale_days: int | None = None) -> dict[str, int]:
    """Return a mapping of story_id → age_in_days for stale pending stories.

    A story is stale when it is pending (not passed/decomposed/skipped) and its
    ``last_attempted`` timestamp is older than *stale_days* days (default: the
    ``SPIRAL_STALE_DAYS`` env var, or 7 if unset).
    """
    from datetime import timedelta, timezone
    if stale_days is None:
        try:
            stale_days = int(os.environ.get("SPIRAL_STALE_DAYS", "7"))
        except (ValueError, TypeError):
            stale_days = 7

    now = datetime.now(timezone.utc)
    threshold_delta = timedelta(days=stale_days)
    stale: dict[str, int] = {}
    for story in prd.get("userStories", []):
        if story.get("passes") or story.get("_decomposed") or story.get("_skipped"):
            continue
        ts_raw = story.get("last_attempted", "")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            age = now - ts
            if age > threshold_delta:
                stale[story["id"]] = age.days
        except (ValueError, TypeError):
            pass
    return stale


def compute_token_forecast(results: list[dict], daily_limit: int | None = None) -> dict | None:
    """Compute API token burn rate and forecast exhaustion time.

    Uses a rolling 1-hour window of rows that have ``input_tokens``/``output_tokens``
    data.  Returns ``None`` (widget hidden) when fewer than 3 such rows are found
    in the window.

    Returned dict keys:
        burn_rate_per_hour  – tokens consumed in the last 3600 s (≈ tokens/hr)
        hours_to_exhaustion – float hours until daily limit reached
        time_str            – human-readable duration string  (e.g. "~2h 15m")
        exhaustion_clock    – wall-clock time of exhaustion    (e.g. "14:32")
        daily_limit         – integer budget ceiling used
        amber_alert         – bool, True when exhaustion < 2 hours away
    """
    from datetime import timedelta, timezone

    if daily_limit is None:
        try:
            daily_limit = int(os.environ.get("SPIRAL_DAILY_TOKEN_LIMIT", "1000000"))
        except (ValueError, TypeError):
            daily_limit = 1_000_000

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=3600)

    recent_rows = []
    for r in results:
        ts_raw = r.get("timestamp", "")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        input_tok = r.get("input_tokens", 0) or 0
        output_tok = r.get("output_tokens", 0) or 0
        try:
            input_tok = int(input_tok)
            output_tok = int(output_tok)
        except (ValueError, TypeError):
            input_tok = output_tok = 0
        if input_tok > 0 or output_tok > 0:
            recent_rows.append({"timestamp": ts, "tokens": input_tok + output_tok})

    if len(recent_rows) < 3:
        return None

    # Tokens burned in the 1-hour window ≈ burn rate per hour
    burn_rate_per_hour = sum(r["tokens"] for r in recent_rows)
    if burn_rate_per_hour <= 0:
        return None

    hours_to_exhaustion = daily_limit / burn_rate_per_hour
    exhaustion_time = now + timedelta(hours=hours_to_exhaustion)
    exhaustion_clock = exhaustion_time.strftime("%H:%M")

    if hours_to_exhaustion < 1:
        mins = int(hours_to_exhaustion * 60)
        time_str = f"~{mins}m"
    else:
        h = int(hours_to_exhaustion)
        m = int((hours_to_exhaustion - h) * 60)
        time_str = f"~{h}h {m}m"

    return {
        "burn_rate_per_hour": burn_rate_per_hour,
        "hours_to_exhaustion": hours_to_exhaustion,
        "time_str": time_str,
        "exhaustion_clock": exhaustion_clock,
        "daily_limit": daily_limit,
        "amber_alert": hours_to_exhaustion < 2,
    }


def compute_story_attempts(prd: dict, results: list[dict]) -> dict:
    """Group results by story_id and build per-story attempt history.

    Returns {story_id: [attempt_rows...]} dict, one entry per story in prd.
    Also includes a ``stale_days`` key (int) when the story is stale.
    """
    stories = prd.get("userStories", [])

    stale_map = compute_stale_stories(prd)

    # Group results by story_id
    by_story: defaultdict[str, list[dict]] = defaultdict(list)
    for r in results:
        sid = r.get("story_id", "")
        if sid:
            by_story[sid].append(r)

    # Build result: one entry per story in prd
    result = {}
    for story in stories:
        sid = story["id"]
        attempts = by_story.get(sid, [])
        # Sort by timestamp descending (most recent first)
        attempts.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        manual_skip_ids = _get_manual_skip_ids()
        if story.get("passes"):
            status = "pass"
        elif story.get("_decomposed"):
            status = "decomposed"
        elif story.get("_skipped"):
            status = "skipped"
        elif sid in manual_skip_ids:
            status = "manual_skip"
        else:
            status = "pending"
        entry: dict = {
            "story_id": sid,
            "title": story.get("title", ""),
            "status": status,
            "attempts": attempts,
            "scope_creep": bool(story.get("_scopeCreep")),
        }
        if sid in stale_map:
            entry["stale_days"] = stale_map[sid]
        result[sid] = entry

    return result


# ── SVG Velocity Chart ───────────────────────────────────────────────────────

def _render_velocity_svg(iteration_velocity: dict) -> str:
    """Render an inline SVG bar chart of stories completed per SPIRAL iteration."""
    if not iteration_velocity:
        return '<div class="no-data">No iteration data yet</div>'

    iters = sorted(iteration_velocity.keys())
    counts = [iteration_velocity[it] for it in iters]
    max_count = max(counts) if counts else 1
    if max_count == 0:
        max_count = 1

    svg_w, svg_h = 500, 180
    margin_left, margin_right = 40, 10
    margin_top, margin_bottom = 10, 30
    chart_w = svg_w - margin_left - margin_right
    chart_h = svg_h - margin_top - margin_bottom

    n = len(iters)
    slot_w = chart_w // n if n > 0 else chart_w
    bar_w = max(4, slot_w - 6)

    elements = []
    # Axes
    elements.append(
        f'<line x1="{margin_left}" y1="{margin_top}" '
        f'x2="{margin_left}" y2="{margin_top + chart_h}" stroke="#444" stroke-width="1"/>'
    )
    elements.append(
        f'<line x1="{margin_left}" y1="{margin_top + chart_h}" '
        f'x2="{margin_left + chart_w}" y2="{margin_top + chart_h}" stroke="#444" stroke-width="1"/>'
    )
    elements.append(
        f'<text x="{margin_left - 4}" y="{margin_top + 10}" '
        f'text-anchor="end" fill="#888" font-size="9">{max_count}</text>'
    )

    for i, (it, count) in enumerate(zip(iters, counts)):
        slot_x = margin_left + i * slot_w
        x = slot_x + (slot_w - bar_w) // 2
        bar_h = int(count / max_count * chart_h)
        y = margin_top + chart_h - bar_h
        elements.append(
            f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" '
            f'fill="#6c63ff" rx="3"/>'
        )
        if count > 0:
            elements.append(
                f'<text x="{x + bar_w // 2}" y="{y - 3}" '
                f'text-anchor="middle" fill="#aaa" font-size="10">{count}</text>'
            )
        lx = x + bar_w // 2
        elements.append(
            f'<text x="{lx}" y="{svg_h - 6}" '
            f'text-anchor="middle" fill="#888" font-size="9">i{it}</text>'
        )

    inner = "\n".join(elements)
    return (
        f'<svg viewBox="0 0 {svg_w} {svg_h}" width="100%" height="{svg_h}" '
        f'xmlns="http://www.w3.org/2000/svg">\n{inner}\n</svg>'
    )


# ── Screenshot Discovery ─────────────────────────────────────────────────────

def find_latest_screenshot(scratch_dir: str) -> str | None:
    """Return the path to the latest screenshot in scratch_dir/screenshots/, or None."""
    screenshots_dir = os.path.join(scratch_dir, "screenshots")
    if not os.path.isdir(screenshots_dir):
        return None
    pngs = sorted(
        (f for f in os.listdir(screenshots_dir) if f.endswith(".png")),
        reverse=True,
    )
    return os.path.join(screenshots_dir, pngs[0]) if pngs else None


# ── Insight Generation ───────────────────────────────────────────────────────

def generate_insights(overview: dict, model_perf: list[dict], retry_analysis: list[dict], bottlenecks: dict) -> list[str]:
    insights = []

    # Model disparity
    if len(model_perf) >= 2:
        best = model_perf[0]
        worst = model_perf[-1]
        gap = best["success_rate"] - worst["success_rate"]
        if gap > 20 and worst["total"] >= 3:
            insights.append(
                f'{best["model"]} has {gap:.0f}% higher success rate than {worst["model"]} '
                f'({best["success_rate"]:.0f}% vs {worst["success_rate"]:.0f}%) — '
                f'consider routing more stories to {best["model"]}'
            )

    # Low first-attempt rate
    if retry_analysis:
        first = retry_analysis[0]
        if first["success_rate"] < 50 and first["total"] >= 5:
            insights.append(
                f'First-attempt success rate is only {first["success_rate"]:.0f}% — '
                f'consider improving story clarity or prompt quality'
            )

    # Heavy retrier
    for b in bottlenecks.get("most_retried", []):
        if b["retries"] >= 3:
            insights.append(
                f'Story {b["story_id"]} consumed {b["retries"]} retries — '
                f'consider manual decomposition or intervention'
            )
            break

    return insights


# ── HTML Renderer ────────────────────────────────────────────────────────────

def _render_screenshot_section(screenshot_path: str | None) -> str:
    """Return an HTML section with the latest screenshot, or empty string."""
    if not screenshot_path or not os.path.isfile(screenshot_path):
        return ""
    fname = os.path.basename(screenshot_path)
    # Use relative path from the dashboard output directory
    return (
        '<section>\n'
        '<h2>Latest Screenshot</h2>\n'
        f'<div style="text-align:center">'
        f'<img src="screenshots/{escape(fname)}" alt="App screenshot" '
        f'style="max-width:100%;border-radius:6px;border:1px solid #333">'
        f'<div class="metric-label" style="margin-top:6px">{escape(fname)}</div>'
        f'</div>\n'
        '</section>\n'
    )


def _render_activity_feed(sections: list[str]) -> str:
    """Return a collapsible Recent Activity section, or '' if no sections."""
    if not sections:
        return ""
    n = len(sections)
    entries = ""
    for sec in sections:
        lines = sec.split("\n", 1)
        title = lines[0].lstrip("# ").strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        entries += (
            f'<div style="margin-bottom:12px">'
            f'<b>{escape(title)}</b>'
            f'<pre style="white-space:pre-wrap;font-size:11px;margin-top:4px;color:#aaa">{escape(body)}</pre>'
            f'</div>\n'
        )
    return (
        '<section>\n'
        f'<details><summary style="cursor:pointer;color:#6c63ff;font-size:14px;text-transform:uppercase;letter-spacing:1px">'
        f'Recent Activity (last {n} entries)</summary>\n'
        f'<div style="margin-top:12px">{entries}</div>\n'
        '</details>\n'
        '</section>\n'
    )


def render_html(overview: dict, velocity: list[dict], status: dict,
                model_perf: list[dict], retry_analysis: list[dict],
                bottlenecks: dict, decomposition: dict, insights: list[str],
                screenshot_path: str | None = None,
                iteration_velocity: dict | None = None,
                epics: list[dict] | None = None,
                activity_sections: list[str] | None = None,
                failure_reasons: list[dict] | None = None,
                story_attempts: dict | None = None,
                refresh_secs: int = 0,
                orphaned_worktrees: list[dict] | None = None,
                token_forecast: dict | None = None) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    max_vel = max((v["kept"] for v in velocity), default=1) or 1

    # Velocity bars
    vel_rows = ""
    for v in velocity:
        pct = v["kept"] / max_vel * 100
        vel_rows += (
            f'<div class="bar-row">'
            f'<span class="bar-label">iter {v["iter"]}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.0f}%"></div></div>'
            f'<span class="bar-value">{v["kept"]} kept ({v["velocity"]:.1f}/hr)</span>'
            f'</div>\n'
        )

    # Status stacked bar
    ss = status["stories"]
    total_s = ss["passed"] + ss["pending"] + ss["decomposed"] + ss["skipped"]
    if total_s > 0:
        pct_passed = ss["passed"] / total_s * 100
        pct_pending = ss["pending"] / total_s * 100
        pct_decomp = ss["decomposed"] / total_s * 100
        pct_skipped = ss["skipped"] / total_s * 100
    else:
        pct_passed = pct_pending = pct_decomp = pct_skipped = 0

    # Attempt status
    att = status["attempts"]
    att_html = " &middot; ".join(f'{k}: <b>{v}</b>' for k, v in sorted(att.items()))

    # Model table
    model_rows = ""
    for m in model_perf:
        rate_class = "good" if m["success_rate"] >= 70 else "warn" if m["success_rate"] >= 40 else "bad"
        model_rows += (
            f'<tr>'
            f'<td>{escape(m["model"])}</td>'
            f'<td>{m["total"]}</td>'
            f'<td>{m["kept"]}</td>'
            f'<td class="{rate_class}">{m["success_rate"]:.0f}%</td>'
            f'<td>{m["avg_duration"]:.0f}s</td>'
            f'</tr>\n'
        )

    # Retry bars
    retry_rows = ""
    for r in retry_analysis:
        retry_rows += (
            f'<div class="bar-row">'
            f'<span class="bar-label">attempt {r["attempt"]}</span>'
            f'<div class="bar-track"><div class="bar-fill retry" style="width:{r["success_rate"]:.0f}%"></div></div>'
            f'<span class="bar-value">{r["success_rate"]:.0f}% ({r["kept"]}/{r["total"]})</span>'
            f'</div>\n'
        )

    # Decomposition
    decomp_html = ""
    if decomposition["total_decomposed"] > 0:
        decomp_html = (
            f'<div class="metric-big">{decomposition["effectiveness_pct"]:.0f}%</div>'
            f'<div class="metric-label">{decomposition["children_passed"]}/{decomposition["children_total"]} sub-stories passed</div>'
        )
        for d in decomposition["details"]:
            children_status = " ".join(
                f'<span class="chip {"pass" if c["passes"] else "fail"}">{escape(c["id"])}</span>'
                for c in d["children"]
            )
            decomp_html += f'<div class="decomp-row"><b>{escape(d["parent_id"])}</b> &rarr; {children_status}</div>'
    else:
        decomp_html = '<div class="no-data">No stories decomposed yet</div>'

    # Bottleneck tables
    retry_table = ""
    for b in bottlenecks["most_retried"]:
        retry_table += f'<tr><td>{escape(b["story_id"])}</td><td class="trunc">{escape(b["title"][:50])}</td><td>{b["retries"]}</td></tr>\n'
    if not retry_table:
        retry_table = '<tr><td colspan="3" class="no-data">None</td></tr>'

    dur_table = ""
    for b in bottlenecks["longest_duration"]:
        dur_table += f'<tr><td>{escape(b["story_id"])}</td><td class="trunc">{escape(b["title"][:50])}</td><td>{b["duration_min"]}m</td></tr>\n'
    if not dur_table:
        dur_table = '<tr><td colspan="3" class="no-data">None</td></tr>'

    # Insights
    insights_html = ""
    if insights:
        for i in insights:
            insights_html += f'<div class="insight">{escape(i)}</div>\n'

    # Failure reasons table
    failure_reasons_html = ""
    fr_list = failure_reasons or []
    if fr_list:
        fr_rows = ""
        for fr in fr_list:
            fr_rows += (
                f'<tr><td>{escape(fr["story_id"])}</td>'
                f'<td class="trunc">{escape(fr["title"][:50])}</td>'
                f'<td title="{escape(fr["reason"])}">{escape(fr["reason"][:80])}</td></tr>\n'
            )
        failure_reasons_html = (
            f'<section>\n<h2>Failure Reasons</h2>\n'
            f'<table>\n<tr><th>ID</th><th>Title</th><th>Reason</th></tr>\n'
            f'{fr_rows}</table>\n</section>\n'
        )

    # Velocity by iteration SVG chart
    iter_vel_svg = _render_velocity_svg(iteration_velocity or {})

    # Epics section
    epics_html = ""
    if epics and any(e["id"] != "__ungrouped__" for e in epics):
        epic_rows = ""
        for e in epics:
            pct_class = "good" if e["pct"] >= 70 else "warn" if e["pct"] >= 40 else "bad"
            epic_rows += (
                f'<tr>'
                f'<td>{escape(e["title"])}</td>'
                f'<td>{e["total"]}</td>'
                f'<td>{e["passed"]}</td>'
                f'<td class="{pct_class}">{e["pct"]:.0f}%</td>'
                f'<td><div class="bar-track" style="height:12px"><div class="bar-fill" style="width:{e["pct"]:.0f}%"></div></div></td>'
                f'</tr>\n'
            )
        epics_html = (
            f'<section>\n<h2>Epics</h2>\n'
            f'<table>\n<tr><th>Epic</th><th>Total</th><th>Done</th><th>%</th><th>Progress</th></tr>\n'
            f'{epic_rows}</table>\n</section>\n'
        )

    # Completion ring SVG
    ring_pct = overview["completion_pct"]
    circumference = 2 * 3.14159 * 36
    offset = circumference * (1 - ring_pct / 100)
    ring_color = "#00d4aa" if ring_pct >= 70 else "#ffd93d" if ring_pct >= 40 else "#ff6b6b"

    # Stories section with per-story attempt drilldown
    stories_html = ""
    if story_attempts:
        stories_rows = ""
        for story_id in sorted(story_attempts.keys()):
            story = story_attempts[story_id]
            status_color = "good" if story["status"] == "pass" else "bad" if story["status"] == "pending" else "warn"
            display_status = "Skipped by user" if story["status"] == "manual_skip" else story["status"]
            attempts = story["attempts"]
            stale_days_val = story.get("stale_days")
            stale_badge = (
                f'<span class="stale-badge">&#9200; stale {stale_days_val}d</span>'
                if stale_days_val is not None else ""
            )
            scope_creep_flag = story.get("scope_creep", False)
            scope_creep_badge = (
                '<span class="scope-creep-badge">&#9888; scope-creep</span>'
                if scope_creep_flag else ""
            )

            # Build attempt table HTML
            attempt_rows = ""
            if attempts:
                for att in attempts:
                    timestamp = att.get("timestamp", "")[:19]  # ISO format, trim to YYYY-MM-DD HH:MM:SS
                    model = escape(att.get("model", ""))
                    tool = escape(att.get("tool", ""))
                    att_status = escape(att.get("status", ""))
                    duration = att.get("duration_sec", 0)
                    retry_num = att.get("retry_num", 0)
                    commit = att.get("commit_sha", "")[:8]
                    attempt_rows += (
                        f'<tr style="font-size:11px">'
                        f'<td style="font-family:monospace;font-size:10px">{timestamp}</td>'
                        f'<td>{model}</td>'
                        f'<td>{tool}</td>'
                        f'<td class="{att_status}">{att_status}</td>'
                        f'<td style="text-align:right">{duration}s</td>'
                        f'<td style="text-align:center">{retry_num}</td>'
                        f'<td style="font-family:monospace;font-size:10px">{commit}</td>'
                        f'</tr>\n'
                    )
            else:
                attempt_rows = '<tr style="font-size:11px"><td colspan="7" class="no-data">No attempts recorded</td></tr>'

            _border_color = "#ffa040" if stale_days_val is not None else ("#ff9900" if scope_creep_flag else "#333")
            _detail_class = "stale-story" if stale_days_val is not None else ("scope-creep-story" if scope_creep_flag else "")
            stories_rows += (
                f'<details class="{_detail_class}" style="margin-bottom:8px;border:1px solid {_border_color};border-radius:4px">'
                f'<summary style="cursor:pointer;padding:8px;background:#0f3460;color:#fff;font-weight:bold;display:flex;justify-content:space-between;align-items:center">'
                f'<span>{escape(story_id)}: {escape(story["title"][:50])}{stale_badge}{scope_creep_badge}</span>'
                f'<span class="{status_color}" style="font-size:11px;padding:2px 6px;border-radius:3px">{display_status}</span>'
                f'</summary>'
                f'<div style="padding:8px;overflow-x:auto">'
                f'<table style="font-size:11px;width:100%">'
                f'<tr><th style="font-size:9px">Timestamp</th><th>Model</th><th>Tool</th><th>Status</th><th style="text-align:right">Secs</th><th style="text-align:center">Retry</th><th>Commit</th></tr>'
                f'{attempt_rows}'
                f'</table>'
                f'</div>'
                f'</details>\n'
            )

        stories_html = (
            f'<section>\n<h2>Stories</h2>\n'
            f'<div style="max-height:600px;overflow-y:auto">{stories_rows}</div>\n'
            f'</section>\n'
        )

    # Orphaned worktrees section
    orphaned_html = ""
    ow_list = orphaned_worktrees or []
    if ow_list:
        ow_rows = ""
        for ow in ow_list:
            ow_rows += (
                f'<tr>'
                f'<td><span class="bad">ORPHANED</span></td>'
                f'<td>{escape(ow["worker_dir"])}</td>'
                f'<td class="trunc" title="{escape(ow["path"])}">{escape(ow["path"])}</td>'
                f'<td>{ow["pid"]}</td>'
                f'<td><code style="font-size:11px;color:#ffd93d">{escape(ow["suggested_cmd"])}</code></td>'
                f'</tr>\n'
            )
        orphaned_html = (
            f'<section style="border-color:#ff6b6b">\n'
            f'<h2 style="color:#ff6b6b">&#9888; Orphaned Worktrees ({len(ow_list)})</h2>\n'
            f'<p style="font-size:12px;color:#aaa;margin-bottom:10px">'
            f'These worktrees have dead worker PIDs. Run the suggested command to clean up.</p>\n'
            f'<table>\n<tr><th>Status</th><th>Worker</th><th>Path</th><th>Dead PID</th><th>Cleanup Command</th></tr>\n'
            f'{ow_rows}</table>\n</section>\n'
        )

    # Token forecast widget
    token_forecast_html = ""
    if token_forecast is not None:
        tf = token_forecast
        amber = tf.get("amber_alert", False)
        border_col = "#ffd93d" if amber else "#0f3460"
        title_col = "#ffd93d" if amber else "#6c63ff"
        alert_badge = ' <span style="font-size:10px;background:#ffd93d;color:#333;padding:1px 6px;border-radius:8px;vertical-align:middle">&#9888; LOW BUDGET</span>' if amber else ""
        burn_rate_fmt = f"{tf['burn_rate_per_hour']:,}"
        limit_fmt = f"{tf['daily_limit']:,}"
        token_forecast_html = (
            f'<section style="border-color:{border_col}">\n'
            f'<h2 style="color:{title_col}">API Rate-Limit Forecast{alert_badge}</h2>\n'
            f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">\n'
            f'<div style="text-align:center"><div style="font-size:22px;font-weight:bold;color:#fff">{burn_rate_fmt}</div>'
            f'<div style="font-size:11px;color:#888;margin-top:4px;text-transform:uppercase">Tokens / Hour</div></div>\n'
            f'<div style="text-align:center"><div style="font-size:22px;font-weight:bold;color:{"#ffd93d" if amber else "#fff"}">'
            f'{tf["time_str"]} <span style="font-size:13px;color:#888">(at {tf["exhaustion_clock"]})</span></div>'
            f'<div style="font-size:11px;color:#888;margin-top:4px;text-transform:uppercase">Daily Limit In</div></div>\n'
            f'<div style="text-align:center"><div style="font-size:22px;font-weight:bold;color:#fff">{limit_fmt}</div>'
            f'<div style="font-size:11px;color:#888;margin-top:4px;text-transform:uppercase">Daily Budget (SPIRAL_DAILY_TOKEN_LIMIT)</div></div>\n'
            f'</div>\n'
            f'<div style="font-size:11px;color:#555;margin-top:8px">'
            f'At current pace, daily limit reached in {tf["time_str"]} (at {tf["exhaustion_clock"]}). '
            f'Based on rolling 1-hour token window.</div>\n'
            f'</section>\n'
        )

    refresh_meta = f'<meta http-equiv="refresh" content="{refresh_secs}">\n' if refresh_secs > 0 else ""
    refresh_footer = f" &middot; Auto-refreshing every {refresh_secs}s" if refresh_secs > 0 else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{refresh_meta}<title>SPIRAL Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#1a1a2e;color:#e0e0e0;font-family:'Cascadia Code','Fira Code',Consolas,monospace;font-size:13px;padding:20px;max-width:1100px;margin:0 auto}}
header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:12px;border-bottom:1px solid #333}}
header h1{{font-size:20px;color:#fff;letter-spacing:1px}}
header .ts{{color:#888;font-size:11px}}
.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}}
.card{{background:#16213e;border:1px solid #0f3460;border-radius:8px;padding:16px;text-align:center}}
.card .val{{font-size:24px;font-weight:bold;color:#fff}}
.card .lbl{{font-size:11px;color:#888;margin-top:4px;text-transform:uppercase}}
.card .ring-wrap{{display:flex;justify-content:center;margin-bottom:4px}}
section{{background:#16213e;border:1px solid #0f3460;border-radius:8px;padding:16px;margin-bottom:14px}}
section h2{{font-size:14px;color:#6c63ff;margin-bottom:12px;text-transform:uppercase;letter-spacing:1px}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}}
.bar-row{{display:flex;align-items:center;gap:8px;margin-bottom:6px}}
.bar-label{{width:70px;text-align:right;color:#888;font-size:11px;flex-shrink:0}}
.bar-track{{flex:1;height:18px;background:#0a0a1a;border-radius:4px;overflow:hidden}}
.bar-fill{{height:100%;background:linear-gradient(90deg,#6c63ff,#00d4aa);border-radius:4px;transition:width .3s}}
.bar-fill.retry{{background:linear-gradient(90deg,#ffd93d,#00d4aa)}}
.bar-value{{width:140px;font-size:11px;color:#aaa;flex-shrink:0}}
.stacked-bar{{display:flex;height:24px;border-radius:4px;overflow:hidden;margin-bottom:8px}}
.stacked-bar .seg{{height:100%;display:flex;align-items:center;justify-content:center;font-size:10px;color:#fff;font-weight:bold}}
.stacked-bar .seg.pass{{background:#00d4aa}}
.stacked-bar .seg.pend{{background:#6c63ff}}
.stacked-bar .seg.dec{{background:#ffd93d;color:#333}}
.stacked-bar .seg.skip{{background:#888;color:#fff}}
.att-line{{color:#888;font-size:11px;margin-top:6px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{text-align:left;color:#888;font-size:10px;text-transform:uppercase;padding:6px 8px;border-bottom:1px solid #333}}
td{{padding:6px 8px;border-bottom:1px solid #222}}
td.trunc{{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.good{{color:#00d4aa;font-weight:bold}}
.warn{{color:#ffd93d;font-weight:bold}}
.bad{{color:#ff6b6b;font-weight:bold}}
.insight{{background:#2a2000;border:1px solid #ffd93d;border-radius:6px;padding:10px 14px;margin-bottom:8px;font-size:12px;color:#ffd93d}}
.no-data{{color:#555;font-style:italic;padding:8px}}
.metric-big{{font-size:32px;font-weight:bold;color:#00d4aa;text-align:center}}
.metric-label{{text-align:center;color:#888;font-size:11px;margin-bottom:8px}}
.decomp-row{{margin:6px 0;font-size:12px}}
.chip{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;margin:2px}}
.chip.pass{{background:#0a3a2a;color:#00d4aa;border:1px solid #00d4aa}}
.chip.fail{{background:#3a0a0a;color:#ff6b6b;border:1px solid #ff6b6b}}
.stale-badge{{display:inline-block;padding:1px 6px;border-radius:8px;font-size:10px;background:#3a2000;color:#ffa040;border:1px solid #ffa040;margin-left:6px}}
.scope-creep-badge{{display:inline-block;padding:1px 6px;border-radius:8px;font-size:10px;background:#3a2200;color:#ff9900;border:1px solid #ff9900;margin-left:6px}}
footer{{text-align:center;color:#444;font-size:10px;margin-top:16px;padding-top:10px;border-top:1px solid #222}}
</style>
</head>
<body>
<header>
<h1>SPIRAL Dashboard</h1>
<span class="ts">Generated: {now}</span>
</header>

<div class="cards">
<div class="card">
<div class="ring-wrap">
<svg width="80" height="80" viewBox="0 0 80 80">
<circle cx="40" cy="40" r="36" fill="none" stroke="#222" stroke-width="6"/>
<circle cx="40" cy="40" r="36" fill="none" stroke="{ring_color}" stroke-width="6"
  stroke-dasharray="{circumference:.1f}" stroke-dashoffset="{offset:.1f}"
  stroke-linecap="round" transform="rotate(-90 40 40)"/>
<text x="40" y="44" text-anchor="middle" fill="#fff" font-size="16" font-family="inherit">{ring_pct:.0f}%</text>
</svg>
</div>
<div class="lbl">Completion ({overview["passed"]}/{overview["total"] - overview["decomposed"]})</div>
</div>
<div class="card">
<div class="val">{velocity[-1]["velocity"]:.1f}/hr</div>
<div class="lbl">Latest Velocity</div>
</div>
<div class="card">
<div class="val">{overview["total_attempts"]}</div>
<div class="lbl">Total Attempts</div>
</div>
<div class="card">
<div class="val">{overview["elapsed"]}</div>
<div class="lbl">Elapsed &middot; {overview["iterations"]} iters</div>
</div>
<div class="card">
<div class="val">${overview["est_cost"]:.2f}</div>
<div class="lbl">Est. Cost &middot; estimate</div>
</div>
</div>

{orphaned_html}
{token_forecast_html}{f'<div>{insights_html}</div>' if insights_html else ''}

{stories_html}

<section>
<h2>Velocity Trend</h2>
{vel_rows if vel_rows else '<div class="no-data">No results data yet</div>'}
</section>

{epics_html}

<div class="two-col">
<section>
<h2>Story Status</h2>
<div class="stacked-bar">
<div class="seg pass" style="width:{pct_passed:.0f}%">{ss["passed"]}</div>
<div class="seg pend" style="width:{pct_pending:.0f}%">{ss["pending"]}</div>
{f'<div class="seg dec" style="width:{pct_decomp:.0f}%">{ss["decomposed"]}</div>' if ss["decomposed"] else ''}
{f'<div class="seg skip" style="width:{pct_skipped:.0f}%">{ss["skipped"]}</div>' if ss["skipped"] else ''}
</div>
<div class="att-line">Attempts: {att_html if att_html else 'none'}</div>
</section>
<section>
<h2>Model Performance</h2>
<table>
<tr><th>Model</th><th>Tries</th><th>Kept</th><th>Rate</th><th>Avg</th></tr>
{model_rows if model_rows else '<tr><td colspan="5" class="no-data">No data</td></tr>'}
</table>
</section>
</div>

<div class="two-col">
<section>
<h2>Retry Analysis</h2>
{retry_rows if retry_rows else '<div class="no-data">No retry data</div>'}
</section>
<section>
<h2>Decomposition</h2>
{decomp_html}
</section>
</div>

<div class="two-col">
<section>
<h2>Most Retried Stories</h2>
<table>
<tr><th>ID</th><th>Title</th><th>Retries</th></tr>
{retry_table}
</table>
</section>
<section>
<h2>Longest Implementations</h2>
<table>
<tr><th>ID</th><th>Title</th><th>Duration</th></tr>
{dur_table}
</table>
</section>
</div>

{failure_reasons_html}
<section>
<h2>Velocity by Iteration</h2>
{iter_vel_svg}
</section>

{_render_activity_feed(activity_sections or [])}
{_render_screenshot_section(screenshot_path)}
<footer>SPIRAL Metrics Dashboard &middot; {now}{refresh_footer}</footer>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="SPIRAL metrics dashboard generator")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    parser.add_argument("--results", default="results.tsv", help="Path to results.tsv")
    parser.add_argument("--retries", default="retry-counts.json", help="Path to retry-counts.json")
    parser.add_argument("--progress", default="progress.txt", help="Path to progress.txt")
    parser.add_argument("--reports-dir", default="test-reports", help="Path to test-reports dir")
    parser.add_argument("--scratch-dir", default=".spiral", help="Path to .spiral scratch dir (for screenshots)")
    parser.add_argument("--output", default=".spiral/dashboard.html", help="Output HTML path")
    parser.add_argument("--open", action="store_true", help="Auto-open in browser after generating")
    parser.add_argument("--refresh-secs", type=int,
                        default=int(os.environ.get("SPIRAL_DASHBOARD_REFRESH_SECS", "30")),
                        help="Auto-refresh interval in seconds (0 to disable)")
    args = parser.parse_args()

    # Orphan check runs at startup (US-087)
    orphans = detect_orphaned_worktrees()

    # Load data
    prd = load_prd(args.prd)
    results = load_results(args.results)
    retries = load_retries(args.retries)
    activity = load_progress(args.progress)

    # Load optional iteration summary (US-039)
    iter_summary_path = os.path.join(args.scratch_dir, "_iteration_summary.json")
    iter_summary = load_iter_summary(iter_summary_path)

    # Compute metrics
    overview = compute_overview(prd, results)

    # Merge latest iteration summary into overview if present
    if iter_summary:
        overview["last_iter_summary"] = iter_summary
    velocity = compute_velocity(results)
    status = compute_status_breakdown(prd, results)
    model_perf = compute_model_performance(results)
    retry_analysis = compute_retry_analysis(results)
    bottle = compute_bottlenecks(results, retries, prd)
    decomposition = compute_decomposition(prd)
    insights = generate_insights(overview, model_perf, retry_analysis, bottle)
    iter_vel = compute_iteration_velocity(results)
    epics = compute_epics(prd)
    failure_reasons = compute_failure_reasons(prd)
    story_attempts = compute_story_attempts(prd, results)
    token_forecast = compute_token_forecast(results)

    # Find latest screenshot
    screenshot = find_latest_screenshot(args.scratch_dir)

    # Need at least one velocity entry for the template
    if not velocity:
        velocity = [{"iter": 0, "kept": 0, "total": 0, "duration_hours": 0.001, "velocity": 0}]

    # Render
    html = render_html(overview, velocity, status, model_perf, retry_analysis, bottle, decomposition, insights, screenshot, iteration_velocity=iter_vel, epics=epics, activity_sections=activity, failure_reasons=failure_reasons, story_attempts=story_attempts, refresh_secs=args.refresh_secs, orphaned_worktrees=orphans, token_forecast=token_forecast)

    # Write
    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[dashboard] Written to {output_path}")

    # Auto-open
    if args.open:
        try:
            if sys.platform == "win32":
                os.startfile(output_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", output_path])
            else:
                subprocess.Popen(["xdg-open", output_path])
            print("[dashboard] Opened in browser")
        except OSError as e:
            print(f"[dashboard] Could not auto-open: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
