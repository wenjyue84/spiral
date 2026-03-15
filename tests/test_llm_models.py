#!/usr/bin/env python3
"""Tests for lib/llm_models.py — Pydantic v2 models for LLM JSON outputs (US-203)."""
import json
import os
import sys
import tempfile

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from llm_models import (
    DecompositionResult,
    ResearchOutput,
    RouteStoriesResult,
    StoryCandidate,
    SubStory,
    FailingTestStory,
    TestSynthesisReport,
    log_validation_error,
    validate_llm_json,
)


# ── DecompositionResult ──────────────────────────────────────────────────────


class TestDecompositionResult:
    def test_valid_full(self):
        data = {
            "ordered": True,
            "stories": [
                {
                    "title": "Create schema",
                    "description": "Add DB schema",
                    "acceptanceCriteria": ["Schema exists"],
                    "technicalNotes": ["Use Drizzle"],
                    "estimatedComplexity": "small",
                },
                {
                    "title": "Add API endpoint",
                    "acceptanceCriteria": ["Endpoint works"],
                },
            ],
        }
        result = DecompositionResult.model_validate(data)
        assert result.ordered is True
        assert len(result.stories) == 2
        assert result.stories[0].title == "Create schema"
        assert result.stories[1].description == ""  # default

    def test_valid_minimal(self):
        data = {"stories": [{"title": "Fix bug"}]}
        result = DecompositionResult.model_validate(data)
        assert result.ordered is False  # default
        assert len(result.stories) == 1
        assert result.stories[0].estimatedComplexity == "small"

    def test_empty_stories(self):
        data = {"ordered": False, "stories": []}
        result = DecompositionResult.model_validate(data)
        assert result.stories == []

    def test_missing_title_fails(self):
        data = {"stories": [{"description": "no title here"}]}
        with pytest.raises(ValidationError) as exc_info:
            DecompositionResult.model_validate(data)
        errors = exc_info.value.errors()
        assert any("title" in str(e["loc"]) for e in errors)

    def test_wrong_type_stories_fails(self):
        data = {"stories": "not a list"}
        with pytest.raises(ValidationError):
            DecompositionResult.model_validate(data)

    def test_defaults_applied(self):
        data = {"stories": [{"title": "Test"}]}
        result = DecompositionResult.model_validate(data)
        story = result.stories[0]
        assert story.description == ""
        assert story.acceptanceCriteria == []
        assert story.technicalNotes == []
        assert story.estimatedComplexity == "small"


# ── ResearchOutput ───────────────────────────────────────────────────────────


class TestResearchOutput:
    def test_valid_research(self):
        data = {
            "stories": [
                {
                    "title": "Add caching layer",
                    "priority": "high",
                    "description": "Implement Redis caching",
                    "acceptanceCriteria": ["Cache hit rate > 80%"],
                    "technicalNotes": ["Use Redis"],
                    "dependencies": ["US-001"],
                    "estimatedComplexity": "medium",
                    "tags": ["performance"],
                }
            ]
        }
        result = ResearchOutput.model_validate(data)
        assert len(result.stories) == 1
        assert result.stories[0].priority == "high"
        assert result.stories[0].tags == ["performance"]

    def test_empty_stories(self):
        result = ResearchOutput.model_validate({"stories": []})
        assert result.stories == []

    def test_extra_fields_allowed(self):
        data = {
            "stories": [
                {
                    "title": "Test",
                    "_source": "research",
                    "epicId": "EPIC-1",
                    "_isTestFix": True,
                }
            ]
        }
        result = ResearchOutput.model_validate(data)
        assert len(result.stories) == 1

    def test_missing_title_fails(self):
        data = {"stories": [{"priority": "high"}]}
        with pytest.raises(ValidationError):
            ResearchOutput.model_validate(data)

    def test_defaults(self):
        data = {"stories": [{"title": "Minimal"}]}
        result = ResearchOutput.model_validate(data)
        s = result.stories[0]
        assert s.priority == "medium"
        assert s.dependencies == []
        assert s.tags == []


# ── RouteStoriesResult ───────────────────────────────────────────────────────


class TestRouteStoriesResult:
    def test_valid_routed(self):
        data = {
            "userStories": [
                {"id": "US-001", "title": "Feature A", "model": "sonnet"},
                {"id": "US-002", "title": "Feature B", "model": "haiku"},
            ]
        }
        result = RouteStoriesResult.model_validate(data)
        assert len(result.userStories) == 2
        assert result.userStories[0].model == "sonnet"

    def test_extra_fields_preserved(self):
        data = {
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Feature",
                    "model": "sonnet",
                    "passes": False,
                    "priority": "high",
                }
            ],
            "goals": ["Build great software"],
        }
        result = RouteStoriesResult.model_validate(data)
        assert len(result.userStories) == 1


# ── TestSynthesisReport ──────────────────────────────────────────────────────


class TestTestSynthesisReport:
    def test_valid_report(self):
        data = {
            "stories": [
                {
                    "title": "Fix failing test: auth",
                    "priority": "high",
                    "description": "Auth test failing",
                    "acceptanceCriteria": ["Test passes"],
                    "technicalNotes": ["Test ID: test_auth"],
                    "dependencies": [],
                    "estimatedComplexity": "small",
                }
            ]
        }
        result = TestSynthesisReport.model_validate(data)
        assert len(result.stories) == 1
        assert result.stories[0].estimatedComplexity == "small"

    def test_extra_source_field(self):
        data = {
            "stories": [
                {"title": "Fix test", "_source": "test-synthesis:test_foo"}
            ]
        }
        result = TestSynthesisReport.model_validate(data)
        assert len(result.stories) == 1


# ── log_validation_error ─────────────────────────────────────────────────────


class TestLogValidationError:
    def test_writes_jsonl_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                DecompositionResult.model_validate({"stories": [{"no_title": True}]})
            except ValidationError as exc:
                log_validation_error(
                    exc,
                    {"stories": [{"no_title": True}]},
                    "test_context",
                    scratch_dir=tmpdir,
                )

            log_path = os.path.join(tmpdir, "spiral_events.jsonl")
            assert os.path.exists(log_path)

            with open(log_path, encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) == 1

            entry = json.loads(lines[0])
            assert entry["event"] == "validation_error"
            assert entry["context"] == "test_context"
            assert entry["error_count"] >= 1
            assert len(entry["errors"]) >= 1
            assert "field_path" in entry["errors"][0]
            assert "message" in entry["errors"][0]
            assert "received_value" in entry["errors"][0]

    def test_includes_field_path_and_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                DecompositionResult.model_validate({"stories": "wrong_type"})
            except ValidationError as exc:
                log_validation_error(exc, {"stories": "wrong_type"}, "test", scratch_dir=tmpdir)

            log_path = os.path.join(tmpdir, "spiral_events.jsonl")
            with open(log_path, encoding="utf-8") as f:
                entry = json.loads(f.readline())
            # Should report the field path to stories
            assert any("stories" in e["field_path"] for e in entry["errors"])

    def test_truncates_large_raw_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            huge_data = {"stories": "x" * 5000}
            try:
                DecompositionResult.model_validate(huge_data)
            except ValidationError as exc:
                log_validation_error(exc, huge_data, "truncation_test", scratch_dir=tmpdir)

            log_path = os.path.join(tmpdir, "spiral_events.jsonl")
            with open(log_path, encoding="utf-8") as f:
                entry = json.loads(f.readline())
            assert "truncated" in entry["raw_output"]


# ── validate_llm_json helper ─────────────────────────────────────────────────


class TestValidateLlmJson:
    def test_success(self):
        data = {"stories": [{"title": "Valid story"}]}
        result = validate_llm_json(ResearchOutput, data, "test")
        assert isinstance(result, ResearchOutput)
        assert len(result.stories) == 1

    def test_failure_raises_and_logs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValidationError):
                validate_llm_json(
                    DecompositionResult,
                    {"stories": [{}]},
                    "test_fail",
                    scratch_dir=tmpdir,
                )
            log_path = os.path.join(tmpdir, "spiral_events.jsonl")
            assert os.path.exists(log_path)

    def test_model_dump_roundtrip(self):
        """Validated output can be model_dump()ed back to dict for downstream."""
        data = {
            "ordered": True,
            "stories": [
                {"title": "A", "acceptanceCriteria": ["x"]},
                {"title": "B", "acceptanceCriteria": ["y"]},
            ],
        }
        result = validate_llm_json(DecompositionResult, data, "roundtrip")
        dumped = result.model_dump()
        assert dumped["ordered"] is True
        assert len(dumped["stories"]) == 2
        assert dumped["stories"][0]["title"] == "A"
