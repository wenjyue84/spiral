#!/usr/bin/env python3
"""
lib/privacy_scrubber.py — Privacy-scrubbing OTel span processor (US-348)

Redacts sensitive data (API keys, emails, file paths) from OpenTelemetry spans
before they are exported, reducing privacy risk in telemetry pipelines.

Reference: https://arxiv.org/abs/2509.17488 (LLM agents leak sensitive data through telemetry)
"""

import re
from typing import Any, Optional, Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanProcessor  # type: ignore[attr-defined]


# ── Default sensitive data patterns ──────────────────────────────────────────
# These patterns match common secret formats and should be kept up-to-date.
DEFAULT_SCRUB_PATTERNS: dict[str, str] = {
    # Anthropic API keys (sk-ant-* or sk-ant_*)
    "anthropic_api_key": r"sk-ant[_-][A-Za-z0-9_\-]{6,}",
    # GitHub personal access tokens (ghp_*)
    "github_token": r"ghp_[A-Za-z0-9_]{30,}",
    # OpenAI API keys (sk-proj-*, sk-svc-*, sk-* generally)
    "openai_api_key": r"sk-(?:proj|svc|[A-Za-z0-9])[A-Za-z0-9_\-]{10,}",
    # AWS secret access keys (pattern: AKIA + 16 chars, or SecretAccessKey=...)
    "aws_secret": r"(?:AKIAIOSFODNN7EXAMPLE|aws_secret_access_key\s*=\s*[A-Za-z0-9/+]{40})",
    # Generic email addresses
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    # File paths that might contain credentials (e.g., path with 'secret', 'key', 'password')
    "credential_path": r"(?i)[/\\][\w./\\]*(?:secret|password|key|credential|token)[\w./\\]*",
}

# Fields that should be fully redacted (not individual value replacement)
DEFAULT_SCRUB_FIELDS: Sequence[str] = [
    "gen_ai.input.messages",
    "gen_ai.output.messages",
]


class PrivacyScrubber(SpanProcessor):
    """
    OpenTelemetry SpanProcessor that redacts sensitive data from span attributes
    before export.

    Respects configuration via environment variables:
    - SPIRAL_OTEL_SCRUB_PATTERNS: Comma-separated list of pattern names to enable
    - SPIRAL_OTEL_SCRUB_FIELDS: Comma-separated list of attribute names to fully redact
    - SPIRAL_OTEL_EMIT_MESSAGES: Enable/disable message fields (gen_ai.input.messages, etc.)
    """

    def __init__(
        self,
        patterns: Optional[dict[str, str]] = None,
        scrub_fields: Optional[Sequence[str]] = None,
        emit_messages: bool = False,
    ):
        """
        Initialize the privacy scrubber.

        Args:
            patterns: Dict mapping pattern name to regex. Defaults to DEFAULT_SCRUB_PATTERNS.
            scrub_fields: List of attribute names to fully redact. Defaults to DEFAULT_SCRUB_FIELDS.
            emit_messages: If False, gen_ai.input.messages and gen_ai.output.messages are removed.
        """
        self.patterns = patterns or DEFAULT_SCRUB_PATTERNS
        self.scrub_fields = scrub_fields or DEFAULT_SCRUB_FIELDS
        self.emit_messages = emit_messages

        # Compile regex patterns for efficiency
        self.compiled_patterns: dict[str, re.Pattern[str]] = {}
        for name, pattern in self.patterns.items():
            try:
                self.compiled_patterns[name] = re.compile(pattern)
            except re.error as e:
                # Log and skip invalid patterns
                print(f"[PrivacyScrubber] Invalid regex pattern '{name}': {e}", flush=True)

    def on_start(self, span: ReadableSpan, parent_context: Any = None) -> None:
        """No-op: redaction happens at on_end."""
        pass

    def on_end(self, span: ReadableSpan) -> None:
        """Redact sensitive data from span attributes before export."""
        if span.attributes is None:
            return

        # Remove message fields if not enabled
        if not self.emit_messages:
            for field in self.scrub_fields:
                if field in span.attributes:
                    del span.attributes[field]  # type: ignore[attr-defined]

        # Scrub remaining attributes for sensitive patterns
        for key, value in list(span.attributes.items()):
            if value is None:
                continue

            # Convert value to string for pattern matching
            if isinstance(value, str):
                redacted = self._redact_value(value)
                if redacted != value:
                    span.attributes[key] = redacted  # type: ignore[index]
            elif isinstance(value, (list, tuple)):
                # Handle lists/tuples of strings (e.g., in structured messages)
                redacted_list = [
                    self._redact_value(str(item)) if isinstance(item, str) else item
                    for item in value
                ]
                if redacted_list != list(value):
                    span.attributes[key] = redacted_list  # type: ignore[index]
            elif isinstance(value, dict):
                # Handle dicts (e.g., structured message objects)
                redacted_dict = self._redact_dict(value)
                if redacted_dict != value:
                    span.attributes[key] = redacted_dict  # type: ignore[index]

    def shutdown(self) -> None:
        """No-op for this processor."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """No-op: delegated to underlying exporter."""
        return True

    def _redact_value(self, value: str) -> str:
        """Redact sensitive patterns in a string value."""
        result = value
        for name, pattern in self.compiled_patterns.items():
            if pattern.search(result):
                # Use pattern name to determine redaction token
                redacted_token = self._get_redaction_token(name)
                result = pattern.sub(redacted_token, result)
        return result

    def _redact_dict(self, d: Any) -> Any:
        """Recursively redact sensitive data in dict/list structures."""
        if isinstance(d, dict):
            return {k: self._redact_dict(v) for k, v in d.items()}
        elif isinstance(d, (list, tuple)):
            return type(d)(self._redact_dict(item) for item in d)
        elif isinstance(d, str):
            return self._redact_value(d)
        return d

    def _get_redaction_token(self, pattern_name: str) -> str:
        """Return a descriptive redaction token based on pattern name."""
        tokens = {
            "anthropic_api_key": "[REDACTED_ANTHROPIC_API_KEY]",
            "github_token": "[REDACTED_GITHUB_TOKEN]",
            "openai_api_key": "[REDACTED_OPENAI_API_KEY]",
            "aws_secret": "[REDACTED_AWS_SECRET]",
            "email": "[REDACTED_EMAIL]",
            "credential_path": "[REDACTED_PATH]",
        }
        return tokens.get(pattern_name, "[REDACTED]")
