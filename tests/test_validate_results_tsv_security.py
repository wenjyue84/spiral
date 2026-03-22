#!/usr/bin/env python3
"""
Security tests for lib/spiral/validate_results_tsv.py (US-754).

Validates that the validator handles adversarial inputs:
  - Path-traversal story_ids
  - Binary/null-byte content
  - Oversized fields
  - Empty TSVs

All tests verify:
  1. No exception raised (returns structured dict)
  2. No absolute filesystem paths leaked in error messages
"""

import csv
import json
import os
import re
import tempfile
from pathlib import Path

import pytest

from lib.spiral.validate_results_tsv import validate


class TestPathTraversal:
    """AC1: Handle path-traversal story_ids safely."""

    @pytest.mark.parametrize(
        "story_id",
        [
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            "../../../../../../../../etc/passwd",
            "../../../secrets.txt",
        ],
    )
    def test_path_traversal_story_id(self, story_id: str) -> None:
        """validate() handles path-traversal story_id safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = os.path.join(tmpdir, "results.tsv")
            prd_path = os.path.join(tmpdir, "prd.json")

            # Write a minimal TSV with path-traversal story_id
            with open(tsv_path, "w", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "story_id",
                        "iteration",
                        "attempt",
                        "token_count",
                        "phase_duration_ms",
                        "model",
                    ],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "story_id": story_id,
                        "iteration": "1",
                        "attempt": "1",
                        "token_count": "1000",
                        "phase_duration_ms": "5000",
                        "model": "haiku",
                    }
                )

            # Write minimal prd.json
            with open(prd_path, "w", encoding="utf-8") as f:
                json.dump({"userStories": []}, f)

            # Validate should not raise, should return dict
            result = validate(tsv_path, prd_path)

            # AC1: Must be a dict with 'errors' key
            assert isinstance(result, dict)
            assert "errors" in result
            assert isinstance(result["errors"], list)

            # AC3: No error string contains absolute filesystem path
            all_errors = " ".join(result["errors"])
            assert not re.search(r"^[A-Za-z]:\\", all_errors), f"Error contains Windows absolute path: {all_errors}"
            assert not re.search(r"^/", all_errors), f"Error contains POSIX absolute path: {all_errors}"


class TestBinaryContent:
    """AC2: Handle binary/null-byte content safely."""

    def test_null_byte_in_field(self) -> None:
        """validate() handles null-byte in TSV field safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = os.path.join(tmpdir, "results.tsv")
            prd_path = os.path.join(tmpdir, "prd.json")

            # Write TSV with null byte in a field
            with open(tsv_path, "wb") as f:
                f.write(b"story_id\titeration\tattempt\ttoken_count\tphase_duration_ms\tmodel\n")
                f.write(b"US-123\x001\x001\x001000\x005000\x00haiku\n")

            # Write minimal prd.json
            with open(prd_path, "w", encoding="utf-8") as f:
                json.dump({"userStories": [{"id": "US-123"}]}, f)

            # Validate should not raise
            result = validate(tsv_path, prd_path)

            # AC2: Must return dict with 'errors' key
            assert isinstance(result, dict)
            assert "errors" in result

            # AC3: No absolute paths in errors
            all_errors = " ".join(result["errors"])
            assert not re.search(r"^[A-Za-z]:\\", all_errors)
            assert not re.search(r"^/", all_errors)

    def test_binary_garbage_in_field(self) -> None:
        """validate() handles random binary data in TSV field safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = os.path.join(tmpdir, "results.tsv")
            prd_path = os.path.join(tmpdir, "prd.json")

            # Write TSV with random binary garbage
            with open(tsv_path, "wb") as f:
                f.write(b"story_id\titeration\tattempt\ttoken_count\tphase_duration_ms\tmodel\n")
                f.write(b"US-123\t1\t1\t\xff\xfe\xfd\t5000\thaiku\n")

            # Write minimal prd.json
            with open(prd_path, "w", encoding="utf-8") as f:
                json.dump({"userStories": [{"id": "US-123"}]}, f)

            # Validate should not raise
            result = validate(tsv_path, prd_path)

            # AC2: Must return dict, not raise exception
            assert isinstance(result, dict)
            assert "errors" in result

            # AC3: No absolute paths in errors
            all_errors = " ".join(result["errors"])
            assert not re.search(r"^[A-Za-z]:\\", all_errors)
            assert not re.search(r"^/", all_errors)


class TestOversizedFields:
    """AC2 variant: Handle oversized fields (10,000+ chars) safely."""

    def test_oversized_field_10k_chars(self) -> None:
        """validate() handles 10,000+ char field safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = os.path.join(tmpdir, "results.tsv")
            prd_path = os.path.join(tmpdir, "prd.json")

            # Create oversized story_id (10,000 chars)
            oversized_id = "A" * 10000

            # Write TSV with oversized field
            with open(tsv_path, "w", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "story_id",
                        "iteration",
                        "attempt",
                        "token_count",
                        "phase_duration_ms",
                        "model",
                    ],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "story_id": oversized_id,
                        "iteration": "1",
                        "attempt": "1",
                        "token_count": "1000",
                        "phase_duration_ms": "5000",
                        "model": "haiku",
                    }
                )

            # Write minimal prd.json
            with open(prd_path, "w", encoding="utf-8") as f:
                json.dump({"userStories": []}, f)

            # Validate should not raise
            result = validate(tsv_path, prd_path)

            # AC2: Must return dict, not raise exception
            assert isinstance(result, dict)
            assert "errors" in result

            # AC3: No absolute paths in errors
            all_errors = " ".join(result["errors"])
            assert not re.search(r"^[A-Za-z]:\\", all_errors)
            assert not re.search(r"^/", all_errors)


class TestEmptyAndMalformed:
    """AC2 variant: Handle empty TSV and malformed cases safely."""

    def test_empty_tsv(self) -> None:
        """validate() handles empty TSV safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = os.path.join(tmpdir, "results.tsv")
            prd_path = os.path.join(tmpdir, "prd.json")

            # Write empty TSV (no headers)
            Path(tsv_path).touch()

            # Write minimal prd.json
            with open(prd_path, "w", encoding="utf-8") as f:
                json.dump({"userStories": []}, f)

            # Validate should not raise
            result = validate(tsv_path, prd_path)

            # AC1/AC2: Must return dict, not raise exception
            assert isinstance(result, dict)
            assert "errors" in result

            # AC3: No absolute paths in errors
            all_errors = " ".join(result["errors"])
            assert not re.search(r"^[A-Za-z]:\\", all_errors)
            assert not re.search(r"^/", all_errors)

    def test_malformed_json_in_prd(self) -> None:
        """validate() handles malformed prd.json gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = os.path.join(tmpdir, "results.tsv")
            prd_path = os.path.join(tmpdir, "prd.json")

            # Write valid TSV
            with open(tsv_path, "w", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "story_id",
                        "iteration",
                        "attempt",
                        "token_count",
                        "phase_duration_ms",
                        "model",
                    ],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "story_id": "US-123",
                        "iteration": "1",
                        "attempt": "1",
                        "token_count": "1000",
                        "phase_duration_ms": "5000",
                        "model": "haiku",
                    }
                )

            # Write malformed JSON
            with open(prd_path, "w", encoding="utf-8") as f:
                f.write("{invalid json}")

            # Validate should not raise
            result = validate(tsv_path, prd_path)

            # AC1/AC2: Must return dict, not raise exception
            assert isinstance(result, dict)
            assert "errors" in result

            # AC3: No absolute paths in warnings/errors
            all_errors = " ".join(result["errors"] + result.get("warnings", []))
            assert not re.search(r"^[A-Za-z]:\\", all_errors)
            assert not re.search(r"^/", all_errors)


class TestNoPathLeakage:
    """AC3: Comprehensive test that no absolute paths leak in error messages."""

    def test_no_absolute_paths_in_all_errors(self) -> None:
        """All error messages must not contain absolute filesystem paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = os.path.join(tmpdir, "results.tsv")
            prd_path = os.path.join(tmpdir, "prd.json")

            # Write a TSV with various issues
            with open(tsv_path, "w", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "story_id",
                        "iteration",
                        "attempt",
                        "token_count",
                        "phase_duration_ms",
                        "model",
                    ],
                    delimiter="\t",
                )
                writer.writeheader()
                # Row 1: invalid token_count
                writer.writerow(
                    {
                        "story_id": "US-123",
                        "iteration": "1",
                        "attempt": "1",
                        "token_count": "not_a_number",
                        "phase_duration_ms": "5000",
                        "model": "haiku",
                    }
                )
                # Row 2: invalid duration
                writer.writerow(
                    {
                        "story_id": "US-124",
                        "iteration": "1",
                        "attempt": "1",
                        "token_count": "1000",
                        "phase_duration_ms": "invalid",
                        "model": "sonnet",
                    }
                )

            # Write prd.json with some stories
            with open(prd_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "userStories": [
                            {"id": "US-123"},
                            {"id": "US-125"},  # Missing from TSV
                        ]
                    },
                    f,
                )

            # Validate
            result = validate(tsv_path, prd_path)

            # AC3: No error or warning should contain absolute paths
            for error in result["errors"]:
                assert not re.search(r"^[A-Za-z]:\\", error), f"Error contains Windows absolute path: {error}"
                assert not re.search(r"^/", error), f"Error contains POSIX absolute path: {error}"

            for warning in result.get("warnings", []):
                assert not re.search(r"^[A-Za-z]:\\", warning), f"Warning contains Windows absolute path: {warning}"
                assert not re.search(r"^/", warning), f"Warning contains POSIX absolute path: {warning}"


class TestReturnStructure:
    """AC1/AC4: validate() always returns dict with required keys."""

    def test_returns_structured_dict_not_exception(self) -> None:
        """validate() returns dict for all inputs, never raises exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = os.path.join(tmpdir, "results.tsv")
            prd_path = os.path.join(tmpdir, "prd.json")

            # Write minimal valid files
            with open(tsv_path, "w", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "story_id",
                        "iteration",
                        "attempt",
                        "token_count",
                        "phase_duration_ms",
                        "model",
                    ],
                    delimiter="\t",
                )
                writer.writeheader()

            with open(prd_path, "w", encoding="utf-8") as f:
                json.dump({"userStories": []}, f)

            # Validate should return dict
            result = validate(tsv_path, prd_path)

            # AC1: Must return dict with errors key, never raise
            assert isinstance(result, dict)
            assert "errors" in result
            assert "warnings" in result
            assert "passed_checks" in result
            assert "total_rows_checked" in result

            # All values should be lists or ints
            assert isinstance(result["errors"], list)
            assert isinstance(result["warnings"], list)
            assert isinstance(result["passed_checks"], int)
            assert isinstance(result["total_rows_checked"], int)
