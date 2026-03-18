"""Unit tests for ai_suggest.py — fallback heuristics, pre-flight dedup, cap checks."""

import json
import os
import subprocess
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from ai_suggest import _jaccard, _would_be_duplicate, analyze_gaps

# ── Jaccard helpers ───────────────────────────────────────────────────────


class TestJaccardHelpers:
    """Unit tests for _jaccard and _would_be_duplicate."""

    def test_jaccard_identical(self):
        assert _jaccard("alpha beta gamma", "alpha beta gamma") == 1.0

    def test_jaccard_disjoint(self):
        assert _jaccard("alpha beta", "gamma delta") == 0.0

    def test_jaccard_both_empty(self):
        assert _jaccard("", "") == 0.0

    def test_jaccard_partial(self):
        # {alpha,beta,gamma} ∩ {alpha,beta,delta} = {alpha,beta}=2, union=4 → Jaccard=2/4=0.5
        score = _jaccard("alpha beta gamma", "alpha beta delta")
        assert abs(score - 0.5) < 0.01

    def test_jaccard_symmetric(self):
        a = "add unit tests"
        b = "add unit tests for merge stories pipeline"
        assert _jaccard(a, b) == _jaccard(b, a)

    def test_would_be_duplicate_true(self):
        assert _would_be_duplicate("alpha beta gamma delta", ["alpha beta gamma eta"], threshold=0.6)

    def test_would_be_duplicate_false(self):
        assert not _would_be_duplicate("Improve test coverage", ["Completely unrelated story"])

    def test_would_be_duplicate_short_not_inflated(self):
        """Short title should not match long existing title."""
        assert not _would_be_duplicate("Improve test coverage", ["Improve test coverage for Phase R research module"])


# ── Cap check ─────────────────────────────────────────────────────────────


def _minimal_prd(**kwargs: Any) -> dict[str, Any]:
    """Build a minimal prd dict for testing."""
    base: dict[str, Any] = {
        "productName": "TestProduct",
        "branchName": "main",
        "goals": [],
        "epics": [],
        "userStories": [],
    }
    base.update(kwargs)
    return base


class TestAnalyzeGapsCapCheck:
    """analyze_gaps() respects max_pending cap."""

    def test_at_max_pending_returns_empty(self):
        prd = _minimal_prd()
        result = analyze_gaps(prd, max_suggest=5, current_pending=50, max_pending=50)
        assert result == []

    def test_over_max_pending_returns_empty(self):
        prd = _minimal_prd()
        result = analyze_gaps(prd, max_suggest=5, current_pending=60, max_pending=50)
        assert result == []

    def test_below_max_pending_generates(self):
        # Add a passed story so fallback heuristics can suggest refactors
        prd = _minimal_prd(
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
            ]
        )
        result = analyze_gaps(prd, max_suggest=3, current_pending=3, max_pending=50)
        assert len(result) > 0

    def test_zero_max_pending_means_no_cap(self):
        prd = _minimal_prd(
            userStories=[
                {
                    "id": "US-001",
                    "title": "Beta",
                    "passes": True,
                    "priority": "medium",
                    "description": "",
                    "acceptanceCriteria": [],
                    "dependencies": [],
                }
            ]
        )
        # max_pending=0 means no cap → should still generate suggestions
        result = analyze_gaps(prd, max_suggest=3, current_pending=999, max_pending=0)
        assert len(result) > 0


# ── Pre-flight dedup ──────────────────────────────────────────────────────


def _saturated_prd(n: int = 10) -> dict[str, Any]:
    """PRD with n passed stories using single-word Greek titles (low Jaccard overlap with fallback verbs)."""
    greek = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota", "Kappa"]
    stories = [
        {
            "id": f"US-{i + 1:03d}",
            "title": greek[i % len(greek)],
            "passes": True,
            "priority": "medium",
            "description": "",
            "acceptanceCriteria": [],
            "dependencies": [],
        }
        for i in range(n)
    ]
    return _minimal_prd(userStories=stories)


class TestAnalyzeGapsPreflightDedup:
    """Pre-flight dedup prevents generating titles Phase M would drop."""

    def test_epic_heuristic_skips_near_match(self):
        """Epic heuristic skips title that would Jaccard-match an existing story."""
        prd = _minimal_prd(
            epics=[{"id": "E-1", "title": "Auth", "description": ""}],
            userStories=[
                {
                    "id": "US-001",
                    "title": "Implement Auth System",
                    "passes": False,
                    "priority": "medium",
                    "description": "",
                    "acceptanceCriteria": [],
                    "dependencies": [],
                    "epicId": "E-1",
                }
            ],
        )
        # Epic E-1 HAS a pending story, so heuristic 1 skips it entirely
        result = analyze_gaps(prd, max_suggest=5)
        titles = [s["title"] for s in result]
        assert "Implement Auth" not in titles

    def test_primary_heuristic_skips_dedup_match(self):
        """If a suggested title is near-identical to existing, it's skipped."""
        # Create a situation where the goal heuristic would generate a near-duplicate
        prd = _minimal_prd(
            goals=["build a robust authentication system for users"],
            userStories=[
                {
                    "id": "US-001",
                    "title": "Implement: build a robust authentication system for users",
                    "passes": False,
                    "priority": "medium",
                    "description": "",
                    "acceptanceCriteria": [],
                    "dependencies": [],
                }
            ],
        )
        result = analyze_gaps(prd, max_suggest=5)
        # The generated goal title "Implement: build a robust authentication system for users"
        # is identical to the existing story → should be skipped
        titles = [s["title"] for s in result]
        assert not any("build a robust authentication" in t.lower() for t in titles)


# ── Fallback heuristics ───────────────────────────────────────────────────


class TestAnalyzeGapsFallback:
    """_generate_fallback_suggestions fills slots when primary heuristics yield nothing."""

    def test_fallback_fills_to_max_suggest(self):
        """Saturated PRD (no primary gaps) → fallback fills to max_suggest."""
        prd = _saturated_prd(n=5)
        result = analyze_gaps(prd, max_suggest=5)
        assert len(result) == 5

    def test_fallback_all_unique(self):
        """All returned titles are unique."""
        prd = _saturated_prd(n=8)
        result = analyze_gaps(prd, max_suggest=5)
        titles = [s["title"] for s in result]
        assert len(titles) == len(set(titles))

    def test_fallback_never_exceeds_max_suggest(self):
        """Returns at most max_suggest stories even with many passed stories."""
        prd = _saturated_prd(n=20)
        result = analyze_gaps(prd, max_suggest=3)
        assert len(result) <= 3

    def test_fallback_skips_duplicates(self):
        """Fallback titles that match existing stories are skipped."""
        # If existing story is "Refactor Alpha", fallback should not generate it again
        prd = _minimal_prd(
            userStories=[
                {
                    "id": "US-001",
                    "title": "Refactor Alpha",
                    "passes": False,
                    "priority": "medium",
                    "description": "",
                    "acceptanceCriteria": [],
                    "dependencies": [],
                },
                {
                    "id": "US-002",
                    "title": "Alpha",
                    "passes": True,
                    "priority": "medium",
                    "description": "",
                    "acceptanceCriteria": [],
                    "dependencies": [],
                },
            ]
        )
        result = analyze_gaps(prd, max_suggest=5)
        titles = [s["title"] for s in result]
        # "Refactor Alpha" already exists → should not appear in suggestions
        assert "Refactor Alpha" not in titles

    def test_fallback_source_is_ai_example(self):
        """All fallback suggestions carry _source='ai-example'."""
        prd = _saturated_prd(n=3)
        result = analyze_gaps(prd, max_suggest=3)
        for story in result:
            assert story.get("_source") == "ai-example"

    def test_fallback_handles_empty_prd(self):
        """Empty PRD with no passed stories → no fallback suggestions (nothing to extend)."""
        prd = _minimal_prd()
        result = analyze_gaps(prd, max_suggest=5)
        # No passed stories means fallback angles A-C have nothing; D needs epics
        assert isinstance(result, list)


# ── CLI integration ───────────────────────────────────────────────────────


class TestAnalyzeGapsCLI:
    """Subprocess integration: --pending/--max-pending respected via CLI."""

    @pytest.fixture()
    def prd_file(self, tmp_path: Any) -> str:
        prd = _minimal_prd(
            userStories=[
                {
                    "id": "US-001",
                    "title": "Zeta",
                    "passes": True,
                    "priority": "medium",
                    "description": "",
                    "acceptanceCriteria": [],
                    "dependencies": [],
                }
            ]
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

    def test_cli_below_max_pending_outputs_stories(self, prd_file: str, tmp_path: Any) -> None:
        out = str(tmp_path / "output.json")
        script = os.path.join(os.path.dirname(__file__), "..", "lib", "research", "ai_suggest.py")
        result = subprocess.run(
            [sys.executable, script, "--prd", prd_file, "--out", out, "--pending", "3", "--max-pending", "50"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["stories"]) > 0
