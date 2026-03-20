"""tests/test_federated_status.py — Integration tests for US-629.

Tests federated-status CLI with mock results.tsv files from multiple sub-projects.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Add lib/ to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from federated_status import (  # noqa: E402
    aggregate_federated_stories,
    calculate_project_metrics,
    format_json_output,
    format_table_output,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


TSV_HEADER = (
    "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
    "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit\t"
    "cache_read_tokens\tcache_creation_tokens\treview_tokens\twall_seconds\t"
    "user_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id"
)


def _make_row(
    story_id: str,
    title: str,
    status: str,
    model: str,
    retry_num: int,
    cache_read: int = 100000,
    cache_create: int = 50000,
    duration: int = 120,
) -> str:
    """Create a results.tsv row."""
    return (
        f"2026-03-20T10:00:00Z\t1\t1\t{story_id}\t{title}\t{status}\t"
        f"{duration}\t{model}\t{retry_num}\tabc123\trun1\ttrue\t"
        f"{cache_read}\t{cache_create}\t0\t0\t0\t0\t0\t"
    )


def test_calculate_project_metrics_empty() -> None:
    """Test calculate_project_metrics with empty results."""
    metrics = calculate_project_metrics("empty-project", [])

    assert metrics["project"] == "empty-project"
    assert metrics["total_stories"] == 0
    assert metrics["passed"] == 0
    assert metrics["failed"] == 0
    assert metrics["pending"] == 0
    assert metrics["tokens_used"] == 0
    assert metrics["cost_usd"] == 0.0


def test_format_json_output() -> None:
    """Test format_json_output produces valid JSON."""
    data = {
        "projects": [
            {
                "project": "test-proj",
                "total_stories": 5,
                "passed": 3,
                "failed": 1,
                "pending": 1,
                "tokens_used": 500000,
                "cost_usd": 3.75,
                "avg_duration_s": 120.0,
            }
        ],
        "summary": {
            "total_stories": 5,
            "passed": 3,
            "failed": 1,
            "pending": 1,
            "tokens_used": 500000,
            "cost_usd": 3.75,
            "avg_duration_s": 120.0,
        },
    }

    output = format_json_output(data)

    # Verify it's valid JSON
    parsed = json.loads(output)
    assert parsed == data


def test_format_table_output() -> None:
    """Test format_table_output produces readable table."""
    data = {
        "projects": [
            {
                "project": "proj-a",
                "total_stories": 5,
                "passed": 3,
                "failed": 1,
                "pending": 1,
                "tokens_used": 500000,
                "cost_usd": 3.75,
                "avg_duration_s": 120.0,
            }
        ],
        "summary": {
            "total_stories": 5,
            "passed": 3,
            "failed": 1,
            "pending": 1,
            "tokens_used": 500000,
            "cost_usd": 3.75,
            "avg_duration_s": 120.0,
        },
    }

    output = format_table_output(data)

    # Verify table structure
    lines = output.split("\n")
    assert len(lines) >= 4  # Header + sep + 1 project + sep + summary
    assert "Sub-Project" in lines[0]
    assert "Total" in lines[0]
    assert "Passed" in lines[0]
    assert "Failed" in lines[0]
    assert "TOTAL" in output
