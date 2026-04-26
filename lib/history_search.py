"""
history_search.py — FTS5-based search over historical SPIRAL execution results.

Builds a SQLite FTS5 index from results.tsv rows and failure snippets, enabling
fast semantic search over prior story attempts.

Usage:
    from lib.history_search import build_index, find_similar_attempts

    build_index()  # rebuild .spiral/history.db from results.tsv
    hits = find_similar_attempts("failing pytest import error", k=5)
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any

from results_tsv import parse_results_tsv

_DEFAULT_DB = os.path.join(".spiral", "history.db")
_DEFAULT_TSV = "results.tsv"


def _get_failure_snippet(story_id: str, root: str = ".") -> str:
    """Read failure snippet from .spiral/crashes/<story_id>.txt if it exists."""
    crash_path = os.path.join(root, ".spiral", "crashes", f"{story_id}.txt")
    try:
        with open(crash_path, encoding="utf-8", errors="replace") as f:
            return f.read(2048)
    except FileNotFoundError:
        return ""


def build_index(
    results_path: str = _DEFAULT_TSV,
    db_path: str = _DEFAULT_DB,
    root: str = ".",
) -> None:
    """Rebuild the FTS5 history index from results.tsv.

    Creates (or replaces) .spiral/history.db with a virtual FTS5 table
    indexed by story_id, title, model, status, failure message, and any
    crash snippets found in .spiral/crashes/.

    Tokenizer: unicode61 with lowercase=1 for case-insensitive search.
    """
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    records = parse_results_tsv(results_path)

    con = sqlite3.connect(db_path)
    try:
        con.execute("DROP TABLE IF EXISTS history_fts")
        con.execute("""
            CREATE VIRTUAL TABLE history_fts USING fts5(
                story_id UNINDEXED,
                model UNINDEXED,
                status UNINDEXED,
                duration_sec UNINDEXED,
                failure_message UNINDEXED,
                searchable_text,
                tokenize='unicode61 remove_diacritics 2'
            )
        """)

        rows: list[tuple[str, str, str, str, str, str]] = []
        for rec in records:
            snippet = _get_failure_snippet(rec.story_id, root)
            searchable = " ".join(filter(None, [rec.story_title, rec.failure_message, rec.failure_root_cause, snippet]))
            rows.append(
                (
                    rec.story_id,
                    rec.model,
                    rec.status,
                    rec.duration_sec,
                    rec.failure_message,
                    searchable,
                )
            )

        con.executemany(
            "INSERT INTO history_fts VALUES (?,?,?,?,?,?)",
            rows,
        )
        con.commit()
    finally:
        con.close()


def find_similar_attempts(
    query: str,
    k: int = 5,
    db_path: str = _DEFAULT_DB,
) -> list[dict[str, Any]]:
    """Search history index for prior attempts similar to query.

    Returns up to k results ordered by FTS5 relevance (BM25).
    Each result is a dict with keys: story_id, model, outcome, duration, cost.

    Returns an empty list if the index does not exist or query is empty.
    """
    if not query.strip() or not os.path.isfile(db_path):
        return []

    # Sanitise query: FTS5 special chars that cause parse errors
    safe_query = query.replace('"', " ").replace("'", " ").strip()
    if not safe_query:
        return []

    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """
            SELECT story_id, model, status, duration_sec, failure_message
            FROM history_fts
            WHERE searchable_text MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (safe_query, k),
        ).fetchall()
    except sqlite3.OperationalError:
        # Invalid FTS query — return empty
        return []
    finally:
        con.close()

    results: list[dict[str, Any]] = []
    for story_id, model, status, duration, failure_msg in rows:
        results.append(
            {
                "story_id": story_id,
                "model": model,
                "outcome": status,
                "duration": duration,
                "cost": "",  # cost not stored in results.tsv currently
            }
        )
    return results
