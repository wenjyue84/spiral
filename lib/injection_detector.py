#!/usr/bin/env python3
"""SPIRAL — injection_detector.py

Detect and block prompt injection patterns in prd.json story fields.

Scans story text (title, description, acceptanceCriteria, technicalNotes) for
OWASP LLM01:2025 prompt injection signatures before LLM calls. Blocks
adversarial stories and writes audit entries to security-audit.jsonl.

Usage (library):
    from injection_detector import scan_for_injection, scan_prd_stories

    detected, pattern = scan_for_injection("Ignore previous instructions and ...")
    if detected:
        print(f"Injection found: {pattern}")

Usage (CLI):
    python lib/injection_detector.py --prd prd.json [--audit-log security-audit.jsonl]
    python lib/injection_detector.py --prd prd.json --update-prd
    python lib/injection_detector.py --prd prd.json --allow-unsafe
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── OWASP LLM01:2025 Injection Pattern Catalogue ──────────────────────────────
# Covers the OWASP Top 10 for LLMs 2025 most common jailbreak / override phrases.
# Patterns are compiled case-insensitively.

_RAW_PATTERNS: list[tuple[str, str]] = [
    # 1. Classic "ignore/disregard previous instructions"
    (r"\bignore\s+(all\s+)?previous\s+instructions?\b", "ignore_previous_instructions"),
    (r"\bdisregard\s+(all\s+)?previous\s+instructions?\b", "disregard_previous_instructions"),
    (r"\bforget\s+(all\s+)?previous\s+instructions?\b", "forget_previous_instructions"),

    # 2. System prompt override attempts
    (r"\bsystem\s*prompt\s*:?\s*override\b", "system_prompt_override"),
    (r"\bnew\s+system\s+prompt\b", "new_system_prompt"),
    (r"\byou\s+are\s+now\s+(a|an)\s+\w", "you_are_now_jailbreak"),
    (r"\byour\s+new\s+instructions?\s+(are|is)\b", "new_instructions_jailbreak"),
    (r"\bact\s+as\s+(if\s+you\s+are\s+)?(a|an)\s+\w+\s+(without|that\s+has\s+no)\s+(restriction|filter|limit)", "act_as_unrestricted"),

    # 3. DAN / STAN / Developer Mode jailbreak tokens
    (r"\bDAN\b", "jailbreak_token_DAN"),
    (r"\bSTAN\b", "jailbreak_token_STAN"),
    (r"\bJailbreak\b", "jailbreak_token_explicit"),
    (r"\bDeveloper\s+Mode\s+(enabled|unlocked|activated)\b", "developer_mode_jailbreak"),
    (r"\bDo\s+Anything\s+Now\b", "do_anything_now"),

    # 4. Prompt delimiter / injection via special tokens
    (r"<\|im_start\|>", "special_token_im_start"),
    (r"<\|im_end\|>", "special_token_im_end"),
    (r"\[INST\]", "llama_inst_tag"),
    (r"<\|system\|>", "special_token_system"),
    (r"\bHuman:\s*Ignore\b", "human_ignore_prefix"),

    # 5. Instruction override / manipulation phrases
    (r"\boverride\s+(your|all)\s+(safety|filter|guideline|restrict|rule|instruct)", "safety_override"),
    (r"\bbypass\s+(your|all)\s+(safety|filter|guideline|restrict|rule|instruct)", "safety_bypass"),
    (r"\bdisable\s+(your|all)\s+(safety|filter|guideline|restrict|rule|instruct)", "safety_disable"),
    (r"\bpretend\s+(you\s+(have\s+no|don.t\s+have)\s+(restrict|filter|rule|guideline|limit))", "pretend_unrestricted"),
    (r"\byou\s+(must\s+)?(comply|obey)\s+with\s+(all\s+)?my\s+(command|instruct|request)", "comply_obey_command"),
    (r"\brepeat\s+(everything|all)\s+(above|that\s+you\s+were\s+told)\b", "repeat_system_prompt"),
    (r"\bprint\s+(your\s+)?(system\s+)?prompt\b", "print_system_prompt"),
    (r"\bwhat\s+(are|were)\s+your\s+(original\s+)?instructions?\b", "reveal_instructions"),
]

# 6. Base64-encoded suspicious payloads — decoded and re-scanned
_BASE64_PATTERN = re.compile(
    r"(?<![A-Za-z0-9+/])"   # not preceded by base64 char
    r"[A-Za-z0-9+/]{20,}"   # at least 20 chars of base64
    r"={0,2}"               # optional padding
    r"(?![A-Za-z0-9+/])",   # not followed by base64 char
    re.ASCII,
)

_COMPILED_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(raw, re.IGNORECASE), name)
    for raw, name in _RAW_PATTERNS
]

# Text fields extracted from a story for scanning
_STORY_TEXT_FIELDS = ("title", "description")
_STORY_LIST_FIELDS = ("acceptanceCriteria", "technicalNotes")


# ── Core detection function ────────────────────────────────────────────────────


def scan_for_injection(text: str) -> tuple[bool, Optional[str]]:
    """Scan *text* for OWASP LLM01:2025 injection patterns.

    Returns:
        (True, pattern_name)  — injection detected
        (False, None)         — clean
    """
    if not text:
        return False, None

    # 1. Direct pattern match
    for pattern, name in _COMPILED_PATTERNS:
        if pattern.search(text):
            return True, name

    # 2. Base64-decoded scan — find candidate blobs, decode, re-scan
    for m in _BASE64_PATTERN.finditer(text):
        blob = m.group(0)
        # Pad to multiple of 4
        padded = blob + "=" * (-len(blob) % 4)
        try:
            decoded = base64.b64decode(padded).decode("utf-8", errors="replace")
        except Exception:
            continue
        # Only re-scan if decoded text is printable and non-trivial
        if len(decoded) >= 10 and decoded.isprintable():
            inner_detected, inner_name = scan_for_injection(decoded)
            if inner_detected:
                return True, f"base64_encoded:{inner_name}"

    return False, None


def _story_text_fragments(story: dict) -> list[str]:
    """Extract all text fragments from a story for scanning."""
    fragments: list[str] = []
    for field in _STORY_TEXT_FIELDS:
        val = story.get(field)
        if isinstance(val, str):
            fragments.append(val)
    for field in _STORY_LIST_FIELDS:
        items = story.get(field)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    fragments.append(item)
    return fragments


# ── Batch scanning ─────────────────────────────────────────────────────────────


def scan_prd_stories(
    prd_path: str,
    audit_log: str = "security-audit.jsonl",
    update_prd: bool = False,
    allow_unsafe: bool = False,
) -> tuple[list[str], list[dict]]:
    """Scan all incomplete stories in *prd_path* for injection patterns.

    Args:
        prd_path:    Path to prd.json.
        audit_log:   Path to security-audit.jsonl (appended to).
        update_prd:  If True, mark blocked stories as failed in prd.json.
        allow_unsafe: If True, log warnings but do NOT block stories.

    Returns:
        (blocked_ids, audit_entries)
    """
    prd_file = Path(prd_path)
    prd = json.loads(prd_file.read_text(encoding="utf-8"))
    stories: list[dict] = prd.get("userStories", [])

    blocked_ids: list[str] = []
    audit_entries: list[dict] = []

    for story in stories:
        if story.get("passes", False):
            continue  # already complete — skip

        sid = story.get("id", "?")
        title = story.get("title", "")

        for fragment in _story_text_fragments(story):
            detected, pattern_name = scan_for_injection(fragment)
            if not detected:
                continue

            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "story_id": sid,
                "story_title": title,
                "pattern": pattern_name,
                "action": "warn_only" if allow_unsafe else "blocked",
                "level": "WARN",
            }
            audit_entries.append(entry)

            if not allow_unsafe:
                blocked_ids.append(sid)
                story["passes"] = False
                story["_failureReason"] = "security_block"
                story["_injectionPattern"] = pattern_name

            # Stop scanning this story on first match
            break

    # Append audit entries to JSONL log
    if audit_entries:
        log_path = Path(audit_log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            for entry in audit_entries:
                fh.write(json.dumps(entry) + "\n")

    # Persist updated prd.json atomically
    if update_prd and blocked_ids:
        tmp = prd_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prd, indent=2), encoding="utf-8")
        os.replace(tmp, prd_file)

    return blocked_ids, audit_entries


# ── CLI ────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Scan prd.json stories for OWASP LLM01:2025 prompt injection patterns."
    )
    p.add_argument("--prd", default="prd.json", help="Path to prd.json")
    p.add_argument(
        "--audit-log",
        default=".spiral/security-audit.jsonl",
        help="Append WARN entries here (default: .spiral/security-audit.jsonl)",
    )
    p.add_argument(
        "--update-prd",
        action="store_true",
        help="Mark blocked stories as failed in prd.json",
    )
    p.add_argument(
        "--allow-unsafe",
        action="store_true",
        help="Log warnings but do not block stories (--allow-unsafe-stories equivalent)",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-error output",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()

    blocked, entries = scan_prd_stories(
        prd_path=args.prd,
        audit_log=args.audit_log,
        update_prd=args.update_prd,
        allow_unsafe=args.allow_unsafe,
    )

    if entries and not args.quiet:
        for e in entries:
            action_tag = "[WARN:unsafe-allowed]" if args.allow_unsafe else "[BLOCKED]"
            print(
                f"  [injection] {action_tag} {e['story_id']} — pattern: {e['pattern']}",
                file=sys.stderr,
            )

    if blocked and not args.quiet:
        print(
            f"  [injection] {len(blocked)} story/stories blocked: {', '.join(blocked)}",
            file=sys.stderr,
        )
        print(
            f"  [injection] Audit log: {args.audit_log}",
            file=sys.stderr,
        )

    # Exit 2 if stories were blocked (not --allow-unsafe), so caller can decide
    if blocked and not args.allow_unsafe:
        sys.exit(2)


if __name__ == "__main__":
    main()
