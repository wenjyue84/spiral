"""Integration test: Phase E injects episodic memory past_patterns into stories."""

from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.research.enrich_stories import enrich_stories

# Long description shared across query story and memory records to ensure high similarity
_SHARED_DESC = (
    "implement episodic memory pattern retrieval for story enrichment "
    "to reuse successful implementation patterns from previous stories"
)


def _write_validated(path: str, stories: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"stories": stories}, f)


def _make_memory_record(story_id: str, description: str) -> dict:
    return {
        "story_id": story_id,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "description": description,
        "outcome": "pass",
        "approach": "standard implementation",
    }


class TestPhaseEEpisodicPatternInjection:
    def test_three_similar_patterns_injected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Phase E injects top-3 episodic patterns with >0.7 similarity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Build episodic memory JSONL with 3 similar records
            mem_path = os.path.join(tmpdir, "episodic_memory.jsonl")
            with open(mem_path, "w", encoding="utf-8") as f:
                for i in range(1, 4):
                    rec = _make_memory_record(f"US-{i}", _SHARED_DESC)
                    f.write(json.dumps(rec) + "\n")

            monkeypatch.setenv("SPIRAL_EPISODIC_MEMORY", mem_path)

            # Validated story uses same description → high cosine similarity
            story = {
                "id": "US-999",
                "title": "Test Story",
                "priority": "medium",
                "description": _SHARED_DESC,
                "acceptanceCriteria": ["something works"],
                "technicalNotes": ["note1", "note2"],
                "filesTouch": ["lib/x.py"],
                "estimatedComplexity": "small",
                "_source": "research",
                "passes": False,
            }

            validated_path = os.path.join(tmpdir, "validated.json")
            enriched_path = os.path.join(tmpdir, "enriched.json")
            _write_validated(validated_path, [story])

            enrich_stories(validated_path, enriched_path, dry_run=True)

            with open(enriched_path, encoding="utf-8") as f:
                output = json.load(f)

            out_stories = output["stories"]
            assert len(out_stories) == 1
            out_story = out_stories[0]

            # AC1: past_patterns injected into enrichment field
            assert "enrichment" in out_story, "missing 'enrichment' field"
            patterns = out_story["enrichment"].get("past_patterns", [])
            assert len(patterns) == 3, f"expected 3 patterns, got {len(patterns)}"

            # AC2: each pattern has similarity_score > 0.7
            for p in patterns:
                score = p.get("similarity_score", 0.0)
                assert score > 0.7, f"similarity_score {score} not > 0.7 for pattern {p.get('story_id')}"

    def test_no_memory_file_does_not_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When episodic memory file does not exist, enrichment runs without past_patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("SPIRAL_EPISODIC_MEMORY", os.path.join(tmpdir, "nonexistent.jsonl"))

            story = {
                "id": "US-998",
                "title": "No Memory Story",
                "priority": "low",
                "description": "some description",
                "acceptanceCriteria": ["it works"],
                "technicalNotes": ["note1", "note2"],
                "filesTouch": ["lib/y.py"],
                "estimatedComplexity": "small",
                "_source": "research",
                "passes": False,
            }
            validated_path = os.path.join(tmpdir, "validated.json")
            enriched_path = os.path.join(tmpdir, "enriched.json")
            _write_validated(validated_path, [story])

            enrich_stories(validated_path, enriched_path, dry_run=True)

            with open(enriched_path, encoding="utf-8") as f:
                output = json.load(f)

            out_story = output["stories"][0]
            # No past_patterns when memory file is absent
            patterns = out_story.get("enrichment", {}).get("past_patterns", [])
            assert patterns == []
