"""phase_replay.py — Re-run a SPIRAL phase with DEBUG=1 and full state capture.

Usage (via main.py CLI):
    spiral replay --phase R --iteration 3

Writes:
    .spiral/replay-{phase}-iter{iteration}.log       — DEBUG log of the re-run
    .spiral/replay-state-{phase}-iter{iteration}.json — pre/post state snapshot

State JSON schema::

    {
      "phase": "R",
      "iteration": 3,
      "prd_snapshot": {"before": {...}, "after": {...}},
      "git_head": "<sha>",
      "api_calls_count": <int>,
      "tokens_used": <int>,
      "output_files": [{"path": "<str>", "checksum": "<sha256hex>"}],
      "started_at": "<iso8601>",
      "completed_at": "<iso8601>"
    }
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Phase → output file mapping (relative to scratch_dir)
# ---------------------------------------------------------------------------

_PHASE_OUTPUTS: dict[str, list[str]] = {
    "R": ["_research_output.json"],
    "T": ["_test_stories_output.json"],
    "S": ["_validated_stories.json"],
    "M": [],  # merges into prd.json at repo root
    "I": [],  # varies per story
    "V": [],
    "C": [],
}

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """Return hex SHA-256 digest of *path* contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_prd_snapshot(prd_path: Path) -> dict[str, Any]:
    """Load *prd_path* and return its parsed JSON, or empty dict on error."""
    if not prd_path.exists():
        return {}
    try:
        with open(prd_path, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return {}


def _git_head(repo_dir: Path) -> str:
    """Return the current git HEAD commit hash, or empty string on error."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_dir),
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass
    return ""


def _collect_output_files(phase: str, scratch_dir: Path) -> list[dict[str, str]]:
    """Return ``[{path, checksum}]`` for phase output files that exist on disk."""
    result: list[dict[str, str]] = []
    for fname in _PHASE_OUTPUTS.get(phase.upper(), []):
        fpath = scratch_dir / fname
        if fpath.exists():
            result.append({"path": str(fpath), "checksum": _sha256_file(fpath)})
    return result


def _parse_token_counts(stdout: str) -> tuple[int, int]:
    """Parse ``tokens_used=N`` and ``api_calls=N`` lines from *stdout*.

    Returns ``(tokens_used, api_calls_count)``.
    """
    tokens_used = 0
    api_calls_count = 0
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("tokens_used="):
            try:
                tokens_used = int(stripped.split("=", 1)[1])
            except (ValueError, IndexError):
                pass
        elif stripped.startswith("api_calls="):
            try:
                api_calls_count = int(stripped.split("=", 1)[1])
            except (ValueError, IndexError):
                pass
    return tokens_used, api_calls_count


# ---------------------------------------------------------------------------
# Phase runner type & default implementation
# ---------------------------------------------------------------------------

PhaseRunner = Callable[[str, int, dict[str, str], Path], tuple[str, str, int]]
"""``(phase, iteration, env, cwd) -> (stdout, stderr, returncode)``."""


def _default_phase_runner(
    phase: str,
    iteration: int,
    env: dict[str, str],
    cwd: Path,
) -> tuple[str, str, int]:
    """Run ``bash spiral.sh --replay-phase PHASE --replay-iter N`` with ``DEBUG=1``."""
    spiral_sh = cwd / "spiral.sh"
    cmd = [
        "bash",
        str(spiral_sh),
        "--replay-phase",
        phase,
        "--replay-iter",
        str(iteration),
    ]
    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=300,
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "ERROR: phase replay timed out after 300s\n", 124
    except (FileNotFoundError, OSError) as exc:
        return "", f"ERROR: could not run phase: {exc}\n", 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_phase_replay(
    phase: str,
    iteration: int,
    prd_path: Path,
    scratch_dir: Path,
    repo_dir: Path,
    phase_runner: Optional[PhaseRunner] = None,
) -> dict[str, Any]:
    """Re-run *phase* with ``DEBUG=1`` and capture full pre/post state.

    Args:
        phase:        Phase letter (e.g. ``"R"``, ``"T"``, ``"S"``).
        iteration:    Iteration number to replay (informational label).
        prd_path:     Absolute path to ``prd.json``.
        scratch_dir:  Path to ``.spiral/`` scratch directory.
        repo_dir:     Repo root that contains ``spiral.sh``.
        phase_runner: Optional injectable callable for testing.  Defaults to
                      the subprocess-based :func:`_default_phase_runner`.

    Returns:
        State dict; also written as JSON to
        ``scratch_dir/replay-state-{phase}-iter{iteration}.json``.
    """
    scratch_dir.mkdir(parents=True, exist_ok=True)
    phase = phase.upper()

    log_path = scratch_dir / f"replay-{phase}-iter{iteration}.log"
    state_path = scratch_dir / f"replay-state-{phase}-iter{iteration}.json"

    started_at = datetime.now(timezone.utc).isoformat()

    # ── Pre-state ────────────────────────────────────────────────────────────
    prd_before = _load_prd_snapshot(prd_path)
    git_head = _git_head(repo_dir)

    # ── Run phase ────────────────────────────────────────────────────────────
    env: dict[str, str] = {**os.environ, "DEBUG": "1"}
    runner = phase_runner or _default_phase_runner
    stdout, stderr, returncode = runner(phase, iteration, env, repo_dir)

    # ── Write log ────────────────────────────────────────────────────────────
    with open(log_path, "w", encoding="utf-8") as lf:
        lf.write(f"[replay] phase={phase} iteration={iteration} started_at={started_at}\n")
        lf.write(stdout)
        if stderr:
            lf.write("\n[stderr]\n")
            lf.write(stderr)
        lf.write(f"\n[replay] exit_code={returncode}\n")

    # ── Parse metrics ────────────────────────────────────────────────────────
    tokens_used, api_calls_count = _parse_token_counts(stdout)

    # ── Post-state ───────────────────────────────────────────────────────────
    prd_after = _load_prd_snapshot(prd_path)
    output_files = _collect_output_files(phase, scratch_dir)
    completed_at = datetime.now(timezone.utc).isoformat()

    state: dict[str, Any] = {
        "phase": phase,
        "iteration": iteration,
        "prd_snapshot": {"before": prd_before, "after": prd_after},
        "git_head": git_head,
        "api_calls_count": api_calls_count,
        "tokens_used": tokens_used,
        "output_files": output_files,
        "started_at": started_at,
        "completed_at": completed_at,
    }

    with open(state_path, "w", encoding="utf-8") as sf:
        json.dump(state, sf, indent=2, ensure_ascii=False)

    return state


# ---------------------------------------------------------------------------
# Standalone CLI
# ---------------------------------------------------------------------------


def _cli(argv: list[str] | None = None) -> int:
    """Standalone CLI entry point (also called by ``main.py cmd_replay``)."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="spiral replay",
        description="Re-run a SPIRAL phase with DEBUG=1 and full state capture.",
    )
    parser.add_argument(
        "--phase",
        required=True,
        metavar="PHASE",
        help="Phase letter to replay, e.g. R, T, S",
    )
    parser.add_argument(
        "--iteration",
        required=True,
        type=int,
        metavar="N",
        help="Iteration number from the original run",
    )
    parser.add_argument(
        "--prd",
        default="prd.json",
        metavar="FILE",
        help="Path to prd.json (default: prd.json)",
    )
    parser.add_argument(
        "--scratch-dir",
        default=".spiral",
        metavar="DIR",
        dest="scratch_dir",
        help="Scratch directory (default: .spiral)",
    )

    parsed = parser.parse_args(argv)

    repo_dir = Path.cwd()
    prd_path = Path(parsed.prd)
    if not prd_path.is_absolute():
        prd_path = repo_dir / prd_path
    scratch_dir = Path(parsed.scratch_dir)
    if not scratch_dir.is_absolute():
        scratch_dir = repo_dir / scratch_dir

    state = run_phase_replay(
        phase=parsed.phase,
        iteration=parsed.iteration,
        prd_path=prd_path,
        scratch_dir=scratch_dir,
        repo_dir=repo_dir,
    )

    p = state["phase"]
    it = state["iteration"]
    print(f"[replay] Log written:   {scratch_dir / f'replay-{p}-iter{it}.log'}")
    print(f"[replay] State written: {scratch_dir / f'replay-state-{p}-iter{it}.json'}")
    print(f"[replay] tokens_used={state['tokens_used']} api_calls={state['api_calls_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
