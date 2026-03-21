"""CLI command: show-worker-logs — Aggregate and stream parallel worker logs.

Scans worker log directories for log files, parses them into structured entries,
and outputs a unified, time-sorted tab-separated report.

Output format: worker_id<TAB>timestamp<TAB>phase<TAB>log_level<TAB>message

Story: US-607
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

# Patterns to extract structured info from raw worker log lines
_TIMESTAMP_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"  # ISO timestamp
    r"|(\d{2}:\d{2}:\d{2})"  # HH:MM:SS
    r"|(\d{10,})"  # Unix epoch
)

_PHASE_RE = re.compile(
    r"\[(?:Phase\s+)?([RSTMIVGCP0])\]"  # [Phase R], [R], [I], etc.
    r"|\bPhase\s+([RSTMIVGCP0])\b",  # Phase R (without brackets)
    re.IGNORECASE,
)

_LEVEL_RE = re.compile(
    r"\b(ERROR|WARN(?:ING)?|INFO|DEBUG|FATAL|CRITICAL)\b",
    re.IGNORECASE,
)

_WORKER_ID_FROM_FILENAME_RE = re.compile(r"worker[-_](\d+|[a-zA-Z0-9_-]+)\.log$")


@dataclass
class LogEntry:
    """A single parsed log line."""

    worker_id: str
    timestamp: str
    phase: str
    log_level: str
    message: str

    def to_tsv(self) -> str:
        """Format as tab-separated line."""
        return f"{self.worker_id}\t{self.timestamp}\t{self.phase}\t{self.log_level}\t{self.message}"


def _extract_worker_id(filepath: Path) -> str:
    """Extract worker ID from log file path."""
    m = _WORKER_ID_FROM_FILENAME_RE.search(filepath.name)
    if m:
        return f"worker-{m.group(1)}"
    # Fallback: use parent directory name if it looks like a worker dir
    if filepath.parent.name.startswith("worker-"):
        return filepath.parent.name
    return filepath.stem


def _parse_line(line: str, worker_id: str) -> LogEntry:
    """Parse a raw log line into a structured LogEntry."""
    line = line.rstrip("\n\r")

    # Extract timestamp
    timestamp = ""
    ts_match = _TIMESTAMP_RE.search(line)
    if ts_match:
        timestamp = ts_match.group(1) or ts_match.group(2) or ts_match.group(3) or ""

    # Extract phase
    phase = ""
    phase_match = _PHASE_RE.search(line)
    if phase_match:
        phase = (phase_match.group(1) or phase_match.group(2) or "").upper()

    # Extract log level
    log_level = "INFO"
    level_match = _LEVEL_RE.search(line)
    if level_match:
        raw = level_match.group(1).upper()
        log_level = "WARN" if raw == "WARNING" else raw

    # Message is the full line (minus leading/trailing whitespace)
    message = line.strip()

    return LogEntry(
        worker_id=worker_id,
        timestamp=timestamp,
        phase=phase,
        log_level=log_level,
        message=message,
    )


def find_worker_logs(
    search_dirs: list[Path],
) -> list[Path]:
    """Find all worker log files in the given directories.

    Looks for files matching worker_*.log or worker-*.log patterns.
    """
    logs: list[Path] = []
    for d in search_dirs:
        if not d.is_dir():
            continue
        # Direct log files in the directory
        for f in sorted(d.glob("worker*.log")):
            if f.is_file() and f.stat().st_size > 0:
                logs.append(f)
        # Log files inside worker-N subdirectories
        for f in sorted(d.glob("worker-*/**.log")):
            if f.is_file() and f.stat().st_size > 0:
                logs.append(f)
    return logs


def parse_worker_logs(
    log_files: list[Path],
    *,
    worker_id_filter: str | None = None,
    phase_filter: str | None = None,
) -> list[LogEntry]:
    """Parse all log files into sorted, filtered LogEntry list.

    Args:
        log_files: List of log file paths.
        worker_id_filter: If set, only include entries from this worker.
        phase_filter: If set, only include entries from this phase.

    Returns:
        Time-sorted list of LogEntry objects (duplicates removed).
    """
    entries: list[LogEntry] = []
    seen: set[tuple[str, str]] = set()  # (timestamp, message) for dedup across files

    for log_file in log_files:
        wid = _extract_worker_id(log_file)

        if worker_id_filter and wid != worker_id_filter:
            continue

        try:
            with open(log_file, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    entry = _parse_line(line, wid)

                    # Apply phase filter
                    if phase_filter and entry.phase != phase_filter.upper():
                        continue

                    # Deduplicate by timestamp + message (same line from multiple files)
                    key = (entry.timestamp, entry.message)
                    if key in seen:
                        continue
                    seen.add(key)

                    entries.append(entry)
        except OSError:
            continue

    # Sort by timestamp (entries without timestamps sort first)
    entries.sort(key=lambda e: (e.timestamp or "", e.worker_id))
    return entries


def format_output(
    entries: list[LogEntry],
    output: TextIO | None = None,
) -> str:
    """Format entries as TSV and optionally write to file.

    Returns the formatted TSV string.
    """
    header = "worker_id\ttimestamp\tphase\tlog_level\tmessage"
    lines = [header] + [e.to_tsv() for e in entries]
    result = "\n".join(lines) + "\n"

    if output:
        output.write(result)

    return result


def show_worker_logs(
    search_dirs: list[Path] | None = None,
    *,
    worker_id: str | None = None,
    phase: str | None = None,
    output_path: str | None = None,
) -> str:
    """Main entry point: find, parse, filter, and format worker logs.

    Args:
        search_dirs: Directories to search for worker logs.
            Default: [.spiral/workers, .spiral-workers]
        worker_id: Filter to specific worker (e.g. "worker-1").
        phase: Filter to specific phase letter (e.g. "I").
        output_path: Optional file path to write output.

    Returns:
        Formatted TSV output string.
    """
    if search_dirs is None:
        cwd = Path.cwd()
        search_dirs = [
            cwd / ".spiral" / "workers",
            cwd / ".spiral-workers",
        ]

    log_files = find_worker_logs(search_dirs)
    if not log_files:
        msg = "No worker log files found.\n"
        print(msg, end="", file=sys.stderr)
        return ""

    entries = parse_worker_logs(
        log_files,
        worker_id_filter=worker_id,
        phase_filter=phase,
    )

    output_file: TextIO | None = None
    try:
        if output_path:
            output_file = open(output_path, "w", encoding="utf-8")

        result = format_output(entries, output=output_file)

        # Also print to stdout
        print(result, end="")
        return result
    finally:
        if output_file:
            output_file.close()
