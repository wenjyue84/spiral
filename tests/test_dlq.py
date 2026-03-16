"""Tests for US-227: Dead-letter queue for permanently failed stories."""

import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main  # noqa: E402

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_prd(tmp_path, stories):
    prd = {
        "productName": "TestProduct",
        "branchName": "main",
        "userStories": stories,
    }
    p = tmp_path / "prd.json"
    p.write_text(json.dumps(prd), encoding="utf-8")
    return p


def _make_retry_counts(tmp_path, counts: dict):
    p = tmp_path / "retry-counts.json"
    p.write_text(json.dumps(counts), encoding="utf-8")
    return p


def _patch_paths(tmp_path, prd_path, retry_path=None, scratch_dir=None):
    """Patch file paths used by DLQ commands."""
    scratch = scratch_dir or (tmp_path / ".spiral")
    scratch.mkdir(parents=True, exist_ok=True)
    patches = [
        patch.object(main, "PRD_FILE", prd_path),
        patch.object(main, "SCRATCH_DIR", scratch),
        patch.object(main, "DLQ_AUDIT_LOG", scratch / "audit.log"),
    ]
    if retry_path is not None:
        patches.append(patch.object(main, "RETRY_COUNTS", retry_path))
    else:
        patches.append(patch.object(main, "RETRY_COUNTS", tmp_path / "retry-counts.json"))
    return patches


# ── _classify_stories dlq bucket ──────────────────────────────────────────


class TestClassifyStoriesDlq:
    def test_dlq_story_goes_to_dlq_bucket(self):
        stories = [{"id": "US-001", "title": "t", "passes": False, "_dlq": True}]
        buckets = main._classify_stories(stories, {})
        assert len(buckets["dlq"]) == 1
        assert buckets["dlq"][0]["id"] == "US-001"
        assert len(buckets["pending"]) == 0

    def test_dlq_story_not_in_other_buckets(self):
        stories = [{"id": "US-001", "title": "t", "passes": False, "_dlq": True}]
        buckets = main._classify_stories(stories, {"US-001": 5})
        # Even with high retry count, _dlq takes precedence over in_progress
        assert len(buckets["dlq"]) == 1
        assert len(buckets["in_progress"]) == 0

    def test_passed_story_not_in_dlq(self):
        stories = [{"id": "US-001", "title": "t", "passes": True, "_dlq": True}]
        buckets = main._classify_stories(stories, {})
        assert len(buckets["passed"]) == 1
        assert len(buckets["dlq"]) == 0

    def test_dlq_bucket_exists_when_empty(self):
        stories = [{"id": "US-001", "title": "t", "passes": False}]
        buckets = main._classify_stories(stories, {})
        assert "dlq" in buckets
        assert buckets["dlq"] == []


# ── cmd_dlq_promote ────────────────────────────────────────────────────────


class TestCmdDlqPromote:
    def test_promotes_exhausted_story(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPIRAL_MAX_RETRIES", "3")
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-001", "title": "t", "passes": False},
            ],
        )
        retry_path = _make_retry_counts(tmp_path, {"US-001": 3})
        with patch.multiple(
            main,
            PRD_FILE=prd_path,
            RETRY_COUNTS=retry_path,
            SCRATCH_DIR=tmp_path / ".spiral",
            DLQ_AUDIT_LOG=tmp_path / ".spiral" / "audit.log",
        ):
            (tmp_path / ".spiral").mkdir(exist_ok=True)
            args = SimpleNamespace(dry_run=False)
            main.cmd_dlq_promote(args)

        prd = json.loads(prd_path.read_text())
        story = prd["userStories"][0]
        assert story["_dlq"] is True
        assert "timestamp" in story["_dlqMetadata"]
        assert story["_dlqMetadata"]["retryCount"] == 3

    def test_does_not_promote_below_threshold(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPIRAL_MAX_RETRIES", "3")
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-001", "title": "t", "passes": False},
            ],
        )
        retry_path = _make_retry_counts(tmp_path, {"US-001": 2})
        with patch.multiple(
            main,
            PRD_FILE=prd_path,
            RETRY_COUNTS=retry_path,
            SCRATCH_DIR=tmp_path / ".spiral",
            DLQ_AUDIT_LOG=tmp_path / ".spiral" / "audit.log",
        ):
            (tmp_path / ".spiral").mkdir(exist_ok=True)
            args = SimpleNamespace(dry_run=False)
            main.cmd_dlq_promote(args)

        prd = json.loads(prd_path.read_text())
        story = prd["userStories"][0]
        assert "_dlq" not in story

    def test_skips_passed_stories(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPIRAL_MAX_RETRIES", "3")
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-001", "title": "t", "passes": True},
            ],
        )
        retry_path = _make_retry_counts(tmp_path, {"US-001": 5})
        with patch.multiple(
            main,
            PRD_FILE=prd_path,
            RETRY_COUNTS=retry_path,
            SCRATCH_DIR=tmp_path / ".spiral",
            DLQ_AUDIT_LOG=tmp_path / ".spiral" / "audit.log",
        ):
            (tmp_path / ".spiral").mkdir(exist_ok=True)
            args = SimpleNamespace(dry_run=False)
            main.cmd_dlq_promote(args)

        prd = json.loads(prd_path.read_text())
        story = prd["userStories"][0]
        assert "_dlq" not in story

    def test_skips_already_dlq_stories(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPIRAL_MAX_RETRIES", "3")
        prd_path = _make_prd(
            tmp_path,
            [
                {
                    "id": "US-001",
                    "title": "t",
                    "passes": False,
                    "_dlq": True,
                    "_dlqMetadata": {"timestamp": "2025-01-01T00:00:00+00:00", "retryCount": 3, "reason": "old"},
                },
            ],
        )
        retry_path = _make_retry_counts(tmp_path, {"US-001": 5})
        with patch.multiple(
            main,
            PRD_FILE=prd_path,
            RETRY_COUNTS=retry_path,
            SCRATCH_DIR=tmp_path / ".spiral",
            DLQ_AUDIT_LOG=tmp_path / ".spiral" / "audit.log",
        ):
            (tmp_path / ".spiral").mkdir(exist_ok=True)
            args = SimpleNamespace(dry_run=False)
            main.cmd_dlq_promote(args)

        prd = json.loads(prd_path.read_text())
        story = prd["userStories"][0]
        # metadata should not be overwritten
        assert story["_dlqMetadata"]["timestamp"] == "2025-01-01T00:00:00+00:00"

    def test_dry_run_does_not_modify_prd(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPIRAL_MAX_RETRIES", "3")
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-001", "title": "t", "passes": False},
            ],
        )
        retry_path = _make_retry_counts(tmp_path, {"US-001": 4})
        original = prd_path.read_text()
        with patch.multiple(
            main,
            PRD_FILE=prd_path,
            RETRY_COUNTS=retry_path,
            SCRATCH_DIR=tmp_path / ".spiral",
            DLQ_AUDIT_LOG=tmp_path / ".spiral" / "audit.log",
        ):
            (tmp_path / ".spiral").mkdir(exist_ok=True)
            args = SimpleNamespace(dry_run=True)
            main.cmd_dlq_promote(args)

        assert prd_path.read_text() == original

    def test_writes_audit_log(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPIRAL_MAX_RETRIES", "3")
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-001", "title": "t", "passes": False},
            ],
        )
        retry_path = _make_retry_counts(tmp_path, {"US-001": 3})
        scratch = tmp_path / ".spiral"
        audit_log = scratch / "audit.log"
        with patch.multiple(
            main, PRD_FILE=prd_path, RETRY_COUNTS=retry_path, SCRATCH_DIR=scratch, DLQ_AUDIT_LOG=audit_log
        ):
            scratch.mkdir(exist_ok=True)
            args = SimpleNamespace(dry_run=False)
            main.cmd_dlq_promote(args)

        assert audit_log.exists()
        entry = json.loads(audit_log.read_text().strip())
        assert entry["event"] == "dlq_promote"
        assert entry["story_id"] == "US-001"
        assert entry["retry_count"] == 3


# ── cmd_dlq_list ───────────────────────────────────────────────────────────


class TestCmdDlqList:
    def test_lists_dlq_stories(self, tmp_path, capsys):
        prd_path = _make_prd(
            tmp_path,
            [
                {
                    "id": "US-001",
                    "title": "A broken story",
                    "passes": False,
                    "_dlq": True,
                    "_dlqMetadata": {"timestamp": "2025-06-01T10:00:00+00:00", "retryCount": 3, "reason": "Exhausted"},
                },
                {"id": "US-002", "title": "Normal story", "passes": False},
            ],
        )
        with patch.object(main, "PRD_FILE", prd_path):
            args = SimpleNamespace(json_output=False)
            main.cmd_dlq_list(args)

        out = capsys.readouterr().out
        assert "US-001" in out
        assert "A broken story" in out
        assert "US-002" not in out

    def test_json_output(self, tmp_path, capsys):
        prd_path = _make_prd(
            tmp_path,
            [
                {
                    "id": "US-001",
                    "title": "A broken story",
                    "passes": False,
                    "_dlq": True,
                    "_dlqMetadata": {"timestamp": "2025-06-01T10:00:00+00:00", "retryCount": 3, "reason": "x"},
                },
            ],
        )
        with patch.object(main, "PRD_FILE", prd_path):
            args = SimpleNamespace(json_output=True)
            main.cmd_dlq_list(args)

        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["id"] == "US-001"
        assert "dlqMetadata" in data[0]

    def test_empty_dlq(self, tmp_path, capsys):
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-001", "title": "Normal", "passes": False},
            ],
        )
        with patch.object(main, "PRD_FILE", prd_path):
            args = SimpleNamespace(json_output=False)
            main.cmd_dlq_list(args)

        out = capsys.readouterr().out
        assert "No stories" in out


# ── cmd_dlq_replay ─────────────────────────────────────────────────────────


class TestCmdDlqReplay:
    def test_replay_clears_dlq(self, tmp_path):
        prd_path = _make_prd(
            tmp_path,
            [
                {
                    "id": "US-001",
                    "title": "t",
                    "passes": False,
                    "_dlq": True,
                    "_dlqMetadata": {"timestamp": "2025-06-01T10:00:00+00:00", "retryCount": 3, "reason": "x"},
                },
            ],
        )
        retry_path = _make_retry_counts(tmp_path, {"US-001": 3})
        scratch = tmp_path / ".spiral"
        audit_log = scratch / "audit.log"
        with patch.multiple(
            main, PRD_FILE=prd_path, RETRY_COUNTS=retry_path, SCRATCH_DIR=scratch, DLQ_AUDIT_LOG=audit_log
        ):
            scratch.mkdir(exist_ok=True)
            args = SimpleNamespace(story="US-001", dry_run=False)
            main.cmd_dlq_replay(args)

        prd = json.loads(prd_path.read_text())
        story = prd["userStories"][0]
        assert "_dlq" not in story
        assert "_dlqMetadata" not in story

    def test_replay_resets_retry_count(self, tmp_path):
        prd_path = _make_prd(
            tmp_path,
            [
                {
                    "id": "US-001",
                    "title": "t",
                    "passes": False,
                    "_dlq": True,
                    "_dlqMetadata": {"timestamp": "2025-06-01T10:00:00+00:00", "retryCount": 3, "reason": "x"},
                },
            ],
        )
        retry_path = _make_retry_counts(tmp_path, {"US-001": 3, "US-002": 5})
        scratch = tmp_path / ".spiral"
        audit_log = scratch / "audit.log"
        with patch.multiple(
            main, PRD_FILE=prd_path, RETRY_COUNTS=retry_path, SCRATCH_DIR=scratch, DLQ_AUDIT_LOG=audit_log
        ):
            scratch.mkdir(exist_ok=True)
            args = SimpleNamespace(story="US-001", dry_run=False)
            main.cmd_dlq_replay(args)

        counts = json.loads(retry_path.read_text())
        assert counts["US-001"] == 0
        assert counts["US-002"] == 5  # unaffected

    def test_replay_writes_audit_log(self, tmp_path):
        prd_path = _make_prd(
            tmp_path,
            [
                {
                    "id": "US-001",
                    "title": "t",
                    "passes": False,
                    "_dlq": True,
                    "_dlqMetadata": {"timestamp": "2025-06-01T10:00:00+00:00", "retryCount": 3, "reason": "x"},
                },
            ],
        )
        retry_path = _make_retry_counts(tmp_path, {"US-001": 3})
        scratch = tmp_path / ".spiral"
        audit_log = scratch / "audit.log"
        with patch.multiple(
            main, PRD_FILE=prd_path, RETRY_COUNTS=retry_path, SCRATCH_DIR=scratch, DLQ_AUDIT_LOG=audit_log
        ):
            scratch.mkdir(exist_ok=True)
            args = SimpleNamespace(story="US-001", dry_run=False)
            main.cmd_dlq_replay(args)

        entry = json.loads(audit_log.read_text().strip())
        assert entry["event"] == "dlq_replay"
        assert entry["story_id"] == "US-001"

    def test_replay_fails_for_non_dlq_story(self, tmp_path):
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-001", "title": "t", "passes": False},
            ],
        )
        retry_path = _make_retry_counts(tmp_path, {"US-001": 2})
        scratch = tmp_path / ".spiral"
        with patch.multiple(
            main, PRD_FILE=prd_path, RETRY_COUNTS=retry_path, SCRATCH_DIR=scratch, DLQ_AUDIT_LOG=scratch / "audit.log"
        ):
            scratch.mkdir(exist_ok=True)
            args = SimpleNamespace(story="US-001", dry_run=False)
            with pytest.raises(SystemExit) as exc:
                main.cmd_dlq_replay(args)
            assert exc.value.code == 1

    def test_replay_fails_for_unknown_story(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        retry_path = _make_retry_counts(tmp_path, {})
        scratch = tmp_path / ".spiral"
        with patch.multiple(
            main, PRD_FILE=prd_path, RETRY_COUNTS=retry_path, SCRATCH_DIR=scratch, DLQ_AUDIT_LOG=scratch / "audit.log"
        ):
            scratch.mkdir(exist_ok=True)
            args = SimpleNamespace(story="US-999", dry_run=False)
            with pytest.raises(SystemExit) as exc:
                main.cmd_dlq_replay(args)
            assert exc.value.code == 1

    def test_dry_run_does_not_modify_prd(self, tmp_path):
        prd_path = _make_prd(
            tmp_path,
            [
                {
                    "id": "US-001",
                    "title": "t",
                    "passes": False,
                    "_dlq": True,
                    "_dlqMetadata": {"timestamp": "2025-06-01T10:00:00+00:00", "retryCount": 3, "reason": "x"},
                },
            ],
        )
        retry_path = _make_retry_counts(tmp_path, {"US-001": 3})
        original = prd_path.read_text()
        scratch = tmp_path / ".spiral"
        with patch.multiple(
            main, PRD_FILE=prd_path, RETRY_COUNTS=retry_path, SCRATCH_DIR=scratch, DLQ_AUDIT_LOG=scratch / "audit.log"
        ):
            scratch.mkdir(exist_ok=True)
            args = SimpleNamespace(story="US-001", dry_run=True)
            main.cmd_dlq_replay(args)

        assert prd_path.read_text() == original
