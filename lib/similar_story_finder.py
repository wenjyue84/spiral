#!/usr/bin/env python3
"""
Find similar passed stories using TF-IDF similarity.

For each validated story, searches past passed stories to find analogous
implementations. Injects top 3 similar stories' file paths into
_enrichment.similar_solutions for Ralph to learn from.

Usage:
  python similar_story_finder.py --prd prd.json \\
    --validated-in _validated_stories.json \\
    --enriched-out _enriched_stories.json
"""

import argparse
import json
import sys
from typing import Any, cast

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def load_json(path: str) -> dict[str, Any]:
    """Load JSON from file."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return cast(dict[str, Any], data)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: Failed to load {path}: {e}", file=sys.stderr)
        return {}


def get_passed_stories(prd: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract all passed stories from prd.json."""
    stories = prd.get("userStories", [])
    return [s for s in stories if s.get("passes") is True]


def create_searchable_text(story: dict[str, Any]) -> str:
    """Create searchable text from story title and description."""
    title = story.get("title", "")
    desc = story.get("description", "")
    return f"{title} {desc}".strip()


def find_similar_stories(
    candidate: dict[str, Any],
    passed_stories: list[dict[str, Any]],
    threshold: float = 0.5,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """
    Find top K similar passed stories using TF-IDF cosine similarity.

    Args:
        candidate: Story to find similar stories for
        passed_stories: All passed stories to search
        threshold: Minimum similarity score (0.0-1.0)
        top_k: Number of similar stories to return

    Returns:
        List of similar stories with their similarity scores
    """
    if not passed_stories:
        return []

    candidate_text = create_searchable_text(candidate)
    if not candidate_text.strip():
        return []

    all_texts = [candidate_text] + [create_searchable_text(s) for s in passed_stories]

    try:
        vectorizer = TfidfVectorizer(lowercase=True, stop_words="english", max_features=500)
        tfidf_matrix = vectorizer.fit_transform(all_texts)
        similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()
    except Exception as e:
        print(f"WARNING: TF-IDF vectorization failed: {e}", file=sys.stderr)
        return []

    similar_with_scores = [
        (passed_stories[i], float(similarities[i])) for i in range(len(passed_stories))
    ]
    similar_with_scores.sort(key=lambda x: x[1], reverse=True)

    results = [s for s, score in similar_with_scores if score >= threshold][:top_k]
    return results


def extract_file_paths(story: dict[str, Any]) -> list[str]:
    """Extract file paths from a story's filesTouch or technicalNotes."""
    files = set()
    files.update(story.get("filesTouch", []))
    for note in story.get("technicalNotes", []):
        if "File to edit:" in note or "File to create:" in note:
            parts = note.split(":", 1)
            if len(parts) > 1:
                file_path = parts[1].strip().split()[0]
                files.add(file_path)
    return sorted(list(files))


def enrich_with_similar_solutions(
    validated_stories: list[dict[str, Any]],
    passed_stories: list[dict[str, Any]],
    similarity_threshold: float = 0.5,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """
    Enrich validated stories with similar solution references.

    For each story, finds top K similar passed stories and injects their
    file paths into _enrichment.similar_solutions.

    Args:
        validated_stories: Stories to enrich
        passed_stories: All passed stories to search
        similarity_threshold: Minimum TF-IDF similarity score
        top_k: Number of similar stories to find

    Returns:
        Enriched stories list with _enrichment fields added
    """
    enriched = []

    for story in validated_stories:
        enriched_story = dict(story)
        enriched_story.setdefault("_enrichment", {})

        similar = find_similar_stories(
            story, passed_stories, threshold=similarity_threshold, top_k=top_k
        )

        if similar:
            similar_solutions = []
            for sim_story in similar:
                files = extract_file_paths(sim_story)
                if files:
                    similar_solutions.append(
                        {
                            "id": sim_story.get("id", "unknown"),
                            "title": sim_story.get("title", ""),
                            "files": files,
                        }
                    )

            if similar_solutions:
                enriched_story["_enrichment"]["similar_solutions"] = similar_solutions

        enriched.append(enriched_story)

    return enriched


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Find similar passed stories and inject as enrichment hints"
    )
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--validated-in", required=True, help="Path to validated stories")
    parser.add_argument("--enriched-out", required=True, help="Output path for enriched stories")
    parser.add_argument("--threshold", type=float, default=0.5, help="Similarity threshold")
    parser.add_argument("--top-k", type=int, default=3, help="Number of similar stories to find")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing")

    args = parser.parse_args()

    prd = load_json(args.prd)
    validated_data = load_json(args.validated_in)
    validated_stories = validated_data.get("stories", [])
    passed_stories = get_passed_stories(prd)

    enriched = enrich_with_similar_solutions(
        validated_stories, passed_stories, similarity_threshold=args.threshold, top_k=args.top_k
    )

    output = {"stories": enriched}

    if args.dry_run:
        print(json.dumps(output, indent=2))
    else:
        with open(args.enriched_out, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"[similar_story_finder] Enriched {len(enriched)} stories -> {args.enriched_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
