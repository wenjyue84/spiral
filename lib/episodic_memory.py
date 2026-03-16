"""episodic_memory.py — SQLite FTS5 episodic memory for Ralph workers.

Stores story implementation records so future workers can recall how similar
stories were implemented.  Uses FTS5 full-text search for keyword-based
retrieval with zero external dependencies (stdlib sqlite3 only).

Usage (CLI):
    python episodic_memory.py write  DB_PATH STORY_ID STORY_TYPE APPROACH OUTCOME ITERATION
    python episodic_memory.py query  DB_PATH QUERY_TEXT [--top-k 3]
    python episodic_memory.py list   DB_PATH [--limit 20]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone

DEFAULT_DB_PATH = ".spiral/episodic_memory.db"

# FTS5 virtual table with content columns.  iteration and timestamp are
# UNINDEXED because we never need full-text search on them.
_CREATE_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS episodic_memory USING fts5(
    story_id,
    story_type,
    approach_summary,
    outcome,
    iteration UNINDEXED,
    timestamp UNINDEXED
);
"""


def init_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create the FTS5 table if needed and return a connection."""
    conn = sqlite3.connect(db_path)
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def write_memory(
    story_id: str,
    story_type: str,
    approach_summary: str,
    outcome: str,
    iteration: int,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Write a single episodic record."""
    conn = init_db(db_path)
    try:
        conn.execute(
            "INSERT INTO episodic_memory "
            "(story_id, story_type, approach_summary, outcome, iteration, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                story_id,
                story_type,
                approach_summary,
                outcome,
                str(iteration),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def query_similar(
    story_title: str,
    top_k: int = 3,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict[str, str]]:
    """Return top-k records whose story_type/approach match *story_title* keywords.

    Uses FTS5 MATCH with BM25 ranking.  Returns empty list if no matches or
    if the database does not exist.
    """
    try:
        conn = init_db(db_path)
    except sqlite3.OperationalError:
        return []

    # Tokenise the title into individual terms joined by OR for broad matching.
    tokens = [t for t in story_title.split() if len(t) > 2]
    if not tokens:
        conn.close()
        return []

    fts_query = " OR ".join(tokens)
    try:
        cursor = conn.execute(
            "SELECT story_id, story_type, approach_summary, outcome, iteration, timestamp "
            "FROM episodic_memory WHERE episodic_memory MATCH ? "
            "ORDER BY rank LIMIT ?",
            (fts_query, top_k),
        )
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        # Malformed FTS query — return empty
        rows = []
    finally:
        conn.close()

    return [
        {
            "story_id": r[0],
            "story_type": r[1],
            "approach_summary": r[2],
            "outcome": r[3],
            "iteration": r[4],
            "timestamp": r[5],
        }
        for r in rows
    ]


def list_recent(
    limit: int = 20,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict[str, str]]:
    """Return the *limit* most recent episodic records (newest first)."""
    try:
        conn = init_db(db_path)
    except sqlite3.OperationalError:
        return []

    try:
        cursor = conn.execute(
            "SELECT story_id, story_type, approach_summary, outcome, iteration, timestamp "
            "FROM episodic_memory ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    return [
        {
            "story_id": r[0],
            "story_type": r[1],
            "approach_summary": r[2],
            "outcome": r[3],
            "iteration": r[4],
            "timestamp": r[5],
        }
        for r in rows
    ]


# ── CLI ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="SPIRAL episodic memory manager")
    sub = parser.add_subparsers(dest="command", required=True)

    # write
    p_write = sub.add_parser("write", help="Store an episodic record")
    p_write.add_argument("db_path")
    p_write.add_argument("story_id")
    p_write.add_argument("story_type")
    p_write.add_argument("approach_summary")
    p_write.add_argument("outcome", choices=["pass", "fail"])
    p_write.add_argument("iteration", type=int)

    # query
    p_query = sub.add_parser("query", help="Find similar past implementations")
    p_query.add_argument("db_path")
    p_query.add_argument("query_text")
    p_query.add_argument("--top-k", type=int, default=3)

    # list
    p_list = sub.add_parser("list", help="List recent episodic records")
    p_list.add_argument("db_path")
    p_list.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    if args.command == "write":
        write_memory(
            args.story_id,
            args.story_type,
            args.approach_summary,
            args.outcome,
            args.iteration,
            db_path=args.db_path,
        )
        print(f"Stored episodic record for {args.story_id}")

    elif args.command == "query":
        results = query_similar(args.query_text, top_k=args.top_k, db_path=args.db_path)
        print(json.dumps(results, indent=2))

    elif args.command == "list":
        results = list_recent(limit=args.limit, db_path=args.db_path)
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
