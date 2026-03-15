"""Tests for lib/work_queue.py — work-offering queue for idle worker prevention."""
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from work_queue import WorkQueue


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _make_prd(path, stories):
    prd = {"productName": "Test", "branchName": "main", "userStories": stories}
    _write_json(path, prd)
    return path


def _story(sid, priority="medium", passes=False, deps=None):
    return {
        "id": sid,
        "title": f"Story {sid}",
        "priority": priority,
        "passes": passes,
        "dependencies": deps or [],
        "acceptanceCriteria": ["x"],
    }


# ── Tests ────────────────────────────────────────────────────────────────────

def test_offer_and_claim_roundtrip(tmp_path):
    """Stories offered by one worker can be claimed by another."""
    queue_path = str(tmp_path / "queue.json")
    prd_path = str(tmp_path / "prd.json")
    _make_prd(prd_path, [_story("US-001", passes=True)])

    wq = WorkQueue(queue_path)
    offered = wq.offer([_story("US-002"), _story("US-003")], source_worker=1)
    assert offered == 2

    claimed = wq.claim(worker_id=2, main_prd_path=prd_path)
    assert claimed is not None
    assert claimed["id"] in ("US-002", "US-003")


def test_claim_returns_highest_priority(tmp_path):
    """Claims should return the highest priority story first."""
    queue_path = str(tmp_path / "queue.json")
    prd_path = str(tmp_path / "prd.json")
    _make_prd(prd_path, [])

    wq = WorkQueue(queue_path)
    wq.offer([
        _story("US-010", priority="low"),
        _story("US-011", priority="critical"),
        _story("US-012", priority="medium"),
    ], source_worker=1)

    claimed = wq.claim(worker_id=2, main_prd_path=prd_path)
    assert claimed is not None
    assert claimed["id"] == "US-011"
    assert claimed["priority"] == "critical"


def test_claim_skips_unmet_deps(tmp_path):
    """Stories with unmet dependencies are not claimed."""
    queue_path = str(tmp_path / "queue.json")
    prd_path = str(tmp_path / "prd.json")
    _make_prd(prd_path, [_story("US-001", passes=True)])

    wq = WorkQueue(queue_path)
    wq.offer([
        _story("US-002", priority="high", deps=["US-099"]),  # dep not met
        _story("US-003", priority="medium"),  # no deps
    ], source_worker=1)

    claimed = wq.claim(worker_id=2, main_prd_path=prd_path)
    assert claimed is not None
    assert claimed["id"] == "US-003"  # US-002 skipped due to unmet dep


def test_concurrent_claims_no_double_assignment(tmp_path):
    """Multiple concurrent claims should not assign the same story twice."""
    queue_path = str(tmp_path / "queue.json")
    prd_path = str(tmp_path / "prd.json")
    _make_prd(prd_path, [])

    wq = WorkQueue(queue_path)
    stories = [_story(f"US-{i:03d}") for i in range(1, 4)]
    wq.offer(stories, source_worker=1)

    claimed_ids: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(3, timeout=10)

    def claimer(wid):
        barrier.wait()
        result = wq.claim(worker_id=wid, main_prd_path=prd_path)
        if result:
            with lock:
                claimed_ids.append(result["id"])

    threads = [threading.Thread(target=claimer, args=(i,)) for i in range(2, 5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    # No duplicate assignments
    assert len(claimed_ids) == len(set(claimed_ids))
    # At most 3 claims possible (3 stories offered)
    assert len(claimed_ids) <= 3


def test_inject_adds_story_to_prd(tmp_path):
    """inject() adds a story to the worker's prd.json."""
    prd_path = str(tmp_path / "prd.json")
    _make_prd(prd_path, [_story("US-001")])

    wq = WorkQueue(str(tmp_path / "queue.json"))
    new_story = _story("US-050", priority="high")
    wq.inject(prd_path, new_story)

    prd = _read_json(prd_path)
    ids = [s["id"] for s in prd["userStories"]]
    assert "US-050" in ids
    injected = [s for s in prd["userStories"] if s["id"] == "US-050"][0]
    assert injected["passes"] is False


def test_inject_skips_duplicate(tmp_path):
    """inject() does not add a story that already exists in prd.json."""
    prd_path = str(tmp_path / "prd.json")
    _make_prd(prd_path, [_story("US-001")])

    wq = WorkQueue(str(tmp_path / "queue.json"))
    wq.inject(prd_path, _story("US-001"))

    prd = _read_json(prd_path)
    assert len(prd["userStories"]) == 1


def test_claim_returns_none_when_empty(tmp_path):
    """claim() returns None on an empty queue."""
    queue_path = str(tmp_path / "queue.json")
    prd_path = str(tmp_path / "prd.json")
    _make_prd(prd_path, [])

    wq = WorkQueue(queue_path)
    result = wq.claim(worker_id=1, main_prd_path=prd_path)
    assert result is None


def test_offer_deduplicates(tmp_path):
    """Offering the same story twice doesn't create duplicates in the queue."""
    queue_path = str(tmp_path / "queue.json")
    wq = WorkQueue(queue_path)

    wq.offer([_story("US-001")], source_worker=1)
    added = wq.offer([_story("US-001"), _story("US-002")], source_worker=2)
    assert added == 1  # only US-002 is new

    queue = _read_json(queue_path)
    assert len(queue["stories"]) == 2


def test_claim_skips_already_passed(tmp_path):
    """Stories already passed in main PRD are not claimed."""
    queue_path = str(tmp_path / "queue.json")
    prd_path = str(tmp_path / "prd.json")
    _make_prd(prd_path, [_story("US-001", passes=True)])

    wq = WorkQueue(queue_path)
    wq.offer([_story("US-001"), _story("US-002")], source_worker=1)

    claimed = wq.claim(worker_id=2, main_prd_path=prd_path)
    assert claimed is not None
    assert claimed["id"] == "US-002"
