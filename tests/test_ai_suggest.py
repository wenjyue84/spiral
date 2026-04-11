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
from ai_suggest import _build_prompt, _suggest_via_llm, clear_queue, load_learned_patterns, load_queue

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
        prompt = _build_prompt(prd, [], [], "", 3)
        assert "improve coverage" in prompt
        assert "reduce latency" in prompt

    def test_includes_existing_titles(self) -> None:
        prd = _minimal_prd()
        prompt = _build_prompt(prd, ["Story Alpha", "Story Beta"], [], "", 3)
        assert "Story Alpha" in prompt
        assert "Story Beta" in prompt

    def test_includes_focus(self) -> None:
        prd = _minimal_prd()
        prompt = _build_prompt(prd, [], [], "performance", 3)
        assert "performance" in prompt

    def test_no_focus_no_focus_line(self) -> None:
        prd = _minimal_prd()
        prompt = _build_prompt(prd, [], [], "", 3)
        assert "Focus area:" not in prompt

    def test_includes_n(self) -> None:
        prd = _minimal_prd()
        prompt = _build_prompt(prd, [], [], "", 7)
        assert "7" in prompt

    def test_no_goals_shows_placeholder(self) -> None:
        prd = _minimal_prd(goals=[])
        prompt = _build_prompt(prd, [], [], "", 3)
        assert "(no goals defined)" in prompt

    def test_no_titles_shows_none(self) -> None:
        prd = _minimal_prd()
        prompt = _build_prompt(prd, [], [], "", 3)
        assert "(none)" in prompt


# ── _suggest_via_llm ───────────────────────────────────────────────────────


class TestSuggestViaLlm:
    def test_zero_n_returns_empty(self) -> None:
        prd = _minimal_prd()
        result = _suggest_via_llm(prd, [], [], "", 0)
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
            result = _suggest_via_llm(prd, [], [], "", 1)

        assert len(result) == 1
        assert result[0]["title"] == "Add rate limiting to Phase R API calls"
        assert result[0]["_source"] == "ai-example"

    def test_cli_nonzero_exit_returns_empty(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"
        with patch("ai_suggest.subprocess.run", return_value=mock_result):
            prd = _minimal_prd()
            result = _suggest_via_llm(prd, [], [], "", 3)
        assert result == []

    def test_cli_timeout_returns_empty(self) -> None:
        with patch("ai_suggest.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 120)):
            prd = _minimal_prd()
            result = _suggest_via_llm(prd, [], [], "", 3)
        assert result == []

    def test_malformed_json_returns_empty(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json at all"
        with patch("ai_suggest.subprocess.run", return_value=mock_result):
            prd = _minimal_prd()
            result = _suggest_via_llm(prd, [], [], "", 3)
        assert result == []

    def test_strips_markdown_fences(self) -> None:
        stories = [{"title": "T", "priority": "medium", "description": "", "acceptanceCriteria": []}]
        fenced = f"```json\n{json.dumps({'stories': stories})}\n```"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fenced
        with patch("ai_suggest.subprocess.run", return_value=mock_result):
            prd = _minimal_prd()
            result = _suggest_via_llm(prd, [], [], "", 1)
        assert len(result) == 1
        assert result[0]["title"] == "T"

    def test_uses_env_model_override(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("SPIRAL_AI_SUGGEST_MODEL", "claude-sonnet-4-6")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"stories": []})
        with patch("ai_suggest.subprocess.run", return_value=mock_result) as mock_run:
            prd = _minimal_prd()
            _suggest_via_llm(prd, [], [], "", 2)
        cmd_args = mock_run.call_args[0][0]
        assert "claude-sonnet-4-6" in cmd_args


# ── load_learned_patterns ──────────────────────────────────────────────────


class TestLoadLearnedPatterns:
    def test_missing_patterns_file_returns_empty(self, tmp_path: Any) -> None:
        result = load_learned_patterns(str(tmp_path))
        assert result == []

    def test_loads_patterns_from_latest_file(self, tmp_path: Any) -> None:
        # Create two pattern files with different iteration numbers
        patterns_1 = {
            "iteration": 1,
            "patterns": [
                {"pattern": "Small stories pass more often", "frequency": 5},
                {"pattern": "Use existing patterns from lib/", "frequency": 3},
            ],
        }
        patterns_2 = {
            "iteration": 2,
            "patterns": [
                {"pattern": "Always write tests first", "frequency": 8},
                {"pattern": "Check for existing utilities", "frequency": 6},
                {"pattern": "Avoid deep nesting", "frequency": 4},
            ],
        }
        (tmp_path / "learned_patterns_iter_1.json").write_text(json.dumps(patterns_1), encoding="utf-8")
        (tmp_path / "learned_patterns_iter_2.json").write_text(json.dumps(patterns_2), encoding="utf-8")

        result = load_learned_patterns(str(tmp_path))

        # Should load from iter_2 (latest), sorted by frequency descending
        assert len(result) == 3
        assert "Always write tests first (frequency: 8)" in result[0]
        assert "Check for existing utilities (frequency: 6)" in result[1]
        assert "Avoid deep nesting (frequency: 4)" in result[2]

    def test_extracts_top_5_patterns(self, tmp_path: Any) -> None:
        patterns_data = {
            "iteration": 1,
            "patterns": [
                {"pattern": f"Pattern {i}", "frequency": 10 - i} for i in range(10)
            ],
        }
        (tmp_path / "learned_patterns_iter_1.json").write_text(json.dumps(patterns_data), encoding="utf-8")

        result = load_learned_patterns(str(tmp_path))

        assert len(result) == 5
        # Should be top 5 by frequency (descending)
        assert "Pattern 0 (frequency: 10)" in result[0]
        assert "Pattern 4 (frequency: 6)" in result[4]

    def test_malformed_json_returns_empty(self, tmp_path: Any) -> None:
        (tmp_path / "learned_patterns_iter_1.json").write_text("not valid json", encoding="utf-8")
        result = load_learned_patterns(str(tmp_path))
        assert result == []

    def test_missing_patterns_key_returns_empty(self, tmp_path: Any) -> None:
        data = {"iteration": 1, "other": []}
        (tmp_path / "learned_patterns_iter_1.json").write_text(json.dumps(data), encoding="utf-8")
        result = load_learned_patterns(str(tmp_path))
        assert result == []


# ── _build_prompt with patterns ────────────────────────────────────────────


class TestBuildPromptWithPatterns:
    def test_includes_patterns_section(self) -> None:
        prd = _minimal_prd()
        patterns = ["- Pattern 1 (frequency: 10)", "- Pattern 2 (frequency: 8)"]
        prompt = _build_prompt(prd, [], [], "", 3, patterns=patterns)
        assert "Lessons Learned from Past Implementations:" in prompt
        assert "Pattern 1 (frequency: 10)" in prompt
        assert "Pattern 2 (frequency: 8)" in prompt

    def test_no_patterns_no_lessons_section(self) -> None:
        prd = _minimal_prd()
        prompt = _build_prompt(prd, [], [], "", 3, patterns=None)
        assert "Lessons Learned" not in prompt

    def test_empty_patterns_no_lessons_section(self) -> None:
        prd = _minimal_prd()
        prompt = _build_prompt(prd, [], [], "", 3, patterns=[])
        assert "Lessons Learned" not in prompt


# ── _suggest_via_llm with patterns ────────────────────────────────────────


class TestSuggestViaLlmWithPatterns:
    def test_passes_patterns_to_prompt(self) -> None:
        patterns = ["- Pattern A (frequency: 7)"]
        with patch("ai_suggest.subprocess.run", return_value=_mock_claude_success([])):
            prd = _minimal_prd()
            _suggest_via_llm(prd, [], [], "", 1, patterns=patterns)
        # The fact that this doesn't raise means patterns were passed through

    def test_patterns_in_llm_prompt(self) -> None:
        """Verify that patterns appear in the prompt sent to LLM."""
        patterns = ["- Small stories pass 80% of the time (frequency: 42)", "- Always test before commit (frequency: 35)"]
        captured_prompt = None

        def mock_run(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal captured_prompt
            captured_prompt = kwargs.get("input", "")
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = json.dumps({"stories": []})
            return mock

        with patch("ai_suggest.subprocess.run", side_effect=mock_run):
            prd = _minimal_prd()
            _suggest_via_llm(prd, [], [], "", 1, patterns=patterns)

        assert captured_prompt is not None
        assert "Lessons Learned from Past Implementations:" in captured_prompt
        assert "Small stories pass 80% of the time" in captured_prompt
        assert "Always test before commit" in captured_prompt


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
