"""Tests for batch_operations.py"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from lib.batch_operations import (
    execute_batch_operation,
    parse_story_file,
    validate_story_id,
)


class TestValidateStoryId:
    """Tests for validate_story_id()"""

    def test_valid_us_id(self) -> None:
        assert validate_story_id("US-123") is True

    def test_valid_ut_id(self) -> None:
        assert validate_story_id("UT-456") is True

    def test_invalid_prefix(self) -> None:
        assert validate_story_id("XY-123") is False

    def test_invalid_no_number(self) -> None:
        assert validate_story_id("US-ABC") is False

    def test_invalid_format(self) -> None:
        assert validate_story_id("US123") is False


class TestParseStoryFile:
    """Tests for parse_story_file()"""

    def test_parse_valid_file(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            encoding="utf-8",
            suffix=".txt",
        ) as f:
            f.write("US-100\n")
            f.write("US-101\n")
            f.write("UT-200\n")
            f.flush()
            path = Path(f.name)

        try:
            result = parse_story_file(path)
            assert result == ["US-100", "US-101", "UT-200"]
        finally:
            path.unlink()

    def test_parse_with_comments(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            encoding="utf-8",
            suffix=".txt",
        ) as f:
            f.write("# This is a comment\n")
            f.write("US-100\n")
            f.write("# Another comment\n")
            f.write("US-101\n")
            f.flush()
            path = Path(f.name)

        try:
            result = parse_story_file(path)
            assert result == ["US-100", "US-101"]
        finally:
            path.unlink()

    def test_parse_with_blank_lines(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            encoding="utf-8",
            suffix=".txt",
        ) as f:
            f.write("US-100\n")
            f.write("\n")
            f.write("US-101\n")
            f.write("  \n")
            f.write("UT-200\n")
            f.flush()
            path = Path(f.name)

        try:
            result = parse_story_file(path)
            assert result == ["US-100", "US-101", "UT-200"]
        finally:
            path.unlink()

    def test_parse_invalid_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            parse_story_file(Path("/nonexistent/file.txt"))

    def test_parse_invalid_story_ids(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            encoding="utf-8",
            suffix=".txt",
        ) as f:
            f.write("US-100\n")
            f.write("INVALID\n")
            f.write("US-101\n")
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Invalid story IDs"):
                parse_story_file(path)
        finally:
            path.unlink()


class TestExecuteBatchOperation:
    """Tests for execute_batch_operation()"""

    def _create_test_prd(self, stories: list[dict]) -> Path:
        """Helper to create temporary prd.json"""
        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            encoding="utf-8",
            suffix=".json",
        ) as f:
            prd = {"userStories": stories}
            json.dump(prd, f)
            f.flush()
            return Path(f.name)

    def test_mark_done_single_story(self) -> None:
        stories = [
            {"id": "US-100", "passes": False, "title": "Test 1"},
            {"id": "US-101", "passes": True, "title": "Test 2"},
        ]
        prd_path = self._create_test_prd(stories)

        try:
            successful, skipped, summary = execute_batch_operation(
                "mark-done",
                ["US-100"],
                prd_path,
            )
            assert successful == 1
            assert skipped == 0
            assert "1 stories mark done" in summary

            # Verify prd.json was updated
            with open(prd_path, encoding="utf-8") as f:
                updated_prd = json.load(f)
            story = updated_prd["userStories"][0]
            assert story["passes"] is True
            assert "completedAt" in story

        finally:
            prd_path.unlink()

    def test_mark_done_already_done(self) -> None:
        stories = [
            {"id": "US-100", "passes": True, "title": "Test 1"},
        ]
        prd_path = self._create_test_prd(stories)

        try:
            successful, skipped, summary = execute_batch_operation(
                "mark-done",
                ["US-100"],
                prd_path,
            )
            assert successful == 0
            assert skipped == 1
            assert "1 skipped" in summary

        finally:
            prd_path.unlink()

    def test_mark_done_nonexistent_story(self) -> None:
        stories = [
            {"id": "US-100", "passes": False, "title": "Test 1"},
        ]
        prd_path = self._create_test_prd(stories)

        try:
            successful, skipped, summary = execute_batch_operation(
                "mark-done",
                ["US-999"],
                prd_path,
            )
            assert successful == 0
            assert skipped == 1

        finally:
            prd_path.unlink()

    def test_retrigger_story(self) -> None:
        stories = [
            {
                "id": "US-100",
                "passes": False,
                "retry_num": 2,
                "title": "Test 1",
            },
        ]
        prd_path = self._create_test_prd(stories)

        try:
            successful, skipped, summary = execute_batch_operation(
                "retrigger",
                ["US-100"],
                prd_path,
            )
            assert successful == 1
            assert skipped == 0
            assert "1 stories retrigger" in summary

            # Verify prd.json was updated
            with open(prd_path, encoding="utf-8") as f:
                updated_prd = json.load(f)
            story = updated_prd["userStories"][0]
            assert story["passes"] is False
            assert story["retry_num"] == 0

        finally:
            prd_path.unlink()

    def test_retrigger_already_done(self) -> None:
        stories = [
            {"id": "US-100", "passes": True, "title": "Test 1"},
        ]
        prd_path = self._create_test_prd(stories)

        try:
            successful, skipped, summary = execute_batch_operation(
                "retrigger",
                ["US-100"],
                prd_path,
            )
            assert successful == 0
            assert skipped == 1

        finally:
            prd_path.unlink()

    def test_batch_multiple_stories(self) -> None:
        stories = [
            {"id": "US-100", "passes": False, "title": "Test 1"},
            {"id": "US-101", "passes": False, "title": "Test 2"},
            {"id": "US-102", "passes": True, "title": "Test 3"},
        ]
        prd_path = self._create_test_prd(stories)

        try:
            successful, skipped, summary = execute_batch_operation(
                "mark-done",
                ["US-100", "US-101", "US-102"],
                prd_path,
            )
            assert successful == 2
            assert skipped == 1
            assert "2 stories mark done" in summary
            assert "1 skipped" in summary

        finally:
            prd_path.unlink()

    def test_invalid_operation(self) -> None:
        stories = [{"id": "US-100", "passes": False}]
        prd_path = self._create_test_prd(stories)

        try:
            with pytest.raises(ValueError, match="Unknown operation"):
                execute_batch_operation("invalid-op", ["US-100"], prd_path)
        finally:
            prd_path.unlink()

    def test_prd_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            execute_batch_operation(
                "mark-done",
                ["US-100"],
                Path("/nonexistent/prd.json"),
            )
