"""lib/federation_audit.py — Federation Audit Trail Management.

Records all story merge/reject/quota-violation events in Phase M for post-hoc debugging
and compliance tracking across sub-projects.

Audit trail is stored as JSONL (.spiral/federation_audit.jsonl) with entries:
{timestamp, story_id, sub_project, action, reason, tokens_spent}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_audit_entry(
    action: str,
    story_id: str,
    sub_project: str = "",
    reason: str = "",
    tokens_spent: int = 0,
    audit_path: str | Path = ".spiral/federation_audit.jsonl",
) -> None:
    """Write an audit entry to the federation audit trail.

    Args:
        action: 'merge', 'reject', or 'quota_violation'
        story_id: Story ID (e.g. 'US-123')
        sub_project: Sub-project name (e.g. 'frontend')
        reason: Human-readable reason for the action
        tokens_spent: Token count (for resource tracking)
        audit_path: Path to JSONL audit file
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "story_id": story_id,
        "sub_project": sub_project,
        "action": action,
        "reason": reason,
        "tokens_spent": tokens_spent,
    }

    # Ensure directory exists
    p = Path(audit_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Append JSONL entry
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def parse_audit_log(
    audit_path: str | Path = ".spiral/federation_audit.jsonl",
) -> list[dict[str, Any]]:
    """Parse audit log JSONL file and return list of entries.

    Args:
        audit_path: Path to JSONL audit file

    Returns:
        List of audit entry dicts; empty list if file doesn't exist
    """
    p = Path(audit_path)
    if not p.exists():
        return []

    entries: list[dict[str, Any]] = []
    with open(audit_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entries.append(entry)
            except json.JSONDecodeError:
                # Skip malformed lines
                continue

    return entries
