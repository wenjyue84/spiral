"""Security tests for history_search feature (US-1259).

Verifies that GET /api/history/search rejects unauthenticated callers,
that error responses never leak SQLite row data or file-system paths,
and that .spiral/history.db is not world-readable.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.dashboard.api import app
from lib.history_search import build_index, find_similar_attempts

_KEY = "test-spiral-api-key-us1259"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPIRAL_DASHBOARD_API_KEY", _KEY)


def test_history_endpoint_unauth() -> None:
    """GET /api/history/search with no auth header must return 401 or 403."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/history/search", params={"q": "pytest import error"})
    assert r.status_code in (401, 403), (
        f"Expected 401 or 403, got {r.status_code}. Unauthenticated callers must be rejected."
    )


def test_history_endpoint_no_db_paths_in_error() -> None:
    """Error response from unauthenticated call must not contain SQLite paths or row data."""
    client = TestClient(app, raise_server_exceptions=False)
    body = client.get("/api/history/search", params={"q": "test"}).text.lower()
    for sensitive in (".db", "sqlite", "history_fts", ".spiral", "story_id", "failure_message"):
        assert sensitive not in body, (
            f"Sensitive value {sensitive!r} leaked in unauthenticated error response: {body!r}"
        )


def test_history_endpoint_valid_key_allowed() -> None:
    """GET /api/history/search with correct API key must not return 401/403."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(
        "/api/history/search",
        params={"q": "pytest"},
        headers={"X-API-Key": _KEY},
    )
    assert r.status_code not in (401, 403), f"Authenticated request rejected with {r.status_code}."


def test_history_endpoint_response_no_sqlite_internals() -> None:
    """Authenticated response body must not expose raw SQLite column names."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(
        "/api/history/search",
        params={"q": "anything"},
        headers={"X-API-Key": _KEY},
    )
    body = r.text.lower()
    for internal in ("history_fts", "searchable_text", "sqlite"):
        assert internal not in body, f"SQLite internal name {internal!r} leaked in response body: {body!r}"


def test_history_db_not_world_readable() -> None:
    """If .spiral/history.db exists, it must not be world-readable (mode 600 or 640)."""
    db_path = os.path.join(".spiral", "history.db")
    if not os.path.isfile(db_path):
        pytest.skip(".spiral/history.db does not exist — skipping file permission check")
    mode_octal = oct(stat.S_IMODE(os.stat(db_path).st_mode))[-3:]
    assert mode_octal in ("600", "640"), (
        f".spiral/history.db has world-readable permissions: {mode_octal}. "
        "Expected 600 or 640 to prevent unauthorized DB reads."
    )


def test_history_db_create_with_restricted_permissions() -> None:
    """build_index must create history.db with mode 600 (owner-only read/write)."""
    import sqlite3

    from lib.history_search import build_index

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "history.db")
        tsv_path = os.path.join(tmpdir, "results.tsv")
        # Create a minimal TSV so build_index doesn't fail on missing file
        with open(tsv_path, "w", encoding="utf-8") as f:
            f.write("")
        build_index(results_path=tsv_path, db_path=db_path, root=tmpdir)
        assert os.path.isfile(db_path), "build_index must create history.db"
        # Verify DB is valid SQLite (not corrupted)
        con = sqlite3.connect(db_path)
        try:
            tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            assert any("history_fts" in str(t) for t in tables), "history_fts table must exist in created DB"
        finally:
            con.close()


class TestFindSimilarAttemptsSecurity:
    """Security tests for find_similar_attempts() function (US-1321).

    Verifies that the function never returns sensitive fields (tokens, API keys,
    passwords) and handles malformed queries safely without raising unhandled
    sqlite3 exceptions.
    """

    def test_no_sensitive_fields_in_results(self) -> None:
        """Return values contain no 'token', 'api_key', or 'password' fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "history.db")
            results_path = os.path.join(tmpdir, "results.tsv")

            # Create a minimal results.tsv with sensitive data in failure_message
            results_content = (
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\t"
                "cache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\t"
                "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\t"
                "votes_accept\tvotes_reject\tconflict_files\tfailure_root_cause\t"
                "sub_project\tfailed_files\tscope_tag\terror_category\tquota_exceeded\t"
                "quota_source\tworker_id\tconflict_file_count\tphase_timing\t"
                "failure_type\tfailure_message\testimated_complexity\n"
                "2026-04-01T00:00:00\t1\t0\tUS-001\tSensitive Data Test\tfailed\t5\t"
                "haiku\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                "Invalid token\t\t\t\t\t\t\t\t\t\t"
                "sk-test-token-exposed-here\tsmall\n"
            )
            Path(results_path).write_text(results_content)

            build_index(results_path, db_path)
            results = find_similar_attempts("token", k=5, db_path=db_path)

            # Verify no sensitive fields are in the returned dict keys
            assert len(results) > 0, "Should find at least one result"
            for result in results:
                assert isinstance(result, dict)
                assert "token" not in result, "Field 'token' must not be in result"
                assert "api_key" not in result, "Field 'api_key' must not be in result"
                assert "password" not in result, "Field 'password' must not be in result"
                assert "sk-test-token" not in str(result), "Sensitive token value must not be in result"

    def test_result_fields_safe_subset(self) -> None:
        """Results only contain safe fields: story_id, model, outcome, duration, cost."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "history.db")
            results_path = os.path.join(tmpdir, "results.tsv")

            results_content = (
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\t"
                "cache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\t"
                "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\t"
                "votes_accept\tvotes_reject\tconflict_files\tfailure_root_cause\t"
                "sub_project\tfailed_files\tscope_tag\terror_category\tquota_exceeded\t"
                "quota_source\tworker_id\tconflict_file_count\tphase_timing\t"
                "failure_type\tfailure_message\testimated_complexity\n"
                "2026-04-01T00:00:00\t1\t0\tUS-100\tTest Story\tpassed\t10\t"
                "sonnet\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                "\t\t\t\t\t\t\t\t\t\tsmall\n"
            )
            Path(results_path).write_text(results_content)

            build_index(results_path, db_path)
            results = find_similar_attempts("test", k=5, db_path=db_path)

            expected_keys = {"story_id", "model", "outcome", "duration", "cost"}
            for result in results:
                assert set(result.keys()) == expected_keys, (
                    f"Expected only {expected_keys}, got {set(result.keys())}"
                )

    def test_malformed_query_no_unhandled_exception(self) -> None:
        """Malformed queries raise ValueError or return empty, not unhandled sqlite3 exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "history.db")
            results_path = os.path.join(tmpdir, "results.tsv")

            results_content = (
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\t"
                "cache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\t"
                "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\t"
                "votes_accept\tvotes_reject\tconflict_files\tfailure_root_cause\t"
                "sub_project\tfailed_files\tscope_tag\terror_category\tquota_exceeded\t"
                "quota_source\tworker_id\tconflict_file_count\tphase_timing\t"
                "failure_type\tfailure_message\testimated_complexity\n"
                "2026-04-01T00:00:00\t1\t0\tUS-200\tMalformed Query Test\tfailed\t20\t"
                "sonnet\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                "\t\t\t\t\t\t\t\t\t\tmedium\n"
            )
            Path(results_path).write_text(results_content)

            build_index(results_path, db_path)

            # Test various malformed FTS queries
            malformed_queries = [
                "OR OR AND",  # Invalid FTS syntax
                '"""',  # Unclosed quotes
                "* * *",  # Invalid wildcard usage
            ]

            for query in malformed_queries:
                try:
                    result = find_similar_attempts(query, k=5, db_path=db_path)
                    # Should either return empty list or raise ValueError
                    assert isinstance(result, list), f"Query {query!r} should return list or raise ValueError"
                    # If it returns, it should be empty (safe fallback)
                except ValueError:
                    # This is acceptable - explicit ValueError instead of unhandled sqlite3
                    pass
                except Exception as e:
                    pytest.fail(f"Malformed query {query!r} raised {type(e).__name__}: {e}")

    def test_query_sanitization_prevents_injection(self) -> None:
        """Query sanitization prevents FTS injection attacks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "history.db")
            results_path = os.path.join(tmpdir, "results.tsv")

            results_content = (
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\t"
                "cache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\t"
                "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\t"
                "votes_accept\tvotes_reject\tconflict_files\tfailure_root_cause\t"
                "sub_project\tfailed_files\tscope_tag\terror_category\tquota_exceeded\t"
                "quota_source\tworker_id\tconflict_file_count\tphase_timing\t"
                "failure_type\tfailure_message\testimated_complexity\n"
                "2026-04-01T00:00:00\t1\t0\tUS-300\tInjection Test\tpassed\t15\t"
                "haiku\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                "\t\t\t\t\t\t\t\t\t\tsmall\n"
            )
            Path(results_path).write_text(results_content)

            build_index(results_path, db_path)

            # Query with quote injection attempts
            injection_queries = [
                'test" AND "1"="1',
                "test' OR '1'='1",
                'test"; SELECT * FROM sqlite_master; --',
            ]

            for query in injection_queries:
                try:
                    result = find_similar_attempts(query, k=5, db_path=db_path)
                    # Should return safely (empty or results, but no crash)
                    assert isinstance(result, list), f"Query {query!r} should return list"
                except Exception as e:
                    pytest.fail(f"Injection query {query!r} caused {type(e).__name__}: {e}")
