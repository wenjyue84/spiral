"""lib/error_catalog.py — Structured error taxonomy for SPIRAL (US-273).

Provides ERROR_CATALOG: a mapping of catalog codes (E1xx–E5xx) to structured
error metadata including category, message template, exit code, remediation
hint, and documentation URL.

Categories and catalog code ranges:
  Config  E1xx  — configuration and usage errors
  API     E2xx  — external API / network errors
  Git     E3xx  — git and worktree errors
  Worker  E4xx  — worker lifecycle and progress errors
  Schema  E5xx  — PRD schema and validation errors
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ErrorEntry:
    """Single entry in the SPIRAL error catalog."""

    code: str  # e.g. "E101"
    category: str  # Config | API | Git | Worker | Schema
    exit_code: int  # process exit code
    message: str  # human-readable template (may contain {placeholders})
    remediation: str  # actionable fix command or instruction
    docs_url: str  # link to docs or empty string


# ── Error Catalog ─────────────────────────────────────────────────────────────
# Exit codes map to the existing constants in spiral.sh (ERR_BAD_USAGE=2, etc.)
# to preserve backward compatibility with CI and existing tooling.

ERROR_CATALOG: dict[str, ErrorEntry] = {
    # ── Config (E1xx) ──────────────────────────────────────────────────────
    "E101": ErrorEntry(
        code="E101",
        category="Config",
        exit_code=2,
        message="Invalid CLI arguments: {details}",
        remediation="Run: bash spiral.sh --help",
        docs_url="https://github.com/user/spiral#usage",
    ),
    "E102": ErrorEntry(
        code="E102",
        category="Config",
        exit_code=3,
        message="Missing or invalid spiral.config.sh value: {details}",
        remediation="Run: bash spiral.sh --doctor   # to check all config values",
        docs_url="https://github.com/user/spiral#configuration",
    ),
    "E103": ErrorEntry(
        code="E103",
        category="Config",
        exit_code=4,
        message="Required tool not found: {details}",
        remediation="Run: bash spiral.sh --doctor   # to identify missing dependencies",
        docs_url="https://github.com/user/spiral#prerequisites",
    ),
    "E104": ErrorEntry(
        code="E104",
        category="Config",
        exit_code=8,
        message="Cost ceiling reached: spent ${details} exceeds SPIRAL_COST_CEILING",
        remediation="Increase SPIRAL_COST_CEILING in spiral.config.sh or set SPIRAL_COST_CEILING=0 to disable",
        docs_url="https://github.com/user/spiral#cost-controls",
    ),
    # ── API (E2xx) ─────────────────────────────────────────────────────────
    "E201": ErrorEntry(
        code="E201",
        category="API",
        exit_code=14,
        message="Claude API unreachable at startup: {details}",
        remediation="Check your API key: echo $ANTHROPIC_API_KEY | head -c8 ; check https://status.anthropic.com",
        docs_url="https://github.com/user/spiral#api-setup",
    ),
    # ── Git (E3xx) ─────────────────────────────────────────────────────────
    "E301": ErrorEntry(
        code="E301",
        category="Git",
        exit_code=12,
        message="Rollback failed for story {details}",
        remediation="Run: git log --oneline -5   # inspect recent commits, then manually revert",
        docs_url="https://github.com/user/spiral#rollback",
    ),
    # ── Worker (E4xx) ──────────────────────────────────────────────────────
    "E401": ErrorEntry(
        code="E401",
        category="Worker",
        exit_code=9,
        message="Zero-progress stall: all pending stories are blocked",
        remediation="Run: python main.py status   # check blocked stories; consider --skip-story or splitting stories",
        docs_url="https://github.com/user/spiral#stall-detection",
    ),
    "E402": ErrorEntry(
        code="E402",
        category="Worker",
        exit_code=10,
        message="Replay failed for story {details}",
        remediation="Run: python main.py status   # check story state; re-run with --replay STORY_ID",
        docs_url="https://github.com/user/spiral#replay",
    ),
    "E403": ErrorEntry(
        code="E403",
        category="Worker",
        exit_code=11,
        message="Story not found in prd.json: {details}",
        remediation="Run: cat prd.json | jq '.userStories[].id'   # list available story IDs",
        docs_url="https://github.com/user/spiral#prd-management",
    ),
    "E404": ErrorEntry(
        code="E404",
        category="Worker",
        exit_code=13,
        message="Max spiral iterations ({details}) reached with stories still pending",
        remediation="Increase max iterations: bash spiral.sh 50 --gate proceed",
        docs_url="https://github.com/user/spiral#iteration-limits",
    ),
    "E405": ErrorEntry(
        code="E405",
        category="Worker",
        exit_code=15,
        message="Cascade abort: consecutive failures exceeded threshold ({details})",
        remediation="Run: python main.py diagnose   # inspect failure chain; fix blocking stories first",
        docs_url="https://github.com/user/spiral#cascade-abort",
    ),
    # ── Schema (E5xx) ──────────────────────────────────────────────────────
    "E501": ErrorEntry(
        code="E501",
        category="Schema",
        exit_code=5,
        message="prd.json not found at {details}",
        remediation="Run: cp templates/prd.example.json prd.json   # create from template",
        docs_url="https://github.com/user/spiral#prd-setup",
    ),
    "E502": ErrorEntry(
        code="E502",
        category="Schema",
        exit_code=6,
        message="prd.json is corrupt and unrecoverable: {details}",
        remediation=(
            "Run: python -m json.tool prd.json   # check JSON syntax; restore from git: git checkout HEAD -- prd.json"
        ),
        docs_url="https://github.com/user/spiral#prd-recovery",
    ),
    "E503": ErrorEntry(
        code="E503",
        category="Schema",
        exit_code=7,
        message="prd.json schemaVersion ({details}) is newer than SPIRAL supports",
        remediation="Update SPIRAL: git pull origin main   # or downgrade prd.json schemaVersion to 1",
        docs_url="https://github.com/user/spiral#schema-versioning",
    ),
}

# Reverse lookup: exit_code → catalog code (first match)
_EXIT_TO_CATALOG: dict[int, str] = {}
for _code, _entry in ERROR_CATALOG.items():
    if _entry.exit_code not in _EXIT_TO_CATALOG:
        _EXIT_TO_CATALOG[_entry.exit_code] = _code


def lookup_by_exit_code(exit_code: int) -> ErrorEntry | None:
    """Find catalog entry by process exit code."""
    cat_code = _EXIT_TO_CATALOG.get(exit_code)
    if cat_code:
        return ERROR_CATALOG[cat_code]
    return None


def format_error(code: str, context: dict[str, str] | None = None) -> str:
    """Format a catalog error for terminal display.

    Returns a multi-line string:
      [SPIRAL-E-<code>] <message>
      Fix: <remediation>
      Docs: <docs_url>
    """
    entry = ERROR_CATALOG.get(code)
    if not entry:
        return f"[SPIRAL-E-{code}] Unknown error code"
    details = (context or {}).get("details", "")
    msg = entry.message.format(details=details)
    lines = [f"[SPIRAL-E-{entry.code}] {msg}"]
    lines.append(f"Fix: {entry.remediation}")
    if entry.docs_url:
        lines.append(f"Docs: {entry.docs_url}")
    return "\n".join(lines)


def error_to_event(code: str, context: dict[str, str] | None = None) -> dict[str, Any]:
    """Build a structured dict suitable for spiral_events.jsonl."""
    entry = ERROR_CATALOG.get(code)
    if not entry:
        return {
            "event": "spiral_error",
            "error_code": code,
            "category": "unknown",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    details = (context or {}).get("details", "")
    return {
        "event": "spiral_error",
        "error_code": entry.code,
        "category": entry.category,
        "exit_code": entry.exit_code,
        "message": entry.message.format(details=details),
        "remediation": entry.remediation,
        "docs_url": entry.docs_url,
        "context": context or {},
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def write_error_event(
    code: str,
    context: dict[str, str] | None = None,
    events_file: Path | None = None,
) -> None:
    """Append a structured error event to spiral_events.jsonl."""
    if events_file is None:
        scratch = Path(os.environ.get("SCRATCH_DIR", ".spiral"))
        events_file = scratch / "spiral_events.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)
    event = error_to_event(code, context)
    with open(events_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


# Allow import without os at module level (only needed in write_error_event)
import os  # noqa: E402


def main() -> None:
    """CLI: print formatted error for a given catalog code.

    Usage: python -m lib.error_catalog E101 [details]
    """
    if len(sys.argv) < 2:
        print("Usage: python -m lib.error_catalog <ERROR_CODE> [details]")
        print("\nAvailable codes:")
        for code, entry in sorted(ERROR_CATALOG.items()):
            print(f"  {code}  [{entry.category}]  exit={entry.exit_code}  {entry.message}")
        sys.exit(0)
    code = sys.argv[1].upper()
    details = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
    ctx = {"details": details} if details else None
    print(format_error(code, ctx))
    entry = ERROR_CATALOG.get(code)
    if entry:
        sys.exit(entry.exit_code)
    sys.exit(1)


if __name__ == "__main__":
    main()
