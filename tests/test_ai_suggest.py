"""Unit tests for ai_suggest.py — LLM story generation, cap checks, queue loading."""

import json
import os
import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from ai_suggest import _build_prompt, _suggest_via_llm, clear_queue, load_queue


# ── Helpers ────────────────────────────────────────────────────────────────


def _minimal_prd(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "productName": "TestProduct",
        "branchName": "main",
        "goals": [],
        "epics": [],
        "userStories": [],
    }
    base.update(kwargs)
    return base


def _mock_claude_success(stories: list[dict[str, Any]]) -> MagicMock:
    """Return a CompletedProcess mock that Claude CLI would return."""
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = json.dumps({"stories": stories})
    mock.stderr = ""
    return mock


# ── load_queue ─────────────────────────────────────────────────────────────


class TestLoadQueue:
    def test_missing_file_returns_empty(self, tmp_path: Any) -> None:
        result = load_queue(str(tmp_path / "missing.json"))
        assert result == []

    def test_loads_stories_list(self, tmp_path: Any) -> None:
        p = tmp_path / "queue.json"
        p.write_text(json.dumps({"stories": [{"title": "T1"}]}), encoding="utf-8")
        result = load_queue(str(p))
        assert result == [{"title": "T1"}]

    def test_malformed_json_returns_empty(self, tmp_path: Any) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        result = load_queue(str(p))
        assert result == []

    def test_missing_stories_key_returns_empty(self, tmp_path: Any) -> None:
        p = tmp_path / "nokey.json"
        p.write_text(json.dumps({"other": []}), encoding="utf-8")
        result = load_queue(str(p))
        assert result == []


# ── clear_queue ────────────────────────────────────────────────────────────


class TestClearQueue:
    def test_clears_queue_file(self, tmp_path: Any) -> None:
        p = tmp_path / "queue.json"
        p.write_text(json.dumps({"stories": [{"title": "Old"}]}), encoding="utf-8")
        clear_queue(str(p))
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["stories"] == []

    def test_no_error_on_missing_file(self, tmp_path: Any) -> None:
        # Should not raise even if file doesn't exist
        clear_queue(str(tmp_path / "nonexistent.json"))


# ── _build_prompt ──────────────────────────────────────────────────────────


class TestBuildPrompt:
    def test_includes_goals(self) -> None:
        prd = _minimal_prd(goals=["improve coverage", "reduce latency"])
        prompt = _build_prompt(prd, [], "", 3)
        assert "improve coverage" in prompt
        assert "reduce latency" in prompt

    def test_includes_existing_titles(self) -> None:
        prd = _minimal_prd()
        prompt = _build_prompt(prd, ["Story Alpha", "Story Beta"], "", 3)
        assert "Story Alpha" in prompt
        assert "Story Beta" in prompt

    def test_includes_focus(self) -> None:
        prd = _minimal_prd()
        prompt = _build_prompt(prd, [], "performance", 3)
        assert "performance" in prompt

    def test_no_focus_no_focus_line(self) -> None:
        prd = _minimal_prd()
        prompt = _build_prompt(prd, [], "", 3)
        assert "Focus area:" not in prompt

    def test_includes_n(self) -> None:
        prd = _minimal_prd()
        prompt = _build_prompt(prd, [], "", 7)
        assert "7" in prompt

    def test_no_goals_shows_placeholder(self) -> None:
        prd = _minimal_prd(goals=[])
        prompt = _build_prompt(prd, [], "", 3)
        assert "(no goals defined)" in prompt

    def test_no_titles_shows_none(self) -> None:
        prd = _minimal_prd()
        prompt = _build_prompt(prd, [], "", 3)
        assert "(none)" in prompt


# ── _suggest_via_llm ───────────────────────────────────────────────────────


class TestSuggestViaLlm:
    def test_zero_n_returns_empty(self) -> None:
        prd = _minimal_prd()
        result = _suggest_via_llm(prd, [], "", 0)
        assert result == []

    def test_cli_success_returns_stories(self) -> None:
        mock_stories = [
            {
                "title": "Add rate limiting to Phase R API calls",
                "priority": "medium",
                "description": "...",
                "acceptanceCriteria": ["lib/phases/phase_r.py includes retry with backoff"],
                "estimatedComplexity": "small",
            }
        ]
        with patch("ai_suggest.subprocess.run", return_value=_mock_claude_success(mock_stories)):
            prd = _minimal_prd(goals=["improve reliability"])
            result = _suggest_via_llm(prd, [], "", 1)

        assert len(result) == 1
        assert result[0]["title"] == "Add rate limiting to Phase R API calls"
        assert result[0]["_source"] == "ai-example"

    def test_cli_nonzero_exit_returns_empty(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"
        with patch("ai_suggest.subprocess.run", return_value=mock_result):
            prd = _minimal_prd()
            result = _suggest_via_llm(prd, [], "", 3)
        assert result == []

    def test_cli_timeout_returns_empty(self) -> None:
        with patch("ai_suggest.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 120)):
            prd = _minimal_prd()
            result = _suggest_via_llm(prd, [], "", 3)
        assert result == []

    def test_malformed_json_returns_empty(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json at all"
        with patch("ai_suggest.subprocess.run", return_value=mock_result):
            prd = _minimal_prd()
            result = _suggest_via_llm(prd, [], "", 3)
        assert result == []

    def test_strips_markdown_fences(self) -> None:
        stories = [{"title": "T", "priority": "medium", "description": "", "acceptanceCriteria": []}]
        fenced = f"```json\n{json.dumps({'stories': stories})}\n```"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fenced
        with patch("ai_suggest.subprocess.run", return_value=mock_result):
            prd = _minimal_prd()
            result = _suggest_via_llm(prd, [], "", 1)
        assert len(result) == 1
        assert result[0]["title"] == "T"

    def test_uses_env_model_override(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("SPIRAL_AI_SUGGEST_MODEL", "claude-sonnet-4-6")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"stories": []})
        with patch("ai_suggest.subprocess.run", return_value=mock_result) as mock_run:
            prd = _minimal_prd()
            _suggest_via_llm(prd, [], "", 2)
        cmd_args = mock_run.call_args[0][0]
        assert "claude-sonnet-4-6" in cmd_args


# ── CLI integration ────────────────────────────────────────────────────────


class TestCLI:
    @pytest.fixture()
    def prd_file(self, tmp_path: Any) -> str:
        prd = _minimal_prd(
            goals=["improve performance"],
            userStories=[
                {
                    "id": "US-001",
                    "title": "Alpha",
                    "passes": True,
                    "priority": "medium",
                    "description": "",
                    "acceptanceCriteria": [],
                    "dependencies": [],
                }
            ],
        )
        p = tmp_path / "prd.json"
        p.write_text(json.dumps(prd), encoding="utf-8")
        return str(p)

    def test_cli_at_max_pending_outputs_empty(self, prd_file: str, tmp_path: Any) -> None:
        out = str(tmp_path / "output.json")
        script = os.path.join(os.path.dirname(__file__), "..", "lib", "research", "ai_suggest.py")
        result = subprocess.run(
            [sys.executable, script, "--prd", prd_file, "--out", out, "--pending", "50", "--max-pending", "50"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        assert data["stories"] == []

    def test_cli_missing_prd_outputs_empty(self, tmp_path: Any) -> None:
        out = str(tmp_path / "output.json")
        script = os.path.join(os.path.dirname(__file__), "..", "lib", "research", "ai_suggest.py")
        result = subprocess.run(
            [sys.executable, script, "--prd", str(tmp_path / "missing.json"), "--out", out],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        assert data["stories"] == []
