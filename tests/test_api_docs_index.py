"""Tests for API docs index generation (US-648)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.docs.api_docs_index import generate_index


@pytest.fixture()
def sample_lib(tmp_path: Path) -> Path:
    """Create a minimal Python module tree for testing."""
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "alpha.py").write_text('"""Alpha module for testing."""\nimport os\nimport json\n', encoding="utf-8")
    (lib / "beta.py").write_text('"""Beta helper."""\nimport alpha\n', encoding="utf-8")
    (lib / "_private.py").write_text('"""Should be skipped."""\n', encoding="utf-8")
    sub = lib / "sub"
    sub.mkdir()
    (sub / "gamma.py").write_text('"""Gamma sub-module."""\nfrom pathlib import Path\n', encoding="utf-8")
    return lib


def test_index_contains_all_modules(tmp_path: Path, sample_lib: Path) -> None:
    out = tmp_path / "docs"
    idx = generate_index(str(out), scan_dirs=[str(sample_lib)])
    html = idx.read_text(encoding="utf-8")
    assert "alpha" in html
    assert "beta" in html
    assert "gamma" in html
    assert "_private" not in html


def test_index_links_are_valid(tmp_path: Path, sample_lib: Path) -> None:
    out = tmp_path / "docs"
    idx = generate_index(str(out), scan_dirs=[str(sample_lib)])
    html = idx.read_text(encoding="utf-8")
    for mod in ("alpha", "beta", "gamma"):
        assert f'href="{mod}.html"' in html


def test_search_filter_present(tmp_path: Path, sample_lib: Path) -> None:
    out = tmp_path / "docs"
    idx = generate_index(str(out), scan_dirs=[str(sample_lib)])
    html = idx.read_text(encoding="utf-8")
    assert '<input id="s"' in html
    assert "oninput" in html
    assert "function f()" in html


def test_descriptions_from_docstrings(tmp_path: Path, sample_lib: Path) -> None:
    out = tmp_path / "docs"
    idx = generate_index(str(out), scan_dirs=[str(sample_lib)])
    html = idx.read_text(encoding="utf-8")
    assert "Alpha module for testing" in html
    assert "Beta helper" in html


def test_dependencies_listed(tmp_path: Path, sample_lib: Path) -> None:
    out = tmp_path / "docs"
    idx = generate_index(str(out), scan_dirs=[str(sample_lib)])
    html = idx.read_text(encoding="utf-8")
    assert "json" in html
    assert "os" in html


def test_real_lib_modules(tmp_path: Path) -> None:
    """Integration: index.html contains actual lib/ modules."""
    root = Path(__file__).resolve().parent.parent
    lib_dir = root / "lib"
    if not lib_dir.is_dir():
        pytest.skip("lib/ not found")
    out = tmp_path / "docs"
    idx = generate_index(str(out), scan_dirs=[str(lib_dir)])
    html = idx.read_text(encoding="utf-8")
    assert "<table>" in html
    assert "analyze_results" in html
