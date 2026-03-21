"""Tests for Phase G: Generate Release Notes from Completed Stories.

Validates that phase_g_release_notes.py correctly:
1. Reads stories where passes=true and creates RELEASE_NOTES.md
2. Groups stories by _source with section headers
3. Includes semantic version header from CHANGELOG.md
4. Formats entries as "- US-123: Title (X tokens, Y cost)" with AC bullets
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from lib.phases.phase_g_release_notes import (
    format_story_entry,
    generate_release_notes,
    get_story_metadata,
    load_prd,
)


class TestLoadPrd:
    """Tests for loading prd.json."""

    def test_load_prd_happy_path(self) -> None:
        """Verify load_prd reads prd.json successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            prd_file = tmpdir_path / "prd.json"

            test_prd = {
                "schemaVersion": 1,
                "productName": "Test",
                "userStories": [{"id": "US-001", "title": "Test", "passes": True}],
            }

            with open(prd_file, "w") as f:
                json.dump(test_prd, f)

            result = load_prd(str(prd_file))
            assert result["productName"] == "Test"
            assert len(result["userStories"]) == 1


class TestFormatStoryEntry:
    """Tests for formatting story entries."""

    def test_format_with_tokens_and_cost(self) -> None:
        """Verify story entry includes tokens and cost when available."""
        story = {
            "id": "US-123",
            "title": "Add Feature X",
            "acceptanceCriteria": ["Criterion 1", "Criterion 2"],
        }
        metadata = {"tokens": "1500", "cost": "$0.45"}

        result = format_story_entry(story, metadata)
        assert "US-123: Add Feature X (1500 tokens, $0.45)" in result
        assert "- Criterion 1" in result
        assert "- Criterion 2" in result

    def test_format_with_tokens_only(self) -> None:
        """Verify story entry works with tokens but no cost."""
        story = {"id": "US-456", "title": "Fix Bug Y", "acceptanceCriteria": []}
        metadata = {"tokens": "800", "cost": ""}

        result = format_story_entry(story, metadata)
        assert "US-456: Fix Bug Y (800 tokens)" in result

    def test_format_with_no_metadata(self) -> None:
        """Verify story entry works with no token/cost data."""
        story = {
            "id": "US-789",
            "title": "Refactor Module Z",
            "acceptanceCriteria": ["AC 1"],
        }
        metadata = {"tokens": "", "cost": ""}

        result = format_story_entry(story, metadata)
        assert "US-789: Refactor Module Z" in result
        assert "- AC 1" in result


class TestGetStoryMetadata:
    """Tests for retrieving story metadata from results.tsv."""

    def test_get_metadata_found(self) -> None:
        """Verify metadata retrieval when story is in results.tsv."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            results_file = tmpdir_path / "results.tsv"

            # Create a minimal results.tsv
            header = "\t".join(
                [
                    "timestamp",
                    "spiral_iter",
                    "ralph_iter",
                    "story_id",
                    "story_title",
                    "status",
                    "duration_sec",
                    "model",
                    "retry_num",
                    "commit_sha",
                    "run_id",
                    "cache_read_tokens",
                ]
            )
            row = "\t".join(
                [
                    "2026-01-01T00:00:00Z",
                    "1",
                    "1",
                    "US-001",
                    "Test Story",
                    "pass",
                    "100",
                    "haiku",
                    "0",
                    "abc123",
                    "run1",
                    "2000",
                ]
            )

            with open(results_file, "w") as f:
                f.write(header + "\n")
                f.write(row + "\n")

            metadata = get_story_metadata("US-001", str(results_file))
            assert metadata["tokens"] == "2000"

    def test_get_metadata_not_found(self) -> None:
        """Verify empty metadata when story not in results.tsv."""
        metadata = get_story_metadata("US-999", "nonexistent.tsv")
        assert metadata["tokens"] == ""
        assert metadata["cost"] == ""


class TestGenerateReleaseNotesHappyPath:
    """Tests for successful release notes generation."""

    def test_ac1_creates_release_notes_file(self) -> None:
        """[AC1] Generate RELEASE_NOTES.md from completed stories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create prd.json with some passed stories
            prd_data = {
                "schemaVersion": 1,
                "productName": "Spiral",
                "userStories": [
                    {
                        "id": "US-100",
                        "title": "Feature A",
                        "passes": True,
                        "_source": "seed",
                        "acceptanceCriteria": ["AC A1"],
                    },
                    {
                        "id": "US-101",
                        "title": "Bug Fix B",
                        "passes": False,
                        "_source": "test-fix",
                        "acceptanceCriteria": [],
                    },
                ],
            }

            prd_file = tmpdir_path / "prd.json"
            with open(prd_file, "w") as f:
                json.dump(prd_data, f)

            # Create CHANGELOG.md with version
            changelog_file = tmpdir_path / "CHANGELOG.md"
            with open(changelog_file, "w") as f:
                f.write("# Changelog\n\n## [1.0.0]\n\nInitial release.\n")

            # Create empty results.tsv
            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w") as f:
                f.write(
                    "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\n"
                )

            output_file = tmpdir_path / "RELEASE_NOTES.md"

            # Generate release notes
            content = generate_release_notes(
                str(prd_file),
                str(output_file),
                str(changelog_file),
                str(results_file),
            )

            # Verify file was created
            assert output_file.exists()
            assert content  # Non-empty content
            assert "US-100" in content
            assert "US-101" not in content  # Only passed stories

    def test_ac2_groups_by_source(self) -> None:
        """[AC2] Group stories by _source with section headers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            prd_data = {
                "schemaVersion": 1,
                "productName": "Spiral",
                "userStories": [
                    {
                        "id": "US-200",
                        "title": "Research Story",
                        "passes": True,
                        "_source": "research",
                        "acceptanceCriteria": [],
                    },
                    {
                        "id": "US-201",
                        "title": "Bug Fix",
                        "passes": True,
                        "_source": "test-fix",
                        "acceptanceCriteria": [],
                    },
                    {
                        "id": "US-202",
                        "title": "Core Feature",
                        "passes": True,
                        "_source": "seed",
                        "acceptanceCriteria": [],
                    },
                ],
            }

            prd_file = tmpdir_path / "prd.json"
            with open(prd_file, "w") as f:
                json.dump(prd_data, f)

            changelog_file = tmpdir_path / "CHANGELOG.md"
            with open(changelog_file, "w") as f:
                f.write("## [2.0.0]\n")

            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w") as f:
                f.write(
                    "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\n"
                )

            output_file = tmpdir_path / "RELEASE_NOTES.md"

            content = generate_release_notes(
                str(prd_file),
                str(output_file),
                str(changelog_file),
                str(results_file),
            )

            # Verify grouping by source
            assert "Bug Fixes & Regression Prevention" in content
            assert "Research & Validation" in content
            assert "Core Features" in content

    def test_ac3_includes_version_header(self) -> None:
        """[AC3] Include semantic version header from CHANGELOG.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            prd_data = {
                "schemaVersion": 1,
                "productName": "Spiral",
                "userStories": [
                    {
                        "id": "US-300",
                        "title": "Feature",
                        "passes": True,
                        "_source": "seed",
                        "acceptanceCriteria": [],
                    }
                ],
            }

            prd_file = tmpdir_path / "prd.json"
            with open(prd_file, "w") as f:
                json.dump(prd_data, f)

            changelog_file = tmpdir_path / "CHANGELOG.md"
            with open(changelog_file, "w") as f:
                f.write("## [3.5.2]\n")

            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w") as f:
                f.write(
                    "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\n"
                )

            output_file = tmpdir_path / "RELEASE_NOTES.md"

            content = generate_release_notes(
                str(prd_file),
                str(output_file),
                str(changelog_file),
                str(results_file),
            )

            assert "v3.5.2" in content

    def test_ac4_formats_entries_with_acs(self) -> None:
        """[AC4] Format entries as '- US-123: Title (X tokens, Y cost)' with AC bullets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            prd_data = {
                "schemaVersion": 1,
                "productName": "Spiral",
                "userStories": [
                    {
                        "id": "US-400",
                        "title": "Complex Feature",
                        "passes": True,
                        "_source": "seed",
                        "acceptanceCriteria": ["Must work on desktop", "Must work on mobile"],
                    }
                ],
            }

            prd_file = tmpdir_path / "prd.json"
            with open(prd_file, "w") as f:
                json.dump(prd_data, f)

            changelog_file = tmpdir_path / "CHANGELOG.md"
            with open(changelog_file, "w") as f:
                f.write("## [1.0.0]\n")

            results_file = tmpdir_path / "results.tsv"
            header = "\t".join(
                [
                    "timestamp",
                    "spiral_iter",
                    "ralph_iter",
                    "story_id",
                    "story_title",
                    "status",
                    "duration_sec",
                    "model",
                    "retry_num",
                    "commit_sha",
                    "run_id",
                    "cache_read_tokens",
                ]
            )
            row = "\t".join(
                [
                    "2026-01-01T00:00:00Z",
                    "1",
                    "1",
                    "US-400",
                    "Complex Feature",
                    "pass",
                    "300",
                    "sonnet",
                    "0",
                    "def456",
                    "run2",
                    "5000",
                ]
            )
            with open(results_file, "w") as f:
                f.write(header + "\n")
                f.write(row + "\n")

            output_file = tmpdir_path / "RELEASE_NOTES.md"

            content = generate_release_notes(
                str(prd_file),
                str(output_file),
                str(changelog_file),
                str(results_file),
            )

            # Verify format: "- US-400: Title (5000 tokens)"
            assert "- US-400: Complex Feature (5000 tokens)" in content
            # Verify AC bullets
            assert "- Must work on desktop" in content
            assert "- Must work on mobile" in content


class TestGenerateReleaseNotesErrorHandling:
    """Tests for error handling in release notes generation."""

    def test_missing_prd_file(self) -> None:
        """Verify error when prd.json not found."""
        with pytest.raises(ValueError, match="prd.json not found"):
            generate_release_notes(
                prd_path="nonexistent.json",
                changelog_path="CHANGELOG.md",
            )

    def test_missing_source_defaults_to_seed(self) -> None:
        """Verify stories without _source default to 'seed' category."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            prd_data = {
                "schemaVersion": 1,
                "productName": "Spiral",
                "userStories": [
                    {
                        "id": "US-500",
                        "title": "No Source Story",
                        "passes": True,
                        # No _source field
                        "acceptanceCriteria": [],
                    }
                ],
            }

            prd_file = tmpdir_path / "prd.json"
            with open(prd_file, "w") as f:
                json.dump(prd_data, f)

            changelog_file = tmpdir_path / "CHANGELOG.md"
            with open(changelog_file, "w") as f:
                f.write("## [1.0.0]\n")

            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w") as f:
                f.write(
                    "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\n"
                )

            output_file = tmpdir_path / "RELEASE_NOTES.md"

            content = generate_release_notes(
                str(prd_file),
                str(output_file),
                str(changelog_file),
                str(results_file),
            )

            # Should include story in "Core Features" (seed default)
            assert "US-500" in content
            assert "Core Features" in content

    def test_missing_changelog_uses_fallback_version(self) -> None:
        """Verify fallback to 0.0.0 when CHANGELOG.md missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            prd_data = {
                "schemaVersion": 1,
                "productName": "Spiral",
                "userStories": [
                    {
                        "id": "US-600",
                        "title": "Feature",
                        "passes": True,
                        "_source": "seed",
                        "acceptanceCriteria": [],
                    }
                ],
            }

            prd_file = tmpdir_path / "prd.json"
            with open(prd_file, "w") as f:
                json.dump(prd_data, f)

            results_file = tmpdir_path / "results.tsv"
            with open(results_file, "w") as f:
                f.write(
                    "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\n"
                )

            output_file = tmpdir_path / "RELEASE_NOTES.md"

            content = generate_release_notes(
                str(prd_file),
                str(output_file),
                str(tmpdir_path / "CHANGELOG.md"),  # Non-existent
                str(results_file),
            )

            # Should use fallback version 0.0.0
            assert "v0.0.0" in content
