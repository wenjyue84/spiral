"""Tests for lib/story_complexity.py — story complexity scorer."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from story_complexity import complexity_band, compute_story_complexity


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_story(
    sid: str = "US-001",
    description: str = "",
    dependencies: list[str] | None = None,
    files_touch: list[str] | None = None,
    retry_num: int = 0,
) -> dict:
    story: dict = {
        "id": sid,
        "title": f"Test story {sid}",
        "description": description,
        "dependencies": dependencies or [],
        "passes": False,
    }
    if files_touch is not None:
        story["filesTouch"] = files_touch
    if retry_num:
        story["retry_num"] = retry_num
    return story


def _make_prd(stories: list[dict]) -> dict:
    return {"userStories": stories}


# ── Unit tests ─────────────────────────────────────────────────────────────────


class TestComputeStoryComplexityScore:
    """Verify score stays in [1, 10] and weights behave as expected."""

    def test_empty_story_returns_minimum(self) -> None:
        story = _make_story()
        score = compute_story_complexity(story, _make_prd([story]))
        assert score == pytest.approx(1.0, abs=0.5)

    def test_score_bounded_between_1_and_10(self) -> None:
        # Extremely long description + many deps + many files + many retries
        story = _make_story(
            description=" ".join(["word"] * 500),
            dependencies=["US-X"] * 20,
            files_touch=["f.py"] * 30,
            retry_num=10,
        )
        score = compute_story_complexity(story, _make_prd([story]))
        assert 1.0 <= score <= 10.0

    def test_short_desc_no_deps_low_score(self) -> None:
        """Short description (~5 words) + 0 deps should yield score ~2."""
        story = _make_story(description="Fix a small bug")
        score = compute_story_complexity(story, _make_prd([story]))
        assert score < 3.5, f"Expected low score, got {score}"

    def test_long_desc_many_deps_high_score(self) -> None:
        """Long description (200+ words) + 5 deps should yield score ~8."""
        long_desc = " ".join(["word"] * 210)
        story = _make_story(description=long_desc, dependencies=["US-A", "US-B", "US-C", "US-D", "US-E"])
        score = compute_story_complexity(story, _make_prd([story]))
        assert score >= 7.0, f"Expected high score, got {score}"

    def test_description_weight_dominates(self) -> None:
        """A story with 200 words and no deps should score higher than 10 words + 2 deps."""
        long_story = _make_story(description=" ".join(["word"] * 200))
        short_story = _make_story(description="Short", dependencies=["US-1", "US-2"])
        long_score = compute_story_complexity(long_story, _make_prd([long_story]))
        short_score = compute_story_complexity(short_story, _make_prd([short_story]))
        assert long_score > short_score

    def test_files_touch_increases_score(self) -> None:
        base = _make_story(description="A medium length description with some words here")
        with_files = _make_story(
            description="A medium length description with some words here",
            files_touch=["a.py", "b.py", "c.py", "d.py", "e.py", "f.py", "g.py", "h.py"],
        )
        base_score = compute_story_complexity(base, _make_prd([base]))
        files_score = compute_story_complexity(with_files, _make_prd([with_files]))
        assert files_score > base_score

    def test_retry_count_increases_score(self) -> None:
        base = _make_story(description="Test story")
        retried = _make_story(description="Test story", retry_num=3)
        assert compute_story_complexity(retried, {}) > compute_story_complexity(base, {})

    def test_files_touch_in_technical_hints(self) -> None:
        """filesTouch inside technicalHints should also be counted."""
        story = _make_story()
        story["technicalHints"] = {"filesTouch": ["a.py", "b.py", "c.py", "d.py", "e.py"]}
        base = _make_story()
        assert compute_story_complexity(story, {}) > compute_story_complexity(base, {})

    def test_none_description_handled(self) -> None:
        story = _make_story()
        story["description"] = None  # type: ignore[assignment]
        score = compute_story_complexity(story, {})
        assert 1.0 <= score <= 10.0


class TestComplexityBand:
    def test_score_1_is_low(self) -> None:
        assert complexity_band(1.0) == "low"

    def test_score_3_is_low(self) -> None:
        assert complexity_band(3.0) == "low"

    def test_score_4_is_medium(self) -> None:
        assert complexity_band(4.0) == "medium"

    def test_score_6_is_medium(self) -> None:
        assert complexity_band(6.0) == "medium"

    def test_score_7_is_high(self) -> None:
        assert complexity_band(7.0) == "high"

    def test_score_10_is_high(self) -> None:
        assert complexity_band(10.0) == "high"


# ── Integration test ───────────────────────────────────────────────────────────


class TestStoryComplexityIntegration:
    """Integration test using realistic story shapes similar to prd.json."""

    def test_three_stories_span_expected_ranges(self) -> None:
        """Short desc + 0 deps → score ~2; long desc + 5 deps → score ~8."""
        easy = _make_story(
            sid="US-100",
            description="Fix typo in README",
        )
        medium_story = _make_story(
            sid="US-101",
            description=" ".join(["implement", "feature", "with", "logic"] * 10),
            dependencies=["US-100"],
            files_touch=["lib/a.py", "lib/b.py", "lib/c.py"],
        )
        hard = _make_story(
            sid="US-102",
            description=" ".join(["complex", "refactor", "involving", "many", "components"] * 42),
            dependencies=["US-100", "US-101", "US-X", "US-Y", "US-Z"],
            files_touch=[f"lib/f{i}.py" for i in range(10)],
            retry_num=2,
        )
        prd = _make_prd([easy, medium_story, hard])

        easy_score = compute_story_complexity(easy, prd)
        medium_score = compute_story_complexity(medium_story, prd)
        hard_score = compute_story_complexity(hard, prd)

        # Verify ordering
        assert easy_score < medium_score < hard_score, (
            f"Expected easy({easy_score}) < medium({medium_score}) < hard({hard_score})"
        )
        # Verify range expectations from AC2
        assert easy_score < 3.5, f"Easy story should score ~2, got {easy_score}"
        assert hard_score >= 7.0, f"Hard story should score ~8, got {hard_score}"

    def test_partition_prd_uses_complexity_bands(self) -> None:
        """Verify partition_prd assign_stories respects complexity bands with 2 workers.

        Band mapping:
          low (score 1-3)  / high (score 7-10) → worker-0 (even index)
          medium (score 4-6)                   → worker-1 (odd index)
        """
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "prd"))
        from partition_prd import assign_stories

        # Easy story: short description, no deps → raw ~0.02 → score ~1.2 (low band)
        easy = _make_story(
            sid="US-200",
            description="Fix typo",
        )
        # Hard story: 250 words + 5 deps → raw ~0.8 → score ~8.2 (high band)
        hard = _make_story(
            sid="US-201",
            description=" ".join(["word"] * 250),
            dependencies=["US-A", "US-B", "US-C", "US-D", "US-E"],
        )
        # Medium story: 100 words + 3 deps → raw ~0.38 → score ~4.4 (medium band)
        # 40%*(100/200) + 30%*(3/5) = 0.20 + 0.18 = 0.38 → 1 + 0.38*9 = 4.42
        medium_story = _make_story(
            sid="US-202",
            description=" ".join(["word"] * 100),
            dependencies=["US-X", "US-Y", "US-Z"],
        )
        prd = _make_prd([easy, hard, medium_story])

        # Verify score bands before testing partition
        from story_complexity import complexity_band, compute_story_complexity

        easy_score = compute_story_complexity(easy, prd)
        hard_score = compute_story_complexity(hard, prd)
        medium_score = compute_story_complexity(medium_story, prd)
        assert complexity_band(easy_score) == "low", f"easy={easy_score}"
        assert complexity_band(hard_score) == "high", f"hard={hard_score}"
        assert complexity_band(medium_score) == "medium", f"medium={medium_score}"

        buckets = assign_stories([easy, hard, medium_story], n_workers=2, prd=prd)

        # All stories should be assigned somewhere
        all_assigned = [s for bucket in buckets for s in bucket]
        assert len(all_assigned) == 3

        # With 2 workers: easy(low)/hard(high) go to worker-0 (even index),
        # medium goes to worker-1 (odd index)
        worker0_ids = {s["id"] for s in buckets[0]}
        worker1_ids = {s["id"] for s in buckets[1]}

        assert "US-200" in worker0_ids, f"Easy story (low band) should go to worker 0, got: {worker0_ids}"
        assert "US-202" in worker1_ids, f"Medium story should go to worker 1, got: {worker1_ids}"
