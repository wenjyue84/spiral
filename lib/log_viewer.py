#!/usr/bin/env python3
"""Log viewer for SPIRAL story implementation logs."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

# ANSI color codes
COLORS = {
    "DEBUG": "\033[36m",  # cyan
    "INFO": "\033[34m",  # blue
    "WARN": "\033[33m",  # yellow
    "ERROR": "\033[31m",  # red
    "RESET": "\033[0m",
}


def read_story_logs(story_id: str, scratch_dir: str = ".spiral") -> list[dict[str, Any]]:
    """
    Read logs for a story from worker log files.

    Searches .spiral/_claude_raw_*.tmp files for log entries matching story_id.
    Returns list of parsed log entries.
    """
    logs: list[dict[str, Any]] = []
    scratch_path = Path(scratch_dir)

    if not scratch_path.exists():
        return logs

    # Search all _claude_raw_*.tmp files
    for log_file in scratch_path.glob("_claude_raw_*.tmp"):
        try:
            with open(log_file, encoding="utf-8") as f:
                content = f.read()
                # Look for story_id mentions in the log
                if story_id in content:
                    # Parse the log content line by line
                    for line in content.split("\n"):
                        parsed = parse_log_line(line)
                        if parsed and (story_id in parsed.get("message", "") or story_id in parsed.get("source", "")):
                            logs.append(parsed)
        except (OSError, UnicodeDecodeError):
            continue

    # If no logs found in raw files, return empty list
    return sorted(logs, key=lambda x: x.get("timestamp", ""))


def parse_log_line(line: str) -> dict[str, Any] | None:
    """
    Parse a log line into structured format.

    Expected formats:
    - [TIMESTAMP] [LEVEL] [CONTEXT] message
    - TIMESTAMP | LEVEL | CONTEXT | message | source:line

    Returns dict with keys: timestamp, level, context, message, source
    Returns None if line doesn't match expected format.
    """
    if not line or not line.strip():
        return None

    # Try pipe-separated format first
    if "|" in line:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 4:
            return {
                "timestamp": parts[0],
                "level": parts[1],
                "context": parts[2],
                "message": parts[3],
                "source": parts[4] if len(parts) > 4 else "",
            }

    # Try bracket format: [TIMESTAMP] [LEVEL] [CONTEXT] message
    match = re.match(
        r"\[([^\]]+)\]\s+\[([^\]]+)\]\s+\[([^\]]+)\]\s+(.*)",
        line,
    )
    if match:
        return {
            "timestamp": match.group(1),
            "level": match.group(2),
            "context": match.group(3),
            "message": match.group(4),
            "source": "",
        }

    return None


def filter_by_level(
    logs: list[dict[str, Any]],
    level: str,
) -> list[dict[str, Any]]:
    """
    Filter logs by log level.

    level: DEBUG, INFO, WARN, ERROR, or empty string for no filtering
    """
    if not level:
        return logs

    level = level.upper()
    valid_levels = ["DEBUG", "INFO", "WARN", "ERROR"]
    if level not in valid_levels:
        return logs

    # Include this level and all higher severity levels
    level_order = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
    min_severity = level_order[level]

    return [log for log in logs if level_order.get(log.get("level", "").upper(), -1) >= min_severity]


def filter_by_context(
    logs: list[dict[str, Any]],
    context: str,
) -> list[dict[str, Any]]:
    """
    Filter logs by phase context.

    context: parse, decompose, implement, verify, or empty string for no filtering
    """
    if not context:
        return logs

    context = context.lower()
    valid_contexts = ["parse", "decompose", "implement", "verify"]
    if context not in valid_contexts:
        return logs

    return [log for log in logs if context in log.get("context", "").lower()]


def colorize_output(logs: list[dict[str, Any]]) -> str:
    """
    Format logs with ANSI color codes.

    Returns formatted string with:
    - RED for ERROR
    - YELLOW for WARN
    - BLUE for INFO
    - CYAN for DEBUG
    """
    if not logs:
        return "No logs found."

    lines = []
    for log in logs:
        level = log.get("level", "INFO").upper()
        color = COLORS.get(level, COLORS["RESET"])
        reset = COLORS["RESET"]

        timestamp = log.get("timestamp", "")
        message = log.get("message", "")
        source = log.get("source", "")

        # Format: timestamp | level | context | message | source
        line = f"{timestamp} | {color}{level}{reset} | {log.get('context', '')} | {message}"
        if source:
            line += f" | {source}"

        lines.append(line)

    return "\n".join(lines)


def main() -> int:
    """CLI entry point for log viewer."""
    if len(sys.argv) < 2:
        print("Usage: python -m lib.log_viewer <story-id> [--level LEVEL] [--context CONTEXT]")
        print("")
        print("Options:")
        print("  --level     DEBUG, INFO, WARN, ERROR (filters to this level and higher)")
        print("  --context   parse, decompose, implement, verify")
        return 1

    story_id = sys.argv[1]
    level = ""
    context = ""

    # Parse optional flags
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--level" and i + 1 < len(sys.argv):
            level = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--context" and i + 1 < len(sys.argv):
            context = sys.argv[i + 1]
            i += 2
        else:
            i += 1

    # Read and filter logs
    logs = read_story_logs(story_id)
    logs = filter_by_level(logs, level)
    logs = filter_by_context(logs, context)

    # Output colorized logs
    output = colorize_output(logs)
    print(output)

    return 0 if logs else 1


if __name__ == "__main__":
    sys.exit(main())
