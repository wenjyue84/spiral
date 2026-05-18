"""tests/test_validate_changelog.py — CHANGELOG.md Markdown & Link Validation Tests (US-1403).

Tests for lib/validate_changelog.py validation functions.
Tests syntax validation, story ID link checking, and file link validation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lib.validate_changelog import (
    validate_all,
    validate_changelog_links,
    validate_changelog_markdown,
)


@pytest.fixture
def tmp_changelog(tmp_path: Path) -> Path:
    """Create temporary CHANGELOG.md for testing."""
    changelog = tmp_path / "CHANGELOG.md"
    return changelog


@pytest.fixture
def tmp_prd(tmp_path: Path) -> Path:
    """Create temporary prd.json for testing."""
    prd_file = tmp_path / "prd.json"
    return prd_file


@pytest.fixture
def valid_prd_data() -> dict[str, Any]:
    """Valid prd.json with completed stories."""
    return {
        "userStories": [
            {"id": "US-1000", "title": "Story 1", "passes": True},
            {"id": "US-1001", "title": "Story 2", "passes": True},
            {"id": "US-1234", "title": "Story 3", "passes": True},
            {"id": "US-9999", "title": "Story 4", "passes": False},  # Not completed
        ]
    }


class TestValidateMarkdownSyntax:
    """Tests for validate_changelog_markdown()."""

    def test_valid_markdown(self, tmp_changelog: Path) -> None:
        """Valid Markdown passes syntax check."""
        tmp_changelog.write_text(
            """# Changelog

## v1.0.0: Initial Release

- Feature 1
- Feature 2

## v0.9.0: Beta

- Beta feature
""",
            encoding="utf-8",
        )

        result = validate_changelog_markdown(tmp_changelog)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_unclosed_code_block(self, tmp_changelog: Path) -> None:
        """Unclosed code block is detected."""
        tmp_changelog.write_text(
            """# Changelog

## v1.0.0: Release

```python
def hello():
    pass
""",
            encoding="utf-8",
        )

        result = validate_changelog_markdown(tmp_changelog)
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert result["errors"][0]["error_type"] == "syntax"
        assert "Unclosed code block" in result["errors"][0]["message"]

    def test_missing_changelog(self, tmp_path: Path) -> None:
        """Missing CHANGELOG.md is reported."""
        missing_file = tmp_path / "MISSING.md"

        result = validate_changelog_markdown(missing_file)
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert result["errors"][0]["error_type"] == "syntax"
        assert "not found" in result["errors"][0]["message"].lower()

    def test_invalid_link_syntax(self, tmp_changelog: Path) -> None:
        """Invalid link syntax is detected."""
        tmp_changelog.write_text(
            """# Changelog

This is a [bad link](<invalid<>>.md)
""",
            encoding="utf-8",
        )

        result = validate_changelog_markdown(tmp_changelog)
        assert result["valid"] is False
        assert any("Invalid link syntax" in e["message"] for e in result["errors"])


class TestValidateLinks:
    """Tests for validate_changelog_links()."""

    def test_detects_missing_story_id(self, tmp_changelog: Path, tmp_prd: Path, valid_prd_data: dict[str, Any]) -> None:
        """Missing story IDs are detected."""
        tmp_changelog.write_text(
            """# Changelog

Implemented US-1000 and US-9999 with support for #US-1234.
""",
            encoding="utf-8",
        )
        tmp_prd.write_text(json.dumps(valid_prd_data), encoding="utf-8")

        result = validate_changelog_links(tmp_changelog, tmp_prd, git_root=tmp_prd.parent)
        assert result["valid"] is False
        assert any(e["error_type"] == "missing_story" for e in result["errors"])
        # US-9999 has passes: false, should be reported as missing
        assert any("US-9999" in e["message"] for e in result["errors"])

    def test_valid_story_ids(self, tmp_changelog: Path, tmp_prd: Path, valid_prd_data: dict[str, Any]) -> None:
        """Valid story IDs pass validation."""
        tmp_changelog.write_text(
            """# Changelog

Implemented #US-1000 and @story:US-1001 plus [US-1234] support.
""",
            encoding="utf-8",
        )
        tmp_prd.write_text(json.dumps(valid_prd_data), encoding="utf-8")

        result = validate_changelog_links(tmp_changelog, tmp_prd, git_root=tmp_prd.parent)
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["link_count_checked"] >= 3

    def test_broken_file_link(self, tmp_changelog: Path, tmp_prd: Path, tmp_path: Path) -> None:
        """Broken file links are detected."""
        tmp_changelog.write_text(
            """# Changelog

See [README](MISSING.md) for details.
""",
            encoding="utf-8",
        )
        tmp_prd.write_text(json.dumps({"userStories": []}), encoding="utf-8")

        result = validate_changelog_links(tmp_changelog, tmp_prd, git_root=tmp_path)
        assert result["valid"] is False
        assert any(e["error_type"] == "broken_link" for e in result["errors"])
        assert any("MISSING.md" in e["message"] for e in result["errors"])

    def test_valid_file_link(self, tmp_changelog: Path, tmp_prd: Path, tmp_path: Path) -> None:
        """Valid file links pass validation."""
        # Create an actual file
        readme = tmp_path / "README.md"
        readme.write_text("# README")

        tmp_changelog.write_text(
            """# Changelog

See [README](README.md) for details.
""",
            encoding="utf-8",
        )
        tmp_prd.write_text(json.dumps({"userStories": []}), encoding="utf-8")

        result = validate_changelog_links(tmp_changelog, tmp_prd, git_root=tmp_path)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_http_links_skipped(
        self, tmp_changelog: Path, tmp_prd: Path, valid_prd_data: dict[str, Any], tmp_path: Path
    ) -> None:
        """HTTP/HTTPS links are not validated."""
        tmp_changelog.write_text(
            """# Changelog

See [docs](https://example.com/docs) and [api](http://example.com/api) for info.
""",
            encoding="utf-8",
        )
        tmp_prd.write_text(json.dumps(valid_prd_data), encoding="utf-8")

        result = validate_changelog_links(tmp_changelog, tmp_prd, git_root=tmp_path)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_missing_prd(self, tmp_changelog: Path, tmp_path: Path) -> None:
        """Missing prd.json is reported."""
        tmp_changelog.write_text("# Changelog\n", encoding="utf-8")
        missing_prd = tmp_path / "MISSING.json"

        result = validate_changelog_links(tmp_changelog, missing_prd, git_root=tmp_path)
        assert result["valid"] is False
        assert any("prd.json not found" in e["message"] for e in result["errors"])

    def test_link_count_tracked(
        self, tmp_changelog: Path, tmp_prd: Path, valid_prd_data: dict[str, Any], tmp_path: Path
    ) -> None:
        """Link count is properly tracked."""
        tmp_changelog.write_text(
            """# Changelog

Story #US-1000 with [US-1001] and link [docs](docs.md).
""",
            encoding="utf-8",
        )
        tmp_prd.write_text(json.dumps(valid_prd_data), encoding="utf-8")

        result = validate_changelog_links(tmp_changelog, tmp_prd, git_root=tmp_path)
        # Should count 2 story IDs + 1 file link = 3
        assert result["link_count_checked"] >= 3


class TestValidateAll:
    """Tests for validate_all() complete validation."""

    def test_success_writes_validation_file(
        self,
        tmp_changelog: Path,
        tmp_prd: Path,
        valid_prd_data: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """Successful validation writes metadata file."""
        scratch_dir = tmp_path / ".spiral"
        tmp_changelog.write_text(
            """# Changelog

## v1.0.0: Release

Fixed #US-1000 and US-1234.
""",
            encoding="utf-8",
        )
        tmp_prd.write_text(json.dumps(valid_prd_data), encoding="utf-8")

        success = validate_all(
            tmp_changelog,
            tmp_prd,
            git_root=tmp_path,
            scratch_dir=scratch_dir,
        )

        assert success is True
        validation_file = scratch_dir / "_changelog_validation.json"
        assert validation_file.exists()

        with validation_file.open(encoding="utf-8") as f:
            result = json.load(f)

        assert result["status"] == "pass"
        assert result["file"] == "CHANGELOG.md"
        assert "timestamp" in result
        assert "checks_performed" in result
        assert "syntax" in result["checks_performed"]
        assert "story_links" in result["checks_performed"]
        assert "file_links" in result["checks_performed"]
        assert result["link_count_checked"] >= 2
        assert result["error_count"] == 0

    def test_failure_writes_errors(
        self,
        tmp_changelog: Path,
        tmp_prd: Path,
        valid_prd_data: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """Failed validation includes errors in metadata."""
        scratch_dir = tmp_path / ".spiral"
        tmp_changelog.write_text(
            """# Changelog

Unclosed code block:
```python
def hello():
    pass
""",
            encoding="utf-8",
        )
        tmp_prd.write_text(json.dumps(valid_prd_data), encoding="utf-8")

        success = validate_all(
            tmp_changelog,
            tmp_prd,
            git_root=tmp_path,
            scratch_dir=scratch_dir,
        )

        assert success is False
        validation_file = scratch_dir / "_changelog_validation.json"
        assert validation_file.exists()

        with validation_file.open(encoding="utf-8") as f:
            result = json.load(f)

        assert result["status"] == "fail"
        assert result["error_count"] > 0
        assert "errors" in result

    def test_creates_scratch_directory(self, tmp_changelog: Path, tmp_prd: Path, tmp_path: Path) -> None:
        """Scratch directory is created if missing."""
        scratch_dir = tmp_path / ".spiral"
        assert not scratch_dir.exists()

        tmp_changelog.write_text("# Changelog\n", encoding="utf-8")
        tmp_prd.write_text(json.dumps({"userStories": []}), encoding="utf-8")

        validate_all(
            tmp_changelog,
            tmp_prd,
            git_root=tmp_path,
            scratch_dir=scratch_dir,
        )

        assert scratch_dir.exists()

    def test_validation_includes_line_numbers(
        self,
        tmp_changelog: Path,
        tmp_prd: Path,
        valid_prd_data: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """Error reports include line numbers for debugging."""
        scratch_dir = tmp_path / ".spiral"
        tmp_changelog.write_text(
            """# Changelog

Line 3: Reference to missing story #US-9999
""",
            encoding="utf-8",
        )
        tmp_prd.write_text(json.dumps(valid_prd_data), encoding="utf-8")

        success = validate_all(
            tmp_changelog,
            tmp_prd,
            git_root=tmp_path,
            scratch_dir=scratch_dir,
        )

        assert success is False
        validation_file = scratch_dir / "_changelog_validation.json"
        with validation_file.open(encoding="utf-8") as f:
            result = json.load(f)

        assert any(e.get("line_number") == 3 for e in result.get("errors", []))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
