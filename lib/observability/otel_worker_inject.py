#!/usr/bin/env python3
"""
lib/otel_worker_inject.py — OTel subprocess span instrumentation for ralph workers (US-377)

Emits ralph_worker spans with proper TRACEPARENT context injection and subprocess attributes.
Spans are created as children of the parent phase context, with semantic convention attributes
for subprocess tracking.

Usage:
  # After worker subprocess completes
  TRACEPARENT="$TRACEPARENT" "$SPIRAL_PYTHON" lib/otel_worker_inject.py emit-worker \
    --story-id "US-123" \
    --worker-num 1 \
    --subprocess-command "bash /path/to/ralph.sh 10 --prd prd.json" \
    --subprocess-pid 12345 \
    --subprocess-returncode 0 \
    2>/dev/null || true
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
from typing import Optional, cast

# ── Subprocess semantic convention attributes ──────────────────────────────────
_SUBPROCESS_COMMAND = "subprocess.command"
_SUBPROCESS_PID = "subprocess.pid"
_SUBPROCESS_RETURNCODE = "subprocess.returncode"
_SUBPROCESS_EXECUTABLE = "subprocess.executable"

# ── GenAI semantic convention attributes ───────────────────────────────────────
_GEN_AI_AGENT_NAME = "gen_ai.agent.name"
_GEN_AI_SYSTEM = "gen_ai.system"


def _now_ns() -> int:
    """Current time in nanoseconds (OTel timestamps are ns)."""
    return time.time_ns()


def _build_traceparent(trace_id: str, span_id: str) -> str:
    """Format W3C traceparent: 00-<trace_id>-<span_id>-01"""
    return f"00-{trace_id}-{span_id}-01"


def _parse_traceparent(tp: str) -> tuple[str, str]:
    """Parse W3C traceparent, return (trace_id, span_id)."""
    parts = tp.split("-")
    if len(parts) < 4:
        raise ValueError(f"Invalid TRACEPARENT: {tp!r}")
    return parts[1], parts[2]


def _otlp_endpoint() -> Optional[str]:
    """Return OTLP HTTP endpoint or None if unset."""
    ep = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    return ep if ep else None


def _create_privacy_scrubber(emit_messages: bool = False) -> object:
    """
    Create a PrivacyScrubber span processor with configuration from environment.
    """
    try:
        from lib.security.privacy_scrubber import DEFAULT_SCRUB_FIELDS, DEFAULT_SCRUB_PATTERNS, PrivacyScrubber

        patterns = DEFAULT_SCRUB_PATTERNS.copy()
        scrub_fields = list(DEFAULT_SCRUB_FIELDS)

        # Allow customization via env vars
        custom_patterns_str = os.environ.get("SPIRAL_OTEL_SCRUB_PATTERNS", "").strip()
        if custom_patterns_str:
            enabled_names = {p.strip() for p in custom_patterns_str.split(",")}
            patterns = {k: v for k, v in patterns.items() if k in enabled_names}

        custom_fields_str = os.environ.get("SPIRAL_OTEL_SCRUB_FIELDS", "").strip()
        if custom_fields_str:
            scrub_fields = [f.strip() for f in custom_fields_str.split(",")]

        return PrivacyScrubber(patterns=patterns, scrub_fields=scrub_fields, emit_messages=emit_messages)
    except Exception:
        return None


def _emit_completed_span(
    *,
    name: str,
    trace_id_hex: str,
    parent_span_id_hex: Optional[str],
    span_id_hex: str,
    start_time_ns: int,
    end_time_ns: int,
    attributes: dict[str, object],
    is_root: bool = False,
    span_kind_override: Optional[str] = None,
    status_code: Optional[str] = None,
) -> None:
    """
    Create and export a single completed OTel span.

    Uses the NonRecordingSpan context trick to set parent_span_id without
    requiring the parent span to be alive in this process.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.trace import SpanContext, SpanKind, Status, StatusCode, TraceFlags

    resource = Resource.create({SERVICE_NAME: "spiral"})
    provider = TracerProvider(resource=resource)

    endpoint = _otlp_endpoint()
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        # Apply privacy scrubbing before export (US-348)
        emit_messages = os.environ.get("SPIRAL_OTEL_EMIT_MESSAGES", "").lower() in ("true", "1", "yes")
        try:
            from opentelemetry.sdk.trace import SpanProcessor as _SpanProcessor

            scrubber = _create_privacy_scrubber(emit_messages=emit_messages)
            provider.add_span_processor(cast(_SpanProcessor, scrubber))
        except Exception:
            pass

        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(SimpleSpanProcessor(exporter))

    # Build trace and span IDs as integers (OTel SDK expects int)
    trace_id_int = int(trace_id_hex, 16)
    int(span_id_hex, 16)

    # If we have a parent, set the parent context
    if parent_span_id_hex:
        parent_span_id_int = int(parent_span_id_hex, 16)
        parent_ctx = SpanContext(
            trace_id=trace_id_int,
            span_id=parent_span_id_int,
            is_remote=True,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )
        parent_span = trace.NonRecordingSpan(parent_ctx)
        ctx = trace.set_span_in_context(parent_span)
    else:
        ctx = None

    tracer = provider.get_tracer("spiral")

    # Determine span kind (default INTERNAL; CLIENT for subprocess)
    kind_map = {"CLIENT": SpanKind.CLIENT, "INTERNAL": SpanKind.INTERNAL}
    kind = kind_map.get(span_kind_override or "", SpanKind.INTERNAL)

    # Start span
    if ctx:
        span = tracer.start_span(
            name,
            context=ctx,
            kind=kind,
            start_time=start_time_ns,
        )
    else:
        span = tracer.start_span(
            name,
            kind=kind,
            start_time=start_time_ns,
        )

    # Set attributes
    for k, v in attributes.items():
        # Type ignore for object -> SpanAttributeValue union
        span.set_attribute(k, v)  # type: ignore[arg-type]

    # Set status if provided (ERROR or OK)
    if status_code:
        if status_code == "ERROR":
            span.set_status(Status(StatusCode.ERROR))
        elif status_code == "OK":
            span.set_status(Status(StatusCode.OK))

    # End the span with the historical timestamp
    span.end(end_time=end_time_ns)

    # Force flush so the exporter actually sends before process exits
    provider.force_flush(timeout_millis=5000)


def cmd_emit_worker(args: argparse.Namespace) -> None:
    """
    Emit a ralph_worker span with subprocess attributes.

    Span is linked to the parent phase context via TRACEPARENT env var.
    Attributes include subprocess.command, subprocess.pid, subprocess.returncode,
    story_id, and worker_num.

    Status is set to ERROR when returncode != 0.
    """
    if not _otlp_endpoint():
        return

    # Parse parent context from TRACEPARENT
    traceparent = os.environ.get("TRACEPARENT", "")
    if not traceparent:
        return

    try:
        trace_id, parent_span_id = _parse_traceparent(traceparent)
    except ValueError:
        return

    story_id = args.story_id
    worker_num = args.worker_num
    subprocess_command = args.subprocess_command
    subprocess_pid = int(args.subprocess_pid)
    subprocess_returncode = int(args.subprocess_returncode)

    # Generate span ID
    span_id = secrets.token_hex(8)

    # Duration: use current time as end, assume subprocess took ~1s (historical span)
    end_ns = _now_ns()
    duration_s = 1.0  # Subprocess timing will be captured by worker heartbeat
    start_ns = end_ns - int(duration_s * 1_000_000_000)

    # Extract executable from command (first token)
    executable = subprocess_command.split()[0] if subprocess_command else ""

    # Build attributes
    attributes: dict[str, object] = {
        _GEN_AI_AGENT_NAME: "spiral",
        _GEN_AI_SYSTEM: "anthropic",
        _SUBPROCESS_COMMAND: subprocess_command,
        _SUBPROCESS_PID: subprocess_pid,
        _SUBPROCESS_RETURNCODE: subprocess_returncode,
        "spiral.story_id": story_id,
        "spiral.worker_num": worker_num,
    }
    if executable:
        attributes[_SUBPROCESS_EXECUTABLE] = executable

    # Determine span status: ERROR if returncode != 0
    status_code = "ERROR" if subprocess_returncode != 0 else "OK"

    _emit_completed_span(
        name=f"ralph_worker {story_id}",
        trace_id_hex=trace_id,
        parent_span_id_hex=parent_span_id,
        span_id_hex=span_id,
        start_time_ns=start_ns,
        end_time_ns=end_ns,
        attributes=attributes,
        span_kind_override="INTERNAL",
        status_code=status_code,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OTel subprocess span instrumentation for SPIRAL workers (US-377)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # emit-worker
    p_worker = sub.add_parser("emit-worker", help="Emit a ralph_worker span with subprocess attributes")
    p_worker.add_argument("--story-id", required=True, help="Story ID (e.g., US-123)")
    p_worker.add_argument("--worker-num", type=int, required=True, help="Worker number (e.g., 1)")
    p_worker.add_argument("--subprocess-command", required=True, help="Full subprocess command string")
    p_worker.add_argument("--subprocess-pid", type=int, required=True, help="Subprocess PID")
    p_worker.add_argument("--subprocess-returncode", type=int, required=True, help="Subprocess exit code")

    args = parser.parse_args()

    try:
        if args.command == "emit-worker":
            cmd_emit_worker(args)
    except Exception:  # pylint: disable=broad-except
        import traceback

        print("[otel_worker_inject] ERROR:", traceback.format_exc(), file=sys.stderr)


if __name__ == "__main__":
    main()
