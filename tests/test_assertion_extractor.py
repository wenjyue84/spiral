"""
Tests for lib/assertion_extractor.py — US-1413: Auto-Extract Verifiable Assertions from AC

Tests the extraction and generation of verifiable assertions from natural language AC patterns.
Run with: pytest tests/test_assertion_extractor.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from assertion_extractor import (
    Assertion,
    extract_assertions,
    generate_pytest_assertions,
)


class TestExtractAssertPattern:
    """Tests for _extract_assert_pattern()."""

    def test_extract_assert_with_is(self) -> None:
        """Extract 'assert X is Y' pattern."""
        ac = "assert response is valid"
        assertions = extract_assertions([ac])
        assert len(assertions) == 1
        assert assertions[0].type == "assert"
        assert assertions[0].subject == "response"
        assert assertions[0].expected_value == "valid"
        assert assertions[0].confidence_score == 0.95

    def test_extract_assert_bare(self) -> None:
        """Extract bare 'assert X' without explicit value."""
        ac = "assert result"
        assertions = extract_assertions([ac])
        assert len(assertions) == 1
        assert assertions[0].type == "assert"
        assert assertions[0].subject == "result"
        assert assertions[0].expected_value == "true"
        assert assertions[0].confidence_score == 0.85


class TestExtractMustHavePattern:
    """Tests for _extract_must_have_pattern()."""

    def test_extract_must_have(self) -> None:
        """Extract 'must have X' pattern."""
        ac = "must have error message"
        assertions = extract_assertions([ac])
        assert len(assertions) == 1
        assert assertions[0].type == "have"
        assert assertions[0].subject == "error message"
        assert assertions[0].expected_value == "present"
        assert assertions[0].confidence_score == 0.90

    def test_extract_must_have_with_field_keyword(self) -> None:
        """Extract 'must have X field' pattern."""
        ac = "must have user_id field"
        assertions = extract_assertions([ac])
        assert len(assertions) == 1
        assert assertions[0].type == "have"
        assert "user_id" in assertions[0].subject


class TestExtractShouldReturnPattern:
    """Tests for _extract_should_return_pattern()."""

    def test_extract_should_return(self) -> None:
        """Extract 'should return X' pattern."""
        ac = "should return status code 200"
        assertions = extract_assertions([ac])
        assert len(assertions) == 1
        assert assertions[0].type == "return"
        assert assertions[0].expected_value == "status code 200"
        assert assertions[0].confidence_score == 0.90

    def test_extract_should_return_object(self) -> None:
        """Extract 'should return X object' pattern."""
        ac = "should return user object"
        assertions = extract_assertions([ac])
        assert len(assertions) == 1
        assert assertions[0].type == "return"
        assert "user" in assertions[0].expected_value


class TestExtractContainsPattern:
    """Tests for _extract_contains_pattern()."""

    def test_extract_contains(self) -> None:
        """Extract 'contains X' pattern."""
        ac = "output contains error message"
        assertions = extract_assertions([ac])
        assert len(assertions) == 1
        assert assertions[0].type == "contains"
        assert assertions[0].subject == "output"
        assert assertions[0].expected_value == "error message"
        assert assertions[0].confidence_score == 0.85

    def test_extract_contains_without_prefix(self) -> None:
        """Extract bare 'contains X' pattern."""
        ac = "contains timestamp"
        assertions = extract_assertions([ac])
        assert len(assertions) == 1
        assert assertions[0].type == "contains"
        assert assertions[0].expected_value == "timestamp"


class TestExtractMultipleAssertions:
    """Tests for extraction of multiple assertions from a single AC list."""

    def test_extract_mixed_patterns(self) -> None:
        """Extract multiple different assertion patterns."""
        ac_list = [
            "assert response is valid",
            "must have user_id field",
            "should return status code 200",
            "output contains success",
        ]
        assertions = extract_assertions(ac_list)
        assert len(assertions) == 4
        types = {a.type for a in assertions}
        assert types == {"assert", "have", "return", "contains"}

    def test_extract_ignores_unparseable_ac(self) -> None:
        """Ignore AC text that doesn't match any pattern."""
        ac_list = [
            "assert status is 200",
            "The system should be user-friendly",
            "must have API key",
        ]
        assertions = extract_assertions(ac_list)
        # Should extract 2 (assert and must have), skip the vague one
        assert len(assertions) == 2

    def test_extract_empty_list(self) -> None:
        """Handle empty AC list."""
        assertions = extract_assertions([])
        assert len(assertions) == 0

    def test_extract_blank_items(self) -> None:
        """Ignore blank/whitespace-only AC items."""
        ac_list = [
            "assert result is true",
            "",
            "   ",
            "must have field",
        ]
        assertions = extract_assertions(ac_list)
        assert len(assertions) == 2


class TestConfidenceScoring:
    """Tests for confidence score assignment."""

    def test_assert_with_value_higher_confidence(self) -> None:
        """Assert with explicit expected value has higher confidence."""
        ac1 = "assert response is valid"
        ac2 = "assert response"

        assertions1 = extract_assertions([ac1])
        assertions2 = extract_assertions([ac2])

        assert assertions1[0].confidence_score > assertions2[0].confidence_score

    def test_confidence_scores_are_normalized(self) -> None:
        """Confidence scores are between 0 and 1."""
        ac_list = [
            "assert status is 200",
            "must have error_message",
            "should return user",
            "contains timestamp",
        ]
        assertions = extract_assertions(ac_list)

        for assertion in assertions:
            assert 0.0 <= assertion.confidence_score <= 1.0


class TestGeneratePytestAssertions:
    """Tests for pytest code generation."""

    def test_generate_pytest_basic(self) -> None:
        """Generate pytest code from simple assertions."""
        story = {
            "id": "US-1413",
            "title": "Phase V: Auto-Extract Assertions",
        }
        ac_list = [
            "assert response is valid",
            "must have status_code",
        ]
        assertions = extract_assertions(ac_list)

        code = generate_pytest_assertions(story, assertions)

        # Verify code structure
        assert "import pytest" in code
        assert "@pytest.mark.us_1413" in code
        assert "class TestUS_1413:" in code
        assert "def test_assert_" in code
        assert "def test_have_" in code

    def test_generate_pytest_has_docstring(self) -> None:
        """Generated code includes module and test docstrings."""
        story = {"id": "US-TEST", "title": "Test Story"}
        assertions = extract_assertions(["assert value is true"])

        code = generate_pytest_assertions(story, assertions)

        assert '"""' in code
        assert "Auto-generated assertions" in code
        assert "US-TEST" in code

    def test_generate_pytest_all_assertion_types(self) -> None:
        """Generate code covering all assertion types."""
        story = {"id": "US-FULL", "title": "Full Test"}
        ac_list = [
            "assert status is 200",
            "must have user_id",
            "should return result",
            "output contains success",
        ]
        assertions = extract_assertions(ac_list)

        code = generate_pytest_assertions(story, assertions)

        # Verify each assertion type is represented
        assert "def test_assert_" in code
        assert "def test_have_" in code
        assert "def test_return_" in code
        assert "def test_contains_" in code


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_case_insensitive_patterns(self) -> None:
        """Pattern matching should be case-insensitive."""
        ac_list = [
            "ASSERT response is valid",
            "Must Have user_id",
            "SHOULD return status",
            "OUTPUT Contains error",
        ]
        assertions = extract_assertions(ac_list)
        assert len(assertions) == 4

    def test_punctuation_handling(self) -> None:
        """Handle AC text with various punctuation."""
        ac_list = [
            "assert response is valid.",
            "must have user_id;",
            "should return status code 200,",
        ]
        assertions = extract_assertions(ac_list)
        assert len(assertions) == 3
        # Verify punctuation doesn't break extraction
        assert all(a.subject for a in assertions)

    def test_multiword_subjects(self) -> None:
        """Extract subjects with multiple words."""
        ac = "assert HTTP response code is 200"
        assertions = extract_assertions([ac])
        assert len(assertions) == 1
        assert "HTTP" in assertions[0].subject or "response" in assertions[0].subject

    def test_assertion_raw_ac_preserved(self) -> None:
        """Raw AC text is preserved in assertion."""
        original_ac = "assert some_variable is true"
        assertions = extract_assertions([original_ac])
        assert assertions[0].raw_ac == original_ac


class TestIntegrationExtractAndGenerate:
    """Integration tests for extraction and generation pipeline."""

    def test_extract_then_generate_workflow(self) -> None:
        """End-to-end workflow: extract from AC, then generate pytest."""
        story = {
            "id": "US-1413",
            "title": "Phase V: Auto-Extract Verifiable Assertions",
            "acceptanceCriteria": [
                "assert response is valid",
                "must have story_id field",
                "should return JSON object",
                "output contains timestamp",
            ],
        }

        # Extract assertions from AC
        ac_list = story.get("acceptanceCriteria", [])
        assertions = extract_assertions(ac_list)

        # Generate pytest code
        pytest_code = generate_pytest_assertions(story, assertions)

        # Verify generated code is valid Python (syntactically)
        assert "import pytest" in pytest_code
        assert "class Test" in pytest_code
        assert "def test_" in pytest_code
        assert len(assertions) == 4

    def test_story_without_ac(self) -> None:
        """Handle story with no acceptance criteria."""
        story = {
            "id": "US-EMPTY",
            "title": "Story with no AC",
        }
        assertions = extract_assertions(story.get("acceptanceCriteria", []))
        assert len(assertions) == 0

        pytest_code = generate_pytest_assertions(story, assertions)
        # Should still generate valid Python structure
        assert "@pytest.mark" in pytest_code
        assert "class Test" in pytest_code
