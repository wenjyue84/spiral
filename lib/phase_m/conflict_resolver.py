"""Phase M — Three-Way Merge Conflict Resolver.

Provides three_way_merge(base_content, version_a, version_b) which attempts to
automatically reconcile divergent edits from two federated workers against a
common base.  When changes to the same region conflict the function returns a
ConflictMarker instead of a string so callers can fall back to manual review.

Typical Phase M usage::

    result = three_way_merge(base, worker_a_content, worker_b_content)
    if isinstance(result, ConflictMarker):
        # mark file for manual resolution
    else:
        # write result to disk and commit with 'Auto-resolved federated conflict'
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Sequence, Union


@dataclass
class ConflictMarker:
    """Returned by three_way_merge when an unresolvable conflict is detected.

    Attributes:
        base_content:     The original common ancestor text.
        version_a:        Worker-A's modified version.
        version_b:        Worker-B's modified version.
        conflict_regions: Line ranges where the two edits overlap, as
                          list of (start_line, end_line) tuples (0-based).
        annotated:        The file text with standard conflict markers
                          (<<<<<<< / ======= / >>>>>>>) embedded for
                          human inspection.
    """

    base_content: str
    version_a: str
    version_b: str
    conflict_regions: list[tuple[int, int]] = field(default_factory=list)
    annotated: str = ""


def _line_diff(base: list[str], version: list[str]) -> Sequence[tuple[str, int, int, int, int]]:
    """Return opcodes from SequenceMatcher comparing *base* to *version*."""
    sm = difflib.SequenceMatcher(None, base, version, autojunk=False)
    return sm.get_opcodes()


def three_way_merge(
    base_content: str,
    version_a: str,
    version_b: str,
) -> Union[str, ConflictMarker]:
    """Attempt a three-way merge of two divergent versions against a common base.

    The algorithm works line-by-line:

    1. Diff base→A and base→B independently using SequenceMatcher.
    2. Walk both diff streams simultaneously, classifying each base-line range as
       ``unchanged``, ``only-A-changed``, ``only-B-changed``, or ``both-changed``.
    3. Regions changed by only one side are applied automatically.
    4. Regions changed by *both* sides in incompatible ways yield a ConflictMarker.

    Args:
        base_content: Common ancestor text (e.g. the file before workers started).
        version_a:    Text produced by Worker-A.
        version_b:    Text produced by Worker-B.

    Returns:
        The merged string when auto-resolution succeeds, or a ConflictMarker when
        at least one region cannot be resolved automatically.
    """
    base_lines = base_content.splitlines(keepends=True)
    a_lines = version_a.splitlines(keepends=True)
    b_lines = version_b.splitlines(keepends=True)

    # Fast path: identical versions always merge cleanly.
    if version_a == version_b:
        return version_a

    # Build change maps indexed by base line number.
    # Each entry: (a_replacement, b_replacement) where None means "no change".
    a_ops = _line_diff(base_lines, a_lines)
    b_ops = _line_diff(base_lines, b_lines)

    # Expand opcodes into per-line change records.
    # changed_a[i] = list[str] of replacement lines from A (or None if equal).
    changed_a: dict[int, list[str] | None] = {}
    changed_b: dict[int, list[str] | None] = {}

    for tag, i1, i2, j1, j2 in a_ops:
        if tag != "equal":
            for base_idx in range(i1, i2):
                changed_a[base_idx] = a_lines[j1:j2] if tag in ("replace", "insert") else []
            if tag == "insert":
                # Insert before i1 — mark the insertion point.
                changed_a[i1] = a_lines[j1:j2]

    for tag, i1, i2, j1, j2 in b_ops:
        if tag != "equal":
            for base_idx in range(i1, i2):
                changed_b[base_idx] = b_lines[j1:j2] if tag in ("replace", "insert") else []
            if tag == "insert":
                changed_b[i1] = b_lines[j1:j2]

    # Walk base lines and build merged output.
    merged: list[str] = []
    conflict_regions: list[tuple[int, int]] = []
    annotated: list[str] = []
    has_conflict = False

    emitted: set[int] = set()
    i = 0
    while i < len(base_lines):
        a_change = changed_a.get(i)
        b_change = changed_b.get(i)

        if i in emitted:
            i += 1
            continue

        if a_change is None and b_change is None:
            # Both sides kept this line unchanged.
            merged.append(base_lines[i])
            annotated.append(base_lines[i])
            emitted.add(i)
            i += 1
            continue

        if a_change is not None and b_change is None:
            # Only A changed — accept A's replacement.
            merged.extend(a_change)
            annotated.extend(a_change)
            emitted.add(i)
            i += 1
            continue

        if a_change is None and b_change is not None:
            # Only B changed — accept B's replacement.
            merged.extend(b_change)
            annotated.extend(b_change)
            emitted.add(i)
            i += 1
            continue

        # Both A and B changed this region (neither is None at this point).
        assert a_change is not None
        assert b_change is not None
        if a_change == b_change:
            # Identical edits — accept without conflict.
            merged.extend(a_change)
            annotated.extend(a_change)
            emitted.add(i)
            i += 1
            continue

        # Genuine conflict — emit conflict markers in annotated output.
        has_conflict = True
        conflict_start = i
        # Find the extent of the conflict (consecutive conflicting lines).
        conflict_end = i
        while conflict_end + 1 < len(base_lines) and (
            changed_a.get(conflict_end + 1) is not None or changed_b.get(conflict_end + 1) is not None
        ):
            conflict_end += 1

        conflict_regions.append((conflict_start, conflict_end))

        a_region = a_change if a_change is not None else [base_lines[i]]
        b_region = b_change if b_change is not None else [base_lines[i]]

        annotated.append("<<<<<<< version_a\n")
        annotated.extend(a_region)
        annotated.append("=======\n")
        annotated.extend(b_region)
        annotated.append(">>>>>>> version_b\n")

        for idx in range(conflict_start, conflict_end + 1):
            emitted.add(idx)
        i = conflict_end + 1

    if has_conflict:
        return ConflictMarker(
            base_content=base_content,
            version_a=version_a,
            version_b=version_b,
            conflict_regions=conflict_regions,
            annotated="".join(annotated),
        )

    return "".join(merged)


def resolve_or_mark(
    base_content: str,
    version_a: str,
    version_b: str,
    *,
    worker_a_label: str = "worker-A",
    worker_b_label: str = "worker-B",
) -> tuple[str, bool]:
    """Convenience wrapper for Phase M orchestration.

    Returns:
        (content, auto_resolved) where:
        - *content* is the merged text (on success) or the annotated conflict
          text (on failure).
        - *auto_resolved* is True when the merge succeeded without conflicts.
    """
    result = three_way_merge(base_content, version_a, version_b)
    if isinstance(result, ConflictMarker):
        return result.annotated, False
    return result, True
