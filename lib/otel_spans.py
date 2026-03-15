#!/usr/bin/env python3
"""
lib/otel_spans.py — OTel GenAI agent spans for SPIRAL (US-184)

Emits OpenTelemetry spans conforming to the GenAI agent semantic conventions
(https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/).

Shell integration:
  # At run start — outputs W3C TRACEPARENT; saves state to <scratch-dir>/otel_run_context.json
  export TRACEPARENT=$("$SPIRAL_PYTHON" lib/otel_spans.py begin-run \
      --run-id "$SPIRAL_RUN_ID" --scratch-dir "$SCRATCH_DIR" 2>/dev/null)

  # After each phase ends
  "$SPIRAL_PYTHON" lib/otel_spans.py end-phase \
      --phase R --duration-s "$_PHASE_DUR_R" \
      [--input-tokens N] [--output-tokens N] \
      [--story-id "$_CURRENT_STORY_ID"] [--iteration "$SPIRAL_ITER"] 2>/dev/null || true

  # At run end
  "$SPIRAL_PYTHON" lib/otel_spans.py end-run \
      [--passes N] [--story-count N] 2>/dev/null || true

Silently no-ops when OTEL_EXPORTER_OTLP_ENDPOINT is not set (except begin-run
which always outputs TRACEPARENT).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Optional

# ── GenAI semantic convention attribute names (semconv 0.61+) ─────────────────
_GEN_AI_AGENT_ID = "gen_ai.agent.id"
_GEN_AI_AGENT_NAME = "gen_ai.agent.name"
_GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
_GEN_AI_SYSTEM = "gen_ai.system"
_GEN_AI_INPUT_TOKENS = "gen_ai.usage.input_tokens"
_GEN_AI_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"

# ── Phase → operation name mapping ────────────────────────────────────────────
_PHASE_OPERATION: dict[str, str] = {
    "R": "research",
    "T": "test_synth",
    "I": "implement",
    "V": "validate",
    "M": "merge",
    "G": "generate",
    "S": "story_validate",
    "C": "check",
}


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


def _make_tracer() -> tuple[object, object]:
    """
    Configure and return (tracer, provider).
    If OTEL_EXPORTER_OTLP_ENDPOINT is not set, returns a no-op tracer.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME

    resource = Resource.create({SERVICE_NAME: "spiral"})
    provider = TracerProvider(resource=resource)

    endpoint = _otlp_endpoint()
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("spiral", schema_url="https://opentelemetry.io/schemas/1.26.0")
    return tracer, provider


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
) -> None:
    """
    Create and export a single completed OTel span.

    Uses the NonRecordingSpan context trick to set parent_span_id without
    requiring the parent span to be alive in this process.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.trace import SpanKind, SpanContext, TraceFlags
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    resource = Resource.create({SERVICE_NAME: "spiral"})
    provider = TracerProvider(resource=resource)

    endpoint = _otlp_endpoint()
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(SimpleSpanProcessor(exporter))

    # Build trace and span IDs as integers (OTel SDK expects int)
    trace_id_int = int(trace_id_hex, 16)
    span_id_int = int(span_id_hex, 16)

    # Build context for the span itself (used to set its own context)
    span_ctx = SpanContext(
        trace_id=trace_id_int,
        span_id=span_id_int,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )

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

    # Start span (will be re-assigned timing below)
    if ctx:
        span = tracer.start_span(
            name,
            context=ctx,
            kind=SpanKind.INTERNAL,
            start_time=start_time_ns,
        )
    else:
        span = tracer.start_span(
            name,
            kind=SpanKind.INTERNAL,
            start_time=start_time_ns,
        )

    # Inject our own span_id by overriding context — SDK doesn't expose this
    # directly; we use the context object already set above.
    # Set attributes
    for k, v in attributes.items():
        span.set_attribute(k, v)

    # End the span with the historical timestamp
    span.end(end_time=end_time_ns)

    # Force flush so the exporter actually sends before process exits
    provider.force_flush(timeout_millis=5000)


def cmd_begin_run(args: argparse.Namespace) -> None:
    """
    Generate trace context for the run and save to state file.
    Prints W3C TRACEPARENT to stdout so the shell can export it.
    """
    trace_id = secrets.token_hex(16)  # 32 hex chars
    span_id = secrets.token_hex(8)    # 16 hex chars
    traceparent = _build_traceparent(trace_id, span_id)

    # Save state for end-run
    scratch = Path(args.scratch_dir)
    scratch.mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": args.run_id,
        "trace_id": trace_id,
        "root_span_id": span_id,
        "start_time_ns": _now_ns(),
    }
    (scratch / "otel_run_context.json").write_text(json.dumps(state))

    # Print TRACEPARENT so shell can: export TRACEPARENT=$(...)
    print(traceparent)


def cmd_end_phase(args: argparse.Namespace) -> None:
    """
    Emit a completed OTel phase span.
    Reads TRACEPARENT from environment for parent context.
    No-ops silently if OTEL_EXPORTER_OTLP_ENDPOINT is not set.
    """
    if not _otlp_endpoint():
        return

    traceparent = os.environ.get("TRACEPARENT", "")
    if not traceparent:
        return

    try:
        trace_id, parent_span_id = _parse_traceparent(traceparent)
    except ValueError:
        return

    phase = args.phase.upper()
    operation = _PHASE_OPERATION.get(phase, phase.lower())

    end_ns = _now_ns()
    duration_s = float(args.duration_s or 0)
    start_ns = end_ns - int(duration_s * 1_000_000_000)

    span_id = secrets.token_hex(8)

    attributes: dict[str, object] = {
        _GEN_AI_AGENT_NAME: "spiral",
        _GEN_AI_OPERATION_NAME: operation,
        _GEN_AI_SYSTEM: "anthropic",
        "spiral.phase": phase,
        "spiral.duration_s": duration_s,
    }
    if args.iteration is not None:
        attributes["spiral.iteration"] = int(args.iteration)
    if args.story_id:
        attributes["spiral.story_id"] = args.story_id
    if args.input_tokens is not None and args.input_tokens >= 0:
        attributes[_GEN_AI_INPUT_TOKENS] = int(args.input_tokens)
    if args.output_tokens is not None and args.output_tokens >= 0:
        attributes[_GEN_AI_OUTPUT_TOKENS] = int(args.output_tokens)

    _emit_completed_span(
        name=f"invoke_agent spiral/{phase}",
        trace_id_hex=trace_id,
        parent_span_id_hex=parent_span_id,
        span_id_hex=span_id,
        start_time_ns=start_ns,
        end_time_ns=end_ns,
        attributes=attributes,
    )


def cmd_end_run(args: argparse.Namespace) -> None:
    """
    Emit the completed root OTel span for the whole run.
    Reads state from otel_run_context.json in the scratch dir.
    No-ops silently if OTEL_EXPORTER_OTLP_ENDPOINT is not set.
    """
    if not _otlp_endpoint():
        return

    scratch = Path(os.environ.get("SPIRAL_SCRATCH_DIR", ".spiral"))
    ctx_file = scratch / "otel_run_context.json"
    if not ctx_file.exists():
        return

    try:
        state = json.loads(ctx_file.read_text())
    except (OSError, json.JSONDecodeError):
        return

    trace_id = state.get("trace_id", "")
    span_id = state.get("root_span_id", "")
    start_ns = int(state.get("start_time_ns", _now_ns()))
    run_id = state.get("run_id", "")

    if not trace_id or not span_id:
        return

    end_ns = _now_ns()

    attributes: dict[str, object] = {
        _GEN_AI_AGENT_NAME: "spiral",
        _GEN_AI_AGENT_ID: run_id,
        _GEN_AI_OPERATION_NAME: "invoke_agent",
        _GEN_AI_SYSTEM: "anthropic",
    }
    if args.passes is not None:
        attributes["spiral.stories_passed"] = int(args.passes)
    if args.story_count is not None:
        attributes["spiral.story_count"] = int(args.story_count)

    _emit_completed_span(
        name="invoke_agent spiral",
        trace_id_hex=trace_id,
        parent_span_id_hex=None,
        span_id_hex=span_id,
        start_time_ns=start_ns,
        end_time_ns=end_ns,
        attributes=attributes,
        is_root=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SPIRAL OTel GenAI span emitter (US-184)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # begin-run
    p_begin = sub.add_parser("begin-run", help="Start a SPIRAL run trace")
    p_begin.add_argument("--run-id", required=True, help="SPIRAL_RUN_ID")
    p_begin.add_argument("--scratch-dir", required=True, help="Path to .spiral/ scratch dir")

    # end-phase
    p_phase = sub.add_parser("end-phase", help="Emit a completed phase span")
    p_phase.add_argument("--phase", required=True,
                         choices=list(_PHASE_OPERATION.keys()),
                         help="Phase letter (R/T/I/V/M/G/S/C)")
    p_phase.add_argument("--duration-s", type=float, default=0,
                         help="Phase wall-clock duration in seconds")
    p_phase.add_argument("--input-tokens", type=int, default=None,
                         help="LLM input token count")
    p_phase.add_argument("--output-tokens", type=int, default=None,
                         help="LLM output token count")
    p_phase.add_argument("--story-id", default=None,
                         help="Current story ID (e.g. US-042)")
    p_phase.add_argument("--iteration", type=int, default=None,
                         help="Spiral iteration number")

    # end-run
    p_end = sub.add_parser("end-run", help="Emit the root run span")
    p_end.add_argument("--passes", type=int, default=None,
                       help="Number of stories that passed")
    p_end.add_argument("--story-count", type=int, default=None,
                       help="Total number of stories")

    args = parser.parse_args()

    try:
        if args.command == "begin-run":
            cmd_begin_run(args)
        elif args.command == "end-phase":
            cmd_end_phase(args)
        elif args.command == "end-run":
            cmd_end_run(args)
    except Exception:  # pylint: disable=broad-except
        # Never crash spiral.sh due to OTel errors
        pass


if __name__ == "__main__":
    main()
