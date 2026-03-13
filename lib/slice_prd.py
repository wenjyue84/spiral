#!/usr/bin/env python3
"""
SPIRAL -- PRD Batch Slicer (stdlib-only)

Produces a PRD subset containing all passed/decomposed stories plus the
N highest-priority pending stories.  Stories outside the batch window are
NOT skipped -- they simply don't appear in this iteration's slice and will
be picked up once higher-priority stories complete.

Usage (CLI):
  python lib/slice_prd.py prd.json 5            # write sliced JSON to stdout
  python lib/slice_prd.py prd.json 5 -o out.json # write to file

As module:
  from slice_prd import slice_prd
  sliced = slice_prd(prd_dict, batch_size=5)
"""
import json
import sys

# Force UTF-8 stdout on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Priority sort order (lower = higher priority)
_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def slice_prd(prd: dict, batch_size: int) -> dict:
    """Return a copy of *prd* with at most *batch_size* pending stories.

    - All stories with ``passes == True`` are always included.
    - Decomposed parents (``_decomposed == True``) are always included.
    - Pending stories are sorted by priority then original order, and only
      the first *batch_size* are kept.
    - If *batch_size* <= 0, the original dict is returned unchanged.
    """
    if batch_size <= 0:
        return prd

    stories = prd.get("userStories", [])

    kept: list[dict] = []
    pending: list[tuple[int, dict]] = []  # (original_index, story)

    for idx, story in enumerate(stories):
        if story.get("passes") is True or story.get("_decomposed") is True:
            kept.append(story)
        else:
            pending.append((idx, story))

    # Sort pending by priority (critical > high > medium > low), stable on
    # original order within the same priority.
    pending.sort(key=lambda t: _PRIORITY_ORDER.get(t[1].get("priority", "low"), 99))

    batch = [s for _, s in pending[:batch_size]]

    # Rebuild in original order: kept stories stay at their indices,
    # batch stories stay at their indices; everything else is dropped.
    kept_set = {id(s) for s in kept}
    batch_set = {id(s) for s in batch}
    result_stories = [s for s in stories if id(s) in kept_set or id(s) in batch_set]

    out = dict(prd)
    out["userStories"] = result_stories
    return out


def merge_batch_results(full_prd: dict, batched_prd: dict) -> dict:
    """Merge pass/decompose updates from *batched_prd* back into *full_prd*.

    For every story in *batched_prd* whose ``passes`` changed to True (or
    whose ``_decomposed``/``_decomposedInto`` fields were added), copy those
    fields back to the matching story in *full_prd*.

    Returns a new dict (does not mutate inputs).
    """
    import copy

    result = copy.deepcopy(full_prd)
    batched_map: dict[str, dict] = {
        s["id"]: s for s in batched_prd.get("userStories", []) if "id" in s
    }

    for story in result["userStories"]:
        sid = story.get("id", "")
        if sid not in batched_map:
            continue
        batched = batched_map[sid]
        # Merge pass status
        if batched.get("passes") is True:
            story["passes"] = True
        # Merge decomposition metadata
        for key in ("_decomposed", "_decomposedInto", "_decomposedFrom", "_skipped"):
            if key in batched:
                story[key] = batched[key]

    # Append any NEW stories created by decomposition (sub-stories)
    full_ids = {s["id"] for s in result["userStories"] if "id" in s}
    for story in batched_prd.get("userStories", []):
        if story.get("id", "") not in full_ids:
            result["userStories"].append(story)

    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Slice or merge prd.json batches")
    sub = parser.add_subparsers(dest="command")

    # slice sub-command
    sp = sub.add_parser("slice", help="Create a batched PRD slice")
    sp.add_argument("prd", help="Path to prd.json")
    sp.add_argument("batch_size", type=int, help="Max pending stories (0 = disabled)")
    sp.add_argument("-o", "--output", help="Output file (default: stdout)")

    # merge sub-command
    mp = sub.add_parser("merge", help="Merge batch results back into full PRD")
    mp.add_argument("full_prd", help="Path to full (backup) prd.json")
    mp.add_argument("batched_prd", help="Path to batched prd.json (with ralph updates)")
    mp.add_argument("-o", "--output", help="Output file (default: stdout)")

    args = parser.parse_args()

    if args.command == "slice":
        try:
            with open(args.prd, encoding="utf-8", errors="replace") as f:
                prd = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"[slice] ERROR: {e}", file=sys.stderr)
            return 1

        sliced = slice_prd(prd, args.batch_size)
        out_json = json.dumps(sliced, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(out_json)
            total = len(prd.get("userStories", []))
            kept = len(sliced.get("userStories", []))
            print(f"[slice] {kept}/{total} stories written to {args.output}", file=sys.stderr)
        else:
            sys.stdout.write(out_json)
        return 0

    elif args.command == "merge":
        try:
            with open(args.full_prd, encoding="utf-8") as f:
                full = json.load(f)
            with open(args.batched_prd, encoding="utf-8") as f:
                batched = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"[merge] ERROR: {e}", file=sys.stderr)
            return 1

        merged = merge_batch_results(full, batched)
        out_json = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(out_json)
            print(f"[merge] Merged results written to {args.output}", file=sys.stderr)
        else:
            sys.stdout.write(out_json)
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
