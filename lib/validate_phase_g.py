#!/usr/bin/env python3
"""lib/validate_phase_g.py — Phase G Output Validator (US-688).

Validates CHANGELOG.md schema compliance and pdoc HTML output structure
before Phase G commit. Logs failures to .spiral/_phase_g_validation.json.

Functions:
    validate_changelog_schema(changelog_path) -> dict
    validate_pdoc_html(pdoc_dir) -> dict
    validate_all_outputs(changelog_path, pdoc_dir, *, scratch_dir) -> bool
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Semver H2 heading: ## v1.2.3 (may have additional suffix)
_SEMVER_H2_RE = re.compile(r"^## v\d+\.\d+\.\d+")

# Full entry format: ## vX.Y.Z: <date or description>
_ENTRY_FORMAT_RE = re.compile(r"^## v\d+\.\d+\.\d+:")


# ── CHANGELOG validation ──────────────────────────────────────────────────────


def validate_changelog_schema(changelog_path: str | Path) -> dict[str, Any]:
    """Validate CHANGELOG.md schema compliance.

    Checks for:
    - H1 'Changelog' header (line exactly '# Changelog')
    - H2 version sections matching semver ('## v1.2.3...')
    - Entry format '## vX.Y.Z: Date' for all H2 version entries

    Returns dict with 'valid' (bool) and 'errors' (list[str]).
    """
    errors: list[str] = []
    path = Path(changelog_path)

    if not path.exists():
        return {"valid": False, "errors": [f"CHANGELOG.md not found: {changelog_path}"]}

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"valid": False, "errors": [f"Cannot read CHANGELOG.md: {exc}"]}

    lines = content.splitlines()

    # Check H1 'Changelog'
    has_h1 = any(line.strip() == "# Changelog" for line in lines)
    if not has_h1:
        errors.append("Missing H1 'Changelog' header (expected a line exactly '# Changelog')")

    # Collect H2 lines that look like version entries
    h2_lines = [line for line in lines if line.startswith("## ")]
    if not h2_lines:
        errors.append("No H2 version sections found (expected '## vX.Y.Z: Date')")
    else:
        for h2 in h2_lines:
            if not _SEMVER_H2_RE.match(h2):
                errors.append(f"H2 section does not match semver: {h2!r} (expected '## vX.Y.Z: ...')")
            elif not _ENTRY_FORMAT_RE.match(h2):
                errors.append(f"H2 entry missing date/description suffix: {h2!r} (expected '## vX.Y.Z: Date')")

    return {"valid": len(errors) == 0, "errors": errors}


# ── pdoc HTML validation ──────────────────────────────────────────────────────


def _has_module_docstring(html: str) -> bool:
    """Return True if HTML appears to contain a module docstring section."""
    # pdoc v3/v14 use section ids for module intro
    if 'id="section-intro"' in html or 'id="module-docstring"' in html:
        return True
    # Generic fallback: any non-empty paragraph
    return bool(re.search(r"<p>\s*\S", html, re.IGNORECASE))


def _count_functions(html: str) -> int:
    """Count function definitions visible in pdoc HTML.

    Counts <dt id="...">def ... anchors (pdoc3 pattern) first, excluding
    class entries. Falls back to counting 'def <name>' patterns in the text.
    """
    # pdoc3: <dt id="module.func_name">def func_name ...
    # Must contain 'def ' in the element text (excludes class entries)
    func_dts = re.findall(r'<dt\s[^>]*id="[^"]+"\s*>[^<]*def\s+\w+', html, re.IGNORECASE)
    if func_dts:
        return len(func_dts)
    # Fallback: raw 'def name(' patterns (e.g. in code blocks)
    return len(re.findall(r"\bdef\s+\w+\s*\(", html))


def _has_class_list(html: str) -> bool:
    """Return True if HTML contains at least one class definition."""
    # pdoc renders classes as <dt id="..."> with 'class ClassName'
    if re.search(r"\bclass\s+\w+", html):
        return True
    # Section header like <h2>Classes</h2>
    return bool(re.search(r"<h[1-6][^>]*>\s*[Cc]lasses?\s*</h[1-6]>", html))


def validate_pdoc_html(pdoc_dir: str | Path) -> dict[str, Any]:
    """Validate pdoc HTML output structure.

    Checks (across all non-index HTML files in pdoc_dir):
    - Valid HTML structure (<html> tag present)
    - Module docstring section exists
    - Function list contains >= 3 expected functions
    - Class list is present

    Returns dict with 'valid' (bool) and 'errors' (list[str]).
    """
    errors: list[str] = []
    directory = Path(pdoc_dir)

    if not directory.exists():
        return {"valid": False, "errors": [f"pdoc output directory not found: {pdoc_dir}"]}

    # Prefer module HTML files over index.html
    html_files = [f for f in directory.rglob("*.html") if f.name != "index.html"]
    if not html_files:
        html_files = list(directory.rglob("*.html"))
    if not html_files:
        return {"valid": False, "errors": ["No HTML files found in pdoc output directory"]}

    combined = ""
    for html_file in html_files:
        try:
            content = html_file.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{html_file.name}: cannot read: {exc}")
            continue

        if "<html" not in content.lower():
            errors.append(f"{html_file.name}: missing <html> tag (invalid HTML structure)")
            # Still accumulate content so other checks run
        combined += content

    if not combined:
        return {"valid": False, "errors": errors or ["No readable HTML content"]}

    # Module docstring
    if not _has_module_docstring(combined):
        errors.append("Module docstring section not found in pdoc HTML output")

    # Function list (>= 3)
    func_count = _count_functions(combined)
    if func_count < 3:
        errors.append(f"Function list has {func_count} function(s); expected >= 3")

    # Class list
    if not _has_class_list(combined):
        errors.append("Class list not found in pdoc HTML output")

    return {"valid": len(errors) == 0, "errors": errors}


# ── Combined validator ────────────────────────────────────────────────────────


def validate_all_outputs(
    changelog_path: str | Path,
    pdoc_dir: str | Path | None = None,
    *,
    scratch_dir: str | Path | None = None,
) -> bool:
    """Run all Phase G validations and log results.

    Calls validate_changelog_schema() and (if pdoc_dir is provided and exists)
    validate_pdoc_html(). Writes a structured report to
    <scratch_dir>/_phase_g_validation.json.

    Returns:
        True  — all validations passed (no errors logged).
        False — one or more validations failed; errors in the JSON report.
    """
    changelog_result = validate_changelog_schema(changelog_path)

    pdoc_result: dict[str, Any]
    if pdoc_dir is None or not Path(pdoc_dir).exists():
        pdoc_result = {"valid": True, "errors": [], "skipped": True}
    else:
        pdoc_result = validate_pdoc_html(pdoc_dir)

    all_valid: bool = bool(changelog_result["valid"]) and bool(pdoc_result["valid"])

    # Resolve scratch dir
    scratch = Path(scratch_dir) if scratch_dir is not None else Path(".spiral")
    scratch.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_valid": all_valid,
        "changelog": changelog_result,
        "pdoc": pdoc_result,
    }

    log_path = scratch / "_phase_g_validation.json"
    with open(log_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    if not all_valid:
        print(f"[phase-g] Validation FAILED — see {log_path}", file=sys.stderr)
        for err in changelog_result.get("errors", []):
            print(f"[phase-g]   CHANGELOG: {err}", file=sys.stderr)
        for err in pdoc_result.get("errors", []):
            print(f"[phase-g]   pdoc: {err}", file=sys.stderr)

    return all_valid


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate Phase G outputs (CHANGELOG.md schema + pdoc HTML).")
    parser.add_argument("--changelog", required=True, help="Path to CHANGELOG.md")
    parser.add_argument(
        "--pdoc-dir",
        default=None,
        help="Path to pdoc HTML output directory (optional)",
    )
    parser.add_argument(
        "--scratch-dir",
        default=".spiral",
        help="Scratch directory for validation log (default: .spiral)",
    )
    args = parser.parse_args()

    ok = validate_all_outputs(
        args.changelog,
        args.pdoc_dir,
        scratch_dir=args.scratch_dir,
    )
    sys.exit(0 if ok else 1)
