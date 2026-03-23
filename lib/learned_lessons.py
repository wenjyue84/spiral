#!/usr/bin/env python3
"""
learned_lessons.py — Self-evolving lesson store for SPIRAL.

Extracts structured lessons from story failures (Phase L) and injects
relevant lessons into new stories (Phase E) so Ralph avoids repeating
the same mistakes.

Store format: append-only JSONL at .spiral/learned_lessons.jsonl

Usage:
    # Phase L — extract lessons from this iteration's failures
    python lib/learned_lessons.py extract \
        --results .spiral/results.tsv --prd prd.json \
        --lessons .spiral/learned_lessons.jsonl --iteration 3

    # Phase E — inject relevant lessons into validated stories
    python lib/learned_lessons.py inject \
        --lessons .spiral/learned_lessons.jsonl \
        --validated-in .spiral/_validated_stories.json \
        --enriched-out .spiral/_lessons_enriched.json --top-k 3
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.failure_categorizer import categorize_message


# ── Lesson data model ────────────────────────────────────────────────────────

def _make_lesson(
    error_category: str,
    pattern: str,
    fix: str,
    story_id: str,
    story_title: str,
) -> dict[str, Any]:
    return {
        "error_category": error_category,
        "pattern": pattern,
        "fix": fix,
        "story_id": story_id,
        "story_title": story_title,
        "seen_count": 1,
        "confidence": 0.5,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


# ── Token overlap similarity ────────────────────────────────────────────────

_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase alpha-numeric tokens."""
    return {t for t in _SPLIT_RE.split(text.lower()) if len(t) > 2}


def _overlap(a: str, b: str) -> float:
    """Jaccard similarity between two strings (token-level)."""
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ── JSONL store operations ───────────────────────────────────────────────────

def load_lessons(path: Path) -> list[dict[str, Any]]:
    """Load all lessons from a JSONL file."""
    if not path.exists():
        return []
    lessons: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            lessons.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return lessons


def _save_lessons(path: Path, lessons: list[dict[str, Any]]) -> None:
    """Overwrite JSONL file with full lesson list (for dedup updates)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for lesson in lessons:
            f.write(json.dumps(lesson, ensure_ascii=False) + "\n")


def append_lesson(path: Path, lesson: dict[str, Any]) -> dict[str, Any]:
    """Append a lesson, deduplicating by pattern similarity.

    If an existing lesson has >80% token overlap on the ``pattern`` field
    AND the same ``error_category``, bump its ``seen_count`` and
    ``confidence`` instead of appending a new entry.

    Returns the lesson dict (new or updated).
    """
    lessons = load_lessons(path)
    for existing in lessons:
        if (
            existing.get("error_category") == lesson.get("error_category")
            and _overlap(existing.get("pattern", ""), lesson.get("pattern", "")) > 0.8
        ):
            existing["seen_count"] = existing.get("seen_count", 1) + 1
            existing["confidence"] = min(
                1.0, existing.get("confidence", 0.5) + 0.1
            )
            existing["ts"] = lesson.get("ts", existing["ts"])
            _save_lessons(path, lessons)
            return existing

    lessons.append(lesson)
    _save_lessons(path, lessons)
    return lesson


# ── Query: match lessons to a story ──────────────────────────────────────────

def query_lessons(
    path: Path,
    story: dict[str, Any],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Find lessons relevant to a story by keyword overlap.

    Builds a search string from the story's title, description, tags,
    and technicalNotes, then scores each lesson by token overlap with
    its pattern + fix + story_title fields, weighted by seen_count *
    confidence.

    Returns up to *top_k* lessons sorted by descending score.
    """
    lessons = load_lessons(path)
    if not lessons:
        return []

    # Build story search text
    parts: list[str] = [
        story.get("title", ""),
        story.get("description", ""),
    ]
    tags = story.get("tags", [])
    if isinstance(tags, list):
        parts.extend(str(t) for t in tags)
    notes = story.get("technicalNotes", [])
    if isinstance(notes, list):
        parts.extend(str(n) for n in notes)
    story_text = " ".join(parts)

    scored: list[tuple[float, dict[str, Any]]] = []
    for lesson in lessons:
        lesson_text = " ".join([
            lesson.get("pattern", ""),
            lesson.get("fix", ""),
            lesson.get("story_title", ""),
            lesson.get("error_category", ""),
        ])
        sim = _overlap(story_text, lesson_text)
        if sim > 0.0:
            weight = lesson.get("seen_count", 1) * lesson.get("confidence", 0.5)
            scored.append((sim * weight, lesson))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [lesson for _, lesson in scored[:top_k]]


# ── Promote: auto-generate skill files ───────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] if slug else "unknown"


def promote_to_skill(
    path: Path,
    skills_dir: Path,
    threshold: int = 3,
) -> list[Path]:
    """Generate skill markdown files for lessons seen >= threshold times.

    Returns list of skill file paths created.
    """
    lessons = load_lessons(path)
    skills_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    for lesson in lessons:
        if lesson.get("seen_count", 0) < threshold:
            continue
        cat = lesson.get("error_category", "other")
        slug = _slugify(lesson.get("pattern", "unknown"))
        skill_path = skills_dir / f"{cat}-{slug}.md"
        if skill_path.exists():
            continue

        content = (
            f"# Pattern: {lesson.get('pattern', 'Unknown')}\n"
            f"Seen {lesson.get('seen_count', 0)} times. "
            f"Confidence: {lesson.get('confidence', 0):.1f}.\n\n"
            f"## Category\n{cat}\n\n"
            f"## When this applies\n"
            f"Stories similar to: {lesson.get('story_title', 'N/A')}\n\n"
            f"## What to do\n{lesson.get('fix', 'No fix recorded.')}\n\n"
            f"## Anti-pattern\n"
            f"Do NOT repeat the pattern that caused the failure: "
            f"{lesson.get('pattern', 'N/A')}\n"
        )
        skill_path.write_text(content, encoding="utf-8")
        created.append(skill_path)

    return created


# ── CLI: extract ─────────────────────────────────────────────────────────────

def _cmd_extract(args: argparse.Namespace) -> None:
    """Extract lessons from results.tsv failures for a given iteration."""
    import csv

    results_path = Path(args.results)
    prd_path = Path(args.prd)
    lessons_path = Path(args.lessons)
    iteration = args.iteration

    # Load results.tsv
    if not results_path.exists():
        print("  [L] No results.tsv found — skipping lesson extraction")
        return

    rows: list[dict[str, str]] = []
    with open(results_path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(dict(row))

    # Load PRD for story titles
    story_titles: dict[str, str] = {}
    if prd_path.exists():
        try:
            prd = json.loads(prd_path.read_text(encoding="utf-8"))
            for s in prd.get("userStories", []):
                sid = s.get("id", "")
                if sid:
                    story_titles[sid] = s.get("title", sid)
        except (json.JSONDecodeError, OSError):
            pass

    # Filter to failed rows for this iteration
    count = 0
    for row in rows:
        if iteration is not None:
            try:
                row_iter = int(row.get("spiral_iter", "").strip())
            except (ValueError, TypeError):
                continue
            if row_iter != iteration:
                continue

        status = (row.get("status") or "").lower()
        if status not in ("fail", "failed", "error", "reject"):
            continue

        story_id = (row.get("story_id") or "").strip()
        if not story_id:
            continue

        # Build lesson from failure
        root_cause = row.get("failure_root_cause", "")
        error_cat = row.get("error_category", "")
        if not error_cat:
            error_cat = categorize_message(root_cause or row.get("story_title", ""))

        # Use root cause as pattern; derive fix as "avoid this"
        pattern = root_cause.strip() if root_cause else f"{error_cat} in {story_id}"
        title = story_titles.get(story_id, row.get("story_title", story_id))

        lesson = _make_lesson(
            error_category=error_cat,
            pattern=pattern[:200],  # cap length
            fix=f"Avoid: {pattern[:150]}" if pattern else "Check error category",
            story_id=story_id,
            story_title=title,
        )
        append_lesson(lessons_path, lesson)
        count += 1

    print(f"  [L] Extracted {count} lessons → {lessons_path}")

    # Auto-promote high-frequency lessons to skill files
    skills_dir = Path(args.skills_dir) if args.skills_dir else None
    if skills_dir:
        created = promote_to_skill(lessons_path, skills_dir, threshold=3)
        if created:
            print(f"  [L] Promoted {len(created)} lessons to skill files")


# ── CLI: inject ──────────────────────────────────────────────────────────────

def _cmd_inject(args: argparse.Namespace) -> None:
    """Inject relevant lessons into validated stories."""
    lessons_path = Path(args.lessons)
    validated_path = Path(args.validated_in)
    output_path = Path(args.enriched_out)
    top_k = args.top_k

    if not lessons_path.exists() or not validated_path.exists():
        # No lessons or no stories — pass through
        if validated_path.exists():
            output_path.write_text(
                validated_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        return

    validated = json.loads(validated_path.read_text(encoding="utf-8"))
    stories = validated.get("stories", [])
    injected_count = 0

    for story in stories:
        matches = query_lessons(lessons_path, story, top_k=top_k)
        if matches:
            story["_learned_lessons"] = [
                {
                    "pattern": m.get("pattern", ""),
                    "fix": m.get("fix", ""),
                    "confidence": m.get("confidence", 0.5),
                    "error_category": m.get("error_category", "other"),
                }
                for m in matches
            ]
            injected_count += 1

    validated["stories"] = stories
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(validated, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"  [E] Injected lessons into {injected_count}/{len(stories)} stories"
    )


# ── CLI entry point ──────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Self-evolving lesson store for SPIRAL"
    )
    sub = parser.add_subparsers(dest="command")

    # extract
    p_ext = sub.add_parser("extract", help="Extract lessons from failures")
    p_ext.add_argument("--results", required=True, help="Path to results.tsv")
    p_ext.add_argument("--prd", required=True, help="Path to prd.json")
    p_ext.add_argument("--lessons", required=True, help="Path to lessons JSONL")
    p_ext.add_argument(
        "--iteration", type=int, default=None, help="Filter to iteration N"
    )
    p_ext.add_argument(
        "--skills-dir", default=None, help="Dir for auto-promoted skill files"
    )

    # inject
    p_inj = sub.add_parser("inject", help="Inject lessons into stories")
    p_inj.add_argument("--lessons", required=True, help="Path to lessons JSONL")
    p_inj.add_argument(
        "--validated-in", required=True, help="Input validated stories JSON"
    )
    p_inj.add_argument(
        "--enriched-out", required=True, help="Output enriched stories JSON"
    )
    p_inj.add_argument(
        "--top-k", type=int, default=3, help="Max lessons per story"
    )

    args = parser.parse_args(argv)
    if args.command == "extract":
        _cmd_extract(args)
    elif args.command == "inject":
        _cmd_inject(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
