"""Unit tests for lib/detect_stack.py (US-301)."""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from detect_stack import detect_stack, load_or_detect, format_summary


# ---------------------------------------------------------------------------
# detect_stack — core detection
# ---------------------------------------------------------------------------

class TestDetectStackPython:
    def test_pyproject_toml(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        result = detect_stack(tmp_path)
        assert result["language"] == "Python"
        assert "pytest" in result["validate_cmd"]
        assert result["package_manager"] == "uv"
        assert result["indicator_file"] == "pyproject.toml"
        assert result["detected"] is True

    def test_setup_py(self, tmp_path):
        (tmp_path / "setup.py").write_text("from setuptools import setup\n")
        result = detect_stack(tmp_path)
        assert result["language"] == "Python"
        assert result["indicator_file"] == "setup.py"
        assert result["detected"] is True

    def test_pyproject_beats_package_json(self, tmp_path):
        """pyproject.toml has higher priority than package.json."""
        (tmp_path / "pyproject.toml").write_text("")
        (tmp_path / "package.json").write_text("{}")
        result = detect_stack(tmp_path)
        assert result["language"] == "Python"


class TestDetectStackNode:
    def test_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        result = detect_stack(tmp_path)
        assert result["language"] == "Node.js"
        assert result["validate_cmd"] == "npm test"
        assert result["package_manager"] == "npm"
        assert result["detected"] is True


class TestDetectStackRust:
    def test_cargo_toml(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]\nname = \"myapp\"\n")
        result = detect_stack(tmp_path)
        assert result["language"] == "Rust"
        assert result["validate_cmd"] == "cargo test"
        assert result["package_manager"] == "cargo"
        assert result["detected"] is True


class TestDetectStackGo:
    def test_go_mod(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/app\n")
        result = detect_stack(tmp_path)
        assert result["language"] == "Go"
        assert result["validate_cmd"] == "go test ./..."
        assert result["detected"] is True


class TestDetectStackMake:
    def test_makefile(self, tmp_path):
        (tmp_path / "Makefile").write_text("test:\n\techo ok\n")
        result = detect_stack(tmp_path)
        assert result["language"] == "Make"
        assert result["validate_cmd"] == "make test"
        assert result["detected"] is True


class TestDetectStackUnknown:
    def test_empty_dir_returns_defaults(self, tmp_path):
        result = detect_stack(tmp_path)
        assert result["detected"] is False
        assert result["language"] == "Unknown"
        assert result["indicator_file"] == ""
        # validate_cmd still has a safe default
        assert result["validate_cmd"]

    def test_project_root_recorded(self, tmp_path):
        result = detect_stack(tmp_path)
        assert str(tmp_path) in result["project_root"] or result["project_root"] == str(tmp_path)


# ---------------------------------------------------------------------------
# load_or_detect — caching
# ---------------------------------------------------------------------------

class TestLoadOrDetect:
    def test_writes_cache_file(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "pyproject.toml").write_text("")
        cache_dir = tmp_path / ".spiral"
        result = load_or_detect(proj, cache_dir)
        assert result["language"] == "Python"
        cache_file = cache_dir / "detected_stack.json"
        assert cache_file.exists()
        cached = json.loads(cache_file.read_text())
        assert cached["language"] == "Python"

    def test_returns_cached_result(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "pyproject.toml").write_text("")
        cache_dir = tmp_path / ".spiral"
        # First call — detects and caches
        r1 = load_or_detect(proj, cache_dir)
        # Remove indicator file — cached result should still be returned
        (proj / "pyproject.toml").unlink()
        r2 = load_or_detect(proj, cache_dir)
        assert r2["language"] == "Python"
        assert r1["language"] == r2["language"]

    def test_cache_invalidated_on_different_root(self, tmp_path):
        proj_a = tmp_path / "proj_a"
        proj_a.mkdir()
        (proj_a / "pyproject.toml").write_text("")

        proj_b = tmp_path / "proj_b"
        proj_b.mkdir()
        (proj_b / "Cargo.toml").write_text("")

        cache_dir = tmp_path / ".spiral"

        load_or_detect(proj_a, cache_dir)  # Caches Python for proj_a
        result = load_or_detect(proj_b, cache_dir)  # Different root → re-detect
        assert result["language"] == "Rust"

    def test_corrupt_cache_falls_back_to_detect(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "Cargo.toml").write_text("")
        cache_dir = tmp_path / ".spiral"
        cache_dir.mkdir()
        (cache_dir / "detected_stack.json").write_text("NOT JSON{{{{")
        result = load_or_detect(proj, cache_dir)
        assert result["language"] == "Rust"


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------

class TestFormatSummary:
    def test_detected_contains_lang(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        result = detect_stack(tmp_path)
        summary = format_summary(result)
        assert "Node.js" in summary
        assert "npm test" in summary

    def test_undetected_message(self, tmp_path):
        result = detect_stack(tmp_path)
        summary = format_summary(result)
        assert "No indicator" in summary or "generic" in summary
