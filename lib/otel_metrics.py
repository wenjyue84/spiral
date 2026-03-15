#!/usr/bin/env python3
"""
lib/otel_metrics.py — OTel GenAI metrics for SPIRAL (US-189)

Emits OpenTelemetry metrics conforming to the GenAI semantic conventions:
  gen_ai.client.token.usage      — counter (input + output tokens per LLM call)
  gen_ai.client.operation.duration — histogram (wall-clock ms per LLM call)

Shell integration:
  # After each LLM call (Phase I per story):
  "$SPIRAL_PYTHON" lib/otel_metrics.py record-tokens \\
      --story-id "$_NEXT_SID" --phase I \\
      --input-tokens "$_TOK_IN" --output-tokens "$_TOK_OUT" \\
      --duration-ms "$_DUR_MS" \\
      --scratch-dir "$SCRATCH_DIR" 2>/dev/null || true

  # Start Prometheus scrape endpoint (background process):
  "$SPIRAL_PYTHON" lib/otel_metrics.py serve-prometheus \\
      --port "$SPIRAL_PROM_PORT" --scratch-dir "$SCRATCH_DIR" &

Silently no-ops on OTLP export when OTEL_EXPORTER_OTLP_ENDPOINT is not set.
Always writes to the local JSONL file regardless of OTLP configuration.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# ── GenAI semconv metric names (semconv 0.61+) ────────────────────────────────
_METRIC_TOKEN_USAGE = "gen_ai.client.token.usage"
_METRIC_OPERATION_DURATION = "gen_ai.client.operation.duration"

# ── Attribute names ───────────────────────────────────────────────────────────
_ATTR_SYSTEM = "gen_ai.system"
_ATTR_OPERATION = "gen_ai.operation.name"
_ATTR_TOKEN_TYPE = "gen_ai.token.type"
_ATTR_STORY_ID = "spiral.story_id"
_ATTR_PHASE = "spiral.phase"


def _otlp_endpoint() -> Optional[str]:
    ep = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    return ep if ep else None


def _token_metrics_path(scratch_dir: str) -> Path:
    return Path(scratch_dir) / "token_metrics.jsonl"


def cmd_record_tokens(args: argparse.Namespace) -> None:
    """
    Record token usage + operation duration for one LLM call.

    1. Appends a JSONL record to $SCRATCH_DIR/token_metrics.jsonl
    2. Emits gen_ai.client.token.usage and gen_ai.client.operation.duration
       via OTLP if OTEL_EXPORTER_OTLP_ENDPOINT is set.
    """
    story_id: str = args.story_id or ""
    phase: str = (args.phase or "I").upper()
    input_tokens: int = max(0, int(args.input_tokens or 0))
    output_tokens: int = max(0, int(args.output_tokens or 0))
    duration_ms: float = max(0.0, float(args.duration_ms or 0))
    scratch_dir: str = args.scratch_dir

    # ── 1. Append to local JSONL ──────────────────────────────────────────────
    Path(scratch_dir).mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "story_id": story_id,
        "phase": phase,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "duration_ms": duration_ms,
    }
    try:
        with open(_token_metrics_path(scratch_dir), "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as e:
        print(f"[otel_metrics] WARNING: failed to write metrics: {e}", file=sys.stderr)

    # ── 2. OTLP metrics export ────────────────────────────────────────────────
    endpoint = _otlp_endpoint()
    if not endpoint:
        return

    try:
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        resource = Resource.create({SERVICE_NAME: "spiral"})
        exporter = OTLPMetricExporter(endpoint=endpoint)
        # Short export interval so force_flush sends immediately
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=100)
        provider = MeterProvider(resource=resource, metric_readers=[reader])
        meter = provider.get_meter("spiral.genai", schema_url="https://opentelemetry.io/schemas/1.26.0")

        common_attrs = {
            _ATTR_SYSTEM: "anthropic",
            _ATTR_OPERATION: "execute_task",
            _ATTR_STORY_ID: story_id,
            _ATTR_PHASE: phase,
        }

        # gen_ai.client.token.usage — separate measurements for input/output
        token_counter = meter.create_counter(
            _METRIC_TOKEN_USAGE,
            unit="{token}",
            description="Number of tokens used in GenAI LLM calls",
        )
        if input_tokens > 0:
            token_counter.add(input_tokens, {**common_attrs, _ATTR_TOKEN_TYPE: "input"})
        if output_tokens > 0:
            token_counter.add(output_tokens, {**common_attrs, _ATTR_TOKEN_TYPE: "output"})

        # gen_ai.client.operation.duration — histogram in ms
        duration_hist = meter.create_histogram(
            _METRIC_OPERATION_DURATION,
            unit="ms",
            description="Wall-clock duration of GenAI LLM operations in milliseconds",
        )
        if duration_ms > 0:
            duration_hist.record(duration_ms, common_attrs)

        # Force flush so the exporter actually sends before process exits
        provider.force_flush(timeout_millis=5000)
    except Exception:  # pylint: disable=broad-except
        import traceback
        print("[otel_metrics] ERROR:", traceback.format_exc(), file=sys.stderr)


def _build_prometheus_text(scratch_dir: str) -> str:
    """
    Read token_metrics.jsonl and render Prometheus text-format metrics.
    Aggregates token totals per story_id × token_type.
    """
    metrics_file = _token_metrics_path(scratch_dir)
    if not metrics_file.exists():
        return "# No token metrics recorded yet.\n"

    # Aggregate: story_id -> {input, output, duration_ms_list}
    totals: dict[str, dict[str, object]] = {}

    try:
        for line in metrics_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = rec.get("story_id", "unknown")
            phase = rec.get("phase", "I")
            key = f"{sid}:{phase}"
            if key not in totals:
                totals[key] = {"story_id": sid, "phase": phase, "input": 0, "output": 0, "calls": 0, "duration_ms": 0.0}
            totals[key]["input"] = totals[key]["input"] + rec.get("input_tokens", 0)  # type: ignore[operator]
            totals[key]["output"] = totals[key]["output"] + rec.get("output_tokens", 0)  # type: ignore[operator]
            totals[key]["calls"] = totals[key]["calls"] + 1  # type: ignore[operator]
            totals[key]["duration_ms"] = totals[key]["duration_ms"] + rec.get("duration_ms", 0.0)  # type: ignore[operator]
    except OSError:
        return "# Error reading token_metrics.jsonl\n"

    lines = [
        "# HELP gen_ai_client_token_usage_total Number of tokens used per GenAI LLM call",
        "# TYPE gen_ai_client_token_usage_total counter",
    ]
    for entry in totals.values():
        sid = str(entry["story_id"]).replace('"', '\\"')
        phase = str(entry["phase"])
        labels = f'story_id="{sid}",phase="{phase}"'
        lines.append(f'gen_ai_client_token_usage_total{{token_type="input",{labels}}} {entry["input"]}')
        lines.append(f'gen_ai_client_token_usage_total{{token_type="output",{labels}}} {entry["output"]}')

    lines += [
        "",
        "# HELP gen_ai_client_operation_duration_ms_total Total wall-clock ms for GenAI LLM operations",
        "# TYPE gen_ai_client_operation_duration_ms_total counter",
    ]
    for entry in totals.values():
        sid = str(entry["story_id"]).replace('"', '\\"')
        phase = str(entry["phase"])
        labels = f'story_id="{sid}",phase="{phase}"'
        lines.append(f'gen_ai_client_operation_duration_ms_total{{{labels}}} {entry["duration_ms"]:.3f}')

    lines += [
        "",
        "# HELP gen_ai_client_llm_calls_total Number of LLM calls recorded",
        "# TYPE gen_ai_client_llm_calls_total counter",
    ]
    for entry in totals.values():
        sid = str(entry["story_id"]).replace('"', '\\"')
        phase = str(entry["phase"])
        labels = f'story_id="{sid}",phase="{phase}"'
        lines.append(f'gen_ai_client_llm_calls_total{{{labels}}} {entry["calls"]}')

    lines.append("")
    return "\n".join(lines)


def cmd_serve_prometheus(args: argparse.Namespace) -> None:
    """
    Start a Prometheus scrape endpoint serving /metrics from token_metrics.jsonl.
    Runs until killed. Intended to be launched as a background process by spiral.sh.
    """
    port: int = int(args.port)
    scratch_dir: str = args.scratch_dir

    class MetricsHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/metrics":
                body = _build_prometheus_text(scratch_dir).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404, "Only /metrics is available")

        def log_message(self, format: str, *fargs: object) -> None:  # noqa: A002
            pass  # Suppress request logs

    server = http.server.HTTPServer(("0.0.0.0", port), MetricsHandler)
    print(f"SPIRAL metrics server listening on :{port}/metrics", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SPIRAL OTel GenAI metrics (US-189)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # record-tokens
    p_rec = sub.add_parser("record-tokens", help="Record token usage for one LLM call")
    p_rec.add_argument("--story-id", default="", help="Story ID (e.g. US-042)")
    p_rec.add_argument("--phase", default="I", help="Phase letter (I/R/T/V/M/G/S/C)")
    p_rec.add_argument("--input-tokens", type=int, default=0, help="Prompt token count")
    p_rec.add_argument("--output-tokens", type=int, default=0, help="Completion token count")
    p_rec.add_argument("--duration-ms", type=float, default=0.0, help="LLM call wall-clock ms")
    p_rec.add_argument("--scratch-dir", required=True, help="Path to .spiral/ scratch dir")

    # serve-prometheus
    p_srv = sub.add_parser("serve-prometheus", help="Serve /metrics Prometheus endpoint")
    p_srv.add_argument("--port", type=int, required=True, help="TCP port to listen on")
    p_srv.add_argument("--scratch-dir", required=True, help="Path to .spiral/ scratch dir")

    args = parser.parse_args()

    try:
        if args.command == "record-tokens":
            cmd_record_tokens(args)
        elif args.command == "serve-prometheus":
            cmd_serve_prometheus(args)
    except Exception:  # pylint: disable=broad-except
        import traceback
        print("[otel_metrics] ERROR:", traceback.format_exc(), file=sys.stderr)


if __name__ == "__main__":
    main()
