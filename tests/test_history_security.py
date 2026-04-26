"""Security tests for history_search DB access control (US-1306).

Verifies that .spiral/history.db and find_similar_attempts() do not expose
sensitive execution data (API keys, tokens, passwords) through query results
or error messages.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.history_search import build_index, find_similar_attempts


class TestNoSensitiveFieldsInResults:
    """Verify that returned results don't contain sensitive fields."""

    def test_no_sensitive_fields_in_results(self) -> None:
        """Results contain no secret/token/password fields in dict keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "history.db")
            results_path = os.path.join(tmpdir, "results.tsv")

            # Create a minimal results.tsv with potential sensitive data in failure_message
            results_content = (
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\t"
                "cache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\t"
                "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\t"
                "votes_accept\tvotes_reject\tconflict_files\tfailure_root_cause\t"
                "sub_project\tfailed_files\tscope_tag\terror_category\tquota_exceeded\t"
                "quota_source\tworker_id\tconflict_file_count\tphase_timing\t"
                "failure_type\tfailure_message\testimated_complexity\n"
                "2026-04-01T00:00:00\t1\t0\tUS-001\tAPI Key Leak Test\tfailed\t5\t"
                "haiku\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                "Invalid auth token\t\t\t\t\t\t\t\t\t\t"
                "API key sk-123456 exposed\tsmall\n"
            )
            Path(results_path).write_text(results_content)

            # Build the index
            build_index(results_path, db_path)

            # Query for results
            results = find_similar_attempts("API key", k=5, db_path=db_path)

            # Verify no sensitive fields are exposed
            assert len(results) > 0, "Should find at least one result"
            for result in results:
                assert isinstance(result, dict)
                # The dict should NOT contain failure_message or other sensitive fields
                assert "failure_message" not in result
                assert "secret" not in result.keys()
                assert "token" not in result.keys()
                assert "password" not in result.keys()

    def test_result_contains_only_expected_keys(self) -> None:
        """Result records contain only the 5 expected keys."""
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
                "2026-04-01T00:00:00\t1\t0\tUS-100\tTest Story 1\tpassed\t10\t"
                "sonnet\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                "\t\t\t\t\t\t\t\t\tTest passed\tsmall\n"
                "2026-04-01T00:00:00\t1\t0\tUS-101\tTest Story 2\tfailed\t15\t"
                "opus\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                "Deadlock\t\t\t\t\t\t\t\t\tTimeout occurred\tmedium\n"
            )
            Path(results_path).write_text(results_content)

            build_index(results_path, db_path)

            results = find_similar_attempts("test", k=5, db_path=db_path)

            # Verify each result has exactly the expected 5 keys
            expected_keys = {"story_id", "model", "outcome", "duration", "cost"}
            for result in results:
                assert set(result.keys()) == expected_keys, f"Expected keys {expected_keys}, got {set(result.keys())}"

    def test_result_schema_types(self) -> None:
        """Result records have correct data types for each field."""
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
                "2026-04-01T00:00:00\t1\t0\tUS-200\tSchema Type Test\tpassed\t8\t"
                "haiku\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                "\t\t\t\t\t\t\t\t\t\tsmall\n"
            )
            Path(results_path).write_text(results_content)

            build_index(results_path, db_path)

            results = find_similar_attempts("Schema", k=5, db_path=db_path)

            assert len(results) > 0
            result = results[0]
            # Verify types
            assert isinstance(result["story_id"], str)
            assert isinstance(result["model"], str)
            assert isinstance(result["outcome"], str)
            assert isinstance(result["duration"], str)  # From TSV, all fields are strings
            assert isinstance(result["cost"], str)


class TestMissingDBSafeError:
    """Verify safe error handling when DB doesn't exist."""

    def test_missing_db_safe_error(self) -> None:
        """Querying a non-existent DB raises handled error with no path leak."""
        # Query a non-existent database path
        result = find_similar_attempts("test query", k=5, db_path="/nonexistent/path/to/history.db")

        # Should return empty list, not raise an exception or leak the path
        assert result == []
        assert isinstance(result, list)

    def test_empty_query_returns_empty(self) -> None:
        """Empty or whitespace-only query returns empty list safely."""
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
                "2026-04-01T00:00:00\t1\t0\tUS-300\tEmpty Query Test\tpassed\t5\t"
                "haiku\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                "\t\t\t\t\t\t\t\t\t\tsmall\n"
            )
            Path(results_path).write_text(results_content)

            build_index(results_path, db_path)

            # Query with empty string
            result = find_similar_attempts("", k=5, db_path=db_path)
            assert result == []

            # Query with only whitespace
            result = find_similar_attempts("   ", k=5, db_path=db_path)
            assert result == []

    def test_fts_parse_error_safe_handling(self) -> None:
        """FTS5 parse errors from special characters return empty list safely."""
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
                "2026-04-01T00:00:00\t1\t0\tUS-400\tFTS Parse Test\tfailed\t20\t"
                "sonnet\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                "\t\t\t\t\t\t\t\t\t\tmedium\n"
            )
            Path(results_path).write_text(results_content)

            build_index(results_path, db_path)

            # Query with special FTS characters that could cause parse errors
            # (even though they're sanitized, verify graceful handling)
            result = find_similar_attempts('test" AND "query', k=5, db_path=db_path)
            assert result == []
            assert isinstance(result, list)


class TestResultSchema:
    """Verify the schema and content of returned results."""

    def test_result_schema_complete(self) -> None:
        """Full schema validation: only expected fields, correct types."""
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
                "2026-04-01T00:00:00\t1\t0\tUS-500\tSchema Complete Test 1\tpassed\t30\t"
                "opus\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                "\t\t\t\t\t\t\t\t\t\tlarge\n"
                "2026-04-01T00:00:00\t1\t0\tUS-501\tSchema Complete Test 2\tfailed\t5\t"
                "haiku\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                "Root cause\t\t\t\t\t\t\t\t\tError message\tsmall\n"
            )
            Path(results_path).write_text(results_content)

            build_index(results_path, db_path)

            results = find_similar_attempts("Schema", k=5, db_path=db_path)

            assert len(results) > 0
            for result in results:
                # Verify it's a dict with exactly 5 keys
                assert isinstance(result, dict)
                assert len(result) == 5

                # Verify all expected fields are present
                assert "story_id" in result
                assert "model" in result
                assert "outcome" in result
                assert "duration" in result
                assert "cost" in result

                # Verify no other fields are present
                unexpected_keys = set(result.keys()) - {
                    "story_id",
                    "model",
                    "outcome",
                    "duration",
                    "cost",
                }
                assert len(unexpected_keys) == 0, f"Found unexpected fields: {unexpected_keys}"

    def test_multiple_results_all_have_valid_schema(self) -> None:
        """Multiple results all conform to the schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "history.db")
            results_path = os.path.join(tmpdir, "results.tsv")

            lines = [
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\t"
                "cache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\t"
                "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\t"
                "votes_accept\tvotes_reject\tconflict_files\tfailure_root_cause\t"
                "sub_project\tfailed_files\tscope_tag\terror_category\tquota_exceeded\t"
                "quota_source\tworker_id\tconflict_file_count\tphase_timing\t"
                "failure_type\tfailure_message\testimated_complexity"
            ]
            for i in range(4):
                status = "passed" if i % 2 == 0 else "failed"
                model = ["haiku", "sonnet", "opus", "haiku"][i]
                title = f"Multiple Results Test {i}"
                lines.append(
                    f"2026-04-01T00:00:00\t1\t0\tUS-60{i}\t{title}\t{status}\t{5 * (i + 1)}\t"
                    f"{model}\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                    f"\t\t\t\t\t\t\t\t\t\tsmall"
                )
            Path(results_path).write_text("\n".join(lines))

            build_index(results_path, db_path)

            results = find_similar_attempts("Multiple", k=10, db_path=db_path)

            # Should have multiple results
            assert len(results) > 1

            # All results should conform to schema
            for idx, result in enumerate(results):
                assert set(result.keys()) == {
                    "story_id",
                    "model",
                    "outcome",
                    "duration",
                    "cost",
                }, f"Result {idx} has invalid schema: {set(result.keys())}"

    def test_result_limit_respected(self) -> None:
        """Result count respects the k parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "history.db")
            results_path = os.path.join(tmpdir, "results.tsv")

            # Create multiple results
            lines = [
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\t"
                "cache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\t"
                "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\t"
                "votes_accept\tvotes_reject\tconflict_files\tfailure_root_cause\t"
                "sub_project\tfailed_files\tscope_tag\terror_category\tquota_exceeded\t"
                "quota_source\tworker_id\tconflict_file_count\tphase_timing\t"
                "failure_type\tfailure_message\testimated_complexity"
            ]
            for i in range(10):
                lines.append(
                    f"2026-04-01T00:00:00\t1\t0\tUS-{700 + i}\tLimit Test {i}\tpassed\t5\t"
                    f"haiku\t0\tabc123\trun1\t\t\t\t\t\t\t\t\t\t\t\t\t"
                    f"\t\t\t\t\t\t\t\t\t\tsmall"
                )
            Path(results_path).write_text("\n".join(lines))

            build_index(results_path, db_path)

            results = find_similar_attempts("Limit", k=3, db_path=db_path)

            # Should return at most k results
            assert len(results) <= 3
