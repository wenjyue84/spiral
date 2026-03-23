"""
Tests for lib/ac_assertion_extractor.py — Phase V AC Assertion Extractor

Tests the extraction logic that parses acceptance criteria into executable assertions.
"""

import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from ac_assertion_extractor import (
    Assertion,
    extract_assertions,
    extract_exit_code,
    extract_file_exists,
    extract_json_field,
    extract_log_grep,
    extract_test_command,
)


class TestExtractExitCode:
    """Tests for extract_exit_code() pattern matching."""

    def test_exits_with_zero(self) -> None:
        """Extract 'exits with 0' pattern."""
        ac = "command exits with 0"
        result = extract_exit_code(ac)
        assert result is not None
        assert result.type == "exit_code"
        assert result.expected == "0"
        assert result.extracted is True

    def test_exits_zero(self) -> None:
        """Extract 'exits 0' pattern."""
        ac = "exits 0 on success"
        result = extract_exit_code(ac)
        assert result is not None
        assert result.expected == "0"

    def test_exit_code_zero(self) -> None:
        """Extract 'exit code 0' pattern."""
        ac = "exit code 0 is returned"
        result = extract_exit_code(ac)
        assert result is not None
        assert result.expected == "0"

    def test_exit_code_nonzero(self) -> None:
        """Extract 'exit code 1' pattern."""
        ac = "exits with 1 on error"
        result = extract_exit_code(ac)
        assert result is not None
        assert result.expected == "1"

    def test_exits_non_zero(self) -> None:
        """Extract 'exits non-zero' pattern."""
        ac = "exits with non-zero on failure"
        result = extract_exit_code(ac)
        assert result is not None
        assert result.type == "exit_code"
        assert result.expected == "true"

    def test_exits_non_zero_no_with(self) -> None:
        """Extract 'exits non-zero' without 'with'."""
        ac = "exits non-zero status"
        result = extract_exit_code(ac)
        assert result is not None
        assert result.extracted is True

    def test_no_match(self) -> None:
        """Return None for non-exit-code AC."""
        ac = "returns a JSON response"
        result = extract_exit_code(ac)
        assert result is None


class TestExtractFileExists:
    """Tests for extract_file_exists() pattern matching."""

    def test_file_to_create(self) -> None:
        """Extract 'File to create: X' pattern."""
        ac = "File to create: output.json"
        result = extract_file_exists(ac)
        assert result is not None
        assert result.type == "file_exists"
        assert "output.json" in result.command

    def test_file_to_create_with_path(self) -> None:
        """Extract file with directory path."""
        ac = "File to create: .spiral/ac_checks/US-1004.json"
        result = extract_file_exists(ac)
        assert result is not None
        assert ".spiral/ac_checks/US-1004.json" in result.command

    def test_creates_file(self) -> None:
        """Extract 'creates file X' pattern."""
        ac = "creates file config.json"
        result = extract_file_exists(ac)
        assert result is not None
        assert "config.json" in result.command

    def test_file_is_created(self) -> None:
        """Extract 'file X is created' pattern."""
        ac = "file report.html is created"
        result = extract_file_exists(ac)
        assert result is not None
        assert "report.html" in result.command

    def test_file_should_exist(self) -> None:
        """Extract 'file X should exist' pattern."""
        ac = "file README.md should exist"
        result = extract_file_exists(ac)
        assert result is not None
        assert "README.md" in result.command

    def test_no_match(self) -> None:
        """Return None for non-file-creation AC."""
        ac = "processes the input data"
        result = extract_file_exists(ac)
        assert result is None


class TestExtractTestCommand:
    """Tests for extract_test_command() pattern matching."""

    def test_uv_run_pytest(self) -> None:
        """Extract 'uv run pytest X' pattern."""
        ac = "uv run pytest tests/test_ac_assertion_extractor.py -v"
        result = extract_test_command(ac)
        assert result is not None
        assert result.type == "test_command"
        assert "pytest" in result.command
        assert "tests/test_ac_assertion_extractor.py" in result.command

    def test_pytest_only(self) -> None:
        """Extract 'pytest X' pattern."""
        ac = "pytest tests/ --tb=short passes"
        result = extract_test_command(ac)
        assert result is not None
        assert "pytest" in result.command

    def test_vitest(self) -> None:
        """Extract 'vitest X' pattern."""
        ac = "vitest run src/components/ should pass"
        result = extract_test_command(ac)
        assert result is not None
        assert "vitest" in result.command

    def test_jest(self) -> None:
        """Extract 'jest X' pattern."""
        ac = "jest src/utils/ succeeds"
        result = extract_test_command(ac)
        assert result is not None
        assert "jest" in result.command

    def test_bats(self) -> None:
        """Extract 'bats X' pattern."""
        ac = "bats tests/integration.bats passes"
        result = extract_test_command(ac)
        assert result is not None
        assert "bats" in result.command

    def test_run_tests_in(self) -> None:
        """Extract 'run tests in X' pattern."""
        ac = "run tests in tests/unit/"
        result = extract_test_command(ac)
        assert result is not None
        assert "pytest" in result.command

    def test_tests_pass_in(self) -> None:
        """Extract 'tests pass in X' pattern."""
        ac = "tests pass in tests/integration/"
        result = extract_test_command(ac)
        assert result is not None
        assert "pytest" in result.command

    def test_no_match(self) -> None:
        """Return None for non-test AC."""
        ac = "outputs the result"
        result = extract_test_command(ac)
        assert result is None


class TestExtractJsonField:
    """Tests for extract_json_field() pattern matching."""

    def test_contains_field(self) -> None:
        """Extract 'contains field Y' pattern."""
        ac = "contains field status"
        result = extract_json_field(ac)
        assert result is not None
        assert result.type == "json_field"
        assert "status" in result.command

    def test_json_contains_field(self) -> None:
        """Extract 'JSON contains field Y' pattern."""
        ac = "JSON contains field error_code"
        result = extract_json_field(ac)
        assert result is not None
        assert "error_code" in result.command

    def test_contains_the_field(self) -> None:
        """Extract 'contains the field Y' pattern."""
        ac = "contains the field user_id"
        result = extract_json_field(ac)
        assert result is not None
        assert "user_id" in result.command

    def test_returns_field_in_json(self) -> None:
        """Extract 'returns field X in JSON' pattern."""
        ac = "returns field data in JSON"
        result = extract_json_field(ac)
        assert result is not None
        assert "data" in result.command

    def test_returns_the_field_in_json(self) -> None:
        """Extract 'returns the field X in JSON' pattern."""
        ac = "returns the field message in JSON output"
        result = extract_json_field(ac)
        assert result is not None
        assert "message" in result.command

    def test_output_includes(self) -> None:
        """Extract 'output includes X' pattern."""
        ac = "output includes version"
        result = extract_json_field(ac)
        assert result is not None
        assert "version" in result.command

    def test_output_contains(self) -> None:
        """Extract 'output contains X' pattern."""
        ac = "output contains timestamp"
        result = extract_json_field(ac)
        assert result is not None
        assert "timestamp" in result.command

    def test_no_match(self) -> None:
        """Return None for non-JSON AC."""
        ac = "processes the input"
        result = extract_json_field(ac)
        assert result is None


class TestExtractLogGrep:
    """Tests for extract_log_grep() pattern matching."""

    def test_log_entry_matching(self) -> None:
        """Extract 'log entry matching X' pattern."""
        ac = "log entry matching 'error occurred'"
        result = extract_log_grep(ac)
        assert result is not None
        assert result.type == "log_grep"
        assert "error occurred" in result.command

    def test_log_entries_matching(self) -> None:
        """Extract 'log entries matching X' pattern."""
        ac = "log entries matching success"
        result = extract_log_grep(ac)
        assert result is not None
        assert "success" in result.command

    def test_logs_contain(self) -> None:
        """Extract 'logs contain X' pattern."""
        ac = "logs contain warning message"
        result = extract_log_grep(ac)
        assert result is not None
        assert "warning" in result.command

    def test_output_contains(self) -> None:
        """Extract 'output contains X' pattern."""
        ac = "output contains 'processing complete'"
        result = extract_log_grep(ac)
        assert result is not None
        assert "processing complete" in result.command

    def test_output_includes(self) -> None:
        """Extract 'output includes X' pattern."""
        ac = "output includes debug"
        result = extract_log_grep(ac)
        assert result is not None
        assert "debug" in result.command

    def test_prints_message(self) -> None:
        """Extract 'prints X' pattern."""
        ac = "prints success message"
        result = extract_log_grep(ac)
        assert result is not None
        assert "success" in result.command

    def test_prints_error(self) -> None:
        """Extract 'prints error X' pattern."""
        ac = "prints error invalid_config"
        result = extract_log_grep(ac)
        assert result is not None
        assert "invalid_config" in result.command

    def test_error_message_appears(self) -> None:
        """Extract 'error message X appears' pattern."""
        ac = "error message timeout appears"
        result = extract_log_grep(ac)
        assert result is not None
        assert "timeout" in result.command

    def test_error_messages_appear(self) -> None:
        """Extract 'error messages X appear' pattern."""
        ac = "error messages connection appear in logs"
        result = extract_log_grep(ac)
        assert result is not None
        assert "connection" in result.command

    def test_no_match(self) -> None:
        """Return None for non-grep AC."""
        ac = "validates the input"
        result = extract_log_grep(ac)
        assert result is None


class TestExtractAssertions:
    """Tests for extract_assertions() integration."""

    def test_mixed_ac_types(self) -> None:
        """Extract multiple assertion types from realistic story AC."""
        story = {
            "id": "US-1004",
            "title": "Phase V: AC Assertion Extractor",
            "acceptanceCriteria": [
                "uv run pytest tests/test_ac_assertion_extractor.py passes",
                "File to create: .spiral/ac_checks/US-1004.json",
                "exit code 0 on success",
                "contains field story_id",
                "logs contain extraction_metadata",
            ],
        }

        result = extract_assertions(story)

        assert result["story_id"] == "US-1004"
        assert result["extraction_metadata"]["successfully_extracted"] == 5
        assert result["extraction_metadata"]["requires_manual_review"] == 0
        assert len(result["extracted_assertions"]) == 5

        # Verify all types present
        types = {a["type"] for a in result["extracted_assertions"]}
        assert "test_command" in types
        assert "file_exists" in types
        assert "exit_code" in types
        assert "json_field" in types
        assert "log_grep" in types

    def test_unparseable_ac(self) -> None:
        """Tag unparseable AC as manual_review."""
        story = {
            "id": "US-TEST",
            "title": "Test Story",
            "acceptanceCriteria": [
                "uv run pytest tests/ passes",
                "The system integrates smoothly with legacy infrastructure",
                "File to create: output.txt",
            ],
        }

        result = extract_assertions(story)

        assert result["extraction_metadata"]["successfully_extracted"] == 2
        assert result["extraction_metadata"]["requires_manual_review"] == 1
        assert len(result["manual_review"]) == 1
        assert result["manual_review"][0]["raw_ac"] == "The system integrates smoothly with legacy infrastructure"
        assert result["manual_review"][0]["extracted"] is False

    def test_empty_ac_list(self) -> None:
        """Handle story with empty AC list."""
        story = {
            "id": "US-EMPTY",
            "title": "Story with no AC",
            "acceptanceCriteria": [],
        }

        result = extract_assertions(story)

        assert result["total_assertions"] == 0
        assert result["extraction_metadata"]["successfully_extracted"] == 0
        assert result["extraction_metadata"]["requires_manual_review"] == 0

    def test_metadata_timestamp(self) -> None:
        """Verify metadata includes timestamp in ISO format."""
        story = {
            "id": "US-TIMESTAMP",
            "acceptanceCriteria": ["uv run pytest tests/"],
        }

        result = extract_assertions(story)

        timestamp = result["extraction_metadata"]["timestamp"]
        # Should be ISO 8601 format with Z
        assert "T" in timestamp
        assert timestamp.endswith("Z")

    def test_assertion_dataclass_serialization(self) -> None:
        """Verify Assertion objects serialize correctly to dict."""
        assertion = Assertion(
            type="exit_code",
            raw_ac="exits with 0",
            command="exit 0",
            expected="0",
            extracted=True,
        )

        d = asdict(assertion)
        assert d["type"] == "exit_code"
        assert d["extracted"] is True
        assert d["raw_ac"] == "exits with 0"


class TestExtractorPriority:
    """Tests for extraction priority (most specific first)."""

    def test_test_command_extracted_first(self) -> None:
        """Test command patterns matched before generic patterns."""
        # This AC mentions both a test command and a file
        ac = "uv run pytest tests/test_foo.py and creates file output.json"
        story = {
            "id": "US-PRIORITY",
            "acceptanceCriteria": [ac],
        }

        result = extract_assertions(story)

        # Should extract test_command (most specific) first
        assert result["extracted_assertions"][0]["type"] == "test_command"

    def test_file_exists_extracted_before_generic(self) -> None:
        """File existence patterns matched before generic patterns."""
        ac = "File to create: config.json with data"
        story = {
            "id": "US-FILE-PRIORITY",
            "acceptanceCriteria": [ac],
        }

        result = extract_assertions(story)

        assert result["extracted_assertions"][0]["type"] == "file_exists"


class TestEdgeCases:
    """Tests for edge cases and special conditions."""

    def test_ac_with_special_characters(self) -> None:
        """Handle AC text with quotes and special chars."""
        ac = 'File to create: "output[1].json"'
        result = extract_file_exists(ac)
        # Should still extract, might include quotes
        assert result is not None

    def test_case_insensitive_matching(self) -> None:
        """Extraction should be case-insensitive."""
        ac_uppercase = "EXITS WITH 0"
        ac_lowercase = "exits with 0"
        ac_mixed = "Exits With 0"

        result_upper = extract_exit_code(ac_uppercase)
        result_lower = extract_exit_code(ac_lowercase)
        result_mixed = extract_exit_code(ac_mixed)

        assert result_upper is not None
        assert result_lower is not None
        assert result_mixed is not None

    def test_missing_acceptance_criteria_field(self) -> None:
        """Handle story without acceptanceCriteria field."""
        story = {
            "id": "US-NO-AC",
            "title": "No AC field",
        }

        result = extract_assertions(story)

        assert result["total_assertions"] == 0
        assert result["extraction_metadata"]["total_ac_items"] == 0

    def test_blank_ac_items_ignored(self) -> None:
        """Ignore empty string AC items."""
        story = {
            "id": "US-BLANK",
            "acceptanceCriteria": [
                "uv run pytest tests/",
                "",
                "   ",
                "File to create: output.txt",
            ],
        }

        result = extract_assertions(story)

        assert result["extraction_metadata"]["total_ac_items"] == 2
        assert result["extraction_metadata"]["successfully_extracted"] == 2
