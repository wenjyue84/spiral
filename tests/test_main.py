"""Tests for main.py CLI (spiral entrypoint)."""
import json
import os
import sys
import subprocess
from pathlib import Path
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


# ── status output format ───────────────────────────────────────────────────

class TestCmdStatus:
    def test_status_output_format(self, tmp_path, capsys):
        """status prints 'X/Y stories complete (Z%) → N pending'."""
        prd_path = _make_prd(tmp_path, [
            {"id": "US-001", "title": "A", "passes": True},
            {"id": "US-002", "title": "B", "passes": False},
            {"id": "US-003", "title": "C", "passes": True},
        ])
        with patch.object(main, "PRD_FILE", prd_path):
            main.cmd_status(None)

        out = capsys.readouterr().out.strip()
        assert out == "2/3 stories complete (66%) -> 1 pending"

    def test_status_all_complete(self, tmp_path, capsys):
        """status shows 100% when all stories pass."""
        prd_path = _make_prd(tmp_path, [
            {"id": "US-001", "title": "A", "passes": True},
            {"id": "US-002", "title": "B", "passes": True},
        ])
        with patch.object(main, "PRD_FILE", prd_path):
            main.cmd_status(None)

        out = capsys.readouterr().out.strip()
        assert "2/2" in out
        assert "100%" in out
        assert "0 pending" in out

    def test_status_no_prd(self, tmp_path, capsys):
        """status exits with code 1 when prd.json missing."""
        missing = tmp_path / "prd.json"
        with patch.object(main, "PRD_FILE", missing):
            with pytest.raises(SystemExit) as exc:
                main.cmd_status(None)
        assert exc.value.code == 1


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
