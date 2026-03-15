#!/usr/bin/env python3
"""
lib/validate_stories.py — Phase S story validation helper

Reads candidate stories from _research_output.json and _test_stories_output.json,
validates each against prd.json goals[], optionally checks a constitution file,
and writes:
  _validated_stories.json  — accepted stories (input to Phase M --research)
  _story_rejected.json     — rejected stories with rejection reasons (log only)

Exit code: 0 always (validation failures are non-fatal; use --min-overlap 0 to accept all).
"""
import argparse
import json
import os
import re
import sys

# Force UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Common English stopwords to exclude from keyword comparison
_STOPWORDS = {
    "the", "and", "for", "are", "was", "this", "with", "from", "that",
    "not", "all", "can", "but", "has", "new", "add", "run", "use",
    "set", "get", "put", "may", "via", "its", "also", "any", "each",
    "when", "have", "been", "will", "into", "only", "more", "such",
    "than", "then", "they", "their", "them", "what", "where", "which",
    "who", "how", "per", "non", "now", "one", "two", "should", "would",
    "could", "must", "does", "did", "out", "too", "end", "log", "key",
}


def _normalize(text: str) -> set[str]:
    """Extract lowercase alpha-numeric tokens >= 3 chars, excluding stopwords."""
    return {
        w for w in re.findall(r"[a-z0-9]+", text.lower())
        if len(w) >= 3 and w not in _STOPWORDS
    }


def _goal_keywords(goals: list[str]) -> set[str]:
    """Extract meaningful keywords from the goals list."""
    words: set[str] = set()
    for g in goals:
        words |= _normalize(g)
    return words


def _story_keywords(story: dict) -> set[str]:
    """Extract keywords from a story's title and description."""
    text = story.get("title", "") + " " + story.get("description", "")
    return _normalize(text)


def _load_candidates(path: str) -> list[dict]:
    """Load story candidates from a JSON file with a .stories array."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("stories", [])
    except (json.JSONDecodeError, OSError):
        return []


def _atomic_write_json(data: dict, path: str) -> None:
    """Write *data* as pretty-printed JSON to *path* atomically."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _load_constitution_forbidden(path: str) -> list[str]:
    """Extract forbidden phrases from a constitution file.

    Lines matching ``NOT:``, ``NEVER:``, ``AVOID:``, or ``FORBIDDEN:`` prefixes
    are treated as forbidden phrases (case-insensitive substring match).
    """
    forbidden: list[str] = []
    if not path or not os.path.exists(path):
        return forbidden
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                for prefix in ("NOT:", "NEVER:", "AVOID:", "FORBIDDEN:"):
                    if line.upper().startswith(prefix):
                        phrase = line[len(prefix):].strip().lower()
                        if phrase:
                            forbidden.append(phrase)
                        break
    except OSError:
        pass
    return forbidden


def validate_stories(
    research_path: str,
    test_stories_path: str,
    prd_path: str,
    validated_out: str,
    rejected_out: str,
    constitution_path: str = "",
    min_overlap: int = 1,
    ai_suggest_path: str = "",
    test_story_candidates_path: str = "",
) -> tuple[list[dict], list[dict]]:
    """Core validation logic. Returns (accepted, rejected) lists."""

    # Load prd.json goals
    try:
        with open(prd_path, encoding="utf-8") as fh:
            prd = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[S] ERROR: Cannot read prd.json: {exc}", file=sys.stderr)
        sys.exit(1)

    goals: list[str] = prd.get("goals", [])
    gkw = _goal_keywords(goals) if goals else set()

    # Load optional constitution forbidden phrases
    forbidden_phrases = _load_constitution_forbidden(constitution_path)

    # Combine candidates from all sources (dedup by lower-cased title)
    research_stories = _load_candidates(research_path)
    test_stories = _load_candidates(test_stories_path)
    ai_suggest_stories = _load_candidates(ai_suggest_path) if ai_suggest_path else []
    test_story_candidates = _load_candidates(test_story_candidates_path) if test_story_candidates_path else []

    # Tag source if not already set
    for story in research_stories:
        if "_source" not in story:
            story["_source"] = "research"
    for story in test_stories:
        if "_source" not in story:
            story["_source"] = "test-fix"
    for story in ai_suggest_stories:
        if "_source" not in story:
            story["_source"] = "ai-example"
    for story in test_story_candidates:
        if "_source" not in story:
            story["_source"] = "test-story"

    seen_titles: set[str] = set()
    all_candidates: list[dict] = []
    # Order: research, test-fix, ai-example, test-story
    for story in research_stories + test_stories + ai_suggest_stories + test_story_candidates:
        t = story.get("title", "").strip().lower()
        if t and t not in seen_titles:
            seen_titles.add(t)
            all_candidates.append(story)

    accepted: list[dict] = []
    rejected: list[dict] = []

    for story in all_candidates:
        title = story.get("title", "").strip()
        if not title:
            continue  # skip malformed entries

        rejection_reason: str | None = None

        # 1. Constitution check
        if forbidden_phrases:
            story_text = (title + " " + story.get("description", "")).lower()
            for phrase in forbidden_phrases:
                if phrase in story_text:
                    rejection_reason = f'Violates constitution: "{phrase}"'
                    break

        # 2. Goal alignment check
        # Skipped for: test-fix, test-story (auto-approved; constitution still runs)
        # Applied for: research, ai-example (must connect to project goals)
        _src = story.get("_source", "research")
        _skip_alignment = (
            story.get("_isTestFix")
            or _src in ("test-fix", "test-story")
        )
        if rejection_reason is None and gkw and min_overlap > 0 and not _skip_alignment:
            skw = _story_keywords(story)
            overlap = len(gkw & skw)
            if overlap < min_overlap:
                rejection_reason = (
                    f"No connection to project goals "
                    f"(keyword overlap={overlap}, required>={min_overlap})"
                )

        if rejection_reason:
            rejected.append({**story, "_rejection_reason": rejection_reason})
            print(f"  [S] REJECTED: {title[:70]!r} — {rejection_reason}")
        else:
            accepted.append(story)

    # Write outputs
    _atomic_write_json({"stories": accepted}, validated_out)
    _atomic_write_json({"stories": rejected}, rejected_out)

    return accepted, rejected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase S: validate story candidates against project goals"
    )
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument(
        "--research", required=True, help="Path to _research_output.json"
    )
    parser.add_argument(
        "--test-stories", required=True, help="Path to _test_stories_output.json"
    )
    parser.add_argument(
        "--validated-out", required=True, help="Output: _validated_stories.json"
    )
    parser.add_argument(
        "--rejected-out", required=True, help="Output: _story_rejected.json"
    )
    parser.add_argument(
        "--constitution",
        default="",
        help="Optional constitution file with NOT:/NEVER:/AVOID: lines",
    )
    parser.add_argument(
        "--min-overlap",
        type=int,
        default=1,
        help="Min goal-keyword overlap to accept a story (0 = accept all)",
    )
    parser.add_argument(
        "--ai-suggest",
        default="",
        help="Path to Phase A ai-suggest output (_ai_suggest_output.json)",
    )
    parser.add_argument(
        "--test-story-candidates",
        default="",
        help="Path to Source 5 test story candidates (_test_story_candidates.json)",
    )
    args = parser.parse_args()

    accepted, rejected = validate_stories(
        research_path=args.research,
        test_stories_path=args.test_stories,
        prd_path=args.prd,
        validated_out=args.validated_out,
        rejected_out=args.rejected_out,
        constitution_path=args.constitution,
        min_overlap=args.min_overlap,
        ai_suggest_path=args.ai_suggest,
        test_story_candidates_path=args.test_story_candidates,
    )

    total = len(accepted) + len(rejected)
    rate = (len(accepted) / total * 100) if total > 0 else 100.0
    print(
        f"  [S] Validated {total} stories: "
        f"{len(accepted)} accepted ({rate:.0f}%), {len(rejected)} rejected"
    )

    # Source breakdown
    src_stats: dict[str, list[int]] = {}  # source -> [accepted_count, total_count]
    for story in accepted:
        src = story.get("_source", "research")
        src_stats.setdefault(src, [0, 0])
        src_stats[src][0] += 1
        src_stats[src][1] += 1
    for story in rejected:
        src = story.get("_source", "research")
        src_stats.setdefault(src, [0, 0])
        src_stats[src][1] += 1
    if src_stats:
        parts = " | ".join(
            f"{src}={counts[0]} accepted/{counts[1]}"
            for src, counts in src_stats.items()
        )
        print(f"  [S] Source breakdown: {parts}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
