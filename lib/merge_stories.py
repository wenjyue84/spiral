#!/usr/bin/env python3
"""
SPIRAL Phase M — Merge Stories
Loads _research_output.json + _test_stories_output.json + optional overflow cache,
deduplicates against prd.json, assigns sequential IDs, and atomically patches prd.json.

Order: test-failure candidates first (known bugs > new features), then research/overflow.
Overflow: unused research candidates (cap-blocked, not duplicates) are persisted to
          --overflow-out and consumed next iteration via --overflow-in.
Cap: --max-new 50 total additions per SPIRAL iteration.
"""
import argparse
import json
import os
import re
import sys
from typing import Any

from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(__file__))
from constants import PRIORITY_RANK
from llm_models import ResearchOutput, log_validation_error
from prd_schema import validate_prd
from spiral_io import atomic_write_json, configure_utf8_stdout
from txn_journal import TxnJournal

configure_utf8_stdout()

# Story ID prefix from env
STORY_PREFIX = os.environ.get("SPIRAL_STORY_PREFIX", "US")


def normalize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def overlap_ratio(a: str, b: str) -> float:
    wa = normalize(a)
    wb = normalize(b)
    if not wa:
        return 0.0
    return len(wa & wb) / len(wa)


def is_duplicate(candidate_title: str, existing_titles: list[str], threshold: float = 0.6,
                 candidate_epic: str = "", existing_epics: list[str] | None = None) -> bool:
    """Check if candidate is duplicate of any existing title.

    When both candidate and existing share the same non-empty epicId, the
    threshold is lowered (0.45) to catch near-duplicates within the same epic.
    """
    epic_threshold = 0.45  # stricter within same epic
    for i, existing in enumerate(existing_titles):
        same_epic = (
            candidate_epic
            and existing_epics is not None
            and i < len(existing_epics)
            and existing_epics[i] == candidate_epic
        )
        t = epic_threshold if same_epic else threshold
        if overlap_ratio(candidate_title, existing) >= t:
            return True
        if overlap_ratio(existing, candidate_title) >= t:
            return True
    return False


def find_next_id(stories: list[dict[str, Any]]) -> int:
    """Scan all PREFIX-NNN ids, return max+1. Handles gaps safely."""
    ids = []
    for s in stories:
        m = re.match(rf"{re.escape(STORY_PREFIX)}-(\d+)$", s.get("id", ""))
        if m:
            ids.append(int(m.group(1)))
    return max(ids) + 1 if ids else 1


def sort_key(story: dict[str, Any]) -> int:
    return PRIORITY_RANK.get(story.get("priority", "medium"), 2)


def _is_done(story: dict[str, Any]) -> bool:
    """Return True if story is completed, decomposed, or skipped."""
    return bool(
        story.get("passes")
        or story.get("_decomposed")
        or story.get("_skipped")
    )


def full_sort_key(story: dict[str, Any]) -> tuple[int, int, int]:
    """Sort key for post-merge ordering.

    Returns (done_rank, priority_rank, dep_count) so that:
    - Active stories come before done/decomposed/skipped
    - Higher priority (critical=0) comes first
    - Fewer dependencies come first within same priority
    Python's stable sort preserves relative order for equal keys.
    """
    done_rank = 1 if _is_done(story) else 0
    priority_rank = PRIORITY_RANK.get(story.get("priority", "medium"), 2)
    dep_count = len(story.get("dependencies", []))
    return (done_rank, priority_rank, dep_count)


def matches_focus(story: dict[str, Any], focus: str) -> bool:
    """Case-insensitive keyword match against title + description."""
    if not focus:
        return True
    focus_lower = focus.lower()
    searchable = (story.get("title", "") + " " + story.get("description", "")).lower()
    return focus_lower in searchable


def load_candidates(path: str) -> list[dict[str, Any]]:
    if not os.path.isfile(path):
        print(f"[merge] WARNING: {path} not found — treating as empty")
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # Validate with Pydantic model (US-203)
    try:
        validated = ResearchOutput.model_validate(data)
        return [s.model_dump() for s in validated.stories]
    except ValidationError as exc:
        log_validation_error(exc, data, f"merge_stories:load_candidates({path})")
        print(f"[merge] WARNING: validation failed for {path}: {exc}")
        # Graceful fallback: return raw stories to avoid blocking the pipeline
        return data.get("stories", [])


def story_to_prd_entry(story: dict[str, Any], story_id: str) -> dict[str, Any]:
    """Convert candidate story to prd.json format. Preserve _source for audit trail."""
    entry: dict[str, Any] = {
        "id": story_id,
        "title": story["title"],
        "priority": story.get("priority", "medium"),
        "description": story.get("description", ""),
        "acceptanceCriteria": story.get("acceptanceCriteria", []),
        "technicalNotes": story.get("technicalNotes", []),
        "dependencies": story.get("dependencies", []),
        "estimatedComplexity": story.get("estimatedComplexity", "medium"),
        "passes": False,
    }
    if "_source" in story:
        entry["_source"] = story["_source"]
    # Enhancement 7: flag test-synthesis stories for audit trail + future ralph prioritisation
    if story.get("_isTestFix"):
        entry["isTestFix"] = True
    # Carry over tags from research output; auto-assign 'bugfix' for test-fix stories
    tags = list(story.get("tags", []))
    if story.get("_isTestFix") and "bugfix" not in tags:
        tags.append("bugfix")
    if tags:
        entry["tags"] = tags
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description="SPIRAL story merger")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    parser.add_argument(
        "--research",
        default=".spiral/_research_output.json",
        help="Research output JSON",
    )
    parser.add_argument(
        "--test-stories",
        default=".spiral/_test_stories_output.json",
        help="Test synthesis output JSON",
    )
    parser.add_argument(
        "--overflow-in",
        default="",
        metavar="PATH",
        help="Overflow cache from previous iteration (unused research candidates)",
    )
    parser.add_argument(
        "--overflow-out",
        default="",
        metavar="PATH",
        help="Write leftover research candidates here for next iteration",
    )
    parser.add_argument("--max-new", type=int, default=50, help="Max new stories to add per iteration")
    parser.add_argument("--max-pending", type=int, default=0, help="Max total pending (incomplete) stories allowed. 0 = unlimited")
    parser.add_argument("--focus", default="", help="Focus theme — hard-filter research, soft-prioritize tests")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"[merge] ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    with open(args.prd, encoding="utf-8") as f:
        prd = json.load(f)

    errors = validate_prd(prd)
    if errors:
        print("[schema] PRD validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    existing_stories: list[dict[str, Any]] = prd.get("userStories", [])
    existing_titles = [s.get("title", "") for s in existing_stories]
    existing_epics = [s.get("epicId", "") for s in existing_stories]

    current_pending = sum(1 for s in existing_stories if not s.get("passes"))
    print(f"[merge] prd.json: {len(existing_stories)} existing stories ({current_pending} pending)")

    # Compute effective cap: min(max_new, remaining room under max_pending)
    effective_cap = args.max_new
    if args.max_pending > 0:
        room = max(0, args.max_pending - current_pending)
        effective_cap = min(effective_cap, room)
        print(f"[merge] Max pending limit: {args.max_pending} (current: {current_pending}, room: {room})")
        if room == 0:
            print(f"[merge] At or over max pending limit ({current_pending}/{args.max_pending}) — no new stories will be added")
            return 0

    # Load all candidate sources
    test_candidates = load_candidates(args.test_stories)
    research_candidates = load_candidates(args.research)
    overflow_candidates = load_candidates(args.overflow_in) if args.overflow_in else []

    # ── Cap research candidates per iteration (before dedup) ─────────────────
    max_research = int(os.environ.get("SPIRAL_MAX_RESEARCH_STORIES", "0"))
    if max_research > 0 and len(research_candidates) > max_research:
        print(f"[merge] Capping research output: {len(research_candidates)} → {max_research} stories")
        research_candidates = research_candidates[:max_research]

    if overflow_candidates:
        print(f"[merge] Overflow (carried from previous iteration): {len(overflow_candidates)} candidates")
    print(f"[merge] Test candidates: {len(test_candidates)}, Research candidates: {len(research_candidates)}")

    # Sort each group by priority
    test_candidates.sort(key=sort_key)
    research_candidates.sort(key=sort_key)

    if args.focus:
        test_candidates.sort(key=lambda s: (0 if matches_focus(s, args.focus) else 1, sort_key(s)))
        print(f"[merge] Focus: \"{args.focus}\" — research hard-filtered, test stories soft-prioritized")

    new_stories: list[dict[str, Any]] = []
    seen_titles: list[str] = list(existing_titles)
    seen_epics: list[str] = list(existing_epics)

    # ── Tag test candidates with source if not already set ────────────────────
    for story in test_candidates:
        if "_source" not in story:
            story["_source"] = "test-fix"

    # ── Group 1: Test-synthesis candidates (never overflow — regenerated each iteration) ──
    for story in test_candidates:
        if len(new_stories) >= effective_cap:
            print(f"[merge] Cap of {effective_cap} reached during test candidates")
            break
        title = story.get("title", "")
        if not title:
            continue
        cand_epic = story.get("epicId", "")
        if is_duplicate(title, seen_titles, candidate_epic=cand_epic, existing_epics=seen_epics):
            print(f"[merge] Skip duplicate (test): {title[:80]}")
            continue
        story["_isTestFix"] = True
        new_stories.append(story)
        seen_titles.append(title)
        seen_epics.append(cand_epic)

    # ── Promote test-story/test-fix from research pool to Group 1 ───────────────
    # _validated_stories.json may contain mixed sources; extract high-priority ones.
    _promoted: list[dict[str, Any]] = []
    _remaining_research: list[dict[str, Any]] = []
    for _s in research_candidates:
        if _s.get("_source") in ("test-fix", "test-story"):
            _promoted.append(_s)
        else:
            _remaining_research.append(_s)
    if _promoted:
        for _s in _promoted:
            if "_source" not in _s:
                _s["_source"] = "test-fix"
        # Process promoted stories through Group 1 pipeline
        for story in sorted(_promoted, key=sort_key):
            if len(new_stories) >= effective_cap:
                break
            title = story.get("title", "")
            if not title:
                continue
            cand_epic = story.get("epicId", "")
            if is_duplicate(title, seen_titles, candidate_epic=cand_epic, existing_epics=seen_epics):
                print(f"[merge] Skip duplicate (promoted): {title[:80]}")
                continue
            story["_isTestFix"] = True
            new_stories.append(story)
            seen_titles.append(title)
            seen_epics.append(cand_epic)
        research_candidates = _remaining_research

    # ── Group 2: Research pool = overflow (older, prioritised) + fresh research ──
    # Non-duplicate cap-blocked candidates are saved to the overflow file
    research_pool = list(overflow_candidates) + list(research_candidates)
    leftover_research: list[dict[str, Any]] = []

    for story in research_pool:
        title = story.get("title", "")
        if not title:
            continue
        if args.focus and not matches_focus(story, args.focus):
            print(f"[merge] Skip (focus mismatch): {title[:80]}")
            continue
        cand_epic = story.get("epicId", "")
        if is_duplicate(title, seen_titles, candidate_epic=cand_epic, existing_epics=seen_epics):
            print(f"[merge] Skip duplicate (research): {title[:80]}")
            continue
        if len(new_stories) >= effective_cap:
            # Cap hit — save non-duplicate for next iteration
            leftover_research.append({k: v for k, v in story.items() if not k.startswith("_")})
        else:
            new_stories.append(story)
            seen_titles.append(title)
            seen_epics.append(cand_epic)

    if not new_stories and not (args.overflow_out and leftover_research):
        # No overflow to write and no new stories
        if args.overflow_out:
            atomic_write_json(args.overflow_out, {"stories": leftover_research})
            print(f"[merge] Overflow: cleared (all candidates consumed or cap not reached)")
        if not new_stories:
            print("[merge] No new stories to add — prd.json unchanged")
            return 0

    # ── Assign IDs and patch prd.json atomically ──────────────────────────────
    next_num = find_next_id(existing_stories)
    added_entries = []
    for story in new_stories:
        story_id = f"{STORY_PREFIX}-{next_num:03d}"
        next_num += 1
        entry = story_to_prd_entry(story, story_id)
        added_entries.append(entry)
        flag = " [testFix]" if entry.get("isTestFix") else ""
        print(f"[merge] Adding [{story_id}] ({entry['priority']}){flag} {entry['title'][:70]}")

    prd["userStories"] = existing_stories + added_entries

    # ── Post-merge sort: priority order so ralph picks highest-priority first ──
    prd["userStories"].sort(key=full_sort_key)

    # ── Transaction-safe write: journal both files for crash recovery ─────────
    scratch_dir = os.environ.get("SPIRAL_SCRATCH_DIR", ".spiral")
    journal = TxnJournal(os.path.join(scratch_dir, "_txn_journal.jsonl"))
    with journal.transaction("phase_m_merge") as txn:
        if args.overflow_out:
            txn.write_json(args.overflow_out, {"stories": leftover_research})
            if leftover_research:
                print(
                    f"[merge] Overflow: {len(leftover_research)} unused research candidates "
                    f"→ {args.overflow_out}"
                )
            else:
                print(f"[merge] Overflow: cleared (all candidates consumed or cap not reached)")
        txn.write_json(args.prd, prd)

    # Source breakdown
    src_counts: dict[str, int] = {}
    for entry in added_entries:
        src = entry.get("_source", "research")
        src_counts[src] = src_counts.get(src, 0) + 1
    if src_counts:
        parts = ", ".join(f"{k}={v}" for k, v in src_counts.items())
        print(f"[merge] Added by source: {parts}")

    total_after = len(prd["userStories"])
    pending_after = sum(1 for s in prd["userStories"] if not s.get("passes"))
    print(
        f"[merge] Done: added {len(added_entries)} stories. "
        f"prd.json now has {total_after} total ({pending_after} pending)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
