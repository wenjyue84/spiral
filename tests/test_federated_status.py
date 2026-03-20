"""tests/test_federated_status.py — Integration tests for US-629.

Tests federated-status CLI with mock results.tsv files from multiple sub-projects.
"""

from __future__ import annotations

import json
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


def test_aggregate_3_project_cost_accuracy(tmp_path: Path) -> None:
    """Mock 3-project PRD with mixed pass/fail/pending stories.

    Assert CLI JSON output cost calculations match results.tsv summation within 2% tolerance.
    AC3 for US-629.
    """
    # Cost constants from federated_status.py (COST_PER_MTOK)
    AVG_HAIKU = (0.80 + 4.00) / 2.0   # 2.40 per MTok
    AVG_SONNET = (3.00 + 15.00) / 2.0  # 9.00 per MTok
    AVG_OPUS = (15.00 + 75.00) / 2.0   # 45.00 per MTok

    # Create prd.json with 3 sub-projects
    prd = {
        "userStories": [
            # project-alpha: 2 stories
            {"id": "US-001", "title": "Alpha 1", "sub_project": "project-alpha"},
            {"id": "US-002", "title": "Alpha 2", "sub_project": "project-alpha"},
            # project-beta: 3 stories
            {"id": "US-003", "title": "Beta 1", "sub_project": "project-beta"},
            {"id": "US-004", "title": "Beta 2", "sub_project": "project-beta"},
            {"id": "US-005", "title": "Beta 3", "sub_project": "project-beta"},
            # project-gamma: 1 story (no results — stays pending)
            {"id": "US-006", "title": "Gamma 1", "sub_project": "project-gamma"},
        ]
    }
    prd_path = tmp_path / "prd.json"
    prd_path.write_text(json.dumps(prd), encoding="utf-8")

    # Row token counts (cache_read, cache_create)
    rows = [
        ("US-001", "Alpha 1", "pass", "haiku", 0, 100_000, 50_000),
        ("US-002", "Alpha 2", "reject", "sonnet", 1, 200_000, 100_000),
        ("US-003", "Beta 1", "pass", "sonnet", 0, 150_000, 75_000),
        ("US-004", "Beta 2", "reject", "opus", 2, 80_000, 40_000),
        # US-005 pending (no row); US-006 pending (no row)
    ]

    tsv_content = TSV_HEADER + "\n"
    for story_id, title, status, model, retry, cr, cc in rows:
        tsv_content += _make_row(story_id, title, status, model, retry, cache_read=cr, cache_create=cc) + "\n"

    tsv_file = tmp_path / "results.tsv"
    tsv_file.write_text(tsv_content, encoding="utf-8")

    result = aggregate_federated_stories(prd_path, results_globs=["results.tsv"])

    # Manually compute expected costs per project
    # project-alpha: US-001 (haiku, 150k tokens) + US-002 (sonnet, 300k tokens)
    expected_alpha = (150_000 * AVG_HAIKU + 300_000 * AVG_SONNET) / 1_000_000
    # project-beta: US-003 (sonnet, 225k tokens) + US-004 (opus, 120k tokens) + US-005 (pending, 0 tokens)
    expected_beta = (225_000 * AVG_SONNET + 120_000 * AVG_OPUS) / 1_000_000
    # project-gamma: no results → 0
    expected_gamma = 0.0
    expected_total = expected_alpha + expected_beta + expected_gamma

    actual_total = result["summary"]["cost_usd"]
    assert expected_total > 0, "expected cost must be positive"
    assert abs(actual_total - expected_total) / expected_total < 0.02, (
        f"cost {actual_total:.6f} differs from expected {expected_total:.6f} by > 2%"
    )

    # Verify pass/fail/pending counts
    projects_by_name = {p["project"]: p for p in result["projects"]}
    alpha = projects_by_name["project-alpha"]
    assert alpha["passed"] == 1
    assert alpha["failed"] == 1
    assert alpha["pending"] == 0

    beta = projects_by_name["project-beta"]
    assert beta["passed"] == 1
    assert beta["failed"] == 1
    assert beta["pending"] == 1  # US-005 has no results row

    gamma = projects_by_name["project-gamma"]
    assert gamma["passed"] == 0
    assert gamma["pending"] == 1

    # Verify JSON output round-trips cleanly
    json_str = format_json_output(result)
    parsed = json.loads(json_str)
    assert parsed["summary"]["cost_usd"] == result["summary"]["cost_usd"]
