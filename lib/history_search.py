"""
history_search.py — FTS5-based search over historical SPIRAL execution results.

Builds a SQLite FTS5 index from results.tsv rows and failure snippets, enabling
fast semantic search over prior story attempts. Provides HistoryIndex class for
building and querying the index with text and structured filters.

Usage:
    from lib.history_search import HistoryIndex, build_index, find_similar_attempts

    index = HistoryIndex()
    index.build()  # rebuild .spiral/history.db from results.tsv
    results = index.query("timeout", status="reject", model="haiku")
    stats = index.stats()
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime
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


class HistoryIndex:
    """FTS5-based full-text search index over results.tsv."""

    def __init__(
        self,
        results_path: str = _DEFAULT_TSV,
        db_path: str = _DEFAULT_DB,
        root: str = ".",
    ) -> None:
        """Initialize the index.

        Args:
            results_path: Path to results.tsv
            db_path: Path to SQLite database (default: .spiral/history.db)
            root: Root directory for crash snippet lookups
        """
        self.results_path = results_path
        self.db_path = db_path
        self.root = root

    def build(self) -> None:
        """Rebuild the FTS5 history index from results.tsv.

        Creates (or replaces) .spiral/history.db with a virtual FTS5 table
        indexed by story_id, title, model, status, failure message, and any
        crash snippets found in .spiral/crashes/.
        """
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

        if not os.path.exists(self.results_path):
            return

        records = parse_results_tsv(self.results_path)

        con = sqlite3.connect(self.db_path)
        try:
            con.execute("DROP TABLE IF EXISTS history_fts")
            con.execute("""
                CREATE VIRTUAL TABLE history_fts USING fts5(
                    story_id UNINDEXED,
                    story_title UNINDEXED,
                    model UNINDEXED,
                    status UNINDEXED,
                    duration_sec UNINDEXED,
                    timestamp UNINDEXED,
                    failure_message UNINDEXED,
                    searchable_text,
                    tokenize='unicode61 remove_diacritics 2'
                )
            """)

            rows: list[tuple[str, str, str, str, str, str, str, str]] = []
            for rec in records:
                snippet = _get_failure_snippet(rec.story_id, self.root)
                searchable = " ".join(
                    filter(
                        None,
                        [
                            rec.story_title,
                            rec.failure_message,
                            rec.failure_root_cause,
                            snippet,
                        ],
                    )
                )
                rows.append(
                    (
                        rec.story_id,
                        rec.story_title,
                        rec.model,
                        rec.status,
                        rec.duration_sec,
                        rec.timestamp,
                        rec.failure_message,
                        searchable,
                    )
                )

            con.executemany(
                "INSERT INTO history_fts VALUES (?,?,?,?,?,?,?,?)",
                rows,
            )
            con.commit()
        finally:
            con.close()

    def query(
        self,
        text: str = "",
        status: str = "",
        model: str = "",
        date_after: str = "",
        date_before: str = "",
    ) -> list[dict[str, Any]]:
        """Query the FTS5 index with text and optional filters.

        Args:
            text: Full-text search query (e.g., "timeout")
            status: Filter by status (e.g., "reject", "keep")
            model: Filter by model (e.g., "haiku", "sonnet")
            date_after: Filter by timestamp >= date (ISO 8601)
            date_before: Filter by timestamp <= date (ISO 8601)

        Returns:
            List of matching stories as dicts with story_id, model, status, duration
        """
        if not os.path.isfile(self.db_path):
            self.build()

        con = sqlite3.connect(self.db_path)
        try:
            # Build FTS5 query
            where_clauses: list[str] = []
            params: list[Any] = []

            # Text search
            if text:
                where_clauses.append("searchable_text MATCH ?")
                params.append(text)

            # Status filter
            if status:
                where_clauses.append("status = ?")
                params.append(status)

            # Model filter
            if model:
                where_clauses.append("model = ?")
                params.append(model)

            # Date range filters
            if date_after:
                where_clauses.append("timestamp >= ?")
                params.append(date_after)

            if date_before:
                where_clauses.append("timestamp <= ?")
                params.append(date_before)

            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
            query_sql = f"""
                SELECT story_id, story_title, model, status, duration_sec, failure_message
                FROM history_fts
                WHERE {where_sql}
                ORDER BY ROWID DESC
                LIMIT 1000
            """

            try:
                rows = con.execute(query_sql, params).fetchall()
            except sqlite3.OperationalError:
                # Invalid FTS query (syntax error) — return empty
                return []

            results: list[dict[str, Any]] = []
            for story_id, story_title, model, status, duration, failure_msg in rows:
                results.append(
                    {
                        "story_id": story_id,
                        "story_title": story_title,
                        "model": model,
                        "status": status,
                        "duration": duration,
                        "failure_message": failure_msg or "",
                    }
                )
            return results
        finally:
            con.close()

    def stats(self) -> dict[str, Any]:
        """Get index statistics.

        Returns:
            Dict with index_exists, row_count, last_updated (ISO 8601)
        """
        if not os.path.isfile(self.db_path):
            return {
                "index_exists": False,
                "row_count": 0,
                "last_updated": None,
            }

        con = sqlite3.connect(self.db_path)
        try:
            # Count rows in FTS5 table
            row = con.execute("SELECT COUNT(*) FROM history_fts").fetchone()
            row_count = row[0] if row else 0

            # Get file mtime as last_updated
            mtime = os.path.getmtime(self.db_path)
            last_updated = datetime.fromtimestamp(mtime).isoformat()

            return {
                "index_exists": True,
                "row_count": row_count,
                "last_updated": last_updated,
            }
        finally:
            con.close()


def build_index(
    results_path: str = _DEFAULT_TSV,
    db_path: str = _DEFAULT_DB,
    root: str = ".",
) -> None:
    """Rebuild the FTS5 history index from results.tsv.

    Backward-compatible function that wraps HistoryIndex.build().
    """
    index = HistoryIndex(results_path, db_path, root)
    index.build()


def find_similar_attempts(
    query: str,
    k: int = 5,
    db_path: str = _DEFAULT_DB,
) -> list[dict[str, Any]]:
    """Search history index for prior attempts similar to query.

    Returns up to k results ordered by FTS5 relevance.
    Each result is a dict with keys: story_id, model, outcome, duration, cost.

    Returns an empty list if the index does not exist or query is empty.

    Backward-compatible function that wraps HistoryIndex.query().
    """
    if not query.strip() or not os.path.isfile(db_path):
        return []

    try:
        con = sqlite3.connect(db_path)
    except (sqlite3.DatabaseError, sqlite3.OperationalError):
        # Database file corrupted or inaccessible
        return []

    try:
        try:
            rows = con.execute(
                """
                SELECT story_id, model, status, duration_sec, failure_message
                FROM history_fts
                WHERE searchable_text MATCH ?
                ORDER BY ROWID DESC
                LIMIT ?
                """,
                (query, k),
            ).fetchall()
        except sqlite3.OperationalError:
            # Invalid FTS query or table doesn't exist — return empty
            return []

        legacy_results: list[dict[str, Any]] = []
        for story_id, model, status, duration, failure_msg in rows:
            legacy_results.append(
                {
                    "story_id": story_id,
                    "model": model,
                    "outcome": status,
                    "duration": duration,
                    "cost": "",
                }
            )
        return legacy_results
    finally:
        con.close()


def main() -> None:
    """CLI entry point for spiral search-history command."""
    if len(sys.argv) < 2:
        print("Usage: spiral search-history <query> [filters...]")
        print("Example: spiral search-history 'timeout'")
        print("Example: spiral search-history 'timeout' status=reject model=sonnet")
        sys.exit(1)

    index = HistoryIndex()

    # Parse command
    command = sys.argv[1]

    if command == "--stats":
        stats = index.stats()
        import json

        print(json.dumps(stats, indent=2))
        sys.exit(0)

    # Assume first arg is search query, rest are filters
    text_query = command
    filter_args = sys.argv[2:] if len(sys.argv) > 2 else []

    # Parse filters (key=value, key>value, key<value format)
    status_filter = ""
    model_filter = ""
    date_after_filter = ""
    date_before_filter = ""

    for arg in filter_args:
        if "=" in arg:
            key, val = arg.split("=", 1)
            if key == "status":
                status_filter = val
            elif key == "model":
                model_filter = val
        elif ">" in arg:
            key, val = arg.split(">", 1)
            if key == "date":
                date_after_filter = val
        elif "<" in arg:
            key, val = arg.split("<", 1)
            if key == "date":
                date_before_filter = val

    # Execute query
    results = index.query(
        text=text_query,
        status=status_filter,
        model=model_filter,
        date_after=date_after_filter,
        date_before=date_before_filter,
    )

    # Print results
    if not results:
        print(f"[spiral] No results found for query: {text_query}")
        sys.exit(0)

    print(f"[spiral] Found {len(results)} result(s):")
    print()
    for result in results:
        duration = str(result.get("duration", ""))
        story_title = result.get("story_title", "")
        print(f"  {result['story_id']:<12} {result['status']:<10} {result['model']:<10} {duration:<6} {story_title}")


if __name__ == "__main__":
    main()
