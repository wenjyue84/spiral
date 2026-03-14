#!/usr/bin/env python3
"""
SPIRAL — PRD Encoding Validator
Validates prd.json for non-UTF-8 bytes and control characters in string values.

Per RFC 8259 §8.1, JSON must be encoded in UTF-8. LLM-generated content can
embed null bytes, CRLF artefacts, or Word clipboard paste artefacts (smart
quotes embedded as Win-1252) that silently corrupt downstream parsing.

Exit codes:
  0 = clean
  1 = file/IO error (unreadable, not valid JSON)
  2 = encoding issues detected (and SANITIZE not set)

Usage:
  python lib/check_prd_encoding.py prd.json
  python lib/check_prd_encoding.py prd.json --sanitize   # strip + rewrite in-place
  python lib/check_prd_encoding.py prd.json --quiet      # suppress OK message

As module:
  from check_prd_encoding import check_encoding, sanitize_prd
  issues = check_encoding(prd_path)  # list of dicts
  clean  = sanitize_prd(prd_path)    # rewrites in-place, returns True on change
"""
import json
import os
import re
import sys
from typing import Any, Generator

# Control-character range: 0x00-0x08, 0x0B-0x0C, 0x0E-0x1F
# Deliberately allows 0x09 (tab), 0x0A (newline), 0x0D (carriage return)
# which are valid in JSON strings.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _walk_strings(obj: Any, path: str = "") -> Generator[tuple[str, str], None, None]:
    """Yield (path, value) for every string in the JSON tree."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{path}[{i}]")


def check_encoding(prd_path: str) -> list[dict]:
    """
    Return a list of issue dicts (empty = clean).

    Each issue dict has keys:
      path  – JSON field path (e.g. "userStories[2].description")
      char  – hex representation of the offending byte (e.g. "0x00")
      pos   – character index within the string value
    """
    raw: bytes
    try:
        with open(prd_path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise FileNotFoundError(f"Cannot open {prd_path}: {exc}") from exc

    # 1. UTF-8 validity
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"prd.json is not valid UTF-8 at byte offset {exc.start}: "
            f"0x{raw[exc.start]:02x}"
        ) from exc

    # 2. JSON parsability
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"prd.json JSON parse error: {exc}") from exc

    # 3. Control character scan
    issues: list[dict] = []
    for path, value in _walk_strings(data):
        for m in _CTRL_RE.finditer(value):
            issues.append({
                "path": path,
                "char": f"0x{ord(m.group()):02x}",
                "pos": m.start(),
            })
    return issues


def sanitize_prd(prd_path: str) -> bool:
    """
    Strip all control characters from every string value in prd.json.
    Rewrites the file in-place with 2-space indentation.
    Returns True if any change was made.
    """
    with open(prd_path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8")
    data = json.loads(text)

    changed = False

    def _strip(obj: Any) -> Any:
        nonlocal changed
        if isinstance(obj, str):
            cleaned = _CTRL_RE.sub("", obj)
            if cleaned != obj:
                changed = True
            return cleaned
        if isinstance(obj, dict):
            return {k: _strip(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_strip(v) for v in obj]
        return obj

    clean_data = _strip(data)
    if changed:
        with open(prd_path, "w", encoding="utf-8") as fh:
            json.dump(clean_data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    return changed


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Check prd.json for non-UTF-8 bytes and control characters."
    )
    parser.add_argument("prd_file", help="Path to prd.json")
    parser.add_argument(
        "--sanitize",
        action="store_true",
        help="Strip control characters in-place instead of aborting",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress success message",
    )
    args = parser.parse_args()

    try:
        issues = check_encoding(args.prd_file)
    except (FileNotFoundError, ValueError) as exc:
        print(f"  [encoding] FATAL: {exc}", file=sys.stderr)
        return 1

    if not issues:
        if not args.quiet:
            print("  [encoding] prd.json encoding: OK")
        return 0

    # Issues found
    if args.sanitize:
        changed = sanitize_prd(args.prd_file)
        if changed:
            print(
                f"  [encoding] WARNING: stripped {len(issues)} control character(s) "
                f"from prd.json (SPIRAL_SANITIZE_PRD=true)"
            )
        return 0

    # Hard-fail mode
    print(
        f"  [encoding] FATAL: {len(issues)} control character(s) found in prd.json:",
        file=sys.stderr,
    )
    for issue in issues:
        print(
            f"    path={issue['path']}  char={issue['char']}  pos={issue['pos']}",
            file=sys.stderr,
        )
    print(
        "  [encoding] Set SPIRAL_SANITIZE_PRD=true to auto-strip instead of aborting.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
