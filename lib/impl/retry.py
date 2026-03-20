"""
lib/impl/retry.py — Python wrapper for Ralph subprocess invocation with timeout handling.

Manages model-tier escalation (haiku→sonnet→opus) when a Ralph worker times out
or fails. Captures partial stdout/stderr on timeout and annotates the result with
enough context for Phase I to decide retry vs skip.

Model escalation ladder:
    haiku  → attempt 1 (or initial assignment)
    sonnet → attempt 2 (first retry)
    opus   → attempt 3 (second retry)
    skip   → attempt 4+ (exhausted)

Environment variables:
    SPIRAL_TIMEOUT_RALPH   — subprocess timeout in seconds (default: 300)
    SPIRAL_MODEL_ROUTING   — if 'auto', enables model escalation
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# Model escalation ladder
_MODEL_LADDER: list[str] = ["haiku", "sonnet", "opus"]

# Default timeout in seconds
_DEFAULT_TIMEOUT = 300


def _next_model(current_model: str) -> str | None:
    """Return next model in escalation ladder, or None if exhausted."""
    try:
        idx = _MODEL_LADDER.index(current_model.lower())
    except ValueError:
        return "sonnet"  # Unknown model → escalate to sonnet
    next_idx = idx + 1
    if next_idx >= len(_MODEL_LADDER):
        return None  # Exhausted
    return _MODEL_LADDER[next_idx]


def execute_ralph(
    story_id: str,
    model: str,
    command: list[str],
    *,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Run a Ralph subprocess for the given story and model tier.

    Returns a dict with keys:
        status          — 'passed' | 'failed' | 'retry_escalated' | 'exhausted'
        stdout          — captured stdout (may be partial on timeout)
        stderr          — captured stderr (may be partial on timeout)
        next_model      — model to use on next retry, or None if exhausted
        timeout_seconds — timeout used (only present on timeout)
        error           — human-readable error message (only present on failure)

    On subprocess.TimeoutExpired:
        - Partial stdout/stderr are captured and returned
        - If output_file is given, partial output is written with a timeout annotation
        - status is set to 'retry_escalated' (unless model ladder exhausted)
        - A structured log message is emitted that includes story_id, model,
          timeout duration, and a suggestion to adjust SPIRAL_TIMEOUT_RALPH
    """
    timeout_seconds = timeout if timeout is not None else int(
        os.environ.get("SPIRAL_TIMEOUT_RALPH", str(_DEFAULT_TIMEOUT))
    )

    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=proc_env,
        )
        if result.returncode == 0:
            return {
                "status": "passed",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "next_model": None,
            }
        else:
            return {
                "status": "failed",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "next_model": _next_model(model),
                "error": f"Ralph exited with code {result.returncode}",
            }

    except subprocess.TimeoutExpired as exc:
        # Capture whatever partial output the process produced before timeout
        partial_stdout: str = exc.stdout if isinstance(exc.stdout, str) else (
            exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
        )
        partial_stderr: str = exc.stderr if isinstance(exc.stderr, str) else (
            exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        )

        escalated_model = _next_model(model)
        status = "retry_escalated" if escalated_model is not None else "exhausted"

        error_msg = (
            f"[Phase I / timeout] story={story_id} model={model} "
            f"timeout={timeout_seconds}s — subprocess timed out. "
            f"Adjust via SPIRAL_TIMEOUT_RALPH env var. "
            f"Next model: {escalated_model or 'none (exhausted)'}."
        )
        logger.error(error_msg)

        if output_file:
            _write_timeout_output(
                output_file=output_file,
                story_id=story_id,
                model=model,
                timeout_seconds=timeout_seconds,
                partial_stdout=partial_stdout,
                partial_stderr=partial_stderr,
            )

        return {
            "status": status,
            "stdout": partial_stdout,
            "stderr": partial_stderr,
            "next_model": escalated_model,
            "timeout_seconds": timeout_seconds,
            "error": error_msg,
        }


def _write_timeout_output(
    *,
    output_file: str,
    story_id: str,
    model: str,
    timeout_seconds: int,
    partial_stdout: str,
    partial_stderr: str,
) -> None:
    """Write partial output and timeout annotation to output_file (JSON)."""
    import json

    annotation = {
        "timeout_error": True,
        "story_id": story_id,
        "model": model,
        "timeout_seconds": timeout_seconds,
        "suggestion": (
            f"Increase timeout via SPIRAL_TIMEOUT_RALPH env var "
            f"(current: {timeout_seconds}s)"
        ),
        "partial_stdout": partial_stdout,
        "partial_stderr": partial_stderr,
    }
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(annotation, f, indent=2)
    except OSError as exc:
        logger.warning("Could not write timeout output to %s: %s", output_file, exc)
