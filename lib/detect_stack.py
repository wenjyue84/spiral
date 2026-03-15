"""lib/detect_stack.py — Tech stack auto-detection for SPIRAL Phase 0.

Scans a project root directory for indicator files and returns a structured
dict of detected values including the language, test command, and package
manager. Results are cached in .spiral/detected_stack.json.

Priority order (highest to lowest):
  pyproject.toml | setup.py  → Python
  package.json               → Node.js
  Cargo.toml                 → Rust
  go.mod                     → Go
  Makefile                   → Make (generic fallback)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Stack definitions: ordered by priority (first match wins).
# Each entry: (indicator_files, lang, validate_cmd, package_manager)
# ---------------------------------------------------------------------------
_STACK_DEFS: list[tuple[list[str], str, str, str]] = [
    (
        ["pyproject.toml", "setup.py"],
        "Python",
        "uv run pytest",
        "uv",
    ),
    (
        ["package.json"],
        "Node.js",
        "npm test",
        "npm",
    ),
    (
        ["Cargo.toml"],
        "Rust",
        "cargo test",
        "cargo",
    ),
    (
        ["go.mod"],
        "Go",
        "go test ./...",
        "go",
    ),
    (
        ["Makefile"],
        "Make",
        "make test",
        "make",
    ),
]

StackResult = dict[str, Any]


def detect_stack(project_root: str | Path | None = None) -> StackResult:
    """Detect the tech stack in *project_root* (defaults to cwd).

    Returns a dict with keys:
        language          str   — detected language name ("Python", "Node.js", …)
        validate_cmd      str   — suggested SPIRAL_VALIDATE_CMD
        package_manager   str   — detected package manager
        indicator_file    str   — the file that triggered detection
        detected          bool  — True if a stack was found, False if only defaults
    """
    root = Path(project_root or os.environ.get("SPIRAL_PROJECT_ROOT", ".")).resolve()

    for indicators, lang, validate_cmd, pkg_mgr in _STACK_DEFS:
        for indicator in indicators:
            if (root / indicator).exists():
                return {
                    "language": lang,
                    "validate_cmd": validate_cmd,
                    "package_manager": pkg_mgr,
                    "indicator_file": indicator,
                    "detected": True,
                    "project_root": str(root),
                }

    # No indicator found — return safe defaults
    return {
        "language": "Unknown",
        "validate_cmd": "python tests/run_tests.py --report-dir test-reports",
        "package_manager": "unknown",
        "indicator_file": "",
        "detected": False,
        "project_root": str(root),
    }


def load_or_detect(
    project_root: str | Path | None = None,
    cache_dir: str | Path | None = None,
) -> StackResult:
    """Return cached stack result, or detect and cache it.

    Cache file: <cache_dir>/detected_stack.json  (default: .spiral/)
    Cache is invalidated if the project_root changes or the cache is missing.
    """
    root = Path(project_root or os.environ.get("SPIRAL_PROJECT_ROOT", ".")).resolve()
    scratch = Path(cache_dir or ".spiral")
    cache_file = scratch / "detected_stack.json"

    # Try to load from cache
    if cache_file.exists():
        try:
            cached: StackResult = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("project_root") == str(root):
                return cached
        except (json.JSONDecodeError, OSError):
            pass

    # Detect and persist
    result = detect_stack(root)
    try:
        scratch.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, indent=2), encoding="utf-8")
        tmp.replace(cache_file)
    except OSError:
        pass  # Best-effort cache write

    return result


def format_summary(result: StackResult) -> str:
    """Return a human-readable summary line for wizard display."""
    if not result.get("detected"):
        return "  │  [detect] No indicator file found — using generic defaults"
    lang = result["language"]
    indicator = result["indicator_file"]
    validate_cmd = result["validate_cmd"]
    pkg = result["package_manager"]
    return (
        f"  │  [detect] {lang} project detected ({indicator})\n"
        f"  │           Package manager : {pkg}\n"
        f"  │           Suggested cmd   : {validate_cmd}"
    )


# ---------------------------------------------------------------------------
# CLI entry point — callable from bash:
#   python lib/detect_stack.py [--root PATH] [--cache-dir DIR] [--json]
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Detect project tech stack.")
    parser.add_argument("--root", default=None, help="Project root (default: cwd / SPIRAL_PROJECT_ROOT)")
    parser.add_argument("--cache-dir", default=".spiral", help="Cache directory (default: .spiral)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of human summary")
    parser.add_argument("--no-cache", action="store_true", help="Skip cache, always re-detect")
    args = parser.parse_args()

    if args.no_cache:
        result = detect_stack(args.root)
    else:
        result = load_or_detect(args.root, args.cache_dir)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_summary(result))
        if result.get("detected"):
            # Emit shell-eval-friendly lines for sourcing in bash
            sys.stdout.write(f"\n__DETECTED_LANG={result['language']}\n")
            sys.stdout.write(f"__DETECTED_VALIDATE_CMD={result['validate_cmd']}\n")
            sys.stdout.write(f"__DETECTED_PKG_MGR={result['package_manager']}\n")


if __name__ == "__main__":
    _cli()
