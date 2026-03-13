#!/usr/bin/env python3
"""story_review_report.py — Generate HTML story review report for human gate.

Reads prd.json and produces a self-contained HTML report that explains each
pending user story in layman terms, helping the human decide whether to
approve, edit, or reject stories before Ralph implements them.

Historical reports are saved to .spiral/gate-reports/ with timestamps.

stdlib-only — no external dependencies.

Usage:
    python lib/story_review_report.py --prd prd.json --iter 3 --output .spiral/gate-reports/
    python lib/story_review_report.py --prd prd.json --iter 3 --output .spiral/gate-reports/ --open
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from html import escape
from pathlib import Path

# Force UTF-8 stdout on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── Data helpers ─────────────────────────────────────────────────────────────

def load_prd(path: str) -> dict:
    if not os.path.isfile(path):
        return {"userStories": []}
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def classify_complexity(story: dict) -> dict:
    """Return a human-friendly complexity label and colour."""
    c = (story.get("estimatedComplexity") or "medium").lower()
    mapping = {
        "small":  {"label": "Small — Quick change",  "color": "#22c55e", "icon": "🟢"},
        "medium": {"label": "Medium — Some work",     "color": "#f59e0b", "icon": "🟡"},
        "large":  {"label": "Large — Significant effort", "color": "#ef4444", "icon": "🔴"},
    }
    return mapping.get(c, mapping["medium"])


def classify_risk(story: dict) -> dict:
    """Estimate risk level from story properties."""
    risk_score = 0
    reasons = []
    deps = story.get("dependencies", [])
    ac = story.get("acceptanceCriteria", [])
    title = (story.get("title") or "").lower()
    desc = (story.get("description") or "").lower()
    notes = " ".join(story.get("technicalNotes", [])).lower()

    # Dependency risk
    if len(deps) > 2:
        risk_score += 2
        reasons.append(f"Depends on {len(deps)} other stories")
    elif len(deps) > 0:
        risk_score += 1
        reasons.append(f"Depends on {', '.join(deps)}")

    # Scope risk (many acceptance criteria)
    if len(ac) > 5:
        risk_score += 2
        reasons.append(f"{len(ac)} acceptance criteria — broad scope")
    elif len(ac) > 3:
        risk_score += 1

    # Keyword-based risk
    risky_words = ["database", "migration", "auth", "security", "payment", "delete", "deploy", "production"]
    found = [w for w in risky_words if w in title or w in desc or w in notes]
    if found:
        risk_score += len(found)
        reasons.append(f"Touches sensitive areas: {', '.join(found)}")

    if risk_score >= 4:
        return {"level": "High", "color": "#ef4444", "icon": "⚠️", "reasons": reasons}
    elif risk_score >= 2:
        return {"level": "Medium", "color": "#f59e0b", "icon": "⚡", "reasons": reasons}
    else:
        return {"level": "Low", "color": "#22c55e", "icon": "✅", "reasons": reasons or ["Straightforward change"]}


def explain_story(story: dict) -> str:
    """Generate a plain-English explanation of what this story does."""
    title = story.get("title", "Untitled")
    desc = story.get("description", "")
    ac = story.get("acceptanceCriteria", [])
    deps = story.get("dependencies", [])

    parts = []
    parts.append(f"This task asks the AI agent to <strong>{escape(title.lower())}</strong>.")

    if desc:
        parts.append(f"{escape(desc)}")

    if ac:
        parts.append("When finished, it should meet these requirements:")
        items = "".join(f"<li>{escape(c)}</li>" for c in ac)
        parts.append(f"<ul>{items}</ul>")

    if deps:
        dep_str = ", ".join(deps)
        parts.append(f"<em>Note: This can only be done after {escape(dep_str)} is completed first.</em>")

    return "\n".join(parts)


def explain_impact(story: dict) -> str:
    """Explain in simple terms what parts of the project this will change."""
    notes = story.get("technicalNotes", [])
    if not notes:
        return "The AI will determine which files to modify based on the requirements."
    items = "".join(f"<li>{escape(n)}</li>" for n in notes)
    return f"Technical approach:<ul>{items}</ul>"


# ── HTML generation ──────────────────────────────────────────────────────────

def _group_by_epic(stories: list[dict], epics_meta: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """Group stories by epicId. Returns list of (epic_id, epic_title, stories).

    Stories without epicId go into 'Ungrouped'. Epic titles come from the
    optional top-level epics array when available.
    """
    epic_title_map = {e["id"]: e.get("title", e["id"]) for e in epics_meta if isinstance(e, dict) and "id" in e}

    groups: dict[str, list[dict]] = {}
    for s in stories:
        eid = s.get("epicId", "")
        if not eid:
            eid = "__ungrouped__"
        groups.setdefault(eid, []).append(s)

    # Named epics first (alphabetical), then ungrouped last
    result = []
    for eid in sorted(k for k in groups if k != "__ungrouped__"):
        title = epic_title_map.get(eid, eid)
        result.append((eid, title, groups[eid]))
    if "__ungrouped__" in groups:
        result.append(("__ungrouped__", "Ungrouped", groups["__ungrouped__"]))
    return result


def _render_epic_progress_bar(stories: list[dict]) -> str:
    """Return HTML for a mini progress bar showing completed vs total within an epic."""
    total = len(stories)
    done = sum(1 for s in stories if s.get("passes"))
    pct = (done / total * 100) if total > 0 else 0
    return (
        f'<div class="epic-progress">'
        f'<div class="epic-progress-track">'
        f'<div class="epic-progress-fill" style="width:{pct:.0f}%"></div>'
        f'</div>'
        f'<span class="epic-progress-label">{done}/{total} done ({pct:.0f}%)</span>'
        f'</div>'
    )


def generate_html(prd: dict, iteration: int, added_count: int = 0) -> str:
    stories = prd.get("userStories", [])
    pending = [s for s in stories if not s.get("passes") and not s.get("_decomposed")]
    completed = [s for s in stories if s.get("passes")]
    product_name = prd.get("productName", "Project")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    epics_meta = prd.get("epics", []) if isinstance(prd.get("epics"), list) else []

    # Group pending stories by priority
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    pending.sort(key=lambda s: priority_order.get((s.get("priority") or "medium").lower(), 2))

    # Group by epic for rendering
    epic_groups = _group_by_epic(stories, epics_meta)
    has_epics = any(s.get("epicId") for s in stories)

    # Build story cards
    story_cards = []
    for s in pending:
        sid = escape(s.get("id", "?"))
        title = escape(s.get("title", "Untitled"))
        priority = (s.get("priority") or "medium").capitalize()
        priority_color = {"Critical": "#dc2626", "High": "#ef4444", "Medium": "#f59e0b", "Low": "#6b7280"}.get(priority, "#6b7280")
        cx = classify_complexity(s)
        risk = classify_risk(s)
        explanation = explain_story(s)
        impact = explain_impact(s)
        is_new = s.get("_isNew", False)

        new_badge = '<span class="badge badge-new">NEW</span>' if is_new else ""
        sub_badge = ""
        if s.get("_decomposedFrom"):
            sub_badge = f'<span class="badge badge-sub">Sub-story of {escape(s["_decomposedFrom"])}</span>'

        risk_reasons = ""
        if risk["reasons"]:
            risk_items = "".join(f"<li>{escape(r)}</li>" for r in risk["reasons"])
            risk_reasons = f'<ul class="risk-reasons">{risk_items}</ul>'

        card = f"""
        <div class="story-card" id="story-{sid}">
            <div class="story-header">
                <div class="story-id-title">
                    <span class="story-id">{sid}</span>
                    <h3 class="story-title">{title}</h3>
                    {new_badge}{sub_badge}
                </div>
                <div class="story-badges">
                    <span class="badge" style="background:{priority_color}">{priority}</span>
                    <span class="badge" style="background:{cx['color']}">{cx['icon']} {escape(cx['label'])}</span>
                    <span class="badge" style="background:{risk['color']}">{risk['icon']} Risk: {risk['level']}</span>
                </div>
            </div>
            <div class="story-body">
                <div class="section">
                    <h4>📖 What does this do? (Plain English)</h4>
                    <div class="explanation">{explanation}</div>
                </div>
                <div class="section">
                    <h4>🔧 What will be changed?</h4>
                    <div class="explanation">{impact}</div>
                </div>
                <div class="section risk-section">
                    <h4>{risk['icon']} Risk Assessment</h4>
                    <p><strong>{risk['level']} risk</strong></p>
                    {risk_reasons}
                </div>
            </div>
            <div class="story-actions">
                <span class="action-hint">Your decision:</span>
                <label class="action-btn approve"><input type="radio" name="decision-{sid}" value="approve" checked> ✅ Approve</label>
                <label class="action-btn edit"><input type="radio" name="decision-{sid}" value="edit"> ✏️ Needs Edit</label>
                <label class="action-btn reject"><input type="radio" name="decision-{sid}" value="reject"> ❌ Reject</label>
                <textarea class="notes-input" placeholder="Optional notes (e.g., what to change, why reject)..." rows="2"></textarea>
            </div>
        </div>
        """
        story_cards.append(card)

    # Summary stats
    total = len(stories)
    n_pending = len(pending)
    n_done = len(completed)
    n_new = sum(1 for s in pending if s.get("_isNew"))

    # Build card lookup by story id for epic grouping
    card_by_id = {}
    for s, card in zip(pending, story_cards):
        card_by_id[s.get("id", "")] = card

    # If any stories have epicId, render grouped; otherwise flat
    if has_epics:
        grouped_html_parts = []
        for eid, etitle, epic_stories in epic_groups:
            epic_pending = [s for s in epic_stories if not s.get("passes") and not s.get("_decomposed")]
            if not epic_pending:
                continue
            progress = _render_epic_progress_bar(epic_stories)
            grouped_html_parts.append(
                f'<div class="epic-group">'
                f'<div class="epic-header"><h3 class="epic-title">{escape(etitle)}</h3>{progress}</div>'
            )
            for s in epic_pending:
                sid = s.get("id", "")
                if sid in card_by_id:
                    grouped_html_parts.append(card_by_id[sid])
            grouped_html_parts.append('</div>')
        cards_html = "\n".join(grouped_html_parts) if grouped_html_parts else '<div class="no-stories">No pending stories to review.</div>'
    else:
        cards_html = "\n".join(story_cards) if story_cards else '<div class="no-stories">No pending stories to review.</div>'

    # Completed stories summary (collapsed)
    completed_rows = ""
    for s in completed:
        sha = s.get("_passedCommit", "")
        if sha:
            short_sha = escape(sha[:8])
            commit_cell = f'<code title="{escape(sha)}">{short_sha}</code>'
        else:
            commit_cell = '<span style="color:var(--text-dim)">—</span>'
        completed_rows += f'<tr><td>{escape(s.get("id",""))}</td><td>{escape(s.get("title",""))}</td><td>{commit_cell}</td><td><span class="badge" style="background:#22c55e">Done</span></td></tr>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SPIRAL Story Review — Iteration {iteration} | {escape(product_name)}</title>
<style>
:root {{
    --bg: #0f172a;
    --surface: #1e293b;
    --surface-2: #334155;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --accent: #3b82f6;
    --border: #475569;
    --green: #22c55e;
    --amber: #f59e0b;
    --red: #ef4444;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 0;
}}
.container {{ max-width: 960px; margin: 0 auto; padding: 24px 20px; }}

/* Header */
.header {{
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    border-bottom: 2px solid var(--accent);
    padding: 28px 0;
    margin-bottom: 28px;
}}
.header .container {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
.header h1 {{ font-size: 1.6rem; font-weight: 700; }}
.header h1 span {{ color: var(--accent); }}
.header .meta {{ color: var(--text-dim); font-size: 0.85rem; text-align: right; }}

/* Summary bar */
.summary-bar {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 14px;
    margin-bottom: 28px;
}}
.stat-card {{
    background: var(--surface);
    border-radius: 10px;
    padding: 18px;
    text-align: center;
    border: 1px solid var(--border);
}}
.stat-card .stat-value {{ font-size: 2rem; font-weight: 800; }}
.stat-card .stat-label {{ font-size: 0.78rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px; }}

/* Info box */
.info-box {{
    background: #1e3a5f;
    border: 1px solid var(--accent);
    border-radius: 10px;
    padding: 18px 22px;
    margin-bottom: 28px;
    font-size: 0.92rem;
    line-height: 1.7;
}}
.info-box h3 {{ color: var(--accent); margin-bottom: 8px; font-size: 1rem; }}
.info-box ul {{ padding-left: 20px; }}

/* Story cards */
.story-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 20px;
    overflow: hidden;
    transition: border-color 0.2s;
}}
.story-card:hover {{ border-color: var(--accent); }}
.story-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding: 18px 22px;
    background: var(--surface-2);
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
    gap: 10px;
}}
.story-id-title {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
.story-id {{ font-family: monospace; font-size: 0.85rem; color: var(--accent); font-weight: 700; white-space: nowrap; }}
.story-title {{ font-size: 1.08rem; font-weight: 600; }}
.story-badges {{ display: flex; gap: 6px; flex-wrap: wrap; }}
.badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 600;
    color: #fff;
    white-space: nowrap;
}}
.badge-new {{ background: var(--accent) !important; }}
.badge-sub {{ background: #7c3aed !important; }}
.story-body {{ padding: 18px 22px; }}
.story-body .section {{ margin-bottom: 16px; }}
.story-body .section:last-child {{ margin-bottom: 0; }}
.story-body h4 {{ font-size: 0.9rem; color: var(--accent); margin-bottom: 6px; }}
.explanation {{ font-size: 0.9rem; color: var(--text); }}
.explanation ul {{ padding-left: 20px; margin-top: 6px; }}
.explanation li {{ margin-bottom: 4px; }}
.explanation em {{ color: var(--amber); }}
.risk-section {{ padding: 12px 16px; background: rgba(255,255,255,0.03); border-radius: 8px; }}
.risk-reasons {{ font-size: 0.85rem; color: var(--text-dim); padding-left: 18px; margin-top: 4px; }}
.risk-reasons li {{ margin-bottom: 2px; }}

/* Action buttons */
.story-actions {{
    padding: 14px 22px;
    background: rgba(0,0,0,0.15);
    border-top: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}}
.action-hint {{ font-size: 0.82rem; color: var(--text-dim); white-space: nowrap; }}
.action-btn {{
    cursor: pointer;
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 0.82rem;
    font-weight: 600;
    border: 1px solid var(--border);
    background: var(--surface);
    transition: all 0.15s;
    display: inline-flex;
    align-items: center;
    gap: 4px;
}}
.action-btn input {{ display: none; }}
.action-btn:has(input:checked).approve {{ background: rgba(34,197,94,0.15); border-color: var(--green); color: var(--green); }}
.action-btn:has(input:checked).edit {{ background: rgba(245,158,11,0.15); border-color: var(--amber); color: var(--amber); }}
.action-btn:has(input:checked).reject {{ background: rgba(239,68,68,0.15); border-color: var(--red); color: var(--red); }}
.notes-input {{
    flex: 1;
    min-width: 200px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    padding: 6px 10px;
    font-size: 0.82rem;
    font-family: inherit;
    resize: vertical;
}}
.notes-input::placeholder {{ color: var(--text-dim); }}

/* Print summary button */
.print-bar {{
    text-align: center;
    margin: 28px 0;
}}
.print-btn {{
    display: inline-block;
    background: var(--accent);
    color: #fff;
    border: none;
    padding: 12px 36px;
    border-radius: 8px;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
}}
.print-btn:hover {{ opacity: 0.85; }}

/* Summary output */
#summary-output {{
    display: none;
    background: var(--surface);
    border: 2px solid var(--accent);
    border-radius: 10px;
    padding: 22px;
    margin-top: 18px;
    white-space: pre-wrap;
    font-family: monospace;
    font-size: 0.85rem;
    line-height: 1.5;
}}

/* Completed stories (collapsible) */
.completed-section {{
    margin-top: 28px;
}}
.completed-toggle {{
    cursor: pointer;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 22px;
    color: var(--text);
    font-size: 0.9rem;
    font-weight: 600;
    width: 100%;
    text-align: left;
    display: flex;
    justify-content: space-between;
    align-items: center;
}}
.completed-toggle:hover {{ border-color: var(--accent); }}
.completed-toggle .arrow {{ transition: transform 0.2s; }}
.completed-body {{
    display: none;
    background: var(--surface);
    border: 1px solid var(--border);
    border-top: none;
    border-radius: 0 0 8px 8px;
    overflow-x: auto;
}}
.completed-body table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
.completed-body th, .completed-body td {{ padding: 10px 16px; text-align: left; border-bottom: 1px solid var(--border); }}
.completed-body th {{ color: var(--text-dim); font-weight: 600; background: var(--surface-2); }}

/* Epic groups */
.epic-group {{
    margin-bottom: 24px;
}}
.epic-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 18px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 12px;
    flex-wrap: wrap;
    gap: 10px;
}}
.epic-title {{
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--accent);
}}
.epic-progress {{
    display: flex;
    align-items: center;
    gap: 8px;
}}
.epic-progress-track {{
    width: 120px;
    height: 8px;
    background: rgba(255,255,255,0.08);
    border-radius: 4px;
    overflow: hidden;
}}
.epic-progress-fill {{
    height: 100%;
    background: var(--green);
    border-radius: 4px;
    transition: width 0.3s;
}}
.epic-progress-label {{
    font-size: 0.78rem;
    color: var(--text-dim);
    white-space: nowrap;
}}

.no-stories {{
    text-align: center;
    color: var(--text-dim);
    padding: 40px;
    font-size: 1.1rem;
}}

/* Footer */
.footer {{
    text-align: center;
    color: var(--text-dim);
    font-size: 0.75rem;
    margin-top: 36px;
    padding-top: 18px;
    border-top: 1px solid var(--border);
}}

@media (max-width: 640px) {{
    .header .container {{ flex-direction: column; text-align: center; }}
    .header .meta {{ text-align: center; }}
    .story-header {{ flex-direction: column; }}
    .story-actions {{ flex-direction: column; align-items: stretch; }}
}}
</style>
</head>
<body>

<div class="header">
    <div class="container">
        <h1>🌀 <span>SPIRAL</span> Story Review</h1>
        <div class="meta">
            <div><strong>{escape(product_name)}</strong></div>
            <div>Iteration {iteration} · {now}</div>
        </div>
    </div>
</div>

<div class="container">
    <div class="summary-bar">
        <div class="stat-card">
            <div class="stat-value" style="color:var(--amber)">{n_pending}</div>
            <div class="stat-label">Pending Review</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color:var(--accent)">{added_count}</div>
            <div class="stat-label">Newly Added</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color:var(--green)">{n_done}</div>
            <div class="stat-label">Completed</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{total}</div>
            <div class="stat-label">Total Stories</div>
        </div>
    </div>

    <div class="info-box">
        <h3>📋 How to use this report</h3>
        <ul>
            <li><strong>Review</strong> each story below — they're explained in plain English so you know exactly what the AI will do.</li>
            <li><strong>Approve</strong> ✅ stories you're happy with — the AI will implement them as-is.</li>
            <li><strong>Edit</strong> ✏️ stories that need changes — add notes on what to adjust, then edit prd.json before proceeding.</li>
            <li><strong>Reject</strong> ❌ stories you don't want — remove them from prd.json before proceeding.</li>
            <li>Click <strong>"Generate Summary"</strong> at the bottom to get a text summary of your decisions you can paste or reference.</li>
        </ul>
    </div>

    <h2 style="margin-bottom:16px; font-size:1.2rem;">📝 Stories Awaiting Your Approval</h2>

    {cards_html}

    <div class="print-bar">
        <button class="print-btn" onclick="generateSummary()">📋 Generate Decision Summary</button>
    </div>
    <pre id="summary-output"></pre>

    {"" if not completed_rows else f'''
    <div class="completed-section">
        <button class="completed-toggle" onclick="toggleCompleted()">
            <span>✅ Already Completed ({n_done} stories)</span>
            <span class="arrow" id="completed-arrow">▶</span>
        </button>
        <div class="completed-body" id="completed-body">
            <table>
                <tr><th>ID</th><th>Title</th><th>Commit</th><th>Status</th></tr>
                {completed_rows}
            </table>
        </div>
    </div>
    '''}

    <div class="footer">
        Generated by SPIRAL · story_review_report.py · {now}
    </div>
</div>

<script>
function generateSummary() {{
    const cards = document.querySelectorAll('.story-card');
    let lines = ['SPIRAL Story Review — Iteration {iteration} — {now}', ''];
    let approved = 0, edits = 0, rejected = 0;

    cards.forEach(card => {{
        const id = card.querySelector('.story-id')?.textContent || '?';
        const title = card.querySelector('.story-title')?.textContent || '?';
        const checked = card.querySelector('input[type=radio]:checked');
        const decision = checked ? checked.value : 'approve';
        const notes = card.querySelector('.notes-input')?.value?.trim() || '';
        const icon = decision === 'approve' ? '✅' : decision === 'edit' ? '✏️' : '❌';

        if (decision === 'approve') approved++;
        else if (decision === 'edit') edits++;
        else rejected++;

        let line = `${{icon}} ${{id}} — ${{title}} → ${{decision.toUpperCase()}}`;
        if (notes) line += `\\n   Notes: ${{notes}}`;
        lines.push(line);
    }});

    lines.push('');
    lines.push(`Summary: ${{approved}} approved, ${{edits}} need edits, ${{rejected}} rejected`);
    lines.push(`Total: ${{cards.length}} stories reviewed`);

    const el = document.getElementById('summary-output');
    el.textContent = lines.join('\\n');
    el.style.display = 'block';
    el.scrollIntoView({{ behavior: 'smooth' }});

    // Also copy to clipboard
    navigator.clipboard?.writeText(lines.join('\\n')).catch(() => {{}});
}}

function toggleCompleted() {{
    const body = document.getElementById('completed-body');
    const arrow = document.getElementById('completed-arrow');
    if (body.style.display === 'block') {{
        body.style.display = 'none';
        arrow.textContent = '▶';
    }} else {{
        body.style.display = 'block';
        arrow.textContent = '▼';
    }}
}}
</script>
</body>
</html>"""


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate SPIRAL story review HTML report")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--iter", type=int, default=0, help="Current spiral iteration number")
    parser.add_argument("--added", type=int, default=0, help="Number of stories added this iteration")
    parser.add_argument("--output", default=".spiral/gate-reports", help="Output directory for reports")
    parser.add_argument("--open", action="store_true", help="Open the report in the default browser")
    args = parser.parse_args()

    prd = load_prd(args.prd)

    # Ensure output directory exists
    os.makedirs(args.output, exist_ok=True)

    # Generate timestamped filename
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"story-review-iter-{args.iter}-{ts}.html"
    filepath = os.path.join(args.output, filename)

    # Also write a "latest" symlink/copy for easy access
    latest_path = os.path.join(args.output, "latest-review.html")

    html = generate_html(prd, args.iter, args.added)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    # Copy to latest (cross-platform — symlinks tricky on Windows)
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  [G] Story review report: {filepath}")

    if args.open:
        try:
            if sys.platform == "win32":
                os.startfile(filepath)
            elif sys.platform == "darwin":
                subprocess.run(["open", filepath], check=False)
            else:
                subprocess.run(["xdg-open", filepath], check=False)
        except Exception:
            pass

    return filepath


if __name__ == "__main__":
    main()
