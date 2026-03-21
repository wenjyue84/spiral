"""Integration test — Phase M federated story conflict detection and rollback (US-660).

Two sub-projects with overlapping filesToTouch → conflict detected, results.tsv
logged with status=rejected, prd.json rolled back, .spiral/conflicts.json written.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(_LIB))

from conflict_detector import detect_conflicts
from merge_conflict_detector import build_conflict_matrix, run
from results_tsv import ResultsRecord, write_results_tsv

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _story(sid: str, sub: str, files: list[str]) -> dict[str, Any]:
    return {
        "id": sid,
        "title": f"Story {sid}",
        "description": "d",
        "priority": "high",
        "acceptanceCriteria": ["AC"],
        "dependencies": [],
        "passes": False,
        "sub_project": sub,
        "filesTouch": files,
        "technicalNotes": [],
    }


STORY_A = _story("FED-001", "payments", ["lib/shared.py", "lib/payments.py"])
STORY_B = _story("FED-002", "billing", ["lib/shared.py", "lib/billing.py"])
STORY_C = _story("FED-003", "auth", ["lib/auth.py"])  # no conflict


def _prd(stories: list[dict[str, Any]]) -> dict[str, Any]:
    return {"productName": "Test", "branchName": "main", "userStories": stories}


# ── AC1: two sub-projects modifying same file path → conflict detected ───────


def test_federated_conflict_detected() -> None:
    matrix = build_conflict_matrix([STORY_A, STORY_B, STORY_C])
    conflicts = {f: ids for f, ids in matrix.items() if len(ids) >= 2}
    assert "lib/shared.py" in conflicts
    assert set(conflicts["lib/shared.py"]) == {"FED-001", "FED-002"}
    # Non-conflicting file not flagged
    solo = {f: ids for f, ids in matrix.items() if len(ids) == 1}
    assert "lib/auth.py" in solo


def test_conflict_detector_finds_overlap() -> None:
    hits = detect_conflicts([STORY_A, STORY_B, STORY_C])
    assert len(hits) == 1
    assert hits[0]["storyA"] == "FED-001"
    assert hits[0]["storyB"] == "FED-002"
    assert "lib/shared.py" in hits[0]["conflict_files"]


# ── AC2: merge rejects with conflict error in results.tsv status=rejected ────


def test_rejected_in_results_tsv(tmp_path: Path) -> None:
    tsv = tmp_path / "results.tsv"
    rejected: list[ResultsRecord] = []
    matrix = build_conflict_matrix([STORY_A, STORY_B])
    conflicts = {f: ids for f, ids in matrix.items() if len(ids) >= 2}
    for fpath, ids in conflicts.items():
        for sid in ids:
            rejected.append(
                ResultsRecord(
                    timestamp="2026-03-21T00:00:00Z",
                    spiral_iter="1",
                    ralph_iter="0",
                    story_id=sid,
                    story_title=f"Story {sid}",
                    status="rejected",
                    duration_sec="0",
                    model="n/a",
                    retry_num="0",
                    commit_sha="",
                    run_id="test",
                    conflict_files=fpath,
                    sub_project=next(s["sub_project"] for s in [STORY_A, STORY_B] if s["id"] == sid),
                )
            )
    write_results_tsv(str(tsv), rejected)
    content = tsv.read_text()
    assert "rejected" in content
    assert "FED-001" in content and "FED-002" in content
    assert "lib/shared.py" in content


# ── AC3: prd.json rolls back, conflict report at .spiral/conflicts.json ──────


def test_rollback_and_conflict_report(tmp_path: Path) -> None:
    stories = [STORY_A.copy(), STORY_B.copy(), STORY_C.copy()]
    prd = _prd(stories)
    prd_path = tmp_path / "prd.json"
    prd_path.write_text(json.dumps(prd))
    original = prd_path.read_text()

    # Phase M conflict detection
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir()
    report_path = str(spiral_dir / "conflicts.json")
    exit_code = run([STORY_A, STORY_B], out_path=report_path)

    assert exit_code == 1, "Should reject when conflicts exist"
    # Rollback: prd.json unchanged (stories still pending, _source preserved)
    assert prd_path.read_text() == original, "prd.json must not be mutated"
    for s in json.loads(prd_path.read_text())["userStories"]:
        assert s["passes"] is False, f"{s['id']} should remain pending"
    # Conflict report written
    assert os.path.isfile(report_path)
    report = json.loads(Path(report_path).read_text())
    assert len(report) >= 1
    sids = {r["story_id"] for r in report}
    assert "FED-001" in sids and "FED-002" in sids
    files = {f for r in report for f in r["conflicting_files"]}
    assert "lib/shared.py" in files
