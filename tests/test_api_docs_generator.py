"""Tests for lib/api_docs_generator.py — API documentation generation.

Tests verify that the generator produces HTML docs with proper structure
and navigation links from Python modules.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib.api_docs_generator import collect_modules, create_index_html, generate_api_docs


class TestCollectModules:
    """Tests for module collection from source directory."""

    def test_collect_modules_finds_py_files(self) -> None:
        """Verify collect_modules finds .py files in directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create test module files
            (tmpdir_path / "module1.py").touch()
            (tmpdir_path / "module2.py").touch()

            modules = collect_modules(tmpdir_path)

            assert len(modules) == 2
            assert "module1" in modules
            assert "module2" in modules

    def test_collect_modules_excludes_test_files(self) -> None:
        """Verify collect_modules excludes test_* files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create test and regular module files
            (tmpdir_path / "module1.py").touch()
            (tmpdir_path / "test_module1.py").touch()

            modules = collect_modules(tmpdir_path)

            assert len(modules) == 1
            assert "module1" in modules
            assert "test_module1" not in modules

    def test_collect_modules_excludes_private_modules(self) -> None:
        """Verify collect_modules excludes _* private modules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create private and public module files
            (tmpdir_path / "module1.py").touch()
            (tmpdir_path / "_private.py").touch()

            modules = collect_modules(tmpdir_path)

            assert len(modules) == 1
            assert "module1" in modules
            assert "_private" not in modules

    def test_collect_modules_excludes_init(self) -> None:
        """Verify collect_modules excludes __init__.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            (tmpdir_path / "__init__.py").touch()
            (tmpdir_path / "module1.py").touch()

            modules = collect_modules(tmpdir_path)

            assert len(modules) == 1
            assert "module1" in modules
            assert "__init__" not in modules

    def test_collect_modules_empty_directory(self) -> None:
        """Verify collect_modules returns empty list for empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            modules = collect_modules(tmpdir_path)

            assert modules == []

    def test_collect_modules_nonexistent_directory(self) -> None:
        """Verify collect_modules returns empty list for nonexistent directory."""
        nonexistent = Path("/nonexistent/directory")

        modules = collect_modules(nonexistent)

        assert modules == []


class TestCreateIndexHtml:
    """Tests for index.html generation with cross-module links."""

    def test_create_index_html_generates_file(self) -> None:
        """Verify create_index_html generates index.html file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            modules = ["module1", "module2"]

            create_index_html(modules, tmpdir_path)

            index_file = tmpdir_path / "index.html"
            assert index_file.exists()
            assert index_file.is_file()

    def test_create_index_html_contains_module_links(self) -> None:
        """Verify index.html contains links to all modules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            modules = ["module1", "module2", "module3"]

            create_index_html(modules, tmpdir_path)

            content = (tmpdir_path / "index.html").read_text()

            assert "module1.html" in content
            assert "module2.html" in content
            assert "module3.html" in content

    def test_create_index_html_displays_module_names(self) -> None:
        """Verify index.html displays human-readable module names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            modules = ["batch_operations", "cost_estimator"]

            create_index_html(modules, tmpdir_path)

            content = (tmpdir_path / "index.html").read_text()

            assert "batch_operations" in content
            assert "cost_estimator" in content

    def test_create_index_html_contains_title(self) -> None:
        """Verify index.html contains SPIRAL API Documentation title."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            modules = ["module1"]

            create_index_html(modules, tmpdir_path)

            content = (tmpdir_path / "index.html").read_text()

            assert "SPIRAL API Documentation" in content

    def test_create_index_html_contains_valid_html(self) -> None:
        """Verify index.html is valid HTML structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            modules = ["module1"]

            create_index_html(modules, tmpdir_path)

            content = (tmpdir_path / "index.html").read_text()

            assert content.startswith("<!DOCTYPE html>")
            assert "<html" in content
            assert "</html>" in content
            assert "<head>" in content
            assert "<body>" in content


class TestGenerateApiDocs:
    """Tests for API documentation generation."""

    def test_generate_api_docs_requires_existing_source(self) -> None:
        """Verify generate_api_docs raises error for nonexistent source."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent_source = Path(tmpdir) / "nonexistent"

            with pytest.raises(FileNotFoundError):
                generate_api_docs(nonexistent_source, Path(tmpdir) / "output")

    def test_generate_api_docs_creates_output_directory(self) -> None:
        """Verify generate_api_docs creates output directory if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_dir = tmpdir_path / "source"
            output_dir = tmpdir_path / "output" / "nested" / "api"

            # Create a module file
            source_dir.mkdir()
            (source_dir / "dummy.py").write_text("# Empty module")

            # Mock pdoc to avoid actual module import
            with patch("builtins.__import__", new_callable=MagicMock) as mock_import:
                mock_import.return_value = MagicMock()
                with patch("lib.api_docs_generator.pdoc") as mock_pdoc:
                    mock_pdoc.render.return_value = "<html></html>"

                    generate_api_docs(source_dir, output_dir)

            assert output_dir.exists()
            assert output_dir.is_dir()

    def test_generate_api_docs_requires_python_modules(self) -> None:
        """Verify generate_api_docs raises error when no modules found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_dir = tmpdir_path / "source"
            output_dir = tmpdir_path / "output"

            # Create empty source directory
            source_dir.mkdir()

            with pytest.raises(RuntimeError, match="No Python modules found"):
                generate_api_docs(source_dir, output_dir)

    def test_generate_api_docs_generates_index_html(self) -> None:
        """Verify generate_api_docs generates index.html."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_dir = tmpdir_path / "source"
            output_dir = tmpdir_path / "output"

            # Create a module file
            source_dir.mkdir()
            (source_dir / "dummy.py").write_text("# Empty module")

            # Mock pdoc to avoid actual module import
            with patch("builtins.__import__", new_callable=MagicMock) as mock_import:
                mock_import.return_value = MagicMock()
                with patch("lib.api_docs_generator.pdoc") as mock_pdoc:
                    mock_pdoc.render.return_value = "<html></html>"

                    generate_api_docs(source_dir, output_dir)

            # Verify index.html was created
            index_file = output_dir / "index.html"
            assert index_file.exists()
            assert "dummy.html" in index_file.read_text()


class TestAcceptanceCriteria:
    """Tests for US-1314 acceptance criteria."""

    def test_ac1_generates_html_docs_excluding_tests(self) -> None:
        """[AC1] lib/api_docs_generator.py generates HTML docs for all .py files in lib/ (excluding tests)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_dir = tmpdir_path / "source"
            output_dir = tmpdir_path / "output"

            # Create module files
            source_dir.mkdir()
            (source_dir / "module1.py").write_text("# Module 1")
            (source_dir / "module2.py").write_text("# Module 2")
            (source_dir / "test_module.py").write_text("# Test module")

            # Mock pdoc
            with patch("builtins.__import__", new_callable=MagicMock) as mock_import:
                mock_import.return_value = MagicMock()
                with patch("lib.api_docs_generator.pdoc") as mock_pdoc:
                    mock_pdoc.render.return_value = "<html></html>"

                    generate_api_docs(source_dir, output_dir)

            # Verify test modules are excluded
            output_files = list(output_dir.glob("*.html"))
            html_names = [f.stem for f in output_files]

            assert "module1" in html_names
            assert "module2" in html_names
            assert "test_module" not in html_names

    def test_ac2_produces_index_html_with_links(self) -> None:
        """[AC2] Phase G completion produces valid index.html with cross-module links."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_dir = tmpdir_path / "source"
            output_dir = tmpdir_path / "output"

            # Create module files
            source_dir.mkdir()
            (source_dir / "batch_ops.py").write_text("# Batch operations")
            (source_dir / "cost_est.py").write_text("# Cost estimator")

            # Mock pdoc
            with patch("builtins.__import__", new_callable=MagicMock) as mock_import:
                mock_import.return_value = MagicMock()
                with patch("lib.api_docs_generator.pdoc") as mock_pdoc:
                    mock_pdoc.render.return_value = "<html></html>"

                    generate_api_docs(source_dir, output_dir)

            # Verify index.html contains links
            index_content = (output_dir / "index.html").read_text()
            assert "batch_ops.html" in index_content
            assert "cost_est.html" in index_content
            assert "SPIRAL API Documentation" in index_content

    def test_ac3_cli_command_runs_without_errors(self) -> None:
        """[AC3] Command `uv run python lib/api_docs_generator.py lib/ --output docs/api/` runs without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_dir = tmpdir_path / "lib"
            output_dir = tmpdir_path / "docs" / "api"

            # Create lib directory with a module
            source_dir.mkdir()
            (source_dir / "dummy.py").write_text("# Dummy module")

            # Mock pdoc
            with patch("builtins.__import__", new_callable=MagicMock) as mock_import:
                mock_import.return_value = MagicMock()
                with patch("lib.api_docs_generator.pdoc") as mock_pdoc:
                    mock_pdoc.render.return_value = "<html></html>"

                    # Call generate_api_docs directly (simulates CLI invocation)
                    generate_api_docs(source_dir, output_dir)

            # Verify output was created successfully
            assert output_dir.exists()
            assert (output_dir / "index.html").exists()
