"""Infer filesTouch from story text fields via static analysis.

Parses story title, description, and acceptanceCriteria for file/module
references and resolves them against a repo_map symbol index.  Writes
inferred files back into stories' filesTouch (tagged _inferred) so
partition_prd.py can use them for co-location.

Usage:
    # Enrich a prd.json in-place (reads .spiral/_repo_map.json for symbols)
    python lib/prd/infer_files_to_touch.py --prd prd.json \
        --repo-map .spiral/_repo_map.json --repo-root .

    # Dry-run (print inferred files without modifying prd.json)
    python lib/prd/infer_files_to_touch.py --prd prd.json \
        --repo-map .spiral/_repo_map.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

# Matches file-like references: foo.py, lib/bar.sh, src/components/Baz.tsx
_FILE_REF_RE = re.compile(
    r"""(?:^|[\s'"`(,])"""  # preceded by whitespace or delimiter
    r"""((?:[\w./-]+/)?"""  # optional directory prefix
    r"""[\w.-]+"""  # filename stem (may contain dots, e.g. prd.schema)
    r"""\.(?:py|sh|ts|tsx|js|jsx|mjs|json|toml|yaml|yml|cfg|sql|bats))"""  # extension
    r"""(?=[\s'"`),;:]|$)""",  # followed by delimiter or end
)

# Matches function/class references: foo_bar(), FooBar, FOO_BAR
_SYMBOL_REF_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9]+(?:[A-Z][a-z]+)+)\b"  # PascalCase class names
    r"|\b([a-z_][a-z0-9_]{2,})\s*\("  # function calls: foo_bar(
)


def extract_text_fields(story: dict[str, Any]) -> str:
    """Concatenate all text fields from a story for analysis."""
    parts: list[str] = []
    for key in ("title", "description", "narrative"):
        val = story.get(key, "")
        if isinstance(val, str):
            parts.append(val)
    ac = story.get("acceptanceCriteria", [])
    if isinstance(ac, list):
        for item in ac:
            if isinstance(item, str):
                parts.append(item)
    hints = story.get("technicalHints", {})
    if isinstance(hints, dict):
        for key in ("approach", "notes"):
            val = hints.get(key, "")
            if isinstance(val, str):
                parts.append(val)
    return "\n".join(parts)


def extract_file_refs(text: str) -> set[str]:
    """Extract explicit file path references from story text."""
    refs: set[str] = set()
    for m in _FILE_REF_RE.finditer(text):
        ref = m.group(1).replace("\\", "/")
        refs.add(ref)
    return refs


def extract_symbol_refs(text: str) -> set[str]:
    """Extract function/class name references from story text."""
    symbols: set[str] = set()
    for m in _SYMBOL_REF_RE.finditer(text):
        sym = m.group(1) or m.group(2)
        if sym:
            symbols.add(sym)
    return symbols


# ---------------------------------------------------------------------------
# Symbol index resolution
# ---------------------------------------------------------------------------


def build_symbol_to_files(repo_map: dict[str, Any]) -> dict[str, set[str]]:
    """Build a reverse index: symbol_name -> set of file paths.

    repo_map format: { story_id: { files: { path: { functions, classes, exports, ... } } } }
    """
    index: dict[str, set[str]] = {}
    for _story_id, story_data in repo_map.items():
        files = story_data.get("files", {})
        for fpath, syms in files.items():
            for key in ("functions", "classes", "exports", "variables"):
                for name in syms.get(key, []):
                    index.setdefault(name, set()).add(fpath)
    return index


def scan_repo_files(repo_root: str) -> set[str]:
    """Collect all source file relative paths from repo root."""
    supported = {".py", ".sh", ".bash", ".ts", ".tsx", ".js", ".jsx", ".mjs"}
    files: set[str] = set()
    for dirpath, _dirs, filenames in os.walk(repo_root):
        rel_dir = os.path.relpath(dirpath, repo_root)
        if any(part.startswith(".") or part == "node_modules" for part in rel_dir.split(os.sep)):
            continue
        for fn in filenames:
            if Path(fn).suffix.lower() in supported:
                rel = os.path.relpath(os.path.join(dirpath, fn), repo_root).replace("\\", "/")
                files.add(rel)
    return files


def resolve_file_refs(
    file_refs: set[str],
    repo_files: set[str],
) -> set[str]:
    """Resolve partial file references against actual repo files.

    Handles both exact matches and basename matches (e.g., "foo.py" matches "lib/foo.py").
    """
    resolved: set[str] = set()
    basename_index: dict[str, list[str]] = {}
    for rf in repo_files:
        bn = rf.rsplit("/", 1)[-1]
        basename_index.setdefault(bn, []).append(rf)

    for ref in file_refs:
        ref_norm = ref.replace("\\", "/")
        if ref_norm in repo_files:
            resolved.add(ref_norm)
        else:
            bn = ref_norm.rsplit("/", 1)[-1]
            matches = basename_index.get(bn, [])
            if len(matches) == 1:
                resolved.add(matches[0])
            elif len(matches) > 1:
                # Prefer matches that end with the reference path
                for m in matches:
                    if m.endswith(ref_norm):
                        resolved.add(m)
                        break
    return resolved


# ---------------------------------------------------------------------------
# Main inference
# ---------------------------------------------------------------------------


def infer_files(
    story: dict[str, Any],
    repo_map: dict[str, Any] | None = None,
    repo_root: str = ".",
    repo_files: set[str] | None = None,
) -> set[str]:
    """Infer filesTouch for a single story.

    Returns a set of resolved file paths (relative to repo_root).
    """
    text = extract_text_fields(story)
    if not text.strip():
        return set()

    # 1. Extract explicit file references from text
    file_refs = extract_file_refs(text)

    # 2. Resolve file references against repo
    if repo_files is None:
        repo_files = scan_repo_files(repo_root)
    resolved = resolve_file_refs(file_refs, repo_files)

    # 3. Extract symbol references and resolve via repo_map
    if repo_map:
        symbol_index = build_symbol_to_files(repo_map)
        symbol_refs = extract_symbol_refs(text)
        for sym in symbol_refs:
            if sym in symbol_index:
                resolved.update(symbol_index[sym])

    return resolved


def enrich_prd(
    prd_path: str,
    repo_map_path: str | None = None,
    repo_root: str = ".",
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Enrich all pending stories in prd.json with inferred filesTouch.

    Returns a dict of {story_id: [inferred_files]} for reporting.
    """
    with open(prd_path, encoding="utf-8") as f:
        prd = json.load(f)

    repo_map: dict[str, Any] | None = None
    if repo_map_path and os.path.isfile(repo_map_path):
        with open(repo_map_path, encoding="utf-8") as f:
            repo_map = json.load(f)

    repo_files = scan_repo_files(repo_root)
    enriched: dict[str, list[str]] = {}

    for story in prd.get("userStories", []):
        if story.get("passes") or story.get("_decomposed") or story.get("_skipped"):
            continue

        existing = set(story.get("filesTouch", []))
        inferred = infer_files(story, repo_map, repo_root, repo_files)

        # Only add truly new files
        new_files = inferred - existing
        if new_files:
            story.setdefault("filesTouch", [])
            story["filesTouch"].extend(sorted(new_files))
            story["_inferredFiles"] = sorted(new_files)
            enriched[story["id"]] = sorted(new_files)

    if not dry_run and enriched:
        tmp = prd_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(prd, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, prd_path)

    return enriched


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Infer filesTouch for SPIRAL stories")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--repo-map", default=None, help="Path to .spiral/_repo_map.json")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument("--dry-run", action="store_true", help="Print inferred files without modifying prd.json")
    args = parser.parse_args()

    enriched = enrich_prd(args.prd, args.repo_map, args.repo_root, args.dry_run)
    if enriched:
        total = sum(len(v) for v in enriched.values())
        print(f"[infer-files] Enriched {len(enriched)} stories with {total} inferred file(s)")
        for sid, files in enriched.items():
            print(f"  {sid}: +{len(files)} files ({', '.join(files[:5])}{'...' if len(files) > 5 else ''})")
    else:
        print("[infer-files] No new files inferred")

    if args.dry_run:
        print("[infer-files] Dry run — prd.json not modified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
