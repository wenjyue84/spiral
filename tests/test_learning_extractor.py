"""Tests for lib/learning_extractor.py — Phase L Learning Extractor.

Tests the extraction logic that reads results.tsv and appends to learning.md.
Run with: uv run pytest tests/test_learning_extractor.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from learning_extractor import (
    _ensure_learning_md,
    _get_existing_story_ids,
    extract_patterns,
)


class TestExtractSuccessfulPatterns:
    """Tests for extract_patterns() with successful stories."""

    def test_extract_successful_patterns(self, tmp_path: Path) -> None:
        """Extract patterns from stories with retry_num == 0."""
        results_tsv = tmp_path / "results.tsv"
        learning_md = tmp_path / "learning.md"

        # Create test results.tsv with some zero-retry stories
        tsv_content = (
            "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\t"
            "status\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\t"
            "cache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\t"
            "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\n"
            "2026-05-18T10:00:00Z\t1\t1\tUS-1001\tFeature A\t"
            "pass\t120\thaiku\t0\tabc123\trun1\t"
            "true\t1000\t500\t0\t0\t0\t0\t0\n"
            "2026-05-18T10:01:00Z\t1\t2\tUS-1002\tFeature B\t"
            "pass\t150\tsonnet\t0\tabc123\trun1\t"
            "true\t1000\t500\t0\t0\t0\t0\t0\n"
            "2026-05-18T10:02:00Z\t1\t3\tUS-1003\tFeature C\t"
            "reject\t100\thaiku\t1\tabc123\trun1\t"
            "false\t0\t0\t0\t0\t0\t0\t0\n"
        )
        results_tsv.write_text(tsv_content, encoding="utf-8")

        count = extract_patterns(results_tsv, learning_md)

        assert count == 2, f"Expected 2 patterns, got {count}"
        assert learning_md.exists()
        content = learning_md.read_text(encoding="utf-8")
        assert "US-1001" in content
        assert "US-1002" in content
        assert "US-1003" not in content  # retry_num != 0

    def test_deduplication(self, tmp_path: Path) -> None:
        """Test that duplicate story_ids are skipped."""
        results_tsv = tmp_path / "results.tsv"
        learning_md = tmp_path / "learning.md"

        # Create learning.md with one existing entry
        learning_md.parent.mkdir(parents=True, exist_ok=True)
        learning_md.write_text(
            "# Learning Patterns\n\n"
            "## Successful Patterns\n\n"
            "- story_id: US-1001, model_used: haiku, title: Feature A\n\n"
            "## Failure Recovery\n\n"
            "## Scope Reduction Tips\n\n",
            encoding="utf-8",
        )

        # Create results.tsv with US-1001 (duplicate) and US-1002 (new)
        tsv_content = (
            "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\t"
            "status\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\t"
            "cache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\t"
            "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\n"
            "2026-05-18T10:00:00Z\t1\t1\tUS-1001\tFeature A\t"
            "pass\t120\thaiku\t0\tabc123\trun1\t"
            "true\t1000\t500\t0\t0\t0\t0\t0\n"
            "2026-05-18T10:01:00Z\t1\t2\tUS-1002\tFeature B\t"
            "pass\t150\tsonnet\t0\tabc123\trun1\t"
            "true\t1000\t500\t0\t0\t0\t0\t0\n"
        )
        results_tsv.write_text(tsv_content, encoding="utf-8")

        count = extract_patterns(results_tsv, learning_md)

        assert count == 1, f"Expected 1 new pattern (US-1002), got {count}"
        content = learning_md.read_text(encoding="utf-8")
        assert "US-1002" in content

    def test_learning_md_sections(self, tmp_path: Path) -> None:
        """Test that learning.md is created with three sections."""
        results_tsv = tmp_path / "results.tsv"
        learning_md = tmp_path / "learning.md"

        # Create minimal results.tsv
        tsv_content = (
            "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\t"
            "status\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\t"
            "cache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\t"
            "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\n"
        )
        results_tsv.write_text(tsv_content, encoding="utf-8")

        extract_patterns(results_tsv, learning_md)

        assert learning_md.exists()
        content = learning_md.read_text(encoding="utf-8")
        assert "## Successful Patterns" in content
        assert "## Failure Recovery" in content
        assert "## Scope Reduction Tips" in content

    def test_missing_results_tsv(self, tmp_path: Path) -> None:
        """Test handling of missing results.tsv."""
        results_tsv = tmp_path / "results.tsv"
        learning_md = tmp_path / "learning.md"

        count = extract_patterns(results_tsv, learning_md)

        assert count == 0
        # learning.md should still be created
        assert learning_md.exists()


class TestEnsureLearningMd:
    """Tests for _ensure_learning_md()."""

    def test_create_from_template(self, tmp_path: Path) -> None:
        """Create learning.md from template if it doesn't exist."""
        learning_md = tmp_path / "learning.md"
        assert not learning_md.exists()

        _ensure_learning_md(learning_md)

        assert learning_md.exists()
        content = learning_md.read_text(encoding="utf-8")
        assert "## Successful Patterns" in content
        assert "## Failure Recovery" in content
        assert "## Scope Reduction Tips" in content

    def test_preserve_existing(self, tmp_path: Path) -> None:
        """Preserve existing learning.md if it exists."""
        learning_md = tmp_path / "learning.md"
        original_content = "# Custom Content\n\nSome custom text."
        learning_md.write_text(original_content, encoding="utf-8")

        _ensure_learning_md(learning_md)

        # Should not overwrite
        assert learning_md.read_text(encoding="utf-8") == original_content


class TestGetExistingStoryIds:
    """Tests for _get_existing_story_ids()."""

    def test_extract_story_ids(self, tmp_path: Path) -> None:
        """Extract story IDs from learning.md."""
        learning_md = tmp_path / "learning.md"
        learning_md.write_text(
            "# Learning\n\n"
            "- story_id: US-1001, model_used: haiku\n"
            "- story_id: US-1002, model_used: sonnet\n"
            "- story_id: US-1003, model_used: opus\n",
            encoding="utf-8",
        )

        ids = _get_existing_story_ids(learning_md)

        assert ids == {"US-1001", "US-1002", "US-1003"}

    def test_missing_file(self, tmp_path: Path) -> None:
        """Return empty set for missing learning.md."""
        learning_md = tmp_path / "learning.md"

        ids = _get_existing_story_ids(learning_md)

        assert ids == set()
