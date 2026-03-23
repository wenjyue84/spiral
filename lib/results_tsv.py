#!/usr/bin/env python3
"""
results_tsv.py — Results.tsv record parsing and serialization.

Handles ResultsRecord dataclass definition and functions to parse/write
results.tsv files with proper backward-compatibility for missing columns.
"""

import csv
import json
import re
from dataclasses import asdict, dataclass
from typing import TextIO


@dataclass
class ResultsRecord:
    """Single row in results.tsv with telemetry and metadata."""

    timestamp: str
    spiral_iter: str
    ralph_iter: str
    story_id: str
    story_title: str
    status: str
    duration_sec: str
    model: str
    retry_num: str
    commit_sha: str
    run_id: str
    cache_hit: str = ""
    cache_read_tokens: str = ""
    cache_creation_tokens: str = ""
    review_tokens: str = ""
    wall_seconds: str = ""
    user_cpu_s: str = ""
    sys_cpu_s: str = ""
    peak_rss_kb: str = ""
    batch_id: str = ""
    votes_accept: str = ""
    votes_reject: str = ""
    conflict_files: str = ""
    failure_root_cause: str = ""
    sub_project: str = ""  # New column for federated SPIRAL runs
    failed_files: str = ""  # US-597: JSON array of files that failed (e.g. '["src/a.py"]')
    scope_tag: str = ""  # US-744: 'scope_reduced' when scope reduction was applied
    error_category: str = ""  # US-1041: failure category from Phase T


# Header fields in order for TSV writing
HEADER = [
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
    "cache_hit",
    "cache_read_tokens",
    "cache_creation_tokens",
    "review_tokens",
    "wall_seconds",
    "user_cpu_s",
    "sys_cpu_s",
    "peak_rss_kb",
    "batch_id",
    "votes_accept",
    "votes_reject",
    "conflict_files",
    "failure_root_cause",
    "sub_project",
    "failed_files",
    "scope_tag",
    "error_category",
]


def parse_failed_files_from_stderr(stderr: str) -> list[str]:
    """
    Extract file paths from Ralph stderr output (US-597).

    Matches lines like:
      Error processing file: src/main.py
      Failed to implement: lib/utils.py
      ERROR: src/api/routes.py — ...

    Returns a deduplicated, sorted list of unique file paths found.
    """
    patterns = [
        r"Error processing file:\s+([\w./\\-]+)",
        r"Failed to implement:\s+([\w./\\-]+)",
        r"ERROR:\s+([\w./\\-]+\.(?:py|sh|ts|js|json|yaml|yml|md))",
        r"FAILED:\s+([\w./\\-]+)",
    ]
    found: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, stderr, re.IGNORECASE | re.MULTILINE):
            path = match.group(1).strip().rstrip("—:,")
            if path:
                found.add(path)
    return sorted(found)


def get_last_failed_files(results_path: str, story_id: str) -> list[str]:
    """
    Read results.tsv and return the failed_files list from the most recent
    failed attempt for the given story_id (US-597).

    Returns an empty list if no matching record exists or failed_files is empty/invalid.
    """
    records = parse_results_tsv(results_path)
    # Find the last record for this story that has a non-empty failed_files
    for record in reversed(records):
        if record.story_id == story_id and record.failed_files:
            try:
                files = json.loads(record.failed_files)
                if isinstance(files, list) and files:
                    return [str(f) for f in files]
            except (json.JSONDecodeError, ValueError):
                pass
    return []


def parse_results_tsv(path: str) -> list[ResultsRecord]:
    """
    Parse a results.tsv file into list of ResultsRecord objects.

    Backward-compatible: missing columns (especially new ones) are treated as empty strings.
    """
    records = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                return []

            for row in reader:
                # Ensure all expected fields exist (backward-compat for missing columns)
                record_dict = {field: row.get(field, "") for field in HEADER}
                records.append(ResultsRecord(**record_dict))
    except (FileNotFoundError, ValueError):
        return []

    return records


def write_results_row(f: TextIO, record: ResultsRecord) -> None:
    """
    Write a single ResultsRecord row to an open TSV file.
    """
    writer = csv.DictWriter(
        f,
        fieldnames=HEADER,
        delimiter="\t",
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writerow(asdict(record))


def write_results_tsv(path: str, records: list[ResultsRecord]) -> None:
    """
    Write a list of ResultsRecord objects to a results.tsv file.
    """
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=HEADER,
            delimiter="\t",
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))
