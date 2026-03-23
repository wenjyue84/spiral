from __future__ import annotations
import argparse, copy, json, re, sys
from pathlib import Path
from typing import Any

_NUM_SUB_STORIES = 4
_STORY_ID_RE = re.compile(r"^([A-Z]+-?)(\d+)$")

def _find_max_id(stories: list[dict[str, Any]]) -> int:
    max_num = 0
    for s in stories:
        m = _STORY_ID_RE.match(s.get("id", ""))
        if m:
            max_num = max(max_num, int(m.group(2)))
    return max_num

def _get_prefix(story_id: str) -> str:
    m = _STORY_ID_RE.match(story_id)
    return m.group(1) if m else "US-"

def _distribute_round_robin(items: list[Any], n: int) -> list[list[Any]]:
    buckets: list[list[Any]] = [[] for _ in range(n)]
    for i, item in enumerate(items):
        buckets[i % n].append(item)
    return buckets

def decompose_exhausted_story(
    story_id: str, prd: dict[str, Any], max_stories_ceiling: int, *, iteration: int = 0
) -> dict[str, Any]:
    prd = copy.deepcopy(prd)
    stories: list[dict[str, Any]] = prd.get("userStories", [])
    parent = next((s for s in stories if s.get("id") == story_id), None)
    if parent is None:
        raise ValueError(f"Story {story_id!r} not found in prd")
    if parent.get("_decomposed"):
        raise ValueError(f"Story {story_id!r} is already decomposed")
    if parent.get("_decomposedFrom") or parent.get("_parent_id"):
        raise ValueError(f"Story {story_id!r} is a sub-story -- cannot recursively decompose")
    current_count = len(stories)
    if max_stories_ceiling > 0 and current_count + _NUM_SUB_STORIES > max_stories_ceiling:
        raise ValueError(
            f"Cannot decompose {story_id!r}: adding {_NUM_SUB_STORIES} sub-stories "
            f"would exceed ceiling of {max_stories_ceiling} "
            f"(currently {current_count} stories)"
        )
    files_touch: list[str] = parent.get("filesTouch", [])
    acs: list[str] = parent.get("acceptanceCriteria", [])
    file_buckets = _distribute_round_robin(files_touch, _NUM_SUB_STORIES) if files_touch else [[] for _ in range(_NUM_SUB_STORIES)]
    ac_buckets = _distribute_round_robin(acs, _NUM_SUB_STORIES) if acs else [[] for _ in range(_NUM_SUB_STORIES)]
    prefix = _get_prefix(story_id)
    next_num = _find_max_id(stories) + 1
    child_ids: list[str] = []
    sub_stories: list[dict[str, Any]] = []
    parent_title: str = parent.get("title", story_id)
    parent_priority: str = parent.get("priority", "medium")
    parent_description: str = parent.get("description", "")
    parent_notes: list[str] = parent.get("technicalNotes", [])
    for i in range(_NUM_SUB_STORIES):
        child_id = f"{prefix}{next_num + i}"
        child_ids.append(child_id)
        sub_acs: list[str] = ac_buckets[i]
        if not sub_acs:
            sub_acs = [f"Implement sub-task {i + 1}/{_NUM_SUB_STORIES} of parent story {story_id}"]
        entry: dict[str, Any] = {
            "id": child_id,
            "title": f"[{i + 1}/{_NUM_SUB_STORIES}] {parent_title}",
            "priority": parent_priority,
            "description": parent_description,
            "acceptanceCriteria": sub_acs,
            "technicalNotes": list(parent_notes),
            "dependencies": [],
            "estimatedComplexity": "small",
            "passes": False,
            "_parent_id": story_id,
            "_decomposedFrom": story_id,
            "_decomposed_from_iteration": iteration,
        }
        sub_files: list[str] = file_buckets[i]
        if sub_files:
            entry["filesTouch"] = sub_files
        sub_stories.append(entry)
    parent["_decomposed"] = True
    parent["_decomposed_count"] = _NUM_SUB_STORIES
    parent["_decomposedInto"] = child_ids
    prd["userStories"] = stories + sub_stories
    return prd

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic Phase I story decomposer")
    parser.add_argument("--story-id", required=True)
    parser.add_argument("--prd", default="prd.json")
    parser.add_argument("--iteration", type=int, default=0)
    parser.add_argument("--max-stories", type=int, default=0)
    args = parser.parse_args(argv)
    prd_path = Path(args.prd)
    if not prd_path.exists():
        print(f"[auto_decompose] ERROR: {prd_path} not found", file=sys.stderr)
        return 1
    with prd_path.open(encoding="utf-8") as f:
        prd = json.load(f)
    try:
        new_prd = decompose_exhausted_story(args.story_id, prd, args.max_stories, iteration=args.iteration)
    except ValueError as exc:
        print(f"[auto_decompose] ERROR: {exc}", file=sys.stderr)
        return 1
    tmp = prd_path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(new_prd, f, indent=2, ensure_ascii=False)
    tmp.replace(prd_path)
    parent_out = next(s for s in new_prd["userStories"] if s.get("id") == args.story_id)
    cids: list[str] = parent_out.get("_decomposedInto", [])
    print(f"[auto_decompose] {args.story_id} -> {len(cids)} sub-stories: {', '.join(cids)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
