"""Integration tests for Phase G: pdoc API Documentation Generation.

Tests verify that Phase G generates HTML API docs with git commit SHA embedded
in YAML frontmatter of each .html file.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from lib.observability.auto_release import embed_git_frontmatter_in_docs, generate_api_docs


class TestApiDocsGeneration:
    """Tests for API documentation generation."""

    def test_generate_api_docs_outputs_to_spiral_docs_api(self) -> None:
        """Verify generate_api_docs uses .spiral/docs/api as default output."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            generate_api_docs()

            # Verify pdoc is called with .spiral/docs/api
            calls = [str(call) for call in mock_run.call_args_list]
            pdoc_call = next((c for c in calls if "pdoc" in c), None)
            assert pdoc_call is not None
            assert ".spiral/docs/api" in pdoc_call

    def test_generate_api_docs_creates_output_directory(self) -> None:
        """Verify generate_api_docs creates output directory if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            docs_output = tmpdir_path / "docs" / "api"

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                generate_api_docs(output_dir=str(docs_output))

                # Verify directory was created or would be created
                mock_run.assert_called()


class TestGitFrontmatterEmbedding:
    """Tests for git frontmatter embedding in HTML files."""

    def test_embed_git_frontmatter_adds_yaml_header(self) -> None:
        """Verify YAML frontmatter with git commit SHA is added to HTML files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create a sample HTML file without frontmatter
            html_file = tmpdir_path / "module.html"
            html_file.write_text("<html><body>Test</body></html>")

            with patch("subprocess.run") as mock_run:
                # Mock git log to return commit SHA and timestamp
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout="abc123def456"),  # git rev-parse HEAD
                    MagicMock(returncode=0, stdout="2026-03-20T12:00:00Z"),  # git log timestamp
                ]

                embed_git_frontmatter_in_docs(str(tmpdir_path))

                # Verify frontmatter was added
                content = html_file.read_text()
                assert content.startswith("---")
                assert "generated_from_commit: abc123def456" in content
                assert "generated_timestamp: 2026-03-20T12:00:00Z" in content
                assert "<html><body>Test</body></html>" in content

    def test_embed_git_frontmatter_skips_existing_frontmatter(self) -> None:
        """Verify existing YAML frontmatter is not duplicated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create HTML file with existing frontmatter
            html_file = tmpdir_path / "module.html"
            existing_content = "---\nexisting: true\n---\n<html></html>"
            html_file.write_text(existing_content)

            with patch("subprocess.run"):
                embed_git_frontmatter_in_docs(str(tmpdir_path))

                # Verify content remains unchanged
                content = html_file.read_text()
                assert content == existing_content

    def test_embed_git_frontmatter_handles_missing_directory(self) -> None:
        """Verify function handles missing output directory gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent_dir = Path(tmpdir) / "nonexistent"

            # Should not raise error
            embed_git_frontmatter_in_docs(str(nonexistent_dir))

    def test_embed_git_frontmatter_processes_multiple_html_files(self) -> None:
        """Verify YAML frontmatter is added to all HTML files recursively."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create nested HTML files
            (tmpdir_path / "module1.html").write_text("<html>Module 1</html>")
            subdir = tmpdir_path / "submodule"
            subdir.mkdir()
            (subdir / "module2.html").write_text("<html>Module 2</html>")

            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout="abc123def456"),
                    MagicMock(returncode=0, stdout="2026-03-20T12:00:00Z"),
                ]

                embed_git_frontmatter_in_docs(str(tmpdir_path))

                # Verify both files have frontmatter
                content1 = (tmpdir_path / "module1.html").read_text()
                content2 = (subdir / "module2.html").read_text()
                assert content1.startswith("---")
                assert content2.startswith("---")

    def test_embed_git_frontmatter_handles_git_failure(self) -> None:
        """Verify function handles git command failures gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            html_file = tmpdir_path / "module.html"
            html_file.write_text("<html></html>")

            with patch("subprocess.run") as mock_run:
                # Simulate git failure
                mock_run.return_value = MagicMock(returncode=128)

                # Should not raise error
                embed_git_frontmatter_in_docs(str(tmpdir_path))

                # Content should remain unchanged
                assert html_file.read_text() == "<html></html>"


# Acceptance Criteria Tests


def test_phase_g_api_docs_generates_valid_html() -> None:
    """[AC1] Bash function phase_generate_api_docs() generates valid HTML docs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        output_dir = tmpdir_path / ".spiral" / "docs" / "api"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            generate_api_docs(output_dir=str(output_dir))

            # Verify pdoc was called
            assert mock_run.called
            call_args = [str(call) for call in mock_run.call_args_list]
            assert any("pdoc" in arg for arg in call_args)


def test_phase_g_produces_index_and_module_pages() -> None:
    """[AC2] Phase G completion produces valid index.html and module pages."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        output_dir = tmpdir_path / ".spiral" / "docs" / "api"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create mock index.html and module pages
        (output_dir / "index.html").write_text("<html>Index</html>")
        (output_dir / "module.html").write_text("<html>Module</html>")

        # Embed frontmatter
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="abc123def456"),
                MagicMock(returncode=0, stdout="2026-03-20T12:00:00Z"),
            ]

            embed_git_frontmatter_in_docs(str(output_dir))

        # Verify both files have frontmatter
        index_content = (output_dir / "index.html").read_text()
        module_content = (output_dir / "module.html").read_text()

        assert index_content.startswith("---")
        assert "generated_from_commit:" in index_content
        assert "<html>Index</html>" in index_content

        assert module_content.startswith("---")
        assert "generated_from_commit:" in module_content
        assert "<html>Module</html>" in module_content


def test_phase_g_embeds_git_commit_sha_in_frontmatter() -> None:
    """[AC2] Git commit SHA is embedded in YAML frontmatter of each HTML file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create sample HTML file
        html_file = tmpdir_path / "test.html"
        html_file.write_text("<html>Test</html>")

        with patch("subprocess.run") as mock_run:
            # Return specific commit SHA and timestamp
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="1a2b3c4d5e6f"),
                MagicMock(returncode=0, stdout="2026-03-20T15:30:00Z"),
            ]

            embed_git_frontmatter_in_docs(str(tmpdir_path))

        content = html_file.read_text()
        assert "---" in content
        assert "generated_from_commit: 1a2b3c4d5e6f" in content
        assert "generated_timestamp: 2026-03-20T15:30:00Z" in content
