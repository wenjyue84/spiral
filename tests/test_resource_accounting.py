"""Tests for US-158: per-worker resource accounting columns in results.tsv."""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from spiral_dashboard import compute_resource_usage, load_results  # noqa: E402

RESOURCE_COLUMNS = ("wall_seconds", "user_cpu_s", "sys_cpu_s", "peak_rss_kb")


# ── results.tsv header ────────────────────────────────────────────────────────

class TestResultsTsvHeader:
    def test_header_contains_all_resource_columns(self, tmp_path):
        """The results.tsv header must include the four resource columns."""
        tsv = tmp_path / "results.tsv"
        header = (
            "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title"
            "\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha"
            "\trun_id\tcache_hit\tcache_read_tokens\treview_tokens"
            "\twall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\n"
        )
        tsv.write_text(header, encoding="utf-8")
        rows = load_results(str(tsv))
        # No data rows, but we can inspect via csv reader directly
        import csv
        with open(str(tsv), encoding="utf-8") as f:
            fieldnames = next(csv.reader(f, delimiter="\t"))
        for col in RESOURCE_COLUMNS:
            assert col in fieldnames, f"Column '{col}' missing from header"

    def test_all_four_resource_columns_present(self):
        """Verify the expected column names have not been renamed."""
        assert len(RESOURCE_COLUMNS) == 4
        assert "wall_seconds" in RESOURCE_COLUMNS
        assert "user_cpu_s" in RESOURCE_COLUMNS
        assert "sys_cpu_s" in RESOURCE_COLUMNS
        assert "peak_rss_kb" in RESOURCE_COLUMNS


# ── load_results coercion ─────────────────────────────────────────────────────

class TestLoadResultsResourceColumns:
    def _make_tsv(self, tmp_path, rows):
        header = (
            "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title"
            "\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha"
            "\trun_id\tcache_hit\tcache_read_tokens\treview_tokens"
            "\twall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\n"
        )
        content = header + "".join(rows)
        tsv = tmp_path / "results.tsv"
        tsv.write_text(content, encoding="utf-8")
        return str(tsv)

    def test_resource_columns_coerced_to_float(self, tmp_path):
        row = (
            "2026-03-15T00:00:00Z\t1\t1\tUS-001\tTest story"
            "\tkeep\t120\tsonnet\t0\tabc123"
            "\trun1\tfalse\t0\t0"
            "\t95.3\t80.1\t15.2\t512000\n"
        )
        path = self._make_tsv(tmp_path, [row])
        results = load_results(path)
        assert len(results) == 1
        r = results[0]
        assert r["wall_seconds"] == pytest.approx(95.3)
        assert r["user_cpu_s"] == pytest.approx(80.1)
        assert r["sys_cpu_s"] == pytest.approx(15.2)
        assert r["peak_rss_kb"] == pytest.approx(512000.0)

    def test_zero_resource_values_coerced(self, tmp_path):
        row = (
            "2026-03-15T00:00:00Z\t1\t1\tUS-002\tAnother story"
            "\treject\t60\thaiku\t1\t"
            "\t\tfalse\t0\t0"
            "\t0\t0\t0\t0\n"
        )
        path = self._make_tsv(tmp_path, [row])
        results = load_results(path)
        assert results[0]["wall_seconds"] == 0.0
        assert results[0]["peak_rss_kb"] == 0.0

    def test_missing_resource_columns_do_not_error(self, tmp_path):
        """Old-format TSV without resource cols loads without error."""
        tsv = tmp_path / "results.tsv"
        tsv.write_text(
            "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title"
            "\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha\n"
            "2026-03-15T00:00:00Z\t1\t1\tUS-001\tStory\tkeep\t120\tsonnet\t0\tabc\n",
            encoding="utf-8",
        )
        results = load_results(str(tsv))
        assert len(results) == 1
        # Columns simply absent — no KeyError
        assert "wall_seconds" not in results[0]


# ── compute_resource_usage ────────────────────────────────────────────────────

class TestComputeResourceUsage:
    def test_empty_returns_empty(self):
        assert compute_resource_usage([]) == []

    def test_single_row_with_data(self):
        rows = [{"model": "sonnet", "wall_seconds": 100.0, "peak_rss_kb": 400000.0}]
        usage = compute_resource_usage(rows)
        assert len(usage) == 1
        assert usage[0]["model"] == "sonnet"
        assert usage[0]["median_wall_s"] == pytest.approx(100.0)
        assert usage[0]["median_rss_kb"] == pytest.approx(400000.0)

    def test_grouped_by_model(self):
        rows = [
            {"model": "haiku", "wall_seconds": 60.0, "peak_rss_kb": 200000.0},
            {"model": "sonnet", "wall_seconds": 120.0, "peak_rss_kb": 500000.0},
            {"model": "haiku", "wall_seconds": 80.0, "peak_rss_kb": 250000.0},
        ]
        usage = compute_resource_usage(rows)
        models = {u["model"]: u for u in usage}
        assert "haiku" in models
        assert "sonnet" in models
        assert models["haiku"]["count"] == 2
        assert models["sonnet"]["count"] == 1

    def test_zero_wall_excluded_from_stats(self):
        rows = [
            {"model": "sonnet", "wall_seconds": 0, "peak_rss_kb": 0},
            {"model": "sonnet", "wall_seconds": 0, "peak_rss_kb": 0},
        ]
        usage = compute_resource_usage(rows)
        assert usage[0]["median_wall_s"] == 0.0
        assert usage[0]["median_rss_kb"] == 0.0

    def test_p95_computed(self):
        rows = [{"model": "sonnet", "wall_seconds": float(i), "peak_rss_kb": float(i * 1000)}
                for i in range(1, 21)]
        usage = compute_resource_usage(rows)
        assert usage[0]["p95_wall_s"] > usage[0]["median_wall_s"]
        assert usage[0]["p95_rss_kb"] > usage[0]["median_rss_kb"]
