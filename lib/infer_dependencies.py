#!/usr/bin/env python3
"""
SPIRAL — Story Dependency Auto-Inference

Scans filesTouch overlap between pending story pairs to suggest or apply
dependency edges based on Jaccard similarity of touched files.

  Jaccard >= 0.5  → strong dependency (written to prd.json if SPIRAL_AUTO_INFER_DEPS=true)
  0 < Jaccard < 0.5 → weak overlap (written to --out-hints file)

Usage:
  python infer_dependencies.py --prd prd.json [--out-hints .spiral/_dependency_hints.json]

Environment:
  SPIRAL_AUTO_INFER_DEPS  — set to "true" to write strong deps to prd.json (default: false)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from check_dag import find_cycles
from prd_schema import validate_prd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def get_files_to_touch(story: dict) -> set[str]:
    """Extract filesTouch from story, checking both top-level and technicalHints."""
    files = set(story.get("filesTouch", []))
    if not files:
        hints = story.get("technicalHints", {})
        if isinstance(hints, dict):
            files = set(hints.get("filesTouch", []))
    return files


def jaccard(a: set, b: set) -> float:
    """Jaccard similarity: |A ∩ B| / |A ∪ B|. Returns 0.0 if union is empty."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def infer_dependencies(
    stories: list[dict],
) -> tuple[list[tuple[str, str]], list[tuple[str, str, float]]]:
    """
    Compare file-touch overlap for all pairs of pending stories.

    Returns:
      strong: list of (a_id, b_id) with Jaccard >= 0.5
      weak:   list of (a_id, b_id, score) with 0 < score < 0.5

    Stories with no filesTouch history are skipped (cannot infer).
    """
    pending = [
        s
        for s in stories
        if isinstance(s, dict)
        and not s.get("passes")
        and not s.get("_skipped")
        and not s.get("_decomposed")
    ]

    strong: list[tuple[str, str]] = []
    weak: list[tuple[str, str, float]] = []

    for i, story_a in enumerate(pending):
        files_a = get_files_to_touch(story_a)
        if not files_a:
            continue
        for story_b in pending[i + 1 :]:
            files_b = get_files_to_touch(story_b)
            if not files_b:
                continue
            score = jaccard(files_a, files_b)
            if score >= 0.5:
                strong.append((story_a["id"], story_b["id"]))
            elif score > 0.0:
                weak.append((story_a["id"], story_b["id"], score))

    return strong, weak


def apply_strong_deps(
    prd: dict, strong: list[tuple[str, str]]
) -> tuple[int, int]:
    """
    Apply strong dependency edges to prd stories without creating cycles.

    For each (a_id, b_id) pair we try b depends-on a first, then a depends-on b.
    If both directions create cycles, the edge is skipped.

    Returns (applied_count, skipped_cycle_count).
    """
    story_map = {
        s["id"]: s
        for s in prd.get("userStories", [])
        if isinstance(s, dict) and "id" in s
    }
    applied = 0
    skipped_cycles = 0

    for a_id, b_id in strong:
        story_a = story_map.get(a_id)
        story_b = story_map.get(b_id)
        if story_a is None or story_b is None:
            continue

        deps_a: list = story_a.setdefault("dependencies", [])
        deps_b: list = story_b.setdefault("dependencies", [])

        # Skip if either direction already recorded
        if b_id in deps_a or a_id in deps_b:
            continue

        # Try b depends on a (a must complete before b)
        deps_b.append(a_id)
        if not find_cycles(list(story_map.values())):
            applied += 1
            continue

        # Revert; try a depends on b
        deps_b.remove(a_id)
        deps_a.append(b_id)
        if not find_cycles(list(story_map.values())):
            applied += 1
            continue

        # Both directions cycle — revert and skip
        deps_a.remove(b_id)
        skipped_cycles += 1

    return applied, skipped_cycles


def _write_json(data: dict, path: str) -> None:
    """Write JSON atomically via a .tmp file."""
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Infer story dependencies from filesTouch overlap"
    )
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument(
        "--out-hints",
        default="",
        help="Output path for weak overlap hints JSON (default: skip)",
    )
    args = parser.parse_args()

    auto_infer = os.environ.get("SPIRAL_AUTO_INFER_DEPS", "false").lower() == "true"

    if not os.path.isfile(args.prd):
        print(f"[infer_deps] ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    try:
        with open(args.prd, encoding="utf-8") as f:
            prd = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[infer_deps] ERROR: Invalid JSON in {args.prd}: {e}", file=sys.stderr)
        return 1

    errors = validate_prd(prd)
    if errors:
        print("[infer_deps] ERROR: PRD schema validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    stories = prd.get("userStories", [])
    strong, weak = infer_dependencies(stories)

    print(
        f"[infer_deps] Scanned {len(stories)} stories — "
        f"{len(strong)} strong deps, {len(weak)} weak overlaps"
    )

    # Write weak overlaps to hints file
    if args.out_hints:
        hints_data = {
            "weak_overlaps": [
                {"story_a": a, "story_b": b, "jaccard_score": round(score, 4)}
                for a, b, score in weak
            ]
        }
        _write_json(hints_data, args.out_hints)
        print(f"[infer_deps] Weak overlap hints → {args.out_hints}")

    # Apply strong deps when SPIRAL_AUTO_INFER_DEPS=true
    if auto_infer and strong:
        applied, skipped = apply_strong_deps(prd, strong)
        if applied > 0:
            _write_json(prd, args.prd)
            print(
                f"[infer_deps] Applied {applied} dependency edges to prd.json"
                + (f" (skipped {skipped} cycle-creating)" if skipped else "")
            )
        else:
            print(
                f"[infer_deps] No new edges applied"
                + (f" (skipped {skipped} cycle-creating)" if skipped else "")
            )
    elif not auto_infer and strong:
        print(
            f"[infer_deps] {len(strong)} strong dep(s) found — "
            "set SPIRAL_AUTO_INFER_DEPS=true to apply to prd.json"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
