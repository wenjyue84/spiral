#!/usr/bin/env python3
"""
tests/test_privacy_scrubber.py — Tests for privacy-scrubbing OTel span processor (US-348)

Tests redaction of sensitive data (API keys, emails, file paths) from span attributes
before telemetry export.
"""

import os
import sys
from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.privacy_scrubber import (
    PrivacyScrubber,
)


class TestPrivacyScrubberPatterns:
    """Test pattern-based redaction of sensitive data."""

    def test_redact_anthropic_api_key(self) -> None:
        """Redact Anthropic API keys (sk-ant-*)."""
        scrubber = PrivacyScrubber()
        value = "Authorization: sk-ant-api03-5z6m7n8o9p0q1r2s3t4u5v6w7x8y9z0"
        redacted = scrubber._redact_value(value)
        assert "[REDACTED_ANTHROPIC_API_KEY]" in redacted
        assert "sk-ant-" not in redacted

    def test_redact_github_token(self) -> None:
        """Redact GitHub personal access tokens (ghp_*)."""
        scrubber = PrivacyScrubber()
        value = "token: ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        redacted = scrubber._redact_value(value)
        assert "[REDACTED_GITHUB_TOKEN]" in redacted
        assert "ghp_" not in redacted

    def test_redact_openai_api_key(self) -> None:
        """Redact OpenAI API keys (sk-*)."""
        scrubber = PrivacyScrubber()
        value = "sk-proj-1234567890abcdefghijklmnopqrstuvwxyz"
        redacted = scrubber._redact_value(value)
        assert "[REDACTED_OPENAI_API_KEY]" in redacted
        assert "sk-" not in redacted

    def test_redact_email_address(self) -> None:
        """Redact email addresses."""
        scrubber = PrivacyScrubber()
        value = "Contact: alice@example.com for details"
        redacted = scrubber._redact_value(value)
        assert "[REDACTED_EMAIL]" in redacted
        assert "@" not in redacted

    def test_redact_multiple_patterns(self) -> None:
        """Redact multiple sensitive patterns in one string."""
        scrubber = PrivacyScrubber()
        value = "API key: sk-ant-abc123 and email: test@domain.com"
        redacted = scrubber._redact_value(value)
        assert "[REDACTED_ANTHROPIC_API_KEY]" in redacted
        assert "[REDACTED_EMAIL]" in redacted
        assert "sk-ant-" not in redacted
        assert "@" not in redacted

    def test_redact_credential_path(self) -> None:
        """Redact file paths containing credential keywords."""
        scrubber = PrivacyScrubber()
        value = "Loading config from /home/user/.ssh/secret_key"
        redacted = scrubber._redact_value(value)
        assert "[REDACTED_PATH]" in redacted

    def test_no_redaction_safe_text(self) -> None:
        """Do not redact safe text without sensitive patterns."""
        scrubber = PrivacyScrubber()
        value = "This is a safe message with no secrets"
        redacted = scrubber._redact_value(value)
        assert redacted == value


class TestPrivacyScrubberStructures:
    """Test redaction in complex data structures."""

    def test_redact_dict_values(self) -> None:
        """Redact sensitive values in dict structures."""
        scrubber = PrivacyScrubber()
        data = {
            "name": "alice",
            "email": "alice@example.com",
            "api_key": "sk-ant-xyz123",
        }
        redacted = scrubber._redact_dict(data)
        assert "[REDACTED_EMAIL]" in str(redacted["email"])
        assert "[REDACTED_ANTHROPIC_API_KEY]" in str(redacted["api_key"])
        assert redacted["name"] == "alice"

    def test_redact_list_items(self) -> None:
        """Redact sensitive values in lists."""
        scrubber = PrivacyScrubber()
        data = [
            "alice@example.com",
            "safe text",
            "sk-ant-secret123",
        ]
        redacted = scrubber._redact_dict(data)
        assert "[REDACTED_EMAIL]" in str(redacted[0])
        assert redacted[1] == "safe text"
        assert "[REDACTED_ANTHROPIC_API_KEY]" in str(redacted[2])

    def test_redact_nested_structures(self) -> None:
        """Redact sensitive data in nested dict/list structures."""
        scrubber = PrivacyScrubber()
        data = {
            "messages": [
                {"role": "user", "content": "My email is alice@example.com"},
                {"role": "assistant", "content": "Got it"},
            ]
        }
        redacted = scrubber._redact_dict(data)
        msg_content = str(redacted["messages"][0]["content"])
        assert "[REDACTED_EMAIL]" in msg_content


class TestPrivacyScrubberSpanProcessor:
    """Test OTel span processor integration."""

    def test_on_end_redacts_string_attribute(self) -> None:
        """on_end() redacts string attributes on spans."""
        scrubber = PrivacyScrubber()
        span = MagicMock()
        span.attributes = {
            "gen_ai.operation.name": "query",
            "user_context": "API: sk-ant-secret123",
        }

        scrubber.on_end(span)

        assert "[REDACTED_ANTHROPIC_API_KEY]" in span.attributes["user_context"]

    def test_on_end_removes_message_fields_by_default(self) -> None:
        """on_end() removes message fields by default (emit_messages=false)."""
        scrubber = PrivacyScrubber(emit_messages=False)
        span = MagicMock()
        span.attributes = {
            "gen_ai.input.messages": "user prompt",
            "gen_ai.output.messages": "assistant response",
            "other_field": "keep this",
        }

        scrubber.on_end(span)

        assert "gen_ai.input.messages" not in span.attributes
        assert "gen_ai.output.messages" not in span.attributes
        assert "other_field" in span.attributes

    def test_on_end_keeps_message_fields_when_enabled(self) -> None:
        """on_end() keeps message fields when emit_messages=true."""
        scrubber = PrivacyScrubber(emit_messages=True)
        span = MagicMock()
        span.attributes = {
            "gen_ai.input.messages": "user prompt",
            "gen_ai.output.messages": "assistant response",
        }

        scrubber.on_end(span)

        # Fields should be present (but scrubbed if they contain sensitive data)
        assert "gen_ai.input.messages" in span.attributes
        assert "gen_ai.output.messages" in span.attributes

    def test_on_end_handles_none_attributes(self) -> None:
        """on_end() gracefully handles spans with no attributes."""
        scrubber = PrivacyScrubber()
        span = MagicMock()
        span.attributes = None

        # Should not raise an exception
        scrubber.on_end(span)

    def test_on_end_redacts_list_attributes(self) -> None:
        """on_end() redacts sensitive data in list attributes."""
        scrubber = PrivacyScrubber()
        span = MagicMock()
        span.attributes = {
            "items": [
                "alice@example.com",
                "safe text",
                "sk-ant-secret123",
            ]
        }

        scrubber.on_end(span)

        items = span.attributes["items"]
        assert "[REDACTED_EMAIL]" in str(items[0])
        assert items[1] == "safe text"
        assert "[REDACTED_ANTHROPIC_API_KEY]" in str(items[2])

    def test_on_end_redacts_dict_attributes(self) -> None:
        """on_end() redacts sensitive data in dict attributes."""
        scrubber = PrivacyScrubber()
        span = MagicMock()
        span.attributes = {
            "context": {
                "user_email": "alice@example.com",
                "safe": "value",
            }
        }

        scrubber.on_end(span)

        context = span.attributes["context"]
        assert "[REDACTED_EMAIL]" in str(context["user_email"])
        assert context["safe"] == "value"


class TestPrivacyScrubberConfiguration:
    """Test configuration of redaction patterns."""

    def test_custom_patterns(self) -> None:
        """Use custom patterns instead of defaults."""
        custom_patterns = {
            "test_pattern": r"TEST-\d{3}",
        }
        scrubber = PrivacyScrubber(patterns=custom_patterns)
        value = "Code: TEST-123 found"
        redacted = scrubber._redact_value(value)
        assert "[REDACTED]" in redacted
        assert "TEST-123" not in redacted

    def test_custom_scrub_fields(self) -> None:
        """Use custom field list for full redaction."""
        custom_fields = ["custom_field"]
        scrubber = PrivacyScrubber(scrub_fields=custom_fields)
        span = MagicMock()
        span.attributes = {
            "custom_field": "will be removed",
            "gen_ai.input.messages": "will be kept",  # not in scrub_fields
        }

        scrubber.on_end(span)

        assert "custom_field" not in span.attributes
        assert "gen_ai.input.messages" in span.attributes

    def test_invalid_regex_pattern_skipped(self, capsys: object) -> None:
        """Invalid regex patterns are skipped with a warning."""
        invalid_patterns = {
            "bad_pattern": r"[invalid(",  # Invalid regex
            "good_pattern": r"test",
        }
        scrubber = PrivacyScrubber(patterns=invalid_patterns)

        # Should have one valid compiled pattern
        assert len(scrubber.compiled_patterns) == 1
        assert "good_pattern" in scrubber.compiled_patterns
        assert "bad_pattern" not in scrubber.compiled_patterns


class TestPrivacyScrubberPropertyBased:
    """Property-based tests using Hypothesis."""

    @given(st.text())
    def test_redaction_is_idempotent(self, text: str) -> None:
        """Redacting twice gives the same result as redacting once."""
        scrubber = PrivacyScrubber()
        redacted_once = scrubber._redact_value(text)
        redacted_twice = scrubber._redact_value(redacted_once)
        assert redacted_once == redacted_twice

    @given(st.text())
    def test_no_unsafe_patterns_in_redacted(self, text: str) -> None:
        """Redacted output does not contain original API key patterns."""
        scrubber = PrivacyScrubber()
        redacted = scrubber._redact_value(text)
        # Check that known unsafe patterns don't appear (if they were in input)
        if "sk-ant-" in text:
            assert "sk-ant-" not in redacted
        if "ghp_" in text:
            assert "ghp_" not in redacted

    @given(
        st.dictionaries(
            st.text(min_size=1),
            st.one_of(st.text(), st.integers(), st.booleans()),
        )
    )
    def test_redact_dict_preserves_structure(self, data: dict[str, object]) -> None:
        """Redacting a dict preserves its structure (keys and types)."""
        scrubber = PrivacyScrubber()
        redacted = scrubber._redact_dict(data)
        assert set(redacted.keys()) == set(data.keys())

    @given(st.lists(st.text()))
    def test_redact_list_preserves_length(self, data: list[str]) -> None:
        """Redacting a list preserves its length."""
        scrubber = PrivacyScrubber()
        redacted = scrubber._redact_dict(data)
        assert len(redacted) == len(data)


class TestPrivacyScrubberAcceptanceCriteria:
    """Tests validating the acceptance criteria from US-348."""

    def test_criterion_api_key_redaction(self) -> None:
        """Criterion: sk-ant-* keys are replaced with [REDACTED_API_KEY]."""
        scrubber = PrivacyScrubber()
        prompt = "Bearer sk-ant-api03-5z6m7n8o9p0q1r2s3t4u5v6w7x8y9z0"
        redacted = scrubber._redact_value(prompt)
        assert "[REDACTED_ANTHROPIC_API_KEY]" in redacted
        assert "sk-ant-" not in redacted

    def test_criterion_emit_messages_disabled_by_default(self) -> None:
        """Criterion: gen_ai.input.messages and gen_ai.output.messages are disabled by default."""
        scrubber = PrivacyScrubber(emit_messages=False)
        span = MagicMock()
        span.attributes = {
            "gen_ai.input.messages": "test",
            "gen_ai.output.messages": "test",
        }
        scrubber.on_end(span)
        assert "gen_ai.input.messages" not in span.attributes
        assert "gen_ai.output.messages" not in span.attributes

    def test_criterion_emit_messages_opt_in(self) -> None:
        """Criterion: Enabling requires explicit opt-in."""
        scrubber = PrivacyScrubber(emit_messages=True)
        span = MagicMock()
        span.attributes = {
            "gen_ai.input.messages": "test",
            "gen_ai.output.messages": "test",
        }
        scrubber.on_end(span)
        assert "gen_ai.input.messages" in span.attributes
        assert "gen_ai.output.messages" in span.attributes

    def test_criterion_configurable_patterns(self) -> None:
        """Criterion: Scrubbing is configurable via patterns and fields."""
        custom_patterns = {"email": r"[a-z]+@[a-z]+\.[a-z]+"}
        custom_fields = ["sensitive_field"]
        scrubber = PrivacyScrubber(
            patterns=custom_patterns,
            scrub_fields=custom_fields,
        )
        span = MagicMock()
        span.attributes = {
            "sensitive_field": "will be removed",
            "email_in_text": "contact@domain.com",
        }
        scrubber.on_end(span)
        assert "sensitive_field" not in span.attributes
        assert "[REDACTED_EMAIL]" in str(span.attributes["email_in_text"])
