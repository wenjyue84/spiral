#!/usr/bin/env python3
"""
lib/llm_client.py — Streaming LLM completion client using Anthropic SDK (US-416).

Provides stream_completion() function using client.messages.stream() context manager
for real-time progress and token usage tracking.

Features:
  - Streaming text accumulation via stream.text_stream
  - Cache metrics extraction from stream.get_final_message().usage
  - Event emission to spiral_events.jsonl (llm_stream_chunk events)
  - Compatible with prompt caching

Usage:
  from lib.llm_client import stream_completion
  from anthropic import Anthropic

  client = Anthropic(api_key="sk-ant-...")
  text, usage = stream_completion(
      client=client,
      messages=[{"role": "user", "content": "..."}],
      model="claude-sonnet-4-6",
      events_file=".spiral/spiral_events.jsonl",
      phase="S"  # "R" for research, "S" for story validation
  )
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

__all__ = ["stream_completion"]


def stream_completion(
    client: Any,
    messages: list[dict[str, str]],
    model: str,
    events_file: str | None = None,
    phase: str = "S",
    **kwargs: Any,
) -> tuple[str, dict[str, Any]]:
    """Stream LLM completion using Anthropic SDK context manager.

    Uses client.messages.stream() to enable real-time progress output and
    incremental token counting. Returns accumulated text and usage metrics.

    Parameters
    ----------
    client:
        Anthropic SDK client instance.
    messages:
        List of message dicts with "role" and "content" keys.
    model:
        Claude model ID (e.g., "claude-sonnet-4-6").
    events_file:
        Path to spiral_events.jsonl for emitting llm_stream_chunk events.
        If None, events are not emitted.
    phase:
        Phase name for event logging: "R" (research) or "S" (story validation).
        Used in event metadata for phase correlation.
    **kwargs:
        Additional parameters passed to client.messages.stream():
        - max_tokens: int
        - system: str or list
        - temperature: float
        - stop_sequences: list[str]
        - tools: list
        - top_p: float
        - top_k: int

    Returns
    -------
    tuple[str, dict[str, Any]]
        (text, usage) where:
        - text: str — Accumulated response text from stream.text_stream
        - usage: dict — Usage metrics from stream.get_final_message().usage:
          - input_tokens: int
          - output_tokens: int
          - cache_creation_input_tokens: int (prompt caching)
          - cache_read_input_tokens: int (prompt caching)
          - stop_reason: str

    Raises
    ------
    Exception
        If streaming fails or response is malformed.

    Examples
    --------
    >>> from anthropic import Anthropic
    >>> client = Anthropic(api_key="sk-ant-...")
    >>> text, usage = stream_completion(
    ...     client=client,
    ...     messages=[{"role": "user", "content": "Hello"}],
    ...     model="claude-sonnet-4-6",
    ...     events_file=".spiral/spiral_events.jsonl",
    ...     phase="S",
    ...     max_tokens=256
    ... )
    >>> print(f"Generated {usage['output_tokens']} tokens")
    """
    accumulated_text = ""
    chunk_count = 0

    try:
        with client.messages.stream(
            model=model,
            messages=messages,
            **kwargs,
        ) as stream:
            for text in stream.text_stream:
                accumulated_text += text
                chunk_count += 1

                # Emit streaming event (optional, rate-limited to avoid spam)
                if events_file and chunk_count % 10 == 0:
                    _emit_stream_chunk_event(
                        events_file=events_file,
                        phase=phase,
                        model=model,
                        chunk=text,
                        accumulated_length=len(accumulated_text),
                    )

            # Extract final message and usage metrics
            final_message = stream.get_final_message()
            usage_obj = final_message.usage if hasattr(final_message, "usage") else None

            # Build usage dict from message attributes
            usage: dict[str, Any] = {}
            if usage_obj:
                usage = {
                    "input_tokens": getattr(usage_obj, "input_tokens", 0),
                    "output_tokens": getattr(usage_obj, "output_tokens", 0),
                    "cache_creation_input_tokens": getattr(usage_obj, "cache_creation_input_tokens", 0),
                    "cache_read_input_tokens": getattr(usage_obj, "cache_read_input_tokens", 0),
                }
            else:
                usage = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                }

            # Add stop reason if available
            if hasattr(final_message, "stop_reason"):
                usage["stop_reason"] = final_message.stop_reason

            # Emit final event with complete metrics
            if events_file:
                _emit_stream_complete_event(
                    events_file=events_file,
                    phase=phase,
                    model=model,
                    total_chunks=chunk_count,
                    accumulated_length=len(accumulated_text),
                    usage=usage,
                )

            return accumulated_text, usage

    except Exception as e:
        # Emit error event and re-raise
        if events_file:
            _emit_stream_error_event(
                events_file=events_file,
                phase=phase,
                model=model,
                error_msg=str(e),
                accumulated_length=len(accumulated_text),
            )
        raise


def _emit_stream_chunk_event(
    events_file: str,
    phase: str,
    model: str,
    chunk: str,
    accumulated_length: int,
) -> None:
    """Emit a llm_stream_chunk event to spiral_events.jsonl."""
    try:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "llm_stream_chunk",
            "phase": phase,
            "model": model,
            "chunk_length": len(chunk),
            "accumulated_length": accumulated_length,
        }
        with open(events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        pass  # Silently ignore write failures


def _emit_stream_complete_event(
    events_file: str,
    phase: str,
    model: str,
    total_chunks: int,
    accumulated_length: int,
    usage: dict[str, Any],
) -> None:
    """Emit a llm_stream_complete event with final metrics to spiral_events.jsonl."""
    try:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "llm_stream_complete",
            "phase": phase,
            "model": model,
            "total_chunks": total_chunks,
            "final_text_length": accumulated_length,
            "usage": usage,
        }
        with open(events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        pass  # Silently ignore write failures


def _emit_stream_error_event(
    events_file: str,
    phase: str,
    model: str,
    error_msg: str,
    accumulated_length: int,
) -> None:
    """Emit a llm_stream_error event to spiral_events.jsonl."""
    try:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "llm_stream_error",
            "phase": phase,
            "model": model,
            "error": error_msg,
            "accumulated_length": accumulated_length,
        }
        with open(events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        pass  # Silently ignore write failures
