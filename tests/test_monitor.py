"""Tests for lib/monitor.py — unified SPIRAL monitoring."""

import json
import os
import sys
import time
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import monitor  # noqa: E402

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_prd(tmp_path: Path, stories: list[dict]) -> Path:
    prd = {
        "productName": "TestProduct",
        "branchName": "main",
        "userStories": stories,
    }
    p = tmp_path / "prd.json"
    p.write_text(json.dumps(prd), encoding="utf-8")
    return p


def _make_retry(tmp_path: Path, counts: dict) -> Path:
    p = tmp_path / "retry-counts.json"
    p.write_text(json.dumps(counts), encoding="utf-8")
    return p


def _make_checkpoint(tmp_path: Path, data: dict) -> Path:
    scratch = tmp_path / ".spiral"
    scratch.mkdir(exist_ok=True)
    p = scratch / "_checkpoint.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _make_state(tmp_path: Path, passes: int, ts: str = "2026-03-20T10:00:00Z") -> Path:
    scratch = tmp_path / ".spiral"
    scratch.mkdir(exist_ok=True)
    p = scratch / "_monitor_state.json"
    p.write_text(json.dumps({"passed_count": passes, "timestamp": ts}), encoding="utf-8")
    return p


def _make_log(tmp_path: Path, content: str = "some log", age_secs: int = 0) -> Path:
    scratch = tmp_path / ".spiral"
    scratch.mkdir(exist_ok=True)
    p = scratch / "_last_run.log"
    p.write_text(content, encoding="utf-8")
    if age_secs > 0:
        old_time = time.time() - age_secs
        os.utime(str(p), (old_time, old_time))
    return p


# ── TestCheckStories ─────────────────────────────────────────────────────


class TestCheckStories:
    def test_empty_prd(self, tmp_path: Path) -> None:
        _make_prd(tmp_path, [])
        result = monitor._check_stories(tmp_path)
        assert result["total"] == 0
        assert result["passed"] == 0
        assert result["pass_pct"] == 0.0

    def test_mixed_statuses(self, tmp_path: Path) -> None:
        stories = [
            {"id": "US-1", "title": "A", "passes": True},
            {"id": "US-2", "title": "B", "passes": True},
            {"id": "US-3", "title": "C"},
            {"id": "US-4", "title": "D", "_dlq": True},
            {"id": "US-5", "title": "E", "_skipped": True},
        ]
        _make_prd(tmp_path, stories)
        _make_retry(tmp_path, {"US-3": 1})
        result = monitor._check_stories(tmp_path)
        assert result["total"] == 5
        assert result["passed"] == 2
        assert result["in_progress"] == 1
        assert result["failed"] == 1
        assert result["skipped"] == 1
        assert result["pending"] == 0
        assert result["pass_pct"] == 40.0

    def test_missing_prd_file(self, tmp_path: Path) -> None:
        result = monitor._check_stories(tmp_path)
        assert result["total"] == 0
        assert result["passed"] == 0

    def test_checkpoint_data(self, tmp_path: Path) -> None:
        _make_prd(tmp_path, [{"id": "US-1", "title": "A", "passes": True}])
        _make_checkpoint(tmp_path, {"run_id": "abc123", "iter": 5})
        result = monitor._check_stories(tmp_path)
        assert result["run_id"] == "abc123"
        assert result["iteration"] == 5


# ── TestCheckDelta ───────────────────────────────────────────────────────


class TestCheckDelta:
    def test_no_state_file(self, tmp_path: Path) -> None:
        state_path = tmp_path / ".spiral" / "_monitor_state.json"
        result = monitor._check_delta(10, state_path)
        assert result["previous"] == 0
        assert result["current"] == 10
        assert result["new_passed"] == 10
        assert result["stalled"] is False

    def test_positive_delta(self, tmp_path: Path) -> None:
        _make_state(tmp_path, 8)
        state_path = tmp_path / ".spiral" / "_monitor_state.json"
        result = monitor._check_delta(12, state_path)
        assert result["previous"] == 8
        assert result["current"] == 12
        assert result["new_passed"] == 4
        assert result["stalled"] is False

    def test_zero_delta_stalled(self, tmp_path: Path) -> None:
        _make_state(tmp_path, 10)
        state_path = tmp_path / ".spiral" / "_monitor_state.json"
        result = monitor._check_delta(10, state_path)
        assert result["new_passed"] == 0
        assert result["stalled"] is True

    def test_zero_delta_first_run_not_stalled(self, tmp_path: Path) -> None:
        """When previous == 0 and current == 0, not stalled (never started)."""
        _make_state(tmp_path, 0)
        state_path = tmp_path / ".spiral" / "_monitor_state.json"
        result = monitor._check_delta(0, state_path)
        assert result["stalled"] is False

    def test_corrupt_state_file(self, tmp_path: Path) -> None:
        scratch = tmp_path / ".spiral"
        scratch.mkdir(exist_ok=True)
        state_path = scratch / "_monitor_state.json"
        state_path.write_text("not json!!!", encoding="utf-8")
        result = monitor._check_delta(5, state_path)
        assert result["previous"] == 0
        assert result["new_passed"] == 5


# ── TestCheckRunHealth ───────────────────────────────────────────────────


class TestCheckRunHealth:
    def test_recent_log(self, tmp_path: Path) -> None:
        _make_log(tmp_path, "log content", age_secs=0)
        result = monitor._check_run_health(tmp_path / ".spiral")
        assert result["running"] is True
        assert result["log_age_secs"] >= 0

    def test_stale_log(self, tmp_path: Path) -> None:
        _make_log(tmp_path, "old log", age_secs=600)
        result = monitor._check_run_health(tmp_path / ".spiral")
        assert result["running"] is False
        assert result["log_age_secs"] >= 590

    def test_missing_log(self, tmp_path: Path) -> None:
        scratch = tmp_path / ".spiral"
        scratch.mkdir(exist_ok=True)
        result = monitor._check_run_health(scratch)
        assert result["running"] is False
        assert result["log_age_secs"] == -1


# ── TestCheckUi ──────────────────────────────────────────────────────────


class TestCheckUi:
    def test_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("monitor.urllib.request.urlopen", return_value=mock_resp):
            result = monitor._check_ui(5299)
        assert result["reachable"] is True
        assert result["status_code"] == 200
        assert result["response_ms"] >= 0

    def test_url_error(self) -> None:
        with patch(
            "monitor.urllib.request.urlopen",
            side_effect=urllib.error.URLError("conn refused"),
        ):
            result = monitor._check_ui(5299)
        assert result["reachable"] is False
        assert result["status_code"] == 0

    def test_http_error(self) -> None:
        err = urllib.error.HTTPError(
            url="http://localhost:5299/",
            code=500,
            msg="Internal Server Error",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )
        with patch("monitor.urllib.request.urlopen", side_effect=err):
            result = monitor._check_ui(5299)
        assert result["reachable"] is True
        assert result["status_code"] == 500


# ── TestDiagnose ─────────────────────────────────────────────────────────


class TestDiagnose:
    def test_no_issues(self, tmp_path: Path) -> None:
        _make_prd(tmp_path, [{"id": "US-1", "title": "A", "passes": True}])
        scratch = tmp_path / ".spiral"
        scratch.mkdir(exist_ok=True)
        with patch("monitor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            diags = monitor._diagnose(tmp_path, scratch)
        assert diags == []

    def test_stale_lock_file(self, tmp_path: Path) -> None:
        _make_prd(tmp_path, [])
        scratch = tmp_path / ".spiral"
        scratch.mkdir(exist_ok=True)
        lock = tmp_path / "prd.json.lock"
        lock.write_text("99999999", encoding="utf-8")
        with patch("monitor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            diags = monitor._diagnose(tmp_path, scratch)
        assert len(diags) >= 1
        assert diags[0]["check"] == "stale_locks"

    def test_recent_crash(self, tmp_path: Path) -> None:
        _make_prd(tmp_path, [])
        scratch = tmp_path / ".spiral"
        crash_dir = scratch / "crashes"
        crash_dir.mkdir(parents=True)
        crash_file = crash_dir / "crash_001.log"
        crash_file.write_text("segfault", encoding="utf-8")
        with patch("monitor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            diags = monitor._diagnose(tmp_path, scratch)
        assert any(d["check"] == "recent_crash" for d in diags)

    def test_corrupt_titles(self, tmp_path: Path) -> None:
        stories = [
            {"id": "US-1", "title": "US-1"},  # corrupt
            {"id": "US-2", "title": "Good title", "passes": True},
            {"id": "US-3", "title": "US-3"},  # corrupt
        ]
        _make_prd(tmp_path, stories)
        scratch = tmp_path / ".spiral"
        scratch.mkdir(exist_ok=True)
        with patch("monitor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            diags = monitor._diagnose(tmp_path, scratch)
        title_diags = [d for d in diags if d["check"] == "corrupt_titles"]
        assert len(title_diags) == 1
        assert "2 pending stories" in title_diags[0]["message"]

    def test_uncommitted_config(self, tmp_path: Path) -> None:
        _make_prd(tmp_path, [])
        scratch = tmp_path / ".spiral"
        scratch.mkdir(exist_ok=True)
        config = tmp_path / "spiral.config.sh"
        config.write_text("# config", encoding="utf-8")
        with patch("monitor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="spiral.config.sh\n", returncode=0)
            diags = monitor._diagnose(tmp_path, scratch)
        assert any(d["check"] == "uncommitted_config" for d in diags)


# ── TestNeedsAttention ───────────────────────────────────────────────────


class TestNeedsAttention:
    def test_all_green(self) -> None:
        assert monitor._needs_attention(
            {"stalled": False},
            {"running": True},
            {"reachable": True},
            [],
        ) is False

    def test_stalled(self) -> None:
        assert monitor._needs_attention(
            {"stalled": True},
            {"running": True},
            {"reachable": True},
            [],
        ) is True

    def test_not_running(self) -> None:
        assert monitor._needs_attention(
            {"stalled": False},
            {"running": False},
            {"reachable": True},
            [],
        ) is True

    def test_ui_down(self) -> None:
        assert monitor._needs_attention(
            {"stalled": False},
            {"running": True},
            {"reachable": False},
            [],
        ) is True

    def test_error_diagnostic(self) -> None:
        assert monitor._needs_attention(
            {"stalled": False},
            {"running": True},
            {"reachable": True},
            [{"severity": "error", "check": "crash", "message": "boom"}],
        ) is True

    def test_warning_only_ok(self) -> None:
        assert monitor._needs_attention(
            {"stalled": False},
            {"running": True},
            {"reachable": True},
            [{"severity": "warning", "check": "stale_locks", "message": "lock"}],
        ) is False


# ── TestRunMonitor (integration) ─────────────────────────────────────────


class TestRunMonitor:
    def test_returns_valid_json_all_keys(self, tmp_path: Path) -> None:
        stories = [
            {"id": "US-1", "title": "A", "passes": True},
            {"id": "US-2", "title": "B"},
        ]
        _make_prd(tmp_path, stories)
        _make_retry(tmp_path, {})
        scratch = tmp_path / ".spiral"
        scratch.mkdir(exist_ok=True)
        _make_log(tmp_path, "log line")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("monitor.urllib.request.urlopen", return_value=mock_resp), \
             patch("monitor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            result = monitor.run_monitor(project_root=tmp_path, ui_port=5299)

        assert result["schema"] == "monitor-v1"
        assert "timestamp" in result
        assert isinstance(result["needs_attention"], bool)
        assert result["status"]["total"] == 2
        assert result["status"]["passed"] == 1
        assert result["status"]["pending"] == 1
        assert "delta" in result
        assert "run_health" in result
        assert "ui_health" in result
        assert isinstance(result["diagnostics"], list)

    def test_state_file_written(self, tmp_path: Path) -> None:
        _make_prd(tmp_path, [{"id": "US-1", "title": "A", "passes": True}])
        scratch = tmp_path / ".spiral"
        scratch.mkdir(exist_ok=True)

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("monitor.urllib.request.urlopen", return_value=mock_resp), \
             patch("monitor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            monitor.run_monitor(project_root=tmp_path, ui_port=5299)

        state_path = scratch / "_monitor_state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["passed_count"] == 1
        assert "timestamp" in state

    def test_never_raises_on_missing_everything(self, tmp_path: Path) -> None:
        """run_monitor must not raise even with no files at all."""
        with patch("monitor.urllib.request.urlopen",
                    side_effect=urllib.error.URLError("nope")):
            result = monitor.run_monitor(project_root=tmp_path, ui_port=9999)
        assert result["schema"] == "monitor-v1"
        assert result["status"]["total"] == 0
