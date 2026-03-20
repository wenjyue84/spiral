"""Phase X: Repo Map / Symbol Map — structural context for Ralph workers.

Parses filesTouch files from pending stories and produces per-story markdown
summaries of exports, imports, test neighbors, callers, and dependency
boundaries.  Zero LLM cost — uses stdlib ast for .py and regex for .sh/.ts/.js.

Usage:
    python lib/context/repo_map.py --prd prd.json --output .spiral/_repo_map.json
    python lib/context/repo_map.py --prd prd.json --story-id US-500 --format md
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SymbolMap:
    """Symbols extracted from a single source file."""

    path: str
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    type_aliases: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)


@dataclass
class StoryMap:
    """Aggregated context for a single story."""

    story_id: str
    files: dict[str, SymbolMap] = field(default_factory=dict)
    test_neighbors: dict[str, list[str]] = field(default_factory=dict)
    callers: dict[str, list[str]] = field(default_factory=dict)
    boundaries: dict[str, str] = field(default_factory=dict)  # file -> "internal"|"external"


@dataclass
class RepoMapResult:
    """Result for all pending stories."""

    stories: dict[str, StoryMap] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_python_file(path: str) -> SymbolMap:
    """Parse a Python file using stdlib ast."""
    sm = SymbolMap(path=path)
    try:
        source = Path(path).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=path)
    except (SyntaxError, OSError):
        return sm

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            sm.functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            sm.classes.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                sm.imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                sm.imports.append(f"{module}.{alias.name}")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    sm.variables.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id[0].isupper():
                sm.type_aliases.append(node.target.id)
    # In Python, all top-level names are implicitly exports
    sm.exports = sm.functions + sm.classes + sm.variables + sm.type_aliases
    return sm


_SH_FUNC_RE = re.compile(r"^\s*(?:function\s+)?(\w+)\s*\(\s*\)", re.MULTILINE)
_SH_SOURCE_RE = re.compile(r'(?:source|\.)\s+["\']?([^"\';\s]+)', re.MULTILINE)
_SH_EXPORT_RE = re.compile(r"^export\s+(\w+)=", re.MULTILINE)


def parse_shell_file(path: str) -> SymbolMap:
    """Parse a shell file using regex."""
    sm = SymbolMap(path=path)
    try:
        source = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return sm

    sm.functions = _SH_FUNC_RE.findall(source)
    sm.imports = _SH_SOURCE_RE.findall(source)
    sm.variables = _SH_EXPORT_RE.findall(source)
    sm.exports = sm.functions + sm.variables
    return sm


_TS_EXPORT_RE = re.compile(
    r"^export\s+(?:default\s+)?(?:function|class|const|let|var|type|interface|enum)\s+(\w+)",
    re.MULTILINE,
)
_TS_IMPORT_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""", re.MULTILINE)


def parse_ts_js_file(path: str) -> SymbolMap:
    """Parse a TypeScript/JavaScript file using regex."""
    sm = SymbolMap(path=path)
    try:
        source = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return sm

    sm.exports = _TS_EXPORT_RE.findall(source)
    sm.imports = _TS_IMPORT_RE.findall(source)
    # Treat exports as both functions and exports for simplicity
    sm.functions = sm.exports[:]
    return sm


_EXTENSION_PARSERS: dict[str, Any] = {
    ".py": parse_python_file,
    ".sh": parse_shell_file,
    ".bash": parse_shell_file,
    ".ts": parse_ts_js_file,
    ".tsx": parse_ts_js_file,
    ".js": parse_ts_js_file,
    ".jsx": parse_ts_js_file,
    ".mjs": parse_ts_js_file,
}


def parse_file(path: str) -> SymbolMap:
    """Dispatch to the right parser by extension. Returns empty SymbolMap for unsupported."""
    ext = Path(path).suffix.lower()
    parser = _EXTENSION_PARSERS.get(ext)
    if parser is None:
        return SymbolMap(path=path)
    return parser(path)


# ---------------------------------------------------------------------------
# Neighbor / caller / boundary helpers
# ---------------------------------------------------------------------------


def find_test_neighbors(path: str, repo_root: str) -> list[str]:
    """Heuristic: find test files that likely cover *path*."""
    stem = Path(path).stem
    repo = Path(repo_root)
    candidates: list[str] = []

    # Python: tests/test_<stem>.py
    py_test = repo / "tests" / f"test_{stem}.py"
    if py_test.exists():
        candidates.append(str(py_test.relative_to(repo)))

    # TS/JS: __tests__/<stem>.test.ts, <stem>.test.ts, <stem>.spec.ts
    for pattern in [
        f"__tests__/{stem}.test.ts",
        f"__tests__/{stem}.test.js",
        f"{stem}.test.ts",
        f"{stem}.test.js",
        f"{stem}.spec.ts",
        f"{stem}.spec.js",
    ]:
        for hit in repo.rglob(pattern):
            rel = str(hit.relative_to(repo))
            if rel not in candidates:
                candidates.append(rel)

    # Bats: tests/<stem>.bats, tests/test_<stem>.bats
    for bname in [f"tests/{stem}.bats", f"tests/test_{stem}.bats"]:
        bp = repo / bname
        if bp.exists() and bname not in candidates:
            candidates.append(bname)

    return candidates


def find_callers(path: str, repo_root: str, all_files: list[str], *, cap: int = 10) -> list[str]:
    """String-match import patterns across repo files to find callers of *path*."""
    stem = Path(path).stem
    rel = str(Path(path).relative_to(repo_root)).replace("\\", "/") if os.path.isabs(path) else path.replace("\\", "/")
    # Build patterns to search for
    patterns: list[str] = []
    # Python: "from lib.foo import" or "import lib.foo"
    dotted = rel.replace("/", ".").replace(".py", "")
    patterns.append(dotted)
    # JS/TS: import from "./foo" or "../foo"
    patterns.append(stem)

    callers: list[str] = []
    for f in all_files:
        if f == path or f == rel:
            continue
        try:
            content = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat in patterns:
            if pat in content:
                f_rel = (
                    str(Path(f).relative_to(repo_root)).replace("\\", "/") if os.path.isabs(f) else f.replace("\\", "/")
                )
                if f_rel not in callers:
                    callers.append(f_rel)
                break
        if len(callers) >= cap:
            break
    return callers


def classify_boundary(
    files_to_touch: list[str],
    file_imports: list[str],
) -> dict[str, str]:
    """Classify each import as internal (in filesTouch) or external."""
    touch_set = {f.replace("\\", "/") for f in files_to_touch}
    # Build stems for matching: "lib/foo.py" -> "lib/foo", "lib.foo"
    touch_stems: set[str] = set()
    for f in touch_set:
        no_ext = f.rsplit(".", 1)[0] if "." in f else f
        touch_stems.add(no_ext)  # lib/foo
        touch_stems.add(no_ext.replace("/", "."))  # lib.foo

    result: dict[str, str] = {}
    for imp in file_imports:
        # Check if any prefix of the dotted import matches a file stem
        # e.g. "lib.foo.helper" -> check "lib.foo.helper", "lib.foo", "lib"
        parts = imp.split(".")
        is_internal = False
        for i in range(len(parts), 0, -1):
            prefix = ".".join(parts[:i])
            if prefix in touch_stems:
                is_internal = True
                break
        result[imp] = "internal" if is_internal else "external"
    return result


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _collect_source_files(repo_root: str) -> list[str]:
    """Collect all parseable source files in the repo."""
    supported = set(_EXTENSION_PARSERS.keys())
    files: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(repo_root):
        # Skip hidden dirs, node_modules, .git, etc.
        rel_dir = os.path.relpath(dirpath, repo_root)
        if any(part.startswith(".") or part == "node_modules" for part in rel_dir.split(os.sep)):
            continue
        for fn in filenames:
            if Path(fn).suffix.lower() in supported:
                files.append(os.path.join(dirpath, fn))
    return files


def build_story_map(
    story: dict[str, Any],
    repo_root: str,
    all_files: list[str],
    max_lines: int = 150,
) -> StoryMap:
    """Build context map for a single story."""
    story_id: str = story.get("id", "unknown")
    files_to_touch: list[str] = story.get("filesTouch", [])
    sm = StoryMap(story_id=story_id)

    all_imports: list[str] = []
    for rel_path in files_to_touch[:max_lines]:  # cap to avoid runaway
        abs_path = os.path.join(repo_root, rel_path)
        if not os.path.isfile(abs_path):
            continue
        symbol_map = parse_file(abs_path)
        sm.files[rel_path] = symbol_map
        all_imports.extend(symbol_map.imports)
        sm.test_neighbors[rel_path] = find_test_neighbors(abs_path, repo_root)
        sm.callers[rel_path] = find_callers(abs_path, repo_root, all_files)

    sm.boundaries = classify_boundary(files_to_touch, all_imports)
    return sm


def build_repo_map(
    prd_path: str,
    repo_root: str,
    max_lines: int = 150,
) -> RepoMapResult:
    """Build context maps for all pending stories in prd.json."""
    with open(prd_path, encoding="utf-8") as f:
        prd = json.load(f)

    all_files = _collect_source_files(repo_root)
    result = RepoMapResult()

    for story in prd.get("userStories", []):
        if story.get("passes") or story.get("_decomposed"):
            continue
        status = story.get("status", "pending")
        if status in ("skipped", "gave_up"):
            continue
        story_map = build_story_map(story, repo_root, all_files, max_lines)
        result.stories[story_map.story_id] = story_map

    return result


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


def _symbol_map_to_dict(sm: SymbolMap) -> dict[str, Any]:
    return {
        "path": sm.path,
        "functions": sm.functions,
        "classes": sm.classes,
        "imports": sm.imports,
        "exports": sm.exports,
        "type_aliases": sm.type_aliases,
        "variables": sm.variables,
    }


def _story_map_to_dict(sm: StoryMap) -> dict[str, Any]:
    return {
        "story_id": sm.story_id,
        "files": {k: _symbol_map_to_dict(v) for k, v in sm.files.items()},
        "test_neighbors": sm.test_neighbors,
        "callers": sm.callers,
        "boundaries": sm.boundaries,
    }


def format_story_map_markdown(story_map: StoryMap) -> str:
    """Format a StoryMap as compact markdown for prompt injection."""
    lines: list[str] = []
    lines.append(f"## Symbol Map — {story_map.story_id}\n")

    for rel_path, sm in story_map.files.items():
        lines.append(f"### `{rel_path}`")

        if sm.functions:
            lines.append(f"**Functions:** {', '.join(sm.functions[:20])}")
        if sm.classes:
            lines.append(f"**Classes:** {', '.join(sm.classes[:20])}")
        if sm.exports:
            lines.append(f"**Exports:** {', '.join(sm.exports[:20])}")
        if sm.imports:
            # Show only unique, deduplicated imports
            unique_imports = list(dict.fromkeys(sm.imports))[:15]
            lines.append(f"**Imports:** {', '.join(unique_imports)}")
        if sm.type_aliases:
            lines.append(f"**Type aliases:** {', '.join(sm.type_aliases[:10])}")
        if sm.variables:
            lines.append(f"**Variables:** {', '.join(sm.variables[:10])}")

        # Test neighbors
        neighbors = story_map.test_neighbors.get(rel_path, [])
        if neighbors:
            lines.append(f"**Test files:** {', '.join(neighbors)}")

        # Callers
        callers = story_map.callers.get(rel_path, [])
        if callers:
            lines.append(f"**Called by:** {', '.join(callers[:5])}")

        lines.append("")  # blank line between files

    # Boundary summary
    if story_map.boundaries:
        internal = [k for k, v in story_map.boundaries.items() if v == "internal"]
        external = [k for k, v in story_map.boundaries.items() if v == "external"]
        if internal:
            lines.append(f"**Internal deps (in filesTouch):** {', '.join(internal[:10])}")
        if external:
            lines.append(f"**External deps:** {', '.join(external[:10])}")

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase X: build repo symbol map for pending stories")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--output", default=".spiral/_repo_map.json", help="Output JSON path")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument("--max-lines", type=int, default=150, help="Max files to process per story")
    parser.add_argument("--story-id", default=None, help="Build map for a single story only")
    parser.add_argument("--format", choices=["json", "md"], default="json", help="Output format")
    args = parser.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    prd_path = os.path.abspath(args.prd)

    if args.story_id:
        # Single-story mode
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
        story = next(
            (s for s in prd.get("userStories", []) if s.get("id") == args.story_id),
            None,
        )
        if story is None:
            print(f"Story {args.story_id} not found in {prd_path}", file=sys.stderr)
            sys.exit(1)
        all_files = _collect_source_files(repo_root)
        sm = build_story_map(story, repo_root, all_files, args.max_lines)
        if args.format == "md":
            print(format_story_map_markdown(sm))
        else:
            print(json.dumps(_story_map_to_dict(sm), indent=2))
        return

    # Full build
    result = build_repo_map(prd_path, repo_root, args.max_lines)

    # Write JSON
    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    out_dict = {sid: _story_map_to_dict(sm) for sid, sm in result.stories.items()}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(out_dict, f, indent=2)
    print(f"  [X] Repo map written: {len(result.stories)} stories -> {output_path}")

    # Write per-story markdown files
    out_dir = os.path.dirname(output_path)
    for sid, sm in result.stories.items():
        md_path = os.path.join(out_dir, f"_repo_map_{sid}.md")
        md_content = format_story_map_markdown(sm)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

    print(f"  [X] Per-story markdown files written to {out_dir}/")


if __name__ == "__main__":
    main()
