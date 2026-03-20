#!/usr/bin/env python3
"""
results_tsv.py — Results.tsv record parsing and serialization.

Handles ResultsRecord dataclass definition and functions to parse/write
results.tsv files with proper backward-compatibility for missing columns.
"""

import csv
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
]


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
