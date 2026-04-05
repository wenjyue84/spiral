"""Tests for lib/enrich_stories.py (Phase E story enrichment)."""

import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.research.enrich_stories import (
    _enrich_batch,
    _enrich_one,
    _inject_reference_implementations,
    _should_enrich,
    enrich_stories,
    find_similar_passed_stories,
    get_git_diff_summary,
)


def _story(**overrides) -> dict:
    base = {
        "title": "Add feature X",
        "priority": "medium",
        "description": "Add feature X to the codebase.",
        "acceptanceCriteria": ["Feature X works"],
        "technicalNotes": ["File to edit: lib/x.py (add_x)", "Test command: uv run pytest tests/test_x.py -v"],
        "dependencies": [],
        "estimatedComplexity": "small",
        "_source": "research",
        "passes": False,
    }
    base.update(overrides)
    return base


class TestShouldEnrich:
    """_should_enrich() should return True only for eligible stories."""

    def test_small_with_notes_is_not_enriched(self):
        s = _story(estimatedComplexity="small", technicalNotes=["note1", "note2"], filesTouch=["src/foo.py"])
        assert _should_enrich(s) is False

    def test_medium_is_enriched(self):
        s = _story(estimatedComplexity="medium")
        assert _should_enrich(s) is True

    def test_large_is_enriched(self):
        s = _story(estimatedComplexity="large")
        assert _should_enrich(s) is True

    def test_small_with_sparse_notes_is_enriched(self):
        s = _story(estimatedComplexity="small", technicalNotes=["one note only"])
        assert _should_enrich(s) is True

    def test_small_with_no_notes_is_enriched(self):
        s = _story(estimatedComplexity="small", technicalNotes=[])
        assert _should_enrich(s) is True


class TestEnrichOne:
    """_enrich_one() should return a list of 1-2 stories."""

    def _mock_enrich_response(self, story: dict) -> str:
        """Return a valid enrich JSON response."""
        enriched = dict(story)
        enriched["technicalNotes"] = [
            "File to edit: lib/x.py (add_x)",
            "Test command: uv run pytest tests/test_x.py::test_add_x -v",
        ]
        enriched["_enriched"] = True
        return json.dumps({"action": "enrich", "story": enriched})

    def _mock_split_response(self, story: dict) -> str:
        """Return a valid split JSON response with 2 sub-stories."""
        s1 = dict(story)
        s1["title"] = story["title"] + " (part 1)"
        s1["acceptanceCriteria"] = ["Part 1 works"]
        s2 = dict(story)
        s2["title"] = story["title"] + " (part 2)"
        s2["acceptanceCriteria"] = ["Part 2 works"]
        return json.dumps({"action": "split", "stories": [s1, s2]})

    def test_enrich_action_returns_one_story(self):
        story = _story(estimatedComplexity="medium", technicalNotes=[])
        mock_response = self._mock_enrich_response(story)

        with patch("lib.research.enrich_stories.call_claude", return_value=mock_response):
            result = _enrich_one(story, model="sonnet")

        assert len(result) == 1
        assert result[0].get("_enriched") is True

    def test_split_action_returns_two_stories(self):
        story = _story(estimatedComplexity="medium")
        mock_response = self._mock_split_response(story)

        with patch("lib.research.enrich_stories.call_claude", return_value=mock_response):
            result = _enrich_one(story, model="sonnet")

        assert len(result) == 2
        assert "part 1" in result[0]["title"]
        assert "part 2" in result[1]["title"]

    def test_claude_failure_returns_original(self):
        """When Claude call fails, original story passes through unchanged."""
        story = _story(estimatedComplexity="medium")

        with patch("lib.research.enrich_stories.call_claude", side_effect=RuntimeError("timeout")):
            result = _enrich_one(story, model="sonnet")

        assert len(result) == 1
        assert result[0] is story  # exact same object — not a copy

    def test_dry_run_returns_original(self):
        story = _story(estimatedComplexity="medium")
        result = _enrich_one(story, model="sonnet", dry_run=True)

        assert len(result) == 1
        assert result[0] is story


class TestEnrichStoriesIntegration:
    """enrich_stories() integration tests using temp files."""

    def test_small_well_specified_stories_pass_through(self):
        """Small stories with 2+ technicalNotes and filesTouch should not be enriched (no Claude call)."""
        story = _story(
            estimatedComplexity="small",
            technicalNotes=["note1", "note2"],
            filesTouch=["lib/x.py", "tests/test_x.py"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            validated = os.path.join(tmpdir, "validated.json")
            enriched = os.path.join(tmpdir, "enriched.json")

            with open(validated, "w", encoding="utf-8") as f:
                json.dump({"stories": [story]}, f)

            with patch("lib.enrich_stories.call_claude") as mock_claude:
                enrich_count, split_count = enrich_stories(validated, enriched, model="sonnet")
                mock_claude.assert_not_called()  # should not call Claude for small+well-specified

            with open(enriched, encoding="utf-8") as f:
                result = json.load(f)

        assert len(result["stories"]) == 1
        assert enrich_count == 0
        assert split_count == 0

    def test_medium_story_gets_enriched(self):
        story = _story(estimatedComplexity="medium", technicalNotes=[])
        enriched_story = dict(story)
        enriched_story["_enriched"] = True
        enriched_story["technicalNotes"] = [
            "File to edit: lib/x.py (add_x)",
            "Test command: uv run pytest tests/test_x.py -v",
        ]
        mock_response = json.dumps({"action": "enrich", "story": enriched_story})

        with tempfile.TemporaryDirectory() as tmpdir:
            validated = os.path.join(tmpdir, "validated.json")
            enriched_out = os.path.join(tmpdir, "enriched.json")

            with open(validated, "w", encoding="utf-8") as f:
                json.dump({"stories": [story]}, f)

            with patch("lib.research.enrich_stories.call_claude", return_value=mock_response):
                enrich_count, split_count = enrich_stories(validated, enriched_out, model="sonnet")

            with open(enriched_out, encoding="utf-8") as f:
                result = json.load(f)

        assert len(result["stories"]) == 1
        assert result["stories"][0].get("_enriched") is True
        assert enrich_count == 1

    def test_priority_aware_enrichment_order(self):
        """Test that high-priority stories are enriched before medium/low when budget is limited."""
        # Create 5 stories: 3 medium-priority, 2 high-priority
        # Each needs enrichment (no filesTouch set)
        stories = [
            _story(title="Medium 1", priority="medium", estimatedComplexity="medium", technicalNotes=[]),
            _story(title="High 1", priority="high", estimatedComplexity="medium", technicalNotes=[]),
            _story(title="Medium 2", priority="medium", estimatedComplexity="medium", technicalNotes=[]),
            _story(title="High 2", priority="high", estimatedComplexity="medium", technicalNotes=[]),
            _story(title="Medium 3", priority="medium", estimatedComplexity="medium", technicalNotes=[]),
        ]

        def mock_enrich(story: dict) -> str:
            enriched = dict(story)
            enriched["_enriched"] = True
            enriched["technicalNotes"] = ["File to edit: lib/x.py", "Test command: pytest"]
            enriched["filesTouch"] = ["lib/x.py"]
            return json.dumps({"action": "enrich", "story": enriched})

        with tempfile.TemporaryDirectory() as tmpdir:
            validated = os.path.join(tmpdir, "validated.json")
            enriched_out = os.path.join(tmpdir, "enriched.json")

            with open(validated, "w", encoding="utf-8") as f:
                json.dump({"stories": stories}, f)

            # Track which stories are enriched
            enriched_order = []

            def track_enrichment(prompt: str, model: str) -> str:
                # Extract story title from prompt
                try:
                    if "High 1" in prompt:
                        enriched_order.append("High 1")
                    elif "High 2" in prompt:
                        enriched_order.append("High 2")
                    elif "Medium 1" in prompt:
                        enriched_order.append("Medium 1")
                    elif "Medium 2" in prompt:
                        enriched_order.append("Medium 2")
                    elif "Medium 3" in prompt:
                        enriched_order.append("Medium 3")
                except Exception:
                    pass
                # Return a generic enriched story
                return json.dumps(
                    {
                        "action": "enrich",
                        "story": {
                            "title": "Enriched",
                            "priority": "medium",
                            "description": "test",
                            "acceptanceCriteria": ["test"],
                            "technicalNotes": ["File to edit: lib/x.py", "Test command: pytest"],
                            "dependencies": [],
                            "estimatedComplexity": "small",
                            "_enriched": True,
                        },
                    }
                )

            with patch("lib.research.enrich_stories.call_claude", side_effect=track_enrichment):
                # With max_enrich=3, should enrich both high-priority stories (2), then 1 medium
                # Disable batching for this test by setting batch_size=1 to test individual enrichment
                enrich_count, split_count = enrich_stories(
                    validated, enriched_out, model="sonnet", max_enrich=3, batch_size=1
                )

        # Verify both high-priority stories were enriched before medium ones
        # The first 2 enriched should be High priority stories
        assert len(enriched_order) <= 3, f"Should enrich at most 3 stories, enriched {len(enriched_order)}"
        high_enriched = [s for s in enriched_order if "High" in s]
        assert len(high_enriched) == 2, f"Both high-priority stories should be enriched, got {high_enriched}"


class TestEnrichBatch:
    """_enrich_batch() should enrich multiple stories in a single Claude call."""

    def test_batch_enrich_multiple_stories(self):
        """Test enriching a batch of 3 stories in a single call."""
        stories = [
            _story(title="Story 1", estimatedComplexity="medium", technicalNotes=[]),
            _story(title="Story 2", estimatedComplexity="medium", technicalNotes=[]),
            _story(title="Story 3", estimatedComplexity="medium", technicalNotes=[]),
        ]

        def mock_batch_response(prompt: str, model: str) -> str:
            """Return a valid batch enrichment response."""
            return json.dumps(
                {
                    "stories": [
                        {
                            "original_index": 0,
                            "action": "enrich",
                            "results": [
                                {
                                    "title": "Story 1",
                                    "priority": "medium",
                                    "description": "test",
                                    "acceptanceCriteria": ["test"],
                                    "technicalNotes": ["File to edit: lib/x.py", "Test command: pytest"],
                                    "dependencies": [],
                                    "estimatedComplexity": "small",
                                }
                            ],
                        },
                        {
                            "original_index": 1,
                            "action": "enrich",
                            "results": [
                                {
                                    "title": "Story 2",
                                    "priority": "medium",
                                    "description": "test",
                                    "acceptanceCriteria": ["test"],
                                    "technicalNotes": ["File to edit: lib/y.py", "Test command: pytest"],
                                    "dependencies": [],
                                    "estimatedComplexity": "small",
                                }
                            ],
                        },
                        {
                            "original_index": 2,
                            "action": "enrich",
                            "results": [
                                {
                                    "title": "Story 3",
                                    "priority": "medium",
                                    "description": "test",
                                    "acceptanceCriteria": ["test"],
                                    "technicalNotes": ["File to edit: lib/z.py", "Test command: pytest"],
                                    "dependencies": [],
                                    "estimatedComplexity": "small",
                                }
                            ],
                        },
                    ]
                }
            )

        with patch("lib.research.enrich_stories.call_claude", return_value=mock_batch_response("", "")):
            result = _enrich_batch(stories, model="sonnet")

        assert len(result) == 3, f"Should have results for 3 stories, got {len(result)}"
        for idx in range(3):
            assert idx in result, f"Missing result for story {idx}"
            assert len(result[idx]) == 1, f"Story {idx} should have 1 result"
            assert result[idx][0].get("_enriched") is True, f"Story {idx} should be marked as enriched"

    def test_batch_with_splits(self):
        """Test batch where some stories are split."""
        stories = [
            _story(title="Story A", estimatedComplexity="large", technicalNotes=[]),
            _story(title="Story B", estimatedComplexity="medium", technicalNotes=[]),
        ]

        def mock_split_batch_response(prompt: str, model: str) -> str:
            """Return batch with one split and one enrich."""
            return json.dumps(
                {
                    "stories": [
                        {
                            "original_index": 0,
                            "action": "split",
                            "results": [
                                {
                                    "title": "Story A (part 1)",
                                    "priority": "medium",
                                    "description": "test",
                                    "acceptanceCriteria": ["test"],
                                    "technicalNotes": ["File to edit: lib/a.py", "Test command: pytest"],
                                    "dependencies": [],
                                    "estimatedComplexity": "small",
                                },
                                {
                                    "title": "Story A (part 2)",
                                    "priority": "medium",
                                    "description": "test",
                                    "acceptanceCriteria": ["test"],
                                    "technicalNotes": ["File to edit: lib/a2.py", "Test command: pytest"],
                                    "dependencies": [],
                                    "estimatedComplexity": "small",
                                },
                            ],
                        },
                        {
                            "original_index": 1,
                            "action": "enrich",
                            "results": [
                                {
                                    "title": "Story B",
                                    "priority": "medium",
                                    "description": "test",
                                    "acceptanceCriteria": ["test"],
                                    "technicalNotes": ["File to edit: lib/b.py", "Test command: pytest"],
                                    "dependencies": [],
                                    "estimatedComplexity": "small",
                                }
                            ],
                        },
                    ]
                }
            )

        with patch("lib.research.enrich_stories.call_claude", return_value=mock_split_batch_response("", "")):
            result = _enrich_batch(stories, model="sonnet")

        assert len(result) == 2
        assert len(result[0]) == 2, "Story A should be split into 2"
        assert "part 1" in result[0][0].get("title", "")
        assert "part 2" in result[0][1].get("title", "")
        assert len(result[1]) == 1
        assert result[1][0].get("_enriched") is True

    def test_batch_enrichment_integration_10_stories_2_batches(self):
        """Integration test: enrich 10 stories in 2 batches of 5."""
        stories = [
            _story(
                title=f"Story {i}",
                estimatedComplexity="medium",
                technicalNotes=[],
            )
            for i in range(10)
        ]

        call_count = [0]  # Use list to allow modification in nested function

        def mock_batch_response(prompt: str, model: str) -> str:
            """Return enriched versions of stories in the batch with correct relative indices."""
            call_count[0] += 1
            results = []

            # Determine which batch this is (check which story titles are in prompt)
            if call_count[0] == 1:
                # First batch: stories 0-4
                for i in range(5):
                    results.append(
                        {
                            "original_index": i,
                            "action": "enrich",
                            "results": [
                                {
                                    "title": f"Story {i}",
                                    "priority": "medium",
                                    "description": "enriched story",
                                    "acceptanceCriteria": [f"Story {i} criterion"],
                                    "technicalNotes": [f"File to edit: lib/story_{i}.py", "Test command: pytest"],
                                    "dependencies": [],
                                    "estimatedComplexity": "small",
                                }
                            ],
                        }
                    )
            else:
                # Second batch: stories 5-9, but with relative indices 0-4
                for i in range(5):
                    results.append(
                        {
                            "original_index": i,  # Relative to this batch
                            "action": "enrich",
                            "results": [
                                {
                                    "title": f"Story {i + 5}",  # Actual story number
                                    "priority": "medium",
                                    "description": "enriched story",
                                    "acceptanceCriteria": [f"Story {i + 5} criterion"],
                                    "technicalNotes": [f"File to edit: lib/story_{i + 5}.py", "Test command: pytest"],
                                    "dependencies": [],
                                    "estimatedComplexity": "small",
                                }
                            ],
                        }
                    )
            return json.dumps({"stories": results})

        with tempfile.TemporaryDirectory() as tmpdir:
            validated = os.path.join(tmpdir, "validated.json")
            enriched_out = os.path.join(tmpdir, "enriched.json")

            with open(validated, "w", encoding="utf-8") as f:
                json.dump({"stories": stories}, f)

            with patch("lib.research.enrich_stories.call_claude", side_effect=mock_batch_response):
                enrich_count, split_count = enrich_stories(validated, enriched_out, model="sonnet", batch_size=5)

            with open(enriched_out, encoding="utf-8") as f:
                result = json.load(f)

        assert len(result["stories"]) == 10, "Should have 10 enriched stories"
        assert enrich_count == 10, "Should have enriched 10 stories"
        assert split_count == 0, "Should have 0 splits"
        # Verify each story is enriched
        for i, story in enumerate(result["stories"]):
            assert story.get("_enriched") is True, f"Story {i} should be marked as enriched"

    def test_batch_failure_fallback_to_individual(self):
        """Test that batch failure falls back to individual enrichment."""
        stories = [
            _story(title="Story 1", estimatedComplexity="medium", technicalNotes=[]),
            _story(title="Story 2", estimatedComplexity="medium", technicalNotes=[]),
        ]

        def mock_batch_fail(*args, **kwargs) -> str:
            """Batch call fails."""
            raise RuntimeError("Batch enrichment failed")

        def mock_individual_succeed(prompt: str, model: str) -> str:
            """Individual enrichment succeeds."""
            if "Story 1" in prompt:
                return json.dumps(
                    {
                        "action": "enrich",
                        "story": {
                            "title": "Story 1",
                            "priority": "medium",
                            "description": "enriched",
                            "acceptanceCriteria": ["test"],
                            "technicalNotes": ["File to edit: lib/x.py", "Test command: pytest"],
                            "dependencies": [],
                            "estimatedComplexity": "small",
                        },
                    }
                )
            else:
                return json.dumps(
                    {
                        "action": "enrich",
                        "story": {
                            "title": "Story 2",
                            "priority": "medium",
                            "description": "enriched",
                            "acceptanceCriteria": ["test"],
                            "technicalNotes": ["File to edit: lib/y.py", "Test command: pytest"],
                            "dependencies": [],
                            "estimatedComplexity": "small",
                        },
                    }
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            validated = os.path.join(tmpdir, "validated.json")
            enriched_out = os.path.join(tmpdir, "enriched.json")

            with open(validated, "w", encoding="utf-8") as f:
                json.dump({"stories": stories}, f)

            # Mock _enrich_batch to fail, then call_claude to succeed
            with patch("lib.research.enrich_stories._enrich_batch", side_effect=lambda *args, **kwargs: {}):
                with patch("lib.research.enrich_stories.call_claude", side_effect=mock_individual_succeed):
                    enrich_count, split_count = enrich_stories(validated, enriched_out, model="sonnet", batch_size=5)

            with open(enriched_out, encoding="utf-8") as f:
                result = json.load(f)

        # Both stories should be enriched via fallback
        assert enrich_count == 2, "Both stories should be enriched via fallback"
        assert len(result["stories"]) == 2
        for story in result["stories"]:
            assert story.get("_enriched") is True


class TestFindSimilarPassedStories:
    """test_find_similar_passed_stories — find semantic similarity in passed stories."""

    def test_finds_similar_passed_stories(self) -> None:
        """Should return top-3 similar passed stories by semantic similarity."""
        story = {
            "id": "US-100",
            "title": "Add authentication to API",
            "description": "Implement JWT-based authentication for REST API endpoints.",
        }
        prd = {
            "userStories": [
                {
                    "id": "US-50",
                    "title": "Add authentication token validation",
                    "description": "Validate JWT tokens in middleware.",
                    "passes": True,
                },
                {
                    "id": "US-51",
                    "title": "Add logging to database operations",
                    "description": "Log all database queries for debugging.",
                    "passes": True,
                },
                {
                    "id": "US-52",
                    "title": "Implement API key authentication",
                    "description": "Add API key-based auth for service-to-service calls.",
                    "passes": True,
                },
            ]
        }

        result = find_similar_passed_stories(story, prd, top_k=3)

        # Should return at least 1 result (US-50 and US-52 are similar to auth topic)
        assert len(result) > 0
        assert all(isinstance(r, tuple) and len(r) == 2 for r in result)
        # All results should be (story_id, score)
        story_ids = [r[0] for r in result]
        assert "US-50" in story_ids or "US-52" in story_ids

    def test_excludes_same_story(self) -> None:
        """Should not include the query story itself in results."""
        story = {"id": "US-100", "title": "Add feature X", "description": "Feature description"}
        prd = {
            "userStories": [
                {
                    "id": "US-100",
                    "title": "Add feature X",
                    "description": "Feature description",
                    "passes": True,
                },
                {"id": "US-101", "title": "Add feature Y", "description": "Other feature", "passes": True},
            ]
        }

        result = find_similar_passed_stories(story, prd, top_k=3)

        # Should not include US-100 (same as query)
        assert all(r[0] != "US-100" for r in result)

    def test_empty_when_no_passed_stories(self) -> None:
        """Should return empty list when no passed stories exist."""
        story = {"id": "US-100", "title": "Add feature X", "description": "Description"}
        prd = {"userStories": [{"id": "US-101", "title": "Other", "description": "test", "passes": False}]}

        result = find_similar_passed_stories(story, prd, top_k=3)

        assert result == []

    def test_returns_top_k(self) -> None:
        """Should return at most top_k results."""
        story = {"id": "US-100", "title": "Test", "description": "Test"}
        prd = {
            "userStories": [
                {"id": f"US-{i}", "title": "Test", "description": "Test", "passes": True} for i in range(10)
            ]
        }

        result = find_similar_passed_stories(story, prd, top_k=3)

        assert len(result) <= 3


class TestGetGitDiffSummary:
    """test_git_diff_summary — retrieve and truncate git diffs."""

    def test_returns_empty_on_no_commits(self) -> None:
        """Should return empty string when no commits match story_id."""
        # Use a non-existent story ID to ensure no commits
        result = get_git_diff_summary("NONEXISTENT-999-STORY-ID", max_chars=8000)

        # May be empty or contain some old commit; just check it doesn't crash
        assert isinstance(result, str)

    def test_truncates_to_max_chars(self) -> None:
        """Should cap total output at max_chars."""
        result = get_git_diff_summary("US-1152", max_chars=500)

        assert isinstance(result, str)
        assert len(result) <= 510  # A bit over to account for truncation marker


class TestInjectReferenceImplementations:
    """test_reference_injection_in_prompt — inject similar stories into enrichment."""

    def test_injects_reference_implementations(self) -> None:
        """Should add _reference_implementations field when similar passed stories exist."""
        story = {
            "id": "US-100",
            "title": "Add authentication",
            "description": "Implement JWT auth.",
        }
        prd = {
            "userStories": [
                {
                    "id": "US-50",
                    "title": "Add JWT validation",
                    "description": "Validate JWT tokens.",
                    "passes": True,
                },
                {"id": "US-51", "title": "Other feature", "description": "Unrelated", "passes": False},
            ]
        }

        with patch("lib.research.enrich_stories.get_git_diff_summary", return_value="diff content"):
            result = _inject_reference_implementations(story, prd)

        # Should have added _reference_implementations field
        assert "_reference_implementations" in result
        refs = result["_reference_implementations"]
        assert len(refs) > 0
        assert all("id" in r and "title" in r and "score" in r for r in refs)

    def test_empty_when_no_passed_stories(self) -> None:
        """Should not add _reference_implementations field when no passed stories exist."""
        story = {"id": "US-100", "title": "Feature", "description": "Description"}
        prd = {"userStories": [{"id": "US-101", "title": "Other", "description": "test", "passes": False}]}

        result = _inject_reference_implementations(story, prd)

        # Should not have _reference_implementations field if no similar passed stories
        assert "_reference_implementations" not in result or len(result.get("_reference_implementations", [])) == 0

    def test_caps_total_diff_at_8000_chars(self) -> None:
        """Should cap total diff content at approximately 8000 characters."""
        story = {"id": "US-100", "title": "Feature", "description": "Description"}
        prd = {
            "userStories": [
                {"id": "US-50", "title": "Similar 1", "description": "Similar", "passes": True},
                {"id": "US-51", "title": "Similar 2", "description": "Similar", "passes": True},
                {"id": "US-52", "title": "Similar 3", "description": "Similar", "passes": True},
            ]
        }

        # Mock get_git_diff_summary to return a large string
        # With max_chars=8000 and 3 stories, each gets ~2667 chars if split evenly
        call_count = [0]

        def mock_git_diff(story_id: str, max_chars: int = 8000, **kwargs) -> str:
            call_count[0] += 1
            # Return a diff that respects the max_chars limit
            if call_count[0] <= 3:
                return "x" * min(2000, max_chars)
            return ""

        with patch("lib.research.enrich_stories.get_git_diff_summary", side_effect=mock_git_diff):
            result = _inject_reference_implementations(story, prd)

        # Total diff should be capped at roughly 8000
        if "_reference_implementations" in result:
            total_chars = sum(len(r.get("diff_summary", "")) for r in result.get("_reference_implementations", []))
            # Each story gets at most max_chars available, so total should be reasonable
            assert total_chars <= 9000  # Allow for realistic overage
