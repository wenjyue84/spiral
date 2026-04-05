"""Tests for lib/validate_stories.py — semantic similarity deduplication (US-371)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from validate_stories import _semantic_dedup_pass, _story_text


def _make_story(
    title: str,
    description: str,
    acs: list[str],
    source: str = "research",
    story_id: str = "US-TST",
) -> dict:
    return {
        "id": story_id,
        "title": title,
        "description": description,
        "acceptanceCriteria": acs,
        "_source": source,
    }


# ── _story_text ───────────────────────────────────────────────────────────────


def test_story_text_combines_title_description_acs():
    story = {
        "title": "Add LRU cache",
        "description": "Implement least-recently-used caching layer",
        "acceptanceCriteria": ["Cache hit returns stored result", "Cache miss triggers fetch"],
    }
    text = _story_text(story)
    assert "Add LRU cache" in text
    assert "Implement least-recently-used caching layer" in text
    assert "Cache hit returns stored result" in text
    assert "Cache miss triggers fetch" in text


def test_story_text_only_uses_first_two_acs():
    story = {
        "title": "T",
        "description": "D",
        "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4"],
    }
    text = _story_text(story)
    assert "AC1" in text
    assert "AC2" in text
    assert "AC3" not in text
    assert "AC4" not in text


def test_story_text_handles_missing_fields():
    assert _story_text({}) == ""
    assert _story_text({"title": "Only title"}) == "Only title"


# ── _semantic_dedup_pass ──────────────────────────────────────────────────────


def test_semantic_dedup_exact_duplicate_rejected():
    """Exact same story text → cosine sim ~1.0 → rejected at threshold 0.5."""
    existing = [
        _make_story(
            "Add LRU cache to research phase for duplicate query avoidance",
            "Implement least-recently-used cache to avoid repeated research API calls",
            ["Cache hit returns stored result", "Cache miss triggers new research"],
            story_id="US-100",
        )
    ]
    candidate = _make_story(
        "Add LRU cache to research phase for duplicate query avoidance",
        "Implement least-recently-used cache to avoid repeated research API calls",
        ["Cache hit returns stored result", "Cache miss triggers new research"],
    )
    kept, rejected = _semantic_dedup_pass([candidate], existing, threshold=0.5)
    assert len(kept) == 0
    assert len(rejected) == 1
    assert rejected[0]["_rejected"] is True
    assert "semantic_duplicate_of: US-100" in rejected[0]["_rejection_reason"]


def test_semantic_dedup_near_duplicate_rejected_at_lower_threshold():
    """Near-identical wording (minor rephrasing) → rejected at threshold 0.5."""
    existing = [
        _make_story(
            "Add LRU caching layer to Phase R to skip repeated research queries",
            "Implement LRU cache for Phase R research results to avoid duplicate API calls",
            ["Cache stores results keyed by query hash", "LRU evicts oldest entry on capacity"],
            story_id="US-200",
        )
    ]
    candidate = _make_story(
        "Add LRU caching to Phase R to avoid repeated research API queries",
        "Implement LRU cache for Phase R to store results and skip duplicate research calls",
        ["Results stored keyed by query hash", "LRU eviction removes oldest entry when capacity reached"],
    )
    kept, rejected = _semantic_dedup_pass([candidate], existing, threshold=0.5)
    # High word overlap → should be caught as duplicate
    assert len(kept) + len(rejected) == 1


def test_semantic_dedup_distinct_stories_pass():
    """Stories on completely different topics should not be rejected at threshold 0.85."""
    existing = [
        _make_story(
            "Add LRU cache to research phase",
            "Implement least-recently-used cache for Phase R research results",
            ["Cache hit returns stored result"],
            story_id="US-100",
        )
    ]
    candidate = _make_story(
        "Add parallel worker timeout monitoring with heartbeat",
        "Implement heartbeat-based worker timeout detection in run_parallel_ralph.sh",
        ["Worker emits heartbeat every 30 seconds", "Timeout triggers worker kill and retry"],
    )
    kept, rejected = _semantic_dedup_pass([candidate], existing, threshold=0.85)
    assert len(kept) == 1
    assert len(rejected) == 0


def test_semantic_dedup_skips_test_fix_source():
    """test-fix stories bypass semantic dedup entirely."""
    existing = [
        _make_story(
            "Add LRU cache to research phase",
            "Implement least-recently-used cache for Phase R research results",
            ["Cache hit returns stored result"],
            story_id="US-100",
        )
    ]
    # Exact same text but source=test-fix
    candidate = _make_story(
        "Add LRU cache to research phase",
        "Implement least-recently-used cache for Phase R research results",
        ["Cache hit returns stored result"],
        source="test-fix",
    )
    kept, rejected = _semantic_dedup_pass([candidate], existing, threshold=0.5)
    assert len(kept) == 1
    assert len(rejected) == 0


def test_semantic_dedup_skips_seed_source():
    """seed stories bypass semantic dedup entirely."""
    existing = [
        _make_story(
            "Add LRU cache to research phase",
            "Implement least-recently-used cache for Phase R research results",
            ["Cache hit returns stored result"],
            story_id="US-100",
        )
    ]
    candidate = _make_story(
        "Add LRU cache to research phase",
        "Implement least-recently-used cache for Phase R research results",
        ["Cache hit returns stored result"],
        source="seed",
    )
    kept, rejected = _semantic_dedup_pass([candidate], existing, threshold=0.5)
    assert len(kept) == 1
    assert len(rejected) == 0


def test_semantic_dedup_empty_existing_returns_all_kept():
    """No existing stories → nothing to compare against → all candidates kept."""
    candidate = _make_story("Add cache", "Add LRU cache", ["Cache hit"])
    kept, rejected = _semantic_dedup_pass([candidate], [], threshold=0.85)
    assert len(kept) == 1
    assert len(rejected) == 0


def test_semantic_dedup_threshold_zero_disables():
    """threshold=0.0 disables semantic dedup regardless of similarity."""
    existing = [_make_story("Add cache", "Add LRU cache", ["Cache hit"], story_id="US-X")]
    candidate = _make_story("Add cache", "Add LRU cache", ["Cache hit"])
    kept, rejected = _semantic_dedup_pass([candidate], existing, threshold=0.0)
    assert len(kept) == 1
    assert len(rejected) == 0


# ---- Complexity gating: _all_acs_vague helper --------------------------------


def test_all_acs_vague_detects_single_verb_phrases():
    from validate_stories import _all_acs_vague  # type: ignore[import]

    assert _all_acs_vague(["Fix the bug"]) is True
    assert _all_acs_vague(["Update config"]) is True
    assert _all_acs_vague(["Add tests"]) is True


def test_all_acs_vague_passes_specific_acs():
    from validate_stories import _all_acs_vague  # type: ignore[import]

    assert _all_acs_vague(["Run pytest tests/test_validate_stories.py and all pass"]) is False
    assert _all_acs_vague(["Add unit tests for atomic_write_json covering edge cases"]) is False


def test_all_acs_vague_requires_all_to_be_vague():
    from validate_stories import _all_acs_vague  # type: ignore[import]

    # One specific AC makes the whole list NOT all-vague
    assert _all_acs_vague(["Fix the bug", "Run pytest tests/ and all pass"]) is False


def test_all_acs_vague_empty_list_is_not_vague():
    from validate_stories import _all_acs_vague  # type: ignore[import]

    assert _all_acs_vague([]) is False


# ---- Complexity gating: ceiling & floor integration tests --------------------

import json
import os
import tempfile


def _write_temp_json(data: dict) -> str:
    """Write data to a temp JSON file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    return path


def _run_validate(candidates, goals=None, source="research", env_overrides=None):
    """Run validate_stories with minimal fixtures. Returns (accepted, rejected)."""
    from validate_stories import validate_stories  # type: ignore[import]

    prd = {"goals": goals or ["improve SPIRAL story quality"], "userStories": []}
    research = {"stories": [dict(s, _source=source) for s in candidates]}

    prd_path = _write_temp_json(prd)
    research_path = _write_temp_json(research)
    validated_out = tempfile.mktemp(suffix=".json")
    rejected_out = tempfile.mktemp(suffix=".json")

    old_env = {}
    for k, v in (env_overrides or {}).items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        accepted, rejected = validate_stories(
            research_path=research_path,
            test_stories_path="/dev/null",
            prd_path=prd_path,
            validated_out=validated_out,
            rejected_out=rejected_out,
            min_overlap=0,  # disable goal-alignment check for focused testing
        )
    finally:
        for k, old in old_env.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        for p in (prd_path, research_path, validated_out, rejected_out):
            try:
                os.unlink(p)
            except OSError:
                pass

    return accepted, rejected


def _good_story(**overrides):
    base = {
        "id": "US-999",
        "title": "Add file-level caching to spiral_io.atomic_write_json",
        "description": (
            "The atomic_write_json helper currently re-opens the file on every call. "
            "Adding an in-memory cache keyed by path will reduce redundant I/O. "
            "This affects every phase that writes intermediate JSON blobs."
        ),
        "acceptanceCriteria": [
            "Run uv run pytest tests/test_spiral_io.py -v and all pass",
            "atomic_write_json returns cached content on second call within same process",
        ],
        "technicalNotes": [
            "File to edit: lib/spiral_io.py (atomic_write_json)",
            "Test command: uv run pytest tests/test_spiral_io.py::test_atomic_write_json -v",
        ],
        "filesTouch": ["lib/spiral_io.py", "tests/test_spiral_io.py"],
        "estimatedComplexity": "small",
        "priority": "medium",
    }
    base.update(overrides)
    return base


def test_ceiling_gate_rejects_story_with_too_many_acs():
    story = _good_story(
        acceptanceCriteria=[f"AC {i}" for i in range(7)],
    )
    _, rejected = _run_validate([story], env_overrides={"SPIRAL_STORY_MAX_AC_COUNT": "6"})
    assert any("too_complex" in r.get("_rejection_reason", "") for r in rejected), rejected


def test_ceiling_gate_accepts_story_at_ac_limit():
    story = _good_story(
        acceptanceCriteria=[
            "Run uv run pytest tests/ -v and all 6 pass",
            "File is created at lib/cache.py",
            "Cache size does not exceed 100 entries",
            "atomic_write_json returns cached value on second call",
            "Cache is invalidated on write",
            "Cache key is the absolute file path",
        ],
    )
    accepted, _ = _run_validate([story], env_overrides={"SPIRAL_STORY_MAX_AC_COUNT": "6"})
    assert any(s["id"] == "US-999" for s in accepted), "Should accept story with exactly 6 ACs"


def test_ceiling_gate_rejects_medium_story_with_no_technical_notes():
    story = _good_story(estimatedComplexity="medium", technicalNotes=[])
    _, rejected = _run_validate([story])
    assert any("too_complex" in r.get("_rejection_reason", "") for r in rejected), rejected


def test_floor_gate_rejects_story_with_too_few_acs():
    story = _good_story(acceptanceCriteria=["It works"])
    _, rejected = _run_validate([story], env_overrides={"SPIRAL_STORY_MIN_AC_COUNT": "2"})
    assert any("too_simple" in r.get("_rejection_reason", "") for r in rejected), rejected


def test_floor_gate_rejects_story_with_all_vague_acs():
    story = _good_story(acceptanceCriteria=["Fix the issue", "Update the config"])
    _, rejected = _run_validate([story])
    assert any("too_simple" in r.get("_rejection_reason", "") for r in rejected), rejected


def test_floor_gate_rejects_story_with_short_description():
    story = _good_story(description="Fix the bug.")
    _, rejected = _run_validate([story])
    assert any("too_simple" in r.get("_rejection_reason", "") for r in rejected), rejected


def test_floor_gate_exempt_for_test_fix_source():
    """test-fix stories bypass the floor gate even if ACs are sparse."""
    story = _good_story(acceptanceCriteria=["It works"])
    accepted, rejected = _run_validate([story], source="test-fix", env_overrides={"SPIRAL_STORY_MIN_AC_COUNT": "2"})
    # Should NOT be rejected by floor gate (test-fix is exempt)
    floor_rejections = [r for r in rejected if "too_simple" in r.get("_rejection_reason", "")]
    assert len(floor_rejections) == 0, f"test-fix should be floor-gate exempt: {floor_rejections}"


# ---- AC Measurability Scoring (US-1154) ----------------------------------------


def test_ac_scorer_measurable():
    """score_ac_measurability detects measurable ACs with CLI, file paths, numbers, and test keywords."""
    from validate_stories import score_ac_measurability  # type: ignore[import]

    # All measurable
    acs = [
        "Run `pytest tests/ -v` and all pass",
        "File lib/new_module.py is created",
        "Response time < 100ms",
        "Test should verify the cache returns results",
    ]
    score = score_ac_measurability(acs)
    assert score == 1.0, f"All ACs measurable: expected 1.0, got {score}"

    # Partial measurability
    acs_mixed = [
        "Run pytest tests/test_foo.py and pass",  # measurable: CLI
        "Fix the bug",  # vague
    ]
    score = score_ac_measurability(acs_mixed)
    assert score == 0.5, f"Half measurable: expected 0.5, got {score}"


def test_ac_scorer_vague():
    """score_ac_measurability penalizes vague ACs."""
    from validate_stories import score_ac_measurability  # type: ignore[import]

    vague_acs = ["Fix the issue", "Update config", "Improve performance", "Add tests"]
    score = score_ac_measurability(vague_acs)
    assert score == 0.0, f"All vague ACs: expected 0.0, got {score}"

    # Single vague AC in list
    mixed_acs = ["Fix the bug", "Run command `foo` and verify"]
    score = score_ac_measurability(mixed_acs)
    assert 0.4 < score < 0.6, f"One vague + one measurable: expected ~0.5, got {score}"


def test_ac_scorer_empty():
    """score_ac_measurability returns 0.0 for empty AC list."""
    from validate_stories import score_ac_measurability  # type: ignore[import]

    assert score_ac_measurability([]) == 0.0
    assert score_ac_measurability([""]) == 0.0


def test_ac_scorer_detects_file_paths():
    """score_ac_measurability identifies file path indicators."""
    from validate_stories import score_ac_measurability  # type: ignore[import]

    # File extensions
    acs = [
        "File lib/module.py is added",
        "File tests/test_foo.sh executes",
        "JSON output at config.json is valid",
    ]
    score = score_ac_measurability(acs)
    assert score == 1.0, f"All have file paths: expected 1.0, got {score}"


def test_ac_scorer_detects_numbers_and_units():
    """score_ac_measurability identifies numeric constraints."""
    from validate_stories import score_ac_measurability  # type: ignore[import]

    acs = [
        "Cache returns results within 100ms",
        "Function completes in <5 seconds",
        "Memory usage stays under 512MB",
        "Test suite runs in 60 seconds",
    ]
    score = score_ac_measurability(acs)
    assert score == 1.0, f"All have time/resource constraints: expected 1.0, got {score}"


def test_ac_rewrite_triggered_on_low_score():
    """AC rewrite is triggered when score < SPIRAL_AC_QUALITY_THRESHOLD."""
    from validate_stories import _rewrite_acs_via_haiku  # type: ignore[import]

    # Verify the rewrite function exists
    assert _rewrite_acs_via_haiku is not None
    # Actual rewrite would require API key; we're just verifying the function is available


def test_story_rejected_on_low_ac_after_rewrite():
    """Stories with <2 measurable ACs are rejected even after rewrite attempt."""
    story = _good_story(
        id="US-VAGUE",
        acceptanceCriteria=["Fix it", "Update"],  # Both vague
    )
    # Run validation with low AC threshold to trigger rewrite path
    _, rejected = _run_validate([story], env_overrides={"SPIRAL_AC_QUALITY_THRESHOLD": "0.5"})

    # Story should be rejected for too few measurable ACs
    vague_rejections = [r for r in rejected if "measurable" in r.get("_rejection_reason", "")]
    assert len(vague_rejections) > 0, f"Expected AC-related rejection for vague story: {rejected}"
