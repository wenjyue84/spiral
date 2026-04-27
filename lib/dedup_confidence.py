#!/usr/bin/env python3
"""
dedup_confidence.py — Find and merge duplicate stories using TF-IDF similarity.

Computes cosine similarity between story title+description pairs and identifies
duplicates with confidence threshold. Excludes seed stories from candidates.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def find_duplicates(prd_data: dict[str, Any], threshold: float = 0.75) -> list[tuple[str, str, float]]:
    """
    Find duplicate stories using TF-IDF + cosine similarity.

    Args:
        prd_data: Loaded prd.json dict
        threshold: Minimum confidence score (0-1) to report as duplicate

    Returns:
        List of (id1, id2, score) tuples sorted by score descending.
        Excludes seed stories. Returns empty list if <2 eligible candidates.
    """
    stories = prd_data.get("userStories", [])

    # Filter: exclude seed stories, passed stories, superseded stories
    candidates = [
        s
        for s in stories
        if s.get("source") != "seed"
        and not s.get("passes", False)
        and not s.get("superseded_by")
        and s.get("id")  # Must have ID
    ]

    if len(candidates) < 2:
        return []

    # Build text corpus: title + " " + description for each candidate
    corpus = [f"{s.get('title', '')} {s.get('description', '')}".strip() for s in candidates]
    ids = [s["id"] for s in candidates]

    # Compute TF-IDF vectors and similarity matrix
    vectorizer = TfidfVectorizer(lowercase=True, stop_words="english")
    vectors = vectorizer.fit_transform(corpus)
    similarity_matrix = cosine_similarity(vectors)

    # Extract pairs above threshold
    duplicates: list[tuple[str, str, float]] = []
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            score = float(similarity_matrix[i][j])
            if score >= threshold:
                duplicates.append((ids[i], ids[j], score))

    # Sort by score descending
    duplicates.sort(key=lambda x: -x[2])
    return duplicates


def merge_stories(id1: str, id2: str, prd_data: dict[str, Any]) -> dict[str, Any] | None:
    """
    Merge two stories into one, mark originals as superseded.

    The new merged story inherits title from id1, combines acceptanceCriteria
    from both, and marks both originals with superseded_by pointing to new ID.

    Args:
        id1: First story ID (title inherited from this)
        id2: Second story ID
        prd_data: Loaded prd.json dict

    Returns:
        Updated prd_data dict with merged story added, originals marked superseded.
        Returns None if either ID not found.
    """
    stories = {s["id"]: s for s in prd_data.get("userStories", [])}

    if id1 not in stories or id2 not in stories:
        return None

    s1 = stories[id1]
    s2 = stories[id2]

    # Generate new merged story ID (e.g., US-1307-merged-001)
    base_prefix = id1.split("-")[0] if "-" in id1 else id1
    merged_id = f"{base_prefix}-1307-merged-{len(stories):03d}"

    # Combine acceptance criteria
    combined_criteria = []
    combined_criteria.extend(s1.get("acceptanceCriteria", []))
    combined_criteria.extend(s2.get("acceptanceCriteria", []))

    # Create merged story
    merged = {
        "id": merged_id,
        "title": f"{s1.get('title', '')} + {s2.get('title', '')}",
        "description": (f"Merged from {id1} and {id2}. {s1.get('description', '')} | {s2.get('description', '')}"),
        "priority": s1.get("priority", "medium"),
        "acceptanceCriteria": combined_criteria,
        "technicalNotes": [],
        "dependencies": list(set(s1.get("dependencies", []) + s2.get("dependencies", []))),
        "estimatedComplexity": "medium",
        "passes": False,
        "_source": "dedup-merge",
        "_merged_from": [id1, id2],
    }

    # Mark originals as superseded
    s1["superseded_by"] = merged_id
    s1["_superseded_date"] = None  # Will be filled by caller with timestamp
    s2["superseded_by"] = merged_id
    s2["_superseded_date"] = None

    # Add merged story to prd_data
    prd_data["userStories"].append(merged)

    return prd_data


if __name__ == "__main__":
    # CLI entry point for dedup-suggestions and merge commands
    if len(sys.argv) < 2:
        print("Usage: dedup_confidence.py <command> [args]", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == "find_duplicates":
        if len(sys.argv) < 3:
            print("Usage: dedup_confidence.py find_duplicates <prd_file>", file=sys.stderr)
            sys.exit(1)
        prd_file = sys.argv[2]
        with open(prd_file, encoding="utf-8") as f:
            prd = json.load(f)
        duplicates = find_duplicates(prd)
        for id1, id2, score in duplicates:
            print(f"{id1} <> {id2} : {score:.3f}")

    elif command == "merge":
        if len(sys.argv) < 5:
            print(
                "Usage: dedup_confidence.py merge <prd_file> <id1> <id2>",
                file=sys.stderr,
            )
            sys.exit(1)
        prd_file = sys.argv[2]
        id1 = sys.argv[3]
        id2 = sys.argv[4]

        with open(prd_file, encoding="utf-8") as f:
            prd = json.load(f)

        result = merge_stories(id1, id2, prd)
        if result is None:
            print(f"ERROR: Story {id1} or {id2} not found", file=sys.stderr)
            sys.exit(1)

        with open(prd_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"Merged {id1} and {id2} into prd.json")

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
