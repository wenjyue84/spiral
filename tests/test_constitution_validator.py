#!/usr/bin/env python3
"""
tests/test_constitution_validator.py — Tests for Phase S constitution validation

Test coverage:
  - parse_constitution_rules: Extract rules from constitution.md
  - validate_story: Validate stories against rules and antiPatterns
  - match_antipattern: Detect antipattern matches in text
  - log_rejection: Write rejection entries to JSON log
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add lib to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from constitution_validator import (
    log_rejection,
    match_antipattern,
    parse_constitution_rules,
    validate_story,
)


@pytest.fixture
def sample_constitution_file() -> str:
    """Create a temporary constitution.md file for testing."""
    content = """
# Spiral Project Constitution

## Core Invariants (Never Break These)
1. **Phase ordering** — 0 → A → R+T → S → E → M → X → G+I → V → P → C → L
2. **Clarify first** — Phase 0 establishes constitution, focus, and scope
3. **Git ratchet** — No story may weaken the gate chain
4. **Story atomicity** — Each story is one independent unit
5. **Backward compatibility** — Environment variables are user-facing API

## What Stories Must NOT Do
- Add features that require re-architecting the phase structure
- Remove or bypass existing quality gates (secret scan, security scan, test ratchet)
- Add hard dependencies on tools not auto-installed by setup.sh
- Commit broken intermediate states
- Skip or remove the Clarify phase (Phase 0)
- Use hardcoded credentials in code
- Introduce SQL injection vulnerabilities

### Anti-Patterns to Avoid
- Stories that only change internal file formats with no user-facing effect
- Add X for future use stories with no current consumer
- Duplicate coverage of already-tested code paths
- Features that require rare external dependencies
- Telemetry infrastructure before there is a consumer UI
- Hardcoded API keys or secrets
- Unvalidated user input in security-critical code

## Acceptable Story Scope
- Improving existing phases
- Adding optional capabilities behind env var flags
- Expanding test coverage
- Fixing bugs in existing behaviour
- Improving documentation and onboarding
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        temp_path = f.name
    yield temp_path
    os.unlink(temp_path)


@pytest.fixture
def empty_constitution_file() -> str:
    """Create an empty temporary file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        temp_path = f.name
    yield temp_path
    os.unlink(temp_path)


class TestParseConstitutionRules:
    """Tests for parse_constitution_rules()."""

    def test_parses_core_invariants(self, sample_constitution_file: str) -> None:
        """Parse Core Invariants section."""
        rules = parse_constitution_rules(sample_constitution_file)
        assert "core_invariants" in rules
        assert len(rules["core_invariants"]) > 0
        # Core invariants are extracted with original capitalization
        assert any("ordering" in inv.lower() for inv in rules["core_invariants"])

    def test_parses_forbidden_phrases(
        self, sample_constitution_file: str
    ) -> None:
        """Parse What Stories Must NOT Do as forbidden phrases."""
        rules = parse_constitution_rules(sample_constitution_file)
        assert "forbidden_phrases" in rules
        assert len(rules["forbidden_phrases"]) > 0
        # Check some forbidden phrases
        forbidden_text = " ".join(rules["forbidden_phrases"]).lower()
        assert "bypass" in forbidden_text or "skip" in forbidden_text

    def test_parses_antipatterns(self, sample_constitution_file: str) -> None:
        """Parse Anti-Patterns to Avoid section."""
        rules = parse_constitution_rules(sample_constitution_file)
        assert "antipatterns" in rules
        assert len(rules["antipatterns"]) > 0
        antipattern_text = " ".join(rules["antipatterns"]).lower()
        assert "hardcoded" in antipattern_text or "future" in antipattern_text

    def test_handles_missing_file(self) -> None:
        """Handle missing constitution file gracefully."""
        rules = parse_constitution_rules("/nonexistent/constitution.md")
        assert isinstance(rules, dict)
        assert rules["rules"] == []
        assert rules["antipatterns"] == []

    def test_handles_empty_file(self, empty_constitution_file: str) -> None:
        """Handle empty constitution file."""
        rules = parse_constitution_rules(empty_constitution_file)
        assert isinstance(rules, dict)
        assert len(rules["antipatterns"]) == 0


class TestMatchAntipattern:
    """Tests for match_antipattern()."""

    def test_matches_simple_pattern(self) -> None:
        """Match simple substring antipattern."""
        patterns = ["hardcoded credentials", "unvalidated input"]
        matched, pattern = match_antipattern(
            "Store API keys as hardcoded credentials", patterns
        )
        assert matched is True
        assert pattern == "hardcoded credentials"

    def test_no_match_returns_empty_pattern(self) -> None:
        """Return empty string when no pattern matches."""
        patterns = ["hardcoded credentials", "sql injection"]
        matched, pattern = match_antipattern(
            "This is a safe story description", patterns
        )
        assert matched is False
        assert pattern == ""

    def test_case_insensitive_matching(self) -> None:
        """Match patterns case-insensitively."""
        patterns = ["hardcoded credentials"]
        matched, pattern = match_antipattern(
            "Do NOT use HARDCODED CREDENTIALS", patterns
        )
        assert matched is True
        assert pattern == "hardcoded credentials"

    def test_empty_patterns_list(self) -> None:
        """Handle empty patterns list."""
        matched, pattern = match_antipattern("Some text", [])
        assert matched is False
        assert pattern == ""

    def test_none_pattern_ignored(self) -> None:
        """Skip empty/None patterns in list."""
        patterns = ["", "hardcoded credentials", None]  # type: ignore
        matched, pattern = match_antipattern(
            "This mentions hardcoded credentials", patterns
        )
        assert matched is True
        assert pattern == "hardcoded credentials"


class TestValidateStory:
    """Tests for validate_story()."""

    def test_valid_story_passes(self, sample_constitution_file: str) -> None:
        """Valid story passes validation."""
        rules = parse_constitution_rules(sample_constitution_file)
        story = {
            "id": "US-123",
            "title": "Improve phase performance",
            "description": "Speed up Phase S validation by caching",
        }
        is_valid, reason = validate_story(story, rules)
        assert is_valid is True
        assert reason == ""

    def test_story_with_forbidden_phrase_rejected(
        self, sample_constitution_file: str
    ) -> None:
        """Story with forbidden phrase is rejected."""
        rules = parse_constitution_rules(sample_constitution_file)
        story = {
            "id": "US-124",
            "title": "Bypass quality gates",
            "description": "Remove or bypass existing quality gates",
        }
        is_valid, reason = validate_story(story, rules)
        assert is_valid is False
        assert "forbidden" in reason or "bypass" in reason

    def test_story_with_antipattern_rejected(
        self, sample_constitution_file: str
    ) -> None:
        """Story matching antipattern is rejected."""
        rules = parse_constitution_rules(sample_constitution_file)
        story = {
            "id": "US-125",
            "title": "Refactoring",
            "description": "Stories that only change internal file formats with no user-facing effect",
        }
        is_valid, reason = validate_story(story, rules)
        assert is_valid is False
        assert "antipattern" in reason

    def test_story_missing_title(
        self, sample_constitution_file: str
    ) -> None:
        """Story without title is rejected."""
        rules = parse_constitution_rules(sample_constitution_file)
        story = {
            "id": "US-126",
            "title": "",
            "description": "Some description",
        }
        is_valid, reason = validate_story(story, rules)
        assert is_valid is False
        assert "title" in reason

    def test_story_missing_description(
        self, sample_constitution_file: str
    ) -> None:
        """Story without description is rejected."""
        rules = parse_constitution_rules(sample_constitution_file)
        story = {
            "id": "US-127",
            "title": "Some title",
            "description": "",
        }
        is_valid, reason = validate_story(story, rules)
        assert is_valid is False
        assert "description" in reason

    def test_story_missing_id(self, sample_constitution_file: str) -> None:
        """Story without ID is rejected."""
        rules = parse_constitution_rules(sample_constitution_file)
        story = {
            "id": "",
            "title": "Some title",
            "description": "Some description",
        }
        is_valid, reason = validate_story(story, rules)
        assert is_valid is False
        assert "id" in reason

    def test_invalid_story_type(
        self, sample_constitution_file: str
    ) -> None:
        """Non-dict story is rejected."""
        rules = parse_constitution_rules(sample_constitution_file)
        is_valid, reason = validate_story("not a dict", rules)  # type: ignore
        assert is_valid is False
        assert "type" in reason

    def test_detects_antipatterns(
        self, sample_constitution_file: str
    ) -> None:
        """All antipattern types are detected."""
        rules = parse_constitution_rules(sample_constitution_file)

        # Test "only change internal file format" antipattern (match extracted text exactly)
        story = {
            "id": "US-200",
            "title": "Refactor internal file format",
            "description": "Stories that only change internal file formats with no user-facing effect",
        }
        is_valid, reason = validate_story(story, rules)
        assert is_valid is False
        assert "antipattern" in reason or "internal" in reason


class TestLogRejection:
    """Tests for log_rejection()."""

    def test_logs_rejection_to_file(self) -> None:
        """Log rejection creates or appends to JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "_rejected_stories.json")
            story = {
                "id": "US-999",
                "title": "Bad story",
                "description": "Violates constitution",
            }
            log_rejection(story, "antipattern: hardcoded_creds", output_file=output_file)

            assert os.path.exists(output_file)
            with open(output_file, encoding="utf-8") as fh:
                data = json.load(fh)
            assert "rejections" in data
            assert len(data["rejections"]) == 1
            assert data["rejections"][0]["story_id"] == "US-999"
            assert data["rejections"][0]["rule_violated"] == "antipattern"
            assert data["total"] == 1

    def test_appends_multiple_rejections(self) -> None:
        """Multiple rejections are appended to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "_rejected_stories.json")

            for i in range(3):
                story = {
                    "id": f"US-{1000 + i}",
                    "title": f"Bad story {i}",
                    "description": "Violates constitution",
                }
                log_rejection(story, "forbidden_phrase: xyz", output_file=output_file)

            with open(output_file, encoding="utf-8") as fh:
                data = json.load(fh)
            assert len(data["rejections"]) == 3
            assert data["total"] == 3

    def test_rejection_includes_timestamp(self) -> None:
        """Rejection entry includes timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "_rejected_stories.json")
            story = {"id": "US-1001", "title": "Bad", "description": "Desc"}
            log_rejection(story, "missing_field", output_file=output_file)

            with open(output_file, encoding="utf-8") as fh:
                data = json.load(fh)
            rejection = data["rejections"][0]
            assert "timestamp" in rejection
            assert isinstance(rejection["timestamp"], int)
            assert rejection["timestamp"] > 0

    def test_rejection_entry_format(self) -> None:
        """Rejection entry has correct fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "_rejected_stories.json")
            story = {
                "id": "US-1002",
                "title": "Test Story",
                "description": "Test Description",
            }
            log_rejection(story, "antipattern: test_pattern", output_file=output_file)

            with open(output_file, encoding="utf-8") as fh:
                data = json.load(fh)
            rejection = data["rejections"][0]
            assert rejection["story_id"] == "US-1002"
            assert rejection["title"] == "Test Story"
            assert rejection["rule_violated"] == "antipattern"
            assert rejection["reason"] == "antipattern: test_pattern"
            assert rejection["phase"] == "S"
