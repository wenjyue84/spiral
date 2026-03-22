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
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conflict_detector import detect_federated_conflicts
from llm_models import ResearchOutput, log_validation_error
from merge_results_tsv import HEADER as RESULTS_HEADER
from prd_schema import validate_prd
from spiral_io import atomic_write_json, configure_utf8_stdout
from story_helpers import priority_key
from txn_journal import TxnJournal

configure_utf8_stdout()

# Story ID prefix from env
STORY_PREFIX = os.environ.get("SPIRAL_STORY_PREFIX", "US")


def _log_conflicts_to_results(results_tsv: str, conflicts: list[dict[str, Any]]) -> None:
    """Append one conflict-detected row per conflict pair to results.tsv."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_header = not os.path.isfile(results_tsv)
    with open(results_tsv, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=RESULTS_HEADER,
            delimiter="\t",
            extrasaction="ignore",
            lineterminator="\n",
        )
        if write_header:
            writer.writeheader()
        for c in conflicts:
            writer.writerow(
                {
                    "timestamp": ts,
                    "story_id": c["storyA"],
                    "status": "conflict_detected",
                    "conflict_files": c["conflict_files"],
                }
            )


def normalize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def overlap_ratio(a: str, b: str) -> float:
    wa = normalize(a)
    wb = normalize(b)
    if not wa:
        return 0.0
    return len(wa & wb) / len(wa)


def jaccard_similarity(a: str, b: str) -> float:
    """Symmetric Jaccard similarity: |intersection| / |union|.

    Eliminates false positives from short candidates matching long existing titles.
    Returns 0.0 when both strings are empty.
    """
    wa = normalize(a)
    wb = normalize(b)
    union = wa | wb
    if not union:
        return 0.0
    return len(wa & wb) / len(union)


def is_duplicate(
    candidate_title: str,
    existing_titles: list[str],
    threshold: float = 0.6,
    candidate_epic: str = "",
    existing_epics: list[str] | None = None,
) -> bool:
    """Check if candidate is duplicate of any existing title.

    Uses symmetric Jaccard similarity to avoid false positives where short
    candidate titles match long existing titles via asymmetric overlap_ratio.
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
        if jaccard_similarity(candidate_title, existing) >= t:
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
    return priority_key(story)


def _is_done(story: dict[str, Any]) -> bool:
    """Return True if story is completed, decomposed, or skipped."""
    return bool(story.get("passes") or story.get("_decomposed") or story.get("_skipped"))


def apply_dead_weight_detection(stories: list[dict[str, Any]], threshold: int) -> None:
    """Mark stories stuck 5+ iterations as archived (US-779).

    Modifies stories in-place:
    - Increments _pending_iterations for non-passed stories
    - Sets _archived:true + _archiveReason for stories exceeding threshold
    - Returns count of newly archived stories
    """
    archived_count = 0
    for story in stories:
        # Skip done stories
        if _is_done(story):
            continue

        # Already archived — don't re-process
        if story.get("_archived"):
            continue

        # Increment iteration counter
        story["_pending_iterations"] = story.get("_pending_iterations", 0) + 1

        # Check threshold (threshold=0 disables feature)
        if threshold > 0 and story["_pending_iterations"] >= threshold:
            story["_archived"] = True
            story["_archiveReason"] = f"stuck for {story['_pending_iterations']} iterations (threshold: {threshold})"
            archived_count += 1
            print(
                f"[merge] AUTO-ARCHIVED [{story['id']}] {story['title'][:60]} "
                f"(pending {story['_pending_iterations']} iterations)"
            )

    if archived_count > 0:
        print(f"[merge] Dead weight detection: {archived_count} story/stories auto-archived this iteration")


def full_sort_key(story: dict[str, Any]) -> tuple[int, int, int]:
    """Sort key for post-merge ordering.

    Returns (done_rank, priority_rank, dep_count) so that:
    - Active stories come before done/decomposed/skipped
    - Higher priority (critical=0) comes first
    - Fewer dependencies come first within same priority
    Python's stable sort preserves relative order for equal keys.
    """
    done_rank = 1 if _is_done(story) else 0
    priority_rank = priority_key(story)
    dep_count = len(story.get("dependencies", []))
    return (done_rank, priority_rank, dep_count)


def matches_focus(story: dict[str, Any], focus: str) -> bool:
    """Case-insensitive keyword match against title + description."""
    if not focus:
        return True
    focus_lower = focus.lower()
    searchable = (story.get("title", "") + " " + story.get("description", "")).lower()
    return focus_lower in searchable


def _load_raw(path: str) -> dict[str, Any]:
    """Load a JSON or YAML file by extension, returning the parsed dict."""
    with open(path, encoding="utf-8") as f:
        if path.endswith(".yaml") or path.endswith(".yml"):
            try:
                import yaml

                return yaml.safe_load(f) or {}
            except ImportError:
                raise ImportError(f"pyyaml required to read {path} — install with: uv add pyyaml")
        return json.load(f)


def load_candidates(path: str) -> list[dict[str, Any]]:
    if not os.path.isfile(path):
        print(f"[merge] WARNING: {path} not found — treating as empty")
        return []
    data = _load_raw(path)
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
        "filesTouch": story.get("filesTouch", []),
        "dependencies": story.get("dependencies", []),
        "estimatedComplexity": story.get("estimatedComplexity", "medium"),
        "passes": False,
    }
    if "_source" in story:
        entry["_source"] = story["_source"]
    # Carry over batch_id from Phase S batch validation (US-406)
    if "_batch_id" in story:
        entry["_batch_id"] = story["_batch_id"]
    # Enhancement 7: flag test-synthesis stories for audit trail + future ralph prioritisation
    if story.get("_isTestFix"):
        entry["isTestFix"] = True
    # Carry over tags from research output; auto-assign 'bugfix' for test-fix stories
    tags = list(story.get("tags", []))
    if story.get("_isTestFix") and "bugfix" not in tags:
        tags.append("bugfix")
    if tags:
        entry["tags"] = tags
    # Initialize _pending_iterations counter (US-779)
    entry["_pending_iterations"] = 0
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
    parser.add_argument(
        "--max-pending",
        type=int,
        default=0,
        help="Max total pending (incomplete) stories allowed. 0 = unlimited",
    )
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

    # ── US-779: Dead weight detection — auto-archive stuck stories ─────────────
    dead_weight_threshold = int(os.environ.get("SPIRAL_DEAD_WEIGHT_THRESHOLD", "5"))
    apply_dead_weight_detection(existing_stories, dead_weight_threshold)

    existing_titles = [s.get("title", "") for s in existing_stories]
    existing_epics = [s.get("epicId", "") for s in existing_stories]

    # ── US-779: Dead weight detection — track iterations and auto-archive stuck stories ───
    archived_this_iteration = 0
    dead_weight_changes_made = False
    for story in existing_stories:
        if not story.get("passes"):  # Only track pending stories
            if story.get("_archived"):
                # Already archived, keep it as-is
                continue
            # Increment iteration counter (first appearance = 0 → 1)
            story["_pending_iterations"] = story.get("_pending_iterations", 0) + 1
            pending_iters = story["_pending_iterations"]
            dead_weight_changes_made = True
            # Check if exceeded threshold
            if pending_iters >= dead_weight_threshold:
                story["_archived"] = True
                story["_archiveReason"] = f"Stuck {pending_iters} iterations (threshold: {dead_weight_threshold})"
                archived_this_iteration += 1
                print(
                    f"[merge] Auto-archive [{story['id']}] {story['title'][:60]} (pending {pending_iters} iterations)"
                )

    current_pending = sum(1 for s in existing_stories if not s.get("passes") and not s.get("_archived"))
    total_archived = sum(1 for s in existing_stories if s.get("_archived"))
    print(
        f"[merge] prd.json: {len(existing_stories)} existing stories "
        f"({current_pending} pending, {total_archived} archived)"
    )
    if archived_this_iteration:
        print(f"[merge] Auto-archived {archived_this_iteration} dead-weight stories this iteration")

    # ── US-545: Detect file conflicts among pending stories ───────────────────
    _file_conflicts, _conflict_errors = detect_federated_conflicts(existing_stories)
    if _file_conflicts:
        _pairwise: list[dict[str, Any]] = []
        for _fc in _file_conflicts:
            if not isinstance(_fc, dict):
                continue
            subs = _fc.get("sub_projects", [])
            fpath = _fc.get("file_path", "")
            if not isinstance(subs, list):
                continue
            for i in range(len(subs)):
                for j in range(i + 1, len(subs)):
                    _pairwise.append({"storyA": str(subs[i]), "storyB": str(subs[j]), "conflict_files": fpath})
        if _pairwise:
            _results_tsv = os.path.join(os.path.dirname(os.path.abspath(args.prd)), "results.tsv")
            try:
                _log_conflicts_to_results(_results_tsv, _pairwise)
            except (TypeError, KeyError) as _e:
                print(f"[merge] WARNING: conflict logging failed: {_e}")
        print(f"[merge] File conflicts detected: {len(_file_conflicts)} file(s) with cross-project collisions")
        for _fc in _file_conflicts:
            if isinstance(_fc, dict):
                print(f"[merge]   {_fc.get('file_path', '?')}: sub_projects={_fc.get('sub_projects', [])}")

    # Compute effective cap: min(max_new, remaining room under max_pending)
    # Note: current_pending already excludes archived stories (see above)
    effective_cap = args.max_new
    if args.max_pending > 0:
        room = max(0, args.max_pending - current_pending)
        effective_cap = min(effective_cap, room)
        print(f"[merge] Max pending limit: {args.max_pending} (current: {current_pending}, room: {room})")
        if room == 0:
            print(
                f"[merge] At or over max pending limit ({current_pending}/{args.max_pending})"
                " — no new stories will be added"
            )
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
        print(f'[merge] Focus: "{args.focus}" — research hard-filtered, test stories soft-prioritized')

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

    if not new_stories and not (args.overflow_out and leftover_research) and not dead_weight_changes_made:
        # No overflow to write and no new stories and no dead weight changes
        if args.overflow_out:
            atomic_write_json(args.overflow_out, {"stories": leftover_research})
            print("[merge] Overflow: cleared (all candidates consumed or cap not reached)")
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

    # ── US-698: Topological reorder pending stories by dependency graph ────────
    # Reorder SPIRAL_PENDING stories using Kahn's algorithm so dependencies are
    # merged before the stories that depend on them.
    _lib_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _lib_dir not in sys.path:
        sys.path.insert(0, _lib_dir)
    try:
        from story_reorder import reorder_stories as _reorder_stories

        _pending = [s for s in prd["userStories"] if not _is_done(s)]
        _done = [s for s in prd["userStories"] if _is_done(s)]
        if _pending:
            _pending = _reorder_stories(_pending)
        prd["userStories"] = _pending + _done
        print(f"[merge] Topological reorder: {len(_pending)} pending stories ordered by dependency graph")
    except Exception as _exc:
        # Fallback: priority sort if topological reorder unavailable
        print(f"[merge] WARNING: topological reorder skipped ({type(_exc).__name__}: {_exc})")
        prd["userStories"].sort(key=full_sort_key)

    # ── Transaction-safe write: journal both files for crash recovery ─────────
    scratch_dir = os.environ.get("SPIRAL_SCRATCH_DIR", ".spiral")
    journal = TxnJournal(os.path.join(scratch_dir, "_txn_journal.jsonl"))
    with journal.transaction("phase_m_merge") as txn:
        if args.overflow_out:
            txn.write_json(args.overflow_out, {"stories": leftover_research})
            if leftover_research:
                print(f"[merge] Overflow: {len(leftover_research)} unused research candidates → {args.overflow_out}")
            else:
                print("[merge] Overflow: cleared (all candidates consumed or cap not reached)")
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
    pending_after = sum(1 for s in prd["userStories"] if not s.get("passes") and not s.get("_archived"))
    archived_after = sum(1 for s in prd["userStories"] if s.get("_archived"))
    print(
        f"[merge] Done: added {len(added_entries)} stories. "
        f"prd.json now has {total_after} total ({pending_after} pending, {archived_after} archived)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
