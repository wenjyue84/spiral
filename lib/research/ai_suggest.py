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
  Fallback (when primary heuristics yield < max_suggest):
  A. Refactor/Optimize/Harden recently-passed stories
  B. Add test coverage for passed non-test stories
  C. Profile and optimize large passed stories
  D. Expand epics with below-average story density
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json, configure_utf8_stdout

configure_utf8_stdout()

_STOPWORDS = {
    "the",
    "and",
    "for",
    "are",
    "was",
    "this",
    "with",
    "from",
    "that",
    "not",
    "all",
    "can",
    "but",
    "has",
    "new",
    "add",
    "run",
    "use",
    "set",
    "get",
    "put",
    "may",
    "via",
    "its",
    "also",
    "any",
    "each",
    "when",
    "have",
    "been",
    "will",
    "into",
    "only",
    "more",
    "such",
}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in _STOPWORDS}


def _normalize(text: str) -> set[str]:
    """Raw token set for dedup pre-flight — no stopword filter, matches merge_stories.normalize().

    NOTE: keep in sync with lib/prd/merge_stories.normalize().
    """
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: str, b: str) -> float:
    """Symmetric Jaccard similarity — mirrors merge_stories.jaccard_similarity()."""
    wa, wb = _normalize(a), _normalize(b)
    union = wa | wb
    return len(wa & wb) / len(union) if union else 0.0


def _would_be_duplicate(title: str, existing_titles: list[str], threshold: float = 0.6) -> bool:
    """Return True if title would be deduplicated by Phase M's is_duplicate()."""
    return any(_jaccard(title, ex) >= threshold for ex in existing_titles)


def load_queue(queue_path: str) -> list[dict[str, Any]]:
    """Load ai-example picks queued from Phase 0-D."""
    if not os.path.exists(queue_path):
        return []
    try:
        with open(queue_path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
        return data.get("stories", [])  # type: ignore[return-value]
    except (json.JSONDecodeError, OSError):
        return []


def clear_queue(queue_path: str) -> None:
    """Clear the queue after consuming it."""
    try:
        atomic_write_json(queue_path, {"stories": []})
    except OSError:
        pass


def _generate_fallback_suggestions(
    prd: dict[str, Any],
    known_titles: list[str],
    needed: int,
) -> list[dict[str, Any]]:
    """Fallback story suggestions when primary heuristics find nothing.

    Angles (in order):
      A. Refactor/Optimize/Harden recently-passed stories
      B. Add test coverage for passed non-test stories
      C. Profile and optimize large/complex passed stories
      D. Expand epics with below-average story density
    """
    results: list[dict[str, Any]] = []
    seen: list[str] = list(known_titles)

    passed = sorted(
        [s for s in prd.get("userStories", []) if s.get("passes")],
        key=lambda s: int(re.sub(r"\D", "", s.get("id", "0")) or "0"),
        reverse=True,
    )

    # Angle A: enhance/refactor recently-passed stories
    verbs = [("Refactor", "medium"), ("Optimize", "medium"), ("Harden", "low")]
    for story in passed:
        for verb, priority in verbs:
            if len(results) >= needed:
                break
            title = f"{verb} {story.get('title', '')[:55]}"
            if not _would_be_duplicate(title, seen):
                results.append(
                    {
                        "title": title,
                        "description": f"Improve {story.get('title', '')} — quality/maintainability angle",
                        "_source": "ai-example",
                        "priority": priority,
                        "acceptanceCriteria": [],
                        "dependencies": [],
                    }
                )
                seen.append(title)

    # Angle B: test coverage for passed non-test stories
    for story in passed:
        if len(results) >= needed:
            break
        if "test" in story.get("title", "").lower():
            continue
        title = f"Add test coverage for {story.get('title', '')[:50]}"
        if not _would_be_duplicate(title, seen):
            results.append(
                {
                    "title": title,
                    "description": f"Improve test coverage for {story.get('title', '')}",
                    "_source": "ai-example",
                    "priority": "low",
                    "acceptanceCriteria": [],
                    "dependencies": [],
                }
            )
            seen.append(title)

    # Angle C: performance profile for large/complex passed stories
    for story in passed:
        if len(results) >= needed:
            break
        if story.get("estimatedComplexity") != "large":
            continue
        title = f"Profile and optimize {story.get('title', '')[:50]}"
        if not _would_be_duplicate(title, seen):
            results.append(
                {
                    "title": title,
                    "description": f"Performance profiling for large story {story.get('id', '')}",
                    "_source": "ai-example",
                    "priority": "low",
                    "acceptanceCriteria": [],
                    "dependencies": [story.get("id", "")],
                }
            )
            seen.append(title)

    # Angle D: expand epics with below-average story count
    epic_counts: Counter[str] = Counter(
        s.get("epicId", "") for s in prd.get("userStories", []) if s.get("epicId")
    )
    avg = sum(epic_counts.values()) / len(epic_counts) if epic_counts else 0.0
    for epic in prd.get("epics", []):
        if len(results) >= needed:
            break
        eid = epic.get("id", "")
        if epic_counts.get(eid, 0) >= avg * 0.5:
            continue
        title = f"Expand {epic.get('title', '')[:55]} — increase story coverage"
        if not _would_be_duplicate(title, seen):
            results.append(
                {
                    "title": title,
                    "description": f"Epic {eid} has fewer stories than average — add coverage",
                    "_source": "ai-example",
                    "priority": "low",
                    "acceptanceCriteria": [],
                    "dependencies": [],
                    "epicId": eid,
                }
            )
            seen.append(title)

    return results


def analyze_gaps(
    prd: dict[str, Any],
    focus: str = "",
    max_suggest: int = 5,
    current_pending: int = 0,
    max_pending: int = 0,
) -> list[dict[str, Any]]:
    """Analyze prd.json and generate story suggestions for coverage gaps."""
    # Respect max_pending cap — skip all suggestions if already at limit
    if max_pending > 0 and current_pending >= max_pending:
        return []

    suggestions: list[dict[str, Any]] = []

    goals: list[str] = prd.get("goals", [])
    epics: list[dict[str, Any]] = prd.get("epics", [])
    existing_stories: list[dict[str, Any]] = prd.get("userStories", [])
    existing_titles = [s.get("title", "") for s in existing_stories]

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
        title = f"Implement {etitle}"
        all_known = existing_titles + [s["title"] for s in suggestions]
        if _would_be_duplicate(title, all_known):
            continue
        suggestions.append(
            {
                "title": title,
                "description": edesc or f"Core implementation for epic: {etitle}",
                "_source": "ai-example",
                "priority": "medium",
                "acceptanceCriteria": [f"Epic {eid} has at least one working implementation"],
                "dependencies": [],
                "epicId": eid,
            }
        )

    # 2. Goals with low keyword coverage
    for goal in goals:
        if len(suggestions) >= max_suggest:
            break
        goal_kw = _tokens(goal)
        if len(goal_kw) < 3:
            continue
        coverage = len(goal_kw & existing_title_tokens) / len(goal_kw)
        if coverage < 0.3:
            title = f"Implement: {goal.strip()[:80]}"
            all_known = existing_titles + [s["title"] for s in suggestions]
            if _would_be_duplicate(title, all_known):
                continue
            suggestions.append(
                {
                    "title": title,
                    "description": f"Story to address low-coverage project goal: {goal.strip()}",
                    "_source": "ai-example",
                    "priority": "medium",
                    "acceptanceCriteria": [f"Goal achieved: {goal.strip()[:120]}"],
                    "dependencies": [],
                }
            )

    # 3. Focus theme gap
    if focus and len(suggestions) < max_suggest:
        focus_primary = focus.split("|")[0].strip()
        focus_kw = _tokens(focus_primary)
        if focus_kw:
            coverage = len(focus_kw & existing_title_tokens) / len(focus_kw)
            if coverage < 0.5:
                title = f"Improve {focus_primary} — fill coverage gap"
                all_known = existing_titles + [s["title"] for s in suggestions]
                if not _would_be_duplicate(title, all_known):
                    suggestions.append(
                        {
                            "title": title,
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
                        }
                    )

    # 4. Dependency chain extension: passed stories whose dependents aren't yet planned
    for story in existing_stories:
        if len(suggestions) >= max_suggest:
            break
        if not story.get("passes"):
            continue
        # If this story has no dependent stories and was complex, suggest a follow-up
        complexity = story.get("estimatedComplexity", "medium")
        has_dependents = any(
            story.get("id") in s.get("dependencies", []) for s in existing_stories if not s.get("passes")
        )
        if complexity == "large" and not has_dependents:
            title = f"Extend {story.get('title', '')[:60]} — next iteration"
            all_known = existing_titles + [s["title"] for s in suggestions]
            if _would_be_duplicate(title, all_known):
                continue
            suggestions.append(
                {
                    "title": title,
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
                }
            )

    # Fill remaining slots with fallback suggestions
    if len(suggestions) < max_suggest:
        all_known = existing_titles + [s["title"] for s in suggestions]
        fallbacks = _generate_fallback_suggestions(
            prd,
            known_titles=all_known,
            needed=max_suggest - len(suggestions),
        )
        suggestions.extend(fallbacks)

    return suggestions


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase A: Generate AI story suggestions (Source 2, per-iteration)")
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
    parser.add_argument(
        "--pending",
        type=int,
        default=0,
        help="Current pending story count (from PENDING var in spiral.sh)",
    )
    parser.add_argument(
        "--max-pending",
        type=int,
        default=0,
        help="SPIRAL_MAX_PENDING cap (0 = no cap check)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"  [A] WARNING: {args.prd} not found — no AI suggestions this iteration")
        atomic_write_json(args.out, {"stories": []})
        return 0

    with open(args.prd, encoding="utf-8") as f:
        prd: dict[str, Any] = json.load(f)

    # Load Phase 0-D queued picks
    queued = load_queue(args.queue)
    if queued:
        print(f"  [A] Loaded {len(queued)} queued ai-example pick(s) from Phase 0-D")

    # Generate gap-analysis suggestions
    generated = analyze_gaps(
        prd,
        focus=args.focus,
        max_suggest=args.max_suggest,
        current_pending=args.pending,
        max_pending=args.max_pending,
    )
    if generated:
        print(f"  [A] Generated {len(generated)} AI suggestion(s) from PRD gap analysis")

    all_suggestions = queued + generated

    # Deduplicate by lowercase title; ensure all tagged as ai-example
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for s in all_suggestions:
        key = s.get("title", "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            s["_source"] = "ai-example"
            unique.append(s)

    atomic_write_json(args.out, {"stories": unique})
    print(f"  [A] AI suggestions: {len(unique)} candidate(s) → {args.out}")

    if args.clear_queue and queued:
        clear_queue(args.queue)
        print(f"  [A] Queue cleared ({args.queue})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
