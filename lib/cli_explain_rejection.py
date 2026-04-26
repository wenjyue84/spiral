"""lib/cli_explain_rejection.py — Display story rejection summary via `spiral explain-rejection <id>`.

CLI: Called from lib/cli_subcommands.sh via:
  python lib/cli_explain_rejection.py <prd_path> <story_id> [--format text|json] [--rejections <jsonl>]

Outputs human-readable rejection reason with remediation hints.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _load_prd(prd_path: str) -> dict[str, Any]:
    """Load prd.json."""
    with open(prd_path, encoding="utf-8") as f:
        data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"prd.json must be a dict, got {type(data)}")
        return data


def _find_story(prd: dict[str, Any], story_id: str) -> dict[str, Any] | None:
    """Find a story by ID in prd.json."""
    for story in prd.get("userStories", []):
        if story.get("id") == story_id:
            return dict(story)
    return None


def _remediation_hints(reason: str) -> list[str]:
    """Return remediation hints based on rejection reason."""
    hints: list[str] = []

    if "constitution" in reason.lower():
        hints.append("Review the project constitution (SPIRAL_SPECKIT_CONSTITUTION)")
        hints.append("Ensure story title/description don't match forbidden phrases")

    if "goal" in reason.lower() or "misalign" in reason.lower():
        hints.append("Review prd.json goals[] field")
        hints.append("Ensure story description uses goal keywords (tech stack, domain, etc.)")

    if "duplicate" in reason.lower():
        hints.append("Check existing stories for similar title/description")
        hints.append("Add unique angles or specify different implementation approach")

    if "acceptance" in reason.lower() or "measurable" in reason.lower():
        hints.append("Add measurable acceptance criteria with:")
        hints.append("  - CLI commands in backticks (e.g., `npm test`)")
        hints.append("  - File paths/extensions (.py, .sh, .tsx, etc.)")
        hints.append("  - Numeric thresholds (e.g., '5 seconds', '80% coverage')")
        hints.append("  - Test assertions (e.g., 'assert X passes')")

    if "quality" in reason.lower():
        hints.append("Improve story structure:")
        hints.append("  - Expand description to ≥20 words")
        hints.append("  - Add technical notes or estimated complexity")
        hints.append("  - Include 2+ measurable acceptance criteria")

    if not hints:
        hints.append("Review prd.json schema and validation constraints")

    return hints


def _format_text(story: dict[str, Any]) -> str:
    """Format rejection info as human-readable text."""
    lines: list[str] = []
    story_id = story.get("id", "")
    title = story.get("title", "")

    lines.append(f"┌─ REJECTION: {story_id} {'─' * max(0, 50 - len(story_id))}")
    lines.append(f"│  Title: {title[:70]}")
    lines.append("└" + "─" * 63)
    lines.append("")

    rejection_log = story.get("_rejectionLog", [])
    if not rejection_log:
        lines.append("No rejection log found.")
        return "\n".join(lines)

    for i, entry in enumerate(rejection_log, 1):
        ts = entry.get("timestamp", "")
        reason = entry.get("reason", "")
        details = entry.get("details", "")

        lines.append(f"Rejection #{i}")
        lines.append(f"  Timestamp: {ts}")
        lines.append(f"  Reason   : {reason}")
        if details:
            lines.append(f"  Details  : {details}")
        lines.append("")

    hints = _remediation_hints(" ".join(str(e.get("reason", "")) for e in rejection_log))
    if hints:
        lines.append("Remediation Hints")
        for hint in hints:
            lines.append(f"  • {hint}")
        lines.append("")

    return "\n".join(lines)


def _format_json(story: dict[str, Any]) -> str:
    """Format rejection info as JSON."""
    output = {
        "id": story.get("id", ""),
        "title": story.get("title", ""),
        "rejectionLog": story.get("_rejectionLog", []),
        "remediationHints": _remediation_hints(
            " ".join(str(e.get("reason", "")) for e in story.get("_rejectionLog", []))
        ),
    }
    return json.dumps(output, indent=2)


def main() -> int:
    """Parse args and display rejection summary."""
    if len(sys.argv) < 3:
        print(
            "Usage: python lib/cli_explain_rejection.py <prd_path> <story_id> [--format text|json]",
            file=sys.stderr,
        )
        return 1

    prd_path = sys.argv[1]
    story_id = sys.argv[2]
    fmt = "text"

    for i in range(3, len(sys.argv)):
        if sys.argv[i] == "--format" and i + 1 < len(sys.argv):
            fmt = sys.argv[i + 1]

    try:
        prd = _load_prd(prd_path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[error] Could not load prd.json: {e}", file=sys.stderr)
        return 1

    story = _find_story(prd, story_id)
    if not story:
        print(f"[error] Story {story_id} not found in prd.json", file=sys.stderr)
        return 1

    if fmt == "json":
        print(_format_json(story))
    else:
        print(_format_text(story))

    return 0


if __name__ == "__main__":
    sys.exit(main())
