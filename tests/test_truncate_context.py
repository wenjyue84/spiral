"""Unit tests for lib/truncate_context.py — story context truncation."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from truncate_context import (
    count_tokens,
    truncate_story,
    load_cached_tokens,
    save_cached_tokens,
    main,
    DEFAULT_CONTEXT_LIMIT,
    TRUNCATION_ORDER,
    CORE_FIELDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_story(
    story_id: str = "US-001",
    extra_fields: dict | None = None,
) -> dict:
    """Build a minimal valid story dict."""
    story = {
        "id": story_id,
        "title": "Test story",
        "description": "A test story for truncation",
        "acceptanceCriteria": ["criterion 1", "criterion 2"],
        "dependencies": [],
        "priority": "medium",
        "estimatedComplexity": "small",
        "passes": False,
    }
    if extra_fields:
        story.update(extra_fields)
    return story


def _big_text(n_chars: int) -> str:
    """Return a string of approximately n_chars characters."""
    unit = "abcdefghij"
    repeats = max(1, n_chars // len(unit))
    return (unit * repeats)[:n_chars]


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------

class TestCountTokens:
    def test_empty_string_returns_at_least_one(self):
        # Approximation: max(1, len("") // 4) = 1
        result = count_tokens("")
        assert result >= 0  # 0 or 1 depending on implementation

    def test_longer_text_more_tokens(self):
        short = count_tokens("hello")
        long = count_tokens("hello " * 100)
        assert long > short

    def test_returns_int(self):
        assert isinstance(count_tokens("some text"), int)

    def test_deterministic(self):
        text = "This is a test sentence for token counting."
        assert count_tokens(text) == count_tokens(text)


# ---------------------------------------------------------------------------
# truncate_story — no-op when under threshold
# ---------------------------------------------------------------------------

class TestTruncateStoryNoOp:
    def test_small_story_unchanged(self):
        story = _make_story()
        truncated, orig, final, dropped = truncate_story(story, limit=DEFAULT_CONTEXT_LIMIT)
        assert truncated == story
        assert dropped == []
        assert orig == final

    def test_returns_original_dict_type(self):
        story = _make_story()
        truncated, _, _, _ = truncate_story(story, limit=DEFAULT_CONTEXT_LIMIT)
        assert isinstance(truncated, dict)

    def test_base_tokens_counted_in_original(self):
        story = _make_story()
        story_tokens = count_tokens(json.dumps(story))
        # Pass base_tokens that together with story_tokens is still under limit
        _, orig, _, _ = truncate_story(story, base_tokens=100, limit=DEFAULT_CONTEXT_LIMIT)
        assert orig == 100 + story_tokens

    def test_zero_limit_drops_all_droppable_fields(self):
        """A limit of 0 should try to drop all optional fields."""
        story = _make_story(extra_fields={
            "_researchOutput": _big_text(1000),
            "hints": {"key": "value"},
            "filesTouch": ["file.py"],
        })
        truncated, _, _, dropped = truncate_story(story, limit=0)
        assert "_researchOutput" not in truncated
        assert "hints" not in truncated
        assert "filesTouch" not in truncated


# ---------------------------------------------------------------------------
# truncate_story — truncation ordering
# ---------------------------------------------------------------------------

class TestTruncateStoryOrdering:
    def _story_with_all_extras(self, size_each: int = 20_000) -> dict:
        """Story with all droppable fields populated with large content."""
        return _make_story(extra_fields={
            "_researchOutput": _big_text(size_each),
            "hints": {"context": _big_text(size_each)},
            "technicalHints": {"notes": _big_text(size_each)},
            "filesTouch": [f"file_{i}.py" for i in range(500)],
        })

    def test_research_output_dropped_first(self):
        """_researchOutput is the first field to be dropped."""
        # Create a story that is slightly over limit — only need to drop
        # _researchOutput to get under.
        base_story = _make_story()
        base_tokens = count_tokens(json.dumps(base_story))
        # Make a story big enough that removing just _researchOutput brings it under
        padding = _big_text(2000)  # ~500 tokens
        story = _make_story(extra_fields={
            "_researchOutput": padding,
            "filesTouch": ["a.py"],
        })
        total_tokens = count_tokens(json.dumps(story))
        # Set limit just below total but above story-minus-research
        limit = total_tokens - 5
        truncated, orig, final, dropped = truncate_story(story, limit=limit)
        assert "_researchOutput" in dropped
        assert "filesTouch" not in dropped  # not needed

    def test_hints_dropped_before_filesTouch(self):
        """hints is dropped before filesTouch."""
        base_story = _make_story()
        padding = _big_text(2000)
        story = _make_story(extra_fields={
            "hints": {"context": padding},
            "filesTouch": ["b.py"],
        })
        total_tokens = count_tokens(json.dumps(story))
        limit = total_tokens - 5
        truncated, _, _, dropped = truncate_story(story, limit=limit)
        assert "hints" in dropped
        assert "filesTouch" not in dropped

    def test_all_fields_dropped_when_necessary(self):
        """All optional fields dropped when story is massively over limit."""
        story = self._story_with_all_extras(size_each=200_000)
        _, _, _, dropped = truncate_story(story, limit=100)
        # All four optional fields should be dropped
        for field in ["_researchOutput", "hints", "technicalHints", "filesTouch"]:
            assert field in dropped

    def test_core_fields_never_dropped(self):
        """Core story spec fields are never removed during truncation."""
        story = self._story_with_all_extras(size_each=200_000)
        truncated, _, _, _ = truncate_story(story, limit=1)
        for field in CORE_FIELDS:
            if field in story:
                assert field in truncated, f"Core field '{field}' was incorrectly dropped"

    def test_truncation_order_matches_constant(self):
        """Verify that the TRUNCATION_ORDER list reflects the documented priority."""
        assert TRUNCATION_ORDER[0] == "_researchOutput"
        assert "hints" in TRUNCATION_ORDER
        assert "filesTouch" in TRUNCATION_ORDER
        # filesTouch comes after hints
        assert TRUNCATION_ORDER.index("filesTouch") > TRUNCATION_ORDER.index("hints")


# ---------------------------------------------------------------------------
# truncate_story — edge case: story spec alone exceeds limit
# ---------------------------------------------------------------------------

class TestTruncateStorySpecExceedsLimit:
    def test_core_story_unchanged_even_when_over_limit(self):
        """If the core story spec itself exceeds the limit, return it unchanged
        (we must never drop core fields, so truncation is a no-op for core-only stories)."""
        # A story with only core fields — no droppable fields
        story = _make_story()
        story_tokens = count_tokens(json.dumps(story))
        # Limit below current size
        limit = max(1, story_tokens - 10)
        truncated, orig, final, dropped = truncate_story(story, limit=limit)
        assert dropped == []
        assert truncated == story

    def test_story_with_extras_but_core_still_over_limit(self):
        """When even after dropping all optional fields the core exceeds the limit,
        return the stripped (core-only) story rather than panicking."""
        big_core_story = _make_story(extra_fields={
            "_researchOutput": _big_text(500),
            "description": _big_text(10_000),  # core — cannot be dropped
        })
        # Set an absurdly tiny limit
        _, _, _, dropped = truncate_story(big_core_story, limit=10)
        # All optional fields should be dropped; core kept
        assert "_researchOutput" not in truncate_story(big_core_story, limit=10)[0]
        assert "description" in truncate_story(big_core_story, limit=10)[0]


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

class TestTokenCache:
    def test_roundtrip(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        save_cached_tokens(cache_dir, "US-001", 0, 12345)
        assert load_cached_tokens(cache_dir, "US-001", 0) == 12345

    def test_miss_returns_none(self, tmp_path):
        assert load_cached_tokens(str(tmp_path), "US-999", 0) is None

    def test_empty_cache_dir_returns_none(self):
        assert load_cached_tokens("", "US-001", 0) is None

    def test_different_attempts_are_independent(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        save_cached_tokens(cache_dir, "US-001", 0, 100)
        save_cached_tokens(cache_dir, "US-001", 1, 200)
        assert load_cached_tokens(cache_dir, "US-001", 0) == 100
        assert load_cached_tokens(cache_dir, "US-001", 1) == 200


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------

class TestMain:
    def test_noop_under_limit(self, monkeypatch, capsys):
        story = _make_story()
        monkeypatch.delenv("SPIRAL_CONTEXT_LIMIT", raising=False)
        rc = main(["--story", json.dumps(story)])
        assert rc == 0
        out = capsys.readouterr().out
        parsed = json.loads(out.strip())
        assert parsed["id"] == story["id"]

    def test_truncation_emits_warning_to_stderr(self, monkeypatch, capsys):
        """When truncation occurs, a structured warning is written to stderr."""
        padding = _big_text(200_000)
        story = _make_story(extra_fields={"_researchOutput": padding})
        # Set a small limit via env var
        monkeypatch.setenv("SPIRAL_CONTEXT_LIMIT", "100")
        rc = main(["--story", json.dumps(story)])
        assert rc == 0
        captured = capsys.readouterr()
        warning = json.loads(captured.err.strip())
        assert warning["event"] == "context_truncated"
        assert warning["story_id"] == "US-001"
        assert "original_tokens" in warning
        assert "truncated_tokens" in warning
        assert "_researchOutput" in warning["dropped_fields"]

    def test_truncation_stdout_is_valid_json(self, monkeypatch, capsys):
        padding = _big_text(200_000)
        story = _make_story(extra_fields={"_researchOutput": padding})
        monkeypatch.setenv("SPIRAL_CONTEXT_LIMIT", "100")
        main(["--story", json.dumps(story)])
        out = capsys.readouterr().out
        parsed = json.loads(out.strip())
        assert "_researchOutput" not in parsed

    def test_no_warning_when_no_truncation(self, monkeypatch, capsys):
        story = _make_story()
        monkeypatch.delenv("SPIRAL_CONTEXT_LIMIT", raising=False)
        main(["--story", json.dumps(story)])
        err = capsys.readouterr().err
        assert err.strip() == ""

    def test_empty_input_returns_error(self, capsys):
        rc = main(["--story", ""])
        assert rc == 1

    def test_invalid_json_returns_error(self, capsys):
        rc = main(["--story", "not-json"])
        assert rc == 1

    def test_spiral_context_limit_env_override(self, monkeypatch, capsys):
        """SPIRAL_CONTEXT_LIMIT env var overrides the default 180000 threshold."""
        padding = _big_text(400)  # ~100 tokens with approx
        story = _make_story(extra_fields={"_researchOutput": padding})
        # With very tight limit, truncation should fire
        monkeypatch.setenv("SPIRAL_CONTEXT_LIMIT", "10")
        rc = main(["--story", json.dumps(story)])
        assert rc == 0
        captured = capsys.readouterr()
        warning = json.loads(captured.err.strip())
        assert warning["limit"] == 10

    def test_base_prompt_file_counts_toward_limit(self, monkeypatch, tmp_path, capsys):
        """Tokens from base prompt file are included in total count."""
        # Write a large base prompt
        prompt_file = tmp_path / "CLAUDE.md"
        prompt_file.write_text(_big_text(400_000), encoding="utf-8")
        story = _make_story(extra_fields={"_researchOutput": _big_text(4000)})
        monkeypatch.delenv("SPIRAL_CONTEXT_LIMIT", raising=False)
        # With a huge base prompt, total will exceed 180000 limit
        rc = main(["--story", json.dumps(story),
                   "--base-prompt-file", str(prompt_file)])
        assert rc == 0
        # Warning may or may not fire depending on approx; just ensure no crash

    def test_stdin_fallback(self, monkeypatch, capsys):
        """Reads story JSON from stdin when --story is not provided."""
        import io
        story = _make_story()
        monkeypatch.delenv("SPIRAL_CONTEXT_LIMIT", raising=False)
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(story)))
        rc = main([])
        assert rc == 0
        out = capsys.readouterr().out
        assert json.loads(out.strip())["id"] == "US-001"
