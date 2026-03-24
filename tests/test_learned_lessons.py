"""Tests for lib/learned_lessons.py — self-evolving lesson store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.learned_lessons import (
    _make_lesson,
    _overlap,
    _tokenize,
    append_lesson,
    load_lessons,
    main,
    promote_to_skill,
    query_lessons,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def lessons_path(tmp_path: Path) -> Path:
    return tmp_path / "learned_lessons.jsonl"


@pytest.fixture()
def skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills" / "learned"
    d.mkdir(parents=True)
    return d


def _lesson(
    pattern: str = "missing init export",
    fix: str = "update __init__.py",
    category: str = "compilation-error",
    story_id: str = "US-100",
    title: str = "Add foo() to lib/bar.py",
    seen: int = 1,
    confidence: float = 0.5,
) -> dict:
    lesson = _make_lesson(category, pattern, fix, story_id, title)
    lesson["seen_count"] = seen
    lesson["confidence"] = confidence
    return lesson


# ── tokenize / overlap ──────────────────────────────────────────────────────

def test_tokenize_basic() -> None:
    tokens = _tokenize("Missing __init__.py export")
    assert "missing" in tokens
    assert "init" in tokens
    assert "export" in tokens


def test_overlap_identical() -> None:
    assert _overlap("hello world", "hello world") == 1.0


def test_overlap_disjoint() -> None:
    assert _overlap("alpha beta", "gamma delta") == 0.0


def test_overlap_partial() -> None:
    score = _overlap("missing init export", "missing init import")
    assert 0.3 < score < 0.9


def test_overlap_empty() -> None:
    assert _overlap("", "something") == 0.0
    assert _overlap("a", "") == 0.0


# ── load / append ────────────────────────────────────────────────────────────

def test_load_empty(lessons_path: Path) -> None:
    assert load_lessons(lessons_path) == []


def test_append_creates_file(lessons_path: Path) -> None:
    lesson = _lesson()
    result = append_lesson(lessons_path, lesson)
    assert result["seen_count"] == 1
    assert lessons_path.exists()
    loaded = load_lessons(lessons_path)
    assert len(loaded) == 1
    assert loaded[0]["pattern"] == "missing init export"


def test_append_dedup_bumps_seen_count(lessons_path: Path) -> None:
    """Appending an identical pattern should bump seen_count, not add new."""
    append_lesson(lessons_path, _lesson(pattern="missing init export"))
    append_lesson(lessons_path, _lesson(pattern="missing init export"))
    loaded = load_lessons(lessons_path)
    assert len(loaded) == 1
    assert loaded[0]["seen_count"] == 2
    assert loaded[0]["confidence"] == 0.6


def test_append_different_category_not_deduped(lessons_path: Path) -> None:
    """Same pattern but different category should NOT dedup."""
    append_lesson(lessons_path, _lesson(category="compilation-error"))
    append_lesson(lessons_path, _lesson(category="test-failure"))
    loaded = load_lessons(lessons_path)
    assert len(loaded) == 2


def test_append_different_pattern_not_deduped(lessons_path: Path) -> None:
    """Different patterns should create separate lessons."""
    append_lesson(lessons_path, _lesson(pattern="missing init export"))
    append_lesson(lessons_path, _lesson(pattern="timeout in database query"))
    loaded = load_lessons(lessons_path)
    assert len(loaded) == 2


# ── query_lessons ────────────────────────────────────────────────────────────

def test_query_empty(lessons_path: Path) -> None:
    story = {"title": "Add something", "description": "test"}
    assert query_lessons(lessons_path, story) == []


def test_query_matches_by_title(lessons_path: Path) -> None:
    append_lesson(
        lessons_path,
        _lesson(
            pattern="missing init export",
            title="Add foo() to lib/bar.py",
        ),
    )
    story = {"title": "Add baz() to lib/bar.py", "description": "new function"}
    results = query_lessons(lessons_path, story, top_k=5)
    assert len(results) == 1
    assert results[0]["pattern"] == "missing init export"


def test_query_respects_top_k(lessons_path: Path) -> None:
    for i in range(10):
        append_lesson(
            lessons_path,
            _lesson(
                pattern=f"error pattern {i} with module lib",
                story_id=f"US-{i}",
                title=f"Add function_{i} to lib/module.py",
            ),
        )
    story = {"title": "Add function to lib/module.py", "description": "lib work"}
    results = query_lessons(lessons_path, story, top_k=3)
    assert len(results) <= 3


def test_query_ranks_by_seen_count(lessons_path: Path) -> None:
    append_lesson(
        lessons_path,
        _lesson(pattern="common lib error", seen=5, confidence=0.9, story_id="US-1"),
    )
    append_lesson(
        lessons_path,
        _lesson(pattern="rare lib error", seen=1, confidence=0.5, story_id="US-2"),
    )
    story = {"title": "Fix lib error", "description": "lib module fix"}
    results = query_lessons(lessons_path, story, top_k=2)
    assert len(results) == 2
    # Higher seen_count * confidence should rank first
    assert results[0]["seen_count"] >= results[1]["seen_count"]


# ── promote_to_skill ─────────────────────────────────────────────────────────

def test_promote_below_threshold(lessons_path: Path, skills_dir: Path) -> None:
    append_lesson(lessons_path, _lesson(seen=2))
    created = promote_to_skill(lessons_path, skills_dir, threshold=3)
    assert created == []


def test_promote_at_threshold(lessons_path: Path, skills_dir: Path) -> None:
    # Manually write a lesson with seen_count=3
    lesson = _lesson(seen=3, confidence=0.7)
    lessons_path.parent.mkdir(parents=True, exist_ok=True)
    lessons_path.write_text(json.dumps(lesson) + "\n", encoding="utf-8")

    created = promote_to_skill(lessons_path, skills_dir, threshold=3)
    assert len(created) == 1
    content = created[0].read_text(encoding="utf-8")
    assert "missing init export" in content.lower() or "Missing" in content
    assert "Seen 3 times" in content


def test_promote_idempotent(lessons_path: Path, skills_dir: Path) -> None:
    lesson = _lesson(seen=5)
    lessons_path.write_text(json.dumps(lesson) + "\n", encoding="utf-8")
    first = promote_to_skill(lessons_path, skills_dir, threshold=3)
    second = promote_to_skill(lessons_path, skills_dir, threshold=3)
    assert len(first) == 1
    assert len(second) == 0  # Already exists, skip


# ── CLI: extract ─────────────────────────────────────────────────────────────

def test_extract_cli_no_results(tmp_path: Path) -> None:
    """extract with missing results.tsv should not crash."""
    lessons = tmp_path / "lessons.jsonl"
    main([
        "extract",
        "--results", str(tmp_path / "results.tsv"),
        "--prd", str(tmp_path / "prd.json"),
        "--lessons", str(lessons),
    ])
    # No crash, no file created
    assert not lessons.exists()


def test_extract_cli_with_failures(tmp_path: Path) -> None:
    """extract should create lessons from failed rows in results.tsv."""
    # Write a minimal results.tsv
    results = tmp_path / "results.tsv"
    results.write_text(
        "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
        "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\t"
        "cache_hit\tcache_read_tokens\tcache_creation_tokens\treview_tokens\t"
        "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\t"
        "batch_id\tvotes_accept\tvotes_reject\tconflict_files\t"
        "failure_root_cause\tsub_project\tfailed_files\tscope_tag\terror_category\n"
        "2026-03-23T10:00:00Z\t1\t1\tUS-100\tAdd widget\tfail\t30\tsonnet\t0\tabc123\trun1\t"
        "\t\t\t\t\t\t\t\t\t\t\t\t"
        "SyntaxError: invalid syntax in widget.py\t\t\t\tcompilation-error\n",
        encoding="utf-8",
    )
    prd = tmp_path / "prd.json"
    prd.write_text('{"userStories": [{"id": "US-100", "title": "Add widget"}]}')

    lessons_path = tmp_path / "lessons.jsonl"
    main([
        "extract",
        "--results", str(results),
        "--prd", str(prd),
        "--lessons", str(lessons_path),
        "--iteration", "1",
    ])
    assert lessons_path.exists()
    loaded = load_lessons(lessons_path)
    assert len(loaded) == 1
    assert loaded[0]["error_category"] == "compilation-error"
    assert "SyntaxError" in loaded[0]["pattern"]


# ── CLI: inject ──────────────────────────────────────────────────────────────

def test_inject_cli_no_lessons(tmp_path: Path) -> None:
    """inject with no lessons file should pass through stories unchanged."""
    validated = tmp_path / "validated.json"
    validated.write_text(json.dumps({
        "stories": [{"id": "US-200", "title": "New feature"}]
    }))
    output = tmp_path / "enriched.json"
    main([
        "inject",
        "--lessons", str(tmp_path / "nonexistent.jsonl"),
        "--validated-in", str(validated),
        "--enriched-out", str(output),
    ])
    assert output.exists()
    data = json.loads(output.read_text())
    assert "_learned_lessons" not in data["stories"][0]


def test_inject_cli_with_matching_lessons(tmp_path: Path) -> None:
    """inject should add _learned_lessons to stories with matching patterns."""
    lessons_path = tmp_path / "lessons.jsonl"
    append_lesson(
        lessons_path,
        _lesson(
            pattern="missing init export in lib module",
            fix="update __init__.py re-exports",
            title="Add function to lib/bar.py",
        ),
    )
    validated = tmp_path / "validated.json"
    validated.write_text(json.dumps({
        "stories": [{"id": "US-300", "title": "Add helper to lib/bar.py"}]
    }))
    output = tmp_path / "enriched.json"
    main([
        "inject",
        "--lessons", str(lessons_path),
        "--validated-in", str(validated),
        "--enriched-out", str(output),
        "--top-k", "3",
    ])
    data = json.loads(output.read_text())
    story = data["stories"][0]
    assert "_learned_lessons" in story
    assert len(story["_learned_lessons"]) >= 1
    assert "pattern" in story["_learned_lessons"][0]
    assert "fix" in story["_learned_lessons"][0]
