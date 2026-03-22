"""
lib/scope_reducer.py — Automatic file-level scope reduction for oversized stories.

When Phase I detects that a story's implementation scope is too large (token prediction
exceeds budget), this module identifies non-critical files (tests, docs, examples) and
marks them as 'deferred' so Ralph can retry with reduced scope before escalating to a
more expensive model.

Usage:
    from lib.scope_reducer import reduce_scope, estimate_story_size

    story = {...}  # prd.json story dict
    if estimate_story_size(story) > 3000:
        reduced_story, deferred = reduce_scope(story, budget_chars=3000)
        # retry ralph with reduced_story; log deferred to results.tsv scope_tag
"""

from __future__ import annotations

import json
import re

# Default character budget for a story before triggering scope reduction.
# ~3000 chars ≈ 750 tokens at ~4 chars/token, a safe haiku budget.
DEFAULT_BUDGET_CHARS = 3000

# Patterns that identify non-critical files that can be deferred.
_NONCRITICAL_PATTERNS = [
    re.compile(r"(^|/)test[_s]?/", re.IGNORECASE),  # tests/ or test/
    re.compile(r"(^|/)tests?_", re.IGNORECASE),  # test_foo.py
    re.compile(r"_tests?\.(py|ts|js)$", re.IGNORECASE),  # foo_test.py
    re.compile(r"\.spec\.(ts|js)$", re.IGNORECASE),  # foo.spec.ts
    re.compile(r"(^|/)examples?/", re.IGNORECASE),  # examples/
    re.compile(r"(^|/)docs?/", re.IGNORECASE),  # docs/ or doc/
    re.compile(r"\.(md|rst|txt|adoc)$", re.IGNORECASE),  # markdown/docs
    re.compile(r"(^|/)fixtures?/", re.IGNORECASE),  # fixtures/
    re.compile(r"(^|/)__pycache__/", re.IGNORECASE),  # __pycache__
    re.compile(r"CHANGELOG", re.IGNORECASE),  # changelogs
    re.compile(r"README", re.IGNORECASE),  # readmes
]


def estimate_story_size(story: dict[str, object]) -> int:
    """Estimate story scope in characters (proxy for token count).

    Includes description, filesTouch list, and technicalNotes.
    ~4 chars ≈ 1 token; 3000 chars ≈ 750 tokens.
    """
    parts: list[str] = []

    desc = story.get("description", "")
    if isinstance(desc, str):
        parts.append(desc)

    files_touch = story.get("filesTouch", [])
    if isinstance(files_touch, list):
        parts.append(" ".join(str(f) for f in files_touch))

    tech_notes = story.get("technicalNotes", [])
    if isinstance(tech_notes, list):
        parts.extend(str(n) for n in tech_notes)
    elif isinstance(tech_notes, str):
        parts.append(tech_notes)

    ac = story.get("acceptanceCriteria", [])
    if isinstance(ac, list):
        parts.extend(str(a) for a in ac)

    return sum(len(p) for p in parts)


def identify_noncritical_files(files: list[str]) -> list[str]:
    """Return the subset of *files* that match non-critical patterns.

    Non-critical files are tests, docs, examples, fixtures, and changelogs.
    These can be deferred to a later retry without blocking core implementation.
    """
    noncritical: list[str] = []
    for f in files:
        path = str(f)
        if any(pat.search(path) for pat in _NONCRITICAL_PATTERNS):
            noncritical.append(f)
    return noncritical


def reduce_scope(
    story: dict[str, object],
    budget_chars: int = DEFAULT_BUDGET_CHARS,
) -> tuple[dict[str, object], list[str]]:
    """Return (reduced_story, deferred_files) by removing non-critical files.

    Algorithm:
    1. If story is already within budget, return unchanged with no deferred files.
    2. Identify non-critical files in filesTouch.
    3. Remove non-critical files one by one (largest-name-first for determinism)
       until estimated size falls within budget.
    4. Mark deferred files in a new '_deferred_files' list on the story.
    5. Add '{deferred_files, token_budget}' hint to technicalNotes for Ralph.

    Args:
        story: prd.json story dict (not mutated — a copy is returned).
        budget_chars: target character count for the reduced story.

    Returns:
        (reduced_story, deferred_files) where deferred_files is the list of
        files removed from filesTouch.
    """
    import copy

    current_size = estimate_story_size(story)
    if current_size <= budget_chars:
        return story, []

    reduced = copy.deepcopy(story)
    raw_files = reduced.get("filesTouch", [])
    files_touch: list[str] = [str(f) for f in raw_files] if isinstance(raw_files, list) else []
    noncritical = identify_noncritical_files(files_touch)

    # Sort by descending path length so we remove the longest paths first,
    # maximising size savings per removal step.
    noncritical_sorted = sorted(noncritical, key=len, reverse=True)

    # Reserve ~150 chars for the scope_reduced hint added to technicalNotes
    # so the final estimated size (including the hint) stays within budget.
    _HINT_OVERHEAD = 150

    deferred: list[str] = []
    for f in noncritical_sorted:
        if estimate_story_size(reduced) <= budget_chars - _HINT_OVERHEAD:
            break
        if f in files_touch:
            files_touch.remove(f)
            deferred.append(f)
            reduced["filesTouch"] = files_touch

    if deferred:
        reduced["_deferred_files"] = deferred
        # Append a hint to technicalNotes so Ralph is aware of the reduced scope.
        raw_notes = reduced.get("technicalNotes", [])
        tech_notes: list[str] = [str(n) for n in raw_notes] if isinstance(raw_notes, list) else []
        # Keep the hint short — the full deferred list is in _deferred_files.
        hint = (
            f"[scope_reduced] {len(deferred)} non-critical file(s) deferred "
            f"(token_budget={budget_chars}). See _deferred_files for list."
        )
        tech_notes.append(hint)
        reduced["technicalNotes"] = tech_notes

    return reduced, deferred


def main() -> None:
    """CLI: reduce scope of a story from a JSON file or stdin.

    Usage:
        uv run python lib/scope_reducer.py estimate <story_json_file>
        uv run python lib/scope_reducer.py reduce <story_json_file> [--budget 3000]
        uv run python lib/scope_reducer.py noncritical <file1> <file2> ...

    Exit codes:
        0  success
        1  error
    """
    import sys

    args = sys.argv[1:]
    if not args:
        print("Usage: scope_reducer.py <estimate|reduce|noncritical> ...", file=sys.stderr)
        sys.exit(1)

    cmd = args[0]

    if cmd == "estimate":
        if len(args) < 2:
            print("Usage: scope_reducer.py estimate <story_json_file>", file=sys.stderr)
            sys.exit(1)
        with open(args[1], encoding="utf-8") as fh:
            story = json.load(fh)
        print(estimate_story_size(story))

    elif cmd == "reduce":
        budget = DEFAULT_BUDGET_CHARS
        # parse optional --budget flag
        story_file = args[1] if len(args) > 1 else None
        for i, arg in enumerate(args):
            if arg == "--budget" and i + 1 < len(args):
                budget = int(args[i + 1])
        if not story_file:
            print("Usage: scope_reducer.py reduce <story_json_file> [--budget N]", file=sys.stderr)
            sys.exit(1)
        with open(story_file, encoding="utf-8") as fh:
            story = json.load(fh)
        reduced, deferred = reduce_scope(story, budget_chars=budget)
        print(json.dumps({"reduced_story": reduced, "deferred_files": deferred}, indent=2))

    elif cmd == "noncritical":
        files = args[1:]
        result = identify_noncritical_files(files)
        print(json.dumps(result))

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
