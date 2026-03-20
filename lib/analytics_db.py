"""DuckDB read layer for SPIRAL analytics — zero-migration SQL over flat files.

Queries existing JSONL/TSV files via DuckDB's read_json_auto() and
read_csv_auto(), providing full SQL analytics (GROUP BY, JOIN, WHERE,
window functions) with zero changes to any writer.

Usage:
    from lib.analytics_db import AnalyticsDB

    db = AnalyticsDB(project_root="/path/to/spiral")
    rows = db.query("SELECT model, count(*) FROM results GROUP BY model")
    summary = db.overview()
    model_perf = db.model_performance()
"""

from __future__ import annotations

import json
import os
from typing import Any

import duckdb


class AnalyticsDB:
    """Read-only SQL interface over SPIRAL's flat-file telemetry."""

    def __init__(self, project_root: str) -> None:
        self.root = os.path.abspath(project_root)
        self.con = duckdb.connect(":memory:")
        self._register_views()

    def _path(self, *parts: str) -> str:
        return os.path.join(self.root, *parts).replace("\\", "/")

    def _register_jsonl_view(self, view_name: str, candidates: list[str], empty_sql: str) -> None:
        """Register a view over a JSONL file, trying candidates in order.
        Falls back to empty_sql if no file exists or the file is corrupt."""
        for path in candidates:
            if os.path.isfile(path):
                try:
                    self.con.execute(f"""
                        CREATE OR REPLACE VIEW {view_name} AS
                        SELECT * FROM read_json('{path}',
                            format='newline_delimited',
                            ignore_errors=true,
                            maximum_object_size=1048576)
                    """)
                    return
                except Exception:
                    # File too corrupt even for ignore_errors — try next candidate
                    continue
        self.con.execute(f"CREATE OR REPLACE VIEW {view_name} AS {empty_sql}")

    def _register_views(self) -> None:
        """Register SQL views over flat files. Views are lazy — no data is
        loaded until a query actually touches them."""

        results_tsv = self._path("results.tsv")
        if os.path.isfile(results_tsv):
            self.con.execute(f"""
                CREATE OR REPLACE VIEW results AS
                SELECT * FROM read_csv_auto('{results_tsv}',
                    delim='\t', header=true, ignore_errors=true,
                    all_varchar=true)
            """)
        else:
            self.con.execute("""
                CREATE OR REPLACE VIEW results AS
                SELECT NULL::VARCHAR AS story_id, NULL::VARCHAR AS story_title,
                       NULL::VARCHAR AS status, NULL::VARCHAR AS spiral_iter,
                       NULL::VARCHAR AS ralph_iter, NULL::VARCHAR AS duration_sec,
                       NULL::VARCHAR AS model, NULL::VARCHAR AS retry_num,
                       NULL::VARCHAR AS timestamp, NULL::VARCHAR AS commit_sha,
                       NULL::VARCHAR AS run_id, NULL::VARCHAR AS wall_seconds,
                       NULL::VARCHAR AS peak_rss_kb, NULL::VARCHAR AS cache_hit
                WHERE false
            """)

        # JSONL files: use format='auto' and let DuckDB infer per-line, which
        # is more tolerant of truncated/malformed lines than 'newline_delimited'.
        self._register_jsonl_view(
            "events",
            [self._path(".spiral", "spiral_events.jsonl"), self._path("spiral_events.jsonl")],
            "SELECT NULL AS event WHERE false",
        )
        self._register_jsonl_view(
            "agent_telemetry",
            [self._path(".spiral", "agent-telemetry.jsonl")],
            "SELECT NULL AS workerId WHERE false",
        )
        self._register_jsonl_view(
            "calibration",
            [self._path("calibration.jsonl")],
            "SELECT NULL AS story_id WHERE false",
        )

        # prd.json requires manual loading (nested JSON array, not JSONL)
        prd_path = self._path("prd.json")
        if os.path.isfile(prd_path):
            try:
                with open(prd_path, encoding="utf-8") as f:
                    prd = json.load(f)
                stories = prd.get("userStories", [])
                if stories:
                    # Write stories as a temporary JSONL file for DuckDB to read
                    import tempfile

                    fd, tmp_jsonl = tempfile.mkstemp(suffix=".jsonl")
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8") as fh:
                            for s in stories:
                                fh.write(json.dumps(s) + "\n")
                        tmp_path = tmp_jsonl.replace("\\", "/")
                        self.con.execute(f"""
                            CREATE OR REPLACE TABLE stories AS
                            SELECT * FROM read_json_auto('{tmp_path}',
                                format='newline_delimited', ignore_errors=true)
                        """)
                    finally:
                        try:
                            os.unlink(tmp_jsonl)
                        except OSError:
                            pass
                else:
                    self._empty_stories_view()
            except (json.JSONDecodeError, OSError):
                self._empty_stories_view()
        else:
            self._empty_stories_view()

    def _empty_stories_view(self) -> None:
        self.con.execute("""
            CREATE OR REPLACE VIEW stories AS
            SELECT NULL AS id WHERE false
        """)

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        """Execute a SQL query and return results as a list of dicts."""
        result = self.con.execute(sql, params or [])
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def query_df(self, sql: str, params: list[Any] | None = None) -> Any:
        """Execute a SQL query and return a DuckDB relation (lazy)."""
        return self.con.execute(sql, params or [])

    # ── Canned queries ────────────────────────────────────────────────────

    def overview(self) -> dict[str, Any]:
        """High-level overview: total attempts, cost estimate, iterations."""
        rows = self.query("""
            SELECT
                count(*) AS total_attempts,
                max(CAST(spiral_iter AS INTEGER)) AS iterations,
                count(CASE WHEN status = 'pass' OR status = 'keep' THEN 1 END) AS passes,
                count(CASE WHEN status = 'fail' THEN 1 END) AS failures,
                min(timestamp) AS first_attempt,
                max(timestamp) AS last_attempt
            FROM results
        """)
        return rows[0] if rows else {}

    def model_performance(self) -> list[dict[str, Any]]:
        """Per-model success rate and average duration."""
        return self.query("""
            SELECT
                model,
                count(*) AS attempts,
                count(CASE WHEN status = 'pass' OR status = 'keep' THEN 1 END) AS passes,
                ROUND(count(CASE WHEN status = 'pass' OR status = 'keep' THEN 1 END)
                      * 100.0 / NULLIF(count(*), 0), 1) AS success_rate_pct,
                ROUND(AVG(CAST(duration_sec AS DOUBLE)), 1) AS avg_duration_sec
            FROM results
            WHERE model IS NOT NULL AND model != ''
            GROUP BY model
            ORDER BY attempts DESC
        """)

    def retry_analysis(self) -> list[dict[str, Any]]:
        """Success rate by retry attempt number."""
        return self.query("""
            SELECT
                CAST(retry_num AS INTEGER) AS retry,
                count(*) AS attempts,
                count(CASE WHEN status = 'pass' OR status = 'keep' THEN 1 END) AS passes,
                ROUND(count(CASE WHEN status = 'pass' OR status = 'keep' THEN 1 END)
                      * 100.0 / NULLIF(count(*), 0), 1) AS success_rate_pct
            FROM results
            GROUP BY CAST(retry_num AS INTEGER)
            ORDER BY retry
        """)

    def iteration_velocity(self) -> list[dict[str, Any]]:
        """Stories kept per iteration with duration."""
        return self.query("""
            SELECT
                CAST(spiral_iter AS INTEGER) AS iteration,
                count(*) AS total_attempts,
                count(CASE WHEN status = 'keep' THEN 1 END) AS kept,
                ROUND(SUM(CAST(duration_sec AS DOUBLE)) / 3600, 2) AS duration_hours
            FROM results
            GROUP BY CAST(spiral_iter AS INTEGER)
            ORDER BY iteration
        """)

    def bottlenecks(self, top_n: int = 10) -> list[dict[str, Any]]:
        """Most-retried and longest-running stories."""
        return self.query(
            """
            SELECT
                story_id,
                story_title,
                count(*) AS attempts,
                count(CASE WHEN status = 'pass' OR status = 'keep' THEN 1 END) AS passes,
                ROUND(SUM(CAST(duration_sec AS DOUBLE)), 1) AS total_duration_sec,
                MAX(model) AS last_model
            FROM results
            GROUP BY story_id, story_title
            ORDER BY attempts DESC
            LIMIT ?
        """,
            [top_n],
        )

    def cost_by_model(self) -> list[dict[str, Any]]:
        """Estimated cost breakdown by model tier."""
        return self.query("""
            WITH costs AS (
                SELECT
                    model,
                    CAST(duration_sec AS DOUBLE) / 3600 AS hours,
                    CASE
                        WHEN LOWER(model) LIKE '%haiku%' THEN 0.04
                        WHEN LOWER(model) LIKE '%sonnet%' THEN 0.24
                        WHEN LOWER(model) LIKE '%opus%' THEN 2.40
                        ELSE 0.24
                    END AS rate_per_hour
                FROM results
                WHERE model IS NOT NULL AND model != ''
            )
            SELECT
                model,
                count(*) AS attempts,
                ROUND(SUM(hours), 2) AS total_hours,
                ROUND(SUM(hours * rate_per_hour), 2) AS estimated_cost_usd
            FROM costs
            GROUP BY model
            ORDER BY estimated_cost_usd DESC
        """)

    def resource_usage_percentiles(self) -> list[dict[str, Any]]:
        """P50/P90/P99 for wall time, CPU, and memory by model."""
        return self.query("""
            SELECT
                model,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY CAST(wall_seconds AS DOUBLE)), 1) AS wall_p50,
                ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY CAST(wall_seconds AS DOUBLE)), 1) AS wall_p90,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY CAST(peak_rss_kb AS DOUBLE)), 0) AS mem_p50_kb,
                ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY CAST(peak_rss_kb AS DOUBLE)), 0) AS mem_p90_kb
            FROM results
            WHERE model IS NOT NULL AND model != ''
                AND wall_seconds IS NOT NULL AND wall_seconds != ''
            GROUP BY model
        """)

    def calibration_report(self) -> list[dict[str, Any]]:
        """Estimated vs actual complexity analysis from calibration data."""
        return self.query("""
            SELECT
                estimated_complexity,
                count(*) AS count,
                ROUND(MEDIAN(CAST(actual_duration_s AS DOUBLE)), 1) AS median_duration_s,
                ROUND(AVG(CAST(actual_duration_s AS DOUBLE)), 1) AS avg_duration_s,
                count(CASE WHEN passed THEN 1 END) AS passes,
                ROUND(count(CASE WHEN passed THEN 1 END) * 100.0 / NULLIF(count(*), 0), 1) AS pass_rate_pct
            FROM calibration
            GROUP BY estimated_complexity
            ORDER BY median_duration_s
        """)

    def event_counts_by_type(self, since: str | None = None) -> list[dict[str, Any]]:
        """Count events by type, optionally filtered by timestamp."""
        where = f"WHERE ts >= '{since}'" if since else ""
        return self.query(f"""
            SELECT
                event,
                count(*) AS count
            FROM events
            {where}
            GROUP BY event
            ORDER BY count DESC
        """)

    def stories_with_results(self) -> list[dict[str, Any]]:
        """JOIN stories with their latest result attempt."""
        # Check which columns exist in the stories table to handle optional fields
        try:
            cols = {
                r[0]
                for r in self.con.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'stories'"
                ).fetchall()
            }
        except Exception:
            cols = set()

        decomposed_col = 's."_decomposed" AS decomposed' if "_decomposed" in cols else "NULL AS decomposed"
        skipped_col = 's."_skipped" AS skipped' if "_skipped" in cols else "NULL AS skipped"
        complexity_col = (
            "s.estimatedComplexity AS complexity" if "estimatedComplexity" in cols else "NULL AS complexity"
        )

        return self.query(f"""
            WITH latest AS (
                SELECT
                    story_id,
                    status,
                    model,
                    duration_sec,
                    timestamp,
                    ROW_NUMBER() OVER (PARTITION BY story_id ORDER BY timestamp DESC) AS rn
                FROM results
            )
            SELECT
                s.id,
                s.title,
                s.passes,
                {decomposed_col},
                {skipped_col},
                {complexity_col},
                l.status AS last_status,
                l.model AS last_model,
                l.duration_sec AS last_duration_sec,
                l.timestamp AS last_attempt_ts
            FROM stories s
            LEFT JOIN latest l ON s.id = l.story_id AND l.rn = 1
            ORDER BY s.id
        """)

    def refresh(self) -> None:
        """Re-register views to pick up new data written since init."""
        self._register_views()

    def close(self) -> None:
        """Close the DuckDB connection."""
        self.con.close()
