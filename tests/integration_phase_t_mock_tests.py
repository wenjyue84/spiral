"""tests/integration_phase_t_mock_tests.py — Phase T integration test (US-658).

Tests the complete Phase T workflow: parse mock test output -> extract failures
-> create stories with correct _source and priority -> verify merge ordering.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(_LIB / "research"))
sys.path.insert(0, str(_LIB))

from synthesize_tests import (  # noqa: E402
    aggregate_failures,
    find_recent_reports,
    is_duplicate,
    result_to_story,
)

# ── Mock report: 3 FAIL/ERROR + 1 PASS ──────────────────────────────────────
MOCK_REPORT: dict[str, Any] = {
    "all_results": [
        {
            "id": "tests.unit.auth.test_login.TestAuth.test_valid",
            "name": "test_valid",
            "status": "FAIL",
            "category": "unit",
            "error": {"type": "AssertionError", "message": "Expected 200 got 401"},
        },
        {
            "id": "tests.integration.api.test_ep.TestAPI.test_users",
            "name": "test_users",
            "status": "ERROR",
            "category": "integration",
            "error": {"type": "ConnError", "message": "Connection refused port 5432"},
        },
        {
            "id": "tests.regression.db.test_mig.TestDB.test_schema",
            "name": "test_schema",
            "status": "FAIL",
            "category": "regression",
            "error": {"type": "SchemaError", "message": "Column email missing"},
        },
        {"id": "tests.unit.utils.test_help.test_parse", "name": "test_parse", "status": "PASS", "category": "unit"},
    ]
}


def _write_report(tmp_path: Path, subdir: str = "2026-03-21T120000") -> str:
    d = tmp_path / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.json").write_text(json.dumps(MOCK_REPORT))
    return str(d / "report.json")


# ── AC1: mocks subprocess output from pytest with 3+ failures ────────────────


def test_aggregate_extracts_only_failures(tmp_path: Path) -> None:
    path = _write_report(tmp_path)
    failures, _names = aggregate_failures([path])
    assert len(failures) == 3
    assert all(f["status"] in ("FAIL", "ERROR") for f in failures)


def test_find_recent_reports(tmp_path: Path) -> None:
    _write_report(tmp_path, "2026-03-20T100000")
    _write_report(tmp_path, "2026-03-21T100000")
    paths = find_recent_reports(str(tmp_path), n=3)
    assert len(paths) == 2
    assert "2026-03-21" in paths[0]  # newest first


def test_dedup_skips_existing_titles() -> None:
    assert is_duplicate("Fix failing test: auth login valid", ["Fix failing test: auth login valid"])
    assert not is_duplicate("Fix failing test: auth login valid", ["Add new feature X"])


# ── AC2: _source='test-fix' and failure reason in description ────────────────


def test_result_to_story_source_and_description() -> None:
    for r in MOCK_REPORT["all_results"][:3]:
        story = result_to_story(r)
        assert story["_source"].startswith("test-synthesis:"), story["_source"]
        # Failure reason appears in acceptanceCriteria (root cause line)
        ac_text = " ".join(story["acceptanceCriteria"])
        assert r["error"]["message"][:15] in ac_text
        assert story["estimatedComplexity"] == "small"


def test_result_to_story_priority_by_category() -> None:
    stories = [result_to_story(r) for r in MOCK_REPORT["all_results"][:3]]
    assert stories[0]["priority"] == "medium"  # unit
    assert stories[1]["priority"] == "high"  # integration
    assert stories[2]["priority"] == "high"  # regression


# ── AC3: test-fix stories prioritized above research in Phase M merge order ──


def test_testfix_prioritized_above_research(tmp_path: Path) -> None:
    prd = {
        "productName": "T",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001",
                "title": "Done story",
                "passes": True,
                "priority": "medium",
                "description": "d",
                "acceptanceCriteria": ["AC"],
                "dependencies": [],
            },
        ],
    }
    (tmp_path / "prd.json").write_text(json.dumps(prd))
    (tmp_path / "test.json").write_text(
        json.dumps(
            {
                "stories": [
                    {
                        "title": "Fix failing auth test",
                        "priority": "high",
                        "description": "test fail",
                        "acceptanceCriteria": ["t passes"],
                        "dependencies": [],
                    },
                ]
            }
        )
    )
    (tmp_path / "research.json").write_text(
        json.dumps(
            {
                "stories": [
                    {
                        "title": "Add widget feature",
                        "priority": "high",
                        "description": "research",
                        "acceptanceCriteria": ["AC"],
                        "dependencies": [],
                    },
                ]
            }
        )
    )
    subprocess.run(
        [
            sys.executable,
            str(_LIB / "prd" / "merge_stories.py"),
            "--prd",
            str(tmp_path / "prd.json"),
            "--test-stories",
            str(tmp_path / "test.json"),
            "--research",
            str(tmp_path / "research.json"),
            "--max-new",
            "10",
        ],
        check=True,
    )
    merged = json.loads((tmp_path / "prd.json").read_text())
    pending = [s for s in merged["userStories"] if not s.get("passes")]
    titles = [s["title"] for s in pending]
    assert "Fix failing auth test" in titles
    assert "Add widget feature" in titles
    tf_idx = titles.index("Fix failing auth test")
    res_idx = titles.index("Add widget feature")
    assert tf_idx < res_idx, f"test-fix@{tf_idx} must precede research@{res_idx}"
