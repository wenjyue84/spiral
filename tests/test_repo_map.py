"""Tests for lib/context/repo_map.py — Phase X symbol map builder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lib.context.repo_map import (
    build_repo_map,
    build_story_map,
    classify_boundary,
    find_callers,
    find_test_neighbors,
    format_story_map_markdown,
    parse_file,
    parse_python_file,
    parse_shell_file,
    parse_ts_js_file,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Create a minimal repo layout for testing."""
    (tmp_path / "lib").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src").mkdir()
    return tmp_path


def _write(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# TestParsePythonFile
# ---------------------------------------------------------------------------


class TestParsePythonFile:
    def test_basic_extraction(self, repo: Path) -> None:
        src = _write(
            repo / "lib" / "foo.py",
            """\
import os
from pathlib import Path

MAX_RETRIES = 3

class FooHandler:
    pass

def do_something():
    pass

async def do_async():
    pass
""",
        )
        sm = parse_python_file(src)
        assert sm.path == src
        assert "do_something" in sm.functions
        assert "do_async" in sm.functions
        assert "FooHandler" in sm.classes
        assert "os" in sm.imports
        assert "pathlib.Path" in sm.imports
        assert "MAX_RETRIES" in sm.variables
        # Exports include all top-level symbols
        assert "do_something" in sm.exports
        assert "FooHandler" in sm.exports

    def test_syntax_error_returns_empty(self, repo: Path) -> None:
        src = _write(repo / "bad.py", "def broken(:\n  pass")
        sm = parse_python_file(src)
        assert sm.functions == []
        assert sm.classes == []

    def test_nonexistent_file(self) -> None:
        sm = parse_python_file("/nonexistent/path.py")
        assert sm.functions == []


# ---------------------------------------------------------------------------
# TestParseShellFile
# ---------------------------------------------------------------------------


class TestParseShellFile:
    def test_function_detection(self, repo: Path) -> None:
        src = _write(
            repo / "lib" / "helper.sh",
            """\
#!/bin/bash
export MY_VAR=42

run_phase() {
  echo "running"
}

function cleanup() {
  echo "cleanup"
}

source "$HOME/lib/utils.sh"
. ./other.sh
""",
        )
        sm = parse_shell_file(src)
        assert "run_phase" in sm.functions
        assert "cleanup" in sm.functions
        assert "MY_VAR" in sm.variables
        assert len(sm.imports) == 2  # utils.sh and other.sh
        assert "run_phase" in sm.exports
        assert "MY_VAR" in sm.exports

    def test_nonexistent_file(self) -> None:
        sm = parse_shell_file("/nonexistent/script.sh")
        assert sm.functions == []


# ---------------------------------------------------------------------------
# TestParseTsJsFile
# ---------------------------------------------------------------------------


class TestParseTsJsFile:
    def test_exports_and_imports(self, repo: Path) -> None:
        src = _write(
            repo / "src" / "app.ts",
            """\
import { useState } from 'react'
import type { Config } from './types'

export function App() {
  return null
}

export const API_URL = "http://localhost"

export default class MainApp {}

export interface AppConfig {
  name: string
}

export type Status = 'ok' | 'err'
""",
        )
        sm = parse_ts_js_file(src)
        assert "App" in sm.exports
        assert "API_URL" in sm.exports
        assert "MainApp" in sm.exports
        assert "AppConfig" in sm.exports
        assert "Status" in sm.exports
        assert "react" in sm.imports
        assert "./types" in sm.imports

    def test_nonexistent_file(self) -> None:
        sm = parse_ts_js_file("/nonexistent/app.ts")
        assert sm.exports == []


# ---------------------------------------------------------------------------
# TestParseFile
# ---------------------------------------------------------------------------


class TestParseFile:
    def test_dispatch_python(self, repo: Path) -> None:
        src = _write(repo / "mod.py", "def hello(): pass")
        sm = parse_file(src)
        assert "hello" in sm.functions

    def test_dispatch_shell(self, repo: Path) -> None:
        src = _write(repo / "run.sh", "run_it() { echo hi; }")
        sm = parse_file(src)
        assert "run_it" in sm.functions

    def test_dispatch_ts(self, repo: Path) -> None:
        src = _write(repo / "index.ts", "export function greet() {}")
        sm = parse_file(src)
        assert "greet" in sm.exports

    def test_unsupported_extension(self, repo: Path) -> None:
        src = _write(repo / "data.json", '{"key": "value"}')
        sm = parse_file(src)
        assert sm.functions == []
        assert sm.exports == []


# ---------------------------------------------------------------------------
# TestFindTestNeighbors
# ---------------------------------------------------------------------------


class TestFindTestNeighbors:
    def test_python_test_neighbor(self, repo: Path) -> None:
        _write(repo / "lib" / "merge.py", "def merge(): pass")
        _write(repo / "tests" / "test_merge.py", "def test_merge(): pass")
        neighbors = find_test_neighbors(str(repo / "lib" / "merge.py"), str(repo))
        assert any("test_merge.py" in n for n in neighbors)

    def test_ts_test_neighbor(self, repo: Path) -> None:
        _write(repo / "src" / "utils.ts", "export function foo() {}")
        _write(repo / "src" / "__tests__" / "utils.test.ts", "test('foo', () => {})")
        neighbors = find_test_neighbors(str(repo / "src" / "utils.ts"), str(repo))
        assert any("utils.test.ts" in n for n in neighbors)

    def test_no_neighbors(self, repo: Path) -> None:
        _write(repo / "lib" / "orphan.py", "x = 1")
        neighbors = find_test_neighbors(str(repo / "lib" / "orphan.py"), str(repo))
        assert neighbors == []


# ---------------------------------------------------------------------------
# TestFindCallers
# ---------------------------------------------------------------------------


class TestFindCallers:
    def test_python_callers(self, repo: Path) -> None:
        target = _write(repo / "lib" / "utils.py", "def helper(): pass")
        caller = _write(repo / "lib" / "main.py", "from lib.utils import helper\nhelper()")
        callers = find_callers(target, str(repo), [caller, target])
        assert len(callers) >= 1

    def test_cap_applied(self, repo: Path) -> None:
        target = _write(repo / "lib" / "popular.py", "def api(): pass")
        callers_files = []
        for i in range(15):
            f = _write(repo / "lib" / f"caller_{i}.py", "import popular")
            callers_files.append(f)
        result = find_callers(target, str(repo), callers_files + [target], cap=5)
        assert len(result) <= 5


# ---------------------------------------------------------------------------
# TestClassifyBoundary
# ---------------------------------------------------------------------------


class TestClassifyBoundary:
    def test_internal_and_external(self) -> None:
        files_to_touch = ["lib/foo.py", "lib/bar.py"]
        imports = ["lib.foo.helper", "os.path", "json"]
        result = classify_boundary(files_to_touch, imports)
        assert result["lib.foo.helper"] == "internal"
        assert result["os.path"] == "external"
        assert result["json"] == "external"

    def test_empty_inputs(self) -> None:
        assert classify_boundary([], []) == {}


# ---------------------------------------------------------------------------
# TestBuildStoryMap
# ---------------------------------------------------------------------------


class TestBuildStoryMap:
    def test_basic_build(self, repo: Path) -> None:
        _write(
            repo / "lib" / "worker.py",
            """\
import os
def run_worker():
    pass
class Worker:
    pass
""",
        )
        _write(repo / "tests" / "test_worker.py", "def test_worker(): pass")
        story: dict[str, Any] = {
            "id": "US-100",
            "filesTouch": ["lib/worker.py"],
        }
        all_files = [str(repo / "lib" / "worker.py"), str(repo / "tests" / "test_worker.py")]
        sm = build_story_map(story, str(repo), all_files)
        assert sm.story_id == "US-100"
        assert "lib/worker.py" in sm.files
        assert "run_worker" in sm.files["lib/worker.py"].functions
        assert any("test_worker.py" in n for n in sm.test_neighbors.get("lib/worker.py", []))

    def test_missing_file(self, repo: Path) -> None:
        story: dict[str, Any] = {
            "id": "US-999",
            "filesTouch": ["lib/nonexistent.py"],
        }
        sm = build_story_map(story, str(repo), [])
        assert sm.story_id == "US-999"
        assert sm.files == {}


# ---------------------------------------------------------------------------
# TestFormatStoryMapMarkdown
# ---------------------------------------------------------------------------


class TestFormatStoryMapMarkdown:
    def test_basic_format(self, repo: Path) -> None:
        _write(repo / "lib" / "foo.py", "def bar(): pass\ndef baz(): pass")
        story: dict[str, Any] = {
            "id": "US-200",
            "filesTouch": ["lib/foo.py"],
        }
        sm = build_story_map(story, str(repo), [str(repo / "lib" / "foo.py")])
        md = format_story_map_markdown(sm)
        assert "## Symbol Map — US-200" in md
        assert "`lib/foo.py`" in md
        assert "bar" in md
        assert "baz" in md

    def test_empty_story(self) -> None:
        from lib.context.repo_map import StoryMap

        sm = StoryMap(story_id="US-EMPTY")
        md = format_story_map_markdown(sm)
        assert "US-EMPTY" in md


# ---------------------------------------------------------------------------
# TestCLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_full_build(self, repo: Path) -> None:
        _write(repo / "lib" / "mod.py", "def func(): pass")
        prd = {
            "userStories": [
                {"id": "US-001", "passes": False, "filesTouch": ["lib/mod.py"]},
                {"id": "US-002", "passes": True, "filesTouch": ["lib/mod.py"]},
            ]
        }
        prd_path = repo / "prd.json"
        prd_path.write_text(json.dumps(prd), encoding="utf-8")

        result = build_repo_map(str(prd_path), str(repo))
        assert "US-001" in result.stories
        assert "US-002" not in result.stories  # passed, should be skipped

    def test_single_story_mode(self, repo: Path) -> None:
        _write(repo / "lib" / "mod.py", "def func(): pass")
        prd = {
            "userStories": [
                {"id": "US-050", "passes": False, "filesTouch": ["lib/mod.py"]},
            ]
        }
        prd_path = repo / "prd.json"
        prd_path.write_text(json.dumps(prd), encoding="utf-8")

        # Use build_story_map directly for single-story
        from lib.context.repo_map import _collect_source_files

        all_files = _collect_source_files(str(repo))
        story = prd["userStories"][0]
        sm = build_story_map(story, str(repo), all_files)
        assert sm.story_id == "US-050"
