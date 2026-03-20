"""Tests for Phase G semantic version bumping.

Tests cover:
- AC1: Parse semantic version from CHANGELOG.md
- AC2: Update both package.json and pyproject.toml
- AC3: Create version commit with [skip ci] message
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lib.phases.phase_g_version_bump import (
    bump_versions,
    create_version_commit,
    parse_version_from_changelog,
    update_package_json,
    update_pyproject_toml,
)


class TestParseVersionFromChangelog:
    """Tests for parse_version_from_changelog function."""

    def test_parse_version_with_brackets(self, tmp_path: Path) -> None:
        """AC1: Parse version from CHANGELOG.md with brackets [X.Y.Z] format."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## [1.2.3] - 2026-03-20\n\n### Features\n")

        version = parse_version_from_changelog(str(changelog))
        assert version == "1.2.3"

    def test_parse_version_without_brackets(self, tmp_path: Path) -> None:
        """Parse version from CHANGELOG.md without brackets."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## 2.0.0 - 2026-03-20\n\n### Features\n")

        version = parse_version_from_changelog(str(changelog))
        assert version == "2.0.0"

    def test_parse_version_extracts_first_entry(self, tmp_path: Path) -> None:
        """Parse version correctly extracts first version entry."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## [1.5.0]\n\n### Features\n\n## [1.4.0]\n\n### Fixes\n")

        version = parse_version_from_changelog(str(changelog))
        assert version == "1.5.0"

    def test_parse_version_missing_raises_error(self, tmp_path: Path) -> None:
        """Raise ValueError when no version found in CHANGELOG."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\nNo version here\n")

        with pytest.raises(ValueError, match="No semantic version found"):
            parse_version_from_changelog(str(changelog))

    def test_parse_version_file_missing_raises_error(self, tmp_path: Path) -> None:
        """Raise ValueError when CHANGELOG.md doesn't exist."""
        with pytest.raises(ValueError, match="CHANGELOG.md not found"):
            parse_version_from_changelog(str(tmp_path / "missing.md"))


class TestUpdatePackageJson:
    """Tests for update_package_json function."""

    def test_update_package_json_success(self, tmp_path: Path) -> None:
        """AC2: Update package.json version field."""
        package_json = tmp_path / "package.json"
        original_content: dict[str, Any] = {
            "name": "spiral-ui",
            "version": "0.0.1",
            "description": "SPIRAL Dashboard",
        }
        package_json.write_text(json.dumps(original_content, indent=2))

        update_package_json("2.3.4", str(package_json))

        updated = json.loads(package_json.read_text())
        assert updated["version"] == "2.3.4"
        assert updated["name"] == "spiral-ui"

    def test_update_package_json_file_missing_raises_error(self, tmp_path: Path) -> None:
        """Raise ValueError when package.json doesn't exist."""
        with pytest.raises(ValueError, match="package.json not found"):
            update_package_json("1.0.0", str(tmp_path / "missing.json"))

    def test_update_package_json_preserves_other_fields(self, tmp_path: Path) -> None:
        """Update version while preserving all other fields."""
        package_json = tmp_path / "package.json"
        original: dict[str, Any] = {
            "name": "spiral-ui",
            "version": "0.0.1",
            "dependencies": {"react": "^18.0"},
            "scripts": {"build": "vite build"},
        }
        package_json.write_text(json.dumps(original, indent=2))

        update_package_json("1.0.0", str(package_json))

        updated = json.loads(package_json.read_text())
        assert updated["version"] == "1.0.0"
        assert updated["dependencies"]["react"] == "^18.0"
        assert updated["scripts"]["build"] == "vite build"


class TestUpdatePyprojectToml:
    """Tests for update_pyproject_toml function."""

    def test_update_pyproject_toml_adds_version(self, tmp_path: Path) -> None:
        """AC2: Update pyproject.toml version field."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[build-system]\nrequires = ['setuptools']\n\n[tool.pytest]\ntimeout = 60\n")

        update_pyproject_toml("1.2.3", str(pyproject))

        content = pyproject.read_text()
        assert 'version = "1.2.3"' in content

    def test_update_pyproject_toml_replaces_existing_version(self, tmp_path: Path) -> None:
        """Update version field if it already exists in [project]."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[build-system]\nrequires = ["setuptools"]\n\n[project]\nversion = "0.0.1"\nname = "spiral"\n'
        )

        update_pyproject_toml("2.0.0", str(pyproject))

        content = pyproject.read_text()
        assert 'version = "2.0.0"' in content
        assert 'version = "0.0.1"' not in content

    def test_update_pyproject_toml_file_missing_raises_error(self, tmp_path: Path) -> None:
        """Raise ValueError when pyproject.toml doesn't exist."""
        with pytest.raises(ValueError, match="pyproject.toml not found"):
            update_pyproject_toml("1.0.0", str(tmp_path / "missing.toml"))


class TestCreateVersionCommit:
    """Tests for create_version_commit function."""

    @patch("subprocess.run")
    def test_create_version_commit_success(self, mock_run: MagicMock) -> None:
        """AC3: Create version commit with [skip ci] message."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        create_version_commit("1.2.3")

        # Verify git add was called
        calls = mock_run.call_args_list
        assert calls[0][0][0][:3] == ["git", "add", "spiral-ui/package.json"]

        # Verify git commit was called with correct message
        assert calls[1][0][0][:2] == ["git", "commit"]
        assert "[skip ci] chore: bump to v1.2.3" in calls[1][0][0]

    @patch("subprocess.run")
    def test_create_version_commit_git_add_fails(self, mock_run: MagicMock) -> None:
        """Raise RuntimeError if git add fails."""
        mock_run.return_value = MagicMock(returncode=1, stderr="git error")

        with pytest.raises(RuntimeError, match="Failed to stage version files"):
            create_version_commit("1.0.0")

    @patch("subprocess.run")
    def test_create_version_commit_git_commit_fails(self, mock_run: MagicMock) -> None:
        """Raise RuntimeError if git commit fails."""
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add succeeds
            MagicMock(returncode=1, stderr="commit error"),  # git commit fails
        ]

        with pytest.raises(RuntimeError, match="Failed to create version commit"):
            create_version_commit("1.0.0")


class TestBumpVersions:
    """Integration tests for bump_versions orchestrator."""

    def test_bump_versions_full_workflow(self, tmp_path: Path) -> None:
        """AC1+AC2+AC3: Full workflow - parse, update files, create commit."""
        # Setup test files
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## [3.1.4]\n\n### Features\n")

        package_json = tmp_path / "package.json"
        package_json.write_text(json.dumps({"name": "spiral-ui", "version": "0.0.0"}))

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[build-system]\nrequires = ['setuptools']\n")

        # Mock git operations
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")

            version = bump_versions(str(changelog), str(package_json), str(pyproject))

        # Verify returned version
        assert version == "3.1.4"

        # Verify package.json updated
        pkg = json.loads(package_json.read_text())
        assert pkg["version"] == "3.1.4"

        # Verify pyproject.toml updated
        toml_content = pyproject.read_text()
        assert 'version = "3.1.4"' in toml_content

    def test_bump_versions_handles_missing_changelog(self, tmp_path: Path) -> None:
        """Handle gracefully if CHANGELOG.md missing."""
        with pytest.raises(ValueError, match="CHANGELOG.md not found"):
            bump_versions(str(tmp_path / "missing.md"))

    def test_bump_versions_returns_correct_version(self, tmp_path: Path) -> None:
        """Return the extracted version from CHANGELOG."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("## [5.2.1]")

        package_json = tmp_path / "package.json"
        package_json.write_text(json.dumps({"version": "0"}))

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[build]")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = bump_versions(str(changelog), str(package_json), str(pyproject))

        assert result == "5.2.1"


class TestIntegration:
    """Integration tests against actual files."""

    def test_version_bump_with_real_files(self, tmp_path: Path) -> None:
        """Test full version bump against real temporary files."""
        # Create a realistic CHANGELOG.md
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            """# Changelog

All notable changes to SPIRAL are documented in this file.

## [2.1.0] - 2026-03-20

### Features
- Add Phase G semantic version bumping
- Auto-sync package.json and pyproject.toml

### Bug Fixes
- Fix version parsing edge cases

## [2.0.0] - 2026-03-10

### Breaking Changes
- Remove old Phase F implementation
"""
        )

        # Create package.json
        package_json = tmp_path / "package.json"
        package_json.write_text(json.dumps({"name": "spiral-ui", "version": "1.0.0"}, indent=2))

        # Create pyproject.toml
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """[build-system]
requires = ["setuptools>=45", "wheel"]

[tool.pytest]
timeout = 60
"""
        )

        # Mock git operations
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            version = bump_versions(str(changelog), str(package_json), str(pyproject))

        # Verify all updates succeeded
        assert version == "2.1.0"

        pkg_data = json.loads(package_json.read_text())
        assert pkg_data["version"] == "2.1.0"

        toml_content = pyproject.read_text()
        assert 'version = "2.1.0"' in toml_content
