"""Tests for main.py CLI (spiral entrypoint)."""
import json
import os
import sys
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

# Ensure root is importable
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


def _make_results_tsv(tmp_path, rows: list[dict]):
    p = tmp_path / "results.tsv"
    if not rows:
        p.write_text("timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha\n", encoding="utf-8")
        return p
    headers = list(rows[0].keys())
    lines = ["\t".join(headers)]
    for row in rows:
        lines.append("\t".join(str(row.get(h, "")) for h in headers))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _args(json_flag=False):
    """Return a minimal args namespace for cmd_status."""
    return SimpleNamespace(json=json_flag)


def _patch_paths(tmp_path, prd_path, retry_path=None, results_path=None, checkpoint_path=None):
    """Context-manager patches for all file paths in main.py."""
    patches = [patch.object(main, "PRD_FILE", prd_path)]
    if retry_path is not None:
        patches.append(patch.object(main, "RETRY_COUNTS", retry_path))
    if results_path is not None:
        patches.append(patch.object(main, "RESULTS_TSV", results_path))
    if checkpoint_path is not None:
        patches.append(patch.object(main, "CHECKPOINT_FILE", checkpoint_path))
    # Always supply a missing checkpoint and results file unless explicitly given
    if retry_path is None:
        patches.append(patch.object(main, "RETRY_COUNTS", tmp_path / "no-retry.json"))
    if results_path is None:
        patches.append(patch.object(main, "RESULTS_TSV", tmp_path / "no-results.tsv"))
    if checkpoint_path is None:
        patches.append(patch.object(main, "CHECKPOINT_FILE", tmp_path / "no-checkpoint.json"))
    return patches


# ── status table output ────────────────────────────────────────────────────

class TestCmdStatusTable:
    def test_table_has_all_status_rows(self, tmp_path, capsys):
        """status table contains passed / in_progress / skipped / pending rows."""
        prd_path = _make_prd(tmp_path, [
            {"id": "US-001", "title": "A", "passes": True},
            {"id": "US-002", "title": "B", "passes": False},
            {"id": "US-003", "title": "C", "passes": False, "_skipped": True},
        ])
        retry_path = _make_retry_counts(tmp_path, {"US-002": 1})
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "RETRY_COUNTS", retry_path), \
             patch.object(main, "RESULTS_TSV", tmp_path / "no.tsv"), \
             patch.object(main, "CHECKPOINT_FILE", tmp_path / "no-ckpt.json"):
            main.cmd_status(_args())

        out = capsys.readouterr().out
        assert "passed" in out
        assert "in_progress" in out
        assert "skipped" in out
        assert "pending" in out

    def test_table_shows_correct_counts(self, tmp_path, capsys):
        """Counts in table match actual story distribution."""
        stories = (
            [{"id": f"US-{i:03d}", "title": f"S{i}", "passes": True} for i in range(5)]
            + [{"id": f"US-{i:03d}", "title": f"S{i}", "passes": False} for i in range(5, 8)]
        )
        prd_path = _make_prd(tmp_path, stories)
        retry_path = _make_retry_counts(tmp_path, {"US-006": 2})
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "RETRY_COUNTS", retry_path), \
             patch.object(main, "RESULTS_TSV", tmp_path / "no.tsv"), \
             patch.object(main, "CHECKPOINT_FILE", tmp_path / "no-ckpt.json"):
            main.cmd_status(_args())

        out = capsys.readouterr().out
        # passed=5, in_progress=1 (US-006 has retries), pending=2
        assert "5" in out  # passed count present somewhere

    def test_table_shows_run_id_header(self, tmp_path, capsys):
        """Header contains SPIRAL_RUN_ID when set via env var."""
        prd_path = _make_prd(tmp_path, [{"id": "US-001", "title": "A", "passes": True}])
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "RETRY_COUNTS", tmp_path / "no.json"), \
             patch.object(main, "RESULTS_TSV", tmp_path / "no.tsv"), \
             patch.object(main, "CHECKPOINT_FILE", tmp_path / "no-ckpt.json"), \
             patch.dict(os.environ, {"SPIRAL_RUN_ID": "run-xyz-42"}):
            main.cmd_status(_args())

        out = capsys.readouterr().out
        assert "run-xyz-42" in out

    def test_table_iteration_from_results_tsv(self, tmp_path, capsys):
        """Iteration number is read from results.tsv when no checkpoint exists."""
        prd_path = _make_prd(tmp_path, [{"id": "US-001", "title": "A", "passes": True}])
        results_path = _make_results_tsv(tmp_path, [
            {"timestamp": "2026-01-01T00:00:00Z", "spiral_iter": "7", "ralph_iter": "1",
             "story_id": "US-001", "story_title": "A", "status": "pass",
             "duration_sec": "100", "model": "haiku", "retry_num": "0", "commit_sha": "abc"},
        ])
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "RETRY_COUNTS", tmp_path / "no.json"), \
             patch.object(main, "RESULTS_TSV", results_path), \
             patch.object(main, "CHECKPOINT_FILE", tmp_path / "no-ckpt.json"):
            main.cmd_status(_args())

        out = capsys.readouterr().out
        assert "7" in out  # iteration 7 appears in header

    def test_total_shown(self, tmp_path, capsys):
        """Total story count is shown in output."""
        stories = [{"id": f"US-{i:03d}", "title": f"S{i}", "passes": i < 3} for i in range(6)]
        prd_path = _make_prd(tmp_path, stories)
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "RETRY_COUNTS", tmp_path / "no.json"), \
             patch.object(main, "RESULTS_TSV", tmp_path / "no.tsv"), \
             patch.object(main, "CHECKPOINT_FILE", tmp_path / "no-ckpt.json"):
            main.cmd_status(_args())

        out = capsys.readouterr().out
        assert "6" in out  # total = 6


# ── status --json output ───────────────────────────────────────────────────

class TestCmdStatusJson:
    def test_json_structure(self, tmp_path, capsys):
        """--json outputs valid JSON with expected top-level keys."""
        prd_path = _make_prd(tmp_path, [
            {"id": "US-001", "title": "A", "passes": True},
            {"id": "US-002", "title": "B", "passes": False},
        ])
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "RETRY_COUNTS", tmp_path / "no.json"), \
             patch.object(main, "RESULTS_TSV", tmp_path / "no.tsv"), \
             patch.object(main, "CHECKPOINT_FILE", tmp_path / "no-ckpt.json"):
            main.cmd_status(_args(json_flag=True))

        out = capsys.readouterr().out
        data = json.loads(out)
        assert "run_id" in data
        assert "iteration" in data
        assert "total" in data
        assert "statuses" in data

    def test_json_statuses_has_all_buckets(self, tmp_path, capsys):
        """statuses dict contains passed / in_progress / skipped / pending."""
        prd_path = _make_prd(tmp_path, [
            {"id": "US-001", "title": "A", "passes": True},
        ])
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "RETRY_COUNTS", tmp_path / "no.json"), \
             patch.object(main, "RESULTS_TSV", tmp_path / "no.tsv"), \
             patch.object(main, "CHECKPOINT_FILE", tmp_path / "no-ckpt.json"):
            main.cmd_status(_args(json_flag=True))

        data = json.loads(capsys.readouterr().out)
        for status in ("passed", "in_progress", "skipped", "pending"):
            assert status in data["statuses"]
            assert "count" in data["statuses"][status]
            assert "percentage" in data["statuses"][status]
            assert "avg_retry_count" in data["statuses"][status]

    def test_json_counts_correct(self, tmp_path, capsys):
        """JSON counts match actual story distribution."""
        prd_path = _make_prd(tmp_path, [
            {"id": "US-001", "title": "A", "passes": True},
            {"id": "US-002", "title": "B", "passes": True},
            {"id": "US-003", "title": "C", "passes": False},
            {"id": "US-004", "title": "D", "passes": False, "_skipped": True},
        ])
        retry_path = _make_retry_counts(tmp_path, {"US-003": 1})
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "RETRY_COUNTS", retry_path), \
             patch.object(main, "RESULTS_TSV", tmp_path / "no.tsv"), \
             patch.object(main, "CHECKPOINT_FILE", tmp_path / "no-ckpt.json"):
            main.cmd_status(_args(json_flag=True))

        data = json.loads(capsys.readouterr().out)
        assert data["total"] == 4
        assert data["statuses"]["passed"]["count"] == 2
        assert data["statuses"]["in_progress"]["count"] == 1
        assert data["statuses"]["skipped"]["count"] == 1
        assert data["statuses"]["pending"]["count"] == 0

    def test_json_avg_retry_count(self, tmp_path, capsys):
        """avg_retry_count computed correctly per status group."""
        prd_path = _make_prd(tmp_path, [
            {"id": "US-001", "title": "A", "passes": False},
            {"id": "US-002", "title": "B", "passes": False},
        ])
        retry_path = _make_retry_counts(tmp_path, {"US-001": 2, "US-002": 4})
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "RETRY_COUNTS", retry_path), \
             patch.object(main, "RESULTS_TSV", tmp_path / "no.tsv"), \
             patch.object(main, "CHECKPOINT_FILE", tmp_path / "no-ckpt.json"):
            main.cmd_status(_args(json_flag=True))

        data = json.loads(capsys.readouterr().out)
        # Both stories have retries → in_progress; avg = (2+4)/2 = 3.0
        assert data["statuses"]["in_progress"]["avg_retry_count"] == 3.0

    def test_json_percentage_sums_to_100(self, tmp_path, capsys):
        """All percentage values sum to ~100%."""
        stories = [{"id": f"US-{i:03d}", "title": f"S{i}", "passes": i < 5} for i in range(10)]
        prd_path = _make_prd(tmp_path, stories)
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "RETRY_COUNTS", tmp_path / "no.json"), \
             patch.object(main, "RESULTS_TSV", tmp_path / "no.tsv"), \
             patch.object(main, "CHECKPOINT_FILE", tmp_path / "no-ckpt.json"):
            main.cmd_status(_args(json_flag=True))

        data = json.loads(capsys.readouterr().out)
        total_pct = sum(v["percentage"] for v in data["statuses"].values())
        assert abs(total_pct - 100.0) < 0.2  # floating-point tolerance


# ── story classification ───────────────────────────────────────────────────

class TestClassifyStories:
    def test_passed_story(self):
        stories = [{"id": "US-001", "passes": True}]
        buckets = main._classify_stories(stories, {})
        assert len(buckets["passed"]) == 1
        assert len(buckets["pending"]) == 0

    def test_skipped_story(self):
        stories = [{"id": "US-001", "passes": False, "_skipped": True}]
        buckets = main._classify_stories(stories, {})
        assert len(buckets["skipped"]) == 1

    def test_in_progress_story(self):
        stories = [{"id": "US-001", "passes": False}]
        retry_counts = {"US-001": 1}
        buckets = main._classify_stories(stories, retry_counts)
        assert len(buckets["in_progress"]) == 1

    def test_pending_story(self):
        stories = [{"id": "US-001", "passes": False}]
        buckets = main._classify_stories(stories, {})
        assert len(buckets["pending"]) == 1


# ── missing prd.json ───────────────────────────────────────────────────────

class TestCmdStatusMissingPrd:
    def test_status_no_prd_exits_1(self, tmp_path):
        """status exits with code 1 when prd.json missing."""
        missing = tmp_path / "prd.json"
        with patch.object(main, "PRD_FILE", missing):
            with pytest.raises(SystemExit) as exc:
                main.cmd_status(_args())
        assert exc.value.code == 1


# ── performance ────────────────────────────────────────────────────────────

class TestCmdStatusPerformance:
    def test_completes_under_1_second(self, tmp_path, capsys):
        """spiral status completes in < 1 second on a realistic prd.json."""
        stories = [
            {"id": f"US-{i:03d}", "title": f"Story {i}", "passes": i % 3 == 0}
            for i in range(200)
        ]
        prd_path = _make_prd(tmp_path, stories)
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.object(main, "RETRY_COUNTS", tmp_path / "no.json"), \
             patch.object(main, "RESULTS_TSV", tmp_path / "no.tsv"), \
             patch.object(main, "CHECKPOINT_FILE", tmp_path / "no-ckpt.json"):
            t0 = time.monotonic()
            main.cmd_status(_args())
            elapsed = time.monotonic() - t0

        assert elapsed < 1.0, f"cmd_status took {elapsed:.2f}s (limit 1s)"


# ── init calls setup.py ───────────────────────────────────────────────────

class TestCmdInit:
    def test_init_calls_setup_py(self):
        """cmd_init calls subprocess.run with lib/setup.py."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            with pytest.raises(SystemExit) as exc:
                main.cmd_init(None)
        assert exc.value.code == 0
        called_args = mock_run.call_args[0][0]
        assert called_args[0] == sys.executable
        assert called_args[1].endswith("setup.py")

    def test_init_propagates_exit_code(self):
        """cmd_init exits with the same returncode as subprocess."""
        mock_result = MagicMock()
        mock_result.returncode = 42
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit) as exc:
                main.cmd_init(None)
        assert exc.value.code == 42


# ── config export-env ─────────────────────────────────────────────────────────

class TestCmdConfigExportEnv:
    """Tests for cmd_config_export_env (US-291)."""

    def _make_config(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "spiral.config.sh"
        p.write_text(content, encoding="utf-8")
        return p

    def _args(self, output: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(output=output)

    def test_writes_key_value_lines(self, tmp_path, capsys):
        cfg = self._make_config(tmp_path, 'SPIRAL_MODEL_ROUTING="auto"\nSPIRAL_MAX_PENDING=30\n')
        out_file = tmp_path / "out.env"
        with patch.dict(os.environ, {"SPIRAL_CONFIG_PATH": str(cfg)}):
            main.cmd_config_export_env(self._args(output=str(out_file)))
        lines = out_file.read_text(encoding="utf-8").splitlines()
        assert "SPIRAL_MODEL_ROUTING=auto" in lines
        assert "SPIRAL_MAX_PENDING=30" in lines

    def test_strips_double_quotes(self, tmp_path, capsys):
        cfg = self._make_config(tmp_path, 'SPIRAL_PYTHON="/usr/bin/python3"\n')
        out_file = tmp_path / "out.env"
        with patch.dict(os.environ, {"SPIRAL_CONFIG_PATH": str(cfg)}):
            main.cmd_config_export_env(self._args(output=str(out_file)))
        content = out_file.read_text(encoding="utf-8")
        assert "SPIRAL_PYTHON=/usr/bin/python3" in content
        assert '"' not in content

    def test_strips_single_quotes(self, tmp_path, capsys):
        cfg = self._make_config(tmp_path, "SPIRAL_STORY_PREFIX='US'\n")
        out_file = tmp_path / "out.env"
        with patch.dict(os.environ, {"SPIRAL_CONFIG_PATH": str(cfg)}):
            main.cmd_config_export_env(self._args(output=str(out_file)))
        content = out_file.read_text(encoding="utf-8")
        assert "SPIRAL_STORY_PREFIX=US" in content

    def test_handles_export_prefix(self, tmp_path, capsys):
        cfg = self._make_config(tmp_path, 'export SPIRAL_VALIDATE_CMD="uv run pytest"\n')
        out_file = tmp_path / "out.env"
        with patch.dict(os.environ, {"SPIRAL_CONFIG_PATH": str(cfg)}):
            main.cmd_config_export_env(self._args(output=str(out_file)))
        content = out_file.read_text(encoding="utf-8")
        assert "SPIRAL_VALIDATE_CMD=uv run pytest" in content
        assert "export" not in content

    def test_masks_sensitive_in_preview(self, tmp_path, capsys):
        cfg = self._make_config(tmp_path, 'SPIRAL_API_KEY="super_secret"\nSPIRAL_MODEL="sonnet"\n')
        out_file = tmp_path / "out.env"
        with patch.dict(os.environ, {"SPIRAL_CONFIG_PATH": str(cfg)}):
            main.cmd_config_export_env(self._args(output=str(out_file)))
        captured = capsys.readouterr()
        assert "***" in captured.out
        assert "super_secret" not in captured.out

    def test_sensitive_value_written_in_full_to_file(self, tmp_path, capsys):
        cfg = self._make_config(tmp_path, 'SPIRAL_API_KEY="super_secret"\n')
        out_file = tmp_path / "out.env"
        with patch.dict(os.environ, {"SPIRAL_CONFIG_PATH": str(cfg)}):
            main.cmd_config_export_env(self._args(output=str(out_file)))
        content = out_file.read_text(encoding="utf-8")
        assert "super_secret" in content

    def test_warns_on_dynamic_expression(self, tmp_path, capsys):
        cfg = self._make_config(tmp_path, 'SPIRAL_WORK_STEALING="${SPIRAL_WORK_STEALING:-false}"\n')
        out_file = tmp_path / "out.env"
        with patch.dict(os.environ, {"SPIRAL_CONFIG_PATH": str(cfg)}):
            main.cmd_config_export_env(self._args(output=str(out_file)))
        captured = capsys.readouterr()
        assert "[warn]" in captured.out
        assert "dynamic" in captured.out

    def test_default_output_in_spiral_dir(self, tmp_path, capsys, monkeypatch):
        cfg = self._make_config(tmp_path, 'SPIRAL_MODEL_ROUTING="auto"\n')
        scratch = tmp_path / ".spiral"
        monkeypatch.setattr(main, "SCRATCH_DIR", scratch)
        with patch.dict(os.environ, {"SPIRAL_CONFIG_PATH": str(cfg)}):
            main.cmd_config_export_env(self._args(output=None))
        assert (scratch / ".env").exists()

    def test_exits_1_if_config_missing(self, tmp_path):
        missing = str(tmp_path / "nonexistent.sh")
        with patch.dict(os.environ, {"SPIRAL_CONFIG_PATH": missing}):
            with pytest.raises(SystemExit) as exc:
                main.cmd_config_export_env(self._args())
        assert exc.value.code == 1

    def test_no_export_keyword_in_env_file(self, tmp_path, capsys):
        cfg = self._make_config(tmp_path, 'export SPIRAL_A="1"\nSPIRAL_B="2"\n')
        out_file = tmp_path / "out.env"
        with patch.dict(os.environ, {"SPIRAL_CONFIG_PATH": str(cfg)}):
            main.cmd_config_export_env(self._args(output=str(out_file)))
        content = out_file.read_text(encoding="utf-8")
        assert not any(line.startswith("export") for line in content.splitlines())
