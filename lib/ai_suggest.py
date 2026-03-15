#!/usr/bin/env python3
"""
SPIRAL Phase A — AI Story Suggestions (Source 2, per-iteration)

Analyzes prd.json state each iteration and generates AI story suggestions
to fill coverage gaps. Also loads queued ai-example picks from Phase 0-D.

Inputs:
  prd.json                         — current PRD state
  .spiral/_ai_example_queue.json   — picks queued from Phase 0-D (optional)

Output:
  .spiral/_ai_suggest_output.json  — {"stories": [...]} with _source="ai-example"

Gap detection heuristics:
  1. Epics with zero pending stories
  2. Goals whose keywords appear in fewer than 30% of existing story titles
  3. Focus theme gaps (if SPIRAL_FOCUS set)
  4. Dependency chains ending in passed stories (next logical story)
"""
import argparse
import json
import os
import re
import sys
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_STOPWORDS = {
    "the", "and", "for", "are", "was", "this", "with", "from", "that",
    "not", "all", "can", "but", "has", "new", "add", "run", "use",
    "set", "get", "put", "may", "via", "its", "also", "any", "each",
    "when", "have", "been", "will", "into", "only", "more", "such",
}


def _tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", text.lower())
        if len(w) >= 3 and w not in _STOPWORDS
    }


def _atomic_write(data: Any, path: str) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def load_queue(queue_path: str) -> list[dict]:
    """Load ai-example picks queued from Phase 0-D."""
    if not os.path.exists(queue_path):
        return []
    try:
        with open(queue_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("stories", [])
    except (json.JSONDecodeError, OSError):
        return []


def clear_queue(queue_path: str) -> None:
    """Clear the queue after consuming it."""
    try:
        _atomic_write({"stories": []}, queue_path)
    except OSError:
        pass


def analyze_gaps(prd: dict, focus: str = "", max_suggest: int = 5) -> list[dict]:
    """Analyze prd.json and generate story suggestions for coverage gaps."""
    suggestions: list[dict] = []

    goals: list[str] = prd.get("goals", [])
    epics: list[dict] = prd.get("epics", [])
    existing_stories: list[dict] = prd.get("userStories", [])

    # Build token coverage from existing story titles
    existing_title_tokens: set[str] = set()
    for story in existing_stories:
        existing_title_tokens |= _tokens(story.get("title", ""))

    # Track epic story counts
    epic_pending: dict[str, int] = {}
    for story in existing_stories:
        eid = story.get("epicId", "")
        if eid and not story.get("passes"):
            epic_pending[eid] = epic_pending.get(eid, 0) + 1

    # 1. Epics with zero pending stories (coverage gap)
    for epic in epics:
        if len(suggestions) >= max_suggest:
            break
        eid = epic.get("id", "")
        etitle = epic.get("title", "").strip()
        edesc = (epic.get("description") or "").strip()
        if not etitle or epic_pending.get(eid, 0) > 0:
            continue
        # Epic has no pending stories — suggest one
        suggestions.append({
            "title": f"Implement {etitle}",
            "description": edesc or f"Core implementation for epic: {etitle}",
            "_source": "ai-example",
            "priority": "medium",
            "acceptanceCriteria": [f"Epic {eid} has at least one working implementation"],
            "dependencies": [],
            "epicId": eid,
        })

    # 2. Goals with low keyword coverage
    for goal in goals:
        if len(suggestions) >= max_suggest:
            break
        goal_kw = _tokens(goal)
        if len(goal_kw) < 3:
            continue
        coverage = len(goal_kw & existing_title_tokens) / len(goal_kw)
        if coverage < 0.3:
            title = goal.strip()[:80]
            suggestions.append({
                "title": f"Implement: {title}",
                "description": f"Story to address low-coverage project goal: {goal.strip()}",
                "_source": "ai-example",
                "priority": "medium",
                "acceptanceCriteria": [f"Goal achieved: {goal.strip()[:120]}"],
                "dependencies": [],
            })

    # 3. Focus theme gap
    if focus and len(suggestions) < max_suggest:
        focus_primary = focus.split("|")[0].strip()
        focus_kw = _tokens(focus_primary)
        if focus_kw:
            coverage = len(focus_kw & existing_title_tokens) / len(focus_kw)
            if coverage < 0.5:
                suggestions.append({
                    "title": f"Improve {focus_primary} — fill coverage gap",
                    "description": (
                        f"Additional stories needed to achieve the '{focus_primary}' "
                        f"focus theme. Current keyword coverage: {coverage:.0%}."
                    ),
                    "_source": "ai-example",
                    "priority": "medium",
                    "acceptanceCriteria": [
                        f"Focus area '{focus_primary}' has improved story coverage",
                    ],
                    "dependencies": [],
                })

    # 4. Dependency chain extension: passed stories whose dependents aren't yet planned
    passed_ids = {s.get("id") for s in existing_stories if s.get("passes")}
    planned_ids = {s.get("id") for s in existing_stories}
    for story in existing_stories:
        if len(suggestions) >= max_suggest:
            break
        if not story.get("passes"):
            continue
        # If this story has no dependent stories and was complex, suggest a follow-up
        complexity = story.get("estimatedComplexity", "medium")
        has_dependents = any(
            story.get("id") in s.get("dependencies", [])
            for s in existing_stories
            if not s.get("passes")
        )
        if complexity == "large" and not has_dependents:
            suggestions.append({
                "title": f"Extend {story.get('title', '')[:60]} — next iteration",
                "description": (
                    f"Follow-up story to extend the large completed story "
                    f"{story.get('id')}: {story.get('title', '')}"
                ),
                "_source": "ai-example",
                "priority": "low",
                "acceptanceCriteria": [
                    f"Extends or builds upon {story.get('id')} with additional capability",
                ],
                "dependencies": [story.get("id", "")],
            })

    return suggestions


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase A: Generate AI story suggestions (Source 2, per-iteration)"
    )
    parser.add_argument("--prd", default="prd.json")
    parser.add_argument(
        "--queue",
        default=".spiral/_ai_example_queue.json",
        help="Path to ai-example picks queued from Phase 0-D",
    )
    parser.add_argument("--out", default=".spiral/_ai_suggest_output.json")
    parser.add_argument("--focus", default="")
    parser.add_argument(
        "--max-suggest",
        type=int,
        default=5,
        help="Max AI-generated gap suggestions per iteration (default: 5)",
    )
    parser.add_argument(
        "--clear-queue",
        action="store_true",
        help="Clear the Phase 0-D queue after consuming it (default: keep)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"  [A] WARNING: {args.prd} not found — no AI suggestions this iteration")
        _atomic_write({"stories": []}, args.out)
        return 0

    with open(args.prd, encoding="utf-8") as f:
        prd = json.load(f)

    # Load Phase 0-D queued picks
    queued = load_queue(args.queue)
    if queued:
        print(f"  [A] Loaded {len(queued)} queued ai-example pick(s) from Phase 0-D")

    # Generate gap-analysis suggestions
    generated = analyze_gaps(prd, focus=args.focus, max_suggest=args.max_suggest)
    if generated:
        print(f"  [A] Generated {len(generated)} AI suggestion(s) from PRD gap analysis")

    all_suggestions = queued + generated

    # Deduplicate by lowercase title; ensure all tagged as ai-example
    seen: set[str] = set()
    unique: list[dict] = []
    for s in all_suggestions:
        key = s.get("title", "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            s["_source"] = "ai-example"
            unique.append(s)

    _atomic_write({"stories": unique}, args.out)
    print(f"  [A] AI suggestions: {len(unique)} candidate(s) → {args.out}")

    if args.clear_queue and queued:
        clear_queue(args.queue)
        print(f"  [A] Queue cleared ({args.queue})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
