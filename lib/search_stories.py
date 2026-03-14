#!/usr/bin/env python3
"""lib/search_stories.py — Fuzzy / semantic story search for Spiral.

Usage (library):
    from lib.search_stories import search_stories
    results = search_stories(prd_path, query, top_k=5, use_json=False)

Uses rapidfuzz for fuzzy matching by default.
Falls back to cosine similarity via sentence-transformers when available,
with embedding cache at .spiral/story_embeddings.pkl.
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any

# Force UTF-8 stdout on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _story_text(story: dict[str, Any]) -> str:
    """Return a single search string combining title, description, and ACs."""
    parts: list[str] = []
    if title := story.get("title", ""):
        parts.append(title)
    if desc := story.get("description", ""):
        parts.append(desc)
    for ac in story.get("acceptanceCriteria", []):
        if isinstance(ac, str):
            parts.append(ac)
    return " ".join(parts)


def _status(story: dict[str, Any]) -> str:
    if story.get("passes"):
        return "passed"
    if story.get("skipped"):
        return "skipped"
    return "pending"


# ---------------------------------------------------------------------------
# Fuzzy search (always available)
# ---------------------------------------------------------------------------

def _fuzzy_search(
    stories: list[dict[str, Any]],
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    from rapidfuzz import process, fuzz

    corpus = [_story_text(s) for s in stories]
    matches = process.extract(
        query,
        corpus,
        scorer=fuzz.WRatio,
        limit=top_k,
    )
    results = []
    for _matched_text, score, idx in matches:
        story = stories[idx]
        results.append(
            {
                "id": story.get("id", ""),
                "title": story.get("title", ""),
                "status": _status(story),
                "score": round(score / 100.0, 4),
                "engine": "fuzzy",
            }
        )
    return results


# ---------------------------------------------------------------------------
# Semantic search (optional; requires sentence-transformers)
# ---------------------------------------------------------------------------

def _cache_path(scratch_dir: Path) -> Path:
    return scratch_dir / "story_embeddings.pkl"


def _load_embedding_cache(
    cache_file: Path,
    prd_mtime: float,
) -> dict[str, Any] | None:
    """Return cached data if still fresh, else None."""
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "rb") as fh:
            data = pickle.load(fh)
        if data.get("prd_mtime", 0) != prd_mtime:
            return None
        return data
    except Exception:
        return None


def _save_embedding_cache(
    cache_file: Path,
    embeddings: Any,
    corpus: list[str],
    prd_mtime: float,
) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(cache_file) + ".tmp"
    try:
        with open(tmp, "wb") as fh:
            pickle.dump(
                {"embeddings": embeddings, "corpus": corpus, "prd_mtime": prd_mtime},
                fh,
            )
        os.replace(tmp, cache_file)
    except Exception:
        pass
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _semantic_search(
    stories: list[dict[str, Any]],
    query: str,
    top_k: int,
    prd_path: Path,
    scratch_dir: Path,
) -> list[dict[str, Any]]:
    from sentence_transformers import SentenceTransformer
    import numpy as np

    corpus = [_story_text(s) for s in stories]
    prd_mtime = prd_path.stat().st_mtime

    cache_file = _cache_path(scratch_dir)
    cached = _load_embedding_cache(cache_file, prd_mtime)

    model = SentenceTransformer("all-MiniLM-L6-v2")

    if cached and cached.get("corpus") == corpus:
        corpus_embeddings = cached["embeddings"]
    else:
        corpus_embeddings = model.encode(corpus, convert_to_numpy=True, show_progress_bar=False)
        _save_embedding_cache(cache_file, corpus_embeddings, corpus, prd_mtime)

    query_emb = model.encode([query], convert_to_numpy=True, show_progress_bar=False)[0]

    # Cosine similarity
    norms = np.linalg.norm(corpus_embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-9, norms)
    normed = corpus_embeddings / norms
    q_norm = query_emb / (np.linalg.norm(query_emb) or 1e-9)
    scores = normed @ q_norm

    top_indices = np.argsort(scores)[::-1][:top_k]
    results = []
    for idx in top_indices:
        story = stories[int(idx)]
        results.append(
            {
                "id": story.get("id", ""),
                "title": story.get("title", ""),
                "status": _status(story),
                "score": round(float(scores[idx]), 4),
                "engine": "semantic",
            }
        )
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_stories(
    prd_path: Path,
    query: str,
    top_k: int = 5,
    scratch_dir: Path | None = None,
    force_fuzzy: bool = False,
) -> list[dict[str, Any]]:
    """Return up to *top_k* stories matching *query*.

    Prefers semantic search (sentence-transformers) when available;
    falls back to rapidfuzz fuzzy matching.

    Args:
        prd_path: Path to prd.json.
        query: Natural-language search query.
        top_k: Maximum number of results to return.
        scratch_dir: Directory for embedding cache (defaults to prd_path.parent / ".spiral").
        force_fuzzy: Skip semantic search even if sentence-transformers is installed.

    Returns:
        List of result dicts: {id, title, status, score, engine}.
    """
    if not prd_path.exists():
        return []
    with open(prd_path, encoding="utf-8") as fh:
        stories: list[dict[str, Any]] = json.load(fh).get("userStories", [])

    if not stories:
        return []

    if scratch_dir is None:
        scratch_dir = prd_path.parent / ".spiral"

    # Try semantic first
    if not force_fuzzy:
        try:
            return _semantic_search(stories, query, top_k, prd_path, scratch_dir)
        except Exception:
            pass

    return _fuzzy_search(stories, query, top_k)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_table(results: list[dict[str, Any]]) -> str:
    """Return a compact fixed-width table string."""
    if not results:
        return "No matching stories found."
    header = f"{'#':<3}  {'ID':<10}  {'Status':<8}  {'Score':<7}  {'Engine':<8}  Title"
    sep = "-" * min(120, 80)
    rows = [header, sep]
    for i, r in enumerate(results, 1):
        title = r["title"]
        if len(title) > 55:
            title = title[:52] + "..."
        rows.append(
            f"{i:<3}  {r['id']:<10}  {r['status']:<8}  {r['score']:<7.4f}  {r['engine']:<8}  {title}"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# CLI (standalone usage)
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="spiral-search",
        description="Search prd.json stories by natural language",
    )
    parser.add_argument("query", help="Search query")
    parser.add_argument("--prd", default="prd.json", metavar="FILE", help="Path to prd.json")
    parser.add_argument("--top", type=int, default=5, metavar="N", help="Max results (default 5)")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument("--fuzzy", action="store_true", help="Force fuzzy mode (skip semantic)")
    args = parser.parse_args()

    results = search_stories(
        Path(args.prd),
        args.query,
        top_k=args.top,
        force_fuzzy=args.fuzzy,
    )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(format_table(results))


if __name__ == "__main__":
    main()
