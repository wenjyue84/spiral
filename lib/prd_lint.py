#!/usr/bin/env python3
"""
lib/prd_lint.py — prd.json acceptance-criteria lint check (US-209)

Scans prd.json and warns on every story that has an absent, null, or empty
acceptanceCriteria array.  Stories with _skipped: true are excluded.

Exit codes:
  0 — no violations (or violations found but SPIRAL_STRICT_AC not set)
  1 — violations found AND SPIRAL_STRICT_AC=true
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Force UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def prd_lint(prd: dict) -> list[dict]:
    """Return a list of violation dicts for stories missing acceptanceCriteria.

    Each dict has keys: id, title
    Stories with _skipped: true are excluded.
    """
    violations: list[dict] = []
    for story in prd.get("userStories", []):
        if story.get("_skipped"):
            continue
        ac = story.get("acceptanceCriteria")
        if ac is None or ac == [] or not isinstance(ac, list) or len(ac) == 0:
            violations.append({"id": story.get("id", "?"), "title": story.get("title", "")})
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lint prd.json for stories missing acceptanceCriteria"
    )
    parser.add_argument("prd", help="Path to prd.json")
    parser.add_argument(
        "--events-file",
        default="",
        help="Path to spiral_events.jsonl (optional; violations are appended)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-violation output (still writes events file)",
    )
    args = parser.parse_args()

    # Load prd.json
    try:
        with open(args.prd, encoding="utf-8") as fh:
            prd = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[prd-lint] ERROR: Cannot read {args.prd}: {exc}", file=sys.stderr)
        return 1

    violations = prd_lint(prd)

    strict = os.environ.get("SPIRAL_STRICT_AC", "").lower() == "true"

    for v in violations:
        msg = f"WARN [prd-lint] Story {v['id']} '{v['title']}' has no acceptanceCriteria"
        if not args.quiet:
            print(msg)

        # Append to spiral_events.jsonl
        events_path = args.events_file
        if events_path:
            try:
                ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                event = json.dumps(
                    {
                        "ts": ts,
                        "event_type": "prd_lint_warning",
                        "story_id": v["id"],
                        "title": v["title"],
                        "message": msg,
                    }
                )
                with open(events_path, "a", encoding="utf-8") as fh:
                    fh.write(event + "\n")
            except OSError:
                pass  # non-fatal

    if violations and strict:
        print(
            f"[prd-lint] FATAL: {len(violations)} story(ies) missing acceptanceCriteria "
            f"(SPIRAL_STRICT_AC=true)"
        )
        return 1

    if violations and not args.quiet:
        print(
            f"[prd-lint] {len(violations)} story(ies) have no acceptanceCriteria "
            f"(set SPIRAL_STRICT_AC=true to make this a hard error)"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
