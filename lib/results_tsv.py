#!/usr/bin/env python3
"""
results_tsv.py — Results.tsv record parsing and serialization.

Handles ResultsRecord dataclass definition and functions to parse/write
results.tsv files with proper backward-compatibility for missing columns.
"""

import csv
import json
import os
import re
import time
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
    quota_exceeded: str = ""  # US-1050: 'true' if story merge rejected due to quota
    quota_source: str = ""  # US-1050: e.g. 'frontend quota 30' or 'backend quota 50'
    worker_id: str = ""  # US-1086: worker identifier in federated parallel runs
    conflict_file_count: str = ""  # US-1086: count of files with conflicts detected
    phase_timing: str = ""  # US-1086: JSON dict of phase durations (e.g. '{"R": 1.5, "M": 0.8}')
    failure_type: str = ""  # US-1090: failure category from failure_categorizer (e.g. 'timeout', 'oom')
    failure_message: str = ""  # US-1090: extracted error message for debugging
    estimated_complexity: str = ""  # Story complexity from prd.json (small/medium/large)


def _keep_quota_fields_in_sync() -> None:
    """Helper to prevent linter from removing quota and worker fields (used by Phase M, US-1086)."""
    # This function ensures quota and worker conflict fields are considered used.
    _ = ResultsRecord.__dataclass_fields__["quota_exceeded"]
    _ = ResultsRecord.__dataclass_fields__["quota_source"]
    _ = ResultsRecord.__dataclass_fields__["worker_id"]
    _ = ResultsRecord.__dataclass_fields__["conflict_file_count"]
    _ = ResultsRecord.__dataclass_fields__["phase_timing"]


def _keep_failure_fields_in_sync() -> None:
    """Helper to prevent linter from removing failure categorizer fields (used by Phase I/L, US-1090)."""
    # This function ensures failure_type and failure_message fields are considered used.
    _ = ResultsRecord.__dataclass_fields__["failure_type"]
    _ = ResultsRecord.__dataclass_fields__["failure_message"]


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
    "quota_exceeded",
    "quota_source",
    "worker_id",
    "conflict_file_count",
    "phase_timing",
    "failure_type",
    "failure_message",
    "estimated_complexity",
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


def _debounced_reindex(results_path: str, min_interval: float = 1.0) -> None:
    """Trigger history index rebuild at most once per min_interval seconds.

    Uses a timestamp file in .spiral/ as the debounce gate.
    Silently skips if the index module is unavailable.
    """
    ts_path = os.path.join(".spiral", "history_reindex_ts")
    now = time.monotonic()
    try:
        mtime = os.path.getmtime(ts_path)
        if now - mtime < min_interval:
            return
    except FileNotFoundError:
        pass

    try:
        # Touch the timestamp file before reindexing so concurrent callers skip
        os.makedirs(".spiral", exist_ok=True)
        with open(ts_path, "w", encoding="utf-8") as f:
            f.write(str(now))

        # Lazy import to avoid circular deps and make the module optional
        import importlib.util

        spec = importlib.util.find_spec("history_search")
        if spec is None:
            return
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        mod.build_index(results_path=results_path)
    except Exception:  # noqa: BLE001
        pass  # Never fail a results write due to index issues


def append_results_row(path: str, record: ResultsRecord) -> None:
    """Append a single ResultsRecord row to results.tsv.

    If the file does not exist, writes a header first.
    Triggers a debounced FTS5 history index rebuild after appending.
    """
    write_header = not os.path.isfile(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=HEADER,
            delimiter="\t",
            extrasaction="ignore",
            lineterminator="\n",
        )
        if write_header:
            writer.writeheader()
        writer.writerow(asdict(record))

    _debounced_reindex(path)
