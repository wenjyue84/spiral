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
            for key in ("duration_sec", "retry_num", "spiral_iter", "ralph_iter"):
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


# ── Metrics Computation ──────────────────────────────────────────────────────

def compute_overview(prd: dict, results: list[dict]) -> dict:
    stories = prd.get("userStories", [])
    total = len(stories)
    passed = sum(1 for s in stories if s.get("passes"))
    decomposed = sum(1 for s in stories if s.get("_decomposed"))
    sub_stories = sum(1 for s in stories if s.get("_decomposedFrom"))
    pending = sum(1 for s in stories if not s.get("passes") and not s.get("_decomposed"))
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

    return {
        "total": total,
        "passed": passed,
        "pending": pending,
        "decomposed": decomposed,
        "sub_stories": sub_stories,
        "completion_pct": completion_pct,
        "total_attempts": len(results),
        "elapsed": elapsed_str,
        "iterations": iters,
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
        "pending": sum(1 for s in stories if not s.get("passes") and not s.get("_decomposed")),
        "decomposed": sum(1 for s in stories if s.get("_decomposed")),
    }
    attempt_status = defaultdict(int)
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
    most_retried = sorted(retries.items(), key=lambda x: x[1], reverse=True)[:5]
    most_retried = [
        {"story_id": sid, "title": story_titles.get(sid, ""), "retries": count}
        for sid, count in most_retried if count > 0
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

def render_html(overview: dict, velocity: list[dict], status: dict,
                model_perf: list[dict], retry_analysis: list[dict],
                bottlenecks: dict, decomposition: dict, insights: list[str]) -> str:
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
    total_s = ss["passed"] + ss["pending"] + ss["decomposed"]
    if total_s > 0:
        pct_passed = ss["passed"] / total_s * 100
        pct_pending = ss["pending"] / total_s * 100
        pct_decomp = ss["decomposed"] / total_s * 100
    else:
        pct_passed = pct_pending = pct_decomp = 0

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

    # Completion ring SVG
    ring_pct = overview["completion_pct"]
    circumference = 2 * 3.14159 * 36
    offset = circumference * (1 - ring_pct / 100)
    ring_color = "#00d4aa" if ring_pct >= 70 else "#ffd93d" if ring_pct >= 40 else "#ff6b6b"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SPIRAL Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#1a1a2e;color:#e0e0e0;font-family:'Cascadia Code','Fira Code',Consolas,monospace;font-size:13px;padding:20px;max-width:1100px;margin:0 auto}}
header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:12px;border-bottom:1px solid #333}}
header h1{{font-size:20px;color:#fff;letter-spacing:1px}}
header .ts{{color:#888;font-size:11px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}}
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
</div>

{f'<div>{insights_html}</div>' if insights_html else ''}

<section>
<h2>Velocity Trend</h2>
{vel_rows if vel_rows else '<div class="no-data">No results data yet</div>'}
</section>

<div class="two-col">
<section>
<h2>Story Status</h2>
<div class="stacked-bar">
<div class="seg pass" style="width:{pct_passed:.0f}%">{ss["passed"]}</div>
<div class="seg pend" style="width:{pct_pending:.0f}%">{ss["pending"]}</div>
{f'<div class="seg dec" style="width:{pct_decomp:.0f}%">{ss["decomposed"]}</div>' if ss["decomposed"] else ''}
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

<footer>SPIRAL Metrics Dashboard &middot; {now}</footer>
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
    parser.add_argument("--output", default=".spiral/dashboard.html", help="Output HTML path")
    parser.add_argument("--open", action="store_true", help="Auto-open in browser after generating")
    args = parser.parse_args()

    # Load data
    prd = load_prd(args.prd)
    results = load_results(args.results)
    retries = load_retries(args.retries)

    # Compute metrics
    overview = compute_overview(prd, results)
    velocity = compute_velocity(results)
    status = compute_status_breakdown(prd, results)
    model_perf = compute_model_performance(results)
    retry_analysis = compute_retry_analysis(results)
    bottle = compute_bottlenecks(results, retries, prd)
    decomposition = compute_decomposition(prd)
    insights = generate_insights(overview, model_perf, retry_analysis, bottle)

    # Need at least one velocity entry for the template
    if not velocity:
        velocity = [{"iter": 0, "kept": 0, "total": 0, "duration_hours": 0.001, "velocity": 0}]

    # Render
    html = render_html(overview, velocity, status, model_perf, retry_analysis, bottle, decomposition, insights)

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
