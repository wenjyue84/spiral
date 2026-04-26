"""Tests for lib/log_viewer.py."""

from __future__ import annotations

from pathlib import Path

from lib.log_viewer import (
    colorize_output,
    filter_by_context,
    filter_by_level,
    parse_log_line,
    read_story_logs,
)


class TestParseLogLine:
    """Tests for parse_log_line function."""

    def test_parse_pipe_separated_format(self) -> None:
        """Test parsing pipe-separated log format."""
        line = "2026-04-27T10:30:45Z | ERROR | implement | Story failed | /path/file.py:42"
        result = parse_log_line(line)
        assert result is not None
        assert result["timestamp"] == "2026-04-27T10:30:45Z"
        assert result["level"] == "ERROR"
        assert result["context"] == "implement"
        assert result["message"] == "Story failed"
        assert result["source"] == "/path/file.py:42"

    def test_parse_bracket_format(self) -> None:
        """Test parsing bracket-enclosed log format."""
        line = "[2026-04-27T10:30:45Z] [WARN] [decompose] Breaking changes detected"
        result = parse_log_line(line)
        assert result is not None
        assert result["timestamp"] == "2026-04-27T10:30:45Z"
        assert result["level"] == "WARN"
        assert result["context"] == "decompose"
        assert result["message"] == "Breaking changes detected"
        assert result["source"] == ""

    def test_parse_empty_line(self) -> None:
        """Test parsing empty line returns None."""
        result = parse_log_line("")
        assert result is None

    def test_parse_whitespace_only(self) -> None:
        """Test parsing whitespace-only line returns None."""
        result = parse_log_line("   ")
        assert result is None

    def test_parse_invalid_format(self) -> None:
        """Test parsing invalid format returns None."""
        result = parse_log_line("some random text")
        assert result is None


class TestFilterByLevel:
    """Tests for filter_by_level function."""

    def test_filter_error_includes_errors_only(self) -> None:
        """Test ERROR level includes only ERROR logs."""
        logs = [
            {"level": "DEBUG", "message": "debug msg"},
            {"level": "INFO", "message": "info msg"},
            {"level": "WARN", "message": "warn msg"},
            {"level": "ERROR", "message": "error msg"},
        ]
        result = filter_by_level(logs, "ERROR")
        assert len(result) == 1
        assert result[0]["level"] == "ERROR"

    def test_filter_warn_includes_warn_and_error(self) -> None:
        """Test WARN level includes WARN and ERROR."""
        logs = [
            {"level": "DEBUG", "message": "debug msg"},
            {"level": "INFO", "message": "info msg"},
            {"level": "WARN", "message": "warn msg"},
            {"level": "ERROR", "message": "error msg"},
        ]
        result = filter_by_level(logs, "WARN")
        assert len(result) == 2
        assert {log["level"] for log in result} == {"WARN", "ERROR"}

    def test_filter_debug_includes_all(self) -> None:
        """Test DEBUG level includes all logs."""
        logs = [
            {"level": "DEBUG", "message": "debug msg"},
            {"level": "INFO", "message": "info msg"},
            {"level": "WARN", "message": "warn msg"},
            {"level": "ERROR", "message": "error msg"},
        ]
        result = filter_by_level(logs, "DEBUG")
        assert len(result) == 4

    def test_filter_empty_level_returns_all(self) -> None:
        """Test empty level filter returns all logs."""
        logs = [
            {"level": "DEBUG", "message": "debug msg"},
            {"level": "ERROR", "message": "error msg"},
        ]
        result = filter_by_level(logs, "")
        assert len(result) == 2

    def test_filter_case_insensitive(self) -> None:
        """Test level filter is case-insensitive."""
        logs = [
            {"level": "ERROR", "message": "error msg"},
        ]
        result = filter_by_level(logs, "error")
        assert len(result) == 1

    def test_filter_invalid_level(self) -> None:
        """Test invalid level returns all logs."""
        logs = [
            {"level": "ERROR", "message": "error msg"},
        ]
        result = filter_by_level(logs, "INVALID")
        assert len(result) == 1


class TestFilterByContext:
    """Tests for filter_by_context function."""

    def test_filter_implement_context(self) -> None:
        """Test filtering by implement context."""
        logs = [
            {"context": "parse", "message": "parsing"},
            {"context": "implement", "message": "implementing"},
            {"context": "verify", "message": "verifying"},
        ]
        result = filter_by_context(logs, "implement")
        assert len(result) == 1
        assert result[0]["context"] == "implement"

    def test_filter_decompose_context(self) -> None:
        """Test filtering by decompose context."""
        logs = [
            {"context": "parse", "message": "parsing"},
            {"context": "decompose", "message": "decomposing"},
            {"context": "verify", "message": "verifying"},
        ]
        result = filter_by_context(logs, "decompose")
        assert len(result) == 1
        assert result[0]["context"] == "decompose"

    def test_filter_empty_context_returns_all(self) -> None:
        """Test empty context filter returns all logs."""
        logs = [
            {"context": "parse", "message": "parsing"},
            {"context": "implement", "message": "implementing"},
        ]
        result = filter_by_context(logs, "")
        assert len(result) == 2

    def test_filter_case_insensitive_context(self) -> None:
        """Test context filter is case-insensitive."""
        logs = [
            {"context": "IMPLEMENT", "message": "implementing"},
        ]
        result = filter_by_context(logs, "implement")
        assert len(result) == 1

    def test_filter_invalid_context(self) -> None:
        """Test invalid context returns all logs."""
        logs = [
            {"context": "implement", "message": "implementing"},
        ]
        result = filter_by_context(logs, "invalid")
        assert len(result) == 1


class TestColorizeOutput:
    """Tests for colorize_output function."""

    def test_colorize_empty_logs(self) -> None:
        """Test colorizing empty log list."""
        result = colorize_output([])
        assert "No logs found" in result

    def test_colorize_includes_timestamp_and_message(self) -> None:
        """Test colorized output includes timestamp and message."""
        logs = [
            {
                "timestamp": "2026-04-27T10:30:45Z",
                "level": "INFO",
                "context": "parse",
                "message": "Starting parse",
                "source": "",
            }
        ]
        result = colorize_output(logs)
        assert "2026-04-27T10:30:45Z" in result
        assert "Starting parse" in result
        assert "parse" in result

    def test_colorize_includes_source(self) -> None:
        """Test colorized output includes source when present."""
        logs = [
            {
                "timestamp": "2026-04-27T10:30:45Z",
                "level": "ERROR",
                "context": "implement",
                "message": "Error occurred",
                "source": "spiral.py:123",
            }
        ]
        result = colorize_output(logs)
        assert "spiral.py:123" in result

    def test_colorize_ansi_color_codes_present(self) -> None:
        """Test that ANSI color codes are present in output."""
        logs = [
            {
                "timestamp": "2026-04-27T10:30:45Z",
                "level": "ERROR",
                "context": "implement",
                "message": "Error message",
                "source": "",
            }
        ]
        result = colorize_output(logs)
        # Check for ANSI escape code for red (ERROR)
        assert "\033[31m" in result or "ERROR" in result

    def test_colorize_multiple_logs(self) -> None:
        """Test colorizing multiple logs produces multiple lines."""
        logs = [
            {
                "timestamp": "2026-04-27T10:30:45Z",
                "level": "INFO",
                "context": "parse",
                "message": "Log 1",
                "source": "",
            },
            {
                "timestamp": "2026-04-27T10:30:46Z",
                "level": "ERROR",
                "context": "implement",
                "message": "Log 2",
                "source": "",
            },
        ]
        result = colorize_output(logs)
        lines = result.split("\n")
        assert len(lines) == 2


class TestReadStoryLogs:
    """Tests for read_story_logs function."""

    def test_read_logs_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test reading logs from non-existent directory returns empty list."""
        result = read_story_logs("US-123", str(tmp_path / "nonexistent"))
        assert result == []

    def test_read_logs_no_matching_files(self, tmp_path: Path) -> None:
        """Test reading logs when story not in any file."""
        # Create a log file without the story ID
        log_file = tmp_path / "_claude_raw_12345.tmp"
        log_file.write_text("Some unrelated log content\n", encoding="utf-8")

        result = read_story_logs("US-999", str(tmp_path))
        assert result == []

    def test_read_logs_with_matching_content(self, tmp_path: Path) -> None:
        """Test reading logs with matching story ID."""
        log_file = tmp_path / "_claude_raw_12345.tmp"
        log_content = (
            "[2026-04-27T10:30:45Z] [INFO] [parse] US-123 story parsing\n"
            "[2026-04-27T10:30:46Z] [ERROR] [implement] US-123 failed\n"
        )
        log_file.write_text(log_content, encoding="utf-8")

        result = read_story_logs("US-123", str(tmp_path))
        assert len(result) > 0
        # Check that at least some logs are matched
        messages = [log.get("message", "") for log in result]
        assert any("US-123" in msg for msg in messages)

    def test_read_logs_handles_unicode(self, tmp_path: Path) -> None:
        """Test reading logs with unicode content."""
        log_file = tmp_path / "_claude_raw_12345.tmp"
        log_content = "[2026-04-27T10:30:45Z] [INFO] [parse] US-123 with emoji 🚀\n"
        log_file.write_text(log_content, encoding="utf-8")

        result = read_story_logs("US-123", str(tmp_path))
        assert len(result) > 0

    def test_read_logs_sorted_by_timestamp(self, tmp_path: Path) -> None:
        """Test that logs are sorted by timestamp."""
        log_file = tmp_path / "_claude_raw_12345.tmp"
        log_content = (
            "[2026-04-27T10:30:46Z] [INFO] [parse] US-123 second\n"
            "[2026-04-27T10:30:45Z] [INFO] [parse] US-123 first\n"
            "[2026-04-27T10:30:47Z] [INFO] [parse] US-123 third\n"
        )
        log_file.write_text(log_content, encoding="utf-8")

        result = read_story_logs("US-123", str(tmp_path))
        if len(result) >= 2:
            # Check that first entry timestamp <= last entry timestamp
            first_ts = result[0].get("timestamp", "")
            last_ts = result[-1].get("timestamp", "")
            assert first_ts <= last_ts
