#!/usr/bin/env python3
"""
lib/otel_content_events.py — OTel GenAI content Events for SPIRAL (US-397)

Emits OpenTelemetry Events conforming to the GenAI semantic conventions:
  gen_ai.content.prompt    — Event with prompt body and attributes
  gen_ai.content.completion — Event with completion body and attributes

See: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-events/

Shell integration:
  # Before API call — emit prompt event
  "$SPIRAL_PYTHON" lib/otel_content_events.py emit-prompt \
      --system-prompt "$RALPH_SYSTEM_PROMPT" \
      --user-prompt "$RALPH_USER_PROMPT" \
      [--model "claude-opus-4-6"] 2>/dev/null || true

  # After API call — emit completion event
  "$SPIRAL_PYTHON" lib/otel_content_events.py emit-completion \
      --completion "$RESPONSE_TEXT" \
      [--model "claude-opus-4-6"] 2>/dev/null || true

Events are emitted as JSONL to $SPIRAL_SCRATCH_DIR/content_events.jsonl for audit trail.
OTEL export only happens when OTEL_EXPORTER_OTLP_ENDPOINT is set.

SPIRAL_OTEL_REDACT_CONTENT=true suppresses the actual prompt/completion bodies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# ── GenAI semantic convention attributes for content events ──────────────────
_GEN_AI_SYSTEM = "gen_ai.system"
_GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
_GEN_AI_PROMPT = "gen_ai.prompt"
_GEN_AI_COMPLETION = "gen_ai.completion"


def _otlp_endpoint() -> Optional[str]:
    """Return OTLP endpoint if configured, else None."""
    ep = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    return ep if ep else None


def _should_redact() -> bool:
    """Check if content redaction is enabled."""
    return os.environ.get("SPIRAL_OTEL_REDACT_CONTENT", "false").lower() == "true"


def _scratch_dir() -> str:
    """Get scratch directory for local audit trail."""
    return os.environ.get("SPIRAL_SCRATCH_DIR", ".spiral")


def _content_events_path() -> Path:
    """Path to local content events audit trail (JSONL)."""
    return Path(_scratch_dir()) / "content_events.jsonl"


def cmd_emit_prompt(args: argparse.Namespace) -> None:
    """
    Emit gen_ai.content.prompt Event.

    Records:
      - gen_ai.prompt (system + user combined, or redacted)
      - gen_ai.system: "anthropic"
      - gen_ai.request.model
      - timestamp
    """
    system_prompt: str = args.system_prompt or ""
    user_prompt: str = args.user_prompt or ""
    model: str = args.model or "unknown"
    redact: bool = _should_redact()

    # Combine prompts into one (OpenAI-like format for consistency)
    combined_prompt = ""
    if system_prompt:
        combined_prompt += f"[SYSTEM]\n{system_prompt}\n\n"
    if user_prompt:
        combined_prompt += f"[USER]\n{user_prompt}"
    combined_prompt = combined_prompt.strip()

    # Record to local audit trail JSONL
    Path(_scratch_dir()).mkdir(parents=True, exist_ok=True)
    event_record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event_type": "gen_ai.content.prompt",
        "model": model,
        "redacted": redact,
        "prompt_length_chars": len(combined_prompt),
        "system_prompt_length": len(system_prompt),
        "user_prompt_length": len(user_prompt),
    }
    if not redact:
        event_record["prompt"] = combined_prompt

    try:
        with open(_content_events_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(event_record) + "\n")
    except OSError as e:
        print(f"[otel_content_events] WARNING: failed to write prompt event: {e}", file=sys.stderr)

    # Emit to OTLP if configured
    endpoint = _otlp_endpoint()
    if not endpoint:
        return

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        resource = Resource.create({SERVICE_NAME: "spiral"})
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("spiral.genai", schema_url="https://opentelemetry.io/schemas/1.26.0")

        # Create a temporary span just to emit the event
        with tracer.start_as_current_span("gen_ai_content_prompt") as span:
            span.set_attribute(_GEN_AI_SYSTEM, "anthropic")
            span.set_attribute(_GEN_AI_REQUEST_MODEL, model)

            # Add the event with content attributes
            event_attrs = {
                _GEN_AI_SYSTEM: "anthropic",
                _GEN_AI_REQUEST_MODEL: model,
            }
            if not redact:
                event_attrs[_GEN_AI_PROMPT] = combined_prompt

            span.add_event("gen_ai.content.prompt", event_attrs)

        provider.force_flush(timeout_millis=5000)
    except Exception:  # pylint: disable=broad-except
        import traceback

        print("[otel_content_events] ERROR emitting prompt event:", traceback.format_exc(), file=sys.stderr)


def cmd_emit_completion(args: argparse.Namespace) -> None:
    """
    Emit gen_ai.content.completion Event.

    Records:
      - gen_ai.completion (response text, or redacted)
      - gen_ai.system: "anthropic"
      - gen_ai.request.model
      - timestamp
    """
    completion: str = args.completion or ""
    model: str = args.model or "unknown"
    redact: bool = _should_redact()

    # Record to local audit trail JSONL
    Path(_scratch_dir()).mkdir(parents=True, exist_ok=True)
    event_record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event_type": "gen_ai.content.completion",
        "model": model,
        "redacted": redact,
        "completion_length_chars": len(completion),
    }
    if not redact:
        event_record["completion"] = completion

    try:
        with open(_content_events_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(event_record) + "\n")
    except OSError as e:
        print(f"[otel_content_events] WARNING: failed to write completion event: {e}", file=sys.stderr)

    # Emit to OTLP if configured
    endpoint = _otlp_endpoint()
    if not endpoint:
        return

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        resource = Resource.create({SERVICE_NAME: "spiral"})
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("spiral.genai", schema_url="https://opentelemetry.io/schemas/1.26.0")

        # Create a temporary span just to emit the event
        with tracer.start_as_current_span("gen_ai_content_completion") as span:
            span.set_attribute(_GEN_AI_SYSTEM, "anthropic")
            span.set_attribute(_GEN_AI_REQUEST_MODEL, model)

            # Add the event with content attributes
            event_attrs = {
                _GEN_AI_SYSTEM: "anthropic",
                _GEN_AI_REQUEST_MODEL: model,
            }
            if not redact:
                event_attrs[_GEN_AI_COMPLETION] = completion

            span.add_event("gen_ai.content.completion", event_attrs)

        provider.force_flush(timeout_millis=5000)
    except Exception:  # pylint: disable=broad-except
        import traceback

        print("[otel_content_events] ERROR emitting completion event:", traceback.format_exc(), file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SPIRAL OTel GenAI content Events (US-397)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # emit-prompt
    p_prompt = sub.add_parser("emit-prompt", help="Emit gen_ai.content.prompt Event")
    p_prompt.add_argument("--system-prompt", default="", help="System prompt text")
    p_prompt.add_argument("--user-prompt", default="", help="User prompt text")
    p_prompt.add_argument("--model", default="unknown", help="Model name (e.g. claude-opus-4-6)")
    p_prompt.add_argument("--scratch-dir", default=None, help="Override SPIRAL_SCRATCH_DIR")

    # emit-completion
    p_comp = sub.add_parser("emit-completion", help="Emit gen_ai.content.completion Event")
    p_comp.add_argument("--completion", default="", help="Completion text")
    p_comp.add_argument("--model", default="unknown", help="Model name (e.g. claude-opus-4-6)")
    p_comp.add_argument("--scratch-dir", default=None, help="Override SPIRAL_SCRATCH_DIR")

    args = parser.parse_args()

    # If --scratch-dir is provided, override the env var for this invocation
    scratch_dir = getattr(args, "scratch_dir", None)
    if scratch_dir:
        os.environ["SPIRAL_SCRATCH_DIR"] = scratch_dir

    try:
        if args.command == "emit-prompt":
            cmd_emit_prompt(args)
        elif args.command == "emit-completion":
            cmd_emit_completion(args)
    except Exception:  # pylint: disable=broad-except
        import traceback

        print("[otel_content_events] ERROR:", traceback.format_exc(), file=sys.stderr)


if __name__ == "__main__":
    main()
