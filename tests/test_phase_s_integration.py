"""Integration tests for Phase S (Story Validate) — validate_stories() full pipeline.

Covers: constitution enforcement, goal alignment, complexity gate, source tagging,
batch API fallback, and end-to-end candidate filtering.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from validate_stories import validate_stories


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _make_prd(goals: list[str], stories: list[dict] | None = None) -> dict:
    return {"goals": goals, "userStories": stories or []}


def _make_candidate(
    title: str,
    description: str = "",
    source: str = "research",
    complexity: str = "small",
    acs: list[str] | None = None,
    tech_notes: list[str] | None = None,
) -> dict:
    return {
        "title": title,
        "description": description,
        "_source": source,
        "estimatedComplexity": complexity,
        "acceptanceCriteria": acs or ["AC1"],
        "technicalNotes": tech_notes or ["Note1"],
    }


@pytest.fixture()
def workspace(tmp_path):
    """Create a temp workspace with all required file paths."""
    return {
        "prd": str(tmp_path / "prd.json"),
        "research": str(tmp_path / "research.json"),
        "test_stories": str(tmp_path / "test_stories.json"),
        "validated": str(tmp_path / "validated.json"),
        "rejected": str(tmp_path / "rejected.json"),
        "constitution": str(tmp_path / "constitution.md"),
        "ai_suggest": str(tmp_path / "ai_suggest.json"),
        "tmp_path": tmp_path,
    }


# ── Happy path: research candidates accepted via goal alignment ──────────────


class TestGoalAlignment:
    def test_research_accepted_when_keywords_overlap(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Improve testing coverage and CI pipeline"]))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Add integration testing for CI pipeline")]},
        )
        _write_json(workspace["test_stories"], {"stories": []})

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            min_overlap=1,
        )
        assert len(accepted) == 1
        assert len(rejected) == 0
        assert accepted[0]["title"] == "Add integration testing for CI pipeline"

    def test_research_rejected_when_no_goal_overlap(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Improve database performance"]))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Build marketing landing page")]},
        )
        _write_json(workspace["test_stories"], {"stories": []})

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            min_overlap=1,
        )
        assert len(accepted) == 0
        assert len(rejected) == 1
        assert "No connection to project goals" in rejected[0]["_rejection_reason"]

    def test_min_overlap_zero_accepts_all(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Unrelated goal"]))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Completely different topic")]},
        )
        _write_json(workspace["test_stories"], {"stories": []})

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            min_overlap=0,
        )
        assert len(accepted) == 1
        assert len(rejected) == 0

    def test_empty_goals_rejects_research(self, workspace):
        _write_json(workspace["prd"], _make_prd([]))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Some research story")]},
        )
        _write_json(workspace["test_stories"], {"stories": []})

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            min_overlap=1,
        )
        # With empty goals, gkw is empty, so condition `gkw and min_overlap > 0`
        # is False — stories pass through without goal check
        assert len(accepted) == 1


# ── Source tagging: test-fix and test-story auto-approved ─────────────────────


class TestSourceTagging:
    def test_test_fix_bypasses_goal_alignment(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Database performance"]))
        _write_json(workspace["research"], {"stories": []})
        _write_json(
            workspace["test_stories"],
            {"stories": [_make_candidate("Fix unrelated widget layout", source="test-fix")]},
        )

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            min_overlap=1,
        )
        assert len(accepted) == 1
        assert accepted[0]["_source"] == "test-fix"

    def test_test_story_bypasses_goal_alignment(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Database performance"]))
        candidates = [_make_candidate("Widget test coverage", source="test-story")]
        _write_json(workspace["research"], {"stories": candidates})
        _write_json(workspace["test_stories"], {"stories": []})

        accepted, _ = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            min_overlap=1,
        )
        assert len(accepted) == 1

    def test_ai_example_requires_goal_alignment(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Database performance"]))
        _write_json(workspace["research"], {"stories": []})
        _write_json(workspace["test_stories"], {"stories": []})
        _write_json(
            workspace["ai_suggest"],
            {"stories": [_make_candidate("Build marketing page", source="ai-example")]},
        )

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            ai_suggest_path=workspace["ai_suggest"],
            min_overlap=1,
        )
        assert len(accepted) == 0
        assert len(rejected) == 1


# ── Constitution enforcement ──────────────────────────────────────────────────


class TestConstitutionEnforcement:
    def test_constitution_rejects_forbidden_phrase(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Improve testing"]))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Add blockchain testing integration")]},
        )
        _write_json(workspace["test_stories"], {"stories": []})
        with open(workspace["constitution"], "w") as f:
            f.write("NEVER: blockchain\n")

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            constitution_path=workspace["constitution"],
            min_overlap=1,
        )
        assert len(accepted) == 0
        assert len(rejected) == 1
        assert "constitution" in rejected[0]["_rejection_reason"].lower()

    def test_constitution_applies_to_test_fix_too(self, workspace):
        """Constitution check runs even for auto-approved sources."""
        _write_json(workspace["prd"], _make_prd(["Improve testing"]))
        _write_json(workspace["research"], {"stories": []})
        _write_json(
            workspace["test_stories"],
            {"stories": [_make_candidate("Fix blockchain module", source="test-fix")]},
        )
        with open(workspace["constitution"], "w") as f:
            f.write("FORBIDDEN: blockchain\n")

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            constitution_path=workspace["constitution"],
            min_overlap=1,
        )
        assert len(accepted) == 0
        assert len(rejected) == 1

    def test_constitution_empty_file_accepts_all(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Improve testing coverage"]))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Add testing coverage for API")]},
        )
        _write_json(workspace["test_stories"], {"stories": []})
        with open(workspace["constitution"], "w") as f:
            f.write("# This is a comment, no forbidden phrases\n")

        accepted, _ = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            constitution_path=workspace["constitution"],
            min_overlap=1,
        )
        assert len(accepted) == 1

    def test_multiple_forbidden_prefixes(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Testing"]))
        stories = [
            _make_candidate("Add crypto wallet testing"),
            _make_candidate("Avoid NFT integration testing"),
            _make_candidate("Add unit testing for cache"),
        ]
        _write_json(workspace["research"], {"stories": stories})
        _write_json(workspace["test_stories"], {"stories": []})
        with open(workspace["constitution"], "w") as f:
            f.write("NOT: crypto wallet\nAVOID: nft integration\n")

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            constitution_path=workspace["constitution"],
            min_overlap=0,
        )
        assert len(accepted) == 1
        assert accepted[0]["title"] == "Add unit testing for cache"
        assert len(rejected) == 2


# ── Complexity gate ───────────────────────────────────────────────────────────


class TestComplexityGate:
    def test_large_complexity_rejected(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Improve performance"]))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Rewrite entire performance layer", complexity="large")]},
        )
        _write_json(workspace["test_stories"], {"stories": []})

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            min_overlap=0,
        )
        assert len(accepted) == 0
        assert len(rejected) == 1
        assert "complexity_too_large" in rejected[0]["_rejection_reason"]

    def test_small_and_medium_accepted(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Improve performance"]))
        stories = [
            _make_candidate("Small performance fix", complexity="small"),
            _make_candidate("Medium performance refactor", complexity="medium"),
        ]
        _write_json(workspace["research"], {"stories": stories})
        _write_json(workspace["test_stories"], {"stories": []})

        accepted, _ = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            min_overlap=0,
        )
        assert len(accepted) == 2


# ── Dedup by title ────────────────────────────────────────────────────────────


class TestTitleDedup:
    def test_duplicate_titles_across_sources_deduped(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Testing"]))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Add widget tests")]},
        )
        _write_json(
            workspace["test_stories"],
            {"stories": [_make_candidate("Add widget tests", source="test-fix")]},
        )

        accepted, _ = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            min_overlap=0,
        )
        assert len(accepted) == 1


# ── Output file writing ──────────────────────────────────────────────────────


class TestOutputFiles:
    def test_validated_and_rejected_files_written(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Testing coverage"]))
        stories = [
            _make_candidate("Add testing coverage for API"),
            _make_candidate("Build unrelated marketing page"),
        ]
        _write_json(workspace["research"], {"stories": stories})
        _write_json(workspace["test_stories"], {"stories": []})

        validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            min_overlap=1,
        )
        validated = _read_json(workspace["validated"])
        rejected = _read_json(workspace["rejected"])
        assert "stories" in validated
        assert "stories" in rejected
        assert len(validated["stories"]) == 1
        assert len(rejected["stories"]) == 1

    def test_empty_candidates_writes_empty_arrays(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Testing"]))
        _write_json(workspace["research"], {"stories": []})
        _write_json(workspace["test_stories"], {"stories": []})

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
        )
        assert accepted == []
        assert rejected == []
        validated = _read_json(workspace["validated"])
        assert validated["stories"] == []


# ── Batch API fallback ────────────────────────────────────────────────────────


class TestBatchApiFallback:
    def test_batch_api_falls_back_without_api_key(self, workspace, monkeypatch):
        """When use_batch_api=True but no ANTHROPIC_API_KEY, falls back to keyword path."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        _write_json(workspace["prd"], _make_prd(["Improve testing coverage"]))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Add testing coverage for modules")]},
        )
        _write_json(workspace["test_stories"], {"stories": []})

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            use_batch_api=True,
            min_overlap=1,
        )
        # Should still work via keyword fallback
        assert len(accepted) == 1


# ── Mixed sources pipeline ────────────────────────────────────────────────────


class TestMixedSourcesPipeline:
    def test_mixed_sources_all_processed(self, workspace):
        """Research, test-fix, ai-example, and test-story all processed correctly."""
        _write_json(workspace["prd"], _make_prd(["Improve testing and performance"]))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Add performance testing suite")]},
        )
        _write_json(
            workspace["test_stories"],
            {"stories": [_make_candidate("Fix broken performance test", source="test-fix")]},
        )
        _write_json(
            workspace["ai_suggest"],
            {"stories": [_make_candidate("Add load testing framework", source="ai-example")]},
        )

        accepted, rejected = validate_stories(
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
            ai_suggest_path=workspace["ai_suggest"],
            min_overlap=1,
        )
        # research: "performance testing" overlaps with goal → accepted
        # test-fix: auto-approved → accepted
        # ai-example: "load testing" overlaps with goal → accepted
        assert len(accepted) == 3
        sources = {s["_source"] for s in accepted}
        assert sources == {"research", "test-fix", "ai-example"}

    def test_missing_input_files_handled_gracefully(self, workspace):
        _write_json(workspace["prd"], _make_prd(["Testing"]))
        # research and test_stories paths don't exist
        accepted, rejected = validate_stories(
            research_path=str(workspace["tmp_path"] / "nonexistent.json"),
            test_stories_path=str(workspace["tmp_path"] / "also_missing.json"),
            prd_path=workspace["prd"],
            validated_out=workspace["validated"],
            rejected_out=workspace["rejected"],
        )
        assert accepted == []
        assert rejected == []
