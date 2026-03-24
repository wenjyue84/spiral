"""lib/validation_confidence_scorer.py — Phase S validation confidence scorer (US-1062).

Scores each story 0-100 for how likely it is to pass validation on the first attempt.
Higher scores = simpler story = more confident it will validate cleanly.
Lower scores = complex story = needs more enrichment before implementation.

Scoring model (starts at 100, subtracts penalties):
  - Complexity keywords in description:  -5 each (max -40)
  - Dependency count:                    -5 per dep (max -30)
  - File change hint complexity:         -10 per (file, pattern) hit (max -20)
  - Minimum score: 0
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

# Keywords that signal implementation complexity; each match costs 5 points (cap: 30)
_COMPLEXITY_KEYWORDS: list[str] = [
    "distributed",
    "concurr",
    "parallel",
    "transaction",
    "database",
    "cache",
    "monitor",
    "migrat",
    "rollback",
    "authentication",
    "authorization",
    "encryption",
    "websocket",
    "streaming",
    "pipeline",
    "federation",
    "orchestrat",
    "async",
    "lock",
    "mutex",
]

# File patterns that indicate cross-cutting concerns; each match costs 10 points (cap: 20)
_COMPLEX_FILE_PATTERNS: list[str] = [
    r"\.\./",
    r"(src|lib)/.+/(src|lib)/",
    r"\*\*",
    r"\.config\.",
    r"schema",
    r"migration",
]

_MAX_KEYWORD_PENALTY = 40
_MAX_DEP_PENALTY = 30
_MAX_FILE_HINT_PENALTY = 20
_KEYWORD_COST = 5
_DEP_COST = 5
_FILE_HINT_COST = 10


def score_story(story: dict[str, Any]) -> int:
    """Return a 0-100 confidence score for a single story.

    100 = simple, high confidence validation will pass.
    0   = complex, needs heavy enrichment before implementation.
    """
    score = 100

    # Keyword penalty
    text = " ".join(
        [
            story.get("description", ""),
            story.get("title", ""),
            *story.get("acceptanceCriteria", []),
        ]
    ).lower()

    keyword_hits = sum(1 for kw in _COMPLEXITY_KEYWORDS if kw in text)
    keyword_penalty = min(keyword_hits * _KEYWORD_COST, _MAX_KEYWORD_PENALTY)
    score -= keyword_penalty

    # Dependency penalty
    dep_count = len(story.get("dependencies", []))
    dep_penalty = min(dep_count * _DEP_COST, _MAX_DEP_PENALTY)
    score -= dep_penalty

    # File change hint penalty — count per (file, pattern) hit so multiple files can trigger
    file_hints: list[str] = story.get("filesTouch", []) or story.get("file_change_hints", [])
    hint_hits = sum(1 for hint in file_hints for pat in _COMPLEX_FILE_PATTERNS if re.search(pat, hint))
    hint_penalty = min(hint_hits * _FILE_HINT_COST, _MAX_FILE_HINT_PENALTY)
    score -= hint_penalty

    return max(0, score)


def score_all_stories(prd_path: Path) -> dict[str, Any]:
    """Read prd.json, add _validation_confidence to each story, write back in-place.

    Returns a summary dict: {scored: int, avg_score: float, low_confidence: list[str]}
    """
    with open(prd_path, encoding="utf-8") as f:
        prd: dict[str, Any] = json.load(f)

    stories: list[dict[str, Any]] = prd.get("userStories", [])
    low_confidence: list[str] = []

    for story in stories:
        confidence = score_story(story)
        story["_validation_confidence"] = confidence
        if confidence < 50:
            low_confidence.append(story.get("id", "?"))

    avg_score = sum(s.get("_validation_confidence", 0) for s in stories) / max(len(stories), 1)

    # Atomic write: write to temp file, then replace
    tmp_fd, tmp_path = tempfile.mkstemp(dir=prd_path.parent, suffix=".tmp", prefix="prd_")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(prd, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, prd_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return {
        "scored": len(stories),
        "avg_score": round(avg_score, 1),
        "low_confidence": low_confidence,
        "low_confidence_count": len(low_confidence),
    }
